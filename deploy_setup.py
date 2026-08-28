"""Database setup script for cloud deployment.

Run this once after deploying to set up the database:
    python deploy_setup.py

It reads connection info from environment variables (or config.py for local dev),
creates the database, loads the schema, and seeds skills.
"""
import os
import sys

import pymysql


def get_connection_params():
    """Build PyMySQL connection params from env vars (cloud) or config.py (local)."""
    host = os.environ.get("SE_DB_HOST", "")
    port = int(os.environ.get("SE_DB_PORT", "3306"))
    user = os.environ.get("SE_DB_USER", "")
    password = os.environ.get("SE_DB_PASSWORD", "")
    db_name = os.environ.get("SE_DB_NAME", "skill_exchange")

    # Fallback to config.py for local dev
    if not host or not user:
        try:
            import config
            host = host or config.MYSQL_HOST
            user = user or config.MYSQL_USER
            password = password or config.MYSQL_PASSWORD
            db_name = db_name or config.MYSQL_DB
        except ImportError:
            pass

    params = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "charset": "utf8mb4",
        "autocommit": True,
    }

    # SSL for TiDB Cloud / managed MySQL
    ssl_ca = os.environ.get("SE_DB_SSL_CA", "")
    if ssl_ca:
        if ssl_ca.lower() in ("1", "true"):
            ssl_ca = "/etc/ssl/certs/ca-certificates.crt"
        if os.path.isfile(ssl_ca):
            params["ssl"] = {"ca": ssl_ca}
            params["ssl_verify_cert"] = True
            params["ssl_verify_identity"] = True
        else:
            params["ssl"] = {"ca": None}
            params["ssl_disabled"] = False

    return params, db_name


def split_statements(sql_text):
    """Split a .sql file into individual statements, skipping comment lines."""
    statements, buf = [], []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buf).strip())
            buf = []
    if buf:
        statements.append("\n".join(buf).strip())
    return [s for s in statements if s]


def run_file(conn, path, label, db_name=None):
    """Execute all statements from a SQL file."""
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()

    # If we're connecting without a database, use the database name from env
    # for statements that reference USE or CREATE DATABASE
    statements = split_statements(sql)
    ok, failed = 0, 0
    for stmt in statements:
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
            ok += 1
        except pymysql.MySQLError as exc:
            failed += 1
            print(f"  ! statement failed:\n    {stmt[:120]}...\n    {exc}")
    print(f"  {label}: {ok}/{len(statements)} statements executed")
    return failed == 0


def main():
    params, db_name = get_connection_params()

    if not params["host"] or not params["user"]:
        print("ERROR: No database connection info found.")
        print("Set SE_DB_HOST, SE_DB_USER, SE_DB_PASSWORD as environment variables.")
        sys.exit(1)

    print(f"Connecting to MySQL at {params['host']}:{params['port']} as {params['user']} ...")

    # Connect without selecting a database (schema.sql creates it)
    try:
        conn = pymysql.connect(**params)
    except pymysql.MySQLError as exc:
        print(f"Could not connect to MySQL: {exc}")
        sys.exit(1)

    try:
        schema_ok = run_file(conn, "schema.sql", "schema.sql")
        seed_ok = run_file(conn, "seed_skills.sql", "seed_skills.sql")
        if schema_ok and seed_ok:
            print(f"\nDone! Database '{db_name}' is ready for deployment.")
        else:
            print("\nSome statements failed — check the errors above.")
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
