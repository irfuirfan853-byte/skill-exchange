"""Seed demo data for SQLite — two users with a live exchange.

Run: python seed_demo_sqlite.py
"""
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_exchange.db")


def main():
    print("Seeding demo data (SQLite) ...")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        # --- Users ---
        def get_or_create(name, email):
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                print(f"  User '{name}' already exists (id={row['id']})")
                return row["id"]
            uid = conn.execute(
                "INSERT INTO users (full_name, email, password_hash, bio, location) VALUES (?, ?, ?, ?, ?)",
                (name, email, generate_password_hash("demo1234"),
                 f"Passionate about learning and teaching. I believe skills are best shared.",
                 "Remote"),
            ).lastrowid
            print(f"  Created user '{name}' (id={uid})")
            return uid

        aria = get_or_create("Aria Sharma", "demo1@skillexchange.com")
        leo = get_or_create("Leo Chen", "demo2@skillexchange.com")

        # --- Skills ---
        def ensure_skill(name, cat="Other"):
            row = conn.execute("SELECT id FROM skills WHERE name=?", (name,)).fetchone()
            if row:
                return row["id"]
            return conn.execute(
                "INSERT INTO skills (name, category) VALUES (?, ?)", (name, cat)
            ).lastrowid

        python_id = ensure_skill("Python", "Programming & Tech")
        guitar_id = ensure_skill("Guitar", "Music & Arts")
        spanish_id = ensure_skill("Spanish", "Languages")
        design_id = ensure_skill("UI / UX Design", "Design & Creative")

        # --- User skills ---
        def add_user_skill(uid, sid, prof="intermediate", teach=True, years=1):
            exists = conn.execute(
                "SELECT id FROM user_skills WHERE user_id=? AND skill_id=?", (uid, sid)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO user_skills (user_id, skill_id, proficiency, can_teach, years_experience) VALUES (?, ?, ?, ?, ?)",
                    (uid, sid, prof, 1 if teach else 0, years),
                )

        add_user_skill(aria, python_id, "advanced", True, 3)
        add_user_skill(aria, guitar_id, "beginner", False, 0)
        add_user_skill(leo, guitar_id, "expert", True, 8)
        add_user_skill(leo, spanish_id, "intermediate", True, 2)
        add_user_skill(leo, python_id, "beginner", False, 0)

        # --- Live exchange: Aria teaches Python to Leo, Leo teaches Guitar to Aria ---
        existing_ex = conn.execute(
            "SELECT id FROM exchanges WHERE initiator_id=? AND partner_id=?",
            (aria, leo),
        ).fetchone()
        if not existing_ex:
            now = datetime.now()
            end = now + timedelta(weeks=4)
            ex_id = conn.execute(
                """INSERT INTO exchanges (initiator_id, partner_id, message,
                    learning_period_weeks, status, start_date, end_date)
                   VALUES (?, ?, ?, 4, 'active', ?, ?)""",
                (aria, leo, "Let's exchange skills!", now.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            ).lastrowid
            print(f"  Created exchange {ex_id}")

            # Exchange skills (legs)
            conn.execute(
                "INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent, status) VALUES (?, ?, ?, ?, 65, 'active')",
                (ex_id, aria, leo, python_id),
            )
            conn.execute(
                "INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent, status) VALUES (?, ?, ?, ?, 30, 'active')",
                (ex_id, leo, aria, guitar_id),
            )
            print("  Added exchange skills (Python 65%, Guitar 30%)")

            # Demo messages
            msgs = [
                (aria, "text", "Hey Leo! Want to trade Python for Guitar? 🎸"),
                (leo, "text", "Absolutely! I've been wanting to learn Python."),
                (aria, "text", "Great! Let's start this week. I'll teach you functions first."),
                (leo, "youtube", "https://www.youtube.com/watch?v=BasicsGuitarLesson"),
                (leo, "text", "Here's a great beginner guitar lesson to get you started!"),
                (aria, "text", "Thanks! Here's a Python basics tutorial for you."),
                (aria, "youtube", "https://www.youtube.com/watch?v=PythonForBeginners"),
            ]
            for sender, mtype, content in msgs:
                url = content if mtype == "youtube" else None
                conn.execute(
                    "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content, youtube_url) VALUES (?, ?, ?, ?, ?)",
                    (ex_id, sender, mtype, content, url),
                )
            print("  Added 7 demo messages")
        else:
            print(f"  Exchange already exists (id={existing_ex['id']})")

        # --- Pending connection request from Leo to Aria (if not exists) ---
        existing_req = conn.execute(
            "SELECT id FROM connection_requests WHERE from_user_id=? AND to_user_id=?",
            (leo, aria),
        ).fetchone()
        if not existing_req:
            conn.execute(
                "INSERT INTO connection_requests (from_user_id, to_user_id, status) VALUES (?, ?, 'pending')",
                (leo, aria),
            )
            print("  Added pending connection request (Leo -> Aria)")

        # --- Demo certificate for Aria (Python) ---
        existing_cert = conn.execute(
            "SELECT id FROM certificates WHERE user_id=? AND skill_id=?", (aria, python_id)
        ).fetchone()
        if not existing_cert:
            conn.execute(
                "INSERT INTO certificates (user_id, skill_id, cert_code) VALUES (?, ?, ?)",
                (aria, python_id, "SE-" + uuid.uuid4().hex[:10].upper()),
            )
            print("  Added demo certificate for Aria (Python)")

        conn.commit()
        print("\nDone! Demo data seeded.")
        print("Login: demo1@skillexchange.com / demo1234")
        print("       demo2@skillexchange.com / demo1234")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
