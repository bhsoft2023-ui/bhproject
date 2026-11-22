"""الإعدادات والنسخ الاحتياطي والاستعادة."""
import os
import subprocess
import sys
from pathlib import Path

from PyQt5.QtPrintSupport import QPrinterInfo
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import config
from ..services import backup, settings
from .widgets import Table, confirm, guarded, show_info, title_label


def backup_dir(conn) -> Path:
    custom = settings.get(conn, "backup_dir").strip()
    return Path(custom) if custom else config.default_backup_dir()


class SettingsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.conn = ctx, ctx.conn
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("الإعدادات والنسخ الاحتياطي"))
        row = QHBoxLayout()

        shop = QGroupBox("بيانات المحل والفاتورة")
        f = QFormLayout(shop)
        self.shop_name, self.shop_address, self.shop_phone, self.footer = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.auto_print = QCheckBox("طباعة الفاتورة تلقائياً بعد كل بيع")
        self.printer = QComboBox()
        self.printer.addItem("الطابعة الافتراضية في ويندوز", "")
        for name in QPrinterInfo.availablePrinterNames():
            self.printer.addItem(name, name)
        self.expiry_days = QSpinBox()
        self.expiry_days.setRange(1, 365)
        self.expiry_days.setSuffix(" يوم")
        f.addRow("اسم المحل", self.shop_name)
        f.addRow("العنوان", self.shop_address)
        f.addRow("الهاتف", self.shop_phone)
        f.addRow("تذييل الفاتورة", self.footer)
        f.addRow("الطابعة (حرارية)", self.printer)
        f.addRow("", self.auto_print)
        f.addRow("التنبيه قبل انتهاء الصلاحية بـ", self.expiry_days)
        row.addWidget(shop)

        bk = QGroupBox("النسخ الاحتياطي التلقائي")
        g = QFormLayout(bk)
        self.interval = QSpinBox()
        self.interval.setRange(0, 48)
        self.interval.setSuffix(" ساعة")
        self.interval.setSpecialValueText("متوقف")
        self.keep = QSpinBox()
        self.keep.setRange(5, 1000)
        self.bdir, self.extra = QLineEdit(), QLineEdit()
        self.bdir.setPlaceholderText(str(config.default_backup_dir()))
        self.extra.setPlaceholderText("مثال: E:\\نسخ_البقالة (فلاشة أو قرص آخر)")
        g.addRow("نسخة كل", self.interval)
        g.addRow("عدد النسخ المحفوظة", self.keep)
        g.addRow("مجلد النسخ", self._with_browse(self.bdir))
        g.addRow("مجلد نسخ إضافي", self._with_browse(self.extra))
        self.last = QLabel()
        g.addRow("آخر نسخة:", self.last)
        g.addRow(QLabel(f"<small>قاعدة البيانات: \u200e{ctx.db_config.label}\u200e</small>"))
        row.addWidget(bk)
        lay.addLayout(row)

        btns = QHBoxLayout()
        for text, slot in [("حفظ الإعدادات", self.save), ("نسخة احتياطية الآن", self.backup_now),
                           ("استعادة نسخة...", self.restore), ("فتح مجلد النسخ", self.open_dir),
                           ("قاعدة البيانات...", self.database_settings)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)
        lay.addWidget(QLabel("<b>النسخ الموجودة</b>"))
        self.table = Table(["الملف", "التاريخ", "الحجم"])
        lay.addWidget(self.table)

    def _with_browse(self, edit):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        b = QPushButton("...")
        b.setFixedWidth(48)
        b.clicked.connect(lambda: edit.setText(QFileDialog.getExistingDirectory(self, "اختر مجلداً") or edit.text()))
        h.addWidget(b)
        return w

    def showEvent(self, e):
        super().showEvent(e)
        s = settings.get_all(self.conn)
        self.shop_name.setText(s["shop_name"])
        self.shop_address.setText(s["shop_address"])
        self.shop_phone.setText(s["shop_phone"])
        self.footer.setText(s["receipt_footer"])
        self.auto_print.setChecked(s["auto_print"] == "1")
        idx = self.printer.findData(s["printer_name"])
        self.printer.setCurrentIndex(max(idx, 0))
        self.expiry_days.setValue(int(s["expiry_warning_days"] or 30))
        self.interval.setValue(int(s["backup_interval_hours"] or 0))
        self.keep.setValue(int(s["backup_keep"] or 60))
        self.bdir.setText(s["backup_dir"])
        self.extra.setText(s["backup_extra_dir"])
        self.refresh_list()

    def refresh_list(self):
        self.last.setText(settings.get(self.conn, "last_backup_at") or "لا توجد")
        files = backup.list_backups(backup_dir(self.conn), backup.suffix_for(self.conn))
        from datetime import datetime
        self.table.fill([[p.name, datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                          f"{p.stat().st_size / 1024:.0f} KB"] for p in files], keys=[str(p) for p in files])

    def save(self):
        guarded(self, settings.set_many, self.conn, {
            "shop_name": self.shop_name.text().strip(), "shop_address": self.shop_address.text().strip(),
            "shop_phone": self.shop_phone.text().strip(), "receipt_footer": self.footer.text().strip(),
            "auto_print": "1" if self.auto_print.isChecked() else "0", "printer_name": self.printer.currentData(),
            "expiry_warning_days": self.expiry_days.value(), "backup_interval_hours": self.interval.value(),
            "backup_keep": self.keep.value(), "backup_dir": self.bdir.text().strip(),
            "backup_extra_dir": self.extra.text().strip(),
        })
        show_info(self, "تم حفظ الإعدادات")

    def backup_now(self):
        if guarded(self, self.ctx.run_backup, "manual"):
            self.refresh_list()
            show_info(self, "تم إنشاء النسخة الاحتياطية")

    def open_dir(self):
        d = str(backup_dir(self.conn))
        if sys.platform == "win32":
            os.startfile(d)  # noqa
        else:
            subprocess.Popen(["xdg-open", d])

    def restore(self):
        path = self.table.selected_key()
        if not path:
            suffix = backup.suffix_for(self.conn)
            kind = "SQL Server" if suffix == backup.MSSQL_SUFFIX else "SQLite"
            path, _ = QFileDialog.getOpenFileName(self, "اختر ملف النسخة", str(backup_dir(self.conn)),
                                                  f"{kind} (*{suffix})")
        if not path:
            return
        if not confirm(self, f"سيتم استبدال كل البيانات الحالية بالنسخة:\n{Path(path).name}\n"
                             "(سيتم حفظ نسخة أمان من البيانات الحالية أولاً)\nسيُعاد تشغيل البرنامج. متابعة؟"):
            return
        guarded(self, self.ctx.restore, path)

    def database_settings(self):
        from .db_dialog import DatabaseDialog
        if DatabaseDialog(self).exec_() and confirm(self, "تم حفظ إعداد قاعدة البيانات.\nإعادة تشغيل البرنامج الآن لتطبيقه؟"):
            self.ctx.restart()
