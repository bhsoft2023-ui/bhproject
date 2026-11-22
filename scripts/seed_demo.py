"""بيانات تجريبية لتجربة النظام (لا تُشغّل على بيانات المحل الحقيقية).

الاستخدام:  set BAQALA_DATA_DIR=C:\\demo_baqala  ثم  python scripts/seed_demo.py
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baqala import config, db  # noqa: E402
from baqala.services import auth, expenses, parties, products, purchases, sales, settings  # noqa: E402


def main():
    conn = db.connect(config.db_path())
    auth.ensure_default_admin(conn)
    admin = auth.authenticate(conn, "admin", "admin") if conn.execute(
        "SELECT must_change_password FROM users WHERE username='admin'").fetchone()[0] else None
    if admin is None:
        print("قاعدة البيانات مستخدمة مسبقاً؛ لن تُضاف بيانات تجريبية.")
        return
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
        print("توجد أصناف مسبقاً.")
        return
    settings.set_many(conn, {"shop_name": "بقالة الأمانة", "shop_address": "صنعاء - شارع الزبيري", "shop_phone": "777000000"})
    cats = {n: products.add_category(conn, admin, n) for n in ["مواد غذائية", "ألبان", "بهارات", "منظفات", "مشروبات"]}
    today = date.today()
    items = [
        ("أرز بسمتي 1 كجم", "6281000000011", "مواد غذائية", "1800", "1500", False, False, "40", None, "10"),
        ("سكر (بالوزن)", "2000001", "مواد غذائية", "900", "750", True, False, "50", None, "5"),
        ("حليب طويل الأجل 1 لتر", "6281000000028", "ألبان", "700", "550", False, True, "24", 20, "6"),
        ("زبادي 170 جم", "6281000000035", "ألبان", "250", "180", False, True, "30", 3, "10"),
        ("كمون مطحون (بالوزن)", "2000002", "بهارات", "6000", "4500", True, False, "3.500", None, "1"),
        ("هيل حب (بالوزن)", "2000003", "بهارات", "24000", "20000", True, False, "0.750", None, "1"),
        ("صابون غسيل", "6281000000042", "منظفات", "500", "380", False, False, "4", None, "6"),
        ("ماء 1.5 لتر", "6281000000059", "مشروبات", "200", "130", False, True, "100", 200, "24"),
    ]
    sup = parties.save_party(conn, admin, "supplier", {"name": "مؤسسة الخير للتجارة", "phone": "771111111"})
    lines = []
    for name, bc, cat, price, cost, w, exp, q, days, mn in items:
        pid = products.create_product(conn, admin, {"name": name, "barcode": bc, "category_id": cats[cat],
                                                    "sell_price": price, "cost_price": cost, "is_weighted": w,
                                                    "track_expiry": exp, "min_qty": mn})
        lines.append(purchases.PurchaseLine(pid, Decimal(q), Decimal(cost),
                                            (today + timedelta(days=days)).isoformat() if days else None))
    purchases.create_purchase(conn, admin, lines, "credit", sup, paid="20000", note="فاتورة 1001")
    c1 = parties.save_party(conn, admin, "customer", {"name": "أحمد علي", "phone": "773333333", "credit_limit": "20000"})
    parties.save_party(conn, admin, "customer", {"name": "سالم محمد", "phone": "774444444", "credit_limit": "5000",
                                                  "opening_balance": "4500"})
    sales.create_sale(conn, admin, [sales.CartLine(1, Decimal(2)), sales.CartLine(5, Decimal("0.250"))])
    sales.create_sale(conn, admin, [sales.CartLine(3, Decimal(3)), sales.CartLine(2, Decimal("1.500"))], "credit", c1, paid="500")
    expenses.add_expense(conn, admin, "كهرباء", "3000", "فاتورة الشهر")
    auth.create_user(conn, admin, "cashier", "موظف الكاشير", "1234", "cashier")
    print("تمت إضافة البيانات التجريبية. الدخول: admin/admin (سيُطلب تغييرها) أو cashier/1234")


if __name__ == "__main__":
    main()
