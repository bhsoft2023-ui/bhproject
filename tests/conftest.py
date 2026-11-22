import os
import uuid

import pytest

from baqala import db
from baqala.services import auth, parties, products

# لتشغيل الاختبارات على SQL Server:
#   BAQALA_TEST_MSSQL_SERVER=localhost BAQALA_TEST_MSSQL_USER=sa BAQALA_TEST_MSSQL_PASSWORD=... pytest
MSSQL_SERVER = os.environ.get("BAQALA_TEST_MSSQL_SERVER", "")
ENGINES = ["sqlite"] + (["mssql"] if MSSQL_SERVER else [])
TABLES_CHILD_FIRST = [
    "sale_item_batches", "sale_items", "customer_payments", "supplier_payments", "stock_adjustments",
    "sales", "batches", "purchases", "price_history", "expenses", "products", "categories",
    "customers", "suppliers", "users", "settings",
]


def mssql_config(database):
    from baqala.config import DatabaseConfig
    user = os.environ.get("BAQALA_TEST_MSSQL_USER", "")
    return DatabaseConfig(engine="mssql", server=MSSQL_SERVER, database=database,
                          auth="sql" if user else "windows", username=user,
                          password=os.environ.get("BAQALA_TEST_MSSQL_PASSWORD", ""))


@pytest.fixture(scope="session")
def mssql_db():
    from baqala import mssql
    cfg = mssql_config(f"BaqalaPOS_test_{uuid.uuid4().hex[:8]}")
    c = mssql.connect(cfg)
    yield cfg, c
    c.close()
    drop_mssql_database(cfg)


def drop_mssql_database(cfg):
    from baqala import mssql
    raw = mssql._raw_connect(cfg, "master")
    try:
        raw.cursor().execute(
            f"IF DB_ID(N'{cfg.database}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{cfg.database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{cfg.database}]; END")
    finally:
        raw.close()


def reset_mssql(c):
    cur = c.raw.cursor()
    for t in TABLES_CHILD_FIRST:
        cur.execute(f"DELETE FROM dbo.{t}")
        used = cur.execute(
            "SELECT CAST(last_value AS BIGINT) FROM sys.identity_columns WHERE object_id = OBJECT_ID(?)", f"dbo.{t}").fetchone()
        if used and used[0] is not None:
            cur.execute(f"DBCC CHECKIDENT ('dbo.{t}', RESEED, 0) WITH NO_INFOMSGS")


@pytest.fixture
def bk_root(engine, tmp_path):
    """مجلد نسخ يراه البرنامج وخادم SQL Server معاً (BAQALA_TEST_MSSQL_SHARE عند الاختبار على خادم في حاوية)."""
    if engine != "mssql":
        return tmp_path
    share = os.environ.get("BAQALA_TEST_MSSQL_SHARE", "")
    if not share:
        pytest.skip("BAQALA_TEST_MSSQL_SHARE غير محدد")
    d = os.path.join(share, uuid.uuid4().hex[:8])
    for sub in ("", "bk", "safety"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        os.chmod(os.path.join(d, sub), 0o777)
    return __import__("pathlib").Path(d)


@pytest.fixture(params=ENGINES)
def engine(request):
    return request.param


@pytest.fixture
def conn(request, engine, tmp_path):
    if engine == "mssql":
        cfg, c = request.getfixturevalue("mssql_db")
        reset_mssql(c)
        auth.ensure_default_admin(c)
        yield c
        c.rollback()
        return
    c = db.connect(tmp_path / "test.db")
    auth.ensure_default_admin(c)
    yield c
    c.close()


@pytest.fixture
def admin(conn):
    return auth.authenticate(conn, "admin", "admin")


@pytest.fixture
def cashier(conn, admin):
    auth.create_user(conn, admin, "ali", "علي", "1234", "cashier")
    return auth.authenticate(conn, "ali", "1234")


@pytest.fixture
def make_product(conn, admin):
    def _make(name="أرز", barcode=None, price="1000", cost="800", weighted=False, track_expiry=False, **kw):
        return products.create_product(
            conn, admin,
            {"name": name, "barcode": barcode, "sell_price": price, "cost_price": cost,
             "is_weighted": weighted, "track_expiry": track_expiry, **kw},
        )
    return _make


@pytest.fixture
def make_customer(conn, admin):
    def _make(name="محمد", limit="10000", opening="0"):
        return parties.save_party(conn, admin, "customer", {"name": name, "credit_limit": limit, "opening_balance": opening})
    return _make
