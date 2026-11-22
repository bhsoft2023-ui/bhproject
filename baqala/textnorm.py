"""توحيد النص العربي للبحث، وتصحيح الباركود المُدخل بتخطيط لوحة مفاتيح عربي."""
import re

_AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]")


def normalize_ar(text: str) -> str:
    if not text:
        return ""
    text = _TASHKEEL.sub("", text)
    text = text.translate(_AR_NORM)
    return " ".join(text.lower().split())


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# تخطيط Arabic (101): الحرف العربي الناتج -> الحرف اللاتيني على نفس المفتاح
_AR_LOWER = {
    "ض": "q", "ص": "w", "ث": "e", "ق": "r", "ف": "t", "غ": "y", "ع": "u", "ه": "i",
    "خ": "o", "ح": "p", "ج": "[", "د": "]", "ش": "a", "س": "s", "ي": "d", "ب": "f",
    "ل": "g", "ا": "h", "ت": "j", "ن": "k", "م": "l", "ك": ";", "ط": "'", "ئ": "z",
    "ء": "x", "ؤ": "c", "ر": "v", "ى": "n", "ة": "m", "و": ",", "ز": ".", "ظ": "/",
}
_AR_UPPER = {
    "َ": "Q", "ً": "W", "ُ": "E", "ٌ": "R", "إ": "Y", "‘": "U", "÷": "I", "×": "O",
    "؛": "P", "ِ": "A", "ٍ": "S", "ـ": "J", "،": "K", "~": "Z", "ْ": "X", "آ": "N",
    "’": "M", "أ": "H",
}
_LIGATURES = {"لا": "b", "لإ": "T", "لأ": "G", "لآ": "B"}


def normalize_barcode(text: str) -> str:
    """يحوّل الأرقام العربية إلى لاتينية، ويصحح الأحرف الناتجة عن تخطيط عربي."""
    if not text:
        return ""
    text = text.strip().translate(_DIGITS)
    for lig, latin in _LIGATURES.items():
        text = text.replace(lig, latin)
    out = []
    for ch in text:
        if ch in _AR_UPPER:
            out.append(_AR_UPPER[ch])
        elif ch in _AR_LOWER:
            out.append(_AR_LOWER[ch])
        else:
            out.append(ch)
    return "".join(out)
