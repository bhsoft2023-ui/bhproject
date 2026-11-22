"""المصروفات (إيجار، كهرباء، رواتب...)."""
from datetime import date

from ..db import now_str, transaction
from ..errors import ValidationError
from ..money import money, money_to_int
from .auth import require
from .inventory import parse_date

EXPENSE_CATEGORIES = ["إيجار", "كهرباء", "ماء", "رواتب", "نقل", "صيانة", "أخرى"]


def add_expense(conn, user, category, amount, description="", expense_date=None) -> int:
    require(user, "expense.manage")
    category = (category or "").strip()
    if not category:
        raise ValidationError("نوع المصروف مطلوب")
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("المبلغ يجب أن يكون أكبر من صفر")
    with transaction(conn):
        return conn.execute(
            "INSERT INTO expenses (category, amount, description, expense_date, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (category, money_to_int(amount), (description or "").strip(),
             parse_date(expense_date) or date.today().isoformat(), user.id, now_str()),
        ).lastrowid


def delete_expense(conn, user, expense_id) -> None:
    require(user, "expense.manage")
    with transaction(conn):
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


def list_expenses(conn, date_from, date_to):
    return conn.execute(
        "SELECT e.*, u.username FROM expenses e LEFT JOIN users u ON u.id = e.user_id"
        " WHERE e.expense_date BETWEEN ? AND ? ORDER BY e.expense_date DESC, e.id DESC",
        (date_from, date_to),
    ).fetchall()
