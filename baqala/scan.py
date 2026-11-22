"""كشف إدخال قارئ الباركود (USB يعمل كلوحة مفاتيح).

القارئ يرسل الأحرف بسرعة كبيرة (عادة أقل من 30 ملّي ثانية بين كل حرف) ثم Enter.
الإنسان أبطأ بكثير. نستخدم هذا الفرق لتمييز المسح عن الكتابة اليدوية، حتى لو كان
المؤشر في حقل آخر (مثل حقل المبلغ المدفوع) فلا يختلط الباركود بالمبلغ.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from .textnorm import normalize_barcode

MAX_INTERVAL_MS = 50
MIN_LENGTH = 4


@dataclass
class ScanDetector:
    max_interval_ms: float = MAX_INTERVAL_MS
    min_length: int = MIN_LENGTH
    _chars: List[str] = field(default_factory=list)
    _last_ms: Optional[float] = None

    def reset(self) -> None:
        self._chars.clear()
        self._last_ms = None

    def starts_new_burst(self, t_ms: float) -> bool:
        return self._last_ms is None or t_ms - self._last_ms > self.max_interval_ms

    def feed_char(self, ch: str, t_ms: float) -> None:
        if self.starts_new_burst(t_ms):
            self._chars.clear()
        self._chars.append(ch)
        self._last_ms = t_ms

    def feed_enter(self, t_ms: float) -> Optional[str]:
        """يُستدعى عند Enter. يُرجع الباركود إن كانت السلسلة الأخيرة مسحاً سريعاً، وإلا None."""
        fast = self._last_ms is not None and t_ms - self._last_ms <= self.max_interval_ms
        code = "".join(self._chars) if fast and len(self._chars) >= self.min_length else None
        self.reset()
        return normalize_barcode(code) if code else None

    @property
    def pending_length(self) -> int:
        return len(self._chars)


def parse_scan_input(text: str):
    """يدعم صيغة «الكمية*الباركود» مثل 0.250*6281234 أو 3*6281234.
    يُرجع (الكمية كنص أو None, الرمز)."""
    text = (text or "").strip()
    if "*" in text:
        q, _, code = text.partition("*")
        return (q.strip() or None), code.strip()
    return None, text
