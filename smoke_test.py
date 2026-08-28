"""Smoke test: exercises every page and key POST action via Flask's test client.

Run:  venv\\Scripts\\python smoke_test.py
Uses the live MySQL database (same as the running app). Cleans up after itself.
"""
import io
import secrets
import sys

for _enc in ("utf-8", "utf-8-sig"):
    try:
        sys.stdout.reconfigure(encoding=_enc)
        break
    except (AttributeError, ValueError):
        continue

from werkzeug.security import generate_password_hash

import app as appmod
import db

app = appmod.app
app.config["TESTING"] = True

client = app.test_client()

PASS, FAIL = 0, 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   :", label)
    else:
        FAIL += 1
        print("  FAIL :", label, extra)


def session_token():
    """The CSRF token stored in the (browser-like) test session."""
    with client.session_transaction() as s:
        return s.get("csrf_token")


def post(path, data=None, **kw):
    """POST with the session's CSRF token, like a real browser form."""
    data = dict(data or {})
    data.setdefault("csrf_token", session_token())
    return client.post(path, data=data, **kw)


print("== Public pages (establishes session) ==")
for path, label in [("/", "home"), ("/login", "login"), ("/signup", "signup")]:
    r = client.get(path)
    check(f"GET {path} ({label}) -> {r.status_code}", r.status_code == 200)

print("== CSRF protection ==")
check("session has a csrf token", bool(session_token()))
r = client.post("/login", data={"email": "demo1@skillexchange.com", "password": "demo1234"})
check("POST without CSRF token is blocked", r.status_code in (302, 400))

print("== Login ==")
r = post("/login", {"email": "demo1@skillexchange.com", "password": "demo1234"})
check("login demo1 redirects", r.status_code == 302, r.status_code)
r = post("/login", {"email": "demo1@skillexchange.com", "password": "wrong"})
check("bad password rejected (200, error flash)", r.status_code == 200)

print("== Authed pages ==")
for path, label in [
    ("/dashboard", "dashboard"),
    ("/settings", "settings"),
    ("/onboarding", "onboarding"),
    ("/conversations", "conversations"),
    ("/requests", "requests"),
    ("/profile/1", "profile/1"),
]:
    r = client.get(path)
    check(f"GET {path} ({label}) -> {r.status_code}", r.status_code == 200, r.status_code)
r = client.get("/nonexistent")
check("GET /nonexistent shows 404 page", r.status_code == 404 and "Page not found" in r.get_data(as_text=True))

# Find the demo exchange id
ex = db.query("SELECT id FROM exchanges WHERE status='active' ORDER BY id LIMIT 1", one=True)
if ex:
    eid = ex["id"]
    r = client.get(f"/exchange/{eid}")
    check(f"GET /exchange/{eid} -> {r.status_code}", r.status_code == 200)

    print("== Exchange POST actions ==")
    r = post(f"/exchange/{eid}", {"action": "text", "content": "smoke test message"})
    check("send text message", r.status_code == 302)
    msg = db.query(
        "SELECT id FROM exchange_messages WHERE exchange_id=%s AND content='smoke test message' ORDER BY id DESC LIMIT 1",
        (eid,), one=True,
    )
    check("message persisted", bool(msg))
    if msg:
        db.execute("DELETE FROM exchange_messages WHERE id=%s", (msg["id"],))

    r = post(f"/exchange/{eid}", {
        "action": "file",
        "file": (io.BytesIO(b"hello skill exchange"), "hello.txt"),
    }, content_type="multipart/form-data")
    check("upload file message", r.status_code == 302)
    fmsg = db.query(
        "SELECT id, file_path FROM exchange_messages WHERE exchange_id=%s AND message_type='file' ORDER BY id DESC LIMIT 1",
        (eid,), one=True,
    )
    check("file message persisted", bool(fmsg))
    if fmsg:
        db.execute("DELETE FROM exchange_messages WHERE id=%s", (fmsg["id"],))

    r = post(f"/exchange/{eid}", {"action": "youtube", "youtube_url": "https://youtu.be/BBz-Jyr23M4"})
    check("share youtube link", r.status_code == 302)
    r = post(f"/exchange/{eid}", {"action": "youtube", "youtube_url": "javascript:alert(1)"})
    check("bad youtube URL rejected", r.status_code == 302)
    bad = db.query(
        "SELECT id FROM exchange_messages WHERE exchange_id=%s AND youtube_url='javascript:alert(1)'", (eid,), one=True
    )
    check("javascript: URL not stored", not bad)

    r = post(f"/exchange/{eid}", {"action": "period", "weeks": "6"})
    check("set learning period", r.status_code == 302)

    r = post(f"/exchange/{eid}", {"action": "add_leg", "direction": "learning", "skill_name": "SmokeTestSkill"})
    check("add learning leg", r.status_code == 302)
    leg = db.query(
        "SELECT id FROM exchange_skills WHERE exchange_id=%s AND skill_id=(SELECT id FROM skills WHERE name='SmokeTestSkill')",
        (eid,), one=True,
    )
    check("leg persisted", bool(leg))
    if leg:
        db.execute("DELETE FROM exchange_skills WHERE id=%s", (leg["id"],))
        db.execute("DELETE FROM skills WHERE name='SmokeTestSkill'")

    r = client.get(f"/exchange/{eid}/messages/after/0")
    check("message polling JSON", r.status_code == 200 and r.is_json)

    r = client.post(f"/exchange/{eid}/call/signal", data={
        "msg_type": "offer", "payload": '{"test":1}',
        "csrf_token": session_token(),
    })
    check("call signal POST (with csrf header/field)", r.status_code == 200)
    r = client.post(f"/exchange/{eid}/call/signal", data={"msg_type": "offer", "payload": '{"x":1}'})
    check("call signal without csrf blocked", r.status_code in (302, 400))
    r = client.get(f"/exchange/{eid}/call/signals/after/0")
    check("call signal poll JSON", r.status_code == 200 and r.is_json)
    db.execute("DELETE FROM call_signals WHERE exchange_id=%s", (eid,))

    r = post(f"/exchange/{eid}/call/end", {"call_type": "video", "duration": "42"})
    check("call end recorded", r.status_code == 200)
    db.execute("DELETE FROM calls WHERE exchange_id=%s AND duration_seconds=42", (eid,))

print("== Connect flow ==")
me = db.query("SELECT id FROM users WHERE email='demo1@skillexchange.com'", one=True)["id"]
tmp_id = db.execute(
    "INSERT INTO users (full_name, email, password_hash) VALUES (%s, %s, %s)",
    ("Smoke Temp", "smoke" + secrets.token_hex(4) + "@test.local", generate_password_hash("x")),
)

try:
    r = post(f"/connect/{tmp_id}")
    check("connect POST", r.status_code == 302)
    req = db.query(
        "SELECT id, status FROM connection_requests WHERE from_user_id=%s AND to_user_id=%s",
        (me, tmp_id), one=True,
    )
    check("connection request created", bool(req) and req["status"] == "pending")
    if req:
        r = post(f"/request/{req['id']}/decline")
        check("decline request", r.status_code == 302)

    leo = db.query("SELECT id FROM users WHERE email='demo2@skillexchange.com'", one=True)["id"]
    before = db.query(
        "SELECT COUNT(*) AS c FROM connection_requests WHERE (from_user_id=%s AND to_user_id=%s) OR (from_user_id=%s AND to_user_id=%s)",
        (me, leo, leo, me), one=True,
    )["c"]
    r = post(f"/connect/{leo}")
    after = db.query(
        "SELECT COUNT(*) AS c FROM connection_requests WHERE (from_user_id=%s AND to_user_id=%s) OR (from_user_id=%s AND to_user_id=%s)",
        (me, leo, leo, me), one=True,
    )["c"]
    check("duplicate connection blocked", before == after == 1)
finally:
    db.execute("DELETE FROM users WHERE id=%s", (tmp_id,))

print("== Accept flow ==")
req = db.query(
    "SELECT id FROM connection_requests WHERE to_user_id=%s AND status='pending' ORDER BY id LIMIT 1",
    (me,), one=True,
)
if req:
    r = post(f"/request/{req['id']}/accept")
    check("accept request -> redirect", r.status_code == 302)
    new_ex = db.query(
        "SELECT id FROM exchanges WHERE message LIKE 'Connected on Skill Exchange%%' AND partner_id=%s",
        (me,), one=True,
    )
    check("exchange auto-created on accept", bool(new_ex))
    if new_ex:
        r = client.get(f"/exchange/{new_ex['id']}")
        check("new exchange page loads", r.status_code == 200)
        db.execute("DELETE FROM exchanges WHERE id=%s", (new_ex["id"],))
    db.execute("UPDATE connection_requests SET status='pending', responded_at=NULL WHERE id=%s", (req["id"],))

print("== Onboarding + learn skills ==")
# Sign up a brand-new user -> should be sent to onboarding
email = "new" + secrets.token_hex(4) + "@test.local"
r = post("/signup", {"full_name": "New User", "email": email, "password": "secret123", "confirm": "secret123"})
check("signup redirects to onboarding", r.status_code == 302 and "/onboarding" in r.headers.get("Location", ""))
new_uid = db.query("SELECT id FROM users WHERE email=%s", (email,), one=True)
check("new user persisted", bool(new_uid))
if new_uid:
    uid = new_uid["id"]
    # complete onboarding: photo-less, bio + location + teach/learn skills
    r = post("/onboarding", {
        "location": "Test City",
        "bio": "I am a test user.",
        "proficiency": "intermediate",
        "teach_skills": "TestTeaching",
        "learn_skills": "TestLearning",
    })
    check("onboarding POST -> dashboard", r.status_code == 302 and "/dashboard" in r.headers.get("Location", ""))
    teach = db.query(
        "SELECT id FROM user_skills WHERE user_id=%s AND skill_id=(SELECT id FROM skills WHERE name='TestTeaching') AND can_teach=1",
        (uid,), one=True,
    )
    learn = db.query(
        "SELECT id FROM user_skills WHERE user_id=%s AND skill_id=(SELECT id FROM skills WHERE name='TestLearning') AND can_teach=0",
        (uid,), one=True,
    )
    check("teach skill saved (can_teach=1)", bool(teach))
    check("learn skill saved (can_teach=0)", bool(learn))
    d = client.get("/dashboard")
    check("dashboard shows full completeness (100%)", "100% done" not in d.get_data(as_text=True))
    # settings learn-skill form also works
    r = post("/settings", {"action": "add_learn_skill", "learn_skill_name": "TestLearning2"})
    check("settings add_learn_skill", r.status_code == 302)
    learn2 = db.query(
        "SELECT id FROM user_skills WHERE user_id=%s AND skill_id=(SELECT id FROM skills WHERE name='TestLearning2') AND can_teach=0",
        (uid,), one=True,
    )
    check("learn skill added from settings", bool(learn2))
    # cleanup
    db.execute("DELETE FROM users WHERE id=%s", (uid,))
    db.execute("DELETE FROM skills WHERE name IN ('TestTeaching','TestLearning','TestLearning2')")

# Back to demo1 (the onboarding section logged in as a throwaway user).
# Logout clears the session (and its CSRF token), so GET /login first to
# mint a fresh token, then log in.
client.get("/logout")
client.get("/login")
r = post("/login", {"email": "demo1@skillexchange.com", "password": "demo1234"})
check("re-login as demo1", r.status_code == 302)

print("== Auto-certificate on 100% ==")
aria = db.query("SELECT id FROM users WHERE email='demo1@skillexchange.com'", one=True)["id"]
leo = db.query("SELECT id FROM users WHERE email='demo2@skillexchange.com'", one=True)["id"]
tmp_ex = db.execute(
    """INSERT INTO exchanges (initiator_id, partner_id, learning_period_weeks, status)
       VALUES (%s, %s, 2, 'active')""", (aria, leo),
)
cert_skill = db.execute("INSERT INTO skills (name, category) VALUES (%s, %s)", ("AutoCertSkill", "Other"))
db.execute(
    """INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent)
       VALUES (%s, %s, %s, %s, 10)""", (tmp_ex, aria, leo, cert_skill),
)
leg = db.query("SELECT id FROM exchange_skills WHERE exchange_id=%s", (tmp_ex,), one=True)
r = post(f"/exchange/{tmp_ex}", {"action": "progress", "leg_id": leg["id"], "pct": "100"})
check("mark 100% as teacher", r.status_code == 302)
cert = db.query(
    "SELECT id FROM certificates WHERE user_id=%s AND skill_id=%s AND exchange_id=%s",
    (leo, cert_skill, tmp_ex), one=True,
)
check("certificate auto-issued to learner", bool(cert))
r = post(f"/exchange/{tmp_ex}", {"action": "progress", "leg_id": leg["id"], "pct": "100"})
n_certs = db.query(
    "SELECT COUNT(*) AS c FROM certificates WHERE user_id=%s AND skill_id=%s AND exchange_id=%s",
    (leo, cert_skill, tmp_ex), one=True,
)["c"]
check("no duplicate certificate on repeat 100%", n_certs == 1)
# cleanup
db.execute("DELETE FROM exchanges WHERE id=%s", (tmp_ex,))
db.execute("DELETE FROM skills WHERE id=%s", (cert_skill,))

print("== Certificates ==")
r = post("/settings", {
    "action": "add_cert",
    "cert_skill": "SmokeTestCert",
    "cert_file": (io.BytesIO(b"fake-cert"), "cert.svg"),
}, content_type="multipart/form-data")
check("cert upload POST", r.status_code == 302)
cert = db.query(
    "SELECT id FROM certificates WHERE user_id=%s AND skill_id=(SELECT id FROM skills WHERE name='SmokeTestCert')",
    (me,), one=True,
)
check("cert persisted", bool(cert))
if cert:
    db.execute("DELETE FROM certificates WHERE id=%s", (cert["id"],))
    db.execute("DELETE FROM skills WHERE name='SmokeTestCert'")

r = post("/settings", {
    "action": "profile",
    "full_name": "Aria Sharma",
    "bio": "smoke bio",
    "location": "Chennai",
    "avatar": (io.BytesIO(b"fake-avatar"), "avatar.png"),
}, content_type="multipart/form-data")
check("profile update with avatar", r.status_code == 302)
r = post("/settings", {
    "action": "profile",
    "full_name": "Aria Sharma",
    "avatar": (io.BytesIO(b"fake"), "avatar.exe"),
}, content_type="multipart/form-data")
check("non-image avatar rejected", r.status_code == 302)

print("== Uploads served ==")
r = client.get("/uploads/avatars/nope.png")
check("missing upload -> 404", r.status_code == 404)

print()
print(f"RESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
