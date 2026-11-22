"""التقارير: المبيعات، الأرباح، المصروفات، قيمة المخزون، الديون."""
from datetime import date, timedelta

from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..money import fmt_money, fmt_qty, int_to_money
from ..services import reports, sales
from . import receipt
from .widgets import Card, DateEdit, Table, guarded, show_error, title_label


class ReportsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("التقارير"))
        flt = QHBoxLayout()
        today = date.today()
        self.d_from, self.d_to = DateEdit(today), DateEdit(today)
        flt.addWidget(QLabel("من:"))
        flt.addWidget(self.d_from)
        flt.addWidget(QLabel("إلى:"))
        flt.addWidget(self.d_to)
        for text, rng in [("اليوم", (today, today)), ("أمس", (today - timedelta(1), today - timedelta(1))),
                          ("آخر 7 أيام", (today - timedelta(6), today)), ("هذا الشهر", (today.replace(day=1), today))]:
            b = QPushButton(text)
            b.clicked.connect(lambda _, r=rng: self.set_range(*r))
            flt.addWidget(b)
        show = QPushButton("عرض التقرير")
        show.setStyleSheet("font-weight:bold;")
        show.clicked.connect(self.refresh)
        flt.addWidget(show)
        flt.addStretch()
        lay.addLayout(flt)

        grid = QGridLayout()
        spec = [
            ("total", "إجمالي المبيعات", "#0d47a1"), ("cash_total", "المبيعات النقدية", "#2e7d32"),
            ("credit_total", "المبيعات الآجلة", "#c62828"), ("count", "عدد الفواتير", "#455a64"),
            ("cost", "تكلفة البضاعة المباعة", "#6d4c41"), ("gross_profit", "إجمالي الربح", "#00897b"),
            ("expenses", "المصروفات", "#e65100"), ("net_profit", "صافي الربح", "#1b5e20"),
            ("inv_cost", "قيمة المخزون (بالتكلفة)", "#4527a0"), ("inv_retail", "قيمة المخزون (بسعر البيع)", "#283593"),
            ("suppliers_debt", "إجمالي ديون الموردين", "#b71c1c"), ("customers_debt", "إجمالي ديون العملاء", "#ad1457"),
        ]
        self.cards = {}
        for i, (key, title, color) in enumerate(spec):
            c = Card(title, color)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)
        lay.addLayout(grid)
        self.note = QLabel()
        self.note.setStyleSheet("color:#666;")
        lay.addWidget(self.note)

        self.tabs = QTabWidget()
        self.daily = Table(["اليوم", "عدد الفواتير", "نقدي", "آجل", "الإجمالي", "الربح"])
        self.invoices = Table(["رقم", "التاريخ", "النوع", "العميل", "الإجمالي", "المدفوع", "الكاشير"], stretch_col=3)
        self.top = Table(["الصنف", "الكمية", "المبيعات", "الربح"])
        self.exp = Table(["نوع المصروف", "الإجمالي"])
        self.tabs.addTab(self.daily, "المبيعات اليومية")
        self.tabs.addTab(self.invoices, "الفواتير")
        self.tabs.addTab(self.top, "الأصناف الأكثر مبيعاً")
        self.tabs.addTab(self.exp, "المصروفات حسب النوع")
        lay.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        exp = QPushButton("تصدير الجدول الحالي (CSV/Excel)")
        exp.clicked.connect(lambda: self.tabs.currentWidget().export_csv(self, "report.csv"))
        rp = QPushButton("إعادة طباعة الفاتورة المحددة")
        rp.clicked.connect(self.reprint)
        bottom.addWidget(exp)
        bottom.addWidget(rp)
        bottom.addStretch()
        lay.addLayout(bottom)

    def set_range(self, a, b):
        self.d_from.set_date(a)
        self.d_to.set_date(b)
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        a, b = self.d_from.iso(), self.d_to.iso()
        if a > b:
            show_error(self, "تاريخ البداية بعد تاريخ النهاية")
            return
        s = reports.sales_summary(self.conn, a, b)
        inv = reports.inventory_value(self.conn)
        debts = reports.debts_overview(self.conn)
        values = {**s, "inv_cost": inv["cost_value"], "inv_retail": inv["retail_value"], **debts}
        for k, card in self.cards.items():
            card.set(str(values[k]) if k == "count" else fmt_money(values[k]))
        self.note.setText(
            f"إتلاف مخزون خلال الفترة: {fmt_money(s['write_offs'])} (مخصوم من صافي الربح)   |   "
            f"سداد عملاء خلال الفترة: {fmt_money(s['customer_payments'])}   |   "
            f"ديون آجلة جديدة: {fmt_money(s['credit_unpaid'])}   |   أصناف في المخزون: {inv['products']}"
        )
        self.daily.fill([[d["day"], d["count"], fmt_money(d["cash"]), fmt_money(d["credit"]), fmt_money(d["total"]),
                          fmt_money(d["profit"])] for d in reports.daily_sales(self.conn, a, b)])
        rows = sales.list_sales(self.conn, a, b)
        self.invoices.fill([[r["id"], r["created_at"], "نقدي" if r["sale_type"] == "cash" else "آجل",
                             r["customer_name"] or "", fmt_money(int_to_money(r["total"])),
                             fmt_money(int_to_money(r["paid"])), r["username"]] for r in rows],
                           keys=[r["id"] for r in rows])
        self.top.fill([[t["name"], f"{fmt_qty(t['qty'])} {t['unit']}", fmt_money(t["total"]), fmt_money(t["profit"])]
                       for t in reports.top_products(self.conn, a, b)])
        self.exp.fill([[e["category"], fmt_money(e["total"])] for e in reports.expenses_by_category(self.conn, a, b)])

    def reprint(self):
        if self.tabs.currentWidget() is not self.invoices or self.invoices.selected_key() is None:
            show_error(self, "اختر فاتورة من تبويب «الفواتير»")
            return
        guarded(self, receipt.print_receipt, self.conn, self.invoices.selected_key())
