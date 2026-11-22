"""اختبار دخان للواجهة: إنشاء كل الصفحات وإتمام بيع نقدي عبر صفحة البيع (بدون شاشة)."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Ctx:
    def __init__(self, conn, user):
        from baqala import config
        self.conn, self.user, self.window = conn, user, None
        self.db_config = config.DatabaseConfig(engine=getattr(conn, "dialect", "sqlite"))

    def status(self, text):
        pass

    def run_backup(self, tag=""):
        pass

    def on_close(self):
        pass


def test_main_window_and_cash_sale(qapp, conn, admin, make_product, monkeypatch):
    from baqala.services import inventory, settings
    from baqala.ui import sale_page
    from baqala.ui.main_window import MainWindow

    settings.set_value(conn, "auto_print", "0")
    pid = make_product(barcode="111", price="500")
    inventory.add_opening_stock(conn, admin, pid, Decimal(10), Decimal(300))
    monkeypatch.setattr(sale_page, "confirm", lambda *a, **k: True, raising=False)
    w = MainWindow(Ctx(conn, admin))
    assert w.nav.count() == 11
    page = w.stack.widget(0)
    page.on_barcode("111")
    page.on_barcode("2*111")
    assert page.cart_total() == Decimal(1500)
    page.paid.setText("2000")
    page.complete()
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 1
    assert inventory.sellable_stock(conn, pid) == 7000
    for i in range(w.stack.count()):
        w.nav.setCurrentRow(i)
        qapp.processEvents()
    w.close()


def test_sale_page_guards(qapp, conn, admin, make_product, monkeypatch):
    from baqala.services import inventory, settings
    from baqala.ui import sale_page

    settings.set_value(conn, "auto_print", "0")
    errors = []
    monkeypatch.setattr(sale_page, "show_error", lambda parent, msg: errors.append(str(msg)))
    pid = make_product(barcode="222", price="500")
    inventory.add_opening_stock(conn, admin, pid, Decimal(10), Decimal(300))
    page = sale_page.SalePage(Ctx(conn, admin), "cash")

    page.on_barcode("0*222")
    assert page.cart == [] and errors

    page.on_barcode("222")
    conn.execute("UPDATE products SET sell_price = 60000 WHERE id = ?", (pid,))
    page.paid.setText("500")
    page.complete()
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    assert page.cart_total() == Decimal(600)


def test_inactive_new_user_cannot_login(conn, admin):
    import pytest as _pytest
    from baqala.errors import POSError
    from baqala.services import auth

    auth.create_user(conn, admin, "off", "موقوف", "1234", "cashier", active=False)
    with _pytest.raises(POSError):
        auth.authenticate(conn, "off", "1234")
