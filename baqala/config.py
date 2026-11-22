"""مسارات البيانات.

قاعدة البيانات والنسخ الاحتياطية والسجلات تُحفظ خارج مجلد البرنامج
(في ProgramData على ويندوز) حتى لا تُحذف عند التحديث أو إعادة التثبيت.
"""
import base64
import configparser
import os
import sys
from dataclasses import dataclass
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


# ---------------- إعداد قاعدة البيانات (SQL Server أو SQLite) ----------------
DB_INI = "database.ini"
DEFAULT_SERVER = r".\SQLEXPRESS"
DEFAULT_DATABASE = "BaqalaPOS"


@dataclass
class DatabaseConfig:
    engine: str = "mssql"  # mssql | sqlite
    server: str = DEFAULT_SERVER
    database: str = DEFAULT_DATABASE
    auth: str = "windows"  # windows | sql
    username: str = ""
    password: str = ""
    driver: str = ""  # فارغ = اختيار تلقائي لأحدث تعريف ODBC مثبت
    encrypt: bool = False

    @property
    def label(self) -> str:
        if self.engine == "sqlite":
            return f"SQLite: {db_path()}"
        return f"SQL Server: {self.server} / {self.database}"


def db_ini_path() -> Path:
    return data_dir() / DB_INI


def _dpapi(data: bytes, protect: bool) -> bytes:
    """تشفير كلمة مرور SQL بـ Windows DPAPI (على مستوى الجهاز)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    crypt32 = ctypes.windll.crypt32
    local_machine = 0x4
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, local_machine, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _encode_secret(value: str) -> str:
    if not value:
        return ""
    raw = value.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
        except OSError:
            pass
    return "b64:" + base64.b64encode(raw).decode("ascii")


def _decode_secret(value: str) -> str:
    if not value:
        return ""
    kind, _, payload = value.partition(":")
    try:
        data = base64.b64decode(payload)
        if kind == "dpapi":
            data = _dpapi(data, False)
        elif kind != "b64":
            return value
        return data.decode("utf-8")
    except (ValueError, OSError):
        return ""


def load_db_config() -> DatabaseConfig:
    """يقرأ database.ini. عند غيابه: SQL Server افتراضياً، إلا إن وُجدت بيانات SQLite سابقة على الجهاز."""
    path = db_ini_path()
    if not path.exists():
        return DatabaseConfig(engine="sqlite" if db_path().exists() else "mssql")
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    s = cp["database"] if cp.has_section("database") else {}
    cfg = DatabaseConfig(
        engine=s.get("engine", "mssql").strip().lower(),
        server=s.get("server", DEFAULT_SERVER).strip() or DEFAULT_SERVER,
        database=s.get("database", DEFAULT_DATABASE).strip() or DEFAULT_DATABASE,
        auth=s.get("auth", "windows").strip().lower(),
        username=s.get("username", "").strip(),
        password=_decode_secret(s.get("password", "").strip()),
        driver=s.get("driver", "").strip(),
        encrypt=s.get("encrypt", "no").strip().lower() in ("1", "yes", "true"),
    )
    if cfg.engine not in ("mssql", "sqlite"):
        cfg.engine = "mssql"
    if cfg.auth not in ("windows", "sql"):
        cfg.auth = "windows"
    return cfg


def save_db_config(cfg: DatabaseConfig) -> None:
    cp = configparser.ConfigParser()
    cp["database"] = {
        "engine": cfg.engine, "server": cfg.server, "database": cfg.database, "auth": cfg.auth,
        "username": cfg.username if cfg.auth == "sql" else "",
        "password": _encode_secret(cfg.password) if cfg.auth == "sql" else "",
        "driver": cfg.driver, "encrypt": "yes" if cfg.encrypt else "no",
    }
    path = db_ini_path()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("; إعداد الاتصال بقاعدة البيانات — engine = mssql أو sqlite\n")
        cp.write(fh)
    tmp.replace(path)
