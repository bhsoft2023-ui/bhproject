from decimal import Decimal

import pytest

from baqala.errors import ValidationError
from baqala.services import auth, expenses, inventory, parties, products, purchases, reports, sales
from baqala.services.sales import CartLine


def test_barcode_unique_and_arabic_layout_lookup(conn, admin, make_product):
    pid = make_product("صابون", barcode="AB12")
    with pytest.raises(ValidationError):
        make_product("آخر", barcode="AB12")
    # الماسح أرسل الحروف بتخطيط عربي (Shift+A = ِ , Shift+B = لآ) والأرقام عربية
    assert products.find_by_barcode(conn, "ِلآ١٢")["id"] == pid
    assert products.find_by_barcode(conn, " AB12 ")["id"] == pid


def test_search_name_normalized_and_category(conn, admin, make_product):
    cat = products.add_category(conn, admin, "منظفات")
    make_product("مسحوق إيريال", barcode="6281000000011", category_id=cat)
    make_product("أرز بسمتي", barcode="6281000000028")
    assert [r["name"] for r in products.search_products(conn, "ايريال")] == ["مسحوق إيريال"]
    assert [r["name"] for r in products.search_products(conn, "ارز")] == ["أرز بسمتي"]
    assert len(products.search_products(conn, "628100")) == 2
    assert [r["name"] for r in products.search_products(conn, "", cat)] == ["مسحوق إيريال"]


def test_delete_product_hard_and_soft(conn, admin, make_product):
    a = make_product("بدون حركة")
    assert products.delete_product(conn, admin, a) == "deleted"
    b = make_product("له حركة", barcode="999", price="10")
    inventory.add_opening_stock(conn, admin, b, 1, 5)
    with pytest.raises(ValidationError):
        products.delete_product(conn, admin, b)
    sales.create_sale(conn, admin, [CartLine(b, Decimal(1))])
    assert products.delete_product(conn, admin, b) == "deactivated"
    assert products.find_by_barcode(conn, "999") is None


def test_low_stock(conn, admin, make_product):
    p = make_product("شاي", min_qty="5")
    inventory.add_opening_stock(conn, admin, p, 4, 100)
    make_product("قهوة", min_qty="0")
    assert [r["name"] for r in products.low_stock(conn)] == ["شاي"]


def test_reports(conn, admin, make_product, make_customer):
    p = make_product("دقيق", price="1000", weighted=True)
    sid_ = parties.save_party(conn, admin, "supplier", {"name": "مورد"})
    purchases.create_purchase(conn, admin, [purchases.PurchaseLine(p, Decimal("10"), Decimal("600"))], "credit", sid_)
    c = make_customer(limit="100000")
    sales.create_sale(conn, admin, [CartLine(p, Decimal("2.5"))], created_at="2026-06-01 10:00:00")
    sales.create_sale(conn, admin, [CartLine(p, Decimal("1"))], "credit", c, created_at="2026-06-01 11:00:00")
    expenses.add_expense(conn, admin, "كهرباء", "300", expense_date="2026-06-01")
    s = reports.sales_summary(conn, "2026-06-01", "2026-06-01")
    assert s["total"] == Decimal("3500.00")
    assert s["cash_total"] == Decimal("2500.00") and s["credit_total"] == Decimal("1000.00")
    assert s["cost"] == Decimal("2100.00")
    assert s["gross_profit"] == Decimal("1400.00")
    assert s["net_profit"] == Decimal("1100.00")
    inv = reports.inventory_value(conn)
    assert inv["cost_value"] == Decimal("3900.00")  # 6.5 × 600
    assert inv["retail_value"] == Decimal("6500.00")
    debts = reports.debts_overview(conn)
    assert debts["suppliers_debt"] == Decimal("6000.00")
    assert debts["customers_debt"] == Decimal("1000.00")
    assert reports.top_products(conn, "2026-06-01", "2026-06-01")[0]["qty"] == Decimal("3.500")


def test_auth(conn, admin):
    assert admin.must_change_password
    auth.change_password(conn, admin.id, "admin", "s3cret")
    assert not auth.authenticate(conn, "ADMIN", "s3cret").must_change_password
    with pytest.raises(Exception):
        auth.authenticate(conn, "admin", "admin")
    with pytest.raises(ValidationError):
        auth.update_user(conn, admin, admin.id, "x", "cashier", True)  # آخر مدير
