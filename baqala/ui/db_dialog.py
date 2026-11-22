"""نافذة إعداد الاتصال بقاعدة البيانات: SQL Server (الأساسية) أو SQLite محلية (احتياطية)."""
from PyQt5.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout)

from .. import config, db
from ..errors import POSError
from .widgets import combo_set_data, confirm, show_error, show_info


def installed_drivers():
    try:
        import pyodbc
        return [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:  # noqa: BLE001
        return []


class DatabaseDialog(QDialog):
    def __init__(self, parent=None, intro=""):
        super().__init__(parent)
        self.setWindowTitle("إعداد قاعدة البيانات")
        self.setMinimumWidth(560)
        cfg = config.load_db_config()
        lay = QVBoxLayout(self)
        if intro:
            msg = QLabel(intro)
            msg.setWordWrap(True)
            msg.setStyleSheet("color: #b71c1c;")
            lay.addWidget(msg)
        f = QFormLayout()
        self.engine = QComboBox()
        self.engine.addItem("SQL Server (موصى به)", "mssql")
        self.engine.addItem("SQLite محلية على هذا الجهاز", "sqlite")
        self.server = QLineEdit(cfg.server)
        self.server.setPlaceholderText(r".\SQLEXPRESS  أو  اسم-الجهاز\SQLEXPRESS")
        self.database = QLineEdit(cfg.database)
        self.auth = QComboBox()
        self.auth.addItem("حساب ويندوز الحالي", "windows")
        self.auth.addItem("مستخدم SQL Server", "sql")
        self.username = QLineEdit(cfg.username)
        self.password = QLineEdit(cfg.password)
        self.password.setEchoMode(QLineEdit.Password)
        self.driver = QComboBox()
        self.driver.addItem("تلقائي (أحدث تعريف مثبت)", "")
        for d in installed_drivers():
            self.driver.addItem(d, d)
        for w in (self.server, self.database, self.username, self.password):
            w.setLayoutDirection(0)  # Qt.LeftToRight
        f.addRow("نوع القاعدة", self.engine)
        f.addRow("الخادم", self.server)
        f.addRow("اسم القاعدة", self.database)
        f.addRow("طريقة الدخول", self.auth)
        f.addRow("اسم المستخدم", self.username)
        f.addRow("كلمة المرور", self.password)
        f.addRow("تعريف ODBC", self.driver)
        self.sqlite_note = QLabel(f"<small>ملف البيانات: \u200e{config.db_path()}\u200e</small>")
        f.addRow(self.sqlite_note)
        lay.addLayout(f)
        btns = QHBoxLayout()
        test = QPushButton("اختبار الاتصال")
        test.clicked.connect(self.test)
        save = QPushButton("حفظ")
        save.setDefault(True)
        save.clicked.connect(self.save)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        for b in (test, save, cancel):
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)
        combo_set_data(self.engine, cfg.engine)
        combo_set_data(self.auth, cfg.auth)
        combo_set_data(self.driver, cfg.driver)
        self.engine.currentIndexChanged.connect(self._update)
        self.auth.currentIndexChanged.connect(self._update)
        self._update()

    def _update(self):
        mssql = self.engine.currentData() == "mssql"
        sql_auth = self.auth.currentData() == "sql"
        for w in (self.server, self.database, self.auth, self.driver):
            w.setEnabled(mssql)
        self.username.setEnabled(mssql and sql_auth)
        self.password.setEnabled(mssql and sql_auth)
        self.sqlite_note.setVisible(not mssql)

    def config(self) -> config.DatabaseConfig:
        return config.DatabaseConfig(
            engine=self.engine.currentData(), server=self.server.text().strip(),
            database=self.database.text().strip() or config.DEFAULT_DATABASE,
            auth=self.auth.currentData(), username=self.username.text().strip(),
            password=self.password.text(), driver=self.driver.currentData() or "",
        )

    def _open(self, cfg):
        if cfg.engine == "mssql" and not cfg.server:
            raise POSError("أدخل اسم خادم SQL Server")
        return db.open_database(cfg)

    def test(self):
        try:
            conn = self._open(self.config())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        try:
            version = db.schema_version(conn)
        finally:
            conn.close()
        show_info(self, f"تم الاتصال بنجاح، وقاعدة البيانات جاهزة (إصدار المخطط {version}).")

    def save(self):
        cfg = self.config()
        try:
            conn = self._open(cfg)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        try:
            if cfg.engine == "mssql" and config.db_path().exists():
                self._offer_transfer(conn)
        finally:
            conn.close()
        config.save_db_config(cfg)
        self.accept()

    def _offer_transfer(self, conn):
        from .. import transfer
        try:
            if transfer.target_has_data(conn):
                return
        except Exception:  # noqa: BLE001
            return
        if not confirm(self, "قاعدة SQL Server فارغة، ويوجد على هذا الجهاز بيانات سابقة (SQLite).\n"
                             "هل تريد نقل كل البيانات (الأصناف، المخزون، المبيعات، الديون، المستخدمين...) إليها الآن؟"):
            return
        try:
            counts = transfer.sqlite_to_mssql(config.db_path(), conn)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        show_info(self, f"تم نقل البيانات: {counts.get('products', 0)} صنف، {counts.get('sales', 0)} فاتورة بيع.")
