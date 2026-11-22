"""اختبارات خاصة بربط SQL Server: تحويل الاستعلامات، الإعداد، والنقل من SQLite."""
from decimal import Decimal

import pytest

from baqala import config, db, mssql
from baqala.errors import POSError, ValidationError
from baqala.services import auth, inventory, parties, products, reports, sales
from baqala.services.sales import CartLine


def test_translate_sqlite_specific_sql():
    sql, params = mssql.translate("SELECT * FROM t WHERE date(t.created_at) = :d ORDER BY x LIMIT ?", {"d": "2026-01-01"})
    assert sql == "SELECT * FROM t WHERE CAST(t.created_at AS DATE) = ? ORDER BY x OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
    assert params == ["2026-01-01"]
    assert mssql.translate("SELECT 'حبة', 'x', 'it''s'")[0] == "SELECT N'حبة', 'x', 'it''s'"


def test_db_name_validation():
    assert mssql.check_db_name("BaqalaPOS") == "BaqalaPOS"
    for bad in ["", "1abc", "a b", "x];DROP", "قاعدة"]:
        with pytest.raises(ValidationError):
            mssql.check_db_name(bad)


def test_db_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    assert config.load_db_config().engine == "mssql"
    cfg = config.DatabaseConfig(server=r".\SQLEXPRESS", database="BaqalaPOS", auth="sql",
                                username="pos", password="p@ss;word=}")
    config.save_db_config(cfg)
    text = config.db_ini_path().read_text(encoding="utf-8")
    assert "p@ss" not in text
    assert config.load_db_config() == cfg


def test_sqlite_fallback_when_existing_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    db.connect(config.db_path()).close()
    assert config.load_db_config().engine == "sqlite"
    c = db.open_database()
    assert db.dialect(c) == "sqlite"
    c.close()


def test_rollback_on_error_keeps_data_consistent(conn, admin, make_product):
    pid = make_product("ماء", price="100")
    inventory.add_opening_stock(conn, admin, pid, 2, 50)
    with pytest.raises(POSError):
        sales.create_sale(conn, admin, [CartLine(pid, Decimal(1)), CartLine(pid, Decimal(5))])
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    assert conn.execute("SELECT SUM(qty_remaining) FROM batches WHERE product_id = ?", (pid,)).fetchone()[0] == 2000
    with pytest.raises(ValidationError):
        with db.transaction(conn):
            products.create_product(conn, admin, {"name": "مؤقت", "sell_price": "1"})
            raise ValidationError("x")
    assert conn.execute("SELECT COUNT(*) FROM products WHERE name = ?", ("مؤقت",)).fetchone()[0] == 0


def test_duplicate_barcode_is_friendly_error(conn, make_product):
    make_product("أ", barcode="123")
    with pytest.raises(ValidationError):
        make_product("ب", barcode="123")


def test_transfer_sqlite_to_sqlserver(engine, conn, tmp_path):
    if engine != "mssql":
        pytest.skip("SQL Server فقط")
    from baqala import transfer
    src = db.connect(tmp_path / "old.db")
    auth.ensure_default_admin(src)
    adm = auth.authenticate(src, "admin", "admin")
    pid = products.create_product(src, adm, {"name": "سكر", "sell_price": "500", "is_weighted": True})
    inventory.add_opening_stock(src, adm, pid, Decimal("10.5"), 400, expiry_date="2030-01-01")
    cid = parties.save_party(src, adm, "customer", {"name": "سالم", "credit_limit": "10000"})
    sales.create_sale(src, adm, [CartLine(pid, Decimal("0.250"))], "credit", cid, paid=0)
    expected = reports.inventory_value(src)
    src.close()

    counts = transfer.sqlite_to_mssql(tmp_path / "old.db", conn)
    assert counts["sales"] == 1 and counts["batches"] == 1
    assert reports.inventory_value(conn) == expected
    assert parties.balance(conn, "customer", cid) == Decimal("125")
    assert auth.authenticate(conn, "admin", "admin").username == "admin"
    new_pid = products.create_product(conn, auth.authenticate(conn, "admin", "admin"),
                                      {"name": "جديد", "sell_price": "1"})
    assert new_pid > pid
    with pytest.raises(ValidationError):
        transfer.sqlite_to_mssql(tmp_path / "old.db", conn)
