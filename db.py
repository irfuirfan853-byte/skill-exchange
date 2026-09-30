"""Database layer - auto-detects MySQL or SQLite.

If MySQL is configured and reachable, uses MySQL.
Otherwise falls back to SQLite (skill_exchange.db) - zero setup needed.

MySQL-specific SQL functions (IF(), NOW(), CURDATE(), etc.) are
auto-translated to SQLite equivalents at query time.
"""
import os
import re
import sqlite3
from datetime import datetime

import pymysql

import config

# --- Auto-detect which database to use ---

_use_sqlite = False


def _test_mysql():
    """Quick check: can we connect to MySQL?"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=config.MYSQL_HOST,
            port=int(os.environ.get("SE_DB_PORT", "3306")),
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            charset="utf8mb4",
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def _sqlite_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_exchange.db")


def _sqlite_available():
    return os.path.isfile(_sqlite_path())


# Decide on first use
if _test_mysql():
    _use_sqlite = False
elif _sqlite_available():
    _use_sqlite = True
else:
    _use_sqlite = False


# --- MySQL-specific -> SQLite translation ---

_TRANSLATIONS = [
    (r"\bIF\s*\(\s*(.+?)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)",
     r"CASE WHEN \1 THEN \2 ELSE \3 END"),
    (r"\bNOW\(\)", "datetime('now','localtime')"),
    (r"\bCURDATE\(\)", "date('now','localtime')"),
    (r"\bDATE_ADD\s*\(\s*date\('now','localtime'\)\s*,\s*INTERVAL\s+(\d+)\s+WEEK\s*\)",
     r"date('now','localtime','+\1 days')"),
    (r"\bDATE_ADD\s*\(\s*(\w+)\s*,\s*INTERVAL\s+(\d+)\s+WEEK\s*\)",
     r"date(\1,'+\2 days')"),
    # DATE_ADD with a bound parameter (%s) instead of a literal number.
    # NOTE: these run BEFORE %s is converted to ?, so match %s literally.
    (r"\bDATE_ADD\s*\(\s*date\('now','localtime'\)\s*,\s*INTERVAL\s+%s\s+WEEK\s*\)",
     r"date('now','localtime','+' || %s || ' days')"),
    (r"\bDATE_ADD\s*\(\s*([\w.]+)\s*,\s*INTERVAL\s+%s\s+WEEK\s*\)",
     r"date(\1, '+' || %s || ' days')"),
    # GROUP_CONCAT(x SEPARATOR ', ')  ->  group_concat(x, ', ')
    (r"\bGROUP_CONCAT\s*\(\s*([^()]+?)\s+SEPARATOR\s+('[^']*')\s*\)",
     r"group_concat(\1, \2)"),
]


def _translate_sql(sql):
    """Translate MySQL-specific functions to SQLite equivalents."""
    if not _use_sqlite:
        return sql
    result = sql
    for pattern, replacement in _TRANSLATIONS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # sqlite3 uses '?' placeholders, MySQL/PyMySQL uses '%s'
    result = result.replace("%s", "?")
    return result


# --- Connection helpers ---

def _mysql_conn():
    """Open a fresh MySQL connection."""
    import pymysql
    db_conf = {
        "host": config.MYSQL_HOST,
        "port": int(os.environ.get("SE_DB_PORT", "3306")),
        "user": config.MYSQL_USER,
        "password": config.MYSQL_PASSWORD,
        "database": config.MYSQL_DB,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": True,
        "charset": "utf8mb4",
        "connect_timeout": 5,
    }
    ssl_ca = os.environ.get("SE_DB_SSL_CA", "")
    if ssl_ca:
        if ssl_ca.lower() in ("1", "true"):
            ssl_ca = "/etc/ssl/certs/ca-certificates.crt"
        if os.path.isfile(ssl_ca):
            db_conf["ssl"] = {"ca": ssl_ca}
            db_conf["ssl_verify_cert"] = True
            db_conf["ssl_verify_identity"] = True
        else:
            db_conf["ssl"] = {"ca": None}
            db_conf["ssl_disabled"] = False
    return pymysql.connect(**db_conf)


def _sqlite_conn():
    """Open a fresh SQLite connection."""
    conn = sqlite3.connect(_sqlite_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db_connection():
    """Opens a fresh database connection (MySQL or SQLite)."""
    if _use_sqlite:
        return _sqlite_conn()
    return _mysql_conn()


def _wrap_sqlite_error(e):
    """Re-raise SQLite errors as pymysql errors so the app's existing
    `except pymysql.MySQLError` handlers catch them (keeps one error path)."""
    raise pymysql.err.OperationalError(str(e)) from e


# Columns SQLite stores as TEXT but templates expect as datetime/date objects.
_DATETIME_COLS = {
    "last_seen", "created_at", "issued_at", "started_at",
    "ended_at", "completed_at", "responded_at",
    # aliases used by aggregate/subquery SELECTs
    "last_at", "other_last_seen",
}
_DATE_COLS = {"start_date", "end_date"}


def _coerce_sqlite_row(row):
    """Convert SQLite date/time strings to datetime/date objects in place
    (only for known date columns — never touches free text like messages)."""
    for k, v in row.items():
        if k in _DATETIME_COLS and isinstance(v, str):
            try:
                row[k] = datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        elif k in _DATE_COLS and isinstance(v, str):
            try:
                row[k] = datetime.strptime(v[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
    return row


def query(sql, params=(), one=False):
    """Run a SELECT and return rows as a list of dicts (or single dict)."""
    sql = _translate_sql(sql)
    try:
        conn = get_db_connection()
    except sqlite3.Error as e:
        _wrap_sqlite_error(e)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if _use_sqlite:
            rows = [_coerce_sqlite_row(dict(r)) for r in cur.fetchall()]
        else:
            rows = cur.fetchall()
        cur.close()
        return (rows[0] if rows else None) if one else rows
    except sqlite3.Error as e:
        _wrap_sqlite_error(e)
    except sqlite3.Warning:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE and return the new row id."""
    sql = _translate_sql(sql)
    try:
        conn = get_db_connection()
    except sqlite3.Error as e:
        _wrap_sqlite_error(e)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        result = cur.lastrowid
        cur.close()
        return result
    except sqlite3.Error as e:
        _wrap_sqlite_error(e)
    finally:
        try:
            conn.close()
        except Exception:
            pass
