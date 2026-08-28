"""Database layer - auto-detects MySQL or SQLite.

If MySQL is configured and reachable, uses MySQL.
Otherwise falls back to SQLite (skill_exchange.db) - zero setup needed.

MySQL-specific SQL functions (IF(), NOW(), CURDATE(), etc.) are
auto-translated to SQLite equivalents at query time.
"""
import os
import re
import sqlite3

import config

# --- Auto-detect which database to use ---

_use_sqlite = False


def _test_mysql():
    """Quick check: can we connect to MySQL?"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=config.MYSQL_HOST,
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
    (r"\bNOW\(\)", "datetime('now')"),
    (r"\bCURDATE\(\)", "date('now')"),
    (r"\bDATE_ADD\s*\(\s*date\('now'\)\s*,\s*INTERVAL\s+(\d+)\s+WEEK\s*\)",
     r"date('now', '+\1 days')"),
    (r"\bDATE_ADD\s*\(\s*(\w+)\s*,\s*INTERVAL\s+(\d+)\s+WEEK\s*\)",
     r"date(\1, '+\2 days')"),
]


def _translate_sql(sql):
    """Translate MySQL-specific functions to SQLite equivalents."""
    if not _use_sqlite:
        return sql
    result = sql
    for pattern, replacement in _TRANSLATIONS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
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
    conn = sqlite3.connect(_sqlite_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db_connection():
    """Opens a fresh database connection (MySQL or SQLite)."""
    if _use_sqlite:
        return _sqlite_conn()
    return _mysql_conn()


def query(sql, params=(), one=False):
    """Run a SELECT and return rows as a list of dicts (or single dict)."""
    sql = _translate_sql(sql)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if _use_sqlite:
            rows = [dict(r) for r in cur.fetchall()]
        else:
            rows = cur.fetchall()
        cur.close()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE and return the new row id."""
    sql = _translate_sql(sql)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        result = cur.lastrowid
        cur.close()
        return result
    finally:
        conn.close()
