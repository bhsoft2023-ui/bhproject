"""التقارير: المبيعات، الأرباح، المصروفات، قيمة المخزون، والديون."""
from decimal import Decimal

from ..money import MONEY_Q, QTY_SCALE, int_to_money, int_to_qty
from . import parties


def _scaled_value(product_sum: int) -> Decimal:
    """قيمة = (الكمية/1000) × (السعر/100). نجمع حاصل الضرب الصحيح في SQL ثم نقسم مرة واحدة بدقة."""
    return (Decimal(int(product_sum or 0)) / (QTY_SCALE * 100)).quantize(MONEY_Q)


def sales_summary(conn, date_from: str, date_to: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt,"
        " COALESCE(SUM(total),0) AS total,"
        " COALESCE(SUM(CASE WHEN sale_type='cash' THEN total END),0) AS cash_total,"
        " COALESCE(SUM(CASE WHEN sale_type='credit' THEN total END),0) AS credit_total,"
        " COALESCE(SUM(CASE WHEN sale_type='credit' THEN total - paid END),0) AS credit_unpaid,"
        " COALESCE(SUM(cost_total),0) AS cost"
        " FROM sales WHERE date(created_at) BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchone()
    expenses = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", (date_from, date_to)
    ).fetchone()[0]
    write_offs = conn.execute(
        "SELECT COALESCE(SUM(-qty_change * unit_cost),0) FROM stock_adjustments"
        " WHERE qty_change < 0 AND date(created_at) BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchone()[0]
    cust_pay = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE date(created_at) BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchone()[0]
    total = int_to_money(row["total"])
    cost = int_to_money(row["cost"])
    gross = total - cost
    exp = int_to_money(expenses)
    wo = _scaled_value(write_offs)
    return {
        "count": row["cnt"],
        "total": total,
        "cash_total": int_to_money(row["cash_total"]),
        "credit_total": int_to_money(row["credit_total"]),
        "credit_unpaid": int_to_money(row["credit_unpaid"]),
        "customer_payments": int_to_money(cust_pay),
        "cost": cost,
        "gross_profit": gross,
        "expenses": exp,
        "write_offs": wo,
        "net_profit": gross - exp - wo,
    }


def daily_sales(conn, date_from, date_to):
    rows = conn.execute(
        "SELECT date(created_at) AS day, COUNT(*) AS cnt, SUM(total) AS total, SUM(cost_total) AS cost,"
        " SUM(CASE WHEN sale_type='cash' THEN total ELSE 0 END) AS cash,"
        " SUM(CASE WHEN sale_type='credit' THEN total ELSE 0 END) AS credit"
        " FROM sales WHERE date(created_at) BETWEEN ? AND ? GROUP BY day ORDER BY day",
        (date_from, date_to),
    ).fetchall()
    return [
        {
            "day": r["day"], "count": r["cnt"], "total": int_to_money(r["total"]),
            "cash": int_to_money(r["cash"]), "credit": int_to_money(r["credit"]),
            "profit": int_to_money(r["total"] - r["cost"]),
        }
        for r in rows
    ]


def top_products(conn, date_from, date_to, limit=50):
    rows = conn.execute(
        "SELECT si.product_name, si.unit, SUM(si.qty) AS qty, SUM(si.line_total) AS total,"
        " SUM(si.line_total - si.cost_total) AS profit FROM sale_items si JOIN sales s ON s.id = si.sale_id"
        " WHERE date(s.created_at) BETWEEN ? AND ? GROUP BY si.product_id ORDER BY total DESC LIMIT ?",
        (date_from, date_to, limit),
    ).fetchall()
    return [
        {"name": r["product_name"], "unit": r["unit"], "qty": int_to_qty(r["qty"]),
         "total": int_to_money(r["total"]), "profit": int_to_money(r["profit"])}
        for r in rows
    ]


def expenses_by_category(conn, date_from, date_to):
    rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses WHERE expense_date BETWEEN ? AND ?"
        " GROUP BY category ORDER BY total DESC",
        (date_from, date_to),
    ).fetchall()
    return [{"category": r["category"], "total": int_to_money(r["total"])} for r in rows]


def inventory_value(conn) -> dict:
    """قيمة المخزون الحالية بسعر التكلفة (من الدفعات) وبسعر البيع."""
    row = conn.execute(
        "SELECT COALESCE(SUM(b.qty_remaining * b.unit_cost),0) AS cost_value,"
        " COALESCE(SUM(b.qty_remaining * p.sell_price),0) AS retail_value,"
        " COUNT(DISTINCT CASE WHEN b.qty_remaining > 0 THEN b.product_id END) AS products"
        " FROM batches b JOIN products p ON p.id = b.product_id WHERE b.qty_remaining > 0"
    ).fetchone()
    cost = _scaled_value(row["cost_value"])
    retail = _scaled_value(row["retail_value"])
    return {"cost_value": cost, "retail_value": retail, "expected_profit": retail - cost, "products": row["products"]}


def debts_overview(conn) -> dict:
    return {
        "suppliers_debt": parties.total_debts(conn, "supplier"),
        "customers_debt": parties.total_debts(conn, "customer"),
    }
