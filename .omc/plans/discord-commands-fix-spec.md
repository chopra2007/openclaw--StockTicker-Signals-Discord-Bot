# Discord Bot Commands & Mentions: Permanent Fix + 24h Verification

## Execution contract
This spec is executed autonomously in a single session. **No human input is required or expected at any point.** Do not pause for review, approval, or confirmation at any phase boundary. Do not ask questions. The operator will not be present.

**Session startup sequence (execute in this exact order):**
1. Run `ralplan .omc/plans/discord-commands-fix-spec.md` — this produces a Planner/Architect/Critic consensus plan at `.omc/plans/ralplan-*.md`. Wait for it to complete.
2. Immediately run `autopilot` — autopilot detects the ralplan output and skips its own Phases 0–1, jumping directly to Phase 2 (Execution). Continue through QA, validation, and into Phase 3 (24h verification loop) without stopping.

**Single prompt to paste:**
```
ralplan .omc/plans/discord-commands-fix-spec.md && autopilot
```

## Mission
Diagnose and permanently fix recurring failures of `!help` and `@API#8079` mention handling on the consensus-engine bot, then prove stability with a self-healing 24-hour verification loop.

## Hard facts (do not re-derive)
- **Service unit:** `consensus-engine.service` (User=`openclaw`, WorkingDirectory=`/home/openclaw/.openclaw/workspace`).
- **No discord.py.** The bot uses a hand-rolled websocket gateway at `consensus_engine/scanners/discord_tweetshift.py` with intents = GUILDS(1) + GUILD_MESSAGES(512) + MESSAGE_CONTENT(32768) = **33281**.
- **Command dispatch:** `consensus_engine/alerts/commands.py` with `!help` listed in the help text. Mention path strips a leading bot mention before parsing, so `@bot !help` and `!help` both route through the same handler.
- **Reply transport:** `send_command_reply(channel_id, reply_to_msg_id, content)` in `consensus_engine/alerts/discord.py:444` — REST POST to `https://discord.com/api/v10/channels/{channel_id}/messages`.
- **Mention LLM path:** gateway calls `self._on_mention(clean, channel_id, message_id, author_id)` at `discord_tweetshift.py:307`.
- **Recent fix attempts (use as priors):** `c9a06b7` revert session timeout / keep `sock_connect` guard; `ef71591` reconnect hang; `a5fc23b` `!commands` after bot mention.
- **Credentials:** `/root/.openclaw/.env` (root-readable). Service reads `/home/openclaw/.openclaw/.env.service`. **Verify the bot token is in the openclaw-readable env file before doing anything else** — the migration root→openclaw is the most likely root cause class.
- **Test suite:** `python3 -m pytest tests/ -v` (asyncio_mode=auto). Run as the user that owns the venv; do not assume root.
- **State dirs:** `.omc/plans/`, `.omc/logs/`, `.omc/state/sessions/{sessionId}/`. All exist.

## Resume detection
On every session start, check for `.omc/state/discord-24h-verify.json`. If it exists and `iteration > 0`, skip Phases 0–2 entirely and jump to Phase 3 to continue the verification loop.

---

## Phase 0 — Investigation (mandatory; no code edits)

**Run steps 1 and 2 first, sequentially, before doing anything else. If step 1 finds the token missing, fix it immediately (see step 1 action), restart the service, run the smoke test from Phase 2 step 5, and only continue to steps 3–5 if the problem persists.**

1. **Token audit — BLOCKING GATE.**
   - Find the exact env var name the gateway uses: `grep -n "os.environ\|getenv\|os.getenv" consensus_engine/scanners/discord_tweetshift.py`
   - Check the service env file: `sudo -u openclaw grep -c "DISCORD" /home/openclaw/.openclaw/.env.service 2>&1`
   - Check the root env file: `sudo grep "DISCORD" /root/.openclaw/.env 2>&1`
   - **If the token var is absent from `.env.service` but present in `/root/.openclaw/.env`:** copy it — `sudo grep "DISCORD_BOT_TOKEN" /root/.openclaw/.env | sudo -u openclaw tee -a /home/openclaw/.openclaw/.env.service && sudo chmod 0600 /home/openclaw/.openclaw/.env.service` — then restart the service and run the smoke test. If both `!help` and the mention now respond within 30s, this was the entire root cause. Document it, go directly to Phase 2 steps 3–6 (skip the rest of Phase 0).
   - Also verify the runtime can load deps: `sudo -u openclaw -H python3 -c "import websockets, aiohttp; print(websockets.__version__, aiohttp.__version__)"` — if this fails, the venv is not accessible to openclaw; fix the venv path before any other work.

2. **Service health — run immediately after step 1.**
   - `systemctl status consensus-engine.service --no-pager` — note PID, uptime, restart count.
   - `journalctl -u consensus-engine.service --since "24 hours ago" --no-pager | grep -iE 'gateway|mention|command|reconnect|resume|heartbeat|429|401|403|disconnect|exception|traceback' > /tmp/disc_evidence.log`
   - Read `/tmp/disc_evidence.log` in full. Tag each line: `[connect]`, `[auth]`, `[heartbeat]`, `[reconnect]`, `[dispatch]`, `[reply]`, `[exception]`. Cite specific lines when forming hypotheses.

3. **Code read (only if steps 1–2 did not resolve the issue):**
   - `consensus_engine/scanners/discord_tweetshift.py` — gateway loop, intents value, IDENTIFY, RESUME, on_mention dispatch
   - `consensus_engine/alerts/commands.py` lines 1–270 — dispatch table, mention prefix strip, !help handler
   - `consensus_engine/alerts/discord.py` lines 420–510 — `send_command_reply`

4. **Diff last 7 days of Discord-touching changes:**
   - `git log --since="7 days ago" --oneline -- consensus_engine/alerts/ consensus_engine/scanners/discord_tweetshift.py`
   - `git show <sha>` for each. Identify the regression commit vs. the "fix" commit. Look for guards that mask the real issue (e.g. `sock_connect` timeout but no IDENTIFY ack timeout).

5. **Hypothesis list (write at least 4, ranked by evidence weight).** Required candidates if not already resolved:
   - a. Token absent/stale in openclaw env (migration class) — already checked in step 1.
   - b. Intents value drifted; MESSAGE_CONTENT dropped — gateway connects but `data["content"]` arrives empty so prefix `!` never matches.
   - c. `on_mention`/command callback raises and the gateway loop swallows it silently.
   - d. RESUME path reconnects but never re-IDENTIFYs after invalid_session(9), so dispatch silently stops while heartbeats continue (looks healthy in `systemctl status`).
   - e. `send_command_reply` 401/403 due to missing channel permissions.
   - f. Outbound HTTP rate-limited (429) and the reply is dropped without retry.

6. **Decision rule:** do not advance to Phase 1 until at least one hypothesis is supported by a specific log line OR a code-read finding (cite file:line).

---

## Phase 1 — Plan

Write `.omc/plans/discord-fix-plan.md` with these sections in order:
1. **Root cause** — single sentence + evidence (file:line or log timestamp).
2. **Why prior fixes were short-lived** — name the masked symptom.
3. **Patch** — exact diff sketch (file, function, before→after). Surgical only; no adjacent refactors.
4. **Regression guard** — the new test added in Phase 2 that would have caught this.
5. **Rollback** — single git command to revert if the 24h loop fails ≥3 hours.

---

## Phase 2 — Fix

1. Apply the patch. Touch only files justified in the plan.
2. **Add a test** to `tests/` that fails without the fix and passes with it. For gateway logic, add an in-process simulation that feeds a fake MESSAGE_CREATE payload through the dispatch path and asserts `send_command_reply` is invoked. Do not mock so heavily that the test becomes vacuous.
3. `python3 -m pytest tests/ -v -x` — must be green. If a pre-existing unrelated test fails, note it and skip explicitly; do not fix adjacent failures.
4. Restart: `sudo systemctl restart consensus-engine.service`, wait 15s, check `systemctl is-active` plus `journalctl -u consensus-engine.service -n 50 --no-pager` for IDENTIFY/READY confirmation.
5. **Smoke test before declaring fix live:** post `!help` and `@API#8079 ping` to the chat channel using the same REST path used in Phase 3. Both must reply within 30s. If not, return to Phase 0 with the new evidence — do NOT enter the 24h loop on a broken fix.
6. Commit: `fix(discord): <one-line root cause>`. Push immediately. Create a new commit (do not amend).

---

## Phase 3 — 24-Hour Self-Healing Verification

### 3.1 Channel + transport
- Read the chat channel ID from the bot's runtime config: `grep -nE 'CHAT_CHANNEL|chat_channel' config/consensus.yaml /root/.openclaw/sources.json`; verify by checking which channel ID appears in recent reply log lines.
- **Send via the bot's own token** using the same REST endpoint as `send_command_reply`: `POST https://discord.com/api/v10/channels/{channel_id}/messages` with header `Authorization: Bot <token>`.
- **Do NOT use the webhook URL in memory for probe sends.** Webhook posts do not trigger the bot's mention handler (Discord only populates `data["mentions"]` for real user/bot messages, not webhook posts). Use bot token for both probe sends.
- **Detect a response** by polling `GET /channels/{channel_id}/messages?after={probe_message_id}&limit=20` every 3s for up to 60s. Match by `message_reference.message_id == probe_message_id` (command replies) OR by `author.id == BOT_USER_ID` arriving within 60s after the probe (mentions).

### 3.2 Driver
- Implementation: `scripts/discord_24h_verify.py` (new). Pure Python, stdlib + aiohttp. ~120 lines max.
- The script does **one hour's check** per invocation (`--once`) and exits:
  - `0` = success
  - `1` = help_timeout
  - `2` = mention_timeout
  - `3` = both
  - `4` = transport_error
- Pacing: the Claude Code session calls `ScheduleWakeup(delaySeconds=3600, prompt="<<continue-discord-24h-verify>>", reason="hourly discord verification check N/24")` at the end of each iteration. The session does **not** sleep inline; it returns and resumes when ScheduleWakeup fires.
- Persist iteration state to `.omc/state/discord-24h-verify.json` (keys: `started_at`, `iteration`, `successes`, `failures[]`, `fixes_applied[]`, `last_fix_signature`).

### 3.3 Each iteration
1. Load state. If `iteration >= 24`, write final report and exit the loop (do not call ScheduleWakeup).
2. Run `scripts/discord_24h_verify.py --once`. Capture exit code + stdout.
3. **Success** → append to `.omc/logs/discord-verification-24h.log` as `ISO_TS iter=N/24 SUCCESS help=Xs mention=Ys`, increment iteration, ScheduleWakeup, return.
4. **Failure** → engage self-heal (3.4), then ScheduleWakeup, return.

### 3.4 Self-heal logic (bounded)
On failure:
1. Capture `journalctl -u consensus-engine.service --since "10 minutes ago" --no-pager > .omc/logs/discord-fail-iter-N.log`.
2. Classify into: `gateway_disconnect`, `auth_401`, `auth_403`, `dispatch_silent` (gateway up, no command log line), `reply_failed` (handler logged but no Discord message), `unknown`.
3. **Fix-approach registry** — ordered remediations per class; pick the next un-tried one:
   - `gateway_disconnect`: restart service → clear gateway resume_url cache → force fresh IDENTIFY
   - `auth_401`: re-read token from env → re-deploy `.env.service` → halt (token regeneration is manual)
   - `auth_403`: halt loop with instructions (permission edits are out of scope for autonomous fix)
   - `dispatch_silent`: restart service → if recurs: bisect last 5 commits touching alerts/scanners and revert the suspect one
   - `reply_failed`: check 429 backoff in logs → restart service
   - `unknown`: restart service → if recurs: write diagnostic dump and halt loop
4. Apply the chosen remediation. Record signature `<class>:<remediation>` in `last_fix_signature`. Append to `fixes_applied`.
5. **Hard stops:**
   - Same `<class>:<remediation>` tried twice → escalate to next remediation in the class list.
   - Same class fails 3 iterations in a row → halt loop, write `HALTED reason=class_3x` to log, do not ScheduleWakeup. Surface halt in final message.
   - Any remediation marked "halt" → halt immediately.
   - Total `fixes_applied` across run > 8 → halt; the architecture is wrong, not the symptom.
6. After applying a fix, wait 30s, re-run `--once` immediately (counts as the same iteration's result, not N+1). Only one re-run per hour.

---

## Definition of Done
1. `tests/` includes a regression test that fails on pre-fix HEAD and passes on post-fix HEAD. Verified by running against `git stash` of the patch.
2. Service has been continuously connected (no restart-due-to-failure) since the fix commit.
3. `.omc/logs/discord-verification-24h.log` contains exactly 24 iteration lines. ≥22 must be SUCCESS. Every FAILURE line has a paired `iter=N fix=<class>:<remediation>` entry.
4. If the loop halted early, the halt reason is logged AND the final message states: "Halted at iter=N, reason=X, manual action required: Y."
5. Fix commit and 24h script pushed to `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` as separate commits (so each can be reverted independently).

---

## Anti-patterns (do not do)
- Do not add try/except around the gateway recv loop "to be safe" — that is exactly the masking pattern that made prior fixes short-lived.
- Do not extend timeouts as a fix. If a timeout fires, the symptom is downstream of a real failure.
- Do not introduce discord.py. The custom gateway is intentional.
- Do not edit `consensus.yaml` thresholds, alert logic, or any non-Discord file.
- Do not run the 24h loop against a webhook or with `--dry-run` — both bypass the failure mode under test.

## Files referenced
- `consensus_engine/scanners/discord_tweetshift.py` — gateway URL + intents, mention dispatch
- `consensus_engine/alerts/commands.py` — dispatch table, mention prefix strip, !help handler
- `consensus_engine/alerts/discord.py:444` — `send_command_reply` REST path
- `/etc/systemd/system/consensus-engine.service` — User=openclaw, EnvironmentFile path
- `/home/openclaw/.openclaw/.env.service` — service env (openclaw-owned; token must live here)
- `/root/.openclaw/.env` — legacy/root env (read-only reference)
- `.omc/plans/discord-fix-plan.md` — to be created in Phase 1
- `.omc/logs/discord-verification-24h.log` — to be created in Phase 3
- `.omc/state/discord-24h-verify.json` — iteration state for resume
- `scripts/discord_24h_verify.py` — to be created in Phase 3
