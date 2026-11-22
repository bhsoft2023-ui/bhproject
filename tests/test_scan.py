from baqala.scan import ScanDetector, parse_scan_input


def _type(det, text, start, step):
    t = start
    for ch in text:
        det.feed_char(ch, t)
        t += step
    return t


def test_fast_burst_is_scan():
    d = ScanDetector()
    t = _type(d, "6281001234567", 0, 8)
    assert d.feed_enter(t) == "6281001234567"


def test_human_typing_not_scan():
    d = ScanDetector()
    t = _type(d, "5000", 0, 180)
    assert d.feed_enter(t) is None


def test_slow_prefix_then_burst_only_burst_counts():
    d = ScanDetector()
    t = _type(d, "12", 0, 300)
    t = _type(d, "99887766", t + 400, 5)
    assert d.feed_enter(t) == "99887766"


def test_too_short_is_not_scan():
    d = ScanDetector()
    t = _type(d, "12", 0, 5)
    assert d.feed_enter(t) is None


def test_arabic_layout_scan_normalized():
    d = ScanDetector()
    t = _type(d, "٦٢٨١٠٠", 0, 5)
    assert d.feed_enter(t) == "628100"


def test_parse_qty_prefix():
    assert parse_scan_input("0.250*628") == ("0.250", "628")
    assert parse_scan_input(" 628 ") == (None, "628")
