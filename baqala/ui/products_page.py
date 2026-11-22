"""إدارة الأصناف والتصنيفات والأسعار."""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)
from PyQt5.QtCore import Qt

from ..money import fmt_money, fmt_qty, int_to_money, int_to_qty
from ..services import products
from .dialogs import ok_cancel
from .widgets import DecimalEdit, OptionalDateEdit, Table, combo_set_data, confirm, guarded, show_error, show_info, title_label


class ProductDialog(QDialog):
    def __init__(self, ctx, product=None, parent=None):
        super().__init__(parent)
        self.ctx, self.conn, self.product = ctx, ctx.conn, product
        self.setWindowTitle("تعديل صنف" if product else "إضافة صنف")
        self.setMinimumWidth(460)
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("امسح الباركود هنا")
        self.category = QComboBox()
        self.category.addItem("بدون تصنيف", None)
        for c in products.list_categories(self.conn):
            self.category.addItem(c["name"], c["id"])
        self.is_weighted = QCheckBox("يُباع بالوزن (كميات عشرية مثل 0.250)")
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(["حبة", "كجم", "جرام", "لتر", "كرتون", "علبة", "كيس", "ربطة"])
        self.sell_price = DecimalEdit(2)
        self.cost_price = DecimalEdit(2)
        self.min_qty = DecimalEdit(3)
        self.track_expiry = QCheckBox("تتبع تاريخ الانتهاء (مواد غذائية)")
        f.addRow("اسم الصنف *", self.name)
        f.addRow("الباركود", self.barcode)
        f.addRow("التصنيف", self.category)
        f.addRow("", self.is_weighted)
        f.addRow("الوحدة", self.unit)
        f.addRow("سعر البيع (للوحدة) *", self.sell_price)
        f.addRow("سعر التكلفة", self.cost_price)
        f.addRow("حد التنبيه (أقل كمية)", self.min_qty)
        f.addRow("", self.track_expiry)
        self.is_weighted.toggled.connect(lambda on: self.unit.setCurrentText("كجم" if on else "حبة"))
        if product is None:
            self.initial_qty = DecimalEdit(3)
            self.initial_expiry = OptionalDateEdit()
            f.addRow(QLabel("<b>رصيد افتتاحي (اختياري)</b>"))
            f.addRow("الكمية الحالية", self.initial_qty)
            f.addRow("تاريخ الانتهاء", self.initial_expiry)
        else:
            self.name.setText(product["name"])
            self.barcode.setText(product["barcode"] or "")
            combo_set_data(self.category, product["category_id"])
            self.is_weighted.setChecked(bool(product["is_weighted"]))
            self.unit.setCurrentText(product["unit"])
            self.sell_price.set_value(int_to_money(product["sell_price"]))
            self.cost_price.set_value(int_to_money(product["cost_price"]))
            self.min_qty.set_value(int_to_qty(product["min_qty"]))
            self.track_expiry.setChecked(bool(product["track_expiry"]))
        f.addRow(ok_cancel(self))

    def keyPressEvent(self, event):
        # قارئ الباركود يرسل Enter: ننقل التركيز بدل حفظ النافذة
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.focusWidget() is self.barcode:
            self.category.setFocus()
            return
        super().keyPressEvent(event)

    def data(self):
        return {
            "name": self.name.text(), "barcode": self.barcode.text(), "category_id": self.category.currentData(),
            "is_weighted": self.is_weighted.isChecked(), "unit": self.unit.currentText(),
            "sell_price": self.sell_price.value(), "cost_price": self.cost_price.value(),
            "min_qty": self.min_qty.value(), "track_expiry": self.track_expiry.isChecked(),
        }

    def accept(self):
        def save():
            if self.product:
                products.update_product(self.conn, self.ctx.user, self.product["id"], self.data())
            else:
                q = self.initial_qty.value() if self.initial_qty.text().strip() else None
                products.create_product(self.conn, self.ctx.user, self.data(), q, self.initial_expiry.iso())
            return True
        if guarded(self, save):
            super().accept()


class CategoriesDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("التصنيفات")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in [("إضافة", self.add), ("تعديل", self.rename), ("حذف", self.delete)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for c in products.list_categories(self.ctx.conn):
            it = QListWidgetItem(c["name"])
            it.setData(Qt.UserRole, c["id"])
            self.list.addItem(it)

    def _current(self):
        it = self.list.currentItem()
        return (it.data(Qt.UserRole), it.text()) if it else (None, None)

    def add(self):
        name, ok = QInputDialog.getText(self, "تصنيف جديد", "الاسم:")
        if ok and guarded(self, products.add_category, self.ctx.conn, self.ctx.user, name):
            self.refresh()

    def rename(self):
        cid, old = self._current()
        if cid:
            name, ok = QInputDialog.getText(self, "تعديل تصنيف", "الاسم:", text=old)
            if ok:
                guarded(self, products.rename_category, self.ctx.conn, self.ctx.user, cid, name)
                self.refresh()

    def delete(self):
        cid, name = self._current()
        if cid and confirm(self, f"حذف التصنيف «{name}»؟ (الأصناف تبقى بدون تصنيف)"):
            guarded(self, products.delete_category, self.ctx.conn, self.ctx.user, cid)
            self.refresh()


class ProductsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("الأصناف والأسعار"))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الباركود (يمكن المسح هنا)")
        self.category = QComboBox()
        self.inactive = QCheckBox("إظهار الموقوفة")
        top.addWidget(self.search, 3)
        top.addWidget(self.category, 1)
        top.addWidget(self.inactive)
        lay.addLayout(top)
        btns = QHBoxLayout()
        can_edit = ctx.user.can("product.edit")
        for text, slot in [("إضافة صنف", self.add), ("تعديل", self.edit), ("تحديث السعر", self.change_price),
                           ("حذف", self.delete), ("التصنيفات", self.categories), ("سجل الأسعار", self.history)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setEnabled(can_edit or text == "سجل الأسعار")
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)
        self.table = Table(["الصنف", "الباركود", "التصنيف", "الوحدة", "سعر البيع", "التكلفة", "المخزون", "حد التنبيه", "الحالة"])
        lay.addWidget(self.table)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.search.textChanged.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.inactive.toggled.connect(self.refresh)
        if can_edit:
            self.table.doubleClicked.connect(self.edit)

    def showEvent(self, e):
        super().showEvent(e)
        self.load_categories()
        self.refresh()

    def load_categories(self):
        cur = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("كل التصنيفات", None)
        for c in products.list_categories(self.conn):
            self.category.addItem(c["name"], c["id"])
        combo_set_data(self.category, cur)
        self.category.blockSignals(False)

    def refresh(self):
        rows = products.search_products(self.conn, self.search.text(), self.category.currentData(),
                                        self.inactive.isChecked(), limit=5000)
        self.rows = {r["id"]: r for r in rows}
        self.table.fill(
            [[r["name"], r["barcode"] or "", r["category_name"] or "", r["unit"],
              fmt_money(int_to_money(r["sell_price"])), fmt_money(int_to_money(r["cost_price"])),
              fmt_qty(int_to_qty(r["stock"])), fmt_qty(int_to_qty(r["min_qty"])),
              "نشط" if r["active"] else "موقوف"] for r in rows],
            keys=[r["id"] for r in rows],
        )
        low = 0
        for i, r in enumerate(rows):
            if r["min_qty"] and r["stock"] <= r["min_qty"]:
                self.table.color_row(i, QColor("#ffebee"))
                low += 1
        self.summary.setText(f"عدد الأصناف: {len(rows)}   |   تحت حد التنبيه: {low}")

    def _selected(self):
        pid = self.table.selected_key()
        if pid is None:
            show_error(self, "اختر صنفاً من الجدول")
        return pid

    def add(self):
        if ProductDialog(self.ctx, parent=self).exec_():
            self.refresh()

    def edit(self, *_):
        pid = self._selected()
        if pid and ProductDialog(self.ctx, products.get_product(self.conn, pid), self).exec_():
            self.refresh()

    def change_price(self):
        pid = self._selected()
        if not pid:
            return
        p = products.get_product(self.conn, pid)
        text, ok = QInputDialog.getText(self, "تحديث السعر", f"سعر البيع الجديد لـ «{p['name']}»:",
                                        text=fmt_money(int_to_money(p["sell_price"])).replace(",", ""))
        if ok:
            guarded(self, products.update_price, self.conn, self.ctx.user, pid, text)
            self.refresh()

    def delete(self):
        pid = self._selected()
        if pid and confirm(self, f"حذف الصنف «{self.rows[pid]['name']}»؟"):
            result = guarded(self, products.delete_product, self.conn, self.ctx.user, pid)
            if result == "deactivated":
                show_info(self, "للصنف حركات سابقة، لذلك تم إيقافه بدلاً من حذفه نهائياً للحفاظ على التقارير.")
            self.refresh()

    def categories(self):
        CategoriesDialog(self.ctx, self).exec_()
        self.load_categories()
        self.refresh()

    def history(self):
        pid = self._selected()
        if not pid:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("سجل تغيير الأسعار")
        dlg.resize(500, 350)
        lay = QVBoxLayout(dlg)
        t = Table(["التاريخ", "السعر القديم", "السعر الجديد", "المستخدم"])
        t.fill([[h["changed_at"], fmt_money(int_to_money(h["old_price"])), fmt_money(int_to_money(h["new_price"])),
                 h["username"] or ""] for h in products.price_history(self.conn, pid)])
        lay.addWidget(t)
        dlg.exec_()
