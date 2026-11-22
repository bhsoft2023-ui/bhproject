"""المبيعات النقدية والآجلة: الحساب، FEFO، خصم المخزون، والسقف الائتماني — في معاملة واحدة."""
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal

from ..db import now_str, transaction
from ..errors import CreditLimitExceeded, NotFoundError, ValidationError
from ..money import fmt_money, int_to_money, line_total_int, money_to_int
from . import inventory
from .auth import require


@dataclass
class CartLine:
    product_id: int
    qty: Decimal


def customer_balance_int(conn, customer_id) -> int:
    row = conn.execute("SELECT balance FROM customer_balances WHERE customer_id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFoundError("العميل غير موجود")
    return row["balance"]


def check_credit_limit(conn, customer_id, new_debt_int: int) -> None:
    """يمنع البيع الآجل إذا كان (الرصيد الحالي + الدين الجديد) يتجاوز السقف الائتماني."""
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if customer is None:
        raise NotFoundError("العميل غير موجود")
    if not customer["active"]:
        raise ValidationError("حساب العميل موقوف")
    if new_debt_int <= 0:
        return
    balance = customer_balance_int(conn, customer_id)
    limit = customer["credit_limit"]
    if balance + new_debt_int > limit:
        available = max(limit - balance, 0)
        raise CreditLimitExceeded(
            f"تجاوز السقف الائتماني للعميل «{customer['name']}».\n"
            f"السقف: {fmt_money(int_to_money(limit))} | الدين الحالي: {fmt_money(int_to_money(balance))}"
            f" | المتاح: {fmt_money(int_to_money(available))} | المطلوب: {fmt_money(int_to_money(new_debt_int))}"
        )


def _merge_lines(lines):
    merged = OrderedDict()
    for line in lines:
        pid = int(line.product_id)
        merged[pid] = merged.get(pid, Decimal(0)) + Decimal(line.qty)
    return merged


def create_sale(conn, user, lines, sale_type="cash", customer_id=None, paid=None, today=None, created_at=None) -> int:
    """تسجيل فاتورة بيع. السعر يُؤخذ من قاعدة البيانات وقت البيع.

    sale_type: 'cash' أو 'credit'. في الآجل يمكن دفع جزء مقدم (paid)، والباقي دين على العميل.
    """
    if sale_type not in ("cash", "credit"):
        raise ValidationError("نوع البيع غير صالح")
    require(user, "sale.cash" if sale_type == "cash" else "sale.credit")
    if not lines:
        raise ValidationError("الفاتورة فارغة")
    if sale_type == "credit" and not customer_id:
        raise ValidationError("اختر العميل للبيع الآجل")

    with transaction(conn):
        items, total, cost_total = [], 0, 0
        for product_id, q in _merge_lines(lines).items():
            product = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)).fetchone()
            if product is None:
                raise NotFoundError("صنف غير موجود أو موقوف")
            qty_int = inventory.validate_qty_for_product(product, q)
            allocations = inventory.allocate_fefo(conn, product_id, qty_int, today)
            lt = line_total_int(qty_int, product["sell_price"])
            cost = sum(line_total_int(a.qty, a.unit_cost) for a in allocations)
            items.append((product, qty_int, lt, cost, allocations))
            total += lt
            cost_total += cost

        if sale_type == "cash":
            paid_int = total
        else:
            paid_int = money_to_int(paid or 0)
            if paid_int < 0 or paid_int > total:
                raise ValidationError("المبلغ المدفوع مقدماً يجب أن يكون بين صفر وإجمالي الفاتورة")
            check_credit_limit(conn, customer_id, total - paid_int)

        cur = conn.execute(
            "INSERT INTO sales (sale_type, customer_id, user_id, total, paid, cost_total, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sale_type, customer_id if sale_type == "credit" else None, user.id, total, paid_int, cost_total,
             created_at or now_str()),
        )
        sale_id = cur.lastrowid
        for product, qty_int, lt, cost, allocations in items:
            inventory.consume(conn, allocations)
            item_id = conn.execute(
                "INSERT INTO sale_items (sale_id, product_id, product_name, unit, qty, unit_price, line_total, cost_total)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sale_id, product["id"], product["name"], product["unit"], qty_int, product["sell_price"], lt, cost),
            ).lastrowid
            conn.executemany(
                "INSERT INTO sale_item_batches (sale_item_id, batch_id, qty, unit_cost) VALUES (?, ?, ?, ?)",
                [(item_id, a.batch_id, a.qty, a.unit_cost) for a in allocations],
            )
    return sale_id


def preview_total(conn, lines) -> Decimal:
    total = 0
    for product_id, q in _merge_lines(lines).items():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        total += line_total_int(inventory.validate_qty_for_product(product, q), product["sell_price"])
    return int_to_money(total)


def get_sale(conn, sale_id):
    sale = conn.execute(
        "SELECT s.*, c.name AS customer_name, u.full_name AS user_full_name, u.username FROM sales s"
        " LEFT JOIN customers c ON c.id = s.customer_id JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sale_id,),
    ).fetchone()
    if sale is None:
        raise NotFoundError("الفاتورة غير موجودة")
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)).fetchall()
    return sale, items


def list_sales(conn, date_from: str, date_to: str, sale_type=None):
    sql = (
        "SELECT s.*, c.name AS customer_name, u.username FROM sales s"
        " LEFT JOIN customers c ON c.id = s.customer_id JOIN users u ON u.id = s.user_id"
        " WHERE date(s.created_at) BETWEEN ? AND ?"
    )
    params = [date_from, date_to]
    if sale_type:
        sql += " AND s.sale_type = ?"
        params.append(sale_type)
    return conn.execute(sql + " ORDER BY s.id DESC", params).fetchall()
