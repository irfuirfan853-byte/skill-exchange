"""Check MySQL connectivity + isolate exactly what the server rejects.

Run:  venv\\Scripts\\python check_db.py
"""
import sys

import pymysql
import config

# Windows consoles often use cp1252 which can't print some unicode symbols
for _enc in ("utf-8", "utf-8-sig"):
    try:
        sys.stdout.reconfigure(encoding=_enc)
        break
    except (AttributeError, ValueError):
        continue

print("=== 1. Connection test ===")
conn = None
try:
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        charset="utf8mb4",
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )
    print("  Connected to the MySQL server. ✓")
except pymysql.MySQLError as exc:
    code = str(exc.args[0]) if exc.args else "?"
    print("  FAILED:", exc)
    if code in ("2003", "2002", "2013"):
        print("  >>> MySQL is NOT running. Open XAMPP Control Panel -> Start MySQL.")
    elif code == "1045":
        print("  >>> Wrong username/password in config.py.")
    elif code == "1049":
        print("  >>> Database missing. Run: venv\\Scripts\\python run_schema.py")
    raise SystemExit(1)

print()
print("=== 2. Server info ===")
with conn.cursor() as cur:
    cur.execute("SELECT VERSION() AS v")
    print("  Server version:", cur.fetchone()["v"])
    cur.execute("SELECT @@sql_mode AS m")
    print("  sql_mode      :", cur.fetchone()["m"])

conn.select_db(config.MYSQL_DB)
print()
print("=== 3. Existing tables ===")
with conn.cursor() as cur:
    cur.execute("SHOW TABLES")
    tables = [list(r.values())[0] for r in cur.fetchall()]
print("  Tables found:", ", ".join(tables) if tables else "(none)")

print()
print("=== 4. CREATE TABLE isolation tests (test tables are dropped after) ===")
tests = [
    ("minimal table", "CREATE TABLE t1 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB"),
    ("+ one timestamp col",
     "CREATE TABLE t2 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB"),
    ("+ two timestamp cols (CURRENT_TIMESTAMP + ON UPDATE)",
     "CREATE TABLE t3 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP) ENGINE=InnoDB"),
    ("+ UNIQUE VARCHAR(190) (utf8mb4 = 760 bytes)",
     "CREATE TABLE t4 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, email VARCHAR(190) NOT NULL UNIQUE) ENGINE=InnoDB"),
    ("+ normal KEY on VARCHAR(100)",
     "CREATE TABLE t5 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(100) NOT NULL, KEY idx (full_name)) ENGINE=InnoDB"),
    ("+ CHECK constraint",
     "CREATE TABLE t6 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, pct TINYINT UNSIGNED NOT NULL DEFAULT 0 CHECK (pct <= 100)) ENGINE=InnoDB"),
    ("+ ENUM column",
     "CREATE TABLE t7 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, s ENUM('a','b') NOT NULL DEFAULT 'a') ENGINE=InnoDB"),
    ("+ TEXT column",
     "CREATE TABLE t8 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, bio TEXT NULL) ENGINE=InnoDB"),
    ("FULL copy of users table",
     """CREATE TABLE t9 (
        id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(100) NOT NULL,
        email VARCHAR(190) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        bio TEXT NULL,
        location VARCHAR(120) NULL,
        avatar_path VARCHAR(255) NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_users_name (full_name)
     ) ENGINE=InnoDB"""),
]
with conn.cursor() as cur:
    for label, sql in tests:
        try:
            cur.execute(sql)
            cur.execute("DROP TABLE " + sql[sql.index("CREATE TABLE ") + 13:sql.index(" (")])
            print(f"  OK    : {label}")
        except pymysql.MySQLError as exc:
            code = str(exc.args[0]) if exc.args else "?"
            msg = exc.args[1] if len(exc.args) > 1 else exc
            print(f"  FAIL  : {label}\n         [{code}] {msg}")
            try:
                cur.execute("DROP TABLE IF EXISTS t1,t2,t3,t4,t5,t6,t7,t8,t9")
            except pymysql.MySQLError:
                pass

conn.close()
print()
print("Paste this whole output into the chat.")
