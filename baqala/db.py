"""قاعدة البيانات والمعاملات: SQL Server (الأساسية) أو SQLite محلية (احتياطية).

نفس الخدمات تعمل على المحركين؛ تفاصيل SQL Server في baqala/mssql.py.

- WAL + synchronous=FULL: كل معاملة مُثبّتة (COMMIT) تبقى سليمة عند انقطاع الكهرباء،
  وأي معاملة لم تكتمل تُلغى تلقائياً عند الفتح التالي.
- كل عملية متعددة الخطوات (بيع، شراء، سداد...) تتم داخل transaction() واحدة.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'cashier')),
    active        INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- المبالغ بوحدة 1/100 ريال، والكميات بوحدة 1/1000
CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    name_norm    TEXT NOT NULL,
    barcode      TEXT UNIQUE,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    unit         TEXT NOT NULL DEFAULT 'حبة',
    is_weighted  INTEGER NOT NULL DEFAULT 0,
    sell_price   INTEGER NOT NULL CHECK (sell_price >= 0),
    cost_price   INTEGER NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    min_qty      INTEGER NOT NULL DEFAULT 0 CHECK (min_qty >= 0),
    track_expiry INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_products_name ON products(name_norm);
CREATE INDEX idx_products_cat ON products(category_id);

CREATE TABLE price_history (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    old_price  INTEGER NOT NULL,
    new_price  INTEGER NOT NULL,
    user_id    INTEGER REFERENCES users(id),
    changed_at TEXT NOT NULL
);

CREATE TABLE customers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    phone           TEXT NOT NULL DEFAULT '',
    address         TEXT NOT NULL DEFAULT '',
    credit_limit    INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
    opening_balance INTEGER NOT NULL DEFAULT 0,
    notes           TEXT NOT NULL DEFAULT '',
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE suppliers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    phone           TEXT NOT NULL DEFAULT '',
    address         TEXT NOT NULL DEFAULT '',
    opening_balance INTEGER NOT NULL DEFAULT 0,
    notes           TEXT NOT NULL DEFAULT '',
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE purchases (
    id            INTEGER PRIMARY KEY,
    supplier_id   INTEGER REFERENCES suppliers(id),
    purchase_type TEXT NOT NULL CHECK (purchase_type IN ('cash', 'credit', 'opening')),
    total         INTEGER NOT NULL CHECK (total >= 0),
    paid          INTEGER NOT NULL CHECK (paid >= 0),
    note          TEXT NOT NULL DEFAULT '',
    user_id       INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL,
    CHECK (paid <= total),
    CHECK (purchase_type <> 'credit' OR supplier_id IS NOT NULL)
);

-- دفعات المخزون: أساس FEFO وتتبع الصلاحية وتكلفة البضاعة المباعة
CREATE TABLE batches (
    id            INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES products(id),
    purchase_id   INTEGER REFERENCES purchases(id),
    qty_received  INTEGER NOT NULL CHECK (qty_received > 0),
    qty_remaining INTEGER NOT NULL CHECK (qty_remaining >= 0),
    unit_cost     INTEGER NOT NULL CHECK (unit_cost >= 0),
    expiry_date   TEXT,
    received_at   TEXT NOT NULL,
    CHECK (qty_remaining <= qty_received)
);
CREATE INDEX idx_batches_fefo ON batches(product_id, expiry_date, received_at);

CREATE TABLE sales (
    id          INTEGER PRIMARY KEY,
    sale_type   TEXT NOT NULL CHECK (sale_type IN ('cash', 'credit')),
    customer_id INTEGER REFERENCES customers(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    total       INTEGER NOT NULL CHECK (total >= 0),
    paid        INTEGER NOT NULL CHECK (paid >= 0),
    cost_total  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    CHECK (paid <= total),
    CHECK (sale_type = 'cash' OR customer_id IS NOT NULL),
    CHECK (sale_type = 'credit' OR paid = total)
);
CREATE INDEX idx_sales_date ON sales(created_at);
CREATE INDEX idx_sales_customer ON sales(customer_id);

CREATE TABLE sale_items (
    id           INTEGER PRIMARY KEY,
    sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    unit         TEXT NOT NULL,
    qty          INTEGER NOT NULL CHECK (qty > 0),
    unit_price   INTEGER NOT NULL,
    line_total   INTEGER NOT NULL,
    cost_total   INTEGER NOT NULL
);
CREATE INDEX idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX idx_sale_items_product ON sale_items(product_id);

CREATE TABLE sale_item_batches (
    id           INTEGER PRIMARY KEY,
    sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE CASCADE,
    batch_id     INTEGER NOT NULL REFERENCES batches(id),
    qty          INTEGER NOT NULL CHECK (qty > 0),
    unit_cost    INTEGER NOT NULL
);

CREATE TABLE customer_payments (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    note        TEXT NOT NULL DEFAULT '',
    user_id     INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_cpay_customer ON customer_payments(customer_id);

CREATE TABLE supplier_payments (
    id          INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    note        TEXT NOT NULL DEFAULT '',
    user_id     INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_spay_supplier ON supplier_payments(supplier_id);

CREATE TABLE expenses (
    id           INTEGER PRIMARY KEY,
    category     TEXT NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),
    description  TEXT NOT NULL DEFAULT '',
    expense_date TEXT NOT NULL,
    user_id      INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_expenses_date ON expenses(expense_date);

-- إتلاف/تسوية المخزون (منتهي، تالف، فرق جرد)
CREATE TABLE stock_adjustments (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id   INTEGER REFERENCES batches(id),
    qty_change INTEGER NOT NULL,
    unit_cost  INTEGER NOT NULL DEFAULT 0,
    reason     TEXT NOT NULL,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE VIEW customer_balances AS
SELECT c.id AS customer_id,
       c.opening_balance
       + COALESCE((SELECT SUM(s.total - s.paid) FROM sales s WHERE s.customer_id = c.id), 0)
       - COALESCE((SELECT SUM(p.amount) FROM customer_payments p WHERE p.customer_id = c.id), 0)
       AS balance
FROM customers c;

CREATE VIEW supplier_balances AS
SELECT s.id AS supplier_id,
       s.opening_balance
       + COALESCE((SELECT SUM(pu.total - pu.paid) FROM purchases pu WHERE pu.supplier_id = s.id), 0)
       - COALESCE((SELECT SUM(p.amount) FROM supplier_payments p WHERE p.supplier_id = s.id), 0)
       AS balance
FROM suppliers s;
"""

# كل ترحيل يرفع user_version بواحد. أضف ترحيلات جديدة في آخر القائمة فقط
# حتى تُحدَّث قواعد بيانات المحلات القائمة دون فقدان بيانات.
MIGRATIONS = [SCHEMA_V1]


def now_str(dt: datetime = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def connect(path) -> sqlite3.Connection:
    path = str(path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 10000")
    migrate(conn)
    return conn


def dialect(conn) -> str:
    return getattr(conn, "dialect", "sqlite")


def open_database(cfg=None):
    """يفتح قاعدة البيانات حسب database.ini (SQL Server افتراضياً)."""
    from . import config
    cfg = cfg or config.load_db_config()
    if cfg.engine == "sqlite":
        return connect(config.db_path())
    from . import mssql
    return mssql.connect(cfg)


def schema_version(conn) -> int:
    if dialect(conn) == "mssql":
        from . import mssql
        return mssql.schema_version(conn)
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn) -> None:
    current = schema_version(conn)
    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        # executescript ينفذ COMMIT ضمنياً، لذلك نضع BEGIN/COMMIT داخل النص
        try:
            conn.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


@contextmanager
def transaction(conn):
    """معاملة ذرّية: إما أن تُنفّذ كل الخطوات أو لا شيء. تدعم التداخل عبر SAVEPOINT."""
    if dialect(conn) == "mssql":
        with _mssql_transaction(conn):
            yield conn
        return
    if conn.in_transaction:
        name = f"sp_{id(object())}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        else:
            conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


@contextmanager
def _mssql_transaction(conn):
    if conn.in_transaction:
        name = conn.savepoint()
        try:
            yield
        except BaseException:
            conn.rollback_to(name)
            raise
    else:
        conn.begin()
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()


def integrity_ok(conn) -> bool:
    if dialect(conn) == "mssql":
        from . import mssql
        return mssql.integrity_ok(conn)
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row is not None and row[0] == "ok"
