"""العملاء والموردين: البيانات، الديون، السداد، كشف الحساب."""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget)

from ..money import fmt_money, int_to_money
from ..services import parties
from .dialogs import ok_cancel
from .widgets import DecimalEdit, Table, guarded, show_error, show_info, title_label

LABELS = {
    "customer": {"title": "العملاء والديون", "one": "عميل", "pay": "استلام سداد من العميل", "debt": "إجمالي ديون العملاء"},
    "supplier": {"title": "الموردين والديون", "one": "مورد", "pay": "تسديد للمورد", "debt": "إجمالي ديون الموردين (علينا)"},
}


class PartyDialog(QDialog):
    def __init__(self, ctx, kind, party=None, parent=None):
        super().__init__(parent)
        self.ctx, self.kind, self.party = ctx, kind, party
        self.setWindowTitle(("تعديل " if party else "إضافة ") + LABELS[kind]["one"])
        self.setMinimumWidth(420)
        f = QFormLayout(self)
        self.name, self.phone, self.address, self.notes = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.opening = DecimalEdit(2)
        self.active = QCheckBox("نشط")
        self.active.setChecked(True)
        f.addRow("الاسم *", self.name)
        f.addRow("الهاتف", self.phone)
        f.addRow("العنوان", self.address)
        if kind == "customer":
            self.limit = DecimalEdit(2)
            f.addRow("السقف الائتماني (أعلى دين) *", self.limit)
            f.addRow("", QLabel("<small>0 = لا يُسمح بالبيع الآجل لهذا العميل</small>"))
        f.addRow("رصيد سابق (دين افتتاحي)", self.opening)
        f.addRow("ملاحظات", self.notes)
        f.addRow("", self.active)
        if party:
            self.name.setText(party["name"])
            self.phone.setText(party["phone"])
            self.address.setText(party["address"])
            self.notes.setText(party["notes"])
            self.opening.set_value(int_to_money(party["opening_balance"]))
            self.active.setChecked(bool(party["active"]))
            if kind == "customer":
                self.limit.set_value(int_to_money(party["credit_limit"]))
        f.addRow(ok_cancel(self))

    def accept(self):
        data = {"name": self.name.text(), "phone": self.phone.text(), "address": self.address.text(),
                "notes": self.notes.text(), "active": self.active.isChecked()}
        ok = guarded(self, lambda: (data.update(opening_balance=self.opening.value(),
                                                **({"credit_limit": self.limit.value()} if self.kind == "customer" else {})),
                                    parties.save_party(self.ctx.conn, self.ctx.user, self.kind, data,
                                                       self.party["id"] if self.party else None)))
        if ok:
            super().accept()


class PaymentDialog(QDialog):
    def __init__(self, ctx, kind, party, parent=None):
        super().__init__(parent)
        self.ctx, self.kind, self.party = ctx, kind, party
        self.setWindowTitle(LABELS[kind]["pay"])
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>{party['name']}</b> — الدين الحالي: {fmt_money(int_to_money(party['balance']), True)}"))
        self.amount = DecimalEdit(2)
        self.note = QLineEdit()
        f.addRow("المبلغ", self.amount)
        f.addRow("ملاحظة", self.note)
        f.addRow(ok_cancel(self))

    def accept(self):
        if guarded(self, lambda: parties.add_payment(self.ctx.conn, self.ctx.user, self.kind, self.party["id"],
                                                     self.amount.value(), self.note.text())):
            super().accept()


class PartiesPage(QWidget):
    def __init__(self, ctx, kind, parent=None):
        super().__init__(parent)
        self.ctx, self.conn, self.kind = ctx, ctx.conn, kind
        L = LABELS[kind]
        lay = QVBoxLayout(self)
        lay.addWidget(title_label(L["title"]))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الهاتف")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        self.show_inactive = QCheckBox("إظهار الموقوفين")
        self.show_inactive.toggled.connect(self.refresh)
        top.addWidget(self.show_inactive)
        edit_perm = "customer.edit" if kind == "customer" else "supplier.manage"
        pay_perm = "customer.payment" if kind == "customer" else "supplier.manage"
        for text, slot, perm in [(f"إضافة {L['one']}", self.add, edit_perm), ("تعديل", self.edit, edit_perm),
                                 (L["pay"], self.pay, pay_perm), ("كشف حساب", self.statement, None)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setEnabled(perm is None or ctx.user.can(perm))
            top.addWidget(b)
        lay.addLayout(top)
        headers = ["الاسم", "الهاتف", "العنوان", "الدين الحالي"]
        if kind == "customer":
            headers += ["السقف الائتماني", "المتاح"]
        self.table = Table(headers)
        self.table.doubleClicked.connect(self.statement)
        lay.addWidget(self.table)
        self.total = QLabel()
        self.total.setStyleSheet("font-size:14pt;font-weight:bold;color:#c62828;")
        lay.addWidget(self.total)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        rows = parties.list_parties(self.conn, self.kind, self.search.text(), self.show_inactive.isChecked())
        self.rows = {r["id"]: r for r in rows}
        data = []
        for r in rows:
            line = [r["name"], r["phone"], r["address"], fmt_money(int_to_money(r["balance"]))]
            if self.kind == "customer":
                line += [fmt_money(int_to_money(r["credit_limit"])),
                         fmt_money(int_to_money(max(r["credit_limit"] - r["balance"], 0)))]
            data.append(line)
        self.table.fill(data, keys=[r["id"] for r in rows])
        if self.kind == "customer":
            for i, r in enumerate(rows):
                if r["balance"] > 0 and r["balance"] >= r["credit_limit"]:
                    self.table.color_row(i, QColor("#ffebee"))
        self.total.setText(f"{LABELS[self.kind]['debt']}: {fmt_money(parties.total_debts(self.conn, self.kind), True)}")

    def _selected(self):
        pid = self.table.selected_key()
        if pid is None:
            show_error(self, "اختر من الجدول")
            return None
        return parties.get_party(self.conn, self.kind, pid)

    def add(self):
        if PartyDialog(self.ctx, self.kind, parent=self).exec_():
            self.refresh()

    def edit(self):
        p = self._selected()
        if p and PartyDialog(self.ctx, self.kind, p, self).exec_():
            self.refresh()

    def pay(self):
        p = self._selected()
        if p:
            if p["balance"] <= 0:
                show_info(self, "لا يوجد دين مستحق")
                return
            if PaymentDialog(self.ctx, self.kind, p, self).exec_():
                self.refresh()

    def statement(self, *_):
        p = self._selected()
        if not p:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"كشف حساب: {p['name']}")
        dlg.resize(720, 480)
        lay = QVBoxLayout(dlg)
        t = Table(["التاريخ", "البيان", "مدين (عليه)", "دائن (سداد)", "الرصيد"], stretch_col=1)
        rows = parties.statement(self.conn, self.kind, p["id"])
        t.fill([[d, desc, fmt_money(dr), fmt_money(cr), fmt_money(bal)] for d, desc, dr, cr, bal in rows])
        lay.addWidget(t)
        lay.addWidget(QLabel(f"<b>الرصيد الحالي: {fmt_money(int_to_money(p['balance']), True)}</b>"))
        b = QPushButton("تصدير CSV")
        b.clicked.connect(lambda: t.export_csv(dlg, f"statement_{p['id']}.csv"))
        lay.addWidget(b)
        dlg.exec_()
