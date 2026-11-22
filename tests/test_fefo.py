from decimal import Decimal

import pytest

from baqala.errors import InsufficientStock, ValidationError
from baqala.money import qty_to_int
from baqala.services import inventory, products, purchases, sales
from baqala.services.sales import CartLine


def _batches(conn, pid):
    return {r["expiry_date"]: r["qty_remaining"] for r in inventory.list_batches(conn, pid, only_available=False)}


def test_fefo_picks_nearest_expiry_first(conn, admin, make_product):
    pid = make_product("حليب", track_expiry=True)
    inventory.add_opening_stock(conn, admin, pid, 10, 500, "2027-03-01")
    inventory.add_opening_stock(conn, admin, pid, 5, 500, "2027-01-01")
    inventory.add_opening_stock(conn, admin, pid, 5, 500, "2027-02-01")

    allocs = inventory.allocate_fefo(conn, pid, qty_to_int(7), today="2026-12-01")
    assert [(a.qty) for a in allocs] == [5000, 2000]
    b = {r["id"]: r["expiry_date"] for r in inventory.list_batches(conn, pid)}
    assert [b[a.batch_id] for a in allocs] == ["2027-01-01", "2027-02-01"]


def test_sale_deducts_by_fefo(conn, admin, make_product):
    pid = make_product("زبادي", track_expiry=True)
    inventory.add_opening_stock(conn, admin, pid, 3, 100, "2027-05-01")
    inventory.add_opening_stock(conn, admin, pid, 3, 100, "2027-04-01")
    sales.create_sale(conn, admin, [CartLine(pid, Decimal(4))], today="2027-01-01")
    assert _batches(conn, pid) == {"2027-04-01": 0, "2027-05-01": 2000}


def test_expired_batches_not_sold(conn, admin, make_product):
    pid = make_product("جبن", track_expiry=True)
    inventory.add_opening_stock(conn, admin, pid, 5, 100, "2026-01-01")
    inventory.add_opening_stock(conn, admin, pid, 2, 100, "2027-01-01")
    with pytest.raises(InsufficientStock) as e:
        inventory.allocate_fefo(conn, pid, qty_to_int(3), today="2026-06-01")
    assert "منتهي" in e.value.message
    allocs = inventory.allocate_fefo(conn, pid, qty_to_int(2), today="2026-06-01")
    assert sum(a.qty for a in allocs) == 2000


def test_expiry_day_itself_still_sellable(conn, admin, make_product):
    pid = make_product("خبز", track_expiry=True)
    inventory.add_opening_stock(conn, admin, pid, 1, 100, "2026-06-01")
    assert inventory.allocate_fefo(conn, pid, 1000, today="2026-06-01")


def test_batches_without_expiry_used_after_dated(conn, admin, make_product):
    pid = make_product("ملح")
    inventory.add_opening_stock(conn, admin, pid, 5, 100, None)
    inventory.add_opening_stock(conn, admin, pid, 5, 100, "2030-01-01")
    allocs = inventory.allocate_fefo(conn, pid, qty_to_int(6), today="2026-01-01")
    first = inventory.list_batches(conn, pid)[0]
    assert allocs[0].batch_id == first["id"] and first["expiry_date"] == "2030-01-01"


def test_track_expiry_requires_date(conn, admin, make_product):
    pid = make_product("لبن", track_expiry=True)
    with pytest.raises(ValidationError):
        inventory.add_opening_stock(conn, admin, pid, 1, 100, None)


def test_expiry_alerts(conn, admin, make_product):
    pid = make_product("عصير", track_expiry=True)
    inventory.add_opening_stock(conn, admin, pid, 1, 100, "2026-05-01")
    inventory.add_opening_stock(conn, admin, pid, 1, 100, "2026-06-10")
    inventory.add_opening_stock(conn, admin, pid, 1, 100, "2026-12-01")
    alerts = inventory.expiry_alerts(conn, 30, today="2026-06-01")
    assert [(a["row"]["expiry_date"], a["expired"]) for a in alerts] == [("2026-05-01", True), ("2026-06-10", False)]


def test_write_off_expired(conn, admin, make_product):
    pid = make_product("قشطة", track_expiry=True)
    bid = inventory.add_opening_stock(conn, admin, pid, 4, 250, "2026-01-01")
    inventory.write_off(conn, admin, bid, 4, "منتهي الصلاحية")
    assert products.get_product(conn, pid)["stock"] == 0
    with pytest.raises(InsufficientStock):
        inventory.write_off(conn, admin, bid, 1, "تالف")


def test_purchase_creates_batches_and_supplier_debt(conn, admin, make_product):
    from baqala.services import parties
    pid = make_product("سكر", weighted=True)
    sid = parties.save_party(conn, admin, "supplier", {"name": "مورد"})
    purchases.create_purchase(
        conn, admin, [purchases.PurchaseLine(pid, Decimal("50.5"), Decimal("700"), None)],
        "credit", sid, paid="5000",
    )
    assert products.get_product(conn, pid)["stock"] == 50500
    assert parties.balance(conn, "supplier", sid) == Decimal("30350.00")  # 35350 - 5000
