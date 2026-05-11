# VPS Consolidation Plan — collapse the root/openclaw split

**Date:** 2026-05-11
**Author:** Claude (drafted, not yet executed)
**Status:** PLAN — no execution, awaiting operator approval
**Related:** `plans/openclaw-debian-setup.md` (the never-executed Debian PC plan; this plan adapts its single-user/single-home-dir end-state to the VPS itself)

---

## 1. Background

### 1.1 How the split arose — timeline

| Date | Event | Effect on state |
|---|---|---|
| pre-2026-05-02 | OpenClaw ran fully as `root` from `/root/.openclaw/` on the Hetzner VPS (62.238.13.149, `snapshot-ubuntu-8gb-hel1-1`). Single home dir, single config, no split. | Baseline — no split. |
| 2026-05-02 19:49 | A `openclaw` user (uid 998) was created and `/home/openclaw/.openclaw/` was populated by copying from `/root/.openclaw/`. `consensus-engine.service` systemd unit was written to run as user `openclaw` with `EnvironmentFile=-/home/openclaw/.openclaw/.env.service`. Workspace was symlinked: `/root/.openclaw/workspace → /home/openclaw/.openclaw/workspace`. Engine was cut over to the `openclaw` user. | Engine moved. Gateway, env files, openclaw.json, agents/, vault/, gmail/, cron/, devices/ all left untouched in `/root/.openclaw/`. **Split begins.** |
| 2026-05-05 | `plans/openclaw-debian-setup.md` written — a Debian PC migration runbook for a *different* target (local Debian PC, user `akash`). This plan was never executed, but it documents what a clean single-user/single-home setup looks like. | No state change — reference doc only. |
| 2026-05-06 02:23 | `/home/openclaw/.openclaw/.env` was hand-edited. Some keys (`EXA_AI_API_KEY`, `INGEST_BEARER_TOKEN_R1/R7`) got commented out — likely a manual cleanup pass that mistook them for unused. The mirror `.env.service` was not regenerated, so it still has them uncommented and the engine kept working. | 3-way `.env` drift seeded. |
| 2026-05-08 → 2026-05-10 | **First production outage caused by the split.** `config/consensus.yaml`'s `llm.model` was updated from `ling-2.6-1t:free` to `ring-2.6-1t:free`. The engine picked up the change. `/root/.openclaw/openclaw.json` (where the gateway's `openrouter/auto` chain lives) was missed — the operator was editing config under `/home/openclaw/.openclaw/` and didn't realize the gateway had its own copy. Cron-triggered gateway agent turns 404'd for two days against the now-dead `ling-2.6-1t:free`. Recorded in `/root/.openclaw/cron/jobs-state.json`. | Concrete cost: 2 days of failed gateway turns. |
| 2026-05-10 | Agentic Discord `@-mention` mode wired. Bridge added: `/etc/sudoers.d/openclaw-agent` containing `openclaw ALL=(root) NOPASSWD: /usr/bin/openclaw`, so the `openclaw`-owned engine could shell out to the root-owned `openclaw` gateway CLI. Discord plugin disabled in both `openclaw.json` files; @-mention routes engine → sudoers bridge → gateway agent → OpenRouter. | Duct tape made the split *functional*, not *fixed*. |
| 2026-05-11 00:05 PDT | Commit `b054f80` (`feat(config): sync gateway LLM chain from consensus.yaml + 4-layer drift defense`). Adds `scripts/sync_gateway_models.py`, a pre-commit hook, daily probe, and `boot_drift_check` in `consensus_engine/health.py`. The boot check reads `/root/.openclaw/openclaw.json` to compare against `consensus.yaml`. | Drift-detection layer added — but assumes both files are *readable from the engine's user*. |
| 2026-05-11 00:06–00:07 PDT | **Second production incident.** Engine restart-looped 3 times. `PermissionError: [Errno 13] Permission denied: '/root/.openclaw/openclaw.json'`. `/root` and `/root/.openclaw` were mode `0700 root:root`; engine runs as `openclaw`; the new `_GATEWAY_CONFIG.exists()` call wasn't wrapped. `asyncio.gather` propagated the exception, killing the engine. Observed live in this conversation: `NRestarts=3`, `Main process exited, code=exited, status=1/FAILURE`. | Direct consequence of the split — the new drift check tried to inspect a file the engine couldn't read. |
| 2026-05-11 00:08 PDT | Commit `93cb202` (`fix(health): catch PermissionError + wrap boot_drift_check so engine survives`). `_enumerate_gateway_chain_models` wraps `exists() + read_text()` in `try / except PermissionError`; `boot_drift_check` body wrapped so any check failure logs and returns instead of taking down the gather. | Engine survives, but the boot check now silently posts a Discord ❌ "GATEWAY config unreadable: Permission denied" alert at every restart. Symptom hidden, not fixed. |
| 2026-05-11 00:22 PDT | Commit `85baf9e` (`fix(model_config): catch PermissionError on dotenv read, not just exists()`). To make the drift check actually work, a POSIX ACL was added: `openclaw:r-x` on `/root` + `/root/.openclaw`, `openclaw:r--` on `/root/.openclaw/openclaw.json`. The ACL traversal made `/root/.openclaw/.env` *visible* to `openclaw` (`exists()` succeeded) but not readable — so the engine's import-time `load_dotenv()` on `/root/.openclaw/.env` raised `PermissionError` and killed the engine before main. Fix: wrap both `exists()` and `load_dotenv()` in a single try and fall through silently. | Engine boots. Drift check now reads `/root/.openclaw/openclaw.json` and reports ❌ via Discord because the chain at `/home/openclaw/.openclaw/openclaw.json` is stale (Apr 24) vs `/root/` fresh (May 11). |

**Net result by 2026-05-11 03:00 PDT:** the engine is stable, but every restart posts a noisy ❌ GATEWAY drift alert to Discord, three `.env` files disagree, and any future change to model config has to remember to write two places. The split-user state is the upstream cause; the last three commits patch symptoms without addressing it.

### 1.2 Current split (point-in-time inventory)

| Component | Runs as | Home dir | `openclaw.json` mtime | Model chain |
|---|---|---|---|---|
| `consensus-engine.service` | `openclaw` | `/home/openclaw/.openclaw` | 2026-04-24 (stale) | `minimax/nemotron/gemma` |
| OMC gateway (port 18789) | `root` | `/root/.openclaw` | 2026-05-11 (fresh) | `ring-2.6/gpt-oss-120b/glm-4.5-air` |

`/root/.openclaw/workspace` is already a symlink to `/home/openclaw/.openclaw/workspace`, so the code is shared. The configs, state, env files, agents/, vault/, gmail/, cron/, devices/, etc. are duplicated.

### 1.3 Why consolidate now

1. **Future regressions of the May 8–10 class are guaranteed** as long as two `openclaw.json` files exist. The drift-defense scripts shipped in `b054f80` only write one of them.
2. **Every engine restart spams Discord** with a ❌ GATEWAY drift alert until the two `openclaw.json` files agree — they currently don't, by design.
3. **Three `.env` files** (`/home/openclaw/.openclaw/.env`, `/home/openclaw/.openclaw/.env.service`, `/root/.openclaw/.env`) keep drifting. Any hand-edit, any regeneration script, any new tooling that loads dotenv has to pick one and risks losing keys (this already happened with the EXA/INGEST keys on May 6).
4. **The sudoers bridge** is an attack surface and a maintenance hazard. Single-user removes the need entirely.
5. **The operator wants to focus on signal quality**, not on remembering which file lives where. The Debian migration was the original cure but is deferred — this is the in-place equivalent.

## 2. Goal

End-state: **one user (`openclaw`), one home dir (`/home/openclaw/.openclaw`), one `openclaw.json`, one `.env`**. `/root/.openclaw` becomes a symlink to `/home/openclaw/.openclaw` (matches the Debian plan's structure, just with `openclaw` instead of `akash`). Gateway runs as `openclaw`. Sudoers bridge removed.

## 3. Pre-flight evidence (collected 2026-05-11, current state)

- Gateway PID 1166954, PPID=1 (daemonized — NOT a child of any claude session). Has `/root/.openclaw/tasks/runs.sqlite` (WAL) open. Killable without disrupting interactive sessions.
- `consensus-engine.service` runs as `openclaw`, `EnvironmentFile=-/home/openclaw/.openclaw/.env.service`, working dir `/home/openclaw/.openclaw/workspace`.
- Existing POSIX ACL (added in `85baf9e`): `openclaw:r-x` on `/root` + `/root/.openclaw`, `openclaw:r--` on `/root/.openclaw/openclaw.json`. `/root/.openclaw/.env` is still root-only (engine skips it via `load_dotenv` PermissionError catch).
- 926/929 tests pass on HEAD (`85baf9e`). 3 pre-existing calibration failures (`TODO commit F`).
- Pre-stage snapshots already exist on disk (taken 2026-05-11T00:41 PDT):
  - `/home/openclaw/openclaw-home.pre-stage1.2026-05-11T00-41-11-07-00.tar.gz` (1.1G — includes the 215MB consensus.db)
  - `/root/openclaw-root.pre-stage1.2026-05-11T00-41-11-07-00.tar.gz` (80M)
  - `/etc/sudoers.d/openclaw-agent.pre-stage1.bak`

These snapshots remain valid for the run-day as long as `/home/openclaw/.openclaw/` and `/root/.openclaw/` haven't been edited since. **Re-take if more than a few hours have passed or any significant change has happened.**

## 4. Stage 1 — file consolidation (~15 min, engine downtime ~2 min)

### 4.1 Stop the engine cleanly
```bash
sudo systemctl stop consensus-engine.service
sudo systemctl is-active consensus-engine.service   # → inactive
```

### 4.2 Reconcile `.env` (the only file that is *currently* drifting in a load-bearing way)
3 keys are uncommented in `/root/.openclaw/.env` and `.env.service` but commented out in `/home/openclaw/.openclaw/.env`. Without this fix, any future "regen .env.service from .env" loses them silently.

```bash
# Uncomment EXA_AI_API_KEY (line 20) and INGEST_BEARER_TOKEN_R1/R7 (lines 27-28) in /home/.env
sudo -u openclaw sed -i.pre-uncomment -E \
  's/^#(export\s+)?(EXA_AI_API_KEY|INGEST_BEARER_TOKEN_R[17])=/\1\2=/' \
  /home/openclaw/.openclaw/.env

# Add `export ` prefix to INGEST lines if not already present (match the file's house style)
sudo -u openclaw sed -i -E 's/^(INGEST_BEARER_TOKEN_R[17]=)/export \1/' /home/openclaw/.openclaw/.env

# Verify: all 3 should appear once, uncommented, with export prefix
sudo grep -nE "(EXA_AI_API_KEY|INGEST_BEARER_TOKEN_R[17])" /home/openclaw/.openclaw/.env
```

### 4.3 Regenerate `.env.service` from `.env`
Use the exact sed pattern from `plans/openclaw-debian-setup.md` Phase 6:
```bash
sudo -u openclaw bash -c '
  sed -E "s/^[[:space:]]*export[[:space:]]+//" /home/openclaw/.openclaw/.env \
    | sed -E "s/^([A-Za-z_][A-Za-z0-9_]*)=\"?(.*[^\"])\"?$/\1=\2/" \
    > /home/openclaw/.openclaw/.env.service.new
'
sudo chown openclaw:openclaw /home/openclaw/.openclaw/.env.service.new
sudo chmod 600 /home/openclaw/.openclaw/.env.service.new

# Verify: must contain DISCORD_BOT_TOKEN, FINNHUB_API_KEY, OPENROUTER_API_KEY, all 3 INGEST/EXA keys
for k in DISCORD_BOT_TOKEN FINNHUB_API_KEY OPENROUTER_API_KEY EXA_AI_API_KEY INGEST_BEARER_TOKEN_R1 INGEST_BEARER_TOKEN_R7; do
  sudo grep -qE "^${k}=" /home/openclaw/.openclaw/.env.service.new && echo "$k ok" || echo "$k MISSING"
done

# Swap in (atomic mv)
sudo mv /home/openclaw/.openclaw/.env.service /home/openclaw/.openclaw/.env.service.pre-regen
sudo mv /home/openclaw/.openclaw/.env.service.new /home/openclaw/.openclaw/.env.service
sudo chmod 600 /home/openclaw/.openclaw/.env.service
```

### 4.4 Reconcile `openclaw.json`
`/root/.openclaw/openclaw.json` is fresher (May 11) and is the file the live gateway reads. Engine's `boot_drift_check` reads it too. The engine-side copy at `/home/openclaw/.openclaw/openclaw.json` is stale (Apr 24). Make the engine-side a hard-copy of the gateway one for now; Stage 2's symlink will collapse the duplication entirely.

```bash
# Sanity: read both, confirm root has the newer model chain
sudo grep -A2 "openrouter/auto" /root/.openclaw/openclaw.json | head -8
sudo cat /home/openclaw/.openclaw/openclaw.json | grep -A2 "openrouter/auto" | head -8

# Replace home copy with root copy
sudo cp /root/.openclaw/openclaw.json /home/openclaw/.openclaw/openclaw.json
sudo chown openclaw:openclaw /home/openclaw/.openclaw/openclaw.json
sudo chmod 600 /home/openclaw/.openclaw/openclaw.json

# Verify both files are byte-identical
sudo cmp /root/.openclaw/openclaw.json /home/openclaw/.openclaw/openclaw.json && echo "IDENTICAL"
```

### 4.5 Drop stale `openclaw.json.bak.*` in `/home/openclaw/.openclaw/`
The `.bak.*` files in `/home/openclaw/.openclaw/` are from April. The `.bak.*` files in `/root/.openclaw/` are fresher and managed by the gateway. Drop the stale home copies; Stage 2 unifies the rest.

```bash
sudo rm -v /home/openclaw/.openclaw/openclaw.json.bak \
           /home/openclaw/.openclaw/openclaw.json.bak.[0-9] \
           /home/openclaw/.openclaw/openclaw.json.last-good \
           /home/openclaw/.openclaw/openclaw.json.new
sudo ls -la /home/openclaw/.openclaw/openclaw.json*
```

### 4.6 Start engine, verify boot is clean
```bash
sudo systemctl start consensus-engine.service
sleep 15

# Must all be true:
sudo systemctl is-active consensus-engine.service                                              # → active
sudo journalctl -u consensus-engine.service --since "1 minute ago" | grep -c "Permission denied"  # → 0
sudo journalctl -u consensus-engine.service --since "1 minute ago" | grep -c "boot drift check FAILED"  # → 0
sudo journalctl -u consensus-engine.service --since "1 minute ago" | grep -c "GATEWAY drift"   # → 0
sudo journalctl -u consensus-engine.service --since "1 minute ago" | grep -E "ingest_server|TweetShift listener|youtube: poll loop started"  # → all 3 present

# Confirm no ❌ GATEWAY drift Discord message was posted (manual: check #chat for last 2 min)
```

**Pass criteria for Stage 1:** all 4 grep counts above match, all 3 startup lines present.

### 4.7 Stage 1 rollback (if any check fails)
```bash
sudo systemctl stop consensus-engine.service
sudo mv /home/openclaw/.openclaw/.env.service.pre-regen /home/openclaw/.openclaw/.env.service
sudo cp /home/openclaw/.openclaw/.env.pre-uncomment /home/openclaw/.openclaw/.env
TS=$(cat /tmp/openclaw-consolidate-ts)
sudo tar -xzf /home/openclaw/openclaw-home.pre-stage1.${TS}.tar.gz -C /tmp/restore .openclaw/openclaw.json
sudo cp /tmp/restore/.openclaw/openclaw.json /home/openclaw/.openclaw/openclaw.json
sudo chown -R openclaw:openclaw /home/openclaw/.openclaw
sudo systemctl start consensus-engine.service
```

## 5. Stage 2 — gateway cutover to openclaw user (~10 min, gateway downtime ~30 s)

### 5.1 Re-snapshot before destructive moves
```bash
TS=$(date -Iseconds | tr ':' '-')
sudo tar --exclude='*.log' -czf /home/openclaw/openclaw-home.pre-stage2.${TS}.tar.gz -C /home/openclaw .openclaw
echo "$TS" | sudo tee /tmp/openclaw-stage2-ts
```

### 5.2 Stop the root-owned gateway (SIGTERM, NOT SIGKILL — let SQLite WAL flush)
```bash
GATEWAY_PID=$(pgrep -f "openclaw/dist/index.js gateway --port 18789")
echo "gateway pid: $GATEWAY_PID"
sudo kill -TERM $GATEWAY_PID
# Wait up to 30s for clean shutdown
for i in $(seq 1 30); do
  pgrep -f "openclaw/dist/index.js gateway" >/dev/null || break
  sleep 1
done
pgrep -f "openclaw/dist/index.js gateway" && echo "FAIL: gateway still running" && exit 1
echo "gateway stopped clean"
```

### 5.3 Replace `/root/.openclaw` with a symlink
```bash
# Sanity: workspace is already a symlink; we don't want it nested
ls -la /root/.openclaw/workspace   # → symlink to /home/openclaw/.openclaw/workspace

sudo mv /root/.openclaw /root/.openclaw.bak-pre-consolidate
sudo ln -sfn /home/openclaw/.openclaw /root/.openclaw

# Verify: paths still resolve
ls -la /root/.openclaw                            # → symlink to /home/openclaw/.openclaw
ls /root/.openclaw/openclaw.json                  # → file exists via symlink
ls /root/.openclaw/workspace/CLAUDE.md            # → file exists via symlink
cat /root/.openclaw/tasks/runs.sqlite >/dev/null  # → readable (or "no such file" if absent in /home/ — acceptable, gateway will recreate)
```

**If `/home/openclaw/.openclaw/tasks/` doesn't exist** (gateway state only existed under /root), the symlink resolves to nowhere. Pre-empt by copying the gateway-only dirs over first:
```bash
for d in tasks devices flows locks delivery-queue session-delivery-queue cron logs; do
  if [ -d /root/.openclaw.bak-pre-consolidate/$d ] && [ ! -d /home/openclaw/.openclaw/$d ]; then
    sudo cp -a /root/.openclaw.bak-pre-consolidate/$d /home/openclaw/.openclaw/
    sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/$d
    echo "copied $d"
  fi
done
```

### 5.4 Start gateway as `openclaw`
```bash
# Run the gateway as openclaw, detached, log to file
sudo -u openclaw bash -c '
  cd /home/openclaw/.openclaw/workspace
  nohup openclaw gateway start --port 18789 \
    > /home/openclaw/.openclaw/logs/gateway.out 2>&1 &
  echo $! > /tmp/openclaw-gateway.pid
'

# Wait for it to listen
for i in $(seq 1 30); do
  ss -tlnp 2>/dev/null | grep -q ":18789" && break
  sleep 1
done

# Verify: listening on 18789, owned by openclaw uid (998)
ss -tlnp | grep ":18789"                           # → users:(("node",pid=*,fd=*))
ps -o pid,user,cmd -p $(cat /tmp/openclaw-gateway.pid)  # → user=openclaw
```

### 5.5 Persistent gateway via systemd unit (recommended — survives reboots, auto-restarts)
```bash
sudo tee /etc/systemd/system/openclaw-gateway.service > /dev/null <<'EOF'
[Unit]
Description=OpenClaw Gateway (WebSocket/agent runtime)
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/home/openclaw/.openclaw/workspace
EnvironmentFile=-/home/openclaw/.openclaw/.env.service
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/openclaw gateway start --port 18789
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Kill the nohup'd gateway, hand over to systemd
sudo kill $(cat /tmp/openclaw-gateway.pid) 2>/dev/null
sleep 2
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-gateway.service
sudo systemctl status openclaw-gateway.service --no-pager | head -10
```

### 5.6 Remove the sudoers bridge
```bash
sudo rm /etc/sudoers.d/openclaw-agent
# Backup at /etc/sudoers.d/openclaw-agent.pre-stage1.bak is preserved
```

### 5.7 Stage 2 rollback (if Stage 3 testing fails)
```bash
sudo systemctl stop openclaw-gateway.service
sudo systemctl disable openclaw-gateway.service
sudo rm /etc/systemd/system/openclaw-gateway.service
sudo systemctl daemon-reload

sudo rm /root/.openclaw
sudo mv /root/.openclaw.bak-pre-consolidate /root/.openclaw

sudo cp /etc/sudoers.d/openclaw-agent.pre-stage1.bak /etc/sudoers.d/openclaw-agent
sudo chmod 0440 /etc/sudoers.d/openclaw-agent

# Restart the original root-owned gateway exactly as it ran before
sudo -i bash -c 'cd /root/.openclaw/workspace && nohup openclaw gateway start --port 18789 > /tmp/openclaw-gateway-revert.log 2>&1 &'
```

## 6. Stage 3 — thorough Discord bot functional testing (~20 min)

**Goal:** verify the bot is fully usable for morning trading. Every test below must show evidence in the journal AND on Discord. Read the bot's Discord responses, don't just assume.

**Test bench** (channel IDs from `DISCORD_CHANNEL_INFO.md` + `.env.service`):
- `#chat`: 1468890179698692147
- briefing: 1496209511436910764
- feed: 1487006319570452490
- Webhook for sending test messages: stored in memory `discord_webhook.md` (use this to deliver test messages the bot can read)

### 6.1 Engine basics
```bash
# Engine is active, no errors in last 5 min
sudo systemctl is-active consensus-engine.service                                            # → active
sudo systemctl is-active openclaw-gateway.service                                            # → active
sudo journalctl -u consensus-engine.service --since "5 min ago" | grep -ciE "error|traceback|permission denied"  # → 0
# Scanners cycled at least once
sudo journalctl -u consensus-engine.service --since "10 min ago" | grep -c "ApeWisdom: .* trending tickers"  # → ≥1
sudo journalctl -u consensus-engine.service --since "10 min ago" | grep -c "TweetShift listener"             # → ≥1
sudo journalctl -u consensus-engine.service --since "10 min ago" | grep -c "youtube: poll loop"              # → ≥1
```

### 6.2 Bot commands (post via webhook, read bot reply)
Send each command to `#chat` via the Discord webhook, then read the bot's reply:

| Test | Send (webhook → #chat) | Expected bot reply (verify by reading message) |
|---|---|---|
| `!ask` quick | `!ask what stock is in the news today` | Coherent multi-line reply citing tickers + sources; no "model 404" error |
| `!trend` | `!trend` | Embed titled "Reddit Trend Digest" with momentum numbers (not "momentum —") |
| `!all <ticker>` | `!all NVDA` | Embed with Buy Zone, Current Price, Stop, TP1/TP2, narrator section, no contradiction warnings |
| `@mention` agentic | `<@BOT_USER_ID> summarize the current state of the workspace TODO.md` | Coherent reply listing the 4 TODO items |
| `@mention` codebase Q | `<@BOT_USER_ID> in consensus_engine/health.py, what does boot_drift_check do?` | Accurate description matching the function body |

Read responses with:
```bash
# Pull last 10 messages from #chat (uses the gateway running as openclaw now)
openclaw message read --channel discord --target 1468890179698692147 --limit 10
```
For each test row above, log to a temp file: command sent, bot response, pass/fail with reason. Fail = response missing, error embed, or content factually wrong.

### 6.3 Cron jobs (already scheduled in `crontab -l`)
Two cron jobs are wired:
- `15 0 * * *` — `scripts/run_reference_assertions_cron.sh` (YouTube reference-video E2E)
- `*/5 * * * *` — `scripts/check_searxng_health.sh` (SearXNG health monitor)

Cron runs as root. Both scripts hit `/root/.openclaw/workspace/...`. After Stage 2's symlink, this resolves to `/home/openclaw/.openclaw/workspace/...`. Test manually so we don't wait for the schedule:
```bash
# SearXNG health check (every 5 min job)
sudo /root/.openclaw/workspace/scripts/check_searxng_health.sh
echo "exit code: $?"   # → 0

# Reference assertions (daily job — only run if SerpAPI/Gemini quota allows; or pass --dry-run if supported)
sudo bash -x /root/.openclaw/workspace/scripts/run_reference_assertions_cron.sh 2>&1 | tail -30
```
Pass criteria: both scripts exit 0; no `Permission denied` or `No such file` errors.

### 6.4 Workspace-aware @-mention smoke test
```bash
# Ask the agent something only knowable from the workspace
# (via webhook → #chat → bot picks up @mention → gateway agent answers)
# Send: "@bot list the 3 most recent commit subjects on master"
# Expected: 85baf9e, 93cb202, b054f80
```
This proves the agent has shell + git access through the new openclaw-owned gateway.

### 6.5 Pass criteria (all must hold)
- Stage 1 boot checks: 4 grep zeros + 3 startup lines present.
- Stage 2: both services `active`, gateway listening on :18789, running as `openclaw` (uid 998).
- Stage 3.1: 0 errors in journal, ≥1 ApeWisdom + TweetShift + YouTube heartbeat.
- Stage 3.2: all 5 command tests pass with coherent on-topic replies (no model errors, no 404s, no `Permission denied` on the gateway).
- Stage 3.3: both cron scripts exit 0.
- Stage 3.4: @-mention with shell access returns the correct commit subjects.

If **any** criterion fails, execute the matching rollback (Stage 1.7 or Stage 2.7), restart from the pre-snapshot, and write up the failure mode here.

## 7. Cleanup (after 24h of stable operation)

```bash
sudo rm -rf /root/.openclaw.bak-pre-consolidate
sudo rm /home/openclaw/openclaw-home.pre-stage1.*.tar.gz
sudo rm /home/openclaw/openclaw-home.pre-stage2.*.tar.gz
sudo rm /root/openclaw-root.pre-stage1.*.tar.gz
sudo rm /etc/sudoers.d/openclaw-agent.pre-stage1.bak
sudo rm /home/openclaw/.openclaw/.env.pre-uncomment
sudo rm /home/openclaw/.openclaw/.env.service.pre-regen
```

Update memory: mark VPS consolidated to single `openclaw` user as of consolidation date; mark Debian PC migration DEFERRED.

## 8. Risks & open questions

| Risk | Mitigation |
|---|---|
| Gateway has open SQLite WAL handles into `/root/.openclaw/tasks/runs.sqlite` at kill time | SIGTERM (not SIGKILL); wait up to 30s for graceful shutdown |
| Gateway state files (`devices/`, `flows/`, `locks/`) only exist under `/root/.openclaw/` — symlink would orphan them | Stage 5.3 copies them into `/home/openclaw/.openclaw/` before mv |
| `cron` jobs run as `root` and hit `/root/.openclaw/workspace/...` | Already works via existing symlink; Stage 5.3 keeps the path valid |
| `openclaw gateway start` CLI invocation may differ from the implicit one done by `claude --settings teammateMode=tmux` | Tested in Stage 2.4 by `nohup` before committing to systemd unit |
| 4 hardcoded references to `/root/.openclaw/...` in `consensus_engine/config.py`, `db.py`, `config/consensus.yaml`, `health.py` | All resolve through the new symlink — no code changes required |
| The current interactive claude session is running as `root` in tmux | Unaffected — it touches `/root/.claude/...` not `/root/.openclaw/...` |
| User added `EXA_AI_API_KEY` to `.env.service` (May 2) but commented it out in `.env` (May 6) — intent unclear | Plan assumes uncommented = intended (`.env.service` is what the engine actually loads); flag if Stage 3.2 reveals an EXA-related failure |

## 9. Out of scope (do not touch in this plan)

- The Debian PC migration itself — explicitly deferred per operator preference.
- Refactoring code references to `/root/.openclaw` to use `/home/openclaw/.openclaw` directly. The symlink approach is intentional: it keeps the diff minimal and matches the Debian plan's Phase 4 pattern.
- Splitting the gateway out of the `openclaw` npm CLI into a separate binary.
- Any change to `consensus.yaml`, model chains, scanner config, or alert logic.
