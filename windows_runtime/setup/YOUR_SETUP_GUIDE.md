# Setup Guide — What You Need to Do

This guide walks you through everything you need to do on the web and on your Windows PC.
No technical knowledge assumed — just follow the steps in order.

---

## PART 1 — On the Web (do these first)

### Step 1 — Get a free domain name for your server (DuckDNS)

Your Windows PC needs a web address to talk to your VPS. DuckDNS gives you a free one.

1. Go to **https://www.duckdns.org** and sign in with Google or GitHub
2. Under "your current ip is …", type a name you want (e.g. `openclaw`) in the subdomain box and click **add domain**
3. Copy your **token** (the long string near the top of the page after you log in)
4. Tell me: `subdomain: <name>` and `token: <your-duckdns-token>` — I'll handle the rest on the server

---

### Step 2 — Set up Gmail access for the bot

The bot reads a Gmail account (`teche2014@gmail.com`) for trade signals. You need to give it permission via Google's developer console.

1. Go to **https://console.cloud.google.com** and sign in with the Google account that owns `teche2014@gmail.com`
2. Click the project dropdown at the top → **New Project** → name it anything (e.g. `openclaw`) → **Create**
3. In the search bar at the top, search for **"Gmail API"** → click it → click **Enable**
4. In the left sidebar, click **APIs & Services** → **Credentials**
5. Click **+ Create Credentials** → **OAuth client ID**
   - If prompted to configure the consent screen first: click **Configure consent screen** → choose **External** → fill in app name (anything) → save and continue through all steps
6. Back at Create Credentials → OAuth client ID → choose **Desktop app** → name it anything → click **Create**
7. Click the **download icon** (⬇) next to the credential you just created — this downloads a JSON file
8. Rename that file to exactly: `credentials.json`
9. Copy `credentials.json` to this folder on your Windows PC:
   ```
   <wherever you cloned the repo>\windows_runtime\setup\
   ```
10. Open a command prompt in that folder and run:
    ```
    python windows_runtime\setup\bootstrap_gmail.py
    ```
    A browser window will open — sign in as `teche2014@gmail.com` and click Allow.
    This creates a file called `token.json` in the same folder.
11. Upload `token.json` to your VPS by running this in command prompt (replace `<your-vps-ip>` with your server's IP):
    ```
    scp windows_runtime\setup\token.json root@<your-vps-ip>:/root/.openclaw/gmail/token.json
    ```

---

## PART 2 — On Your Windows PC

### Step 3 — Install Python (if you haven't already)

1. Go to **https://www.python.org/downloads** and download Python **3.11** or **3.12** (not 3.13)
2. Run the installer — **check the box "Add Python to PATH"** before clicking Install
3. Open a command prompt and verify it works:
   ```
   python --version
   ```
   Should show `Python 3.11.x` or `3.12.x`

---

### Step 4 — Install required Python packages

Open a command prompt and run these two commands:

```
pip install pywinauto playwright google-auth-oauthlib requests
```

```
python -m playwright install chromium
```

---

### Step 5 — Clone the repo (if you haven't already)

In command prompt, navigate to where you want the files, then run:

```
git clone https://github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot.git
cd openclaw--StockTicker-Signals-Discord-Bot
```

---

### Step 6 — Get your security passwords from the server

The Windows PC needs two secret passwords (called "bearer tokens") to talk to the server. These were generated during server setup.

On the VPS, run:
```bash
grep INGEST_BEARER /root/.openclaw/.env
```

You'll see two lines like:
```
INGEST_BEARER_TOKEN_R1=abc123...
INGEST_BEARER_TOKEN_R7=def456...
```

Now create two files on your Windows PC inside the repo folder:

- Create file `windows_runtime\ingest_client\.bearer.R1.local`
  — paste the R1 token value (just the part after the `=`) as the file contents, no extra spaces

- Create file `windows_runtime\ingest_client\.bearer.R7.local`
  — paste the R7 token value as the file contents

> **Note:** Files starting with `.` can be hidden in Windows Explorer — use Notepad or a code editor to create them.

---

### Step 7 — Set the server address

Create a Windows environment variable so the app knows where your server is:

1. Open the Start menu → search **"environment variables"** → click **"Edit the system environment variables"**
2. Click **Environment Variables** → under "User variables" click **New**
3. Variable name: `INGEST_URL`
4. Variable value: `https://<your-subdomain>.duckdns.org:8443/ingest`
   (replace `<your-subdomain>` with what you picked in Step 1)
5. Click OK

> **Note:** Do this AFTER I finish the server-side DuckDNS/certificate setup (I'll let you know when it's ready).

---

### Step 8 — Install the Discord background watcher

This installs a background program that watches your Discord app and sends signals to the server automatically.

1. Right-click the Windows Start button → click **Windows PowerShell (Admin)** or **Terminal (Admin)**
2. Navigate to the repo folder:
   ```
   cd <path-to-repo>\windows_runtime\R7_DISCORD_DAEMON
   ```
3. Run the installer script:
   ```
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
4. It will ask you to enter your R7 password (the token from Step 6) — paste it in
5. The script sets everything up: the background watcher will start automatically every time you log in to Windows

> **Important:** Discord must be running and logged in for the watcher to work. The watcher only reads messages that are visible on screen — it needs Discord open.

---

### Step 9 — Set up the Claude Desktop web-browsing routine

This adds an automated task to Claude Desktop that browses Reddit, SeekingAlpha, and Benzinga for trade signals.

1. Open Claude Desktop
2. Go to **Settings** (gear icon) → find **Routines** or **Scheduled Tasks**
3. Add a new routine
4. Open the file `windows_runtime\R1_AUTHED_WEB\PROMPT.md` in any text editor (Notepad works)
5. Copy the entire contents and paste it as the routine's instructions
6. Set it to run on a schedule (every 30–60 minutes during market hours is recommended)
7. Save

---

### Step 10 — Verify everything is working

After completing all steps above and after I confirm the server certificate is set up (Step 1 / DuckDNS), test the connection:

```
python -c "
import sys, os
sys.path.insert(0, 'windows_runtime')
os.environ.setdefault('INGEST_URL', 'https://<your-subdomain>.duckdns.org:8443/ingest')
from ingest_client import submit
result = submit('R1', 'desktop_auth', 'test', 'connection test')
print('SUCCESS' if result else 'FAILED — check INGEST_URL and bearer token')
"
```

---

## Summary checklist

```
WEB
[ ] Step 1 — DuckDNS: register subdomain, give me the token
[ ] Step 2 — Gmail: download credentials.json, run bootstrap script, upload token.json to server

WINDOWS
[ ] Step 3 — Python 3.11 or 3.12 installed
[ ] Step 4 — Python packages installed (pywinauto, playwright, etc.)
[ ] Step 5 — Repo cloned
[ ] Step 6 — Bearer token files created (.bearer.R1.local and .bearer.R7.local)
[ ] Step 7 — INGEST_URL environment variable set (after server cert is ready)
[ ] Step 8 — Discord watcher installed via install.ps1
[ ] Step 9 — Claude Desktop routine added from PROMPT.md
[ ] Step 10 — Connection test passes
```

---

## What I handle on the server (you don't need to do these)

- Setting up the SSL certificate once you give me the DuckDNS token
- Extracting the security pin from the certificate and putting it in the right place
- Restarting the server engine after cert setup
- Enabling GitHub branch protection

---

*Questions? Just ask — reference the step number.*
