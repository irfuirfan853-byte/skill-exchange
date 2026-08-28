"""One-click launcher for the Skill Exchange app.

Double-click start.bat (which runs this file with the venv Python).
It does everything needed to get the app running:

  1. Installs any missing packages (first run only).
  2. Starts MySQL automatically when XAMPP is installed, and waits for it.
  3. Creates the database + tables if they are missing (never drops existing data).
  4. Loads demo accounts only in demo mode (launch.py --demo, or SE_DEMO=1).
     A normal launch starts with a real, empty database — people sign up on the site.
  5. Starts the app on a production-ready WSGI server and opens your browser.

Keep this window open while you use the app - closing it stops the server.
To stop the server from anywhere: double-click stop.bat.
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import pymysql

import config

PID_FILE = os.path.join(".freebuff", "app.pid")
HOST = "127.0.0.1"
PORT = 5000
URL = "http://{}:{}".format(HOST, PORT)
OUR_TABLES = (
    "users", "skills", "user_skills", "exchanges", "exchange_skills",
    "exchange_messages", "calls", "certificates",
    "connection_requests", "call_signals",
)


def step(n, msg):
    print("[{}/5] {}".format(n, msg))


def connect_no_db():
    """Connect to the MySQL server without selecting a database."""
    return pymysql.connect(
        host=config.MYSQL_HOST,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        charset="utf8mb4",
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )


def mysql_up():
    try:
        conn = connect_no_db()
        conn.close()
        return True
    except pymysql.MySQLError:
        return False


def find_xampp_root():
    """Find an installed XAMPP (looks on C:, D:, E:)."""
    for drive in ("C:\\", "D:\\", "E:\\"):
        base = drive + "xampp"
        if os.path.isfile(os.path.join(base, "xampp_start.exe")):
            return base
        try:
            entries = os.listdir(drive)
        except OSError:
            continue
        for entry in entries:
            full = os.path.join(drive, entry)
            if entry.lower().startswith("xampp") and os.path.isfile(
                os.path.join(full, "xampp_start.exe")
            ):
                return full
    return None


def ensure_mysql():
    """Make sure MySQL is reachable; auto-start it via XAMPP if possible."""
    if mysql_up():
        print("      MySQL is running. [OK]")
        return True

    step(2, "MySQL is not reachable yet")
    print("      Looking for XAMPP to start it automatically ...")
    root = find_xampp_root()
    if root:
        print("      Found XAMPP at {} - starting Apache & MySQL ...".format(root))
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([os.path.join(root, "xampp_start.exe")],
                             creationflags=flags)
        except OSError as exc:
            print("      Could not auto-start XAMPP: {}".format(exc))

        deadline = time.time() + 45
        while time.time() < deadline:
            time.sleep(1.5)
            if mysql_up():
                print("      MySQL is running. [OK]")
                return True
        print("      MySQL still not up after 45 seconds.")

    print("      Could not reach MySQL. Please start it manually:")
    print("        XAMPP  -> open XAMPP Control Panel -> click Start next to MySQL")
    print("        or make sure your MySQL service is running")
    print("      Then double-click start.bat again.")
    return False


def schema_ready():
    """True when all 8 of our tables exist in the configured database."""
    try:
        conn = connect_no_db()
        try:
            with conn.cursor() as cur:
                placeholders = ", ".join(["%s"] * len(OUR_TABLES))
                cur.execute(
                    "SELECT COUNT(*) AS c FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name IN ({})".format(placeholders),
                    (config.MYSQL_DB,) + OUR_TABLES,
                )
                return cur.fetchone()["c"] == len(OUR_TABLES)
        finally:
            conn.close()
    except pymysql.MySQLError:
        return False


def run_script(script):
    print("      Running {} ...".format(script))
    rc = subprocess.call([sys.executable, script])
    if rc != 0:
        print("      That step failed - paste the output above into the chat.")
    return rc == 0


def ensure_schema():
    step(3, "Checking the database ...")
    if schema_ready():
        print("      Database '{}' is ready. [OK]".format(config.MYSQL_DB))
        return True
    print("      Database or tables are missing - creating them now ...")
    # NOTE: a partial set of tables (1-7 of 8) counts as broken and triggers a
    # full rebuild via run_schema.py, which DROPs and recreates the database.
    # That's fine here - a partial state has no real data worth keeping.
    return run_script("run_schema.py")


def ensure_demo_data():
    step(4, "Checking accounts ...")
    try:
        import db
        row = db.query("SELECT COUNT(*) AS c FROM users", one=True)
        n = row["c"] if row else 0
    except pymysql.MySQLError as exc:
        print("      Could not read users: {}".format(exc))
        return True  # not fatal - the app shows its own page

    if n > 0:
        print("      Found {} user(s). [OK]".format(n))
        return True
    if not config.DEMO_MODE:
        print("      No users yet - the app starts empty. People sign up on the site.")
        print("      (To load demo accounts instead, run: venv\\Scripts\\python launch.py --demo)")
        return True
    print("      No users yet - loading demo accounts ...")
    return run_script("seed_demo.py")


def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) == 0


def start_server():
    step(5, "Starting the app ...")

    if port_in_use():
        print("      The app is already running at {}".format(URL))
        webbrowser.open(URL)
        print("      Your browser has been opened.")
        return

    os.makedirs(".freebuff", exist_ok=True)
    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))

    # Open the browser as soon as the server answers
    def open_browser_when_ready():
        for _ in range(40):
            if port_in_use():
                webbrowser.open(URL)
                return
            time.sleep(0.5)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    print("      Serving at {}   (keep this window open)".format(URL))
    if config.DEMO_MODE:
        print("      Demo login: demo1@skillexchange.com  /  demo1234")
    try:
        import app as appmod
        # Production-ready WSGI server (threaded) — safe for real use.
        # For development with auto-reload, run: venv\\Scripts\\python app.py
        from waitress import serve
        serve(appmod.app, host=HOST, port=PORT, threads=8)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def main():
    if "--demo" in sys.argv:
        config.DEMO_MODE = True
        print("Demo mode enabled.")

    print("=" * 54)
    print("   Skill Exchange - One-Click Launcher")
    print("=" * 54)

    step(1, "Checking packages ...")
    try:
        import flask  # noqa: F401
        import werkzeug  # noqa: F401
    except ImportError:
        print("      Installing required packages (first run) ...")
        rc = subprocess.call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        )
        if rc != 0:
            print("      Package install failed.")
            print("      Run: venv\\Scripts\\python -m pip install -r requirements.txt")
            return
        print("      Packages installed. [OK]")
    else:
        print("      All packages are ready. [OK]")

    if not ensure_mysql():
        return
    if not ensure_schema():
        return
    if not ensure_demo_data():
        return

    start_server()


if __name__ == "__main__":
    main()
