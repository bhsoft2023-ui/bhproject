"""المشتريات من الموردين (نقداً أو آجلاً) — تُضيف دفعات للمخزون بتواريخ الصلاحية."""
from dataclasses import dataclass
from decimal import Decimal

from ..db import now_str, transaction
from ..errors import NotFoundError, ValidationError
from ..money import line_total, money, money_to_int
from . import inventory
from .auth import require


@dataclass
class PurchaseLine:
    product_id: int
    qty: Decimal
    unit_cost: Decimal
    expiry_date: str = None


def create_purchase(conn, user, lines, purchase_type="cash", supplier_id=None, paid=None, note="") -> int:
    require(user, "purchase.manage")
    if purchase_type not in ("cash", "credit"):
        raise ValidationError("نوع الشراء غير صالح")
    if not lines:
        raise ValidationError("فاتورة الشراء فارغة")
    if purchase_type == "credit" and not supplier_id:
        raise ValidationError("اختر المورد للشراء الآجل")
    total = sum((line_total(l.qty, l.unit_cost) for l in lines), Decimal(0))
    paid_amt = total if purchase_type == "cash" else money(paid or 0)
    if paid_amt < 0 or paid_amt > total:
        raise ValidationError("المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة")
    with transaction(conn):
        if supplier_id and not conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone():
            raise NotFoundError("المورد غير موجود")
        ts = now_str()
        pid = conn.execute(
            "INSERT INTO purchases (supplier_id, purchase_type, total, paid, note, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (supplier_id, purchase_type, money_to_int(total), money_to_int(paid_amt), (note or "").strip(), user.id, ts),
        ).lastrowid
        for l in lines:
            inventory.add_batch(conn, l.product_id, l.qty, l.unit_cost, l.expiry_date, purchase_id=pid, received_at=ts)
    return pid


def list_purchases(conn, date_from, date_to):
    return conn.execute(
        "SELECT pu.*, s.name AS supplier_name FROM purchases pu LEFT JOIN suppliers s ON s.id = pu.supplier_id"
        " WHERE date(pu.created_at) BETWEEN ? AND ? ORDER BY pu.id DESC",
        (date_from, date_to),
    ).fetchall()
