import os
import pymysql
import config


def get_db_connection():
    """Opens a fresh connection to the MySQL database.

    We call this at the start of every route that needs the database.
    Rows come back as dicts, e.g. {'name': 'Python Programming'}.

    Supports TiDB Cloud (SSL) via SE_DB_SSL_CA env var.
    """
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

    # TiDB Cloud and other managed MySQL providers require SSL
    ssl_ca = os.environ.get("SE_DB_SSL_CA", "")
    if ssl_ca:
        if ssl_ca.lower() in ("1", "true"):
            # Use system CA bundle (works on most Linux distros and Render)
            ssl_ca = "/etc/ssl/certs/ca-certificates.crt"
        if os.path.isfile(ssl_ca):
            db_conf["ssl"] = {"ca": ssl_ca}
            db_conf["ssl_verify_cert"] = True
            db_conf["ssl_verify_identity"] = True
        else:
            # Fallback: allow unverified SSL (still encrypted, just not CA-checked)
            db_conf["ssl"] = {"ca": None}
            db_conf["ssl_disabled"] = False

    connection = pymysql.connect(**db_conf)
    return connection


def query(sql, params=(), one=False):
    """Run a SELECT and return the rows as a list of dicts.

    Pass one=True to get a single dict (or None) instead of a list.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE and return the new row id (or affected count)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()