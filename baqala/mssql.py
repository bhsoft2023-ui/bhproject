"""الاتصال بـ SQL Server (عبر ODBC/pyodbc) بنفس واجهة اتصال SQLite التي تستخدمها الخدمات.

- القاعدة وجداولها تُنشأ تلقائياً من baqala/sql/BaqalaPOS_SQLServer.sql عند أول اتصال.
- كل عملية متعددة الخطوات داخل معاملة واحدة مع XACT_ABORT، فانقطاع الكهرباء أو الشبكة
  أثناء العملية يُلغيها بالكامل، وما تم تثبيته (COMMIT) محفوظ في سجل SQL Server.
- المعاملات تأخذ قفل كتابة على مستوى التطبيق (sp_getapplock) حتى لا يتعارض كاشيران على
  نفس الدفعة أو نفس السقف الائتماني عند تشغيل أكثر من جهاز على نفس الخادم.
"""
import itertools
import logging
import re
from datetime import date, datetime
from pathlib import Path

from .errors import POSError, ValidationError

log = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent / "sql" / "BaqalaPOS_SQLServer.sql"
SCHEMA_MARKER = "-- @@schema"
LOCK_RESOURCE = "BaqalaPOS.write"
PREFERRED_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
_sp_counter = itertools.count(1)


class DatabaseConnectionError(POSError):
    pass


def _pyodbc():
    try:
        import pyodbc
    except ImportError as exc:  # pragma: no cover
        raise DatabaseConnectionError("مكتبة pyodbc غير مثبتة، ولا يمكن الاتصال بـ SQL Server") from exc
    return pyodbc


def check_db_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValidationError("اسم قاعدة البيانات يجب أن يكون بالأحرف الإنجليزية والأرقام و _ فقط")
    return name


def pick_driver(requested: str = "") -> str:
    installed = _pyodbc().drivers()
    if requested and requested in installed:
        return requested
    for d in PREFERRED_DRIVERS:
        if d in installed:
            return d
    raise DatabaseConnectionError(
        "لم يُعثر على تعريف ODBC لـ SQL Server على هذا الجهاز.\n"
        "ثبّت «Microsoft ODBC Driver 18 for SQL Server» ثم أعد تشغيل البرنامج."
    )


def _quote_odbc(value: str) -> str:
    value = str(value)
    if any(ch in value for ch in ";{}=") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value


def connection_string(cfg, database: str = None) -> str:
    driver = pick_driver(cfg.driver)
    parts = {
        "DRIVER": "{%s}" % driver,
        "SERVER": _quote_odbc(cfg.server),
        "DATABASE": _quote_odbc(database or cfg.database),
        "APP": "BaqalaPOS",
    }
    if cfg.auth == "sql":
        parts["UID"] = _quote_odbc(cfg.username)
        parts["PWD"] = _quote_odbc(cfg.password)
    else:
        parts["Trusted_Connection"] = "yes"
    if driver.startswith("ODBC Driver 18"):
        # الخادم المحلي يستخدم شهادة ذاتية التوقيع
        parts["Encrypt"] = "yes" if cfg.encrypt else "no"
        parts["TrustServerCertificate"] = "yes"
    return ";".join(f"{k}={v}" for k, v in parts.items())


def _to_py(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    return value


class Row:
    """صف يدعم row["col"] و row[0] و dict(row) مثل sqlite3.Row."""

    __slots__ = ("_index", "_values")

    def __init__(self, index, values):
        self._index = index
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._index[key.lower()]]
        except KeyError:
            raise IndexError(f"No item with that key: {key}") from None

    def keys(self):
        return list(self._index)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self.keys(), self._values))})"


class Cursor:
    """النتائج تُقرأ كاملة فوراً ويُغلق مؤشر ODBC، فلا يبقى الاتصال مشغولاً بنتائج لم تُقرأ."""

    def __init__(self, cur, lastrowid=None, rowcount=-1):
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self._rows = []
        self._pos = 0
        if cur is not None:
            if cur.description:
                index = {}
                for i, col in enumerate(cur.description):
                    index.setdefault(col[0].lower(), i)
                self._rows = [Row(index, tuple(_to_py(v) for v in raw)) for raw in cur.fetchall()]
            cur.close()

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def fetchall(self):
        rows, self._pos = self._rows[self._pos:], len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_DATE_FN = re.compile(r"\bdate\(([A-Za-z_][\w.]*)\)", re.IGNORECASE)
_LIMIT = re.compile(r"\s+LIMIT\s+(\?|\d+)\s*$", re.IGNORECASE)
_NON_ASCII_LITERAL = re.compile(r"(?<![\w'])'((?:[^']|'')*[^\x00-\x7f](?:[^']|'')*)'")


def translate(sql: str, params=None):
    """يحوّل الأجزاء القليلة الخاصة بـ SQLite إلى T-SQL: المعاملات المسماة، date()، LIMIT، والنصوص العربية."""
    if isinstance(params, dict):
        names = _NAMED.findall(sql)
        sql = _NAMED.sub("?", sql)
        params = [params[n] for n in names]
    sql = _DATE_FN.sub(r"CAST(\1 AS DATE)", sql)
    sql = _LIMIT.sub(r" OFFSET 0 ROWS FETCH NEXT \1 ROWS ONLY", sql)
    sql = _NON_ASCII_LITERAL.sub(r"N'\1'", sql)
    return sql, list(params or [])


_SQL_ERRORS = {
    "2627": "القيمة مسجلة مسبقاً (مكررة)",
    "2601": "القيمة مسجلة مسبقاً (مكررة)",
    "547": "العملية مرفوضة لأنها تخالف قيود سلامة البيانات (سجل مرتبط أو قيمة غير مسموحة)",
    "8152": "أحد الحقول أطول من الحد المسموح",
    "2628": "أحد الحقول أطول من الحد المسموح",
    "1205": "تعارض مؤقت مع جهاز آخر، أعد المحاولة",
}


def _friendly(exc):
    text = str(exc)
    for code, msg in _SQL_ERRORS.items():
        if f"({code})" in text or f"[{code}]" in text or f"Msg {code}," in text:
            return ValidationError(msg)
    return None


class MSSQLConnection:
    dialect = "mssql"

    def __init__(self, raw, cfg, database):
        self.raw = raw
        self.cfg = cfg
        self.database = database
        self._closed = False

    # ---- تنفيذ ----
    def _run(self, cur, sql, params):
        try:
            cur.execute(sql, params) if params else cur.execute(sql)
        except _pyodbc().Error as exc:
            friendly = _friendly(exc)
            if friendly:
                raise friendly from exc
            raise

    def execute(self, sql, params=None):
        sql, params = translate(sql, params)
        cur = self.raw.cursor()
        if sql.lstrip()[:6].upper() == "INSERT":
            self._run(cur, sql + ";\nSELECT CAST(SCOPE_IDENTITY() AS BIGINT)", params)
            rowcount = cur.rowcount
            new_id = None
            while cur.description is None and cur.nextset():
                pass
            if cur.description is not None:
                r = cur.fetchone()
                new_id = int(r[0]) if r and r[0] is not None else None
            cur.close()
            return Cursor(None, lastrowid=new_id, rowcount=rowcount)
        self._run(cur, sql, params)
        return Cursor(cur, rowcount=cur.rowcount)

    def executemany(self, sql, seq):
        sql, _ = translate(sql)
        seq = [list(p) for p in seq]
        if not seq:
            return Cursor(None, rowcount=0)
        cur = self.raw.cursor()
        try:
            cur.executemany(sql, seq)
        except _pyodbc().Error as exc:
            friendly = _friendly(exc)
            if friendly:
                raise friendly from exc
            raise
        finally:
            cur.close()
        return Cursor(None, rowcount=len(seq))

    def scalar(self, sql, params=None):
        row = self.execute(sql, params).fetchone()
        return None if row is None else row[0]

    # ---- المعاملات ----
    @property
    def in_transaction(self) -> bool:
        return bool(self.raw.cursor().execute("SELECT @@TRANCOUNT").fetchone()[0])

    def begin(self):
        cur = self.raw.cursor()
        cur.execute("BEGIN TRANSACTION")
        rc = cur.execute(
            "DECLARE @rc INT; EXEC @rc = sp_getapplock @Resource = ?, @LockMode = 'Exclusive',"
            " @LockOwner = 'Transaction', @LockTimeout = 15000; SELECT @rc",
            LOCK_RESOURCE,
        ).fetchone()[0]
        if rc < 0:
            self.rollback()
            raise ValidationError("قاعدة البيانات مشغولة بعملية من جهاز آخر، أعد المحاولة")

    def commit(self):
        if self.in_transaction:
            self.raw.cursor().execute("COMMIT TRANSACTION")

    def rollback(self):
        if self.in_transaction:
            self.raw.cursor().execute("ROLLBACK TRANSACTION")

    def savepoint(self):
        name = f"sp{next(_sp_counter)}"
        self.raw.cursor().execute(f"SAVE TRANSACTION {name}")
        return name

    def rollback_to(self, name):
        cur = self.raw.cursor()
        if cur.execute("SELECT XACT_STATE()").fetchone()[0] == 1:
            cur.execute(f"ROLLBACK TRANSACTION {name}")

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.rollback()
            except Exception:  # noqa: BLE001
                pass
            self.raw.close()


def _raw_connect(cfg, database, timeout=10):
    pyodbc = _pyodbc()
    try:
        raw = pyodbc.connect(connection_string(cfg, database), autocommit=True, timeout=timeout)
    except pyodbc.Error as exc:
        raise DatabaseConnectionError(
            f"تعذر الاتصال بخادم SQL Server «{cfg.server}».\n"
            "تأكد أن خدمة SQL Server تعمل وأن اسم الخادم وبيانات الدخول صحيحة.\n\n"
            f"التفاصيل: {exc}"
        ) from exc
    raw.setdecoding(pyodbc.SQL_WCHAR, encoding="utf-16le")
    raw.setencoding(encoding="utf-16le")
    raw.timeout = 60
    cur = raw.cursor()
    cur.execute("SET XACT_ABORT ON; SET LOCK_TIMEOUT 15000; SET DATEFORMAT ymd;")
    return raw


def _split_batches(script: str):
    batch = []
    for line in script.splitlines():
        if line.strip().upper() == "GO":
            text = "\n".join(batch).strip()
            if text:
                yield text
            batch = []
        else:
            batch.append(line)
    text = "\n".join(batch).strip()
    if text:
        yield text


def schema_batches():
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    idx = text.index(SCHEMA_MARKER)
    return list(_split_batches(text[idx:]))


# كل ترحيل جديد يُضاف كقائمة دفعات T-SQL في آخر القائمة ويرفع schema_info.version
def migrations():
    return [schema_batches()]


def ensure_database(cfg) -> None:
    """ينشئ القاعدة إن لم تكن موجودة (بترميز عربي، واسترداد بسيط، وقراءة لقطات)."""
    name = check_db_name(cfg.database)
    raw = _raw_connect(cfg, "master")
    try:
        cur = raw.cursor()
        if cur.execute("SELECT DB_ID(?)", name).fetchone()[0] is not None:
            return
        log.info("إنشاء قاعدة بيانات SQL Server: %s", name)
        cur.execute(f"CREATE DATABASE [{name}] COLLATE Arabic_CI_AS")
        cur.execute(f"ALTER DATABASE [{name}] SET RECOVERY SIMPLE")
        cur.execute(f"ALTER DATABASE [{name}] SET AUTO_CLOSE OFF")
        cur.execute(f"ALTER DATABASE [{name}] SET PAGE_VERIFY CHECKSUM")
        cur.execute(f"ALTER DATABASE [{name}] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE")
    finally:
        raw.close()


def schema_version(conn) -> int:
    if conn.scalar("SELECT OBJECT_ID(N'dbo.schema_info', N'U')") is None:
        return 0
    return int(conn.scalar("SELECT COALESCE(MAX(version), 0) FROM dbo.schema_info") or 0)


def migrate(conn) -> None:
    steps = migrations()
    if schema_version(conn) >= len(steps):
        return
    conn.begin()
    try:
        current = schema_version(conn)  # بعد القفل: ربما رحّلها جهاز آخر للتو
        cur = conn.raw.cursor()
        for version, batches in enumerate(steps, start=1):
            if version <= current:
                continue
            for b in batches:
                cur.execute(b)
            if version > 1:
                cur.execute("INSERT INTO dbo.schema_info (version) VALUES (?)", version)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def connect(cfg, create=True) -> MSSQLConnection:
    name = check_db_name(cfg.database)
    if create:
        ensure_database(cfg)
    conn = MSSQLConnection(_raw_connect(cfg, name), cfg, name)
    try:
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def integrity_ok(conn) -> bool:
    try:
        cur = conn.raw.cursor()
        cur.execute("DBCC CHECKDB WITH NO_INFOMSGS, PHYSICAL_ONLY")
        while cur.nextset():
            pass
        return True
    except _pyodbc().Error as exc:
        if "permission" in str(exc).lower() or "(2571)" in str(exc):
            log.warning("لا توجد صلاحية لفحص سلامة القاعدة: %s", exc)
            return True
        log.error("فحص سلامة قاعدة البيانات فشل: %s", exc)
        return False


# ---------------- النسخ الاحتياطي ----------------
def _drain(cur):
    while cur.nextset():
        pass


def backup_to(conn, path) -> None:
    """نسخة كاملة بصيغة .bak. المسار يجب أن يكون قابلاً للكتابة من خدمة SQL Server."""
    cur = conn.raw.cursor()
    cur.execute(
        f"BACKUP DATABASE [{conn.database}] TO DISK = ? WITH INIT, FORMAT, CHECKSUM, NAME = ?",
        str(path), f"BaqalaPOS {conn.database}",
    )
    _drain(cur)
    verify_file(conn, path)


def verify_file(conn, path) -> None:
    cur = conn.raw.cursor()
    try:
        header = cur.execute("RESTORE HEADERONLY FROM DISK = ?", str(path)).fetchone()
        _drain(cur)
        cur.execute("RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM", str(path))
        _drain(cur)
    except _pyodbc().Error as exc:
        raise ValidationError(f"ملف النسخة غير صالح أو تالف:\n{exc}") from exc
    if header is None:
        raise ValidationError("ملف النسخة لا يحتوي نسخة قاعدة بيانات")


def restore_from(cfg, path) -> None:
    """يستبدل القاعدة بالنسخة. يُغلق اتصالات الأجهزة الأخرى بالقاعدة أثناء الاستعادة."""
    name = check_db_name(cfg.database)
    raw = _raw_connect(cfg, "master")
    try:
        cur = raw.cursor()
        files = cur.execute("RESTORE FILELISTONLY FROM DISK = ?", str(path)).fetchall()
        _drain(cur)
        current = {
            r[0]: r[1] for r in cur.execute(
                "SELECT type_desc, physical_name FROM sys.master_files WHERE database_id = DB_ID(?)"
                " ORDER BY file_id", name).fetchall()
        }
        if not current:
            data_dir, log_dir = cur.execute(
                "SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(4000)),"
                " CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS NVARCHAR(4000))").fetchone()
            current = {"ROWS": f"{data_dir}{name}.mdf", "LOG": f"{log_dir}{name}_log.ldf"}
        moves, params = [], []
        for f in files:
            logical, ftype = f[0], f[2]
            target = current.get("ROWS" if ftype == "D" else "LOG")
            if target and ftype in ("D", "L"):
                moves.append("MOVE ? TO ?")
                params += [logical, target]
        exists = cur.execute("SELECT DB_ID(?)", name).fetchone()[0] is not None
        if exists:
            cur.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        try:
            sql = f"RESTORE DATABASE [{name}] FROM DISK = ? WITH REPLACE, CHECKSUM"
            if moves and len(moves) == len(files):
                sql += ", " + ", ".join(moves)
            cur.execute(sql, str(path), *params)
            _drain(cur)
        finally:
            cur.execute(f"IF DB_ID(?) IS NOT NULL ALTER DATABASE [{name}] SET MULTI_USER", name)
    finally:
        raw.close()
