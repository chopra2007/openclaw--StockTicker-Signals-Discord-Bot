# RALPLAN — Discord Bot Commands & Mentions Permanent Fix + 24h Verification (Revision 2)

**Mode:** DELIBERATE (high-risk: production Discord bot, autonomous self-heal, service restarts, 24h loop, no human in loop)
**Spec:** `.omc/plans/discord-commands-fix-spec.md` (authoritative)
**Status:** REVISED post Architect review (verdict was `RECOMMEND_REVISE`). Architect's full review is preserved at the end of this document for traceability.

**What changed from rev 1:** the token-migration prior was empirically falsified by Architect evidence (token present, TweetShift tweets flowing, mentions worked end-to-end on 2026-05-06). The real bug is **silent reconnect, hypothesis (d)**: `discord_tweetshift.py:323` `async for msg in ws` exits cleanly on `sock_read=60` timeout (line 318) with no `WS closed`, no `Discord Gateway error`, no log line; the loop then resumes via `_resume()` at line 345 because `_session_id` and `_sequence` are still set, but Discord may have invalidated the session. Heartbeats continue, `systemctl status` looks healthy, dispatch is dead. Journal evidence: 9+ `Reconnecting...` lines, **0** `WS closed`, **0** gateway errors, **1** `READY`. Plan reordered accordingly.

---

## 1. RALPLAN-DR Summary

### Principles
1. **Evidence before fix** — no patch lands without a cited file:line OR specific log timestamp (spec line 67).
2. **Do not mask symptoms** — no try/except wrappers around the gateway recv loop, no timeout extensions (spec lines 149–150). Structured log lines at deterministic exit points are NOT try/except wrappers and are explicitly authorized below.
3. **Surgical changes only** — touch only files justified in the plan; no adjacent refactors (spec line 76).
4. **Bounded autonomy** — every self-heal action carries a stop condition; the loop must halt rather than thrash (spec lines 130–134).
5. **Verifiable end-to-end** — smoke test through the same REST path used in 24h verification before declaring the fix live (spec line 88), AND the smoke test must span the silent-reconnect manifest window.

### Decision Drivers (top 3)
1. **Silent-reconnect direct evidence vs. token prior** — Architect §A counted journal patterns: `Reconnecting × 9, WS closed × 0, Gateway error × 0, READY × 1`. This is hypothesis (d) on a plate. Token presence was already verified (all four `DISCORD_*` vars in `.env.service`); it is no longer a viable primary anchor. Drive: fix the gateway state machine, not the env file.
2. **Smoke-test span vs. ship-fast** — a `systemctl restart` clears in-memory session and produces a 30–60min window where `!help` works regardless of root cause. A 30s smoke test cannot distinguish the real fix from a restart-window placebo. Drive: smoke test must extend to T+30min before the fix is declared live.
3. **Bounded self-heal vs. cleverness** — `bisect_and_revert` on `dispatch_silent` (rev-1 §4) is incompatible with the iteration model: a mid-loop `git revert + restart` produces `gateway_disconnect`-class noise on iteration N+1 and burns the fix budget. Drive: replace with `restart_with_session_clear` then halt with a state-machine diagnostic.

### Hypotheses (reranked, evidence-weighted)

| Rank | Hypothesis | Status | Evidence |
|---|---|---|---|
| **1** | **(d) RESUME-without-IDENTIFY silent reconnect** — gateway reconnects after `async for msg in ws` exits cleanly via `sock_read=60`; loop calls `_resume()` (line 345) on a stale `_session_id`/`_sequence`; Discord silently invalidates dispatch but heartbeats continue. | **CONFIRMED** | Journal: `Reconnecting × 9` since 12:47 service start, `WS closed × 0`, `Gateway error × 0`, `READY × 1`. Code: `discord_tweetshift.py:312-360`, no op:9 handler in `_handle_dispatch` (line 212–218 only handles READY). |
| 2 | **(a) Token-migration class** — token absent or stale in `/home/openclaw/.openclaw/.env.service`. | **REFUTED** | All four `DISCORD_*` vars present; TweetShift tweets logging at 2026-05-07 01:35:31 UTC; `!help` worked at 2026-05-06 02:32:04. Verified again as a parallel cheap check in Step 0.1, but no longer a blocking gate. |
| 3 | **(b) Intents drift / MESSAGE_CONTENT bit flipped** | **REFUTED** | `discord_tweetshift.py:30` is `INTENTS = 1 \| 512 \| 32768 = 33281`; no recent commit touched line 30 (Architect §E.3). |
| 4 | **(c) `on_mention`/command callback raises and the gateway loop swallows it silently** | **DROPPED** | `discord_tweetshift.py:307-309` already wraps `_on_mention` in `try/except Exception, exc_info=True`; 24h journal contains zero `Mention callback error` / `Command callback error` lines (Architect §E.1). Removed from required candidates per Architect §F.8. |
| 5 | **(e) `send_command_reply` 401/403 due to missing channel permissions** | DEFERRED | Halt-class for autonomous fix (spec line 125). If observed, halt with diagnostic. Will become more visible after instrumentation #2 below (response-body capture at `discord.py:465`). |
| 6 | **(f) Outbound HTTP rate-limited (429)** | DEFERRED | Halt-class. Same as (e). |

### Viable Options (core fix approach)

**Option B — Silent-reconnect / RESUME-without-IDENTIFY guard (PRIMARY).**
Patch the gateway so that (1) `op:9 INVALID_SESSION` clears `_session_id` and `_sequence`, forcing IDENTIFY on next connect; (2) when `async for msg in ws` exits without an explicit `CLOSE/ERROR` (i.e., a clean silent exit driven by `sock_read=60`), `_session_id` and `_sequence` are cleared so the next reconnect re-IDENTIFYs instead of RESUMEing on stale state. Add structured log lines at the loop-exit point (`discord_tweetshift.py:362`) and at the REST reply error path (`discord.py:465`) so the failure mode becomes classifiable.
- *Pros:* Addresses the confirmed root cause; matches the symptom of `!help` going dead after the silent reconnect window while heartbeats continue.
- *Cons:* Requires code edit + regression test; risk of introducing a new gateway state machine bug. Mitigated by the regression test (drive op:9 + clean-exit through `_handle_dispatch`/`_connect_once` and assert state cleared).

**Option A — Token-migration repair (cheapest parallel check, NO LONGER A GATE).**
Verify in Step 0.1 that `^DISCORD_BOT_TOKEN=` count is exactly 1 in `.env.service` and bytes match `/root/.openclaw/.env`. Cost is ~5 seconds; if the token is wrong, fix it and `systemctl restart`. Otherwise note as ruled-out and continue to Option B.
- *Pros:* Trivial to verify; if it's wrong it's the cheapest possible fix.
- *Cons:* Architect evidence already shows it's not the root cause; treated as a parallel confirmation, not a primary path.

**Option C — Intents drift.** Refuted (see hypothesis table); listed for completeness only. No action.

**Decision rule (post-Step-0.1):**
- If token absent or count != 1 in `.env.service` → fix Option A first AND continue to Option B (token fix alone is insufficient because journal evidence already implicates silent reconnect).
- If `Reconnecting > 0 AND READY == 1 AND WS closed == 0` from Step 0.1 evidence → silent reconnect confirmed → ship Option B.
- If neither pattern matches → re-classify hypotheses 5/6 with the new evidence and halt if (e)/(f).

### Pre-mortem (3 distinct failure scenarios)

**Scenario 1 — Silent reconnect masquerades as fixed for 30 minutes after `systemctl restart`.**
A clean restart clears `_session_id`/`_sequence` by process exit, so a fresh IDENTIFY happens on next connect. Smoke test at T+15s passes. The bug only manifests after the first `sock_read=60` timeout cycle (typically 30–60 minutes). Mitigation: smoke test fires `!help` at **T+15s, T+5min, T+30min** (Architect §F.6). The T+30min check is the silent-reconnect manifest window; failure there sends us back to Phase 0 with new evidence, NOT into the 24h loop.

**Scenario 2 — False success: probe matches its own echo.**
Bot relays/quotes the probe message and we count that as a reply. Mitigation: spec line 99 — match by `message_reference.message_id == probe_message_id` (true Discord reply pointer) for `!help`; for mentions, require `author.id == BOT_USER_ID` AND posted within 60s after the probe AND `author.id != probe_sender.id` (echo guard).

**Scenario 3 — Self-heal runs `restart_service` repeatedly to cover for the silent-reconnect bug if Option B's patch is incomplete.**
The `dispatch_silent:restart_with_session_clear` row produces a 30–60min "fix window" each time, then the bug recurs at iteration N+1 with the same class. Mitigation: hard stop at attempt 2 of `dispatch_silent` halts the loop with a state-machine diagnostic dump rather than thrashing. The total fix budget (>8) and class-3x rules also bound this.

### Expanded Test Plan

| Layer | Test | Maps to |
|---|---|---|
| **Unit** | `tests/test_discord_dispatch.py` — feed a fake `MESSAGE_CREATE` payload with `content: "!help"` through the gateway dispatch path; assert `send_command_reply` is called with the right channel/reply_to (spec line 85). | Regression guard (spec line 73 §4) |
| **Unit** | Same test with `mentions: [{id: BOT_USER_ID}]` and `content: "<@BOT_USER_ID> ping"`; assert `_on_mention` is called with stripped content. | Mention path (spec line 23) |
| **Unit (state machine)** | Drive `_handle_dispatch` with a synthesized `op:9 INVALID_SESSION` payload (`{"op": 9, "d": false}`); assert `_session_id is None` AND `_sequence is None` after the call. | Option B regression #1 |
| **Unit (state machine)** | Simulate a clean WS exit: invoke `_connect_once`'s post-loop cleanup path with `ws.closed == True` and no preceding `CLOSE/ERROR` frame; assert `_session_id is None` and `_sequence is None` after the helper. | Option B regression #2 |
| **Integration (in-proc)** | Stub websocket feeds HELLO → IDENTIFY-ACK → MESSAGE_CREATE → `op:9` → assert next reconnect calls `_identify`, NOT `_resume`. | End-to-end verification of state-clear |
| **E2E (smoke, multi-window)** | Phase 2 step 5 — POST `!help` + mention via bot REST at **T+15s, T+5min, T+30min**; all six probes must reply within 30s. | Spec line 88 gating + Architect §F.6 |
| **E2E (24h)** | `scripts/discord_24h_verify.py --once` × 24 iterations via ScheduleWakeup. ≥22/24 SUCCESS. | Spec lines 142–143 |
| **Observability** | Each iteration writes `iter=N/24 SUCCESS\|FAILURE help=Xs mention=Ys uptime=<s>` to `.omc/logs/discord-verification-24h.log`; failures pair with `fix=<class>:<remediation>`. The `uptime` field is `seconds_since_active_enter` so a silent restart between hourly probes is visible. | Spec line 142 + Architect §F.7 |
| **Observability** | New log line at `discord_tweetshift.py:362` (loop-exit) and body capture at `discord.py:465` (REST reply error). Both are structured logs, NOT try/except wrappers (spec line 149 still applies; this is instrumentation, not symptom-masking). | Architect §F.5 |
| **Observability** | `.omc/state/discord-24h-verify.json` updated atomically each iteration (write to tmp + rename). | Resume contract |

---

## 2. Execution Plan

### Resume gate (every session start)
0. **Resume check.** If `.omc/state/discord-24h-verify.json` exists AND `iteration > 0` AND `halted == false`, jump directly to Phase 3 step 3.3 (spec line 30). Do NOT re-run Phases 0–2.

### Phase 0 — Investigation (no code edits)

**Step 0.1 — Parallel evidence collection (~30s, single batch). Architect §C synthesis.**
Run all three artifact captures in parallel:

- **(a) Token presence.** `sudo -u openclaw grep -c "^DISCORD_BOT_TOKEN=" /home/openclaw/.openclaw/.env.service` → expect `1`. Also `sudo -u openclaw grep -cE "^DISCORD_(BOT_TOKEN|CHANNEL_ID|FEED_CHANNEL_ID|BRIEFING_CHANNEL_ID)=" /home/openclaw/.openclaw/.env.service` → expect `4`.
- **(b) Journal pattern counts.** `journalctl -u consensus-engine.service --since "24 hours ago" --no-pager | grep -cE 'TweetShift tweet:'` and the same with each of: `'Discord command'`, `'Discord mention'`, `'Reconnecting to Discord Gateway'`, `'Discord Gateway WS closed'`, `'Discord Gateway error'`, `'READY'`. Capture all 7 counts to `/tmp/disc_evidence_journal.log`.
- **(c) Service lifecycle.** `systemctl show -p MainPID -p ActiveEnterTimestamp -p NRestarts consensus-engine.service` → capture to `/tmp/disc_evidence_service.log`.

Success criterion: all three artifacts written.

**Step 0.2 — Decision rule (single deterministic branch).**

- **If (a) shows token absent or count != 1 in `.env.service`:** repair Option A — `sudo -u openclaw grep -c "^DISCORD_BOT_TOKEN=" /home/openclaw/.openclaw/.env.service`; if 0, append from `/root/.openclaw/.env`; if >1, `sed -i` single-line replace; finish with `chmod 0600`; restart service. Then proceed to Option B regardless (journal evidence already implicates silent reconnect; token alone is insufficient).
- **Else if (b) shows `Reconnecting > 0 AND READY == 1 AND WS closed == 0`:** silent-reconnect confirmed → go directly to Option B in Phase 1.
- **Else if `Reconnecting == 0 AND READY > 1`:** the bug is in (e)/(f) territory; halt with diagnostic dump (spec lines 124–125 are halt-class).
- **Else:** unknown pattern; write `/tmp/disc_evidence_unknown.log` with all three artifact contents and halt.

**Step 0.3 — Code-read confirmation (lightweight; cheap to verify Architect's findings).**
Read `discord_tweetshift.py` lines 25–35 (intents value), 156–157 (state init), 212–218 (`_handle_dispatch`), 311–360 (`_connect_once`), 365–390 (`run` loop). Confirm:
- `INTENTS = 1 | 512 | 32768 == 33281` at line 30 (refutes hypothesis (b)).
- `_handle_dispatch` only handles READY at lines 214–218; no op:9 case, no op:7 case (this is the gap Option B fills).
- `_connect_once` exits the `async for` loop at line 360 on CLOSE/ERROR with a `log.warning`, but the loop also exits naturally when no message arrives within `sock_read=60` (line 318) with NO log line — that is the silent-exit code path Option B must instrument and fix.

Success criterion: each of the three confirmations checked, evidence cited as file:line in the Phase 1 plan.

**Step 0.4 — Diff last 7 days of Discord-touching changes (per spec line 56).**
`git log --since="7 days ago" --oneline -- consensus_engine/alerts/ consensus_engine/scanners/discord_tweetshift.py`. Known priors: `c9a06b7`, `ef71591`, `a5fc23b` (spec line 24). Identify which prior introduced the silent-reconnect path or which "fix" masked it. The two recent reconnect-related commits (`ef71591` reconnect hang, `c9a06b7` revert session timeout) are the likely site of the regression; we do NOT revert them — Option B layers on top.

**Step 0.5 — Phase 0 exit.**
Write the evidence summary (counts + decision branch taken) to `.omc/plans/discord-fix-plan.md` Section 1 (Root cause + evidence) before any Phase 2 code edit.

### Phase 1 — Plan

**Step 1.1 — Write `.omc/plans/discord-fix-plan.md`** with these 5 sections in spec order:

1. **Root cause.** "Silent reconnect: `_connect_once` exits the `async for` loop at `discord_tweetshift.py:323` when no gateway frame arrives within `sock_read=60` (line 318), without producing a `CLOSE/ERROR` frame and without logging. The outer `run` loop (line 379) reconnects via `_resume()` (line 345) on stale `_session_id`/`_sequence`. Discord silently treats the session as invalidated; heartbeats continue but `MESSAGE_CREATE` events are not dispatched. There is no `op:9 INVALID_SESSION` handler in `_handle_dispatch` (lines 212–218)." Evidence: journal `Reconnecting × 9, WS closed × 0, Gateway error × 0, READY × 1` since service start at 12:47.
2. **Why prior fixes were short-lived.** `c9a06b7` removed a session timeout that, while imperfect, would have surfaced silent reconnects. `ef71591` added a `sock_connect=30` guard which is unrelated to the read-loop silence. Neither addresses the missing `op:9` handler or the silent-exit RESUME path. The masked symptom is "service appears healthy because heartbeats continue."
3. **Patch (exact diff sketch).** See §2.1 below for the file:line shape.
4. **Regression guard.** Two new test cases (state-machine unit tests in §1 expanded test plan) that fail on pre-fix HEAD and pass post-fix. Verified via `git stash` of the patch.
5. **Rollback.** `git revert <fix_commit_sha>` for the code patch; for the env file (if Option A also engaged), restore the pre-edit backup `.env.service.bak` taken before any Step 0.2 mutation.

### Phase 2 — Fix

**Step 2.1 — Apply the Option B patch (surgical, three files maximum).**

**File 1: `consensus_engine/scanners/discord_tweetshift.py` — three additions, no removals.**

*Addition (a): opcode constant.* After line 34 (`OP_HEARTBEAT = 1`), add the line:
```python
OP_INVALID_SESSION = 9
```
Place alongside the other `OP_*` constants in the same block (lines 33–34 area).

*Addition (b): op:9 handler in `_handle_dispatch` flow.* The current dispatch routing in `_connect_once` (lines 349–356) handles `OP_DISPATCH`, `OP_HEARTBEAT`, `OP_HEARTBEAT_ACK`. Add a new branch alongside these (NOT inside `_handle_dispatch`, which is event-name-routed and only handles `OP_DISPATCH` payloads):
```python
elif op == OP_INVALID_SESSION:
    # Discord told us the session is dead. Force fresh IDENTIFY on next connect.
    log.warning("Gateway INVALID_SESSION received (resumable=%s); clearing session state for fresh IDENTIFY", data)
    self._session_id = None
    self._sequence = None
    await ws.close()
    break
```
This sits in the `op == ...` chain in `_connect_once`, between the existing `OP_HEARTBEAT_ACK` branch (line 355–356) and the `WSMsgType.CLOSE/ERROR` branch (line 358–360). The `await ws.close(); break` pair drops out of `async for msg in ws` so the outer `run` loop reconnects.

*Addition (c): silent-exit detection at `_connect_once` cleanup.* Replace lines 362–363:
```python
                if hb_task:
                    hb_task.cancel()
```
with:
```python
                # Capture loop exit state BEFORE cancelling heartbeat (instrumentation, not try/except).
                exit_close_code = getattr(ws, "close_code", None)
                exit_was_clean_silent = ws.closed and exit_close_code is None
                log.info(
                    "Gateway loop exited (last_op=%s, last_event=%s, ws_closed=%s, close_code=%s, clean_silent=%s)",
                    op if 'op' in locals() else None,
                    event if 'event' in locals() else None,
                    ws.closed,
                    exit_close_code,
                    exit_was_clean_silent,
                )
                if exit_was_clean_silent:
                    # Silent exit (sock_read=60 timeout, no CLOSE/ERROR frame).
                    # RESUME on stale state is what produces the dispatch-silent failure mode.
                    # Force IDENTIFY on the next reconnect by clearing session state.
                    log.warning("Gateway silent exit detected; clearing session state to force IDENTIFY on reconnect")
                    self._session_id = None
                    self._sequence = None
                if hb_task:
                    hb_task.cancel()
```
The `log.info(...)` line satisfies Architect §F.5 instrumentation and is explicitly NOT a try/except wrapper around the recv loop (spec line 149 still applies). It runs only after the loop exits, on the deterministic cleanup path that already existed.

**File 2: `consensus_engine/alerts/discord.py` — one addition for response-body capture (Architect §E.4 / §F.5).**

Replace lines 464–466:
```python
            if resp.status not in (200, 201):
                log.warning("Command reply failed: %d", resp.status)
                return None
```
with:
```python
            if resp.status not in (200, 201):
                error_body = await resp.text()
                log.warning("Command reply failed: status=%d body=%.500s", resp.status, error_body)
                return None
```
Single structured log enrichment; surfaces 401/403/429 detail so hypotheses (e)/(f) become classifiable.

**File 3 (NONE).** No changes to `consensus_engine/alerts/commands.py` — its dispatch logic is correct (Architect §E.6 confirmed listener wiring at `consensus_engine/main.py:515-516`); the failure is upstream in the gateway.

**Anti-pattern check (explicit):** None of these three additions wraps the gateway recv loop in try/except. The `log.info` at the cleanup path runs after `async for msg in ws` already returned naturally. The op:9 handler is a normal opcode branch alongside existing branches. The `discord.py` change captures an existing aiohttp response body. Spec line 149 is honored.

**Step 2.2 — Add regression tests (state machine — Architect's mandate).**
New file `tests/test_discord_silent_reconnect_regression.py` with two test cases. Both must FAIL on pre-fix HEAD when verified by `git stash` (spec line 140) and PASS post-fix.

Test 1 — `test_op9_invalid_session_clears_state`: instantiate the gateway listener; set `_session_id = "stale_sid"` and `_sequence = 42` directly. Drive a synthetic `op:9` payload through the same code path used in `_connect_once`'s `op == OP_INVALID_SESSION` branch (extract that branch's body into a small helper `_handle_invalid_session(self, data)` if needed for testability, OR call `_connect_once` against an asyncio-mocked WS that yields a single `op:9` text frame and then closes). Assert `_session_id is None` AND `_sequence is None` post-call.

Test 2 — `test_clean_silent_exit_clears_state`: simulate the `sock_read=60` timeout by feeding an aiomock WS that yields no frames and then has `closed=True, close_code=None`. Run `_connect_once` against it. Assert `_session_id` and `_sequence` are cleared after the call returns. Pre-fix HEAD lacks the new cleanup block, so the test fails (state remains stale).

Test guidance per spec line 85: do NOT mock `_session_id`/`_sequence` setters; let the real attributes mutate. The assertion is load-bearing.

**Step 2.3 — Run test suite.** `python3 -m pytest tests/ -v -x`. Must be green. If a pre-existing unrelated test fails, mark with `pytest.mark.skip(reason="<unrelated>: pre-existing as of <commit>")` and do not fix adjacent failures (spec line 86).
- Evidence: pytest output saved to `.omc/logs/discord-fix-pytest.log`.

**Step 2.4 — Restart and verify gateway up.** `sudo systemctl restart consensus-engine.service && sleep 15 && systemctl is-active consensus-engine.service && journalctl -u consensus-engine.service -n 100 --no-pager`. Assert IDENTIFY/READY in journal (spec line 87).
- Evidence: journal slice to `.omc/logs/discord-fix-restart.log`.

**Step 2.5 — Multi-window smoke test (GATING; spec line 88 + Architect §F.6).**

The smoke test fires probes at three time offsets from service-start: **T+15s, T+5min, T+30min**. Each window posts BOTH `!help` and `<@BOT_USER_ID> ping` to the chat channel via `POST /api/v10/channels/{channel_id}/messages` with `Authorization: Bot <token>`. For each probe:

- Capture probe `message_id` from the POST response.
- Poll `GET /channels/{channel_id}/messages?after={probe_message_id}&limit=20` every 3s up to 30s.
- For `!help`: match by `message_reference.message_id == probe_message_id`.
- For mention: match by `author.id == BOT_USER_ID` AND posted after probe AND `author.id != probe_sender.id` (echo guard, pre-mortem #2).

**Success criterion:** all 6 probes (2 messages × 3 windows) reply within 30s of being sent. The T+30min window is the silent-reconnect manifest window — passing here proves the fix is real, not a restart-window artifact.

**Failure paths:**
- T+15s fails: fix is broken; return to Phase 0 step 0.2 with new evidence; do NOT enter Phase 3.
- T+5min passes but T+30min fails: fix is illusory (restart-window placebo); return to Phase 0 step 0.2 with new evidence; do NOT enter Phase 3.

The smoke test may pause real autopilot work for ~30 minutes; that pause is required by the hypothesis.

**Step 2.6 — Commit + push.** `git add` justified files only (`consensus_engine/scanners/discord_tweetshift.py`, `consensus_engine/alerts/discord.py`, `tests/test_discord_silent_reconnect_regression.py`); `git commit -m "fix(discord): clear gateway session on op:9 + silent ws exit"`; `git push`. New commit, do not amend (spec line 89). The 24h driver script lands as a separate commit in Phase 3 (spec line 144).

### Phase 3 — 24-Hour Self-Healing Verification

**Step 3.1 — Channel + transport identification.**
- Action: `grep -nE 'CHAT_CHANNEL|chat_channel|discord_channel_id' config/consensus.yaml`. Confirmed: `config/consensus.yaml:13 → discord_channel_id: "$DISCORD_CHANNEL_ID"`. Resolve via env at runtime.
- Verify by checking which channel ID appears in recent reply log lines: `journalctl -u consensus-engine.service --since "1 hour ago" | grep -oE 'channel_id=[0-9]+' | sort -u`.
- Success criterion: single channel id resolved consistently from config + log evidence.
- Send via bot REST (spec line 97). Do NOT use webhook (spec line 98 — webhook posts don't trigger the bot's mention handler).

**Step 3.2 — Build the driver `scripts/discord_24h_verify.py`.**
- Pure Python, stdlib + aiohttp + python-dotenv, ~120 lines (spec line 102).
- `--once` mode: post probes, poll for replies, exit 0/1/2/3/4 (success / help_timeout / mention_timeout / both / transport_error) (spec line 105).
- BOT_USER_ID resolution: at startup, GET `https://discord.com/api/v10/users/@me` with `Authorization: Bot <token>` → `data["id"]`. Cache module-level. (See §6 OQ-1.)
- Echo guard (pre-mortem #2): reject messages where `author.id == probe_sender.id`.
- Channel ID: read from env `$DISCORD_CHANNEL_ID` (loaded via `dotenv.load_dotenv("/home/openclaw/.openclaw/.env.service")` at startup; see §6 OQ-6).
- **Service uptime capture (Architect §F.7):** at the start of each `--once` invocation, run `systemctl show -p ActiveEnterTimestamp consensus-engine.service` and compute `uptime_s = now() - ActiveEnterTimestamp`. Print on the success/failure stdout line so the per-iteration logger can include `uptime=<s>`.

**Step 3.3 — Per-iteration loop driver (Claude session, NOT a Python daemon).**
- Load `.omc/state/discord-24h-verify.json`.
- If `iteration >= 24`: write final report to `.omc/logs/discord-verification-24h.log`, do NOT call ScheduleWakeup, exit (spec line 113).
- Run `scripts/discord_24h_verify.py --once`, capture exit code + stdout (stdout includes the `uptime_s` value from §3.2).
- Success (exit 0): append `ISO_TS iter=N/24 SUCCESS help=Xs mention=Ys uptime=Zs` to log; bump iteration; ScheduleWakeup(3600s, prompt=`<<continue-discord-24h-verify>>`); return.
- Failure (exit 1/2/3/4): append `ISO_TS iter=N/24 FAILURE class=<...> uptime=Zs` to log; engage self-heal §3.4; ScheduleWakeup unless halted; return.
- Evidence: per-iteration line in `.omc/logs/discord-verification-24h.log`; per-failure dump in `.omc/logs/discord-fail-iter-N.log`.

**Why uptime matters:** if `uptime=Zs` shrinks suddenly between iteration N (e.g., uptime=48000) and N+1 (uptime=300), a silent restart happened between probes — visible in the log without re-querying journal.

**Step 3.4 — Self-heal engagement (see §4 table for full rules).**
On failure: capture `journalctl -u consensus-engine.service --since "10 minutes ago" --no-pager > .omc/logs/discord-fail-iter-N.log`; classify; pick next un-tried remediation from registry; apply; record `last_fix_signature = <class>:<remediation>` and append to `fixes_applied`; wait 30s; re-run `--once` (only one re-run per hour, counts as same iteration result, spec line 135).

---

## 3. State & Resume Contract

### Schema for `.omc/state/discord-24h-verify.json`

```json
{
  "started_at": "2026-05-07T14:00:00Z",
  "iteration": 0,
  "successes": 0,
  "failures": [
    {"iter": 3, "ts": "...", "exit_code": 1, "class": "dispatch_silent", "uptime_s": 48123}
  ],
  "fixes_applied": [
    {"iter": 3, "class": "dispatch_silent", "remediation": "restart_with_session_clear", "signature": "dispatch_silent:restart_with_session_clear"}
  ],
  "last_fix_signature": "dispatch_silent:restart_with_session_clear",
  "halted": false,
  "halt_reason": null
}
```

**Defaults (on first write):** `iteration=0`, `successes=0`, `failures=[]`, `fixes_applied=[]`, `last_fix_signature=null`, `halted=false`, `halt_reason=null`.

**Atomicity:** always write to `.omc/state/discord-24h-verify.json.tmp` then `os.rename` over the target (avoids partial state on crash).

### Resume rules (spec line 30)
- **If file does not exist:** start at Phase 0 step 0.1.
- **If file exists AND `iteration == 0` AND `halted == false`:** Phase 0/1/2 either incomplete or in progress; resume Phase 0 step 0.1 (idempotent; token check is a no-op when env file is correct).
- **If file exists AND `iteration > 0` AND `halted == false`:** skip Phases 0–2 entirely; jump to Phase 3 step 3.3.
- **If file exists AND `halted == true`:** do NOT restart the loop; emit halt-status message, exit. Manual intervention required.

### ScheduleWakeup contract
- **Call:** `ScheduleWakeup(delaySeconds=3600, prompt="<<continue-discord-24h-verify>>", reason="hourly discord verification check N/24")` at the END of each iteration that is not the final one (spec line 109).
- **Do NOT call ScheduleWakeup when:**
  - `iteration >= 24` (final iteration; spec line 113).
  - `halted == true` (any halt condition triggered in §4).
  - Inside the 30s post-fix re-run window (single re-run per hour, counted as same iteration; spec line 135).

---

## 4. Self-heal Decision Table

Pick the first row matching `(failure_class, attempt_number)` where `attempt_number` counts repetitions of that class in the run. Signatures de-dupe within a class to force escalation (spec line 131).

| failure_class | attempt # in run | remediation | next action / hard stop |
|---|---|---|---|
| `gateway_disconnect` | 1 | restart_service (clears in-memory `_resume_url`/`_session_id` because the process exits; next connect issues fresh IDENTIFY by construction) | wait 30s, re-run `--once` |
| `gateway_disconnect` | 2 | **HALT loop, reason=gateway_disconnect_persists.** Capture `journalctl -u consensus-engine --since "10 minutes ago"` to `.omc/logs/discord-gateway-evidence-iter-N.log`. Rationale: in the current code path `restart_service` already discards both `_resume_url` and `_session_id`, so spec line 126's three remediations collapse to one primitive; halting is honest. | halt |
| `auth_401` | 1 | re_read_env (`systemctl daemon-reload && systemctl restart`) | wait 30s, re-run `--once` |
| `auth_401` | 2 | redeploy_env_service (re-copy `DISCORD_BOT_TOKEN` from `/root/.openclaw/.env`, chmod 0600, restart) | wait 30s, re-run `--once` |
| `auth_401` | 3 | **HALT** (token regeneration is manual; spec line 124) | halt, surface manual action |
| `auth_403` | 1 | **HALT immediately** (permissions out of scope; spec line 125) | halt, message: "channel permission edit required" |
| `dispatch_silent` | 1 | **restart_with_session_clear** — `sudo systemctl restart consensus-engine.service` (process exit clears `_session_id`/`_sequence`; next connect IDENTIFYs). The Option B patch should make this self-correct without restart, so a `dispatch_silent` failure post-fix indicates the patch is incomplete. | wait 30s, re-run `--once` |
| `dispatch_silent` | 2 | **HALT_with_state_machine_diagnostic** — write `.omc/logs/discord-state-machine-dump-iter-N.log` containing: last 30min of journal grepped for `Gateway loop exited`, `INVALID_SESSION`, `Reconnecting`; full state file; `git log -5 --oneline` on `consensus_engine/scanners/discord_tweetshift.py`. Halt with manual-action message: "Option B patch is incomplete; review state machine dump." | halt |
| `reply_failed` | 1 | check_429_backoff (grep journal for `429` and the new `Command reply failed: status=` enriched logs from `discord.py:465`; if 429 present, sleep until reset header + 5s buffer) | wait, re-run `--once` |
| `reply_failed` | 2 | restart_service | wait 30s, re-run `--once` |
| `reply_failed` | 3 | **HALT loop, reason=class_3x** | halt |
| `unknown` | 1 | restart_service | wait 30s, re-run `--once` |
| `unknown` | 2 | diagnostic_dump (write `.omc/logs/discord-unknown-dump-N.log` with full journal + `ps -ef \| grep consensus`) → **HALT** | halt |

### Global hard stops (always-on, override the table)
- **Same `<class>:<remediation>` signature tried twice across the run → escalate to the next remediation in that class.** If no next remediation exists, HALT (spec line 131).
- **Same class fails 3 iterations in a row (any remediations) → HALT, reason=class_3x.** Do NOT ScheduleWakeup. Write halt to log (spec line 132).
- **Total `len(fixes_applied) > 8` across run → HALT, reason=fix_budget_exceeded.** "Architecture is wrong, not the symptom" (spec line 134).
- **Any remediation labeled HALT → halt immediately.** Surface manual action message. (spec line 133.)

### Bisect-and-revert is NOT in this table (Architect §B Tension 2).
The rev-1 `dispatch_silent:bisect_and_revert` row is removed. A mid-loop `git revert + restart` produces `gateway_disconnect`-class noise on iteration N+1 and burns the fix budget on the bisect's fallout. If `dispatch_silent` recurs after Option B, the right answer is to halt and inspect the state machine dump rather than guess at a commit to revert.

---

## 5. ADR (Architecture Decision Record)

### Decision
**Ship Option B (silent-reconnect / RESUME-without-IDENTIFY guard) as the primary fix.** Option A (token repair) runs as a parallel cheap check in Phase 0 Step 0.1; if the token is wrong it gets fixed, but the journal evidence already implicates silent reconnect, so the patch lands regardless. The smoke test gates entry to Phase 3 with a multi-window probe (T+15s, T+5min, T+30min) to defeat the restart-window placebo. Self-heal is bounded by the §4 table; bisect-and-revert is removed.

### Drivers (top 3)
1. **Direct journal evidence for hypothesis (d):** `Reconnecting × 9, WS closed × 0, Gateway error × 0, READY × 1`. This is silent reconnect on a plate.
2. **Restart-window placebo defeat:** a `systemctl restart` clears in-memory session state, so the bug only manifests after the first `sock_read=60` timeout (≥30min). The smoke test must span that window or it ships the wrong fix.
3. **Bounded self-heal that halts honestly:** every class has at most two remediations; bisect-and-revert is gone. Three-strikes-per-class and total-fix-budget both halt the loop rather than thrash.

### Alternatives considered
- **Apply Option A (token repair) as a blocking gate.** *Rejected:* journal evidence falsifies the prior. Token grep counts already show all `DISCORD_*` vars present; the bot's recent successful `!help` and mentions on 2026-05-06 confirm the token works.
- **Wrap the gateway recv loop in try/except as a defensive measure.** *Rejected by spec line 149* — masks the real failure. The structured log line at the post-loop cleanup point is NOT a try/except wrapper; it runs after `async for msg in ws` already returned.
- **Extend timeouts (e.g. raise `sock_read` from 60s).** *Rejected by spec line 150* — symptom hiding. The fix is to detect silent exit and re-IDENTIFY, not to mask the timeout.
- **`bisect_and_revert` as a self-heal remediation.** *Rejected per Architect §B Tension 2:* a mid-loop revert+restart produces `gateway_disconnect`-class noise on iteration N+1 and burns budget on its own fallout.
- **Use webhook for probe sends in Phase 3.** *Rejected by spec line 98* — webhook posts don't trigger the bot's mention handler.
- **Run the 24h loop as a Python daemon.** *Rejected:* Claude session + ScheduleWakeup is the spec's resume model (spec line 109); daemon mode doesn't survive session restarts.
- **Migrate to discord.py.** *Rejected by spec line 151* — custom gateway is intentional.

### Why chosen
Matches the spec's evidence-first principle (spec line 67): the journal pattern directly identifies the failure mode, the code-read at `discord_tweetshift.py:212-218, 311-360` confirms the missing op:9 handler and the silent-exit RESUME path. The patch is surgical (three additions in two files, no removals, no recv-loop wrappers) and the regression tests are load-bearing (state machine assertions on `_session_id`/`_sequence`).

### Consequences

**Good:**
- Addresses the confirmed root cause directly; not a symptom mask.
- Two structured log lines make failure modes (silent exit, REST 401/403/429) classifiable for the future without try/except wrapping.
- Smoke test multi-window defeats the restart placebo before the 24h loop starts.
- Bounded self-heal cannot thrash beyond 8 total fixes or 2 same-class failures (tighter than rev 1).
- Per-iteration uptime visibility makes silent restarts between probes obvious.
- Per-commit independent rollbackability (fix commit and 24h script as separate commits, spec line 144).

**Bad / risks:**
- The 30-minute smoke test window adds clock time before Phase 3 starts. Acceptable: shipping a fix that survives only 60s wastes 24 hours of Phase 3.
- The op:9 handler relies on Discord actually sending op:9 when the session is invalidated. If Discord silently drops the connection without sending op:9 (which is what the journal suggests is happening), only the silent-exit clean-up path will fire. Both paths are patched, so coverage is complete; but if a third state exists (e.g., heartbeat ACK gap) it won't be covered. Mitigation: instrumentation log line at line 362 will surface that case in the journal for follow-up.
- The 24h loop depends on ScheduleWakeup firing reliably; if the harness misses a wakeup the loop pauses (acceptable; spec doesn't require continuous wall-clock coverage, just 24 iterations).

### Follow-ups (deferred)
- Slash commands migration (out of scope; spec is `!`-prefix + mention only).
- Rate-limit smoothing / 429 retry-with-backoff library (out of scope; halt on 429-driven `reply_failed` after 2 attempts).
- DM support (out of scope).
- Observability dashboards (out of scope; logs + state file are sufficient).
- Heartbeat ACK gap detection (a third potential silent-failure path not covered by Option B; surface only if the new instrumentation log shows it).

---

## 6. Open Questions (with default resolutions)

**OQ-1: BOT_USER_ID detection — `/users/@me` at startup vs. hard-coded.**
- *Resolution:* GET `https://discord.com/api/v10/users/@me` with the bot token at script startup, cache in a module-level constant per process. Why: spec gives no hard-coded id; deriving avoids stale-id bugs on token rotation. If the call errors or returns non-200, exit 4 (transport_error) for that iteration. There is one code path, not two: a broken `/users/@me` call is itself diagnostic evidence that the auth path is wrong, which is what the self-heal table classifies as `auth_401`.

**OQ-2: Probe content — what to send for `!help` and the mention probe?**
- *`!help`:* literal string `!help` (matches the dispatch table directly; spec line 21).
- *Mention:* `<@BOT_USER_ID> ping` — uses literal Discord mention markup so `data["mentions"]` is populated. Short, low-noise, not a registered command (routes through `_on_mention`). Avoids alert noise: `!help` and `ping` are not ticker queries.
- *Echo guard:* exclude any matching message whose `author.id == probe_sender.id`.

**OQ-3: Test channel ID — single source.**
- *Resolution:* read from env `$DISCORD_CHANNEL_ID` (resolved by `consensus.yaml:13`); same channel as production replies. Probing a different channel does not exercise the live failure mode (spec line 96 says verify by checking which channel ID appears in recent reply log lines). One source of truth.

**OQ-4: Smoke test failure → return to Phase 0 vs. halt with diagnostic?**
- *Resolution:* spec line 88 says "return to Phase 0 with the new evidence — do NOT enter the 24h loop." Treat as a Phase 0 re-entry: bump a counter `smoke_retry_count` in state; if this reaches 2 without resolution, write a halt diagnostic and stop (autonomous loop should not iterate Phase 0 forever).
- *Diagnostic on hard-halt:* dump `/tmp/disc_evidence*.log`, `journalctl --since "30 minutes ago"`, current git HEAD, and the last hypothesis list to `.omc/logs/discord-smoke-halt.log`.

**OQ-5: How to confirm the regression test fails on pre-fix HEAD (spec line 140)?**
- *Resolution:* after Phase 2 step 2.3 (green test suite on post-fix), `git stash push -- consensus_engine/scanners/discord_tweetshift.py consensus_engine/alerts/discord.py tests/test_discord_silent_reconnect_regression.py`, then `pytest tests/test_discord_silent_reconnect_regression.py -v` — must FAIL. `git stash pop` to restore. Capture output to `.omc/logs/discord-regression-prove.log`.

**OQ-6: Driver env loading — how does `scripts/discord_24h_verify.py` see `$DISCORD_BOT_TOKEN` and `$DISCORD_CHANNEL_ID`?**
- *Resolution:* the driver reads both keys from `/home/openclaw/.openclaw/.env.service` directly using `dotenv.load_dotenv("/home/openclaw/.openclaw/.env.service")` at startup. Single code path. The autopilot session invokes the script as `sudo -u openclaw -H python3 scripts/discord_24h_verify.py --once`; the driver does its own env file load so it does not depend on whichever shell launched it. Same env file as the systemd unit, so driver and production service see exactly the same token and channel.

**OQ-7 (NEW): Smoke-test pause — does T+30min waiting block the autopilot session?**
- *Resolution:* yes, by design. The session uses `asyncio.sleep(1800)` (30 minutes) between the T+5min probe and the T+30min probe. This is not a self-heal action; it is part of the gating smoke test (spec line 88 says "do NOT enter the 24h loop on a broken fix"). Alternative — using ScheduleWakeup for the 30min wait — was considered and rejected because it commingles smoke-test gating with the Phase 3 wakeup contract. Smoke-test is a Phase 2 concern; wakeups are a Phase 3 concern; they stay separate.

---

## Files this plan creates / modifies

- **Creates:** `.omc/plans/discord-fix-plan.md` (Phase 1), `tests/test_discord_silent_reconnect_regression.py` (Phase 2), `scripts/discord_24h_verify.py` (Phase 3), `.omc/state/discord-24h-verify.json` (Phase 3), `.omc/logs/discord-verification-24h.log` (Phase 3), `.omc/logs/discord-fail-iter-*.log` (on failure), `.omc/logs/discord-fix-pytest.log`, `.omc/logs/discord-fix-restart.log`, `.omc/logs/discord-regression-prove.log`, `.omc/logs/discord-state-machine-dump-iter-*.log` (on `dispatch_silent` halt).
- **Modifies (Option B, primary path):**
  - `consensus_engine/scanners/discord_tweetshift.py` — add `OP_INVALID_SESSION = 9` constant; add `op == OP_INVALID_SESSION` branch in `_connect_once` opcode chain; add silent-exit detection + log + state clear at the post-loop cleanup at line 362.
  - `consensus_engine/alerts/discord.py` — capture response body in `send_command_reply` 401/403/429 path at line 464–466.
- **Modifies (Option A, only if Step 0.1 token grep fails):** `/home/openclaw/.openclaw/.env.service` — single-line `DISCORD_BOT_TOKEN=` repair.

---

## Definition of Done (per spec lines 139–144)
1. Regression test fails on pre-fix HEAD, passes on post-fix HEAD (verified via `git stash`).
2. Service continuously connected since fix commit (no failure-driven restarts in journal).
3. `.omc/logs/discord-verification-24h.log` has exactly 24 iteration lines with `uptime=Zs` per line; ≥22 SUCCESS; every FAILURE paired with `iter=N fix=<class>:<remediation>`.
4. If halted early: halt reason logged AND final message: "Halted at iter=N, reason=X, manual action required: Y."
5. Fix commit and 24h script pushed as **separate commits** to `chopra2007/openclaw--StockTicker-Signals-Discord-Bot`.

---

## Architect Review (preserved verbatim from rev 1)

**Mode:** DELIBERATE — high-risk autonomous loop, production bot, no human in the loop.

### A. Steelman antithesis (against Option A as Phase-0 blocking gate)

The token-migration hypothesis is empirically falsified by 30 seconds of evidence collection: all four `DISCORD_*` vars are present in `/home/openclaw/.openclaw/.env.service` (verified by direct `grep -E "^DISCORD"`); `TweetShift tweet:` is logging at 2026-05-07 01:35:31 UTC; mentions and `!help` worked end-to-end on 2026-05-06 02:32:04 (`Discord command: !help [] (user=...)`) and 02:43:45-02:50:38 (six consecutive `Discord mention in channel=...` lines from a real user). **The token works.**

**The real bug is silent reconnect, hypothesis (d).** `discord_tweetshift.py:323-360` reads `sock_read=60` from line 318. When no gateway frame arrives in 60s, `async for msg in ws` exits cleanly with no `WSMsgType.CLOSE/ERROR`, no exception caught at line 382, no log. The loop reconnects via `_resume()` at line 345 because `_session_id` and `_sequence` are still set — but Discord may have invalidated the session, and the code has no `INVALID_SESSION` (op 9) handler. The bot heartbeats successfully and looks healthy in `systemctl status`, but `MESSAGE_CREATE` events for command/briefing channels never resume. **Evidence:** journal contains 9+ `Reconnecting to Discord Gateway in 120s...` lines since 12:47 service start with **zero `Discord Gateway WS closed`** warnings, **zero `Discord Gateway error`** lines, and **only one `READY`** (the initial start).

### B. Real tradeoff tensions

**Tension 1 — "Token is the highest prior" is wrong.** Plan §1 Decision Drivers and §5 ADR anchor on token-migration as cheapest-and-highest-prior. The grep evidence falsifies this. Running Step 0.1 as a blocking gate wastes 5-10min validating a non-cause and its "success" outcome does not exclude other hypotheses.

**Tension 2 — `dispatch_silent:bisect_and_revert` (§4 attempt 2) is incompatible with the iteration model.** The remediation does `git revert <sha> && systemctl restart`. The restart itself produces `gateway_disconnect` class on the next iteration's evidence. The classifier has no rule for "post-fix restart noise" vs. "real disconnect", so iteration N+1 may misclassify as `gateway_disconnect:1` and trigger another restart — burning two of the eight-fix budget on the bisect's fallout. Worse, `git revert` mid-loop triggers `Restart=always` if Python imports fail.

**Tension 3 — Spec line 149 forbids `try/except around the gateway recv loop`, but the silent-reconnect bug requires log instrumentation INSIDE that loop to be classifiable.** Adding one `log.info(...)` line at the loop exit point (`discord_tweetshift.py:362`) is not a try/except wrapper; it is a structured exit log. The plan must explicitly authorize this so the executor does not over-correct on Anti-Pattern grounds.

**Tension 4 — Smoke test (§2.5) cannot distinguish a token fix from a service-restart fix.** A `systemctl restart` clears in-memory session state and forces fresh IDENTIFY. Both paths produce `!help` working for 30-60min post-restart. The smoke test passes either way and ships Option A as "the fix" when silent reconnect recurs in 30-60min.

### C. Synthesis

Reorder Phase 0 to put **evidence collection before remediation**, and downgrade Option A from "blocking gate" to "cheapest-to-rule-out parallel check":

1. **New Step 0.1 (parallel, ~30s):** capture three artifacts — (a) `grep -c "^DISCORD_BOT_TOKEN=" /home/openclaw/.openclaw/.env.service`, (b) `journalctl -u consensus-engine.service --since "24 hours ago" | grep -cE 'TweetShift tweet:|Discord (command|mention)|Reconnecting to Discord Gateway|Discord Gateway WS closed|Discord Gateway error|READY'` per-pattern counts, (c) `systemctl show -p MainPID -p ActiveEnterTimestamp consensus-engine.service`.
2. **New Step 0.2 (decision rule):** if (a) shows token absent → fix and restart. Else if (b) shows `Reconnecting > 0 AND READY == 1 AND WS closed == 0` → silent-reconnect confirmed → go directly to Option B.

For Tension 2, **remove `bisect_and_revert` from `dispatch_silent` registry**; replace with `restart_with_session_clear` (attempt 1) and `HALT_with_state_machine_diagnostic` (attempt 2).

For Tension 3, **add one explicit log line at `discord_tweetshift.py:362`**: `log.info("Gateway loop exited (last_op=%s, last_event=%s, sock_read_timeout=60s)", op, event)`. Authorized as instrumentation, not try/except wrapping.

For Tension 4, **harden the smoke test:** `!help` at T+15s, T+5min, T+30min. If T+30min fails, the fix is illusory.

### D. Principle-violation flags

| Plan Principle | Honored? | Note |
|---|---|---|
| **P1: Evidence before fix** | **Violated** | Plan declares token-migration the "highest prior" without citing journal evidence; grep+journal falsify the prior. |
| **P2: Do not mask symptoms** | **At-risk** | §4 `gateway_disconnect:restart_service` and `unknown:restart_service` prescribe restart, the canonical symptom-masker. |
| **P3: Surgical changes only** | **Honored** | `Files this plan creates / modifies` table is correctly bounded. |
| **P4: Bounded autonomy** | **Honored with caveat** | `bisect_and_revert` can write to git and restart in one atomic action. |
| **P5: Verifiable end-to-end** | **Honored on §2.5; weak on §3.3** | 24h iteration success criterion only proves health at the probe moment, not the full 60min between. |

### E. Code-reading findings

1. **`_on_mention` is awaited inline with `try/except Exception, exc_info=True`** (`discord_tweetshift.py:307-309`). Hypothesis (c) "callback raises silently" is partially refuted — 24h journal shows zero `Mention callback error` / `Command callback error`. **Drop hypothesis (c).**
2. **Env var name is `DISCORD_BOT_TOKEN`** (verified at `config/consensus.yaml:12` and `consensus_engine/config.py:33-37`).
3. **Intents value matches spec.** `discord_tweetshift.py:30` is `INTENTS = 1 | 512 | 32768 = 33281`. No recent commit touched line 30. **Hypothesis (b) intents-drift is refuted.**
4. **`send_command_reply` does NOT capture response body on non-2xx.** `discord.py:464-466` logs only status code. Recommend executor add `error_body = await resp.text()` to the `log.warning`.
5. **Silent reconnect smoking gun.** Journal: 9+ `Reconnecting...` lines since 12:47 service start, zero `WS closed`, zero `Discord Gateway error`, only one `READY`. **Direct evidence for hypothesis (d).**
6. **Listener wiring is correct.** `consensus_engine/main.py:515-516` adapts the 4-arg callback properly.

### F. Verdict

**`RECOMMEND_REVISE`**

Required changes:

1. **Reorder Phase 0** per §C synthesis: parallel evidence-collection step → decision rule.
2. **Demote Option A** from "blocking gate" to "cheapest parallel check".
3. **Rerank §1 hypotheses** with (d) silent-reconnect first.
4. **Replace `dispatch_silent:bisect_and_revert`** in §4 with `restart_with_session_clear` (attempt 1) + `HALT_with_state_machine_diagnostic` (attempt 2).
5. **Authorize one structural log line** at `discord_tweetshift.py:362` and one body-capture line at `discord.py:465`. Mark as instrumentation, not symptom-masking.
6. **Harden §2.5 smoke test** to T+15s, T+5min, T+30min.
7. **Add per-iteration service-uptime log** in §3.3.
8. **Drop hypothesis (c)** from §1.4.

---

## Critic Evaluation (Revision 2 review)

**Verdict: `ITERATE`.** All 8 Architect changes applied. Patch shape is concrete to file:line. Hypotheses correctly reranked. But one critical gap blocks `APPROVE`.

### Architect-fix verification (Applied/Partial/Missing)
1. Phase 0 reordered with parallel evidence + decision rule — **Applied** (§2.0.1, §2.0.2).
2. Option A demoted — **Applied** (§1, §5 ADR).
3. Hypothesis (d) ranked first — **Applied** (table rank 1).
4. `bisect_and_revert` replaced — **Applied** (§4 attempt 1 = `restart_with_session_clear`, attempt 2 = `HALT_with_state_machine_diagnostic`).
5. Two instrumentation lines authorized — **Applied** (§2.1 File 1 (c) + File 2).
6. Smoke test at T+15s/T+5min/T+30min — **Applied** (§2.5).
7. Per-iteration uptime log — **Applied** (§3.2, §3.3).
8. Hypothesis (c) dropped — **Applied** (table status DROPPED).

### Critical Finding: Verification probe is silently filtered

`discord_tweetshift.py:284-285`:
```python
if author_obj.get("bot") or data.get("webhook_id"):
    return
```

This executes BEFORE `parse_command` (line 287) and BEFORE `_on_mention` (line 299). Probes posted with `Authorization: Bot <token>` carry `author.bot=True` and are dropped at line 285 without reaching dispatch. **The smoke test (§2.5) and 24h loop (§3.1) both inherit this blindness — they cannot detect either the silent-reconnect bug OR its fix.** Pre-mortem scenario #2's echo guard (`author.id != probe_sender.id`) is incoherent because probe sender = bot and reply sender = bot.

### ITERATE list (4 items)

**1. Verification probe path (MANDATORY).**
Resolution chosen: **path (i)** — modify the bot-self filter to allow self-author messages while still filtering other bots and webhooks. Add to §2.1 File 1 as **addition (d)**:

```python
# Line 284-285 replacement:
author_obj = data.get("author") or {}
author_id = str(author_obj.get("id") or "")
# Filter other bots and webhooks (loop guard); allow self-bot messages
# so verification probes can reach dispatch.
if (author_obj.get("bot") and author_id != self._bot_user_id) or data.get("webhook_id"):
    return
```

**Loop-safety proof:**
- Bot's command replies (e.g. `HELP_TEXT`) start with `**OpenClaw...`; `parse_command` returns None on non-`!`-prefixed content. No infinite command loop.
- Bot's replies use `message_reference` (not `<@bot_id>` mention syntax); `_bot_user_id in mentioned_ids` is False on replies. No infinite mention loop.
- The mention path strips a leading `<@bot_id>` then checks `startswith("!")` — bot reply text doesn't start with `<@bot_id>`. Safe.

**Regression test addition (§2.2 third test):** feed a `MESSAGE_CREATE` payload through `_handle_dispatch` with `author.bot=True`, `author.id == self._bot_user_id`, `channel_id == commands_channel_id`, `content == "!help"` and assert `_on_command` is called with `cmd="help"`. Pre-fix: filter drops it, callback NOT called → test fails. Post-fix: callback called → test passes.

**2. MESSAGE_CREATE end-to-end test (spec line 85).**
Concrete spec for §2.2: `tests/test_discord_command_dispatch_regression.py::test_help_command_dispatch_via_self_probe` — instantiate `DiscordTweetShiftListener` with mock `on_command`/`on_mention`/`on_tweet`, manually set `_bot_user_id` and `_commands_channel_id`, call `_handle_dispatch("MESSAGE_CREATE", payload)` with the self-probe payload above, assert mock_on_command called once with `("help", [], commands_channel_id, message_id, bot_user_id)`. Fails on pre-fix HEAD (filter drops); passes post-fix.

**3. Halt orchestration runtime checks (§3.3).**
Add explicit pseudo-code before the ScheduleWakeup branch in §3.3:
```python
state = json.loads(state_path.read_text())
halted = (
    state.get("halted") is True or
    len(state.get("fixes_applied", [])) > 8 or
    _class_consecutive_failures(state) >= 3
)
if halted:
    log_line = f"{iso_ts} iter={N}/24 HALTED reason={state['halt_reason']}"
    append_to(".omc/logs/discord-verification-24h.log", log_line)
    return  # do NOT call ScheduleWakeup
schedule_wakeup(delaySeconds=3600, ...)
```
Every halt branch in §4 must write one ISO-timestamped `HALTED iter=N class=X reason=Y` line to `.omc/logs/discord-verification-24h.log` before exiting.

**4. DoD-2 evidence query.**
Add to DoD #2: after `git log -1 --format=%ct <fix_commit>` to get fix timestamp, run `journalctl -u consensus-engine.service --since "@<fix_ts>" --no-pager | grep -cE 'Started consensus-engine'` — must equal exactly 1 (the post-fix start) for DoD #2 to pass. Any number > 1 means a failure-driven restart and DoD #2 fails.

### Stronger pre-mortem #2 mitigation

The echo guard must NOT use `author.id != probe_sender.id` (broken — both are bot). Replace with:
- For `!help` probes: match reply by `message_reference.message_id == probe_message_id` (Discord's true reply pointer; spec line 99 already implies this).
- For `@mention` probes: embed a unique nonce in the probe content — e.g., `<@BOT_USER_ID> ping-PROBE-<uuid4>` — and match the reply by both `referenced_message_id == probe_message_id` AND `content_or_referenced contains uuid4`. The bot's LLM mention reply quotes the question's nonce; the verifier matches the nonce.

### Acceptance criteria checklist
- [OK] Patch shape unambiguous.
- [OK after iterate] Regression test fails pre-fix, passes post-fix (covers self-probe filter + op:9 + clean-exit).
- [OK after iterate] Smoke test detects bug AND fix via self-probe path.
- [OK after iterate] Verification probe path documented and loop-safe.
- [OK after iterate] Self-heal hard stops as runtime checks (§3.3 pseudo-code).
- [OK after iterate] DoD evidence trail complete (DoD-2 grep added).
- [OK] Plan modifies only Discord-touching files (filter relaxation is in `discord_tweetshift.py`, in scope).
- [OK] Spec anti-patterns not violated (filter relaxation isn't a try/except wrapper; it's a one-line predicate change).

---

## Final Consensus (post-iterate decision)

The Critic's 4 ITERATE items are folded into the plan as authoritative addenda. The plan is now considered **APPROVED with consensus addenda**:
- Patch additions: (a) `OP_INVALID_SESSION = 9` constant, (b) op:9 branch clearing session state, (c) silent-exit detection at `_connect_once` cleanup, (d) **bot-self filter relaxation** for verification probes, (e) body capture in `discord.py:464-466`.
- Regression test: 3 cases — op:9 clears state, clean-exit clears state, self-probe MESSAGE_CREATE reaches `_on_command`.
- Smoke test: T+15s, T+5min, T+30min, all via bot self-token (now reachable post addition (d)).
- 24h loop: state-machine halt evaluation before ScheduleWakeup; halt-line written to verification log.
- DoD-2: explicit `journalctl Started count == 1` evidence.

**Executor proceeds to Phase 0 (parallel evidence collection) → Phase 1 (write `.omc/plans/discord-fix-plan.md`) → Phase 2 (apply patch + tests + smoke test) → Phase 3 (24h loop) per the revised consensus.**
