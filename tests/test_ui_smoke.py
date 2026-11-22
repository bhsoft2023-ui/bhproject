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
        self.conn, self.user, self.window = conn, user, None

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
