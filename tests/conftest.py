import pytest

from baqala import db
from baqala.services import auth, parties, products


@pytest.fixture
def conn(tmp_path):
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
