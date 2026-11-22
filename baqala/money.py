"""الحسابات المالية والكميات بدقة عشرية (Decimal) بدون float.

التخزين في قاعدة البيانات كأعداد صحيحة:
  - المبالغ: بوحدة 1/100 ريال (MONEY_SCALE)
  - الكميات: بوحدة 1/1000 (QTY_SCALE) لدعم الوزن مثل 0.250 كجم
بهذا تكون عمليات SUM في SQLite دقيقة تماماً.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .errors import ValidationError

MONEY_Q = Decimal("0.01")
QTY_Q = Decimal("0.001")
MONEY_SCALE = 100
QTY_SCALE = 1000
CURRENCY = "ر.ي"

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")


def D(value) -> Decimal:
    """تحويل آمن إلى Decimal. يرفض float لمنع أخطاء التقريب."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValidationError("قيمة رقمية غير صالحة")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError("لا يُسمح باستخدام float في الحسابات المالية")
    if value is None:
        raise ValidationError("القيمة مطلوبة")
    text = str(value).strip().translate(_DIGITS).replace(",", "").replace("٬", "")
    if not text:
        raise ValidationError("القيمة مطلوبة")
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise ValidationError(f"قيمة رقمية غير صالحة: {value}")
    if not result.is_finite():
        raise ValidationError(f"قيمة رقمية غير صالحة: {value}")
    return result


def money(value) -> Decimal:
    return D(value).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def qty(value) -> Decimal:
    return D(value).quantize(QTY_Q, rounding=ROUND_HALF_UP)


def money_to_int(value) -> int:
    return int(money(value) * MONEY_SCALE)


def int_to_money(value) -> Decimal:
    return (Decimal(int(value or 0)) / MONEY_SCALE).quantize(MONEY_Q)


def qty_to_int(value) -> int:
    return int(qty(value) * QTY_SCALE)


def int_to_qty(value) -> Decimal:
    return (Decimal(int(value or 0)) / QTY_SCALE).quantize(QTY_Q)


def line_total(quantity, unit_price) -> Decimal:
    """إجمالي السطر = الكمية × السعر، مقرّب إلى أقرب 0.01 (نصف للأعلى)."""
    return money(qty(quantity) * money(unit_price))


def line_total_int(qty_int: int, price_int: int) -> int:
    """نفس line_total لكن على القيم المخزنة كأعداد صحيحة."""
    return money_to_int(int_to_qty(qty_int) * int_to_money(price_int))


def fmt_money(value, with_currency: bool = False) -> str:
    m = money(value)
    if m == m.to_integral_value():
        text = f"{m:,.0f}"
    else:
        text = f"{m:,.2f}"
    return f"{text} {CURRENCY}" if with_currency else text


def fmt_qty(value) -> str:
    q = qty(value)
    if q == q.to_integral_value():
        return f"{q:.0f}"
    return f"{q:.3f}".rstrip("0").rstrip(".")
