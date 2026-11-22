"""العملاء والموردين: البيانات، الأرصدة (الديون)، السداد، وكشف الحساب."""
from ..db import now_str, transaction
from ..errors import NotFoundError, ValidationError
from ..money import int_to_money, money, money_to_int
from ..textnorm import normalize_ar
from .auth import require

_CFG = {
    "customer": {
        "table": "customers", "view": "customer_balances", "fk": "customer_id",
        "payments": "customer_payments", "label": "العميل",
        "edit": "customer.edit", "view_perm": "customer.view", "pay": "customer.payment",
    },
    "supplier": {
        "table": "suppliers", "view": "supplier_balances", "fk": "supplier_id",
        "payments": "supplier_payments", "label": "المورد",
        "edit": "supplier.manage", "view_perm": "supplier.manage", "pay": "supplier.manage",
    },
}


def _cfg(kind):
    if kind not in _CFG:
        raise ValueError(kind)
    return _CFG[kind]


def list_parties(conn, kind, term="", include_inactive=False):
    c = _cfg(kind)
    rows = conn.execute(
        f"SELECT t.*, v.balance FROM {c['table']} t JOIN {c['view']} v ON v.{c['fk']} = t.id"
        + ("" if include_inactive else " WHERE t.active = 1")
        + " ORDER BY t.name"
    ).fetchall()
    term_n = normalize_ar(term)
    if term_n:
        rows = [r for r in rows if term_n in normalize_ar(r["name"]) or term_n in (r["phone"] or "")]
    return rows


def get_party(conn, kind, party_id):
    c = _cfg(kind)
    row = conn.execute(
        f"SELECT t.*, v.balance FROM {c['table']} t JOIN {c['view']} v ON v.{c['fk']} = t.id WHERE t.id = ?",
        (party_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"{c['label']} غير موجود")
    return row


def balance(conn, kind, party_id):
    return int_to_money(get_party(conn, kind, party_id)["balance"])


def save_party(conn, user, kind, data: dict, party_id=None) -> int:
    c = _cfg(kind)
    require(user, c["edit"])
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError(f"اسم {c['label']} مطلوب")
    values = {
        "name": name,
        "phone": (data.get("phone") or "").strip(),
        "address": (data.get("address") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
        "opening_balance": money_to_int(data.get("opening_balance") or 0),
        "active": 1 if data.get("active", True) else 0,
    }
    if kind == "customer":
        limit = money(data.get("credit_limit") or 0)
        if limit < 0:
            raise ValidationError("السقف الائتماني لا يمكن أن يكون سالباً")
        values["credit_limit"] = money_to_int(limit)
    cols = list(values)
    with transaction(conn):
        if party_id:
            get_party(conn, kind, party_id)
            sets = ", ".join(f"{k} = :{k}" for k in cols)
            conn.execute(f"UPDATE {c['table']} SET {sets} WHERE id = :id", {**values, "id": party_id})
            return party_id
        values["created_at"] = now_str()
        cols.append("created_at")
        return conn.execute(
            f"INSERT INTO {c['table']} ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)})", values
        ).lastrowid


def add_payment(conn, user, kind, party_id, amount, note="") -> int:
    """تسجيل سداد (من العميل للمحل، أو من المحل للمورد)."""
    c = _cfg(kind)
    require(user, c["pay"])
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("مبلغ السداد يجب أن يكون أكبر من صفر")
    with transaction(conn):
        party = get_party(conn, kind, party_id)
        if money_to_int(amount) > party["balance"]:
            raise ValidationError(
                f"مبلغ السداد أكبر من الدين المستحق ({int_to_money(party['balance'])})"
            )
        return conn.execute(
            f"INSERT INTO {c['payments']} ({c['fk']}, amount, note, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (party_id, money_to_int(amount), (note or "").strip(), user.id, now_str()),
        ).lastrowid


def statement(conn, kind, party_id):
    """كشف حساب: قائمة حركات (تاريخ، بيان، مدين، دائن، الرصيد)."""
    _cfg(kind)
    party = get_party(conn, kind, party_id)
    if kind == "customer":
        moves = conn.execute(
            "SELECT created_at, 'فاتورة آجل رقم ' || id AS description, total - paid AS debit, 0 AS credit"
            " FROM sales WHERE customer_id = ? AND total - paid > 0"
            " UNION ALL SELECT created_at, 'سداد ' || note, 0, amount FROM customer_payments WHERE customer_id = ?"
            " ORDER BY 1",
            (party_id, party_id),
        ).fetchall()
    else:
        moves = conn.execute(
            "SELECT created_at, 'فاتورة شراء رقم ' || id, total - paid, 0 FROM purchases"
            " WHERE supplier_id = ? AND total - paid > 0"
            " UNION ALL SELECT created_at, 'سداد ' || note, 0, amount FROM supplier_payments WHERE supplier_id = ?"
            " ORDER BY 1",
            (party_id, party_id),
        ).fetchall()
    running = party["opening_balance"]
    result = []
    if running:
        result.append(("", "رصيد افتتاحي", int_to_money(running), int_to_money(0), int_to_money(running)))
    for m in moves:
        running += m[2] - m[3]
        result.append((m[0], m[1].strip(), int_to_money(m[2]), int_to_money(m[3]), int_to_money(running)))
    return result


def total_debts(conn, kind):
    c = _cfg(kind)
    v = conn.execute(f"SELECT COALESCE(SUM(balance),0) FROM {c['view']} WHERE balance > 0").fetchone()[0]
    return int_to_money(v)
