"""مسارات البيانات.

قاعدة البيانات والنسخ الاحتياطية والسجلات تُحفظ خارج مجلد البرنامج
(في ProgramData على ويندوز) حتى لا تُحذف عند التحديث أو إعادة التثبيت.
"""
import os
import sys
from pathlib import Path

from . import APP_NAME


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    override = os.environ.get("BAQALA_DATA_DIR")
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p
    candidates = []
    if sys.platform == "win32":
        if os.environ.get("PROGRAMDATA"):
            candidates.append(Path(os.environ["PROGRAMDATA"]) / APP_NAME)
        if os.environ.get("LOCALAPPDATA"):
            candidates.append(Path(os.environ["LOCALAPPDATA"]) / APP_NAME)
    else:
        candidates.append(Path.home() / f".{APP_NAME.lower()}")
    for c in candidates:
        if _is_writable(c):
            return c
    raise RuntimeError("تعذر إيجاد مجلد قابل للكتابة لحفظ البيانات")


def db_path() -> Path:
    return data_dir() / "baqala.db"


def default_backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p
