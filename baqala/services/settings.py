"""إعدادات المحل والنظام (مخزنة في جدول settings)."""
from ..db import transaction

DEFAULTS = {
    "shop_name": "بقالة",
    "shop_address": "",
    "shop_phone": "",
    "receipt_footer": "شكراً لزيارتكم",
    "auto_print": "0",
    "printer_name": "",
    "expiry_warning_days": "30",
    "backup_interval_hours": "4",
    "backup_keep": "60",
    "backup_dir": "",
    "backup_extra_dir": "",
    "last_backup_at": "",
}


def get(conn, key: str) -> str:
    row = conn.execute('SELECT value FROM settings WHERE "key" = ?', (key,)).fetchone()
    return row["value"] if row else DEFAULTS.get(key, "")


def get_int(conn, key: str, fallback: int = 0) -> int:
    try:
        return int(get(conn, key))
    except (TypeError, ValueError):
        return fallback


def get_all(conn) -> dict:
    data = dict(DEFAULTS)
    for row in conn.execute('SELECT "key", value FROM settings'):
        data[row["key"]] = row["value"]
    return data


def set_many(conn, values: dict) -> None:
    with transaction(conn):
        for key, value in values.items():
            cur = conn.execute('UPDATE settings SET value = ? WHERE "key" = ?', (str(value), key))
            if cur.rowcount == 0:
                conn.execute('INSERT INTO settings ("key", value) VALUES (?, ?)', (key, str(value)))


def set_value(conn, key: str, value) -> None:
    set_many(conn, {key: value})
