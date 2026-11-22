"""حقل الباركود ومرشّح التقاط المسح من أي حقل آخر في صفحة البيع."""
import sys
import time

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QAbstractButton, QAbstractItemView, QLineEdit

from ..scan import ScanDetector
from ..textnorm import normalize_barcode


def _now_ms():
    return time.monotonic() * 1000


def latin_from_native_key(event):
    """على ويندوز: نستخدم رمز المفتاح الافتراضي (VK) ليُقرأ الباركود صحيحاً حتى لو كان تخطيط لوحة المفاتيح عربياً."""
    if sys.platform != "win32" or event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
        return None
    vk = event.nativeVirtualKey()
    if 0x30 <= vk <= 0x39:
        return chr(vk) if not event.modifiers() & Qt.ShiftModifier else None
    if 0x60 <= vk <= 0x69:  # لوحة الأرقام
        return chr(vk - 0x30)
    if 0x41 <= vk <= 0x5A:
        ch = chr(vk)
        return ch if event.modifiers() & Qt.ShiftModifier else ch.lower()
    if vk == 0xBD and not event.modifiers() & Qt.ShiftModifier:
        return "-"
    return None


class BarcodeEdit(QLineEdit):
    """حقل إدخال الباركود. Enter (أو Enter من لوحة الأرقام) يُطلق submitted بالنص.

    عند اكتشاف مسح سريع على ويندوز تُستخدم رموز المفاتيح (VK) بدل الأحرف، فيُقرأ الباركود
    صحيحاً حتى لو كان تخطيط لوحة المفاتيح عربياً، دون التأثير على كتابة أسماء الأصناف بالعربي.
    """

    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        f = QFont()
        f.setPointSize(16)
        self.setFont(f)
        self.setMinimumHeight(44)
        self.setPlaceholderText("امسح الباركود أو اكتب الاسم ثم Enter  |  للوزن: 0.250*الباركود")
        self.detector = ScanDetector()
        self._prefix = ""
        self._latin = []

    def keyPressEvent(self, event):
        t = _now_ms()
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            code = self.detector.feed_enter(t)
            text = (self._prefix + normalize_barcode("".join(self._latin))) if code else self.text()
            self.clear()
            self._latin = []
            text = text.strip()
            if text:
                self.submitted.emit(text)
            event.accept()
            return
        ch = event.text()
        if ch and ch.isprintable() and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            if self.detector.starts_new_burst(t):
                self._prefix = self.text()
                self._latin = []
            self.detector.feed_char(ch, t)
            self._latin.append(latin_from_native_key(event) or ch)
        super().keyPressEvent(event)


class ScanCatcher(QObject):
    """يُركّب على صفحة البيع.

    - إذا كان التركيز على جدول أو زر: تُحوَّل الأحرف إلى حقل الباركود مباشرة.
    - إذا كان التركيز على حقل نصي آخر (مثل المبلغ المدفوع): يُكشف المسح السريع بالتوقيت،
      ويُعاد الحقل لما كان عليه، ويُرسل الباركود لحقل البيع، ولا يُعتبر Enter تأكيداً للبيع.
    """

    scanned = pyqtSignal(str)

    def __init__(self, barcode_edit: BarcodeEdit, parent=None):
        super().__init__(parent)
        self.barcode_edit = barcode_edit
        self.detector = ScanDetector()
        self._snapshot = None
        self._latin = []

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress or obj is self.barcode_edit:
            return False
        printable = bool(event.text()) and event.text().isprintable() and not (
            event.modifiers() & (Qt.ControlModifier | Qt.AltModifier))
        if isinstance(obj, (QAbstractItemView, QAbstractButton)):
            if printable:
                self.barcode_edit.setFocus()
                self.barcode_edit.keyPressEvent(event)
                return True
            return False
        if isinstance(obj, QLineEdit) and obj.isEnabled() and not obj.isReadOnly():
            t = _now_ms()
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                code = self.detector.feed_enter(t)
                if code and self._snapshot and self._snapshot[0] is obj:
                    obj.setText(self._snapshot[1])
                    self.scanned.emit(normalize_barcode("".join(self._latin)) or code)
                    self._snapshot = None
                    return True
                self._snapshot = None
                return False
            if printable:
                if self.detector.starts_new_burst(t) or self._snapshot is None or self._snapshot[0] is not obj:
                    self._snapshot = (obj, obj.text())
                    self._latin = []
                self.detector.feed_char(event.text(), t)
                self._latin.append(latin_from_native_key(event) or event.text())
        return False
