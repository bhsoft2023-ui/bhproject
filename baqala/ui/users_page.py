"""إدارة المستخدمين (للمدير فقط)."""
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ..services import auth
from .dialogs import ok_cancel
from .widgets import Table, combo_set_data, guarded, show_error, show_info, title_label


class UserDialog(QDialog):
    def __init__(self, ctx, user_row=None, parent=None):
        super().__init__(parent)
        self.ctx, self.row = ctx, user_row
        self.setWindowTitle("تعديل مستخدم" if user_row else "مستخدم جديد")
        f = QFormLayout(self)
        self.username, self.full_name, self.password = QLineEdit(), QLineEdit(), QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.role = QComboBox()
        for k, v in auth.ROLE_LABELS.items():
            self.role.addItem(v, k)
        self.active = QCheckBox("نشط")
        self.active.setChecked(True)
        f.addRow("اسم الدخول", self.username)
        f.addRow("الاسم الكامل", self.full_name)
        if not user_row:
            f.addRow("كلمة المرور", self.password)
        f.addRow("نوع الحساب", self.role)
        f.addRow("", self.active)
        if user_row:
            self.username.setText(user_row["username"])
            self.username.setEnabled(False)
            self.full_name.setText(user_row["full_name"])
            combo_set_data(self.role, user_row["role"])
            self.active.setChecked(bool(user_row["active"]))
        f.addRow(ok_cancel(self))

    def accept(self):
        c, u = self.ctx.conn, self.ctx.user
        if self.row:
            ok = guarded(self, lambda: auth.update_user(c, u, self.row["id"], self.full_name.text(),
                                                        self.role.currentData(), self.active.isChecked()) or True)
        else:
            ok = guarded(self, auth.create_user, c, u, self.username.text(), self.full_name.text(),
                         self.password.text(), self.role.currentData())
        if ok:
            super().accept()


class UsersPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(title_label("المستخدمون والصلاحيات"))
        row = QHBoxLayout()
        for text, slot in [("مستخدم جديد", self.add), ("تعديل", self.edit), ("إعادة تعيين كلمة المرور", self.reset)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.table = Table(["اسم الدخول", "الاسم", "نوع الحساب", "الحالة"], stretch_col=1)
        lay.addWidget(self.table)
        perms = "<br>".join(f"• {auth.ALL_PERMISSIONS[p]}" for p in sorted(auth.ROLE_PERMISSIONS["cashier"]))
        from PyQt5.QtWidgets import QLabel
        lay.addWidget(QLabel(f"<b>صلاحيات الموظف (الكاشير):</b><br>{perms}<br><b>المدير:</b> كل الصلاحيات"))

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        rows = auth.list_users(self.ctx.conn)
        self.rows = {r["id"]: r for r in rows}
        self.table.fill([[r["username"], r["full_name"], auth.ROLE_LABELS[r["role"]], "نشط" if r["active"] else "موقوف"]
                         for r in rows], keys=[r["id"] for r in rows])

    def add(self):
        if UserDialog(self.ctx, parent=self).exec_():
            self.refresh()

    def edit(self):
        uid = self.table.selected_key()
        if uid is None:
            show_error(self, "اختر مستخدماً")
            return
        if UserDialog(self.ctx, self.rows[uid], self).exec_():
            self.refresh()

    def reset(self):
        uid = self.table.selected_key()
        if uid is None:
            show_error(self, "اختر مستخدماً")
            return
        pw, ok = QInputDialog.getText(self, "إعادة تعيين", "كلمة المرور المؤقتة (سيُطلب تغييرها عند الدخول):",
                                      QLineEdit.Password)
        if ok and guarded(self, lambda: auth.reset_password(self.ctx.conn, self.ctx.user, uid, pw) or True):
            show_info(self, "تم")
