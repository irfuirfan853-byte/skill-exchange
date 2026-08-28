"""Seed demo data so the dashboard has realistic content to show.

Run AFTER schema.sql + seed_skills.sql:
    venv\\Scripts\\python seed_demo.py

Creates two demo accounts:
    demo1@skillexchange.com  /  demo1234   (Aria — teaches Python, UI/UX)
    demo2@skillexchange.com  /  demo1234   (Leo  — teaches Guitar, Spanish)

They have an active exchange in progress (learning + teaching both sides),
chat with text/file/YouTube messages, a pending connection request,
and Aria has a completed Spanish certificate (with an image file).
Log in as either to see the dashboard.
"""
import os
import secrets

from werkzeug.security import generate_password_hash

import config
import db

CERT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="800" height="560" viewBox="0 0 800 560">
  <rect width="800" height="560" fill="#f8fafc"/>
  <rect x="24" y="24" width="752" height="512" rx="18" fill="none" stroke="#4f46e5" stroke-width="6"/>
  <rect x="38" y="38" width="724" height="484" rx="12" fill="none" stroke="#0ea5e9" stroke-width="2"/>
  <text x="400" y="130" text-anchor="middle" font-family="Georgia, serif" font-size="30" fill="#1e293b">Skill Exchange</text>
  <text x="400" y="185" text-anchor="middle" font-family="Georgia, serif" font-size="46" font-weight="bold" fill="#4f46e5">Certificate of Completion</text>
  <text x="400" y="250" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="20" fill="#64748b">This certifies that</text>
  <text x="400" y="310" text-anchor="middle" font-family="Georgia, serif" font-size="38" font-weight="bold" fill="#0f172a">Aria Sharma</text>
  <text x="400" y="365" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="20" fill="#64748b">has successfully completed the skill</text>
  <text x="400" y="420" text-anchor="middle" font-family="Georgia, serif" font-size="32" font-weight="bold" fill="#0ea5e9">Spanish</text>
  <text x="400" y="480" text-anchor="middle" font-family="Consolas, monospace" font-size="16" fill="#94a3b8">SE-2026-DEMO-01 · issued by Skill Exchange</text>
</svg>
"""


def write_demo_cert():
    folder = os.path.join(config.UPLOAD_FOLDER, "certs")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "demo_spanish_cert.svg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(CERT_SVG)
    return "certs/demo_spanish_cert.svg"


def get_or_create_user(full_name, email):
    row = db.query("SELECT id FROM users WHERE email=%s", (email,), one=True)
    if row:
        return row["id"]
    uid = db.execute(
        "INSERT INTO users (full_name, email, password_hash, location, bio) "
        "VALUES (%s, %s, %s, %s, %s)",
        (full_name, email, generate_password_hash("demo1234"),
         "Chennai, India", "Here to exchange skills — teach what I know, learn what I don't."),
    )
    print(f"  + user {full_name} <{email}>")
    return uid


def get_skill_id(name, category="Other"):
    row = db.query("SELECT id FROM skills WHERE name=%s", (name,), one=True)
    if row:
        return row["id"]
    sid = db.execute("INSERT INTO skills (name, category) VALUES (%s, %s)", (name, category))
    print(f"  + skill {name} (new)")
    return sid


def add_user_skill(user_id, skill_name, proficiency, years, category="Other"):
    skill_id = get_skill_id(skill_name, category)
    exists = db.query(
        "SELECT id FROM user_skills WHERE user_id=%s AND skill_id=%s",
        (user_id, skill_id), one=True,
    )
    if not exists:
        db.execute(
            "INSERT INTO user_skills (user_id, skill_id, proficiency, years_experience, can_teach) "
            "VALUES (%s, %s, %s, %s, 1)",
            (user_id, skill_id, proficiency, years),
        )


def main():
    print("Seeding demo data…")
    aria = get_or_create_user("Aria Sharma", "demo1@skillexchange.com")
    leo = get_or_create_user("Leo Martins", "demo2@skillexchange.com")

    # What each person can teach
    add_user_skill(aria, "Python", "expert", 5, "Programming & Tech")
    add_user_skill(aria, "UI / UX Design", "advanced", 4, "Design & Creative")
    add_user_skill(aria, "Excel (Advanced)", "intermediate", 2, "Programming & Tech")

    add_user_skill(leo, "Guitar", "expert", 7, "Music & Arts")
    add_user_skill(leo, "Spanish", "advanced", 6, "Languages")
    add_user_skill(leo, "Singing", "intermediate", 3, "Music & Arts")

    # Active give-and-take exchange: Aria teaches Python to Leo, Leo teaches Guitar to Aria
    existing = db.query(
        "SELECT id FROM exchanges WHERE initiator_id=%s AND partner_id=%s AND status='active'",
        (aria, leo), one=True,
    )
    if existing:
        print("  exchange already exists — skipping")
    else:
        ex_id = db.execute(
            """INSERT INTO exchanges (initiator_id, partner_id, message,
                                      learning_period_weeks, status, start_date, end_date)
               VALUES (%s, %s, %s, 6, 'active', CURDATE(), DATE_ADD(CURDATE(), INTERVAL 6 WEEK))""",
            (aria, leo, "I'll teach you Python, you teach me Guitar."),
        )
        print(f"  + exchange #{ex_id} (active, 6 weeks)")

        # Aria -> Leo: Python (45% done)
        python_id = get_skill_id("Python", "Programming & Tech")
        db.execute(
            """INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent, status)
               VALUES (%s, %s, %s, %s, 45, 'active')""",
            (ex_id, aria, leo, python_id),
        )
        # Leo -> Aria: Guitar (30% done)
        guitar_id = get_skill_id("Guitar", "Music & Arts")
        db.execute(
            """INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent, status)
               VALUES (%s, %s, %s, %s, 30, 'active')""",
            (ex_id, leo, aria, guitar_id),
        )
        # A couple of chat messages
        db.execute(
            "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content) "
            "VALUES (%s, %s, 'text', %s)",
            (ex_id, aria, "Ready when you are! Let's do 30 min sessions twice a week."),
        )
        db.execute(
            "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content) "
            "VALUES (%s, %s, 'text', %s)",
            (ex_id, leo, "Sounds good. I found a great YouTube video for your first guitar lesson."),
        )
        # A shared YouTube reference + a shared file
        db.execute(
            "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, content, youtube_url) "
            "VALUES (%s, %s, 'youtube', %s, %s)",
            (ex_id, leo,
             "https://www.youtube.com/watch?v=BBz-Jyr23M4",
             "https://www.youtube.com/watch?v=BBz-Jyr23M4"),
        )
        files_dir = os.path.join(config.UPLOAD_FOLDER, "files")
        os.makedirs(files_dir, exist_ok=True)
        demo_file = os.path.join(files_dir, "demo_guitar_chords.txt")
        with open(demo_file, "w", encoding="utf-8") as fh:
            fh.write("Guitar practice plan\n\nWeek 1: Open chords A, D, E\nWeek 2: Strumming patterns\nWeek 3: Barre chords intro\nWeek 4: Your first full song\n")
        db.execute(
            "INSERT INTO exchange_messages (exchange_id, sender_id, message_type, file_path, file_name) "
            "VALUES (%s, %s, 'file', %s, %s)",
            (ex_id, leo, "files/demo_guitar_chords.txt", "guitar_chords.txt"),
        )

    # Completed exchange: Leo taught Spanish to Aria -> Aria gets a certificate
    done = db.query(
        "SELECT id FROM exchanges WHERE initiator_id=%s AND partner_id=%s AND status='completed'",
        (leo, aria), one=True,
    )
    if not done:
        ex_id = db.execute(
            """INSERT INTO exchanges (initiator_id, partner_id, message,
                                      learning_period_weeks, status, start_date, end_date)
               VALUES (%s, %s, %s, 8, 'completed',
                       DATE_SUB(CURDATE(), INTERVAL 8 WEEK), DATE_SUB(CURDATE(), INTERVAL 1 WEEK))""",
            (leo, aria, "Spanish exchange — completed 🎉"),
        )
        spanish_id = get_skill_id("Spanish", "Languages")
        db.execute(
            """INSERT INTO exchange_skills (exchange_id, teacher_id, learner_id, skill_id, progress_percent, status, completed_at)
               VALUES (%s, %s, %s, %s, 100, 'completed', DATE_SUB(CURDATE(), INTERVAL 1 WEEK))""",
            (ex_id, leo, aria, spanish_id),
        )
        cert_path = write_demo_cert()
        db.execute(
            "INSERT INTO certificates (user_id, skill_id, exchange_id, cert_code, file_path) "
            "VALUES (%s, %s, %s, %s, %s)",
            (aria, spanish_id, ex_id, "SE-2026-" + secrets.token_hex(4).upper(), cert_path),
        )
        print("  + completed exchange: Spanish -> Aria, certificate issued (with image)")

    # Pending connection request: Leo -> Aria (so the Requests page has content)
    pending = db.query(
        "SELECT id FROM connection_requests WHERE from_user_id=%s AND to_user_id=%s AND status='pending'",
        (leo, aria), one=True,
    )
    if not pending:
        db.execute(
            "INSERT INTO connection_requests (from_user_id, to_user_id) VALUES (%s, %s)",
            (leo, aria),
        )
        print("  + pending connection request: Leo -> Aria")

    # Mark both users online so presence shows correctly
    db.execute("UPDATE users SET last_seen=NOW() WHERE id IN (%s, %s)", (aria, leo))

    print("\nDone! Log in as demo1@skillexchange.com or demo2@skillexchange.com")
    print("Password for both: demo1234")


if __name__ == "__main__":
    main()
