# 🛠️ Skill Exchange — Database Setup Guide

This guide gets your **MySQL database** ready for the Skill Exchange app.
Everything here is a **one-time setup** — after this, the app handles the rest.

---

## ⭐ Easiest: run everything with one click

If MySQL is already installed (e.g. XAMPP) and `config.py` has your MySQL
password, you can skip most of this guide:

1. **Double-click `start.bat`** in the project folder.
2. The launcher window will:
   - auto-start MySQL via XAMPP if it isn't running,
   - create the database + tables if they're missing (never deletes existing data),
   - load the demo accounts if the database is empty,
   - start the app and **open your browser** at http://127.0.0.1:5000.
3. Keep the window open while you use the app. To stop the server:
   double-click **`stop.bat`** (or just close the launcher window).

> You can double-click it again anytime — it only does what's needed and never
> wipes your data.

**About demo data:** `start.bat` starts a **real, empty** app — people sign up
on the site. If you want to try it with sample accounts first, use
**`start_demo.bat`** instead (creates `demo1@` / `demo2@` with a live exchange).
When you're done playing, run `venv\Scripts\python clear_demo.py` to remove
them and start clean.

The launcher runs the app on a **production-ready WSGI server (waitress)** —
stable and safe for real use. For development with auto-reload, run
`venv\Scripts\python app.py` instead.

---

## Step 1 — Install MySQL (skip if you already have it)

You need MySQL **8.0 or newer** running locally. Three easy options:

| Option | How | Notes |
|--------|-----|-------|
| **XAMPP** (easiest for beginners) | Download from https://www.apachefriends.org → install → open **XAMPP Control Panel** → click **Start** next to MySQL | MySQL runs on port 3306 with user `root` and **no password** by default |
| **MySQL Installer** | Download from https://dev.mysql.com/downloads/installer/ → install **MySQL Server** + **MySQL Shell** | You set a root password during install |
| **Existing install** | You already have MySQL — just find your username/password | |

> 💡 **Remember your MySQL username and password** — you'll put them in `config.py`.

## Step 2 — Update your credentials in `config.py`

Open `config.py` and make sure it matches *your* MySQL login:

```python
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "your-mysql-password"   # ← put YOUR password here (empty "" if no password)
MYSQL_DB = "skill_exchange"
SECRET_KEY = "dev-secret-key-change-this-later"
```

## Step 3 — Run the schema file

Open a **terminal** in this project folder. Easiest way — **no mysql client needed** (uses your Python + PyMySQL):

```bash
venv\Scripts\python run_schema.py
```

This runs `schema.sql` then `seed_skills.sql` for you in one step.

**Alternative — mysql CLI.** Two shell options:

**Command Prompt (cmd):**
```bash
mysql -u root -p < schema.sql
mysql -u root -p skill_exchange < seed_skills.sql
```

**PowerShell** (note: PowerShell doesn't support `<` — use `Get-Content ... |` instead):
```powershell
Get-Content schema.sql | mysql -u root -p
Get-Content seed_skills.sql | mysql -u root -p skill_exchange
```

> 💡 **Windows / XAMPP users:** if the `mysql` command isn't found, use the full path:
> ```bash
> "C:/xampp/mysql/bin/mysql.exe" -u root -p < schema.sql
> ```
> or in PowerShell: `Get-Content schema.sql | "C:/xampp/mysql/bin/mysql.exe" -u root -p`

- If your MySQL **has no password** (default XAMPP): `mysql -u root < schema.sql`
- If MySQL asks for a password, type it and press Enter.

This creates the `skill_exchange` database and **all 10 tables**:

| Table | What it stores |
|-------|----------------|
| `users` | Everyone who signs up (name, email, password, bio, avatar, online status) |
| `skills` | The global skill catalog used in every dropdown |
| `user_skills` | Which skills each user knows / can teach, with proficiency |
| `connection_requests` | The "Connect" button flow (pending / accepted / declined) |
| `exchanges` | Give-and-take pairings between two people + learning period |
| `exchange_skills` | Who teaches what to whom, and **progress %** for each side |
| `exchange_messages` | Chat messages, shared files, YouTube references |
| `calls` | History of voice / video calls inside an exchange |
| `call_signals` | WebRTC signaling relay (offer / answer / ICE) for live calls |
| `certificates` | Certificates (with uploaded image/PDF) for completed skills |

> 🔄 **Upgrading an existing install?** This version added 2 tables
> (`connection_requests`, `call_signals`) and some columns. Just double-click
> `start.bat` — it detects the missing tables and rebuilds the schema
> automatically (demo data is re-created; any real accounts you made are
> reset, so sign up again after the rebuild).

## Step 4 — Load the starter skill catalog

```bash
mysql -u root -p skill_exchange < seed_skills.sql
```

This loads **~120 popular skills** (Python, Guitar, Spanish, Digital Marketing…)
so every dropdown and search has data to show.

## Step 5 — Verify everything worked

```bash
mysql -u root -p skill_exchange
```

Then run these and check you get the same result:

```sql
SHOW TABLES;
-- Should list 8 tables

SELECT COUNT(*) FROM skills;
-- Should return 120 (or close to it)

DESCRIBE users;
-- Should show id, full_name, email, password_hash, bio, ...
```

Type `exit` to leave MySQL.

## Step 6 — Install Python packages (one time)

```bash
pip install -r requirements.txt
```

> ⚠️ If you get an error here, you may need to run `python -m pip install -r requirements.txt`
> or activate your virtual environment first: `venv\Scripts\activate` on Windows.

## Step 7 — (Optional) Load demo accounts

This creates two demo users with a live exchange in progress and a certificate,
so the dashboard shows real progress graphs right away:

```bash
venv\Scripts\python seed_demo.py
```

Demo accounts:
- `demo1@skillexchange.com` / password `demo1234` (Aria — teaches Python, UI/UX)
- `demo2@skillexchange.com` / password `demo1234` (Leo — teaches Guitar, Spanish)

Demo data includes: a live 6-week exchange with progress on both sides, chat
messages (text + a YouTube link + a shared file), a pending connection request,
and a Spanish certificate with an image on Aria's profile.

## ✨ What the app does now

- **Connect**: every profile has a **🤝 Connect** button → the other person gets a
  request → accepting it opens a conversation automatically.
- **Online status**: green dot + "Online now / Last seen …" on profiles, search
  results and conversations.
- **Conversations**: chat with **text messages, file sharing and YouTube video
  links** (auto-embedded), plus **📞 voice / 📹 video calls** (WebRTC) between
  the two people in the exchange.
- **Learning period & skills**: set the exchange duration (weeks) and add what
  each person teaches; teachers update the learner's progress %, which drives
  the dashboard graphs. Hitting 100% **auto-issues a certificate** to the learner.
- **Skills you want to learn**: add them in Settings (or onboarding) — teachers
  can see them on your profile and find you through them.
- **Onboarding**: new members get a 3-step wizard (photo, about, skills) after
  signing up, and the dashboard shows a completeness meter until their profile
  is done.
- **Certificates**: upload your certificate image/PDF (with the skill name) in
  Settings → it appears on your profile and is clickable to view.
- **Dark mode**: 🌙/☀️ button in the top bar (remembered between visits).
- **Security**: CSRF-protected forms, login rate limiting, hashed passwords,
  hardened session cookies, and an auto-generated secret key.
- **Email notifications**: optional — set `SE_SMTP_*` env vars (see DEPLOY.md)
  to get emails on new messages and connection requests.

## ✅ You're ready!

When you start the app with `python app.py`, it will connect to MySQL using
`db.py` + `config.py`. Everything is in place — you just sign up through the
web page and start exchanging skills.

---

## 🔄 Re-running the setup

- **Re-run everything from scratch** (wipes all data): just run Step 3 again — `schema.sql` drops and recreates the tables.
- **Re-load only the skills**: run Step 4 again (safe, won't duplicate).

## 🐛 Common problems

| Problem | Fix |
|---------|-----|
| `Can't connect to MySQL server` | MySQL isn't running — start it in XAMPP Control Panel |
| `Access denied for user 'root'` | Password in `config.py` doesn't match your MySQL password |
| `Unknown database 'skill_exchange'` | You skipped Step 3 — run `schema.sql` first |
| `Duplicate entry ... for key` | Already ran the seed — ignore it or run Step 4 only |
| `Port 3306 already in use` | Another MySQL instance is running — stop one of them |
| `Table ... doesn't exist` | Your DB is older than the code — re-run `run_schema.py` (or `start.bat`) once |
| `Too many failed attempts` | You were blocked after 10 wrong passwords — wait 15 minutes |

---

## 🌍 Going live

To put the app on the internet (a VPS, or Railway/Render/Fly.io), see
**`DEPLOY.md`** — it covers env vars, a managed MySQL database, nginx + HTTPS,
and a launch checklist.
