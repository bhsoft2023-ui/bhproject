"""المخزون بالدفعات: الصلاحية، FEFO، الإتلاف والتسوية."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..db import now_str, transaction
from ..errors import InsufficientStock, NotFoundError, ValidationError
from ..money import fmt_qty, int_to_qty, money, money_to_int, qty, qty_to_int
from .auth import require


@dataclass
class Allocation:
    batch_id: int
    qty: int  # بوحدة 1/1000
    unit_cost: int  # بوحدة 1/100


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValidationError(f"تاريخ غير صالح: {value} (الصيغة YYYY-MM-DD)")


def validate_qty_for_product(product, quantity) -> int:
    q = qty(quantity)
    if q <= 0:
        raise ValidationError("الكمية يجب أن تكون أكبر من صفر")
    if not product["is_weighted"] and q != q.to_integral_value():
        raise ValidationError(f"الصنف «{product['name']}» لا يُباع بالوزن، والكمية يجب أن تكون عدداً صحيحاً")
    return qty_to_int(q)


def add_batch(conn, product_id, quantity, unit_cost, expiry_date=None, purchase_id=None, received_at=None) -> int:
    """إضافة دفعة (يجب استدعاؤها داخل transaction)."""
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        raise NotFoundError("الصنف غير موجود")
    q = validate_qty_for_product(product, quantity)
    cost = money(unit_cost or 0)
    if cost < 0:
        raise ValidationError("التكلفة لا يمكن أن تكون سالبة")
    expiry = parse_date(expiry_date)
    if product["track_expiry"] and not expiry:
        raise ValidationError(f"الصنف «{product['name']}» يتطلب تاريخ انتهاء")
    cur = conn.execute(
        "INSERT INTO batches (product_id, purchase_id, qty_received, qty_remaining, unit_cost, expiry_date, received_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, purchase_id, q, q, money_to_int(cost), expiry, received_at or now_str()),
    )
    if cost > 0:
        conn.execute("UPDATE products SET cost_price = ? WHERE id = ?", (money_to_int(cost), product_id))
    return cur.lastrowid


def add_opening_stock(conn, user, product_id, quantity, unit_cost, expiry_date=None) -> int:
    """رصيد افتتاحي أو زيادة جرد بدون مورد."""
    require(user, "inventory.manage")
    with transaction(conn):
        return add_batch(conn, product_id, quantity, unit_cost, expiry_date)


def allocate_fefo(conn, product_id, qty_int: int, today=None):
    """يحدد الدفعات التي ستُصرف: الأقرب انتهاءً أولاً، ثم الدفعات بلا تاريخ انتهاء حسب الأقدم استلاماً.
    الدفعات المنتهية لا تُباع."""
    if qty_int <= 0:
        raise ValidationError("الكمية يجب أن تكون أكبر من صفر")
    today = parse_date(today) or date.today().isoformat()
    rows = conn.execute(
        "SELECT id, qty_remaining, unit_cost, expiry_date FROM batches"
        " WHERE product_id = ? AND qty_remaining > 0 AND (expiry_date IS NULL OR expiry_date >= ?)"
        " ORDER BY expiry_date IS NULL, expiry_date, received_at, id",
        (product_id, today),
    ).fetchall()
    allocations, needed = [], qty_int
    for row in rows:
        if needed <= 0:
            break
        take = min(needed, row["qty_remaining"])
        allocations.append(Allocation(row["id"], take, row["unit_cost"]))
        needed -= take
    if needed > 0:
        product = conn.execute("SELECT name, unit FROM products WHERE id = ?", (product_id,)).fetchone()
        available = qty_int - needed
        expired = conn.execute(
            "SELECT COALESCE(SUM(qty_remaining),0) FROM batches WHERE product_id = ? AND expiry_date < ?",
            (product_id, today),
        ).fetchone()[0]
        msg = (
            f"الكمية غير متوفرة للصنف «{product['name']}». المطلوب {fmt_qty(int_to_qty(qty_int))}"
            f"، المتاح للبيع {fmt_qty(int_to_qty(available))} {product['unit']}"
        )
        if expired:
            msg += f" (يوجد {fmt_qty(int_to_qty(expired))} منتهي الصلاحية لا يُباع)"
        raise InsufficientStock(msg)
    return allocations


def consume(conn, allocations) -> None:
    """خصم الكميات من الدفعات (داخل transaction). يفشل إن تغير الرصيد أثناء العملية."""
    for a in allocations:
        cur = conn.execute(
            "UPDATE batches SET qty_remaining = qty_remaining - ? WHERE id = ? AND qty_remaining >= ?",
            (a.qty, a.batch_id, a.qty),
        )
        if cur.rowcount != 1:
            raise InsufficientStock("تغير رصيد المخزون أثناء العملية، أعد المحاولة")


def sellable_stock(conn, product_id, today=None) -> int:
    today = parse_date(today) or date.today().isoformat()
    return conn.execute(
        "SELECT COALESCE(SUM(qty_remaining),0) FROM batches WHERE product_id = ?"
        " AND (expiry_date IS NULL OR expiry_date >= ?)",
        (product_id, today),
    ).fetchone()[0]


def list_batches(conn, product_id=None, only_available=True):
    where, params = [], []
    if product_id:
        where.append("b.product_id = ?")
        params.append(product_id)
    if only_available:
        where.append("b.qty_remaining > 0")
    sql = (
        "SELECT b.*, p.name AS product_name, p.unit, s.name AS supplier_name FROM batches b"
        " JOIN products p ON p.id = b.product_id"
        " LEFT JOIN purchases pu ON pu.id = b.purchase_id LEFT JOIN suppliers s ON s.id = pu.supplier_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.name, b.expiry_date IS NULL, b.expiry_date, b.received_at"
    return conn.execute(sql, params).fetchall()


def expiry_alerts(conn, warning_days: int = 30, today=None):
    """الدفعات المنتهية والقريبة من الانتهاء (التي لا يزال لها رصيد)."""
    today_d = date.fromisoformat(parse_date(today) or date.today().isoformat())
    limit = (today_d + timedelta(days=warning_days)).isoformat()
    rows = conn.execute(
        "SELECT b.*, p.name AS product_name, p.unit FROM batches b JOIN products p ON p.id = b.product_id"
        " WHERE b.qty_remaining > 0 AND b.expiry_date IS NOT NULL AND b.expiry_date <= ?"
        " ORDER BY b.expiry_date",
        (limit,),
    ).fetchall()
    result = []
    for r in rows:
        days_left = (date.fromisoformat(r["expiry_date"]) - today_d).days
        result.append({"row": r, "days_left": days_left, "expired": days_left < 0})
    return result


def write_off(conn, user, batch_id, quantity, reason) -> None:
    """إتلاف كمية من دفعة (منتهية/تالفة/فرق جرد)."""
    require(user, "inventory.manage")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("سبب الإتلاف مطلوب")
    batch = conn.execute(
        "SELECT b.*, p.is_weighted, p.name FROM batches b JOIN products p ON p.id = b.product_id WHERE b.id = ?",
        (batch_id,),
    ).fetchone()
    if batch is None:
        raise NotFoundError("الدفعة غير موجودة")
    q = validate_qty_for_product(batch, quantity)
    if q > batch["qty_remaining"]:
        raise InsufficientStock("الكمية المطلوب إتلافها أكبر من رصيد الدفعة")
    with transaction(conn):
        consume(conn, [Allocation(batch_id, q, batch["unit_cost"])])
        conn.execute(
            "INSERT INTO stock_adjustments (product_id, batch_id, qty_change, unit_cost, reason, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (batch["product_id"], batch_id, -q, batch["unit_cost"], reason, user.id, now_str()),
        )
