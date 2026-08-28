import os
import secrets

# ------------------------------------------------------------------
# All settings can be overridden with environment variables so the app
# can be deployed anywhere (Render, Railway, a VPS) without code edits.
# Examples:
#   set SE_DB_HOST=myhost  SE_DB_USER=root  SE_DB_PASSWORD=secret
#   set SE_SECRET_KEY=random-long-string  SE_SMTP_HOST=smtp.gmail.com ...
# ------------------------------------------------------------------

MYSQL_HOST = os.environ.get("SE_DB_HOST", "localhost")
MYSQL_USER = os.environ.get("SE_DB_USER", "root")
MYSQL_PASSWORD = os.environ.get("SE_DB_PASSWORD", "irfan@123")
MYSQL_DB = os.environ.get("SE_DB_NAME", "skill_exchange")

# Session signing key. Use the SE_SECRET_KEY env var in production;
# locally we persist a random key in .secret_key so logins survive restarts.
SECRET_KEY = os.environ.get("SE_SECRET_KEY", "")
if not SECRET_KEY:
    _keyfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
    try:
        with open(_keyfile, "r", encoding="utf-8") as _fh:
            SECRET_KEY = _fh.read().strip()
        if not SECRET_KEY:
            raise IOError
    except (IOError, OSError):
        SECRET_KEY = secrets.token_hex(32)
        with open(_keyfile, "w", encoding="utf-8") as _fh:
            _fh.write(SECRET_KEY)

# Optional email notifications (new messages / connection requests).
# Leave SMTP_HOST empty to disable emails — the app works fine without them.
SMTP_HOST = os.environ.get("SE_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SE_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SE_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SE_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SE_SMTP_FROM", "Skill Exchange <no-reply@skillexchange.app>")
APP_URL = os.environ.get("SE_APP_URL", "http://127.0.0.1:5000")

# Uploaded files (certificates, shared files) live in an uploads/ folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "svg",
    "pdf", "txt", "md", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "csv", "zip", "mp3", "mp4", "mov", "wav",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

# Demo accounts are only seeded when SE_DEMO=1 (dev machines). A fresh
# production install starts empty and fills up with real sign-ups.
DEMO_MODE = os.environ.get("SE_DEMO", "0") == "1"