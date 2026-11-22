from decimal import Decimal

import pytest

from baqala import db
from baqala.errors import CreditLimitExceeded, InsufficientStock, PermissionDenied, ValidationError
from baqala.services import inventory, parties, products, sales
from baqala.services.sales import CartLine


def stock(conn, pid):
    return products.get_product(conn, pid)["stock"]


def test_cash_sale_totals_and_stock(conn, admin, make_product):
    rice = make_product("أرز", "111", price="1200")
    spice = make_product("كمون", "222", price="6000", weighted=True)
    inventory.add_opening_stock(conn, admin, rice, 10, 900)
    inventory.add_opening_stock(conn, admin, spice, "2.000", 4000)
    sid = sales.create_sale(conn, admin, [CartLine(rice, Decimal(2)), CartLine(spice, Decimal("0.250"))])
    sale, items = sales.get_sale(conn, sid)
    assert sale["total"] == (2400 + 1500) * 100
    assert sale["paid"] == sale["total"]
    assert sale["cost_total"] == (1800 + 1000) * 100
    assert stock(conn, rice) == 8000 and stock(conn, spice) == 1750


def test_duplicate_lines_merged(conn, admin, make_product):
    p = make_product(price="100")
    inventory.add_opening_stock(conn, admin, p, 5, 50)
    sid = sales.create_sale(conn, admin, [CartLine(p, Decimal(1)), CartLine(p, Decimal(2))])
    _, items = sales.get_sale(conn, sid)
    assert len(items) == 1 and items[0]["qty"] == 3000


def test_fractional_qty_rejected_for_unit_products(conn, admin, make_product):
    p = make_product()
    inventory.add_opening_stock(conn, admin, p, 5, 50)
    with pytest.raises(ValidationError):
        sales.create_sale(conn, admin, [CartLine(p, Decimal("1.5"))])


def test_insufficient_stock_rolls_back_everything(conn, admin, make_product):
    a = make_product("أ", price="100")
    b = make_product("ب", price="100")
    inventory.add_opening_stock(conn, admin, a, 5, 50)
    inventory.add_opening_stock(conn, admin, b, 1, 50)
    with pytest.raises(InsufficientStock):
        sales.create_sale(conn, admin, [CartLine(a, Decimal(2)), CartLine(b, Decimal(3))])
    assert stock(conn, a) == 5000 and stock(conn, b) == 1000
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0


def test_failure_midway_leaves_no_partial_data(conn, admin, make_product, monkeypatch):
    """محاكاة انقطاع/خطأ بعد خصم المخزون: يجب ألا يبقى أي أثر."""
    p = make_product(price="100")
    inventory.add_opening_stock(conn, admin, p, 5, 50)

    class Boom(Exception):
        pass

    class Proxy:
        def __getattr__(self, name):
            return getattr(conn, name)

        def executemany(self, *a, **k):
            raise Boom()

    with pytest.raises(Boom):
        sales.create_sale(Proxy(), admin, [CartLine(p, Decimal(2))])
    assert not conn.in_transaction
    assert stock(conn, p) == 5000
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0] == 0




def test_credit_sale_within_limit(conn, admin, make_product, make_customer):
    p = make_product(price="1000")
    inventory.add_opening_stock(conn, admin, p, 20, 500)
    c = make_customer(limit="5000")
    sales.create_sale(conn, admin, [CartLine(p, Decimal(3))], "credit", c, paid="1000")
    assert parties.balance(conn, "customer", c) == Decimal("2000.00")


def test_credit_limit_blocks_sale(conn, admin, make_product, make_customer):
    p = make_product(price="1000")
    inventory.add_opening_stock(conn, admin, p, 20, 500)
    c = make_customer(limit="5000", opening="3000")
    with pytest.raises(CreditLimitExceeded) as e:
        sales.create_sale(conn, admin, [CartLine(p, Decimal(3))], "credit", c)
    assert "المتاح: 2,000" in e.value.message
    assert stock(conn, p) == 20000
    # البيع بالضبط حتى السقف مسموح
    sales.create_sale(conn, admin, [CartLine(p, Decimal(2))], "credit", c)
    assert parties.balance(conn, "customer", c) == Decimal("5000.00")
    with pytest.raises(CreditLimitExceeded):
        sales.create_sale(conn, admin, [CartLine(p, Decimal(1))], "credit", c)


def test_down_payment_can_keep_under_limit(conn, admin, make_product, make_customer):
    p = make_product(price="1000")
    inventory.add_opening_stock(conn, admin, p, 20, 500)
    c = make_customer(limit="1000")
    sales.create_sale(conn, admin, [CartLine(p, Decimal(3))], "credit", c, paid="2000")
    assert parties.balance(conn, "customer", c) == Decimal("1000.00")


def test_zero_limit_means_no_credit(conn, admin, make_product, make_customer):
    p = make_product(price="10")
    inventory.add_opening_stock(conn, admin, p, 5, 5)
    c = make_customer(limit="0")
    with pytest.raises(CreditLimitExceeded):
        sales.create_sale(conn, admin, [CartLine(p, Decimal(1))], "credit", c)


def test_payment_restores_credit(conn, admin, make_product, make_customer):
    p = make_product(price="1000")
    inventory.add_opening_stock(conn, admin, p, 20, 500)
    c = make_customer(limit="2000")
    sales.create_sale(conn, admin, [CartLine(p, Decimal(2))], "credit", c)
    parties.add_payment(conn, admin, "customer", c, "1500")
    sales.create_sale(conn, admin, [CartLine(p, Decimal(1))], "credit", c)
    assert parties.balance(conn, "customer", c) == Decimal("1500.00")
    with pytest.raises(ValidationError):
        parties.add_payment(conn, admin, "customer", c, "99999")
    st = parties.statement(conn, "customer", c)
    assert st[-1][4] == Decimal("1500.00")


def test_credit_requires_customer(conn, admin, make_product):
    p = make_product()
    inventory.add_opening_stock(conn, admin, p, 1, 1)
    with pytest.raises(ValidationError):
        sales.create_sale(conn, admin, [CartLine(p, Decimal(1))], "credit", None)


def test_cashier_permissions(conn, cashier, make_product):
    p = make_product()
    with pytest.raises(PermissionDenied):
        products.update_price(conn, cashier, p, "5")
    with pytest.raises(PermissionDenied):
        inventory.add_opening_stock(conn, cashier, p, 1, 1)


def test_price_taken_from_db_and_history(conn, admin, make_product):
    p = make_product(price="100")
    inventory.add_opening_stock(conn, admin, p, 5, 50)
    products.update_price(conn, admin, p, "150")
    sid = sales.create_sale(conn, admin, [CartLine(p, Decimal(1))])
    assert sales.get_sale(conn, sid)[0]["total"] == 15000
    assert products.price_history(conn, p)[0]["new_price"] == 15000


def test_transaction_nested_savepoint(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO categories (name) VALUES ('خارجي')")
        with pytest.raises(RuntimeError):
            with db.transaction(conn):
                conn.execute("INSERT INTO categories (name) VALUES ('داخلي')")
                raise RuntimeError
    names = [r[0] for r in conn.execute("SELECT name FROM categories")]
    assert names == ["خارجي"]
