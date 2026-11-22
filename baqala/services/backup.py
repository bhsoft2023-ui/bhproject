"""النسخ الاحتياطي التلقائي والاستعادة.

- يستخدم SQLite Online Backup API: نسخة متسقة حتى أثناء عمل البرنامج.
- يتحقق من سلامة كل نسخة (integrity_check) ويحذف الأقدم بعد تجاوز العدد المحدد.
- يمكن نسخ إضافي لمجلد ثانٍ (فلاشة/قرص آخر) للحماية من تلف القرص.
"""
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..errors import ValidationError

log = logging.getLogger(__name__)
PREFIX = "baqala_"
SUFFIX = ".db"


def backup_filename(now: datetime = None, tag: str = "") -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{PREFIX}{stamp}{('_' + tag) if tag else ''}{SUFFIX}"


def create_backup(conn, backup_dir, keep: int = 60, extra_dir=None, now: datetime = None, tag: str = "") -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / backup_filename(now, tag)
    i = 1
    while target.exists():
        target = backup_dir / backup_filename(now, f"{tag}{i}")
        i += 1
    tmp = target.with_suffix(".tmp")
    dest = sqlite3.connect(str(tmp))
    try:
        conn.backup(dest)
        ok = dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        dest.close()
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("فشل التحقق من سلامة النسخة الاحتياطية")
    tmp.replace(target)
    rotate(backup_dir, keep)
    if extra_dir:
        try:
            extra = Path(extra_dir)
            extra.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, extra / target.name)
            rotate(extra, keep)
        except OSError as exc:
            log.warning("تعذر النسخ إلى المجلد الإضافي %s: %s", extra_dir, exc)
    log.info("تم إنشاء نسخة احتياطية: %s", target)
    return target


def list_backups(backup_dir):
    d = Path(backup_dir)
    if not d.exists():
        return []
    return sorted(d.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True)


def rotate(backup_dir, keep: int) -> None:
    keep = max(int(keep), 1)
    for old in list_backups(backup_dir)[keep:]:
        try:
            old.unlink()
        except OSError as exc:
            log.warning("تعذر حذف نسخة قديمة %s: %s", old, exc)


def is_due(last_backup_at: str, interval_hours: int, now: datetime = None) -> bool:
    if interval_hours <= 0:
        return False
    if not last_backup_at:
        return True
    try:
        last = datetime.strptime(last_backup_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (now or datetime.now()) - last >= timedelta(hours=interval_hours)


def verify_backup_file(path) -> None:
    path = Path(path)
    if not path.is_file():
        raise ValidationError("ملف النسخة غير موجود")
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValidationError("ملف النسخة تالف")
            c.execute("SELECT COUNT(*) FROM products").fetchone()
        finally:
            c.close()
    except sqlite3.DatabaseError:
        raise ValidationError("الملف المختار ليس نسخة احتياطية صالحة لهذا النظام")


def restore_backup(db_path, backup_file, safety_dir) -> Path:
    """يستعيد نسخة. يجب إغلاق اتصال قاعدة البيانات قبل الاستدعاء.
    يحفظ نسخة أمان من البيانات الحالية قبل الاستبدال."""
    verify_backup_file(backup_file)
    db_path = Path(db_path)
    safety = None
    if db_path.exists():
        src = sqlite3.connect(str(db_path))
        try:
            safety = create_backup(src, safety_dir, keep=1000, tag="before_restore")
        finally:
            src.close()
    for ext in ("-wal", "-shm"):
        Path(str(db_path) + ext).unlink(missing_ok=True)
    tmp = db_path.with_suffix(".restore_tmp")
    shutil.copy2(backup_file, tmp)
    tmp.replace(db_path)
    return safety
