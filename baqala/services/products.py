"""الأصناف والتصنيفات والأسعار."""
from ..db import now_str, transaction
from ..errors import NotFoundError, ValidationError
from ..money import int_to_qty, money, money_to_int, qty, qty_to_int
from ..textnorm import normalize_ar, normalize_barcode
from .auth import require

STOCK_SQL = "COALESCE((SELECT SUM(b.qty_remaining) FROM batches b WHERE b.product_id = p.id), 0)"


# ---------------- التصنيفات ----------------
def list_categories(conn):
    return conn.execute("SELECT * FROM categories ORDER BY name").fetchall()


def add_category(conn, user, name) -> int:
    require(user, "product.edit")
    name = (name or "").strip()
    if not name:
        raise ValidationError("اسم التصنيف مطلوب")
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise ValidationError("التصنيف موجود مسبقاً")
    with transaction(conn):
        return conn.execute("INSERT INTO categories (name) VALUES (?)", (name,)).lastrowid


def rename_category(conn, user, category_id, name) -> None:
    require(user, "product.edit")
    name = (name or "").strip()
    if not name:
        raise ValidationError("اسم التصنيف مطلوب")
    if conn.execute("SELECT 1 FROM categories WHERE name = ? AND id <> ?", (name, category_id)).fetchone():
        raise ValidationError("التصنيف موجود مسبقاً")
    with transaction(conn):
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))


def delete_category(conn, user, category_id) -> None:
    require(user, "product.edit")
    with transaction(conn):
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


# ---------------- الأصناف ----------------
def _clean(conn, data: dict, product_id=None) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("اسم الصنف مطلوب")
    barcode = normalize_barcode(data.get("barcode") or "") or None
    if barcode:
        dup = conn.execute(
            "SELECT name FROM products WHERE barcode = ? AND id <> ?", (barcode, product_id or 0)
        ).fetchone()
        if dup:
            raise ValidationError(f"الباركود مستخدم للصنف: {dup['name']}")
    sell_price = money(data.get("sell_price", 0))
    cost_price = money(data.get("cost_price", 0) or 0)
    min_qty = qty(data.get("min_qty", 0) or 0)
    if sell_price < 0 or cost_price < 0 or min_qty < 0:
        raise ValidationError("لا يُسمح بقيم سالبة للأسعار أو الحد الأدنى")
    is_weighted = bool(data.get("is_weighted"))
    unit = (data.get("unit") or "").strip() or ("كجم" if is_weighted else "حبة")
    category_id = data.get("category_id") or None
    return {
        "name": name,
        "name_norm": normalize_ar(name),
        "barcode": barcode,
        "category_id": category_id,
        "unit": unit,
        "is_weighted": 1 if is_weighted else 0,
        "sell_price": money_to_int(sell_price),
        "cost_price": money_to_int(cost_price),
        "min_qty": qty_to_int(min_qty),
        "track_expiry": 1 if data.get("track_expiry") else 0,
    }


def create_product(conn, user, data: dict, initial_qty=None, initial_expiry=None) -> int:
    """إضافة صنف، مع رصيد افتتاحي اختياري (يُسجّل كدفعة)."""
    require(user, "product.edit")
    from .inventory import add_opening_stock

    clean = _clean(conn, data)
    ts = now_str()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO products (name, name_norm, barcode, category_id, unit, is_weighted, sell_price,"
            " cost_price, min_qty, track_expiry, created_at, updated_at)"
            " VALUES (:name, :name_norm, :barcode, :category_id, :unit, :is_weighted, :sell_price,"
            " :cost_price, :min_qty, :track_expiry, :ts, :ts)",
            {**clean, "ts": ts},
        )
        product_id = cur.lastrowid
        if initial_qty is not None and qty(initial_qty) > 0:
            add_opening_stock(conn, user, product_id, initial_qty, data.get("cost_price", 0) or 0, initial_expiry)
    return product_id


def update_product(conn, user, product_id, data: dict) -> None:
    require(user, "product.edit")
    old = get_product(conn, product_id)
    clean = _clean(conn, data, product_id)
    if old["is_weighted"] and not clean["is_weighted"]:
        frac = conn.execute(
            "SELECT CASE WHEN EXISTS(SELECT 1 FROM batches WHERE product_id = ? AND qty_remaining % 1000 <> 0)"
            " THEN 1 ELSE 0 END", (product_id,)
        ).fetchone()[0]
        if frac:
            raise ValidationError("لا يمكن إلغاء البيع بالوزن لوجود كميات عشرية في المخزون")
    with transaction(conn):
        conn.execute(
            "UPDATE products SET name=:name, name_norm=:name_norm, barcode=:barcode, category_id=:category_id,"
            " unit=:unit, is_weighted=:is_weighted, sell_price=:sell_price, cost_price=:cost_price,"
            " min_qty=:min_qty, track_expiry=:track_expiry, updated_at=:ts WHERE id=:id",
            {**clean, "ts": now_str(), "id": product_id},
        )
        if old["sell_price"] != clean["sell_price"]:
            _log_price(conn, user, product_id, old["sell_price"], clean["sell_price"])


def _log_price(conn, user, product_id, old_price, new_price):
    conn.execute(
        "INSERT INTO price_history (product_id, old_price, new_price, user_id, changed_at) VALUES (?, ?, ?, ?, ?)",
        (product_id, old_price, new_price, user.id, now_str()),
    )


def update_price(conn, user, product_id, new_price) -> None:
    require(user, "product.edit")
    new_price = money(new_price)
    if new_price < 0:
        raise ValidationError("السعر لا يمكن أن يكون سالباً")
    old = get_product(conn, product_id)
    new_int = money_to_int(new_price)
    if old["sell_price"] == new_int:
        return
    with transaction(conn):
        conn.execute("UPDATE products SET sell_price = ?, updated_at = ? WHERE id = ?", (new_int, now_str(), product_id))
        _log_price(conn, user, product_id, old["sell_price"], new_int)


def delete_product(conn, user, product_id) -> str:
    """يحذف الصنف نهائياً إن لم تكن له حركات، وإلا يُوقفه (حذف منطقي) للحفاظ على السجلات."""
    require(user, "product.edit")
    get_product(conn, product_id)
    used = conn.execute(
        "SELECT CASE WHEN EXISTS(SELECT 1 FROM sale_items WHERE product_id = ?)"
        " OR EXISTS(SELECT 1 FROM batches WHERE product_id = ?) THEN 1 ELSE 0 END",
        (product_id, product_id),
    ).fetchone()[0]
    with transaction(conn):
        if used:
            stock = conn.execute(
                "SELECT COALESCE(SUM(qty_remaining),0) FROM batches WHERE product_id = ?", (product_id,)
            ).fetchone()[0]
            if stock > 0:
                raise ValidationError("لا يمكن حذف صنف له رصيد في المخزون. قم بإتلاف/تسوية الرصيد أولاً")
            conn.execute(
                "UPDATE products SET active = 0, barcode = NULL, updated_at = ? WHERE id = ?", (now_str(), product_id)
            )
            return "deactivated"
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return "deleted"


def get_product(conn, product_id):
    row = conn.execute(
        f"SELECT p.*, c.name AS category_name, {STOCK_SQL} AS stock FROM products p"
        " LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?",
        (product_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("الصنف غير موجود")
    return row


def find_by_barcode(conn, code: str):
    """بحث بالباركود. يجرب النص كما هو ثم بعد تصحيح تخطيط لوحة المفاتيح العربي."""
    raw = (code or "").strip()
    if not raw:
        return None
    norm = normalize_barcode(raw)
    for candidate in dict.fromkeys([raw, norm, norm.upper(), norm.lower()]):
        row = conn.execute(
            f"SELECT p.*, {STOCK_SQL} AS stock FROM products p WHERE p.barcode = ? AND p.active = 1", (candidate,)
        ).fetchone()
        if row:
            return row
    return None


def search_products(conn, term: str = "", category_id=None, include_inactive=False, limit=500):
    """بحث بالاسم (مع توحيد الهمزات والتاء المربوطة) أو الباركود، مع فلترة بالتصنيف."""
    where, params = [], []
    if not include_inactive:
        where.append("p.active = 1")
    if category_id:
        where.append("p.category_id = ?")
        params.append(category_id)
    term = (term or "").strip()
    if term:
        words = normalize_ar(term).split()
        name_cond = " AND ".join("p.name_norm LIKE ?" for _ in words)
        params_name = [f"%{w}%" for w in words]
        where.append(f"(({name_cond}) OR p.barcode LIKE ?)")
        params.extend(params_name)
        params.append(f"{normalize_barcode(term)}%")
    sql = (
        f"SELECT p.*, c.name AS category_name, {STOCK_SQL} AS stock FROM products p"
        " LEFT JOIN categories c ON c.id = p.category_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.name LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def low_stock(conn):
    return conn.execute(
        f"SELECT p.*, {STOCK_SQL} AS stock FROM products p"
        f" WHERE p.active = 1 AND p.min_qty > 0 AND {STOCK_SQL} <= p.min_qty ORDER BY p.name"
    ).fetchall()


def price_history(conn, product_id):
    return conn.execute(
        "SELECT h.*, u.username FROM price_history h LEFT JOIN users u ON u.id = h.user_id"
        " WHERE h.product_id = ? ORDER BY h.id DESC",
        (product_id,),
    ).fetchall()


def stock_of(row):
    return int_to_qty(row["stock"])
