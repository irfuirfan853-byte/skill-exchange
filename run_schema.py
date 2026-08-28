"""One-click database setup — no mysql command-line client needed.

Run from the project folder:
    venv\\Scripts\\python run_schema.py

It reads your MySQL credentials from config.py (or SE_DB_* env vars),
then runs schema.sql (creates the database + all tables) and seed_skills.sql
(loads ~120 skills).
"""
import os
import pymysql
import config


def _statements(sql_text):
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


def run_file(conn, path, label):
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    statements = _statements(sql)
    ok, failed = 0, 0
    for stmt in statements:
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
            ok += 1
        except pymysql.MySQLError as exc:
            failed += 1
            print(f"  ! statement failed:\n    {stmt}\n    {exc}")
    print(f"  {label}: {ok}/{len(statements)} statements executed")
    return failed == 0


def main():
    host = os.environ.get("SE_DB_HOST", config.MYSQL_HOST)
    user = os.environ.get("SE_DB_USER", config.MYSQL_USER)
    password = os.environ.get("SE_DB_PASSWORD", config.MYSQL_PASSWORD)
    port = int(os.environ.get("SE_DB_PORT", "3306"))

    print(f"Connecting to MySQL at {host}:{port} as {user} ...")

    connect_params = {
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
            connect_params["ssl"] = {"ca": ssl_ca}
            connect_params["ssl_verify_cert"] = True
            connect_params["ssl_verify_identity"] = True
        else:
            connect_params["ssl"] = {"ca": None}
            connect_params["ssl_disabled"] = False

    try:
        conn = pymysql.connect(**connect_params)
    except pymysql.MySQLError as exc:
        print("Could not connect to MySQL. Is it running?")
        print("Error:", exc)
        return

    try:
        schema_ok = run_file(conn, "schema.sql", "schema.sql")
        seed_ok = run_file(conn, "seed_skills.sql", "seed_skills.sql")
        if schema_ok and seed_ok:
            print("\nDone! Database 'skill_exchange' is ready.")
            print("Next: run  venv\\Scripts\\python seed_demo.py  then  venv\\Scripts\\python app.py")
        else:
            print("\nSome statements failed — the database is NOT ready.")
            print("Paste this output into the chat so we can fix it.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
