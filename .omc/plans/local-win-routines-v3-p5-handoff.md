# Pass 5 Execution Log — local-win-routines-v3

_Started: 2026-05-02 · Interrupted for context compression after Tasks 1–5_

---

## Progress Summary

**Completed tasks (Tasks 1–5 of 12) — all committed and pushed to master**

| Task | Description | Commit SHA | Notes |
|---|---|---|---|
| 1 | Schema: models.py + db.py (5 new tables, 2 SourceType values, IN-list) | `616f054` | Reviewed ✅ |
| 2 | `consensus_engine/utils/redacting_filter.py` | `6467aea` | Reviewed ✅ |
| 3 | `consensus_engine/ingest_server.py` | `847864e` + `d29b5aa` | Reviewed ✅ (3 HIGH issues fixed in d29b5aa) |
| 4 | `consensus_engine/scanners/gmail_watcher.py` | `b2fdd79` | Reviewed ✅ |
| 5 | Wire main.py + config/consensus.yaml + requirements.txt + .gitignore + .pre-commit-config.yaml | `5418029` | Quick-verified ✅ |

**Baseline tests:** 703 pass, 2 pre-existing failures (test_feature_flags.py), 1 skipped — no regressions.

---

## Pending Tasks (7 of 12 remain)

### Task 6: `tests/test_ingest_server.py`
Write unit tests for `consensus_engine/ingest_server.py` covering:
- Bearer rotation overlap (old token still accepted in 24h window)
- Nonce idempotent retry (assert exactly-one row in ticker_signals on duplicate nonce)
- ts freshness rejects stale (>600s old signed_ts)
- JSON schema rejects malformed payload
- RedactingFilter scrubs Authorization header from log records
- Partial-fanout idempotency (409 when result row absent)
- ip_rate_limit per /64 IPv6 + per /24 IPv4
- Per-routine bearer (R1 token rejected on R7 routine_id)
- Use pytest-asyncio + aiohttp.test_utils or direct handler calls with mocked db
- `tests/test_ingest_server.py`

### Task 7: `tests/test_gmail_watcher.py`
Write unit tests for `consensus_engine/scanners/gmail_watcher.py` covering:
- Three-of-three gate (each check independently blocks)
- Body-hash dedup (same body different message-id = skip)
- Quoted-content stripping (forwarded chain tickers not extracted)
- Per-sender-per-hour quota (21st insert blocked)
- Scope-verification path (missing scope triggers error)
- restart-on-exception: inner loop breaks on RuntimeError, retries auth
- Message-id dedup
- Mock the Gmail API service
- `tests/test_gmail_watcher.py`

### Task 8: `windows_runtime/ingest_client/post.py` (~200 lines)
Shared HTTPS POST helper for R1 and R7 Windows routines.
- `submit(routine_id, source_type, source_detail, raw_text, sentiment='neutral', event_ts=None) -> bool`
- `flush_outbox() -> int`
- Reads bearer from `windows_runtime/ingest_client/.bearer.<routine_id>.local` (gitignored)
- Reads SPKI pin from `windows_runtime/ingest_client/spki.pinned`
- Payload: `{v:1, src=routine_id, source_type, source_detail, raw_text, sentiment, event_ts, signed_ts=now, nonce=uuid4, routine_id}`
- On 200: success. On 401/403: pause outbox. On 429: respect Retry-After. On 5xx/connect error: write to outbox.db
- Outbox SQLite schema: `(nonce PK, routine_id, payload_json, first_attempt, last_attempt, attempt_count, dropped_at NULL)`
- Drop if `now - first_attempt > 23h`
- Flush every 60s up to 10 unsent. Alert at 900 queued.

### Task 9: `windows_runtime/R1_AUTHED_WEB/` artifacts
Two files: `PROMPT.md` (~150 lines) and `target_sites.yaml`.
- PROMPT.md: Claude Desktop routine instructions — preflight (git pull, signature verify, version check, bearer check, SHA assertion, heartbeat-start), per-target loop (Reddit/SA/Benzinga with jitter, sentinel checks), postflight heartbeat, 360s wall-clock abort.
- target_sites.yaml: Reddit subs (placeholder), SA/Benzinga ticker lists (~5 examples), per-site selectors + sentinels + jitter/dwell ranges.

### Task 10: `windows_runtime/R7_DISCORD_DAEMON/` artifacts
Three files: `daemon.py` (~400 lines), `install.ps1`, `config.example.json`.
- daemon.py: pywinauto UIA daemon — human-activity gate, per-channel scroll+snapshot, AutomationId dedup with composite fallback, same-sender-60s suppress, ingest_client.submit, heartbeat every 60s, Class-A detection, 6 polls/hour target.
- install.ps1: Win Task Scheduler (at logon, restart every 1 min), bearer file with attrib+ACL, Defender exclusions, 7-min kill task for R1.
- config.example.json: `{discord_ui_enabled: false, ...}`

### Task 11: `windows_runtime/setup/` docs + bootstrap_gmail.py
Four files:
- `OPERATOR_README.md`: step-by-step setup (clone, Python install, install.ps1, DuckDNS, bearer pull, Claude Desktop routine, verify with check.py, ops notes)
- `REQUIRED_VERSIONS.md`: Python >=3.11 <3.13, pywinauto==0.6.x, Playwright >=1.40, Claude Desktop >=1.0 stable
- `GMAIL_SETUP.md`: GCP project, Gmail API, OAuth2 Desktop client for `teche2014@gmail.com`, credentials.json, bootstrap_gmail.py, SCP to VPS
- `bootstrap_gmail.py` (~50 lines): InstalledAppFlow on Windows, writes token.json, prints SCP command

### Task 12: Phase 0a host hardening + systemd unit + Phase 0b bearer token generation
**WARNING: System-level destructive changes. Execute carefully and in order.**
1. `gitleaks detect --source . --log-opts='--all'` — surface findings, DO NOT auto-rotate
2. `chmod 600 /root/.openclaw/.env`
3. Create `openclaw` user: `useradd -r -m -s /bin/bash openclaw`
4. Copy workspace: `cp -r /root/.openclaw /home/openclaw/ && chown -R openclaw:openclaw /home/openclaw/`
5. Update `/etc/systemd/system/consensus-engine.service` — add User=openclaw, hardening directives, update paths to `/home/openclaw/`, only check `gmail/token.json` if the file exists
6. `systemctl daemon-reload`
7. Disable cups: `systemctl disable --now cups cups-browsed 2>/dev/null; apt purge -y cups 2>/dev/null || true`
8. ufw: `ufw default deny incoming; ufw allow 22/tcp; ufw allow 8443/tcp; ufw enable` — VERIFY SSH STILL WORKS
9. SSH hardening: `PermitRootLogin prohibit-password`, `PasswordAuthentication no`; `systemctl reload sshd`
10. `apt install -y fail2ban; systemctl enable --now fail2ban`
11. Generate bearer tokens: `python3 -c 'import secrets; print(secrets.token_hex(32))'` x2, append to `/home/openclaw/.env`
12. Create gmail dirs: `mkdir -p /root/.openclaw/gmail /home/openclaw/gmail; chmod 700 /root/.openclaw/gmail /home/openclaw/gmail`
13. Restart engine, verify green: `systemctl restart consensus-engine && journalctl -u consensus-engine --since "1 min ago" -n 20`

---

## Hard Constraints (must check on every change)

- ZERO edits to: `consensus_engine/alerts/`, `engine.py`, `cross_reference.py`, scoring*, `volume_scanner.py`, `briefing/alfred.py`, `api_adapters.py`, `discord_tweetshift.py`
- Exactly 2 new SourceType values: DESKTOP_AUTH, DESKTOP_LOCAL (already done in Task 1)
- `db.py:783` IN-list: only `'desktop_auth'` added (done), NOT `'desktop_local'`
- Verify: `git diff --stat $(git merge-base HEAD master~5)..HEAD` shows no forbidden files

---

## Operator Inputs Still Needed

1. **DuckDNS subdomain + token** — needed for Phase 0b certbot TLS. Reply format: `subdomain: <name>` and `token: <duckdns-token>`
2. **GCP credentials.json for teche2014@gmail.com** — operator creates GCP project, enables Gmail API, creates OAuth2 Desktop client, downloads credentials.json. Then runs bootstrap_gmail.py on Windows, SCPs token.json to VPS at `/root/.openclaw/gmail/token.json`.
3. **GitHub branch protection** — enable on `master` + `windows-stable` via GitHub UI after push.

---

## How to Resume

Start fresh session and run: `discover: resume local-win-routines-v3`

The discover skill will read state.json (`current_pass: 4, status: ready_for_pass_5`), read EXECUTE.md and this execution log, and continue from Task 6.

**Or paste this into a fresh session directly:**
```
I'm resuming Pass 5 of the local-win-routines-v3 discover run. Tasks 1-5 are complete (commits 616f054 through 5418029 on master). Read /root/.openclaw/workspace/.claude/discover/local-win-routines-v3/pass-5-execution-log.md for full context, then continue with Task 6 (tests/test_ingest_server.py) through Task 12 (host hardening).
```

---

## Files Created/Modified So Far

**New files:**
- `consensus_engine/ingest_server.py` (302 lines)
- `consensus_engine/scanners/gmail_watcher.py` (432 lines)
- `consensus_engine/utils/redacting_filter.py` (43 lines)
- `.pre-commit-config.yaml`

**Modified files:**
- `consensus_engine/models.py` (+2 SourceType values)
- `consensus_engine/db.py` (+5 tables in SCHEMA, +1 IN-list entry, comment)
- `consensus_engine/main.py` (+imports, +2 tasks in run_live, +RedactingFilter install)
- `config/consensus.yaml` (+ingest_server and gmail_watcher blocks)
- `requirements.txt` (+3 google-api deps)
- `.gitignore` (+Windows runtime patterns)
