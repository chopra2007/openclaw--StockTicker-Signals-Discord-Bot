# OpenClaw + Claude — Debian PC Setup Runbook

**Goal:** A Debian 12 (or 13) XFCE PC where Claude has full read/write/edit/Bash access and can autonomously run the openclaw bot. The original VPS at `62.238.13.149` keeps running until you've verified the Debian PC.

**You do**: 5 small copy/paste blocks (Part 1).
**Claude does**: everything else, autonomously, with checkpointing so a crash mid-run doesn't restart from zero (Part 2).

---

## PART 1 — Manual copy/paste (akash@debian-pc, terminal in XFCE)

### Step 1 — Install three prereqs

```bash
sudo apt update && sudo apt install -y curl git tmux
```

### Step 2 — Passwordless sudo for `akash`

So Claude is never blocked on a password during the autonomous run.

```bash
echo "akash ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/akash-nopasswd
sudo chmod 440 /etc/sudoers.d/akash-nopasswd
```

### Step 3 — Install Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash && source ~/.bashrc
```

### Step 4 — Permission allowlist + clone the repo

The allowlist tells Claude Code to never prompt before running Bash, reading, writing, editing, or fetching. The git clone brings this runbook to disk so Claude can read it.

```bash
mkdir -p ~/.claude && cat > ~/.claude/settings.json <<'EOF'
{
  "permissions": {
    "allow": ["Bash(*)","Read(*)","Write(*)","Edit(*)","WebFetch(*)","WebSearch(*)"]
  },
  "env": {"DISPLAY":":0","PYTHONUNBUFFERED":"1"}
}
EOF

mkdir -p ~/.openclaw
git clone https://github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot.git ~/.openclaw/workspace
```

### Step 5 — Launch Claude in tmux, sign in, paste the trigger

```bash
tmux new-session -s setup
claude
```

A browser opens for sign-in. Once you're back at the prompt, paste **this single line** as your first message:

> Read /home/akash/.openclaw/workspace/plans/openclaw-debian-setup.md and execute every phase autonomously. If you crash or are interrupted, resume from the last checkpoint in ~/.openclaw/setup-progress.json. Pause only when a choice depends on info only I have (such as a file path or password).

That's it. Claude takes over from here.

---

## PART 2 — Phases Claude executes autonomously

> **You (Claude) are running as `akash` with passwordless sudo and full file access. Read every phase below in order. After each phase succeeds, update `~/.openclaw/setup-progress.json` with `{"phase_N": "done", "ts": "<ISO8601>"}` so a crashed run resumes from the next phase. On failure: investigate root cause, fix, retry. Only stop and ask the operator when (a) you need a secret/path only they know (Phase 6 .pem path is the canonical case), or (b) you've made three honest attempts at the same fix and are still blocked.**

### Phase 0 — Resumability checkpoint

Initialize the progress file if it doesn't exist; otherwise read it and skip every phase already marked `done`.

```bash
PROG=~/.openclaw/setup-progress.json
[[ -f "$PROG" ]] || echo '{"started":"'$(date -Iseconds)'"}' > "$PROG"
cat "$PROG"
```

For each subsequent phase, after success run:

```bash
python3 - <<PY
import json, datetime, pathlib
p = pathlib.Path.home() / ".openclaw" / "setup-progress.json"
d = json.loads(p.read_text())
d["phase_${PHASE_N}"] = {"status": "done", "ts": datetime.datetime.now().isoformat()}
p.write_text(json.dumps(d, indent=2))
PY
```

(Substitute `${PHASE_N}` with the current phase number, 1–12.)

### Phase 1 — System packages

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y \
  build-essential jq unzip ca-certificates gnupg wget \
  python3 python3-pip python3-venv python3-dev \
  libssl-dev libffi-dev sqlite3 \
  xdotool scrot xclip wmctrl imagemagick x11-utils
```

Verify: `python3 --version` ≥ 3.10 AND `which xdotool scrot wmctrl xclip` resolves all four.

### Phase 2 — Docker

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker akash
```

Verify with `sg docker -c 'docker ps'` (NOT `newgrp` — that opens a subshell and doesn't return). If `sg docker -c` still says permission denied, the group hasn't propagated to your session: tell the operator they need to log out and back in (or reboot), then resume from this phase. From now on, all `docker` commands in this runbook must be wrapped: `sg docker -c '<cmd>'`.

### Phase 3 — Discord desktop app

```bash
cd /tmp
wget -O discord.deb "https://discord.com/api/download?platform=linux&format=deb"
sudo apt install -y ./discord.deb
```

Verify: `which discord` resolves.

### Phase 4 — Symlinks (BEFORE migration, so SCP destinations resolve)

The codebase hardcodes `/root/.openclaw/...` and `/root/task_system/...` in `consensus_engine/config.py`, `db.py`, `config/consensus.yaml`, etc. Symlinks make those paths transparently land in `akash`'s home.

```bash
mkdir -p /home/akash/.openclaw /home/akash/task_system/scripts /home/akash/task_system/logs
touch /home/akash/task_system/notifications.log

sudo ln -sfn /home/akash/.openclaw /root/.openclaw
sudo ln -sfn /home/akash/task_system /root/task_system
```

Verify: `ls -la /root/.openclaw && ls -la /root/task_system` → both show as symlinks pointing into `/home/akash`.

### Phase 5 — Python venv + bot deps + Playwright Chromium

```bash
python3 -m venv /home/akash/.openclaw/venv
source /home/akash/.openclaw/venv/bin/activate
pip install --upgrade pip
pip install -r /home/akash/.openclaw/workspace/requirements.txt
playwright install chromium
sudo $(which playwright) install-deps chromium
deactivate
```

(`playwright install-deps` requires sudo because it installs system libraries. Use `$(which playwright)` so sudo finds the venv binary.)

Verify:
```bash
source /home/akash/.openclaw/venv/bin/activate
python3 -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
deactivate
```

### Phase 6 — Migrate data from the VPS via SCP

The VPS is `62.238.13.149`, runs as root. You need to copy:

- `/root/.openclaw/.env` (API keys; uses `export KEY=val` syntax)
- `/root/.openclaw/sources.json` (YouTube channels, analyst handles)
- `/root/.openclaw/workspace/*.db` + `*.db-shm` + `*.db-wal` (SQLite + WAL siblings — must take all three or risk inconsistent reads)
- `/root/.openclaw/vault/` (research memory directory; recursive)
- `/root/.openclaw/gmail/token.json` (Gmail OAuth token; only if it exists)
- `/root/task_system/scripts/{create,list,run}_task.sh` (the actual task system scripts — Phase 8 needs these)

**Pause here ONCE and ask the operator:** *"What's the path to the .pem key for SSH'ing into 62.238.13.149?"*

Once they answer, set `KEY=<their answer>` and run:

```bash
chmod 600 "$KEY"
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

# Single config files
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/.openclaw/.env         /home/akash/.openclaw/.env
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/.openclaw/sources.json /home/akash/.openclaw/sources.json

# All SQLite files (db + WAL siblings) — use bash brace expansion via a here-string
ssh "${SSH_OPTS[@]}" root@62.238.13.149 'ls /root/.openclaw/workspace/*.db* 2>/dev/null' | \
  while read -r f; do
    scp "${SSH_OPTS[@]}" "root@62.238.13.149:$f" /home/akash/.openclaw/workspace/
  done

# Vault directory (recursive)
scp -r "${SSH_OPTS[@]}" root@62.238.13.149:/root/.openclaw/vault /home/akash/.openclaw/ 2>/dev/null || \
  echo "No vault directory on VPS — skipping (will be created on first run)"

# Gmail OAuth token (optional)
mkdir -p /home/akash/.openclaw/gmail
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/.openclaw/gmail/token.json \
  /home/akash/.openclaw/gmail/token.json 2>/dev/null || \
  echo "No Gmail token on VPS — Gmail watcher will need bootstrap_gmail.py later"

# Task system scripts
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/task_system/scripts/create_task.sh /home/akash/task_system/scripts/
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/task_system/scripts/list_task.sh   /home/akash/task_system/scripts/ 2>/dev/null || true
scp "${SSH_OPTS[@]}" root@62.238.13.149:/root/task_system/scripts/run_task.sh    /home/akash/task_system/scripts/ 2>/dev/null || true
chmod +x /home/akash/task_system/scripts/*.sh
```

Now generate a systemd-friendly env file (the original `.env` uses `export KEY=val`, which `EnvironmentFile=` in systemd cannot parse):

```bash
sed -E 's/^[[:space:]]*export[[:space:]]+//' /home/akash/.openclaw/.env \
  | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)="?(.*[^"])"?$/\1=\2/' \
  > /home/akash/.openclaw/.env.systemd
chmod 600 /home/akash/.openclaw/.env.systemd
```

Verify:
- `grep -c '^export ' /home/akash/.openclaw/.env` is > 0 (original has exports).
- `grep -c '^export ' /home/akash/.openclaw/.env.systemd` is 0 (stripped version has none).
- `grep -E '^(DISCORD_BOT_TOKEN|FINNHUB_API_KEY|OPENROUTER_API_KEY)=' /home/akash/.openclaw/.env.systemd` finds all three.

### Phase 7 — SearXNG (Tier 4 news fallback on :8888)

```bash
cd /home/akash/.openclaw/workspace
sg docker -c 'docker compose up -d'
sleep 10
curl -s http://localhost:8888/healthz && echo " — SearXNG OK"
```

If healthz fails: `sg docker -c 'docker compose logs searxng | tail -50'`, fix root cause, retry.

### Phase 8 — Task system

The scripts were copied in Phase 6. Sanity-check they exist and are executable:

```bash
ls -la /home/akash/task_system/scripts/create_task.sh
[[ -x /home/akash/task_system/scripts/create_task.sh ]] || chmod +x /home/akash/task_system/scripts/create_task.sh
test -d /home/akash/task_system/logs || mkdir -p /home/akash/task_system/logs
test -f /home/akash/task_system/notifications.log || touch /home/akash/task_system/notifications.log
```

If `create_task.sh` is missing (VPS didn't have it for some reason), write the minimal-viable version:

```bash
cat > /home/akash/task_system/scripts/create_task.sh <<'SCRIPT'
#!/bin/bash
# Fallback create_task.sh — basic background scheduler with logging.
TASK_NAME="$1"; DELAY="$2"; COMMAND="$3"
LOG_DIR=/home/akash/task_system/logs; mkdir -p "$LOG_DIR"
(sleep "$DELAY" && eval "$COMMAND" >>"$LOG_DIR/${TASK_NAME}.log" 2>&1 && \
  echo "[$(date)] Task $TASK_NAME completed" >> /home/akash/task_system/notifications.log) &
echo "Task $TASK_NAME scheduled for ${DELAY}s from now"
SCRIPT
chmod +x /home/akash/task_system/scripts/create_task.sh
```

### Phase 9 — systemd service (write only — DO NOT enable, DO NOT start)

The VPS is still running the bot. If we start a second one with the same Discord token, the gateway will boot one of them. Phase 9 prepares the unit; Phase 12 explains how to cut over.

```bash
sudo tee /etc/systemd/system/openclaw.service > /dev/null <<'EOF'
[Unit]
Description=OpenClaw Signal Engine
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=akash
WorkingDirectory=/home/akash/.openclaw/workspace
EnvironmentFile=/home/akash/.openclaw/.env.systemd
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:0
ExecStart=/home/akash/.openclaw/venv/bin/python3 -m consensus_engine
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
```

Do **NOT** run `enable` or `start` here. Verify with `sudo systemctl is-enabled openclaw.service` → `disabled`, and `sudo systemctl is-active openclaw.service` → `inactive`.

### Phase 10 — Dry-run verification (no Discord posting)

```bash
cd /home/akash/.openclaw/workspace
source /home/akash/.openclaw/.env
source /home/akash/.openclaw/venv/bin/activate
python3 -m consensus_engine --dry-run --once 2>&1 | tail -50
deactivate
```

Must complete with no Python traceback. If a module is missing, `pip install` it inside the venv and retry. If a config key is missing, check `/home/akash/.openclaw/.env` against `consensus_engine/config.py` and resolve.

### Phase 11 — Final verification

Run all of these. Every check must pass before declaring setup complete:

```bash
echo "=== checkpoint file ==="
cat ~/.openclaw/setup-progress.json | jq

echo "=== systemd state (must be disabled+inactive) ==="
sudo systemctl is-enabled openclaw.service
sudo systemctl is-active  openclaw.service

echo "=== SearXNG ==="
curl -s http://localhost:8888/healthz

echo "=== symlinks ==="
ls -la /root/.openclaw  /root/task_system
ls /root/.openclaw/workspace/CLAUDE.md
ls /root/task_system/notifications.log

echo "=== desktop control tools ==="
which xdotool scrot wmctrl xclip

echo "=== docker ==="
sg docker -c 'docker ps'

echo "=== playwright ==="
source /home/akash/.openclaw/venv/bin/activate
python3 -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
deactivate

echo "=== env files ==="
grep -c '^export '            /home/akash/.openclaw/.env
grep -c '^export '            /home/akash/.openclaw/.env.systemd
grep -E '^DISCORD_BOT_TOKEN=' /home/akash/.openclaw/.env.systemd | wc -l
```

### Phase 12 — Cutover instructions (print, do NOT execute)

Print exactly this for the operator:

```
SETUP COMPLETE.

The bot is INSTALLED but NOT RUNNING on this Debian PC, so it doesn't fight
the VPS for the Discord bot token. When you're ready to cut over:

  1. On the VPS (62.238.13.149):
       sudo systemctl stop openclaw.service     # or however you stop it there
       sudo systemctl disable openclaw.service  # so it doesn't auto-revive

  2. On THIS Debian PC:
       sudo systemctl enable --now openclaw.service
       sudo journalctl -u openclaw.service -f   # confirm scanners + Discord login

If the Debian bot looks healthy after a few minutes (alerts firing, no crashes,
sources cycling), you're cut over. If anything looks wrong:

       sudo systemctl stop openclaw.service     # on Debian
       sudo systemctl enable --now openclaw.service  # on the VPS, to roll back

The VPS data lives at /home/akash/.openclaw and /home/akash/task_system; the
/root/* paths are symlinks to those, so anything that references the old VPS
paths still works.
```

---

## What you can do once everything is verified

- **Screenshot Discord**: `wmctrl -a Discord && sleep 0.5 && scrot /tmp/discord.png` then read the image.
- **Click anything on screen**: `xdotool mousemove X Y click 1`
- **Read clipboard**: `xclip -o`
- **Watch bot logs (post-cutover)**: `journalctl -u openclaw.service -f`
- **One-off bot run**: `cd ~/.openclaw/workspace && source ~/.openclaw/.env && source ~/.openclaw/venv/bin/activate && python3 -m consensus_engine --once`
- **Push code changes**: `git -C ~/.openclaw/workspace add -A && git commit -m "msg" && git push`

---

*End of runbook. Begin at Phase 0.*
