"""يلتقط صوراً لصفحات الواجهة (للتوثيق) دون تسجيل دخول يدوي."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QFont  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from baqala.services import auth  # noqa: E402
from baqala.ui import app as appmod  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
app.setLayoutDirection(Qt.RightToLeft)
f = QFont("Noto Sans Arabic UI")
f.setPointSize(10)
app.setFont(f)
app.setStyleSheet(appmod.STYLE)
ctx = appmod.AppContext(app)
row = ctx.conn.execute("SELECT * FROM users WHERE username='admin'").fetchone()
ctx.user = auth.User(row["id"], "admin", "المدير", "admin")
from baqala.ui.main_window import MainWindow  # noqa: E402
w = MainWindow(ctx)
w.resize(1366, 768)
w.show()
names = ["sale_cash", "sale_credit", "products", "inventory", "purchases", "customers", "suppliers", "expenses",
         "reports", "users", "settings"]
for i, n in enumerate(names):
    w.nav.setCurrentRow(i)
    page = w.stack.currentWidget()
    if n == "sale_cash":
        page.on_barcode("6281000000011")
        page.on_barcode("0.250*2000002")
        page.on_barcode("6281000000028")
        page.paid.setText("5000")
    if n == "sale_credit":
        page.customer.setCurrentIndex(1)
        page.on_barcode("3*6281000000035")
    for _ in range(5):
        app.processEvents()
    w.grab().save(os.path.join(out, f"{i + 1:02d}_{n}.png"))
print("saved to", out)
