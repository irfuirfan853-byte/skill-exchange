"""Remove the demo accounts so the app is clean for real users.

Run:  venv\\Scripts\\python clear_demo.py

Deletes demo1@ and demo2@ and everything they created
(requests, exchanges, messages, calls, certificates, uploads).
Real user data is never touched.
"""
import os
import sys

for _enc in ("utf-8", "utf-8-sig"):
    try:
        sys.stdout.reconfigure(encoding=_enc)
        break
    except (AttributeError, ValueError):
        continue

import db

DEMO_EMAILS = ("demo1@skillexchange.com", "demo2@skillexchange.com")


def _try_remove(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


rows = db.query(
    "SELECT id, full_name FROM users WHERE email IN (%s, %s)", DEMO_EMAILS
)
if not rows:
    print("No demo accounts found — nothing to do.")
    raise SystemExit(0)

ids = [r["id"] for r in rows]
placeholders = ", ".join(["%s"] * len(ids))

# Remove uploaded files owned by the demo users (best-effort)
for row in db.query(
    "SELECT avatar_path FROM users WHERE id IN ({})".format(placeholders), ids
):
    _try_remove(os.path.join("uploads", row["avatar_path"]))
for row in db.query(
    """SELECT m.file_path FROM exchange_messages m
       JOIN exchanges e ON e.id = m.exchange_id
       WHERE e.initiator_id IN ({0}) OR e.partner_id IN ({0})""".format(placeholders),
    ids + ids,
):
    _try_remove(os.path.join("uploads", row["file_path"]))
for row in db.query(
    "SELECT file_path FROM certificates WHERE user_id IN ({})".format(placeholders), ids
):
    _try_remove(os.path.join("uploads", row["file_path"]))

# Cascades delete the demo users' requests/exchanges/messages/calls/certs
db.execute(
    "DELETE FROM users WHERE id IN ({})".format(placeholders), ids
)

print("Removed demo accounts:", ", ".join(r["full_name"] for r in rows))
print("The app now starts with a clean, real database.")
