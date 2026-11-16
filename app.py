import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlsplit

import pymysql
from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, abort,
    jsonify, send_from_directory,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import config
import db

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set SESSION_COOKIE_SECURE=1 (env) when serving over HTTPS in production
    SESSION_COOKIE_SECURE=os.environ.get("SE_COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=config.MAX_CONTENT_LENGTH,
)

# Uploads (avatars, certificates, shared files)
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

ONLINE_WINDOW_SECONDS = 300  # a user is "online" if active within the last 5 minutes

# --- CSRF (cross-site request forgery) protection -------------------------
# Every POST must carry a token from the session. Forms get it as a hidden
# input; fetch() calls (calls/chat) send it in the X-CSRF-Token header.
def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, get_csrf_token()):
            flash("Your session expired — please try again.", "error")
            # only bounce back to a same-site page (never an external URL)
            ref = urlsplit(request.referrer or "")
            if ref.netloc in (request.host, request.host.split(":")[0]) and ref.path.startswith("/"):
                return redirect(ref.path)
            return redirect(url_for("home"))


# --- Simple login throttling (brute-force protection) ---------------------
_login_failures = {}  # ip -> [count, first_attempt_ts]


def login_throttled(ip):
    now = time.time()
    entry = _login_failures.get(ip)
    if not entry or now - entry[1] > 900:  # 15 minute window
        _login_failures[ip] = [0, now]
        return False
    return entry[0] >= 10


def record_login_failure(ip):
    entry = _login_failures.setdefault(ip, [0, time.time()])
    entry[0] += 1


def clear_login_failures(ip):
    _login_failures.pop(ip, None)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def login_required(f):
    """Redirect to /login when the visitor is not signed in."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to view that page.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def db_error_page():
    """Friendly page shown when MySQL is unreachable or not set up."""
    return render_template("db_error.html"), 500


def get_user(user_id):
    row = db.query("SELECT id, full_name, email, bio, location, avatar_path, last_seen FROM users WHERE id=%s", (user_id,), one=True)
    return row


def presence(last_seen):
    """Turn a last_seen timestamp into an online flag + human label."""
    if not last_seen:
        return {"online": False, "label": "Offline"}
    # SQLite returns a string like '2026-09-30 12:34:56' — parse it.
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.strptime(last_seen[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return {"online": False, "label": "Offline"}
    diff = datetime.now() - last_seen
    secs = diff.total_seconds()
    if secs < ONLINE_WINDOW_SECONDS:
        return {"online": True, "label": "Online now"}
    if secs < 3600:
        return {"online": False, "label": "Last seen {}m ago".format(max(1, int(secs // 60)))}
    if secs < 86400:
        return {"online": False, "label": "Last seen {}h ago".format(int(secs // 3600))}
    return {"online": False, "label": "Last seen {}d ago".format(int(secs // 86400))}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS
    )


def save_upload(file_storage, folder):
    """Save an uploaded file into uploads/<folder>/ and return its relative path."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    name = secure_filename(file_storage.filename)
    sub = os.path.join(config.UPLOAD_FOLDER, folder)
    os.makedirs(sub, exist_ok=True)
    unique = "{}_{}".format(uuid.uuid4().hex[:10], name)
    file_storage.save(os.path.join(sub, unique))
    return os.path.join(folder, unique).replace("\\", "/")


# --- Email delivery -------------------------------------------------------
# Two transports:
#   SMTP      — smtplib; works locally and on paid hosts.
#   HTTPS API — Brevo or Resend; needed on hosts that block outbound SMTP
#               (Render free web services block ports 25/465/587), so reset
#               codes still reach a member's Gmail inbox.
_last_email = {"at": None, "transport": "", "error": ""}


def email_transport():
    """Which transport is configured: 'brevo', 'resend', 'smtp' or ''."""
    if config.MAIL_API in ("brevo", "resend") and config.MAIL_API_KEY:
        return config.MAIL_API
    if config.SMTP_HOST:
        return "smtp"
    return ""


def email_status():
    """Small summary for the admin console."""
    transport = email_transport()
    return {
        "transport": transport,
        "from_address": (config.MAIL_API_FROM if transport in ("brevo", "resend")
                         else config.SMTP_FROM),
        "last_error": _last_email.get("error", ""),
        "last_at": _last_email.get("at"),
    }


def _send_smtp(to_address, subject, body_text):
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_address

    if config.SMTP_PORT == 465:  # implicit TLS
        srv = smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=15)
    else:
        srv = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
    with srv:
        if config.SMTP_USER and config.SMTP_PORT != 465:
            srv.starttls()
        if config.SMTP_USER:
            srv.login(config.SMTP_USER, config.SMTP_PASSWORD)
        srv.send_message(msg)


def _post_json(url, payload, headers):
    """POST JSON over HTTPS (stdlib only — no extra dependency)."""
    import json
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("HTTP {} — {}".format(exc.code, detail))
    except urllib.error.URLError as exc:
        raise RuntimeError("network error: {}".format(exc.reason))


def _send_mail_api(transport, to_address, subject, body_text):
    if transport == "brevo":
        _post_json(
            "https://api.brevo.com/v3/smtp/email",
            {
                "sender": {"name": config.MAIL_API_FROM_NAME,
                           "email": config.MAIL_API_FROM},
                "to": [{"email": to_address}],
                "subject": subject,
                "textContent": body_text,
            },
            {"api-key": config.MAIL_API_KEY, "accept": "application/json"},
        )
    else:  # resend
        _post_json(
            "https://api.resend.com/emails",
            {
                "from": "{} <{}>".format(config.MAIL_API_FROM_NAME, config.MAIL_API_FROM),
                "to": [to_address],
                "subject": subject,
                "text": body_text,
            },
            {"Authorization": "Bearer " + config.MAIL_API_KEY},
        )


def send_email(to_address, subject, body_text):
    """Send an email through the configured transport. Never raises."""
    transport = email_transport()
    if not transport or not to_address:
        return False
    try:
        if transport == "smtp":
            _send_smtp(to_address, subject, body_text)
        else:
            _send_mail_api(transport, to_address, subject, body_text)
        _last_email.update({"at": datetime.now(), "transport": transport, "error": ""})
        return True
    except Exception as exc:  # email must never break a request
        detail = str(exc)
        if transport == "smtp" and ("timed out" in detail.lower() or "timeout" in detail.lower()):
            detail += (" — many hosts (including Render's free plan) block outbound SMTP; "
                       "set SE_MAIL_API and SE_MAIL_API_KEY to send over HTTPS instead")
        _last_email.update({"at": datetime.now(), "transport": transport,
                            "error": detail[:400]})
        try:
            app.logger.warning("email send failed (%s): %s", transport, detail)
        except Exception:
            pass
        return False


def notify_user(user_id, subject, body):
    """Email a user (silently skipped when no SMTP or no email)."""
    try:
        row = db.query("SELECT email FROM users WHERE id=%s", (user_id,), one=True)
        if row and row["email"]:
            send_email(row["email"], subject, body)
    except pymysql.MySQLError:
        pass


# ------------------------------------------------------------------
# Emergency SOS + admin access
# ------------------------------------------------------------------
SOS_CATEGORIES = {
    "medical": "Medical emergency",
    "safety": "Personal safety",
    "harassment": "Harassment or abuse",
    "account": "Account or data security",
    "other": "Other",
}
SOS_STATUSES = ("open", "acknowledged", "resolved")


def ensure_security_schema():
    """Make sure the SOS table and the users.is_admin flag exist.

    Fresh installs get them from schema.sql / schema_sqlite.sql. This keeps
    databases created before the SOS feature working without wiping data.
    """
    try:
        if db.using_sqlite():
            db.execute(
                """CREATE TABLE IF NOT EXISTS sos_reports (
                       id              INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id         INTEGER NOT NULL,
                       category        TEXT    NOT NULL DEFAULT 'other',
                       message         TEXT    NOT NULL,
                       location        TEXT,
                       contact         TEXT,
                       status          TEXT    NOT NULL DEFAULT 'open',
                       admin_note      TEXT,
                       handled_by      INTEGER,
                       created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                       acknowledged_at TEXT,
                       resolved_at     TEXT,
                       FOREIGN KEY (user_id)    REFERENCES users(id) ON DELETE CASCADE,
                       FOREIGN KEY (handled_by) REFERENCES users(id) ON DELETE SET NULL
                   )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_sos_user ON sos_reports(user_id, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_sos_status ON sos_reports(status, created_at)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS sos_call_signals (
                       id         INTEGER PRIMARY KEY AUTOINCREMENT,
                       sos_id     INTEGER NOT NULL,
                       sender_id  INTEGER NOT NULL,
                       msg_type   TEXT    NOT NULL,
                       payload    TEXT    NOT NULL,
                       created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                       FOREIGN KEY (sos_id)    REFERENCES sos_reports(id) ON DELETE CASCADE,
                       FOREIGN KEY (sender_id) REFERENCES users(id)       ON DELETE CASCADE
                   )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_soscs_sos ON sos_call_signals(sos_id, id)")
            cols = [c.get("name") for c in db.query("PRAGMA table_info(users)")]
            if "is_admin" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        else:
            db.execute(
                """CREATE TABLE IF NOT EXISTS sos_reports (
                       id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                       user_id         INT UNSIGNED NOT NULL,
                       category        VARCHAR(40)  NOT NULL DEFAULT 'other',
                       message         TEXT         NOT NULL,
                       location        VARCHAR(160) NULL,
                       contact         VARCHAR(120) NULL,
                       status          VARCHAR(20)  NOT NULL DEFAULT 'open',
                       admin_note      VARCHAR(500) NULL,
                       handled_by      INT UNSIGNED NULL,
                       created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                       acknowledged_at DATETIME     NULL,
                       resolved_at     DATETIME     NULL,
                       KEY idx_sos_user (user_id, status),
                       KEY idx_sos_status (status, created_at),
                       CONSTRAINT fk_sos_user    FOREIGN KEY (user_id)    REFERENCES users (id) ON DELETE CASCADE,
                       CONSTRAINT fk_sos_handler FOREIGN KEY (handled_by) REFERENCES users (id) ON DELETE SET NULL
                   ) ENGINE=InnoDB"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS sos_call_signals (
                       id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                       sos_id     INT UNSIGNED NOT NULL,
                       sender_id  INT UNSIGNED NOT NULL,
                       msg_type   VARCHAR(20)  NOT NULL,
                       payload    MEDIUMTEXT   NOT NULL,
                       created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                       KEY idx_soscs_sos (sos_id, id),
                       CONSTRAINT fk_soscs_sos    FOREIGN KEY (sos_id)    REFERENCES sos_reports (id) ON DELETE CASCADE,
                       CONSTRAINT fk_soscs_sender FOREIGN KEY (sender_id) REFERENCES users (id)        ON DELETE CASCADE
                   ) ENGINE=InnoDB"""
            )
            cols = db.query(
                """SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'"""
            )
            if "is_admin" not in [c.get("name") for c in cols]:
                db.execute("ALTER TABLE users ADD COLUMN is_admin TINYINT NOT NULL DEFAULT 0")
    except pymysql.MySQLError:
        # Database not reachable or not set up yet — the friendly setup page
        # handles that case, so there is nothing to do here.
        pass


def is_admin_user(user_id):
    """Admin rights are decided on the server — never by the URL, a form field
    or the session cookie's contents.

    When SE_ADMIN_EMAILS is set it is the hard allowlist: an account is admin
    only if its email is listed, whatever its database flag says. Otherwise the
    users.is_admin flag decides.
    """
    try:
        row = db.query("SELECT email, is_admin FROM users WHERE id=%s", (user_id,), one=True)
        if not row:
            return False
        if config.ADMIN_EMAILS:
            return (row.get("email") or "").strip().lower() in config.ADMIN_EMAILS
        return bool(row.get("is_admin"))
    except pymysql.MySQLError:
        return False


def admin_required(f):
    """Like login_required, but also demands the admin flag."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to view that page.", "warning")
            return redirect(url_for("login", next=request.path))
        if not is_admin_user(session["user_id"]):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def grant_admin_if_listed(user):
    """Promote accounts named in SE_ADMIN_EMAILS at login time."""
    if not config.ADMIN_EMAILS or not user:
        return
    try:
        if (user.get("email") or "").lower() in config.ADMIN_EMAILS and not user.get("is_admin"):
            db.execute("UPDATE users SET is_admin=1 WHERE id=%s", (user["id"],))
    except pymysql.MySQLError:
        pass


def notify_admins(subject, body):
    """Email every admin address. Never raises."""
    if not config.SMTP_HOST:
        return
    for address in config.ADMIN_EMAILS:
        send_email(address, subject, body)


# Runs once at import: adds the SOS table / admin flag to older databases.
ensure_security_schema()


def get_exchange_for_user(exchange_id, user_id):
    """Fetch an exchange only if the given user is part of it."""
    row = db.query(
        """SELECT e.*, u.id AS other_id, u.full_name AS other_name,
                  u.last_seen AS other_last_seen
           FROM exchanges e
           JOIN users u ON u.id = IF(e.initiator_id = %s, e.partner_id, e.initiator_id)
           WHERE e.id = %s AND (e.initiator_id = %s OR e.partner_id = %s)""",
        (user_id, exchange_id, user_id, user_id),
        one=True,
    )
    return row


@app.before_request
def touch_last_seen():
    """Keep the online-presence timestamp fresh for signed-in users."""
    uid = session.get("user_id")
    if uid and request.endpoint != "static":
        try:
            db.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (uid,))
        except pymysql.MySQLError:
            pass


@app.context_processor
def inject_nav_counts():
    """Unread messages + pending connection requests, shown as nav badges."""
    counts = {"unread_count": 0, "pending_count": 0, "is_admin": False, "counts_open_sos": 0}
    uid = session.get("user_id")
    if uid:
        try:
            row = db.query(
                """SELECT COUNT(*) AS c FROM exchange_messages m
                   JOIN exchanges e ON e.id = m.exchange_id
                   WHERE (e.initiator_id = %s OR e.partner_id = %s)
                     AND m.sender_id <> %s AND m.is_read = 0""",
                (uid, uid, uid), one=True,
            )
            counts["unread_count"] = row["c"] if row else 0
            row = db.query(
                "SELECT COUNT(*) AS c FROM connection_requests WHERE to_user_id=%s AND status='pending'",
                (uid,), one=True,
            )
            counts["pending_count"] = row["c"] if row else 0
            counts["is_admin"] = is_admin_user(uid)
            if counts["is_admin"]:
                sos_row = db.query(
                    "SELECT COUNT(*) AS c FROM sos_reports WHERE status='open'", one=True
                )
                counts["counts_open_sos"] = sos_row["c"] if sos_row else 0
        except pymysql.MySQLError:
            pass
    return counts


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not full_name or not email or not password:
            error = "All fields are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."

        if not error:
            try:
                existing = db.query("SELECT id FROM users WHERE email=%s", (email,), one=True)
                if existing:
                    error = "An account with that email already exists. Try logging in."
                else:
                    user_id = db.execute(
                        "INSERT INTO users (full_name, email, password_hash) VALUES (%s, %s, %s)",
                        (full_name, email, generate_password_hash(password)),
                    )
                    session["user_id"] = user_id
                    session["full_name"] = full_name
                    session["avatar_path"] = None
                    flash(f"Welcome aboard, {full_name}! 🎉 Let's set up your profile.", "success")
                    return redirect(url_for("onboarding"))
            except pymysql.MySQLError:
                return db_error_page()

        if error:
            flash(error, "error")
            return render_template("signup.html", full_name=full_name, email=email)

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("home")
    # only allow relative paths (no open redirects — also blocks //evil.com)
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("home")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ip = request.remote_addr or "?"
        if login_throttled(ip):
            flash("Too many failed attempts. Please wait 15 minutes.", "error")
            return render_template("login.html", next_url=next_url), 429
        try:
            user = db.query("SELECT * FROM users WHERE email=%s", (email,), one=True)
            if user and check_password_hash(user["password_hash"], password):
                clear_login_failures(ip)
                grant_admin_if_listed(user)
                session["user_id"] = user["id"]
                session["full_name"] = user["full_name"]
                session["avatar_path"] = user.get("avatar_path")
                flash(f"Welcome back, {user['full_name']}! 👋", "success")
                return redirect(next_url)
            record_login_failure(ip)
            flash("Invalid email or password.", "error")
        except pymysql.MySQLError:
            return db_error_page()

    return render_template("login.html", next_url=next_url)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out. See you soon! 👋", "success")
    return redirect(url_for("home"))


# ------------------------------------------------------------------
# Forgot password — email OTP flow
# Request code -> enter 6-digit OTP -> set a new password.
# OTPs are hashed, expire in 10 minutes, max 5 wrong tries and
# max 3 codes per 15 minutes per account.
# ------------------------------------------------------------------
def _dtfmt(dt):
    """Format a datetime the way both MySQL and SQLite store it."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        try:
            user = db.query(
                "SELECT id, full_name, email FROM users WHERE email=%s", (email,), one=True
            )
        except pymysql.MySQLError:
            return db_error_page()

        if user:
            now = datetime.now()
            cutoff = _dtfmt(now - timedelta(minutes=15))
            recent = db.query(
                "SELECT COUNT(*) AS c FROM password_resets WHERE user_id=%s AND created_at > %s",
                (user["id"], cutoff), one=True,
            )
            if (recent or {}).get("c", 0) >= 3:
                flash("Too many reset codes requested. Please wait 15 minutes.", "error")
                return render_template("forgot_password.html")

            otp = "{:#06d}".format(secrets.randbelow(1000000))
            db.execute(
                """INSERT INTO password_resets (user_id, otp_hash, expires_at, created_at)
                   VALUES (%s, %s, %s, %s)""",
                (user["id"], generate_password_hash(otp),
                 _dtfmt(now + timedelta(minutes=10)), _dtfmt(now)),
            )
            sent = send_email(
                user["email"],
                "Your Skill Exchange password reset code",
                "Hi {},\n\nYour password reset code is: {}\n\n"
                "It expires in 10 minutes.\n"
                "If you didn't request this, you can safely ignore this email.\n\n"
                "— Skill Exchange".format(user["full_name"], otp),
            )
            if not sent:
                if not email_transport() and config.SHOW_RESET_CODE:
                    # Local testing only (SE_SHOW_RESET_CODE=1): show the code.
                    # Never enabled on a public site — otherwise anyone could
                    # reset any account by reading the code on screen.
                    flash(
                        "Email isn't configured on this machine — "
                        "your reset code is: {}".format(otp), "warning"
                    )
                elif not email_transport():
                    flash(
                        "We can't send emails from this server yet, so no code was sent. "
                        "Please contact the site admin.", "error"
                    )
                else:
                    flash(
                        "Couldn't send the email right now — please try again in a moment.",
                        "error",
                    )
            session["reset_user_id"] = user["id"]
            return redirect(url_for("verify_otp"))

        # Same message whether or not the account exists (no account enumeration)
        flash("If that email is registered, a reset code is on its way. Check your inbox.", "success")
        return redirect(url_for("verify_otp"))

    return render_template("forgot_password.html")


@app.route("/reset/verify", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_user_id")
    if not uid:
        flash("No password reset in progress — start again.", "warning")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        row = db.query(
            """SELECT * FROM password_resets
               WHERE user_id=%s AND used=0 ORDER BY id DESC LIMIT 1""",
            (uid,), one=True,
        )
        if not row:
            flash("No active code — request a new one.", "error")
            return redirect(url_for("forgot_password"))

        expires = row.get("expires_at")
        if isinstance(expires, str):
            try:
                expires = datetime.strptime(expires[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires = None
        if not expires or expires < datetime.now():
            flash("That code has expired — request a new one.", "error")
            return redirect(url_for("forgot_password"))
        if row.get("attempts", 0) >= 5:
            flash("Too many wrong attempts — request a new code.", "error")
            return redirect(url_for("forgot_password"))

        if code and check_password_hash(row["otp_hash"], code):
            db.execute("UPDATE password_resets SET used=1 WHERE id=%s", (row["id"],))
            session["reset_verified_id"] = uid
            session.pop("reset_user_id", None)
            return redirect(url_for("reset_password"))

        db.execute("UPDATE password_resets SET attempts=attempts+1 WHERE id=%s", (row["id"],))
        remaining = 5 - row.get("attempts", 0) - 1
        flash("Wrong code. Try again." + (
            " ({} attempt{} left)".format(remaining, "s" if remaining != 1 else "")
            if remaining <= 2 else ""), "error")

    return render_template("verify_otp.html")


@app.route("/reset/password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_verified_id")
    if not uid:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        p1 = request.form.get("password", "")
        p2 = request.form.get("confirm", "")
        if len(p1) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif p1 != p2:
            flash("Passwords do not match.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (generate_password_hash(p1), uid),
            )
            db.execute("DELETE FROM password_resets WHERE user_id=%s", (uid,))
            session.pop("reset_verified_id", None)
            flash("Password updated! Log in with your new password. 🔐", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html")


# ------------------------------------------------------------------
# Emergency SOS — visible only to the member who sent it and to admins
# ------------------------------------------------------------------
@app.route("/sos", methods=["GET", "POST"])
@login_required
def sos():
    me = session["user_id"]
    try:
        if request.method == "POST":
            category = request.form.get("category", "other")
            if category not in SOS_CATEGORIES:
                category = "other"
            message = request.form.get("message", "").strip()[:2000]
            location = request.form.get("location", "").strip()[:160] or None
            contact = request.form.get("contact", "").strip()[:120] or None

            if len(message) < 10:
                flash("Describe the emergency in a few words (at least 10 characters).", "error")
            else:
                open_report = db.query(
                    """SELECT id FROM sos_reports
                       WHERE user_id=%s AND status <> 'resolved'
                       ORDER BY id DESC LIMIT 1""",
                    (me,), one=True,
                )
                if open_report:
                    flash("You already have an SOS report open (#{}) — the admin team is on it. "
                          "Use “Mark as resolved” on that report before sending a new one."
                          .format(open_report["id"]), "warning")
                else:
                    sos_id = db.execute(
                        """INSERT INTO sos_reports
                               (user_id, category, message, location, contact, status, created_at)
                           VALUES (%s, %s, %s, %s, %s, 'open', %s)""",
                        (me, category, message, location, contact, _dtfmt(datetime.now())),
                    )
                    sender = get_user(me) or {}
                    notify_admins(
                        "🆘 SOS #{} — {}".format(sos_id, SOS_CATEGORIES[category]),
                        "A member sent an emergency SOS.\n\n"
                        "Member: {} ({})\nCategory: {}\nLocation: {}\nContact: {}\n\n{}"
                        "\n\nReview it in the admin console: {}/admin".format(
                            sender.get("full_name", "Unknown"),
                            sender.get("email", ""),
                            SOS_CATEGORIES[category],
                            location or "not given",
                            contact or "not given",
                            message,
                            config.APP_URL.rstrip("/"),
                        ),
                    )
                    flash("🆘 SOS sent to the admin team (#{}). This report is private — "
                          "only you and the admin can see it.".format(sos_id), "success")
            return redirect(url_for("sos"))

        reports = db.query(
            """SELECT * FROM sos_reports WHERE user_id=%s ORDER BY id DESC""",
            (me,),
        )
        return render_template(
            "sos.html",
            reports=reports,
            call_rooms=[{"id": r["id"], "name": "the admin team"}
                        for r in reports if r["status"] != "resolved"],
            categories=SOS_CATEGORIES,
            status_labels={"open": "Open — admin notified",
                           "acknowledged": "Acknowledged by admin",
                           "resolved": "Resolved"},
        )
    except pymysql.MySQLError:
        return db_error_page()


@app.route("/sos/<int:sos_id>/resolve", methods=["POST"])
@login_required
def sos_resolve(sos_id):
    me = session["user_id"]
    try:
        row = db.query(
            "SELECT id, status FROM sos_reports WHERE id=%s AND user_id=%s",
            (sos_id, me), one=True,
        )
        if not row:
            abort(404)  # someone else's report — never reveal that it exists
        if row["status"] != "resolved":
            db.execute(
                "UPDATE sos_reports SET status='resolved', resolved_at=%s WHERE id=%s AND user_id=%s",
                (_dtfmt(datetime.now()), sos_id, me),
            )
            flash("SOS #{} marked as resolved. Glad you're safe. 💙".format(sos_id), "success")
        else:
            flash("That SOS is already closed.", "warning")
    except pymysql.MySQLError:
        return db_error_page()
    return redirect(url_for("sos"))


# ------------------------------------------------------------------
# SOS calls — voice / video between the member and an admin.
# Only the report owner and admins may read or write a room.
# ------------------------------------------------------------------
def _sos_call_room(sos_id, user_id):
    """Return the report when this user may use its call room, else None."""
    report = db.query(
        "SELECT id, user_id, status FROM sos_reports WHERE id=%s", (sos_id,), one=True
    )
    if not report:
        return None
    if report["user_id"] != user_id and not is_admin_user(user_id):
        return None  # never leak that the report exists
    return report


@app.route("/sos/<int:sos_id>/call/signal", methods=["POST"])
@login_required
def sos_call_signal(sos_id):
    me = session["user_id"]
    try:
        report = _sos_call_room(sos_id, me)
        if not report:
            abort(404)
        if report["status"] == "resolved":
            return jsonify({"ok": False, "error": "This SOS is closed."}), 409
        msg_type = request.form.get("msg_type")
        payload = request.form.get("payload", "")
        if msg_type not in ("offer", "answer", "candidate", "bye") or not payload:
            return jsonify({"ok": False, "error": "bad payload"}), 400
        if msg_type == "offer":
            db.execute("DELETE FROM sos_call_signals WHERE sos_id=%s", (sos_id,))
        db.execute(
            """INSERT INTO sos_call_signals (sos_id, sender_id, msg_type, payload)
               VALUES (%s, %s, %s, %s)""",
            (sos_id, me, msg_type, payload[:20000]),
        )
        return jsonify({"ok": True})
    except pymysql.MySQLError:
        return jsonify({"ok": False}), 500


@app.route("/sos/<int:sos_id>/call/signals/after/<int:last_id>")
@login_required
def sos_call_poll(sos_id, last_id):
    me = session["user_id"]
    try:
        if not _sos_call_room(sos_id, me):
            abort(404)
        rows = db.query(
            """SELECT id, sender_id, msg_type, payload FROM sos_call_signals
               WHERE sos_id=%s AND id > %s ORDER BY id ASC LIMIT 200""",
            (sos_id, last_id),
        )
        for r in rows:
            r["mine"] = (r["sender_id"] == me)
        return jsonify(rows)
    except pymysql.MySQLError:
        return jsonify([]), 500


@app.route("/sos/<int:sos_id>/call/end", methods=["POST"])
@login_required
def sos_call_end(sos_id):
    me = session["user_id"]
    try:
        if not _sos_call_room(sos_id, me):
            abort(404)
        # Signaling only — dropping it keeps SDP/ICE details out of the database.
        db.execute("DELETE FROM sos_call_signals WHERE sos_id=%s", (sos_id,))
        return jsonify({"ok": True})
    except pymysql.MySQLError:
        return jsonify({"ok": False}), 500


# ------------------------------------------------------------------
# Admin console — SOS triage
# ------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_panel():
    status = request.args.get("status", "")
    if status not in SOS_STATUSES:
        status = ""
    try:
        base_sql = """SELECT s.*, u.full_name AS user_name, u.email AS user_email,
                             u.location AS user_location, h.full_name AS handler_name
                      FROM sos_reports s
                      JOIN users u ON u.id = s.user_id
                      LEFT JOIN users h ON h.id = s.handled_by"""
        order = (""" ORDER BY CASE s.status WHEN 'open' THEN 0
                                       WHEN 'acknowledged' THEN 1 ELSE 2 END,
                             s.id DESC LIMIT 200""")
        if status:
            reports = db.query(base_sql + " WHERE s.status=%s" + order, (status,))
        else:
            reports = db.query(base_sql + order)

        counts = {"open": 0, "acknowledged": 0, "resolved": 0}
        for row in db.query("SELECT status, COUNT(*) AS c FROM sos_reports GROUP BY status"):
            if row["status"] in counts:
                counts[row["status"]] = row["c"]
        stats = {
            "users": (db.query("SELECT COUNT(*) AS c FROM users", one=True) or {}).get("c", 0),
            "exchanges": (db.query("SELECT COUNT(*) AS c FROM exchanges", one=True) or {}).get("c", 0),
        }
        return render_template(
            "admin.html",
            reports=reports,
            mail=email_status(),
            call_rooms=[{"id": r["id"], "name": r["user_name"]}
                        for r in reports if r["status"] != "resolved"],
            counts=counts,
            stats=stats,
            status=status,
            categories=SOS_CATEGORIES,
            status_labels={"open": "Open", "acknowledged": "Acknowledged", "resolved": "Resolved"},
        )
    except pymysql.MySQLError:
        return db_error_page()


@app.route("/admin/email/test", methods=["POST"])
@admin_required
def admin_email_test():
    me = session["user_id"]
    target = request.form.get("to", "").strip()
    if not target:
        target = (get_user(me) or {}).get("email") or ""
    if not target:
        flash("No address to send to — add one in the field.", "error")
    elif not email_transport():
        flash(
            "No email transport configured. Set SE_SMTP_HOST (paid hosts) or "
            "SE_MAIL_API + SE_MAIL_API_KEY (HTTPS, works on Render's free plan).",
            "error",
        )
    elif send_email(
        target,
        "Skill Exchange — test email",
        "This is a test email from your Skill Exchange admin console.\n\n"
        "If you can read this, password-reset codes will reach members' inboxes.",
    ):
        flash("Test email sent to {}. Check the inbox (and the spam folder). 🎉".format(target),
              "success")
    else:
        flash("Test email failed: {}".format(_last_email.get("error") or "unknown error"),
              "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/sos/<int:sos_id>/<action>", methods=["POST"])
@admin_required
def admin_sos_action(sos_id, action):
    if action not in ("acknowledge", "resolve", "reopen"):
        abort(404)
    me = session["user_id"]
    note = request.form.get("admin_note", "").strip()[:500]
    try:
        report = db.query("SELECT id, user_id FROM sos_reports WHERE id=%s", (sos_id,), one=True)
        if not report:
            abort(404)
        now = _dtfmt(datetime.now())
        if action == "acknowledge":
            db.execute(
                """UPDATE sos_reports SET status='acknowledged', acknowledged_at=%s,
                          handled_by=%s WHERE id=%s""",
                (now, me, sos_id),
            )
            flash("SOS #{} acknowledged.".format(sos_id), "success")
        elif action == "resolve":
            db.execute(
                """UPDATE sos_reports SET status='resolved', resolved_at=%s, handled_by=%s,
                          acknowledged_at=COALESCE(acknowledged_at, %s) WHERE id=%s""",
                (now, me, now, sos_id),
            )
            flash("SOS #{} resolved.".format(sos_id), "success")
        else:
            db.execute(
                "UPDATE sos_reports SET status='open', resolved_at=NULL WHERE id=%s",
                (sos_id,),
            )
            flash("SOS #{} reopened.".format(sos_id), "warning")

        if note:
            db.execute("UPDATE sos_reports SET admin_note=%s WHERE id=%s", (note, sos_id))
        notify_user(
            report["user_id"],
            "SOS #{} update".format(sos_id),
            "The admin team {} your SOS report.{}\n\nSee it here: {}/sos".format(
                {"acknowledge": "acknowledged", "resolve": "resolved", "reopen": "reopened"}[action],
                ("\n\nNote from the admin: " + note) if note else "",
                config.APP_URL.rstrip("/"),
            ),
        )
    except pymysql.MySQLError:
        return db_error_page()
    return redirect(url_for("admin_panel"))


# ------------------------------------------------------------------
# Home + Search
# ------------------------------------------------------------------
@app.route("/")
def home():
    q = request.args.get("q", "").strip()

    skill_results = []
    people_results = []
    popular = []
    stats = {"users": 0, "exchanges": 0, "certificates": 0}

    try:
        # Stats strip
        stats["users"] = (db.query("SELECT COUNT(*) AS c FROM users", one=True) or {}).get("c", 0)
        stats["exchanges"] = (db.query("SELECT COUNT(*) AS c FROM exchanges", one=True) or {}).get("c", 0)
        stats["certificates"] = (db.query("SELECT COUNT(*) AS c FROM certificates", one=True) or {}).get("c", 0)

        # Search: skills by name/category + people by name or their skills
        if q:
            like = f"%{q}%"
            skill_results = db.query(
                """SELECT s.id, s.name, s.category, COUNT(us.user_id) AS people
                   FROM skills s
                   LEFT JOIN user_skills us ON us.skill_id = s.id
                   WHERE s.name LIKE %s OR s.category LIKE %s
                   GROUP BY s.id, s.name, s.category
                   ORDER BY people DESC, s.name
                   LIMIT 20""",
                (like, like),
            )
            people_results = db.query(
                """SELECT DISTINCT u.id, u.full_name, u.location, u.avatar_path, u.last_seen,
                          (SELECT GROUP_CONCAT(s2.name SEPARATOR ', ')
                           FROM user_skills us2 JOIN skills s2 ON s2.id = us2.skill_id
                           WHERE us2.user_id = u.id) AS skills
                   FROM users u
                   LEFT JOIN user_skills us ON us.user_id = u.id
                   LEFT JOIN skills s ON s.id = us.skill_id
                   WHERE u.full_name LIKE %s OR s.name LIKE %s
                   ORDER BY u.full_name
                   LIMIT 12""",
                (like, like),
            )
            for p in people_results:
                p["presence"] = presence(p.get("last_seen"))
        else:
            popular = db.query(
                """SELECT s.id, s.name, s.category, COUNT(us.user_id) AS people
                   FROM skills s
                   LEFT JOIN user_skills us ON us.skill_id = s.id
                   GROUP BY s.id, s.name, s.category
                   ORDER BY people DESC, s.name
                   LIMIT 12"""
            )
    except pymysql.MySQLError:
        # Database not ready yet — show the friendly setup page
        return db_error_page()

    return render_template(
        "home.html",
        q=q,
        skill_results=skill_results,
        people_results=people_results,
        popular=popular,
        stats=stats,
    )


# ------------------------------------------------------------------
# Dashboard — learning vs teaching progress
# ------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    me = session["user_id"]
    try:
        user = get_user(me)
        if not user:
            session.clear()
            return redirect(url_for("login"))

        # Skills I am LEARNING (I am the learner)
        learning = db.query(
            """SELECT es.id, es.skill_id, es.progress_percent, es.status AS leg_status,
                      es.completed_at, s.name AS skill_name, s.category,
                      t.full_name AS teacher_name, e.learning_period_weeks,
                      e.status AS exchange_status
               FROM exchange_skills es
               JOIN skills s ON s.id = es.skill_id
               JOIN users t ON t.id = es.teacher_id
               JOIN exchanges e ON e.id = es.exchange_id
               WHERE es.learner_id = %s
               ORDER BY es.progress_percent DESC""",
            (me,),
        )

        # Skills I am TEACHING (I am the teacher)
        teaching = db.query(
            """SELECT es.id, es.skill_id, es.progress_percent, es.status AS leg_status,
                      es.completed_at, s.name AS skill_name, s.category,
                      l.full_name AS learner_name, e.learning_period_weeks,
                      e.status AS exchange_status
               FROM exchange_skills es
               JOIN skills s ON s.id = es.skill_id
               JOIN users l ON l.id = es.learner_id
               JOIN exchanges e ON e.id = es.exchange_id
               WHERE es.teacher_id = %s
               ORDER BY es.progress_percent DESC""",
            (me,),
        )

        # My known skills (from profile) so the dashboard shows what I can teach
        known_skills = db.query(
            """SELECT s.name, us.proficiency, us.years_experience
               FROM user_skills us JOIN skills s ON s.id = us.skill_id
               WHERE us.user_id = %s AND us.can_teach = 1
               ORDER BY s.name""",
            (me,),
        )

        certificates = db.query(
            """SELECT c.cert_code, c.issued_at, c.file_path, s.name AS skill_name
               FROM certificates c JOIN skills s ON s.id = c.skill_id
               WHERE c.user_id = %s ORDER BY c.issued_at DESC""",
            (me,),
        )

        completeness, todo = profile_completeness(user)
        active_learning = [r for r in learning if r["leg_status"] == "active"]
        active_teaching = [r for r in teaching if r["leg_status"] == "active"]
        learning_pct = _avg_progress(active_learning)
        teaching_pct = _avg_progress(active_teaching)
        return render_template(
            "dashboard.html",
            user=user,
            learning=learning,
            teaching=teaching,
            learning_pct=learning_pct,
            teaching_pct=teaching_pct,
            learning_active=len(active_learning),
            teaching_active=len(active_teaching),
            known_skills=known_skills,
            certificates=certificates,
            completeness=completeness,
            todo=todo,
        )
    except pymysql.MySQLError:
        return db_error_page()


def _avg_progress(rows):
    if not rows:
        return 0
    return round(sum(r["progress_percent"] for r in rows) / len(rows))


def add_skill_to_user(user_id, skill_name, proficiency="intermediate", can_teach=True, years=0):
    """Get-or-create a skill and attach it to the user. Returns True if added."""
    skill = db.query("SELECT id FROM skills WHERE name=%s", (skill_name,), one=True)
    if not skill:
        skill_id = db.execute(
            "INSERT INTO skills (name, category) VALUES (%s, %s)",
            (skill_name, "Other"),
        )
    else:
        skill_id = skill["id"]
    exists = db.query(
        "SELECT id FROM user_skills WHERE user_id=%s AND skill_id=%s",
        (user_id, skill_id), one=True,
    )
    if exists:
        return False
    db.execute(
        """INSERT INTO user_skills (user_id, skill_id, proficiency, years_experience, can_teach)
           VALUES (%s, %s, %s, %s, %s)""",
        (user_id, skill_id, proficiency, years, 1 if can_teach else 0),
    )
    return True


def profile_completeness(user):
    """Score 0-100 how complete a user's public profile is."""
    parts = [
        (bool(user.get("avatar_path")), "Add a profile photo"),
        (bool(user.get("bio")), "Write a short about me"),
        (bool(user.get("location")), "Add your location"),
    ]
    score = sum(20 for ok, _ in parts if ok)
    try:
        teach = db.query("SELECT COUNT(*) AS c FROM user_skills WHERE user_id=%s AND can_teach=1", (user["id"],), one=True)["c"]
        learn = db.query("SELECT COUNT(*) AS c FROM user_skills WHERE user_id=%s AND can_teach=0", (user["id"],), one=True)["c"]
        if teach:
            score += 20
        else:
            parts.append((False, "List at least one skill you can teach"))
        if learn:
            score += 20
        else:
            parts.append((False, "List a skill you want to learn"))
    except pymysql.MySQLError:
        pass
    return score, [label for ok, label in parts if not ok]


# ------------------------------------------------------------------
# Onboarding — a short wizard new members finish after signing up
# ------------------------------------------------------------------
@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    me = session["user_id"]
    try:
        user = get_user(me)
        if not user:
            session.clear()
            return redirect(url_for("login"))
        if request.method == "POST":
            location = request.form.get("location", "").strip()
            bio = request.form.get("bio", "").strip()
            proficiency = request.form.get("proficiency", "intermediate")
            avatar_file = request.files.get("avatar")
            if avatar_file and avatar_file.filename:
                ext = avatar_file.filename.rsplit(".", 1)[-1].lower()
                if ext not in config.IMAGE_EXTENSIONS:
                    flash("Profile pictures must be an image file (png, jpg, …).", "error")
                    return redirect(url_for("onboarding"))
                avatar = save_upload(avatar_file, "avatars")
                if avatar:
                    db.execute("UPDATE users SET avatar_path=%s WHERE id=%s", (avatar, me))
                    session["avatar_path"] = avatar
            db.execute("UPDATE users SET bio=%s, location=%s WHERE id=%s", (bio, location, me))
            for name in [s.strip() for s in request.form.get("teach_skills", "").split(",") if s.strip()]:
                add_skill_to_user(me, name, proficiency, True)
            for name in [s.strip() for s in request.form.get("learn_skills", "").split(",") if s.strip()]:
                add_skill_to_user(me, name, "beginner", False)
            flash("Your profile is live — find someone to exchange with! 🚀", "success")
            return redirect(url_for("dashboard"))
        all_skills = db.query("SELECT name FROM skills ORDER BY name")
        return render_template(
            "onboarding.html",
            user=user,
            all_skills=[s["name"] for s in all_skills],
        )
    except pymysql.MySQLError:
        return db_error_page()


# ------------------------------------------------------------------
# Profile (public view of a user + their certificates)
# ------------------------------------------------------------------
@app.route("/profile/<int:user_id>")
def profile(user_id):
    try:
        user = get_user(user_id)
        if not user:
            abort(404)
        skills = db.query(
            """SELECT s.name, us.proficiency, us.years_experience, us.can_teach
               FROM user_skills us JOIN skills s ON s.id = us.skill_id
               WHERE us.user_id = %s ORDER BY s.name""",
            (user_id,),
        )
        certificates = db.query(
            """SELECT c.cert_code, c.issued_at, c.file_path, s.name AS skill_name
               FROM certificates c JOIN skills s ON s.id = c.skill_id
               WHERE c.user_id = %s ORDER BY c.issued_at DESC""",
            (user_id,),
        )
        # Connection state so the profile shows the right button
        connection = None  # None | 'self' | 'connected' | 'pending' | 'incoming' | 'can_connect'
        me = session.get("user_id")
        if me:
            if me == user_id:
                connection = "self"
            else:
                req = db.query(
                    """SELECT from_user_id, status FROM connection_requests
                       WHERE (from_user_id=%s AND to_user_id=%s)
                          OR (from_user_id=%s AND to_user_id=%s)
                       ORDER BY id DESC LIMIT 1""",
                    (me, user_id, user_id, me), one=True,
                )
                if req:
                    if req["status"] == "accepted":
                        connection = "connected"
                    elif req["from_user_id"] == me:
                        connection = "pending"
                    else:
                        connection = "incoming"
                else:
                    connection = "can_connect"
        return render_template(
            "profile.html",
            user=user,
            skills=skills,
            teach_skills=[s for s in skills if s["can_teach"]],
            learn_skills=[s for s in skills if not s["can_teach"]],
            certificates=certificates,
            connection=connection,
            presence=presence(user.get("last_seen")),
        )
    except pymysql.MySQLError:
        return db_error_page()


# ------------------------------------------------------------------
# Settings (edit profile + manage skills)
# ------------------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    me = session["user_id"]
    try:
        if request.method == "POST":
            action = request.form.get("action")

            if action == "profile":
                full_name = request.form.get("full_name", "").strip()
                bio = request.form.get("bio", "").strip()
                location = request.form.get("location", "").strip()
                avatar = save_upload(request.files.get("avatar"), "avatars")
                avatar_file = request.files.get("avatar")
                if avatar_file and avatar_file.filename:
                    ext = avatar_file.filename.rsplit(".", 1)[-1].lower()
                    if ext not in config.IMAGE_EXTENSIONS:
                        flash("Profile pictures must be an image file (png, jpg, …).", "error")
                        return redirect(url_for("settings"))
                if full_name:
                    db.execute(
                        "UPDATE users SET full_name=%s, bio=%s, location=%s WHERE id=%s",
                        (full_name, bio, location, me),
                    )
                    if avatar:
                        db.execute(
                            "UPDATE users SET avatar_path=%s WHERE id=%s",
                            (avatar, me),
                        )
                        session["avatar_path"] = avatar
                    session["full_name"] = full_name
                    flash("Profile updated. ✅", "success")
                else:
                    flash("Name cannot be empty.", "error")

            elif action == "add_cert":
                # Upload a certificate as proof of a completed skill
                skill_name = request.form.get("cert_skill", "").strip()
                cert_file = request.files.get("cert_file")
                if not skill_name or not cert_file or not cert_file.filename:
                    flash("Choose a skill and attach your certificate file.", "error")
                elif not allowed_file(cert_file.filename):
                    flash("That file type isn't allowed for certificates.", "error")
                else:
                    path = save_upload(cert_file, "certs")
                    skill = db.query("SELECT id FROM skills WHERE name=%s", (skill_name,), one=True)
                    if not skill:
                        skill_id = db.execute(
                            "INSERT INTO skills (name, category) VALUES (%s, %s)",
                            (skill_name, "Other"),
                        )
                    else:
                        skill_id = skill["id"]
                    db.execute(
                        """INSERT INTO certificates (user_id, skill_id, cert_code, file_path)
                           VALUES (%s, %s, %s, %s)""",
                        (me, skill_id, "SE-" + uuid.uuid4().hex[:10].upper(), path),
                    )
                    flash(f"Certificate added for {skill_name} 🏅", "success")

            elif action == "add_skill":
                skill_name = request.form.get("skill_name", "").strip()
                proficiency = request.form.get("proficiency", "intermediate")
                years = request.form.get("years_experience") or 0
                if skill_name:
                    if add_skill_to_user(me, skill_name, proficiency, True, years):
                        flash(f"Added skill: {skill_name} 🎓", "success")
                    else:
                        flash("You already have that skill.", "warning")
                else:
                    flash("Please choose a skill.", "error")

            elif action == "add_learn_skill":
                # Skills you WANT to learn — shown on your profile so teachers find you
                skill_name = request.form.get("learn_skill_name", "").strip()
                if skill_name:
                    if add_skill_to_user(me, skill_name, "beginner", False):
                        flash(f"Added to your learning list: {skill_name} 🎯", "success")
                    else:
                        flash("That skill is already on your profile.", "warning")
                else:
                    flash("Please choose a skill.", "error")

            elif action == "remove_skill":
                skill_id = request.form.get("skill_id")
                if skill_id:
                    db.execute("DELETE FROM user_skills WHERE user_id=%s AND skill_id=%s", (me, skill_id))
                    flash("Skill removed.", "success")

            return redirect(url_for("settings"))

        user = get_user(me)
        skills = db.query(
            """SELECT us.id AS us_id, us.skill_id, s.name, us.proficiency,
                      us.years_experience, us.can_teach
               FROM user_skills us JOIN skills s ON s.id = us.skill_id
               WHERE us.user_id = %s ORDER BY s.name""",
            (me,),
        )
        all_skills = db.query("SELECT name FROM skills ORDER BY name")
        return render_template(
            "settings.html",
            user=user,
            skills=skills,
            teach_skills=[s for s in skills if s["can_teach"]],
            learn_skills=[s for s in skills if not s["can_teach"]],
            all_skills=[s["name"] for s in all_skills],
        )
    except pymysql.MySQLError:
        return db_error_page()


# ------------------------------------------------------------------
# Connections (the "Connect" button on profiles)
# ------------------------------------------------------------------
@app.route("/connect/<int:user_id>", methods=["POST"])
@login_required
def connect(user_id):
    me = session["user_id"]
    if user_id == me:
        flash("You can't connect with yourself.", "error")
        return redirect(url_for("home"))
    try:
        other = get_user(user_id)
        if not other:
            abort(404)
        req = db.query(
            """SELECT id, status FROM connection_requests
               WHERE (from_user_id=%s AND to_user_id=%s)
                  OR (from_user_id=%s AND to_user_id=%s)
               ORDER BY id DESC LIMIT 1""",
            (me, user_id, user_id, me), one=True,
        )
        if req and req["status"] == "accepted":
            flash(f"You're already connected with {other['full_name']}.", "warning")
        elif req and req["status"] == "pending":
            flash("A connection request is already pending.", "warning")
        elif req and req["status"] == "declined":
            # they declined before — allow a fresh request
            db.execute(
                "UPDATE connection_requests SET status='pending', responded_at=NULL WHERE id=%s",
                (req["id"],),
            )
            notify_user(user_id, "New connection request",
                        "{} sent you a connection request on Skill Exchange.\nAccept it here: {}/requests".format(
                            session.get("full_name", "Someone"), config.APP_URL))
            flash(f"Connection request sent to {other['full_name']} ✉️", "success")
        else:
            db.execute(
                "INSERT INTO connection_requests (from_user_id, to_user_id) VALUES (%s, %s)",
                (me, user_id),
            )
            notify_user(user_id, "New connection request",
                        "{} sent you a connection request on Skill Exchange.\nAccept it here: {}/requests".format(
                            session.get("full_name", "Someone"), config.APP_URL))
            flash(f"Connection request sent to {other['full_name']} ✉️", "success")
    except pymysql.MySQLError:
        return db_error_page()
    return redirect(url_for("profile", user_id=user_id))


@app.route("/requests")
@login_required
def requests_page():
    me = session["user_id"]
    try:
        incoming = db.query(
            """SELECT cr.id, cr.status, cr.created_at,
                      u.id AS user_id, u.full_name, u.location, u.last_seen
               FROM connection_requests cr JOIN users u ON u.id = cr.from_user_id
               WHERE cr.to_user_id = %s AND cr.status = 'pending'
               ORDER BY cr.created_at DESC""",
            (me,),
        )
        outgoing = db.query(
            """SELECT cr.id, cr.status, cr.created_at,
                      u.id AS user_id, u.full_name, u.location
               FROM connection_requests cr JOIN users u ON u.id = cr.to_user_id
               WHERE cr.from_user_id = %s AND cr.status = 'pending'
               ORDER BY cr.created_at DESC""",
            (me,),
        )
        for r in incoming:
            r["presence"] = presence(r.get("last_seen"))
        return render_template("requests.html", incoming=incoming, outgoing=outgoing)
    except pymysql.MySQLError:
        return db_error_page()


@app.route("/request/<int:req_id>/<action>", methods=["POST"])
@login_required
def respond_request(req_id, action):
    me = session["user_id"]
    if action not in ("accept", "decline"):
        abort(404)
    try:
        req = db.query(
            "SELECT * FROM connection_requests WHERE id=%s AND to_user_id=%s AND status='pending'",
            (req_id, me), one=True,
        )
        if not req:
            flash("That request is no longer pending.", "warning")
            return redirect(url_for("requests_page"))

        # URL uses accept/decline, the column ENUM expects accepted/declined
        db_status = {"accept": "accepted", "decline": "declined"}[action]
        db.execute(
            "UPDATE connection_requests SET status=%s, responded_at=NOW() WHERE id=%s",
            (db_status, req_id),
        )

        if action == "accept":
            # Accepting a connection immediately creates the conversation
            # (a give-and-take exchange). The two people then set the
            # learning period + skills on the exchange page.
            db.execute(
                """INSERT INTO exchanges (initiator_id, partner_id, message,
                                          learning_period_weeks, status, start_date, end_date)
                   VALUES (%s, %s, %s, 4, 'active', CURDATE(), DATE_ADD(CURDATE(), INTERVAL 4 WEEK))""",
                (req["from_user_id"], me, "Connected on Skill Exchange — let's plan the exchange!"),
            )
            notify_user(req["from_user_id"], "Connection accepted 🎉",
                        "{} accepted your connection request. Start planning your skill exchange here: {}/conversations".format(
                            session.get("full_name", "Someone"), config.APP_URL))
            flash("Connected! Start a conversation and plan your exchange. 🤝", "success")
        else:
            flash("Request declined.", "warning")
    except pymysql.MySQLError:
        return db_error_page()
    return redirect(url_for("requests_page"))


# ------------------------------------------------------------------
# Conversations
# ------------------------------------------------------------------
@app.route("/conversations")
@login_required
def conversations():
    me = session["user_id"]
    try:
        convos = db.query(
            """SELECT e.id, e.status AS exchange_status, e.learning_period_weeks,
                      other.id AS other_id, other.full_name AS other_name,
                      other.last_seen AS other_last_seen,
                      (SELECT COUNT(*) FROM exchange_messages m2
                        WHERE m2.exchange_id = e.id AND m2.sender_id = other.id
                          AND m2.is_read = 0) AS unread,
                      (SELECT m3.content FROM exchange_messages m3
                        WHERE m3.exchange_id = e.id ORDER BY m3.id DESC LIMIT 1) AS last_content,
                      (SELECT m3.message_type FROM exchange_messages m3
                        WHERE m3.exchange_id = e.id ORDER BY m3.id DESC LIMIT 1) AS last_type,
                      (SELECT m3.created_at FROM exchange_messages m3
                        WHERE m3.exchange_id = e.id ORDER BY m3.id DESC LIMIT 1) AS last_at
               FROM exchanges e
               JOIN users other ON other.id = IF(e.initiator_id = %s, e.partner_id, e.initiator_id)
               WHERE e.initiator_id = %s OR e.partner_id = %s
               ORDER BY last_at DESC""",
            (me, me, me),
        )
        for c in convos:
            c["presence"] = presence(c.get("other_last_seen"))
        return render_template("conversations.html", convos=convos)
    except pymysql.MySQLError:
        return db_error_page()


# ------------------------------------------------------------------
# Exchange page: chat, files, YouTube, learning period, skills & calls
# ------------------------------------------------------------------
@app.route("/exchange/<int:exchange_id>", methods=["GET", "POST"])
@login_required
def exchange(exchange_id):
    me = session["user_id"]
    try:
        ex = get_exchange_for_user(exchange_id, me)
        if not ex:
            abort(404)

        if request.method == "POST":
            action = request.form.get("action")

            if action == "text":
                content = request.form.get("content", "").strip()
                if content:
                    db.execute(
                        "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content) VALUES (%s, %s, 'text', %s)",
                        (exchange_id, me, content),
                    )
                    notify_user(ex["other_id"], "New message from " + session.get("full_name", ""),
                                "You have a new message in your exchange.\nOpen it: {}/exchange/{}".format(
                                    config.APP_URL, exchange_id))

            elif action == "youtube":
                url = request.form.get("youtube_url", "").strip()
                if url.startswith(("http://", "https://")):
                    db.execute(
                        "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content, youtube_url) VALUES (%s, %s, 'youtube', %s, %s)",
                        (exchange_id, me, url, url),
                    )
                    notify_user(ex["other_id"], "New YouTube link from " + session.get("full_name", ""),
                                "A YouTube video was shared in your exchange.\nOpen it: {}/exchange/{}".format(
                                    config.APP_URL, exchange_id))
                else:
                    flash("Please paste a full YouTube link (starting with http).", "error")

            elif action == "file":
                f = request.files.get("file")
                if f and f.filename and allowed_file(f.filename):
                    path = save_upload(f, "files")
                    if path:
                        db.execute(
                            "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, file_path, file_name) VALUES (%s, %s, 'file', %s, %s)",
                            (exchange_id, me, path, secure_filename(f.filename)),
                        )
                        notify_user(ex["other_id"], "New file from " + session.get("full_name", ""),
                                    "A file was shared in your exchange.\nOpen it: {}/exchange/{}".format(
                                        config.APP_URL, exchange_id))
                    else:
                        flash("Could not save that file.", "error")
                else:
                    flash("Choose a file to share (allowed types only).", "error")

            elif action == "period":
                weeks = request.form.get("weeks")
                try:
                    weeks = max(1, min(int(weeks), 52))
                except (TypeError, ValueError):
                    weeks = 4
                db.execute(
                    "UPDATE exchanges SET learning_period_weeks=%s, start_date=CURDATE(), end_date=DATE_ADD(CURDATE(), INTERVAL %s WEEK) WHERE id=%s",
                    (weeks, weeks, exchange_id),
                )
                flash(f"Learning period set to {weeks} week(s). 📅", "success")

            elif action == "add_leg":
                # Add a skill I'm LEARNING or TEACHING in this exchange
                direction = request.form.get("direction")
                skill_name = request.form.get("skill_name", "").strip()
                if direction in ("learning", "teaching") and skill_name:
                    skill = db.query("SELECT id FROM skills WHERE name=%s", (skill_name,), one=True)
                    if not skill:
                        skill_id = db.execute(
                            "INSERT INTO skills (name, category) VALUES (%s, %s)",
                            (skill_name, "Other"),
                        )
                    else:
                        skill_id = skill["id"]
                    teacher = me if direction == "teaching" else ex["other_id"]
                    learner = me if direction == "learning" else ex["other_id"]
                    leg = db.query(
                        "SELECT id FROM exchange_skills WHERE exchange_id=%s AND skill_id=%s",
                        (exchange_id, skill_id), one=True,
                    )
                    if leg:
                        flash("That skill already has an entry in this exchange.", "warning")
                    else:
                        db.execute(
                            """INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent)
                               VALUES (%s, %s, %s, %s, 0)""",
                            (exchange_id, teacher, learner, skill_id),
                        )
                        flash(f"Added to your exchange: {skill_name} ({direction})", "success")
                else:
                    flash("Pick a skill and a direction.", "error")

            elif action == "progress":
                leg_id = request.form.get("leg_id")
                try:
                    pct = max(0, min(int(request.form.get("pct", 0)), 100))
                except (TypeError, ValueError):
                    pct = 0
                leg = db.query(
                    "SELECT * FROM exchange_skills WHERE id=%s AND exchange_id=%s",
                    (leg_id, exchange_id), one=True,
                )
                if leg and leg["teacher_id"] == me:
                    if pct >= 100:
                        db.execute(
                            "UPDATE exchange_skills SET progress_percent=100, status='completed', completed_at=NOW() WHERE id=%s",
                            (leg_id,),
                        )
                        # Auto-issue a certificate to the learner (once)
                        cert = db.query(
                            """SELECT id FROM certificates
                               WHERE user_id=%s AND skill_id=%s AND exchange_id=%s""",
                            (leg["learner_id"], leg["skill_id"], exchange_id), one=True,
                        )
                        if not cert:
                            db.execute(
                                """INSERT INTO certificates (user_id, skill_id, exchange_id, cert_code)
                                   VALUES (%s, %s, %s, %s)""",
                                (leg["learner_id"], leg["skill_id"], exchange_id,
                                 "SE-" + uuid.uuid4().hex[:10].upper()),
                            )
                            learner = db.query("SELECT full_name FROM users WHERE id=%s", (leg["learner_id"],), one=True)
                            flash("Progress updated ✅ — certificate issued to {}! 🏅".format(
                                learner["full_name"] if learner else "the learner"), "success")
                        else:
                            flash("Progress updated ✅", "success")
                    else:
                        db.execute(
                            "UPDATE exchange_skills SET progress_percent=%s, status='active', completed_at=NULL WHERE id=%s",
                            (pct, leg_id),
                        )
                        flash("Progress updated ✅", "success")
                else:
                    flash("Only the teacher can update that progress.", "error")

            return redirect(url_for("exchange", exchange_id=exchange_id))

        # ---- GET: load the conversation ----
        messages = db.query(
            """SELECT m.*, u.full_name AS sender_name
               FROM exchange_messages m JOIN users u ON u.id = m.sender_id
               WHERE m.exchange_id = %s
               ORDER BY m.id ASC""",
            (exchange_id,),
        )
        # Mark incoming messages as read
        db.execute(
            "UPDATE exchange_messages SET is_read=1 WHERE exchange_id=%s AND sender_id<>%s AND is_read=0",
            (exchange_id, me),
        )
        legs = db.query(
            """SELECT es.*, s.name AS skill_name,
                      t.full_name AS teacher_name, l.full_name AS learner_name
               FROM exchange_skills es
               JOIN skills s ON s.id = es.skill_id
               JOIN users t ON t.id = es.teacher_id
               JOIN users l ON l.id = es.learner_id
               WHERE es.exchange_id = %s ORDER BY es.id""",
            (exchange_id,),
        )
        calls = db.query(
            """SELECT c.*, u.full_name AS caller_name
               FROM calls c JOIN users u ON u.id = c.caller_id
               WHERE c.exchange_id = %s ORDER BY c.started_at DESC LIMIT 5""",
            (exchange_id,),
        )
        all_skills = db.query("SELECT name FROM skills ORDER BY name")
        return render_template(
            "exchange.html",
            ex=ex,
            me=me,
            messages=messages,
            legs=legs,
            calls=calls,
            all_skills=[s["name"] for s in all_skills],
            presence=presence(ex.get("other_last_seen")),
        )
    except pymysql.MySQLError:
        return db_error_page()


# --- Message polling (real-time-ish chat without websockets) ---
@app.route("/exchange/<int:exchange_id>/messages/after/<int:last_id>")
@login_required
def new_messages(exchange_id, last_id):
    me = session["user_id"]
    try:
        if not get_exchange_for_user(exchange_id, me):
            abort(404)
        rows = db.query(
            """SELECT m.id, m.sender_id, m.message_type, m.content, m.file_path,
                      m.file_name, m.youtube_url, m.created_at, u.full_name AS sender_name
               FROM exchange_messages m JOIN users u ON u.id = m.sender_id
               WHERE m.exchange_id = %s AND m.id > %s
               ORDER BY m.id ASC""",
            (exchange_id, last_id),
        )
        for r in rows:
            r["created_at"] = r["created_at"].strftime("%H:%M")
        return jsonify(rows)
    except pymysql.MySQLError:
        return jsonify([]), 500


# ------------------------------------------------------------------
# Voice / video calls — WebRTC signaling relayed through the database
# (both users sit on the same exchange page; polling keeps them in sync)
# ------------------------------------------------------------------
@app.route("/exchange/<int:exchange_id>/call/signal", methods=["POST"])
@login_required
def call_signal(exchange_id):
    me = session["user_id"]
    try:
        if not get_exchange_for_user(exchange_id, me):
            abort(404)
        msg_type = request.form.get("msg_type")
        payload = request.form.get("payload", "")
        if msg_type in ("offer", "answer", "candidate", "bye") and payload:
            if msg_type == "offer":
                # A new call starts clean — never replay an old call's SDP
                db.execute("DELETE FROM call_signals WHERE exchange_id=%s", (exchange_id,))
            db.execute(
                "INSERT INTO call_signals (exchange_id, sender_id, msg_type, payload) VALUES (%s, %s, %s, %s)",
                (exchange_id, me, msg_type, payload[:20000]),
            )
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "bad payload"}), 400
    except pymysql.MySQLError:
        return jsonify({"ok": False}), 500


@app.route("/exchange/<int:exchange_id>/call/signals/after/<int:last_id>")
@login_required
def call_signals_poll(exchange_id, last_id):
    me = session["user_id"]
    try:
        if not get_exchange_for_user(exchange_id, me):
            abort(404)
        rows = db.query(
            """SELECT id, sender_id, msg_type, payload
               FROM call_signals WHERE exchange_id = %s AND id > %s
               ORDER BY id ASC""",
            (exchange_id, last_id),
        )
        for r in rows:
            r["mine"] = (r["sender_id"] == me)
        return jsonify(rows)
    except pymysql.MySQLError:
        return jsonify([]), 500


@app.route("/exchange/<int:exchange_id>/call/end", methods=["POST"])
@login_required
def call_end(exchange_id):
    me = session["user_id"]
    try:
        ex = get_exchange_for_user(exchange_id, me)
        if not ex:
            abort(404)
        call_type = request.form.get("call_type", "video")
        duration = 0
        try:
            duration = max(0, int(float(request.form.get("duration", 0))))
        except (TypeError, ValueError):
            duration = 0
        other_id = ex["initiator_id"] if ex["partner_id"] == me else ex["partner_id"]
        db.execute(
            "INSERT INTO calls (exchange_id, caller_id, callee_id, call_type, ended_at, duration_seconds) VALUES (%s, %s, %s, %s, NOW(), %s)",
            (exchange_id, me, other_id, call_type, duration),
        )
        # Signaling is cleared when the next offer arrives (see call_signal),
        # so a "bye" posted by the other side survives long enough to be read.
        return jsonify({"ok": True})
    except pymysql.MySQLError:
        return jsonify({"ok": False}), 500


# ------------------------------------------------------------------
# Uploaded files (avatars, certs, shared files)
# ------------------------------------------------------------------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html", message="You don't have access to that page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ------------------------------------------------------------------
# SEO — help search engines index the site (robots.txt + sitemap.xml)
# ------------------------------------------------------------------
@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /dashboard",
        "Disallow: /settings",
        "Disallow: /conversations",
        "Disallow: /requests",
        "Disallow: /onboarding",
        "Disallow: /exchange/",
        "Disallow: /uploads/",
        "Disallow: /sos",
        "Disallow: /admin",
        "Allow: /",
        "",
        "Sitemap: {}/sitemap.xml".format(config.APP_URL.rstrip("/")),
        "",
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/sitemap.xml")
def sitemap_xml():
    base = config.APP_URL.rstrip("/")
    urls = [
        ("/", "daily", "1.0"),
        ("/signup", "monthly", "0.8"),
        ("/login", "monthly", "0.5"),
    ]
    # Public profiles are the pages people actually search for
    try:
        rows = db.query("SELECT id FROM users ORDER BY id LIMIT 500")
        for r in rows:
            urls.append(("/profile/{}".format(r["id"]), "weekly", "0.6"))
    except pymysql.MySQLError:
        pass
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, pri in urls:
        parts.append("  <url><loc>{}{}</loc><changefreq>{}</changefreq>"
                     "<priority>{}</priority></url>".format(base, path, freq, pri))
    parts.append("</urlset>")
    return "\n".join(parts), 200, {"Content-Type": "application/xml; charset=utf-8"}


if __name__ == "__main__":
    app.run(debug=True)