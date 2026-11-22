"""تحميل خط Noto Kufi Arabic المضمّن مع البرنامج (لا يحتاج تثبيته على ويندوز)."""
import logging
from pathlib import Path

from PyQt5.QtGui import QFont, QFontDatabase

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FAMILY = "Noto Kufi Arabic"
FALLBACK = "Tahoma"
_loaded = None


def load_app_font() -> str:
    """يسجّل الخط في Qt ويعيد اسم العائلة المتاحة."""
    global _loaded
    if _loaded is None:
        _loaded = FALLBACK
        for path in sorted(FONTS_DIR.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if FAMILY in families:
                _loaded = FAMILY
        if _loaded != FAMILY:
            logging.getLogger("baqala").warning("تعذر تحميل خط %s من %s", FAMILY, FONTS_DIR)
    return _loaded


def apply_app_font(app, point_size=10) -> str:
    family = load_app_font()
    font = QFont(family, point_size)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    return family
