"""صفحة البيع (نقدي / آجل) — مصممة للسرعة: الماسح، الاختصارات، والتركيز الدائم على حقل الباركود."""
from decimal import Decimal

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QShortcut, QVBoxLayout, QWidget, QCompleter)

from ..errors import POSError
from ..money import fmt_money, fmt_qty, int_to_money, int_to_qty, line_total, qty
from ..scan import parse_scan_input
from ..services import inventory, parties, products, sales, settings
from . import receipt
from .barcode_input import BarcodeEdit, ScanCatcher
from .dialogs import ProductPicker, QuantityDialog
from .widgets import DecimalEdit, Table, confirm, guarded, show_error, title_label

COLS = ["الصنف", "الكمية", "الوحدة", "السعر", "الإجمالي"]


class SalePage(QWidget):
    def __init__(self, ctx, mode="cash", parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.conn = ctx.conn
        self.mode = mode
        self.cart = []  # dict(product, qty)
        self.last_sale_id = None
        self._build()
        self.catcher = ScanCatcher(self.barcode, self)
        self.catcher.scanned.connect(self.on_barcode)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self.catcher)

    # ------------------------------------------------------------ UI
    def _build(self):
        credit = self.mode == "credit"
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        head = title_label("بيع آجل (على الحساب)" if credit else "بيع نقدي", 18)
        head.setStyleSheet(f"color:{'#c62828' if credit else '#2e7d32'};")
        left.addWidget(head)

        if credit:
            row = QHBoxLayout()
            self.customer = QComboBox()
            self.customer.setEditable(True)
            self.customer.setInsertPolicy(QComboBox.NoInsert)
            self.customer.completer().setFilterMode(Qt.MatchContains)
            self.customer.completer().setCompletionMode(QCompleter.PopupCompletion)
            self.customer.currentIndexChanged.connect(self.update_customer_info)
            row.addWidget(QLabel("العميل:"))
            row.addWidget(self.customer, 1)
            self.customer_info = QLabel("")
            self.customer_info.setStyleSheet("font-weight:bold;")
            left.addLayout(row)
            left.addWidget(self.customer_info)

        self.barcode = BarcodeEdit()
        self.barcode.submitted.connect(self.on_barcode)
        left.addWidget(self.barcode)

        self.table = Table(COLS)
        self.table.doubleClicked.connect(self.edit_qty)
        left.addWidget(self.table, 1)

        hint = QLabel("F2 الباركود | F3 بحث | F4 تعديل الكمية | Delete حذف سطر | F12 إتمام البيع | Esc إلغاء الفاتورة")
        hint.setStyleSheet("color:#666;")
        left.addWidget(hint)
        root.addLayout(left, 3)

        side = QVBoxLayout()
        box = QGroupBox("الإجمالي")
        bl = QVBoxLayout(box)
        self.total_lbl = QLabel("0")
        self.total_lbl.setAlignment(Qt.AlignCenter)
        self.total_lbl.setStyleSheet("font-size:34pt;font-weight:bold;color:#0d47a1;")
        bl.addWidget(self.total_lbl)
        self.count_lbl = QLabel("")
        self.count_lbl.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.count_lbl)
        side.addWidget(box)

        form = QFormLayout()
        self.paid = DecimalEdit(2, "0")
        self.paid.setStyleSheet("font-size:16pt;")
        self.paid.textChanged.connect(self.update_totals)
        self.paid.returnPressed.connect(self.barcode.setFocus)
        form.addRow("دفعة مقدمة:" if credit else "المبلغ المستلم:", self.paid)
        self.change_lbl = QLabel("")
        self.change_lbl.setStyleSheet("font-size:16pt;font-weight:bold;")
        form.addRow("المتبقي دين:" if credit else "الباقي للعميل:", self.change_lbl)
        side.addLayout(form)

        def btn(text, slot, color="#455a64"):
            b = QPushButton(text)
            b.setMinimumHeight(44)
            b.setStyleSheet(f"QPushButton{{background:{color};color:white;font-size:12pt;border-radius:4px;}}")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            side.addWidget(b)
            return b

        btn("إتمام البيع (F12)", self.complete, "#2e7d32" if not credit else "#c62828")
        btn("بحث عن صنف (F3)", self.search_product)
        btn("تعديل الكمية/الوزن (F4)", self.edit_qty)
        btn("حذف السطر (Delete)", self.remove_line)
        btn("إلغاء الفاتورة (Esc)", self.clear_cart, "#757575")
        btn("طباعة آخر فاتورة", self.print_last, "#5d4037")
        side.addStretch()
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        root.addWidget(sep)
        root.addLayout(side, 1)

        for key, slot in [("F2", self.barcode.setFocus), ("F3", self.search_product), ("F4", self.edit_qty),
                          ("F12", self.complete), ("Delete", self.remove_line), ("Escape", self.clear_cart)]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def showEvent(self, event):
        super().showEvent(event)
        if self.mode == "credit":
            self.load_customers()
        self.barcode.setFocus()

    # ------------------------------------------------------------ customers
    def load_customers(self):
        current = self.customer.currentData()
        self.customer.blockSignals(True)
        self.customer.clear()
        self.customer.addItem("— اختر العميل —", None)
        for c in parties.list_parties(self.conn, "customer"):
            label = c["name"] + (f" - {c['phone']}" if c["phone"] else "")
            self.customer.addItem(label, c["id"])
        idx = self.customer.findData(current)
        self.customer.setCurrentIndex(max(idx, 0))
        self.customer.blockSignals(False)
        self.update_customer_info()

    def update_customer_info(self):
        cid = self.customer.currentData()
        if not cid:
            self.customer_info.setText("")
            return
        c = parties.get_party(self.conn, "customer", cid)
        bal, limit = int_to_money(c["balance"]), int_to_money(c["credit_limit"])
        avail = max(limit - bal, Decimal(0))
        color = "#c62828" if avail <= 0 else "#2e7d32"
        self.customer_info.setText(
            f"الدين الحالي: {fmt_money(bal)}   |   السقف: {fmt_money(limit)}   |   "
            f"<span style='color:{color}'>المتاح: {fmt_money(avail)}</span>"
        )
        self.update_totals()

    # ------------------------------------------------------------ cart
    def on_barcode(self, text):
        q_text, code = parse_scan_input(text)
        if not code:
            return
        product = products.find_by_barcode(self.conn, code)
        if product is None:
            dlg = ProductPicker(self.conn, code, self)
            if not dlg.exec_() or dlg.selected is None:
                self.barcode.setFocus()
                return
            product = products.get_product(self.conn, dlg.selected["id"])
        quantity = None
        if q_text:
            try:
                quantity = qty(q_text)
            except POSError as e:
                show_error(self, e)
                return
        elif product["is_weighted"]:
            dlg = QuantityDialog(product, parent=self)
            if not dlg.exec_():
                self.barcode.setFocus()
                return
            quantity = dlg.value
        self.add_to_cart(product, quantity or Decimal(1))

    def add_to_cart(self, product, quantity):
        existing = next((l for l in self.cart if l["product"]["id"] == product["id"]), None)
        new_qty = quantity + (existing["qty"] if existing and not product["is_weighted"] else 0)
        if existing and product["is_weighted"]:
            existing = None  # كل وزنة سطر مستقل
        try:
            inventory.validate_qty_for_product(product, quantity)
            self._check_stock(product, new_qty if existing else quantity, exclude=existing)
        except POSError as e:
            show_error(self, e)
            self.barcode.setFocus()
            return
        if existing:
            existing["qty"] = new_qty
            row = self.cart.index(existing)
        else:
            self.cart.append({"product": product, "qty": qty(quantity)})
            row = len(self.cart) - 1
        self.refresh_table()
        self.table.selectRow(row)
        self.barcode.setFocus()

    def _check_stock(self, product, wanted, exclude=None):
        in_cart = sum((l["qty"] for l in self.cart if l["product"]["id"] == product["id"] and l is not exclude),
                      Decimal(0))
        available = int_to_qty(inventory.sellable_stock(self.conn, product["id"]))
        if in_cart + qty(wanted) > available:
            raise POSError(
                f"الكمية غير متوفرة للصنف «{product['name']}». المتاح للبيع: {fmt_qty(available)} {product['unit']}"
                + (f" (في الفاتورة: {fmt_qty(in_cart)})" if in_cart else "")
            )

    def refresh_table(self):
        rows = []
        for l in self.cart:
            p = l["product"]
            price = int_to_money(p["sell_price"])
            rows.append([p["name"], fmt_qty(l["qty"]), p["unit"], fmt_money(price), fmt_money(line_total(l["qty"], price))])
        self.table.fill(rows)
        for r, l in enumerate(self.cart):
            if l["product"]["is_weighted"]:
                self.table.color_row(r, QColor("#fff8e1"))
        self.update_totals()

    def cart_total(self):
        return sum((line_total(l["qty"], int_to_money(l["product"]["sell_price"])) for l in self.cart), Decimal(0))

    def update_totals(self):
        total = self.cart_total()
        self.total_lbl.setText(fmt_money(total, True))
        self.count_lbl.setText(f"عدد الأصناف: {len(self.cart)}")
        try:
            paid = self.paid.value()
        except POSError:
            paid = Decimal(0)
        if self.mode == "cash":
            change = paid - total if self.paid.text().strip() else Decimal(0)
            self.change_lbl.setText(fmt_money(change) if change >= 0 else f"ناقص {fmt_money(-change)}")
            self.change_lbl.setStyleSheet(
                f"font-size:16pt;font-weight:bold;color:{'#2e7d32' if change >= 0 else '#c62828'};")
        else:
            self.change_lbl.setText(fmt_money(max(total - paid, Decimal(0))))

    def edit_qty(self, *_):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.cart):
            return
        line = self.cart[row]
        dlg = QuantityDialog(line["product"], line["qty"], self)
        if dlg.exec_():
            try:
                inventory.validate_qty_for_product(line["product"], dlg.value)
                self._check_stock(line["product"], dlg.value, exclude=line)
            except POSError as e:
                show_error(self, e)
                return
            line["qty"] = qty(dlg.value)
            self.refresh_table()
            self.table.selectRow(row)
        self.barcode.setFocus()

    def remove_line(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.cart):
            del self.cart[row]
            self.refresh_table()
            if self.cart:
                self.table.selectRow(min(row, len(self.cart) - 1))
        self.barcode.setFocus()

    def clear_cart(self, ask=True):
        if self.cart and ask and not confirm(self, "إلغاء الفاتورة الحالية؟"):
            return
        self.cart.clear()
        self.paid.clear()
        self.refresh_table()
        self.barcode.setFocus()

    def search_product(self):
        dlg = ProductPicker(self.conn, "", self)
        if dlg.exec_() and dlg.selected:
            product = products.get_product(self.conn, dlg.selected["id"])
            quantity = Decimal(1)
            if product["is_weighted"]:
                qd = QuantityDialog(product, parent=self)
                if not qd.exec_():
                    return
                quantity = qd.value
            self.add_to_cart(product, quantity)
        self.barcode.setFocus()

    # ------------------------------------------------------------ complete
    def complete(self):
        if not self.cart:
            show_error(self, "الفاتورة فارغة")
            return
        total = self.cart_total()
        try:
            paid = self.paid.value()
        except POSError as e:
            show_error(self, e)
            return
        customer_id = None
        if self.mode == "cash":
            if self.paid.text().strip() and paid < total:
                show_error(self, "المبلغ المستلم أقل من الإجمالي")
                return
        else:
            customer_id = self.customer.currentData()
            if not customer_id:
                show_error(self, "اختر العميل أولاً")
                self.customer.setFocus()
                return
            if paid > total:
                show_error(self, "الدفعة المقدمة أكبر من الإجمالي")
                return
            if not confirm(self, f"تأكيد البيع الآجل بمبلغ {fmt_money(total, True)}"
                                 f"\nدين جديد على العميل: {fmt_money(total - paid, True)}"):
                return
        lines = [sales.CartLine(l["product"]["id"], l["qty"]) for l in self.cart]
        sale_id = guarded(self, sales.create_sale, self.conn, self.ctx.user, lines, self.mode, customer_id,
                          paid if self.mode == "credit" else None)
        if sale_id is None:
            self.barcode.setFocus()
            return
        self.last_sale_id = sale_id
        change_text = ""
        if self.mode == "cash" and self.paid.text().strip():
            change_text = f"   الباقي: {fmt_money(paid - total)}"
        self.ctx.status(f"تم حفظ الفاتورة رقم {sale_id} بمبلغ {fmt_money(total, True)}{change_text}")
        if settings.get(self.conn, "auto_print") == "1":
            guarded(self, receipt.print_receipt, self.conn, sale_id)
        self.clear_cart(ask=False)
        if self.mode == "credit":
            self.update_customer_info()

    def print_last(self):
        if not self.last_sale_id:
            show_error(self, "لا توجد فاتورة سابقة في هذه الجلسة")
            return
        guarded(self, receipt.print_receipt, self.conn, self.last_sale_id)
        self.barcode.setFocus()
