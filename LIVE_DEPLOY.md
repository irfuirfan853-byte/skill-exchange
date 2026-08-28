# 🚀 Deploy Skill Exchange Live — Free, Step by Step

This guide gets your app live on the internet in **~15 minutes**, totally free.

**What you'll use:**
| Service | What it does | Free tier |
|---------|-------------|-----------|
| **GitHub** | Hosts your code | Unlimited public repos |
| **Render** | Runs your Flask app | 750 hours/month |
| **TiDB Cloud** | MySQL-compatible database | 5 GB storage |

No credit card required for any of these.

---

## Step 1: Push your code to GitHub

### 1a. Create a GitHub account (if you don't have one)
Go to [github.com](https://github.com) and sign up (free).

### 1b. Install Git (if you don't have it)
Download from [git-scm.com](https://git-scm.com/download/win) and install with default settings.

### 1c. Create a new repository
1. Go to [github.com/new](https://github.com/new)
2. Name it `skill-exchange`
3. Keep it **Public** (or Private — both work)
4. Do NOT check "Add a README" (you already have files)
5. Click **Create repository**

### 1d. Push your code
Open **PowerShell** in your project folder and run these one at a time:

```powershell
cd C:\Users\acer\Desktop\skill-exchange

# Initialize git
git init
git add .
git commit -m "Initial commit - Skill Exchange app"

# Connect to your GitHub repo (replace YOUR_USERNAME with your actual GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/skill-exchange.git
git branch -M main
git push -u origin main
```

> **Tip:** If Git asks for your GitHub username and password, use a **Personal Access Token** instead of your password. Create one at [github.com/settings/tokens](https://github.com/settings/tokens) with "repo" permission.

---

## Step 2: Create a free MySQL database on TiDB Cloud

### 2a. Sign up for TiDB Cloud
1. Go to [tidbcloud.com](https://tidbcloud.com)
2. Click **Sign Up** (free, no credit card needed)
3. Sign up with GitHub or email

### 2b. Create a Serverless cluster
1. After signing in, click **Create Cluster**
2. Choose **Serverless** (the free tier)
3. Select a region close to you (e.g., AWS Oregon or AWS Singapore)
4. Click **Create**
5. Wait ~30 seconds for it to provision

### 2c. Get your connection details
1. Click on your cluster name to open it
2. Click **Connect** in the upper right
3. Select **General** connection type
4. Click **Generate Password** (save this — you'll need it!)
5. Copy these values:
   - **Host** (looks like `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`)
   - **Port** (usually `4000`)
   - **User** (looks like `xxxxx.root`)
   - **Password** (the one you just generated)

### 2d. Allow Render to connect
1. In TiDB Cloud, go to **Networking** (left sidebar)
2. Under **IP Access List**, click **Add IP**
3. Add `0.0.0.0/0` (allows all IPs — safe for a public web app)
4. Click **Save**

> **Note:** You can restrict this later to Render's IP ranges for extra security.

### 2e. Set up the database
Still in TiDB Cloud:
1. Click **Chat2Query** (left sidebar) or go to the SQL Editor
2. Paste and run this:

```sql
CREATE DATABASE IF NOT EXISTS skill_exchange
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

---

## Step 3: Deploy to Render

### 3a. Sign up for Render
1. Go to [render.com](https://render.com)
2. Click **Get Started for Free**
3. Sign up with your **GitHub account** (easiest)

### 3b. Create a new Web Service
1. Click **New +** → **Web Service**
2. Connect your GitHub account if prompted
3. Find and select your `skill-exchange` repository
4. Click **Connect**

### 3c. Configure the service
Fill in these settings:

| Field | Value |
|-------|-------|
| **Name** | `skill-exchange` |
| **Runtime** | `Python` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `waitress-serve --host=0.0.0.0 --port=$PORT --threads=8 app:app` |
| **Plan** | `Free` |

### 3d. Add environment variables
Click **Advanced** → **Add Environment Variable** for each of these:

```
SE_DB_HOST     = gateway01.ap-southeast-1.prod.aws.tidbcloud.com  (your TiDB host)
SE_DB_PORT     = 4000
SE_DB_USER     = xxxxxx.root  (your TiDB user)
SE_DB_PASSWORD = your-tidb-password-here
SE_DB_NAME     = skill_exchange
SE_DB_SSL_CA   = 1
SE_COOKIE_SECURE = 1
SE_APP_URL     = https://skill-exchange.onrender.com  (your Render URL)
```

> **Tip:** For `SE_SECRET_KEY`, Render can generate one automatically. Or set it to a random string:
> ```
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

### 3e. Deploy
1. Click **Create Web Service**
2. Render will build and deploy your app (~2-3 minutes)
3. When it says **"Live"**, click the URL (it looks like `https://skill-exchange.onrender.com`)

---

## Step 4: Initialize the database

Your app is live but the database is empty. Run the schema setup:

### Option A: Render Shell (easiest)
1. In your Render dashboard, go to your service
2. Click **Shell** (left sidebar)
3. Run:
```bash
python deploy_setup.py
```

### Option B: From your local machine
```powershell
cd C:\Users\acer\Desktop\skill-exchange
$env:SE_DB_HOST="gateway01.ap-southeast-1.prod.aws.tidbcloud.com"
$env:SE_DB_PORT="4000"
$env:SE_DB_USER="xxxxx.root"
$env:SE_DB_PASSWORD="your-password"
$env:SE_DB_NAME="skill_exchange"
$env:SE_DB_SSL_CA="1"
venv\Scripts\python deploy_setup.py
```

---

## Step 5: Verify it works! 🎉

1. Open your Render URL in your browser
2. You should see the Skill Exchange home page
3. Click **Sign up free** and create a real account
4. Complete the onboarding wizard (add skills, write your bio)
5. The app is live — share the URL with anyone!

---

## Step 6: Custom domain (optional)

Want `skillexchange.com` instead of `skill-exchange.onrender.com`?

1. Buy a domain from [Namecheap](https://namecheap.com) or [Cloudflare](https://cloudflare.com) (~$10/year)
2. In Render dashboard → **Settings** → **Custom Domains**
3. Add your domain
4. Update your domain's DNS to point to Render (they'll give you the exact records)
5. Update `SE_APP_URL` to your new domain
6. Render auto-provisions HTTPS

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **"Database not connected"** page | Check your `SE_DB_*` env vars are correct in Render. Make sure TiDB is running and IP `0.0.0.0/0` is allowed. |
| **App works but images don't load** | Render's free tier has ephemeral storage — uploaded files disappear on redeploy. For production, use AWS S3 or Cloudinary for uploads (I can set this up if needed). |
| **App is slow on first load** | Render free tier "spins down" after 15 min of inactivity. First request takes ~30s to wake up. This is normal for free tier. |
| **"SSL required" error from TiDB** | Make sure `SE_DB_SSL_CA=1` is set. |
| **Build fails on Render** | Check the build logs. Usually it's a missing dependency — make sure `requirements.txt` is up to date. |

---

## What's included

- ✅ Sign up / Log in with password hashing
- ✅ Onboarding wizard (photo, bio, skills)
- ✅ Dashboard with learning vs teaching progress
- ✅ Search for skills and people
- ✅ Connect with other users (request/accept flow)
- ✅ Real-time chat (text, files, YouTube links)
- ✅ Voice & video calls (WebRTC)
- ✅ Certificates of completed skills
- ✅ Dark mode
- ✅ CSRF protection & login rate limiting
- ✅ Email notifications (when SMTP is configured)
- ✅ Production-ready WSGI server (waitress)

---

## Cost

| Service | Monthly cost |
|---------|-------------|
| GitHub | Free |
| Render Free Tier | $0 |
| TiDB Serverless Free Tier | $0 |
| **Total** | **$0/month** |

When you outgrow the free tier, Render starts at $7/month and TiDB has pay-as-you-go pricing.

---

## Next steps (when you're ready)

- **Custom domain** — see Step 6 above
- **Email notifications** — add your Gmail SMTP credentials as env vars
- **File uploads** — switch to AWS S3 or Cloudinary for persistent uploads
- **Analytics** — add Plausible or Umami for privacy-friendly analytics
- **PWA** — add a manifest.json so users can install it on their phone
