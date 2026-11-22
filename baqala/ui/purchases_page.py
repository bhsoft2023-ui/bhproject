"""المشتريات: استلام بضاعة من مورد نقداً أو آجلاً مع تواريخ الصلاحية."""
from datetime import date
from decimal import Decimal

from PyQt5.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QRadioButton, QVBoxLayout, QWidget)

from ..errors import POSError
from ..money import fmt_money, fmt_qty, int_to_money, line_total
from ..services import parties, products, purchases
from .barcode_input import BarcodeEdit
from .dialogs import ProductPicker, ok_cancel
from .widgets import DecimalEdit, OptionalDateEdit, Table, confirm, guarded, show_error, show_info, title_label


class LineDialog(QDialog):
    def __init__(self, product, parent=None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("بيانات الصنف المستلم")
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>{product['name']}</b>"))
        self.qty = DecimalEdit(3 if product["is_weighted"] else 0)
        self.cost = DecimalEdit(2)
        self.cost.set_value(int_to_money(product["cost_price"]))
        self.expiry = OptionalDateEdit()
        if product["track_expiry"]:
            self.expiry.set_date(date.today())
        f.addRow(f"الكمية ({product['unit']})", self.qty)
        f.addRow("تكلفة الوحدة", self.cost)
        f.addRow("تاريخ الانتهاء" + (" *" if product["track_expiry"] else ""), self.expiry)
        f.addRow(ok_cancel(self))
        self.line = None

    def accept(self):
        try:
            q, c = self.qty.value(), self.cost.value()
        except POSError as e:
            show_error(self, e)
            return
        if q <= 0:
            show_error(self, "أدخل الكمية")
            return
        if self.product["track_expiry"] and not self.expiry.iso():
            show_error(self, "هذا الصنف يتطلب تاريخ انتهاء")
            return
        self.line = purchases.PurchaseLine(self.product["id"], q, c, self.expiry.iso())
        super().accept()


class PurchasesPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        self.lines = []
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("المشتريات واستلام البضاعة"))
        row = QHBoxLayout()
        self.cash = QRadioButton("شراء نقدي")
        self.credit = QRadioButton("شراء آجل")
        self.cash.setChecked(True)
        self.supplier = QComboBox()
        row.addWidget(self.cash)
        row.addWidget(self.credit)
        row.addWidget(QLabel("المورد:"))
        row.addWidget(self.supplier, 1)
        row.addWidget(QLabel("المدفوع (للآجل):"))
        self.paid = DecimalEdit(2, "0")
        row.addWidget(self.paid)
        lay.addLayout(row)
        self.barcode = BarcodeEdit()
        self.barcode.setPlaceholderText("امسح باركود الصنف أو اكتب اسمه ثم Enter")
        self.barcode.submitted.connect(self.add_line)
        lay.addWidget(self.barcode)
        self.table = Table(["الصنف", "الكمية", "تكلفة الوحدة", "تاريخ الانتهاء", "الإجمالي"])
        lay.addWidget(self.table)
        bottom = QHBoxLayout()
        self.total = QLabel()
        self.total.setStyleSheet("font-size:16pt;font-weight:bold;")
        self.note = QLineEdit()
        self.note.setPlaceholderText("ملاحظة / رقم فاتورة المورد")
        for text, slot in [("حذف السطر", self.remove), ("حفظ فاتورة الشراء", self.save)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        bottom.addWidget(self.note, 1)
        bottom.addWidget(self.total)
        lay.addLayout(bottom)
        lay.addWidget(QLabel("<b>آخر المشتريات</b>"))
        self.history = Table(["رقم", "التاريخ", "المورد", "النوع", "الإجمالي", "المدفوع"], stretch_col=2)
        lay.addWidget(self.history)
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        cur = self.supplier.currentData()
        self.supplier.clear()
        self.supplier.addItem("— بدون مورد —", None)
        for s in parties.list_parties(self.conn, "supplier"):
            self.supplier.addItem(s["name"], s["id"])
        idx = self.supplier.findData(cur)
        self.supplier.setCurrentIndex(max(idx, 0))
        self.load_history()
        self.barcode.setFocus()

    def load_history(self):
        today = date.today()
        rows = purchases.list_purchases(self.conn, today.replace(day=1).isoformat(), today.isoformat())
        self.history.fill([[r["id"], r["created_at"], r["supplier_name"] or "", "آجل" if r["purchase_type"] == "credit" else "نقدي",
                            fmt_money(int_to_money(r["total"])), fmt_money(int_to_money(r["paid"]))] for r in rows])

    def add_line(self, text):
        p = products.find_by_barcode(self.conn, text)
        if p is None:
            dlg = ProductPicker(self.conn, text, self)
            if not dlg.exec_() or not dlg.selected:
                return
            p = dlg.selected
        p = products.get_product(self.conn, p["id"])
        dlg = LineDialog(p, self)
        if dlg.exec_():
            self.lines.append((p, dlg.line))
            self.refresh()
        self.barcode.setFocus()

    def remove(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.lines):
            del self.lines[r]
            self.refresh()

    def refresh(self):
        self.table.fill([[p["name"], f"{fmt_qty(l.qty)} {p['unit']}", fmt_money(l.unit_cost), l.expiry_date or "—",
                          fmt_money(line_total(l.qty, l.unit_cost))] for p, l in self.lines])
        total = sum((line_total(l.qty, l.unit_cost) for _, l in self.lines), Decimal(0))
        self.total.setText(f"الإجمالي: {fmt_money(total, True)}")

    def save(self):
        if not self.lines:
            show_error(self, "لا توجد أصناف")
            return
        kind = "credit" if self.credit.isChecked() else "cash"
        if not confirm(self, "حفظ فاتورة الشراء وإضافة الكميات للمخزون؟"):
            return
        pid = guarded(self, lambda: purchases.create_purchase(
            self.conn, self.ctx.user, [l for _, l in self.lines], kind, self.supplier.currentData(),
            self.paid.value() if kind == "credit" else None, self.note.text()))
        if pid:
            show_info(self, f"تم حفظ فاتورة الشراء رقم {pid}")
            self.lines.clear()
            self.paid.clear()
            self.note.clear()
            self.refresh()
            self.load_history()
