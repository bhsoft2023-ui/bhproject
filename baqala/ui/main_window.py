"""النافذة الرئيسية وتسجيل الدخول."""
from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_TITLE, __version__
from ..errors import POSError
from ..services import auth, inventory, products, settings
from .dialogs import ok_cancel
from .expenses_page import ExpensesPage
from .inventory_page import InventoryPage
from .parties_page import PartiesPage
from .products_page import ProductsPage
from .purchases_page import PurchasesPage
from .reports_page import ReportsPage
from .sale_page import SalePage
from .settings_page import SettingsPage
from .users_page import UsersPage
from .widgets import show_error, show_info, title_label


class LoginDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn, self.user = conn, None
        self.setWindowTitle(f"تسجيل الدخول - {APP_TITLE}")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(title_label(settings.get(conn, "shop_name"), 18), alignment=Qt.AlignCenter)
        f = QFormLayout()
        self.username, self.password = QLineEdit(), QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        f.addRow("اسم المستخدم", self.username)
        f.addRow("كلمة المرور", self.password)
        lay.addLayout(f)
        lay.addWidget(ok_cancel(self))
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.accept)

    def accept(self):
        try:
            self.user = auth.authenticate(self.conn, self.username.text(), self.password.text())
        except POSError as e:
            show_error(self, e)
            self.password.clear()
            return
        if self.user.must_change_password and not ChangePasswordDialog(self.conn, self.user, True, self).exec_():
            return
        super().accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, conn, user, forced=False, parent=None):
        super().__init__(parent)
        self.conn, self.user = conn, user
        self.setWindowTitle("تغيير كلمة المرور")
        lay = QFormLayout(self)
        if forced:
            lay.addRow(QLabel("<b>يجب تغيير كلمة المرور قبل المتابعة</b>"))
        self.old, self.new, self.new2 = QLineEdit(), QLineEdit(), QLineEdit()
        for w in (self.old, self.new, self.new2):
            w.setEchoMode(QLineEdit.Password)
        lay.addRow("الحالية", self.old)
        lay.addRow("الجديدة", self.new)
        lay.addRow("تأكيد الجديدة", self.new2)
        lay.addRow(ok_cancel(self))

    def accept(self):
        if self.new.text() != self.new2.text():
            show_error(self, "كلمتا المرور غير متطابقتين")
            return
        try:
            auth.change_password(self.conn, self.user.id, self.old.text(), self.new.text())
        except POSError as e:
            show_error(self, e)
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.window = self
        self.setWindowTitle(f"{settings.get(ctx.conn, 'shop_name')} - {APP_TITLE} {__version__}")
        self.resize(1280, 800)
        central = QWidget()
        root = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.setFixedWidth(250)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setIconSize(QSize(1, 1))
        self.nav.setStyleSheet(
            "QListWidget{background:#263238;color:white;font-size:12pt;border:none;}"
            "QListWidget::item{padding:12px;}QListWidget::item:selected{background:#00897b;}")
        self.stack = QStackedWidget()
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        u = ctx.user
        pages = [
            ("بيع نقدي", "sale.cash", lambda: SalePage(ctx, "cash")),
            ("بيع آجل", "sale.credit", lambda: SalePage(ctx, "credit")),
            ("الأصناف والأسعار", "product.view", lambda: ProductsPage(ctx)),
            ("المخزون والصلاحية", "inventory.manage", lambda: InventoryPage(ctx)),
            ("المشتريات", "purchase.manage", lambda: PurchasesPage(ctx)),
            ("العملاء", "customer.view", lambda: PartiesPage(ctx, "customer")),
            ("الموردين", "supplier.manage", lambda: PartiesPage(ctx, "supplier")),
            ("المصروفات", "expense.manage", lambda: ExpensesPage(ctx)),
            ("التقارير", "report.view", lambda: ReportsPage(ctx)),
            ("المستخدمون", "user.manage", lambda: UsersPage(ctx)),
            ("الإعدادات والنسخ", "settings.manage", lambda: SettingsPage(ctx)),
        ]
        for title, perm, factory in pages:
            if u.can(perm):
                self.nav.addItem(QListWidgetItem(title))
                self.stack.addWidget(factory())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        sb = self.statusBar()
        self.user_lbl = QLabel(f"المستخدم: {u.display_name} ({auth.ROLE_LABELS[u.role]})")
        sb.addPermanentWidget(self.user_lbl)
        pw = QPushButton("تغيير كلمة المرور")
        pw.setFlat(True)
        pw.clicked.connect(lambda: ChangePasswordDialog(ctx.conn, u, parent=self).exec_() and show_info(self, "تم"))
        sb.addPermanentWidget(pw)
        if u.can("inventory.manage"):
            QTimer.singleShot(800, self.startup_alerts)

    def startup_alerts(self):
        days = settings.get_int(self.ctx.conn, "expiry_warning_days", 30)
        alerts = inventory.expiry_alerts(self.ctx.conn, days)
        expired = sum(1 for a in alerts if a["expired"])
        low = len(products.low_stock(self.ctx.conn))
        if expired or alerts or low:
            QMessageBox.warning(self, "تنبيهات المخزون",
                                f"دفعات منتهية الصلاحية: {expired}\n"
                                f"دفعات تنتهي خلال {days} يوم: {len(alerts) - expired}\n"
                                f"أصناف تحت حد التنبيه: {low}\n\nراجع صفحة «المخزون والصلاحية».")

    def closeEvent(self, event):
        self.ctx.on_close()
        super().closeEvent(event)
