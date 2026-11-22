"""نقل كل البيانات من قاعدة SQLite سابقة إلى قاعدة SQL Server فارغة (مع الحفاظ على الأرقام والعلاقات)."""
import sqlite3
from pathlib import Path

from .db import transaction
from .errors import ValidationError

# ترتيب الآباء قبل الأبناء حتى تتحقق المفاتيح الأجنبية
TABLES = [
    "settings", "users", "categories", "products", "price_history", "customers", "suppliers",
    "purchases", "batches", "sales", "sale_items", "sale_item_batches", "customer_payments",
    "supplier_payments", "expenses", "stock_adjustments",
]
CHECK_TABLES = ["products", "sales", "customers", "suppliers", "purchases", "expenses"]


def target_has_data(conn) -> bool:
    for t in CHECK_TABLES:
        if conn.scalar(f"SELECT COUNT(*) FROM dbo.{t}"):
            return True
    return False


def sqlite_to_mssql(sqlite_path, conn, progress=None) -> dict:
    """ينقل البيانات داخل معاملة واحدة: إما أن تُنقل كاملة أو لا يُنقل شيء."""
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.is_file():
        raise ValidationError("ملف قاعدة SQLite غير موجود")
    if target_has_data(conn):
        raise ValidationError("قاعدة SQL Server تحتوي بيانات مسبقاً؛ النقل يتم إلى قاعدة فارغة فقط")
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    counts = {}
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValidationError("قاعدة SQLite المصدر تالفة؛ استعد نسخة سليمة أولاً")
        with transaction(conn):
            conn.execute("DELETE FROM dbo.users")  # المدير الافتراضي يُستبدل بمستخدمي القاعدة القديمة
            conn.execute("DELETE FROM dbo.settings")
            for table in TABLES:
                if progress:
                    progress(table)
                cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
                rows = [tuple(r) for r in src.execute(f"SELECT {', '.join(cols)} FROM {table}")]
                counts[table] = len(rows)
                if not rows:
                    continue
                has_identity = "id" in cols
                col_sql = ", ".join(f'"{c}"' for c in cols)
                marks = ", ".join("?" for _ in cols)
                if has_identity:
                    conn.execute(f"SET IDENTITY_INSERT dbo.{table} ON")
                try:
                    conn.executemany(f"INSERT INTO dbo.{table} ({col_sql}) VALUES ({marks})", rows)
                finally:
                    if has_identity:
                        conn.execute(f"SET IDENTITY_INSERT dbo.{table} OFF")
            for table, n in counts.items():
                got = conn.scalar(f"SELECT COUNT(*) FROM dbo.{table}")
                if got != n:
                    raise ValidationError(f"فشل التحقق بعد النقل في جدول {table}: {got} بدلاً من {n}")
    finally:
        src.close()
    return counts
