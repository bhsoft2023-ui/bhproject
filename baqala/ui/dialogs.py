"""نوافذ حوار مشتركة: اختيار صنف، إدخال كمية/وزن."""
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QVBoxLayout)

from ..errors import POSError
from ..money import fmt_money, fmt_qty, int_to_money, int_to_qty, line_total
from ..services import products
from .widgets import DecimalEdit, Table, show_error


def ok_cancel(dialog):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText("موافق")
    bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


class ProductPicker(QDialog):
    """بحث عن صنف بالاسم أو الباركود أو التصنيف واختياره."""

    def __init__(self, conn, term="", parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("بحث عن صنف")
        self.resize(760, 480)
        self.selected = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit(term)
        self.search.setPlaceholderText("اسم الصنف أو الباركود")
        self.category = QComboBox()
        self.category.addItem("كل التصنيفات", None)
        for c in products.list_categories(conn):
            self.category.addItem(c["name"], c["id"])
        top.addWidget(self.search, 3)
        top.addWidget(self.category, 1)
        lay.addLayout(top)
        self.table = Table(["الصنف", "الباركود", "التصنيف", "السعر", "المتوفر"])
        lay.addWidget(self.table)
        lay.addWidget(ok_cancel(self))
        self.search.textChanged.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.table.doubleClicked.connect(self.accept)
        self.search.returnPressed.connect(self._enter)
        self.refresh()

    def _enter(self):
        if self.table.rowCount():
            if self.table.currentRow() < 0:
                self.table.selectRow(0)
            self.accept()

    def refresh(self):
        self.rows = products.search_products(self.conn, self.search.text(), self.category.currentData())
        self.table.fill(
            [[r["name"], r["barcode"] or "", r["category_name"] or "", fmt_money(int_to_money(r["sell_price"])),
              f"{fmt_qty(int_to_qty(r['stock']))} {r['unit']}"] for r in self.rows],
            keys=[r["id"] for r in self.rows],
        )
        if self.rows:
            self.table.selectRow(0)

    def accept(self):
        pid = self.table.selected_key()
        if pid is None:
            return
        self.selected = next(r for r in self.rows if r["id"] == pid)
        super().accept()


class QuantityDialog(QDialog):
    """إدخال الكمية؛ للأصناف الموزونة 3 خانات عشرية مع حساب السعر فوراً."""

    def __init__(self, product, current=None, parent=None):
        super().__init__(parent)
        self.product = product
        weighted = bool(product["is_weighted"])
        self.setWindowTitle("الوزن" if weighted else "الكمية")
        self.price = int_to_money(product["sell_price"])
        lay = QFormLayout(self)
        lay.addRow(QLabel(f"<b>{product['name']}</b>"))
        lay.addRow("السعر:", QLabel(f"{fmt_money(self.price)} / {product['unit']}"))
        self.edit = DecimalEdit(3 if weighted else 0)
        f = QFont()
        f.setPointSize(18)
        self.edit.setFont(f)
        if current is not None:
            self.edit.set_value(current)
        lay.addRow(f"{'الوزن' if weighted else 'الكمية'} ({product['unit']}):", self.edit)
        self.total = QLabel("")
        self.total.setStyleSheet("font-size:14pt;font-weight:bold;color:#2e7d32;")
        lay.addRow("المبلغ:", self.total)
        lay.addRow(ok_cancel(self))
        self.edit.textChanged.connect(self._update)
        self.edit.selectAll()
        self._update()
        self.value = None

    def _update(self):
        try:
            self.total.setText(fmt_money(line_total(self.edit.value(), self.price), True))
        except (POSError, ArithmeticError):
            self.total.setText("-")

    def accept(self):
        try:
            v = self.edit.value()
        except POSError as e:
            show_error(self, e)
            return
        if v <= 0:
            show_error(self, "أدخل كمية أكبر من صفر")
            return
        self.value = v
        super().accept()
