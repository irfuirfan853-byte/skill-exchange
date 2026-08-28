# 🚀 Deploying Skill Exchange to the internet

The app is designed to be deployed anywhere a Python app + MySQL can run.
Everything (database, email, secret key, cookie security) is configured with
**environment variables**, so you deploy without editing code.

---

## 1. What you need

| Thing | Why |
|-------|-----|
| A server (VPS, Railway, Render, Fly.io…) | Runs the app |
| A MySQL 8 database (managed or self-hosted) | Stores everything |
| A domain + HTTPS (recommended) | Real-world security, camera/mic calls need a secure context |
| SMTP credentials (optional) | Email notifications for messages & requests |

---

## 2. Environment variables

Set these in your host's dashboard (or `.env` file if your host supports it):

```
# --- Database (required) ---
SE_DB_HOST=your-db-host
SE_DB_USER=your-db-user
SE_DB_PASSWORD=your-db-password
SE_DB_NAME=skill_exchange

# --- Security (required) ---
SE_SECRET_KEY=generate-a-long-random-string   # e.g. python -c "import secrets; print(secrets.token_hex(32))"
SE_COOKIE_SECURE=1                            # only send session cookie over HTTPS

# --- App (recommended) ---
SE_APP_URL=https://your-domain.com            # used in notification emails

# --- Email notifications (optional) ---
SE_SMTP_HOST=smtp.gmail.com
SE_SMTP_PORT=587
SE_SMTP_USER=you@gmail.com
SE_SMTP_PASSWORD=your-app-password
SE_SMTP_FROM="Skill Exchange <no-reply@your-domain.com>"
```

> Without SMTP the app works perfectly — it just skips emails.

---

## 3. Option A — PaaS (Railway / Render / Fly.io) — easiest

1. Push this folder to a GitHub repo.
2. On Railway or Render: create a **new service from the repo**.
   - Build command: `pip install -r requirements.txt`
   - Start command: `waitress-serve --host=0.0.0.0 --port=$PORT --threads=8 app:app`
   - Set the env vars from section 2 (for `$PORT`, use the host's injected port).
3. Add a **MySQL service** (Railway has one-click MySQL; Render uses a managed
   provider). Point `SE_DB_*` at it.
4. One-time: run the schema against that database. On Railway use a one-off
   shell: `python run_schema.py` — or locally:
   ```
   set SE_DB_HOST=... SE_DB_USER=... SE_DB_PASSWORD=...
   python run_schema.py
   ```
5. The app starts **empty** — real people sign up on your site. 🎉

---

## 4. Option B — VPS (Ubuntu + nginx) — full control

```bash
# 1. System packages
sudo apt update && sudo apt install -y python3-venv nginx mysql-server

# 2. App code + venv
cd /srv && git clone https://github.com/you/skill-exchange.git && cd skill-exchange
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. MySQL: create the database and a dedicated user
sudo mysql <<'SQL'
CREATE DATABASE skill_exchange CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'skillapp'@'localhost' IDENTIFIED BY 'a-strong-password';
GRANT ALL PRIVILEGES ON skill_exchange.* TO 'skillapp'@'localhost';
SQL

# 4. Load schema + skills
SE_DB_HOST=localhost SE_DB_USER=skillapp SE_DB_PASSWORD='a-strong-password' \
  venv/bin/python run_schema.py

# 5. Env file (see section 2)
sudo nano /etc/skill-exchange.env    # export SE_DB_* SE_SECRET_KEY=... SE_COOKIE_SECURE=1

# 6. Run with systemd so it survives reboots
sudo nano /etc/systemd/system/skillexchange.service
```

`/etc/systemd/system/skillexchange.service`:
```ini
[Unit]
Description=Skill Exchange web app
After=network.target mysql.service

[Service]
WorkingDirectory=/srv/skill-exchange
EnvironmentFile=/etc/skill-exchange.env
ExecStart=/srv/skill-exchange/venv/bin/waitress-serve --host=127.0.0.1 --port=8000 --threads=8 app:app
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now skillexchange
```

nginx (`/etc/nginx/sites-available/skillexchange`):
```nginx
server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 20M;               # allow certificate/file uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;            # keep long video calls alive
    }
}
```

Then add HTTPS with [Certbot](https://certbot.eff.org):
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 5. After deploying — launch checklist

- [ ] Sign up a real account and complete the onboarding wizard.
- [ ] Upload a profile photo + a certificate; view it on your profile.
- [ ] Create a second account, connect, accept, send a message — check the
      unread badge and (if SMTP is set) the email arrives.
- [ ] Make a video call between two browsers (both on the same conversation
      page). Camera/mic require **HTTPS** or localhost.
- [ ] Set `SE_COOKIE_SECURE=1` and confirm you can still log in over HTTPS.
- [ ] Backup plan: dump MySQL regularly — `mysqldump skill_exchange > backup.sql`
      (add a cron job). Uploads live in `uploads/` — back that folder up too.

## 6. Dev vs prod cheat sheet

| | Local (start.bat) | Production |
|---|---|---|
| Server | waitress on 127.0.0.1:5000 | waitress behind nginx |
| Demo data | only with `launch.py --demo` / `start_demo.bat` | none — real sign-ups |
| Secret key | auto-generated in `.secret_key` | `SE_SECRET_KEY` env var |
| Cookies | `SE_COOKIE_SECURE` off | `SE_COOKIE_SECURE=1` |
| Clean demo data | `venv\Scripts\python clear_demo.py` | — |

## 7. Handy commands

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # make a secret key
mysqldump skill_exchange > backup.sql                       # backup database
venv/bin/waitress-serve --host=0.0.0.0 --port=8000 --threads=8 app:app  # run manually
```
