from decimal import Decimal

import pytest

from baqala.errors import ValidationError
from baqala.money import (D, fmt_money, fmt_qty, int_to_money, int_to_qty, line_total, line_total_int, money,
                          money_to_int, qty, qty_to_int)


def test_rejects_float():
    with pytest.raises(TypeError):
        D(0.1)


def test_parses_arabic_digits_and_separators():
    assert D("١٬٢٥٠٫٥") == Decimal("1250.5")
    assert D("1,500") == Decimal("1500")


def test_invalid_input():
    for bad in ["", "abc", "nan", "inf", None]:
        with pytest.raises(ValidationError):
            D(bad)


def test_weighted_line_total_exact():
    # 0.250 كجم بهارات × 6000 ريال/كجم = 1500 ريال بالضبط
    assert line_total("0.250", "6000") == Decimal("1500.00")
    assert line_total("0.333", "1000") == Decimal("333.00")
    assert line_total("0.125", "1001") == Decimal("125.13")  # 125.125 -> نصف للأعلى


def test_classic_float_error_avoided():
    assert money("0.1") + money("0.2") == money("0.3")
    assert sum(line_total("1", "0.10") for _ in range(10)) == Decimal("1.00")


def test_int_roundtrip():
    assert money_to_int("1234.56") == 123456
    assert int_to_money(123456) == Decimal("1234.56")
    assert qty_to_int("0.250") == 250
    assert int_to_qty(250) == Decimal("0.250")
    assert qty("1.0004") == Decimal("1.000")


def test_line_total_int_matches_decimal():
    assert line_total_int(250, 600000) == money_to_int(line_total("0.250", "6000"))
    assert line_total_int(1333, 75050) == money_to_int(line_total("1.333", "750.50"))


def test_formatting():
    assert fmt_money("1500") == "1,500"
    assert fmt_money("1500.5") == "1,500.50"
    assert fmt_money("200", with_currency=True) == "200 ر.ي"
    assert fmt_qty("0.250") == "0.25"
    assert fmt_qty("3") == "3"
