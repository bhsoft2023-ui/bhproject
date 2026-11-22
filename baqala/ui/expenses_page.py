"""المصروفات."""
from datetime import date

from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..money import fmt_money, int_to_money
from ..services import expenses
from .widgets import DateEdit, DecimalEdit, Table, confirm, guarded, show_error, title_label


class ExpensesPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("المصروفات"))
        form = QHBoxLayout()
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(expenses.EXPENSE_CATEGORIES)
        self.amount = DecimalEdit(2, "المبلغ")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("البيان")
        self.date = DateEdit()
        add = QPushButton("إضافة مصروف")
        add.clicked.connect(self.add)
        for w in (QLabel("النوع:"), self.category, self.amount, self.desc, self.date, add):
            form.addWidget(w)
        lay.addLayout(form)
        flt = QHBoxLayout()
        today = date.today()
        self.d_from, self.d_to = DateEdit(today.replace(day=1)), DateEdit(today)
        show = QPushButton("عرض")
        show.clicked.connect(self.refresh)
        delete = QPushButton("حذف المحدد")
        delete.clicked.connect(self.delete)
        for w in (QLabel("من:"), self.d_from, QLabel("إلى:"), self.d_to, show, delete):
            flt.addWidget(w)
        flt.addStretch()
        lay.addLayout(flt)
        self.table = Table(["التاريخ", "النوع", "المبلغ", "البيان", "المستخدم"], stretch_col=3)
        lay.addWidget(self.table)
        self.total = QLabel()
        self.total.setStyleSheet("font-size:14pt;font-weight:bold;")
        lay.addWidget(self.total)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        rows = expenses.list_expenses(self.conn, self.d_from.iso(), self.d_to.iso())
        self.table.fill([[r["expense_date"], r["category"], fmt_money(int_to_money(r["amount"])), r["description"],
                          r["username"] or ""] for r in rows], keys=[r["id"] for r in rows])
        self.total.setText(f"الإجمالي: {fmt_money(int_to_money(sum(r['amount'] for r in rows)), True)}")

    def add(self):
        if guarded(self, lambda: expenses.add_expense(self.conn, self.ctx.user, self.category.currentText(),
                                                      self.amount.value(), self.desc.text(), self.date.iso())):
            self.amount.clear()
            self.desc.clear()
            self.refresh()

    def delete(self):
        eid = self.table.selected_key()
        if eid is None:
            show_error(self, "اختر مصروفاً")
            return
        if confirm(self, "حذف المصروف المحدد؟"):
            guarded(self, expenses.delete_expense, self.conn, self.ctx.user, eid)
            self.refresh()
