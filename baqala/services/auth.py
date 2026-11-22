"""المستخدمون وكلمات المرور والصلاحيات."""
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from ..db import now_str, transaction
from ..errors import AuthError, NotFoundError, PermissionDenied, ValidationError

ROLE_LABELS = {"admin": "مدير", "cashier": "موظف (كاشير)"}

ALL_PERMISSIONS = {
    "sale.cash": "البيع النقدي",
    "sale.credit": "البيع الآجل",
    "product.view": "عرض الأصناف",
    "product.edit": "إضافة وتعديل وحذف الأصناف والأسعار",
    "inventory.manage": "إدارة المخزون والدفعات",
    "purchase.manage": "المشتريات",
    "customer.view": "عرض العملاء",
    "customer.edit": "إضافة وتعديل العملاء والسقف الائتماني",
    "customer.payment": "استلام سداد العملاء",
    "supplier.manage": "الموردين وسدادهم",
    "expense.manage": "المصروفات",
    "report.view": "التقارير",
    "user.manage": "إدارة المستخدمين",
    "settings.manage": "الإعدادات والنسخ الاحتياطي",
}

ROLE_PERMISSIONS = {
    "admin": set(ALL_PERMISSIONS),
    "cashier": {"sale.cash", "sale.credit", "product.view", "customer.view", "customer.payment"},
}

_ITERATIONS = 200_000


@dataclass(frozen=True)
class User:
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool = False

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


def require(user, permission: str) -> None:
    if user is None or not user.can(permission):
        label = ALL_PERMISSIONS.get(permission, permission)
        raise PermissionDenied(f"ليست لديك صلاحية: {label}")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def _row_to_user(row) -> User:
    return User(row["id"], row["username"], row["full_name"], row["role"], bool(row["must_change_password"]))


def ensure_default_admin(conn) -> bool:
    """ينشئ حساب المدير الافتراضي (admin / admin) عند أول تشغيل. يُجبر على تغيير كلمة المرور."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    with transaction(conn):
        conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role, must_change_password, created_at)"
            " VALUES ('admin', 'المدير', ?, 'admin', 1, ?)",
            (hash_password("admin"), now_str()),
        )
    return True


def authenticate(conn, username: str, password: str) -> User:
    row = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
    if row is None or not verify_password(password or "", row["password_hash"]):
        raise AuthError("اسم المستخدم أو كلمة المرور غير صحيحة")
    if not row["active"]:
        raise AuthError("هذا الحساب موقوف")
    return _row_to_user(row)


def _validate_password(password: str) -> None:
    if not password or len(password) < 4:
        raise ValidationError("كلمة المرور يجب أن تكون 4 أحرف على الأقل")


def change_password(conn, user_id: int, old_password: str, new_password: str) -> None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFoundError("المستخدم غير موجود")
    if not verify_password(old_password or "", row["password_hash"]):
        raise AuthError("كلمة المرور الحالية غير صحيحة")
    _validate_password(new_password)
    if new_password == old_password:
        raise ValidationError("اختر كلمة مرور مختلفة عن الحالية")
    with transaction(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(new_password), user_id),
        )


def list_users(conn):
    return conn.execute("SELECT * FROM users ORDER BY id").fetchall()


def create_user(conn, actor, username, full_name, password, role, active=True) -> int:
    require(actor, "user.manage")
    username = (username or "").strip()
    if not username:
        raise ValidationError("اسم المستخدم مطلوب")
    if role not in ROLE_PERMISSIONS:
        raise ValidationError("نوع الحساب غير صالح")
    _validate_password(password)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise ValidationError("اسم المستخدم مستخدم مسبقاً")
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, (full_name or "").strip(), hash_password(password), role, 1 if active else 0, now_str()),
        )
    return cur.lastrowid


def _active_admins(conn, exclude_id=None) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id <> ?", (exclude_id or 0,)
    ).fetchone()[0]


def update_user(conn, actor, user_id, full_name, role, active) -> None:
    require(actor, "user.manage")
    if role not in ROLE_PERMISSIONS:
        raise ValidationError("نوع الحساب غير صالح")
    if (role != "admin" or not active) and _active_admins(conn, user_id) == 0:
        raise ValidationError("يجب أن يبقى مدير نشط واحد على الأقل")
    with transaction(conn):
        conn.execute(
            "UPDATE users SET full_name = ?, role = ?, active = ? WHERE id = ?",
            ((full_name or "").strip(), role, 1 if active else 0, user_id),
        )


def reset_password(conn, actor, user_id, new_password) -> None:
    require(actor, "user.manage")
    _validate_password(new_password)
    with transaction(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (hash_password(new_password), user_id),
        )
