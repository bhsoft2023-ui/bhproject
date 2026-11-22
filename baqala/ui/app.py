"""تهيئة التطبيق: السجلات، القفل (نسخة واحدة)، قاعدة البيانات، النسخ التلقائي، وتسجيل الدخول."""
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from PyQt5.QtCore import QLockFile, QProcess, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox

from .. import APP_TITLE, config, db
from ..db import now_str
from ..services import auth, backup, settings
from .fonts import apply_app_font

log = logging.getLogger("baqala")

STYLE = """
QPushButton { padding: 6px 12px; }
QTableWidget { gridline-color: #ddd; selection-background-color: #b2dfdb; selection-color: black; }
QHeaderView::section { background: #eceff1; padding: 6px; font-weight: bold; border: 1px solid #ddd; }
QLineEdit, QComboBox, QDateEdit, QSpinBox { padding: 4px; }
"""


def setup_logging():
    handler = RotatingFileHandler(config.logs_dir() / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


class AppContext:
    """حالة مشتركة بين الصفحات: الاتصال، المستخدم الحالي، والنسخ الاحتياطي."""

    def __init__(self, app):
        self.app = app
        self.conn = db.connect(config.db_path())
        self.user = None
        self.window = None
        self.restart_requested = False
        if not db.integrity_ok(self.conn):
            QMessageBox.critical(None, "تحذير", "تم اكتشاف مشكلة في سلامة قاعدة البيانات.\n"
                                 "يُنصح باستعادة آخر نسخة احتياطية من الإعدادات.")
        auth.ensure_default_admin(self.conn)
        self.timer = QTimer()
        self.timer.timeout.connect(self.auto_backup)
        self.timer.start(10 * 60 * 1000)  # فحص كل 10 دقائق إن كان موعد النسخ قد حان

    def status(self, text):
        if self.window:
            self.window.statusBar().showMessage(text, 15000)

    def run_backup(self, tag=""):
        from .settings_page import backup_dir
        path = backup.create_backup(
            self.conn, backup_dir(self.conn), settings.get_int(self.conn, "backup_keep", 60),
            settings.get(self.conn, "backup_extra_dir").strip() or None, tag=tag)
        settings.set_value(self.conn, "last_backup_at", now_str())
        return path

    def auto_backup(self):
        try:
            if backup.is_due(settings.get(self.conn, "last_backup_at"),
                             settings.get_int(self.conn, "backup_interval_hours", 4)):
                self.run_backup("auto")
                self.status("تم إنشاء نسخة احتياطية تلقائية")
        except Exception:  # noqa: BLE001
            log.exception("فشل النسخ الاحتياطي التلقائي")
            self.status("تعذر إنشاء النسخة الاحتياطية التلقائية — راجع الإعدادات")

    def on_close(self):
        if self.restart_requested:
            return
        try:
            if settings.get_int(self.conn, "backup_interval_hours", 4) > 0:
                self.run_backup("exit")
        except Exception:  # noqa: BLE001
            log.exception("فشل النسخ عند الإغلاق")

    def restore(self, path):
        self.timer.stop()
        self.conn.close()
        try:
            backup.restore_backup(config.db_path(), path, backup_dir_safe())
        finally:
            self.restart_requested = True
            QProcess.startDetached(sys.executable, sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv)
            self.app.quit()


def backup_dir_safe():
    return config.default_backup_dir()


def excepthook(exc_type, exc, tb):
    log.error("خطأ غير معالج:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
    try:
        QMessageBox.critical(None, "خطأ", f"حدث خطأ غير متوقع ولم تُحفظ العملية الجارية:\n{exc}\n"
                             f"تفاصيل الخطأ في: {config.logs_dir() / 'app.log'}")
    except Exception:  # noqa: BLE001
        pass


def run():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setLayoutDirection(Qt.RightToLeft)
    apply_app_font(app)
    app.setStyleSheet(STYLE)
    setup_logging()
    sys.excepthook = excepthook

    lock = QLockFile(str(config.data_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_TITLE, "البرنامج مفتوح بالفعل على هذا الجهاز.")
        return 1

    try:
        ctx = AppContext(app)
    except Exception as exc:  # noqa: BLE001
        log.exception("تعذر فتح قاعدة البيانات")
        QMessageBox.critical(None, APP_TITLE, f"تعذر فتح قاعدة البيانات:\n{exc}")
        return 1
    ctx.auto_backup()

    from .main_window import LoginDialog, MainWindow
    login = LoginDialog(ctx.conn)
    if not login.exec_():
        return 0
    ctx.user = login.user
    log.info("دخول المستخدم %s", ctx.user.username)
    window = MainWindow(ctx)
    window.showMaximized()
    code = app.exec_()
    if not ctx.restart_requested:
        ctx.conn.close()
    lock.unlock()
    return code
