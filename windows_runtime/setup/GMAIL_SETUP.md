# Gmail OAuth2 Setup

This guide sets up OAuth2 credentials for the Gmail watcher (`gmail_watcher.py`) on the VPS.
The auth flow runs on Windows (where a browser is available), then the resulting token is copied to the VPS.

> **Account:** These credentials are for `teche2014@gmail.com`.

---

## Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown (top-left) → **New Project**
3. Name: `openclaw-gmail` (or anything memorable) → **Create**
4. Wait for the project to be created, then select it from the dropdown

---

## Step 2 — Enable the Gmail API

1. In the left sidebar: **APIs & Services** → **Library**
2. Search for `Gmail API`
3. Click **Gmail API** → **Enable**

---

## Step 3 — Create OAuth 2.0 Credentials

1. **APIs & Services** → **Credentials** → **+ Create Credentials** → **OAuth 2.0 Client ID**
2. If prompted to configure the OAuth consent screen:
   - User Type: **External** → **Create**
   - App name: `openclaw`
   - User support email: `teche2014@gmail.com`
   - Developer contact: `teche2014@gmail.com`
   - **Save and Continue** through all steps → **Back to Dashboard**
3. Back on Credentials → **+ Create Credentials** → **OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Name: `openclaw-desktop`
   - **Create**
4. Click **Download JSON** on the confirmation dialog
5. Rename the downloaded file to `credentials.json`

---

## Step 4 — Copy credentials.json to Windows

Copy the `credentials.json` file to the setup directory on your Windows machine:

```
windows_runtime\setup\credentials.json
```

---

## Step 5 — Run the Bootstrap Script (Windows)

Open a Command Prompt or PowerShell in the repo root, then:

```powershell
python windows_runtime\setup\bootstrap_gmail.py
```

This will:
1. Open your default browser to Google's OAuth consent page
2. Ask you to sign in as `teche2014@gmail.com` and grant access
3. Write `token.json` to `windows_runtime\setup\token.json`

---

## Step 6 — Copy token.json to the VPS

```powershell
scp windows_runtime\setup\token.json root@<your-vps>:/root/.openclaw/gmail/token.json
```

Replace `<your-vps>` with your VPS IP or DuckDNS hostname (e.g. `openclaw-vps.duckdns.org`).

---

## Step 7 — Verify on the VPS

SSH into the VPS and run:

```bash
python3 -c "import json,pathlib; d=json.loads(pathlib.Path('/root/.openclaw/gmail/token.json').read_text()); print(d.get('client_id','ok'))"
```

Expected output: your OAuth client ID (a long string ending in `.apps.googleusercontent.com`), confirming the file is present and valid JSON.

---

## Token Refresh

The `token.json` includes a refresh token. The gmail watcher auto-refreshes the access token before it expires — you should not need to redo this flow unless:
- You revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
- The `credentials.json` client secret is rotated
- The token file is deleted or corrupted

If refresh fails, re-run steps 5–6.

---

## Security Notes

- Keep `credentials.json` and `token.json` out of version control (both are in `.gitignore`)
- `token.json` on the VPS should be readable only by root: `chmod 600 /root/.openclaw/gmail/token.json`
- If you suspect credential compromise, revoke at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) and redo the flow
