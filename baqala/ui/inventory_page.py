"""المخزون: الدفعات، تنبيهات النقص والصلاحية، الإتلاف، وإضافة رصيد."""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget,
                             QVBoxLayout, QWidget)

from ..money import fmt_money, fmt_qty, int_to_money, int_to_qty
from ..services import inventory, products, settings
from .dialogs import ProductPicker, ok_cancel
from .widgets import DecimalEdit, OptionalDateEdit, Table, guarded, show_error, title_label


class AddStockDialog(QDialog):
    def __init__(self, ctx, product, parent=None):
        super().__init__(parent)
        self.ctx, self.product = ctx, product
        self.setWindowTitle("إضافة رصيد (افتتاحي / تسوية جرد)")
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>{product['name']}</b>"))
        self.qty = DecimalEdit(3 if product["is_weighted"] else 0)
        self.cost = DecimalEdit(2)
        self.cost.set_value(int_to_money(product["cost_price"]))
        self.expiry = OptionalDateEdit()
        f.addRow(f"الكمية ({product['unit']})", self.qty)
        f.addRow("تكلفة الوحدة", self.cost)
        f.addRow("تاريخ الانتهاء", self.expiry)
        f.addRow(ok_cancel(self))

    def accept(self):
        if guarded(self, inventory.add_opening_stock, self.ctx.conn, self.ctx.user, self.product["id"],
                   self.qty.value(), self.cost.value(), self.expiry.iso()) is not None:
            super().accept()


class WriteOffDialog(QDialog):
    def __init__(self, ctx, batch, parent=None):
        super().__init__(parent)
        self.ctx, self.batch = ctx, batch
        self.setWindowTitle("إتلاف / تسوية")
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>{batch['product_name']}</b> — رصيد الدفعة: {fmt_qty(int_to_qty(batch['qty_remaining']))}"))
        self.qty = DecimalEdit(3)
        self.qty.set_value(int_to_qty(batch["qty_remaining"]))
        self.reason = QLineEdit("منتهي الصلاحية")
        f.addRow("الكمية", self.qty)
        f.addRow("السبب", self.reason)
        f.addRow(ok_cancel(self))

    def accept(self):
        if guarded(self, lambda: inventory.write_off(self.ctx.conn, self.ctx.user, self.batch["id"],
                                                     self.qty.value(), self.reason.text()) or True):
            super().accept()


class InventoryPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("المخزون والصلاحية"))
        btns = QHBoxLayout()
        for text, slot in [("إضافة رصيد لصنف", self.add_stock), ("إتلاف/تسوية الدفعة المحددة", self.write_off),
                           ("تحديث", self.refresh)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("تصفية باسم الصنف")
        self.filter.textChanged.connect(self.refresh)
        btns.addWidget(self.filter)
        lay.addLayout(btns)
        self.tabs = QTabWidget()
        self.batches = Table(["الصنف", "الكمية المتبقية", "الوحدة", "تكلفة الوحدة", "تاريخ الانتهاء", "تاريخ الاستلام", "المورد"])
        self.expiry = Table(["الصنف", "الكمية", "تاريخ الانتهاء", "الحالة"])
        self.low = Table(["الصنف", "المخزون الحالي", "حد التنبيه", "الوحدة"])
        self.tabs.addTab(self.batches, "الدفعات الحالية")
        self.tabs.addTab(self.expiry, "تنبيهات الصلاحية")
        self.tabs.addTab(self.low, "نقص المخزون")
        lay.addWidget(self.tabs)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        term = self.filter.text().strip()
        rows = [r for r in inventory.list_batches(self.conn) if not term or term in r["product_name"]]
        self.batch_rows = {r["id"]: r for r in rows}
        self.batches.fill(
            [[r["product_name"], fmt_qty(int_to_qty(r["qty_remaining"])), r["unit"], fmt_money(int_to_money(r["unit_cost"])),
              r["expiry_date"] or "—", r["received_at"][:10], r["supplier_name"] or ""] for r in rows],
            keys=[r["id"] for r in rows],
        )
        days = settings.get_int(self.conn, "expiry_warning_days", 30)
        alerts = inventory.expiry_alerts(self.conn, days)
        self.expiry_rows = {a["row"]["id"]: a["row"] for a in alerts}
        self.expiry.fill(
            [[a["row"]["product_name"], fmt_qty(int_to_qty(a["row"]["qty_remaining"])), a["row"]["expiry_date"],
              "منتهي منذ %d يوم" % -a["days_left"] if a["expired"] else "ينتهي خلال %d يوم" % a["days_left"]]
             for a in alerts],
            keys=[a["row"]["id"] for a in alerts],
        )
        for i, a in enumerate(alerts):
            self.expiry.color_row(i, QColor("#ffcdd2" if a["expired"] else "#fff3e0"))
        low = products.low_stock(self.conn)
        self.low.fill([[r["name"], fmt_qty(int_to_qty(r["stock"])), fmt_qty(int_to_qty(r["min_qty"])), r["unit"]] for r in low])
        self.tabs.setTabText(1, f"تنبيهات الصلاحية ({len(alerts)})")
        self.tabs.setTabText(2, f"نقص المخزون ({len(low)})")

    def add_stock(self):
        dlg = ProductPicker(self.conn, "", self)
        if dlg.exec_() and dlg.selected:
            if AddStockDialog(self.ctx, products.get_product(self.conn, dlg.selected["id"]), self).exec_():
                self.refresh()

    def write_off(self):
        table = self.tabs.currentWidget()
        if table is self.low:
            show_error(self, "اختر دفعة من «الدفعات الحالية» أو «تنبيهات الصلاحية»")
            return
        bid = table.selected_key()
        rows = self.batch_rows if table is self.batches else self.expiry_rows
        if bid is None or bid not in rows:
            show_error(self, "اختر دفعة من الجدول")
            return
        if WriteOffDialog(self.ctx, rows[bid], self).exec_():
            self.refresh()
