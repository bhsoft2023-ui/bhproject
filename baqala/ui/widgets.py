"""عناصر واجهة مشتركة."""
import csv
import logging
from datetime import date

from PyQt5.QtCore import QDate, QRegExp, Qt
from PyQt5.QtGui import QFont, QRegExpValidator
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QFileDialog, QFrame, QHeaderView, QLabel,
                             QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..errors import POSError
from ..money import D, money, qty

log = logging.getLogger(__name__)


def show_error(parent, exc_or_msg, title="خطأ"):
    msg = exc_or_msg.message if isinstance(exc_or_msg, POSError) else str(exc_or_msg)
    QMessageBox.critical(parent, title, msg)


def show_info(parent, msg, title="تم"):
    QMessageBox.information(parent, title, msg)


def confirm(parent, msg, title="تأكيد") -> bool:
    box = QMessageBox(QMessageBox.Question, title, msg, QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("نعم")
    box.button(QMessageBox.No).setText("لا")
    box.setDefaultButton(QMessageBox.No)
    return box.exec_() == QMessageBox.Yes


def guarded(parent, func, *args, **kwargs):
    """ينفذ عملية ويعرض أي خطأ برسالة عربية بدل إغلاق البرنامج."""
    try:
        return func(*args, **kwargs)
    except POSError as exc:
        show_error(parent, exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("خطأ غير متوقع")
        show_error(parent, f"حدث خطأ غير متوقع:\n{exc}\n\nتم تسجيل التفاصيل في ملف السجل.")
    return None


class DecimalEdit(QLineEdit):
    """حقل رقمي يُرجع Decimal (يقبل الأرقام العربية)."""

    def __init__(self, decimals=2, placeholder="", parent=None):
        super().__init__(parent)
        self.decimals = decimals
        pattern = r"[0-9٠-٩]*([.٫][0-9٠-٩]{0,%d})?" % decimals if decimals else r"[0-9٠-٩]*"
        self.setValidator(QRegExpValidator(QRegExp(pattern), self))
        self.setPlaceholderText(placeholder)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def value(self, default="0"):
        text = self.text().strip()
        if not text:
            text = default
        return qty(text) if self.decimals == 3 else (money(text) if self.decimals == 2 else D(text))

    def set_value(self, v):
        if v is None:
            self.clear()
            return
        d = D(v)
        self.setText(f"{d:f}".rstrip("0").rstrip(".") if "." in f"{d:f}" else f"{d:f}")


class DateEdit(QDateEdit):
    def __init__(self, value: date = None, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setLayoutDirection(Qt.LeftToRight)
        self.set_date(value or date.today())

    def set_date(self, d: date):
        self.setDate(QDate(d.year, d.month, d.day))

    def iso(self) -> str:
        return self.date().toString("yyyy-MM-dd")


class OptionalDateEdit(DateEdit):
    """تاريخ اختياري: القيمة الدنيا تعني «بدون تاريخ»."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setMinimumDate(QDate(2000, 1, 1))
        self.setSpecialValueText("بدون")
        self.setDate(self.minimumDate())

    def iso(self):
        return None if self.date() == self.minimumDate() else super().iso()


class Table(QTableWidget):
    def __init__(self, headers, parent=None, stretch_col=0):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        h = self.horizontalHeader()
        h.setMinimumSectionSize(60)
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        if stretch_col is not None:
            h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)

    def fill(self, rows, keys=None):
        """rows: قائمة من القوائم (نصوص). keys: معرّف يُخزّن مع كل صف."""
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem("" if value is None else str(value))
                if keys is not None:
                    item.setData(Qt.UserRole, keys[r])
                self.setItem(r, c, item)

    def color_row(self, r, color):
        for c in range(self.columnCount()):
            it = self.item(r, c)
            if it:
                it.setBackground(color)

    def selected_key(self):
        row = self.currentRow()
        if row < 0 or self.item(row, 0) is None:
            return None
        return self.item(row, 0).data(Qt.UserRole)

    def export_csv(self, parent, default_name="report.csv"):
        path, _ = QFileDialog.getSaveFileName(parent, "تصدير", default_name, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([self.horizontalHeaderItem(c).text() for c in range(self.columnCount())])
            for r in range(self.rowCount()):
                w.writerow([(self.item(r, c).text() if self.item(r, c) else "") for c in range(self.columnCount())])
        show_info(parent, "تم التصدير (يفتح في Excel)")


def title_label(text, size=13):
    lbl = QLabel(text)
    f = QFont()
    f.setPointSize(size)
    f.setBold(True)
    lbl.setFont(f)
    return lbl


class Card(QFrame):
    """بطاقة رقم في التقارير."""

    def __init__(self, title, color="#1565c0"):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(
            f"#card {{background:white;border:1px solid #ddd;border-right:5px solid {color};border-radius:6px;}}"
        )
        lay = QVBoxLayout(self)
        self.title = QLabel(title)
        self.title.setStyleSheet("color:#555;")
        self.value = QLabel("-")
        self.value.setStyleSheet(f"font-size:18pt;font-weight:bold;color:{color};")
        lay.addWidget(self.title)
        lay.addWidget(self.value)

    def set(self, text):
        self.value.setText(text)


def combo_set_data(combo: QComboBox, data):
    idx = combo.findData(data)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
