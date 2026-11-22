from datetime import datetime
from decimal import Decimal

import pytest

from baqala import db
from baqala.errors import ValidationError
from baqala.services import backup, inventory, products, sales
from baqala.services.sales import CartLine


def test_backup_rotation_and_integrity(engine, conn, bk_root, tmp_path, make_product):
    make_product("أرز")
    d = bk_root / "bk"
    extra = tmp_path / "usb"
    for i in range(5):
        backup.create_backup(conn, d, keep=3, extra_dir=extra, now=datetime(2026, 1, 1, 10, i))
    suffix = backup.suffix_for(conn)
    files = backup.list_backups(d, suffix)
    assert len(files) == 3
    if engine == "sqlite":  # ملف .bak في الحاوية مملوك لمستخدم SQL Server ولا يُنسخ للمجلد الإضافي
        assert len(backup.list_backups(extra, suffix)) == 3
    backup.verify_backup_file(files[0], conn)


def test_is_due():
    now = datetime(2026, 1, 1, 12, 0)
    assert backup.is_due("", 4, now)
    assert not backup.is_due("2026-01-01 09:00:00", 4, now)
    assert backup.is_due("2026-01-01 08:00:00", 4, now)
    assert not backup.is_due("", 0, now)




def test_restore_roundtrip(tmp_path):
    from baqala.services import auth
    path = tmp_path / "live.db"
    c = db.connect(path)
    auth.ensure_default_admin(c)
    admin = auth.authenticate(c, "admin", "admin")
    products.create_product(c, admin, {"name": "قبل", "sell_price": "1"})
    bk = backup.create_backup(c, tmp_path / "bk")
    products.create_product(c, admin, {"name": "بعد", "sell_price": "1"})
    c.close()
    safety = backup.restore_backup(path, bk, tmp_path / "bk")
    c = db.connect(path)
    assert [r["name"] for r in c.execute("SELECT name FROM products")] == ["قبل"]
    c.close()
    s = db.connect(safety)
    assert len(s.execute("SELECT * FROM products").fetchall()) == 2
    s.close()


def test_restore_rejects_garbage(tmp_path):
    bad = tmp_path / "x.db"
    bad.write_bytes(b"not a database" * 100)
    with pytest.raises(ValidationError):
        backup.verify_backup_file(bad)


def test_data_persists_after_reopen(tmp_path):
    from baqala.services import auth
    path = tmp_path / "p.db"
    c = db.connect(path)
    auth.ensure_default_admin(c)
    admin = auth.authenticate(c, "admin", "admin")
    pid = products.create_product(c, admin, {"name": "ماء", "sell_price": "100"})
    inventory.add_opening_stock(c, admin, pid, 3, 50)
    sales.create_sale(c, admin, [CartLine(pid, Decimal(1))])
    c.close()
    c = db.connect(path)
    assert db.schema_version(c) == len(db.MIGRATIONS)
    assert c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 1
    assert db.integrity_ok(c)
    c.close()


def test_mssql_backup_restore_roundtrip(engine, conn, admin, bk_root, request):
    if engine != "mssql":
        pytest.skip("SQL Server فقط")
    from tests.conftest import drop_mssql_database, mssql_config
    from baqala import mssql
    cfg = mssql_config("BaqalaPOS_restore_test")
    c = mssql.connect(cfg)
    try:
        from baqala.services import auth
        auth.ensure_default_admin(c)
        adm = auth.authenticate(c, "admin", "admin")
        products.create_product(c, adm, {"name": "قبل", "sell_price": "1"})
        bk = backup.create_backup(c, bk_root / "bk")
        assert bk.suffix == ".bak"
        products.create_product(c, adm, {"name": "بعد", "sell_price": "1"})
        c.close()
        safety = backup.restore_mssql_backup(cfg, bk, bk_root / "safety")
        assert safety.exists()
        c = mssql.connect(cfg)
        assert [r["name"] for r in c.execute("SELECT name FROM products")] == ["قبل"]
        assert db.integrity_ok(c)
        with pytest.raises(ValidationError):
            backup.verify_backup_file(bk_root / "missing.bak", c)
    finally:
        c.close()
        drop_mssql_database(cfg)


def test_mssql_rejects_sqlite_file_and_vice_versa(engine, conn, tmp_path):
    if engine == "mssql":
        from baqala.config import DatabaseConfig
        with pytest.raises(ValidationError):
            backup.restore_mssql_backup(DatabaseConfig(), tmp_path / "x.db", tmp_path)
    else:
        with pytest.raises(ValidationError):
            backup.verify_backup_file(tmp_path / "x.bak", conn)
