# OpenClaw Windows Runtime — Operator Setup Guide

## Prerequisites

- **Git** — [git-scm.com](https://git-scm.com/download/win), any recent version
- **Python 3.11 or 3.12** — [python.org/downloads](https://www.python.org/downloads/) (see `REQUIRED_VERSIONS.md`; do NOT use 3.13)
- **Claude Desktop >= 1.0 stable** — [claude.ai/download](https://claude.ai/download)
- **Windows 10 (build 1903 / 19H1+) or Windows 11** — required for UIA3 automation

---

## 1. Clone the Repository

```powershell
git clone https://github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot.git
cd openclaw--StockTicker-Signals-Discord-Bot
```

---

## 2. Install Python Dependencies (Windows)

Open a regular Command Prompt or PowerShell (not necessarily Administrator yet):

```powershell
pip install pywinauto playwright google-auth-oauthlib
playwright install chromium
```

> **Tip:** If `pip` is not found, use `python -m pip install ...`

---

## 3. Run `install.ps1` as Administrator

Right-click PowerShell → **Run as Administrator**, then:

```powershell
cd windows_runtime\R7_DISCORD_DAEMON
.\install.ps1
```

What `install.ps1` does:
- Creates Task Scheduler entries for the R7 daemon (trigger: AtLogon, restart on failure every 1 min)
- Creates `.bearer.R7.local` in `windows_runtime/ingest_client/` — prompts you for the bearer token, then sets hidden+system attributes and locks ACLs to current user only
- Adds a Windows Defender exclusion for the workspace path (prevents AV interference with pywinauto)
- Creates a 7-minute kill task for R1 (fires at logon+7 min, terminates any R1 pythonw.exe)

---

## 4. DuckDNS (Dynamic DNS for your VPS)

1. Go to [duckdns.org](https://www.duckdns.org) → sign in → create a subdomain (e.g. `openclaw-vps`)
2. Note your **token** from the DuckDNS dashboard
3. On the VPS, create `/etc/cron.d/duckdns`:
   ```
   */5 * * * * root curl -s "https://www.duckdns.org/update?domains=openclaw-vps&token=YOUR_TOKEN&ip=" > /tmp/duckdns.log 2>&1
   ```
4. Verify: `curl "https://www.duckdns.org/update?domains=openclaw-vps&token=YOUR_TOKEN&ip="` → should return `OK`

---

## 5. Bearer Tokens

Bearer tokens authenticate the Windows clients to the VPS ingest server.

**Source:** On the VPS, the tokens are in `/root/.openclaw/.env`:
```
INGEST_BEARER_R1=<token>
INGEST_BEARER_R7=<token>
```

**Destination (Windows):** Copy them to:
- `windows_runtime/ingest_client/.bearer.R1.local`
- `windows_runtime/ingest_client/.bearer.R7.local`

Each file should contain just the raw token (no newline, no quotes).

> The `install.ps1` script will prompt you interactively for the R7 token and write + lock the file automatically. For R1, repeat the manual step or run the R1 install script.

---

## 6. Claude Desktop Routine (R1)

1. Open **Claude Desktop** → Settings (gear icon) → **Routines** tab
2. Click **Add Routine**
3. Open `windows_runtime/R1_AUTHED_WEB/PROMPT.md` in a text editor
4. Paste the full contents into the Routine body
5. Set the trigger as described in `PROMPT.md` (typically a scheduled or manual trigger)
6. Save

---

## 7. Gmail OAuth Setup

See `GMAIL_SETUP.md` for the full flow. Summary:

1. Create OAuth credentials in Google Cloud Console
2. Run `bootstrap_gmail.py` on Windows to complete the auth flow → `token.json`
3. SCP `token.json` to the VPS: `/root/.openclaw/gmail/token.json`

---

## 8. Verification

After completing setup, run this quick smoke test from the repo root on Windows:

```powershell
python -c "import sys; sys.path.insert(0, 'windows_runtime'); from ingest_client import submit; print(submit('R1', 'desktop_auth', 'check', 'test signal'))"
```

Expected output: `{"status": "ok", ...}` or similar 2xx response from the ingest server.

---

## Operations Notes

| Topic | Detail |
|-------|---------|
| **Log location** | `%APPDATA%\openclaw\r7.log` |
| **Restart daemon** | Open Task Scheduler → find `OpenClaw-R7-Daemon` → right-click → Run |
| **Stop daemon** | Task Scheduler → `OpenClaw-R7-Daemon` → right-click → End |
| **Bearer rotation** | Replace token in `.bearer.R7.local`, restart daemon via Task Scheduler |
| **View live logs** | `Get-Content "$env:APPDATA\openclaw\r7.log" -Wait` in PowerShell |

---

## Troubleshooting

### pywinauto COM errors
- Ensure you are running the daemon as the **same Windows user** that has Discord open
- Do not run as a different elevated account — pywinauto needs to share the same desktop session
- Check Event Viewer → Application for COM/DCOM errors

### UFW blocking ingest traffic
On the VPS, verify port 8443 is open:
```bash
ufw status | grep 8443
# If not present:
ufw allow 8443/tcp
```

### Discord window not found
- The daemon searches for a window matching `.*Discord.*` by title
- Ensure Discord is running and **not minimized to the system tray** (tray-only = no window)
- Check the window title: open Discord, press `Alt+Space` and note the title bar text
- If the title differs, update `title_re` in `daemon.py` → `find_discord_window()`

### Token auth failures (403)
- Verify the bearer token in `.bearer.R7.local` matches `INGEST_BEARER_R7` on the VPS exactly
- No trailing newline: `(Get-Content .bearer.R7.local).Length` should equal the token length

### Python not found in Task Scheduler
- Task Scheduler runs with a minimal PATH; use the full path to `python.exe` in the action
- Find it: `(Get-Command python).Source` in PowerShell
