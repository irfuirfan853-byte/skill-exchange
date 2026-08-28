"""One-click SQLite database setup — no MySQL server needed.

Run once:
    python setup_sqlite.py

Creates skill_exchange.db with all tables and 120+ skills.
"""
import os
import sqlite3

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_exchange.db")


def run_sql_file(conn, path):
    """Execute all statements from a SQL file."""
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    conn.executescript(sql)
    return True


def main():
    print(f"Creating SQLite database: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        print("  Running schema_sqlite.sql ...")
        run_sql_file(conn, "schema_sqlite.sql")
        print("  schema OK")

        print("  Running seed_skills_sqlite.sql ...")
        run_sql_file(conn, "seed_skills_sqlite.sql")
        print("  skills OK")

        count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        print(f"\nDone! Database created with {count} skills.")
        print(f"Next: python seed_demo_sqlite.py  then  python app.py")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
