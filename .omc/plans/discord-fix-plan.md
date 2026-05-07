# Discord Bot — Phase 1 Fix Plan

**Source spec:** `.omc/plans/discord-commands-fix-spec.md`
**Consensus plan:** `.omc/plans/ralplan-discord-fix-v1.md` (Revision 2 + Critic consensus addenda)
**Phase:** 1 — Plan (no code edits yet)

---

## 1. Root cause

The Discord gateway loop in `consensus_engine/scanners/discord_tweetshift.py:323` (`async for msg in ws`) exits cleanly when `aiohttp` `sock_read=60` (line 318) fires after Discord stops sending frames; the cleanup path then RESUMEs (line 345) on stale `_session_id`/`_sequence` because `op:9 INVALID_SESSION` is never handled and a clean WS exit never clears session state. Heartbeats keep the process looking healthy in `systemctl status`, but `MESSAGE_CREATE` dispatch silently dies. **Evidence:** 24h journal grep shows `Reconnecting × 33`, `READY × 6` (across 6 separate restart episodes, only 1 per episode), `Discord Gateway WS closed × 0`, `Discord Gateway error × 0`.

Secondary fault: `discord_tweetshift.py:284-285` filters out the bot's own messages before dispatch, so any verification probe sent via the bot's own token is silently dropped — the existing smoke test path is blind to the bug.

## 2. Why prior fixes were short-lived

- **`ef71591`** added `sock_connect=30` (correct guard against TCP/SSL handshake hangs) but also wrapped `_connect_once` in `asyncio.wait_for(timeout=300)` — which killed live gateway sessions every 5 minutes. The 5-minute kill was the *visible* symptom; the underlying zombie-session bug stayed hidden behind it.
- **`c9a06b7`** reverted the 300s outer timeout (correct: it was killing live sessions). But it did NOT add HEARTBEAT_ACK tracking, did NOT handle `op:9`, and did NOT distinguish "WS exited cleanly without CLOSE/ERROR" from "WS closed normally". So the silent-zombie path that pre-existed `ef71591` re-emerged the moment the masking timeout was removed.

The masked symptom both prior fixes obscured: **the gateway can RESUME on a session that Discord has silently invalidated, and the bot has no detection path** (no op:9 handler, no ACK timeout, no exit log).

## 3. Patch (exact diff sketch — surgical only)

### File 1 — `consensus_engine/scanners/discord_tweetshift.py`

**Addition (a) — opcode constant.** After line 38 (`OP_HEARTBEAT_ACK = 11`):
```python
OP_INVALID_SESSION = 9
```

**Addition (b) — op:9 INVALID_SESSION handler.** Inside `_connect_once`'s opcode dispatch chain (currently lines 337–356), insert a new `elif` branch after the `OP_HEARTBEAT_ACK` branch and before the `WSMsgType.CLOSE/ERROR` arm at line 358:
```python
elif op == OP_INVALID_SESSION:
    log.warning("Discord Gateway op:9 INVALID_SESSION (resumable=%s) — clearing session, will IDENTIFY on next connect", bool(data))
    self._session_id = None
    self._sequence = None
    await ws.close(code=4000)
    break
```
Behavior: clears `_session_id` and `_sequence`, closes WS with non-1000 code (signals "not a clean shutdown" to aiohttp), breaks the recv loop. The outer `run()` loop reconnects with cleared state → `_connect_once` falls through to `_identify()` at line 347 instead of `_resume()` at line 345.

**Addition (c) — silent-exit detection (replaces lines 362–363 cleanup).** Replace:
```python
                if hb_task:
                    hb_task.cancel()
```
with:
```python
                # Detect silent exit (sock_read=60 zombie): WS read loop
                # ended without an explicit CLOSE/ERROR frame.
                # Force IDENTIFY on next reconnect by clearing session state.
                ws_close_code = ws.close_code if self._ws else None
                log.info(
                    "Gateway loop exited (last_op=%s, last_event=%s, ws_closed=%s, close_code=%s)",
                    op if 'op' in dir() else None,
                    event if 'event' in dir() else None,
                    ws.closed if ws else None,
                    ws_close_code,
                )
                if ws_close_code is None:
                    # Clean exit with no close frame — zombie session.
                    log.warning("Silent gateway exit detected — clearing session to force IDENTIFY")
                    self._session_id = None
                    self._sequence = None
                if hb_task:
                    hb_task.cancel()
```
The structured log line is **instrumentation, NOT a try/except wrapper**. It runs after `async for msg in ws` returns naturally; spec line 149's anti-pattern (try/except inside the recv loop) is honored.

**Addition (d) — bot-self-filter relaxation with self-reply guard (verification probe support).** Replace lines 281–285:
```python
                author_id = str((data.get("author") or {}).get("id") or "")
                # Ignore messages from bots/webhooks to avoid loops
                author_obj = data.get("author") or {}
                if author_obj.get("bot") or data.get("webhook_id"):
                    return
```
with:
```python
                author_obj = data.get("author") or {}
                author_id = str(author_obj.get("id") or "")
                is_self = bool(self._bot_user_id) and author_id == self._bot_user_id
                # Self-bot replies carry message_reference (Discord auto-pings
                # the replied-to user, which is the bot itself, causing a
                # mention loop). Drop them. Self-bot fresh posts (no
                # message_reference) are verification probes — let them through.
                is_self_reply = is_self and bool((data.get("message_reference") or {}).get("message_id"))
                # Filter other bots, webhooks, and the bot's own replies.
                if (author_obj.get("bot") and not is_self) or data.get("webhook_id") or is_self_reply:
                    return
```

**Why the self-reply guard is mandatory:** Discord populates `mentions[]` with the replied-to user automatically when a message has a `message_reference`. The bot's own reply (created by `send_command_reply`) therefore arrives back as a MESSAGE_CREATE with `mentions: [{id: bot_user_id}]`, which would re-trigger the mention path → another LLM reply → infinite loop. Discovered during T+15s smoke test execution, where the first relaxation (without `is_self_reply` check) produced an immediate reply storm of dozens of "OpenClaw Signal Engine" / "pong-PROBE-..." / "⚠️ LLM unavailable" messages. The fix is to drop self-bot messages that carry `message_reference` (i.e., are replies) while keeping fresh self-bot posts (probes) processable.

**Loop-safety proof (revised):**
- Self-bot fresh post (probe, no `message_reference`): processed. Examples: `!help` reaches command dispatch; `<@bot> ping-PROBE-{nonce}` reaches mention dispatch.
- Self-bot reply (with `message_reference`): filtered. The bot's own help-text reply, mention reply, and "LLM unavailable" replies all carry `message_reference` and are dropped.
- Other-bot message: filtered (the `not is_self` guard preserves the original behavior).
- Webhook: filtered (`webhook_id` clause unchanged).
- A non-reply post by the bot to its own commands channel (e.g., a future scheduled status message) would reach dispatch. That message would not @-mention the bot in `mentions[]` (Discord only auto-includes mentions for explicit `<@id>` syntax or replies), so the mention path would not fire. The command path requires the content to start with `!`, which automated bot posts do not. No loop.

### File 2 — `consensus_engine/alerts/discord.py`

**Addition (e) — capture response body on send_command_reply error.** Replace lines 462–466:
```python
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                log.warning("Command reply failed: %d", resp.status)
                return None
```
with:
```python
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                error_body = await resp.text()
                log.warning("Command reply failed: %d body=%.300s", resp.status, error_body)
                return None
```
Mirrors the existing pattern in `send_detail_followup` at lines 502–503. Makes 401/403/429/50001 classifiable for the self-heal `reply_failed` class.

## 4. Regression guard

**File:** `tests/test_discord_command_dispatch_regression.py` (new).

Three test cases, all `pytest.mark.asyncio` (auto via `pytest.ini`):

1. **`test_op9_invalid_session_clears_state`** — Construct a `DiscordTweetShiftListener`, set `_session_id="abc"` and `_sequence=42`, simulate the op:9 handler (call the new code path with `op=9, data=False`), assert `_session_id is None and _sequence is None`. **Fails pre-fix:** the handler doesn't exist; `_session_id` retains stale value.

2. **`test_silent_exit_clears_state`** — Mock an `aiohttp` WebSocket whose `async for` exits without a CLOSE/ERROR frame and `ws.close_code is None`. Run `_connect_once` (or extracted helper) and assert `_session_id is None and _sequence is None` after exit. **Fails pre-fix:** the exit path does not clear state.

3. **`test_self_bot_probe_reaches_dispatch`** — Construct a `DiscordTweetShiftListener` with `_bot_user_id="999"`, `_commands_channel_id="100"`, mock `_on_command`. Call `_handle_dispatch("MESSAGE_CREATE", payload)` with payload `{"channel_id":"100", "id":"m1", "author":{"id":"999","bot":True}, "content":"!help", "mentions":[]}`. Assert `_on_command` called once with `("help", [], "100", "m1", "999")`. **Fails pre-fix:** filter drops the message at line 285; `_on_command` not called.

**Verification of the "fails pre-fix" claim:** `git stash push -- consensus_engine/scanners/discord_tweetshift.py consensus_engine/alerts/discord.py tests/test_discord_command_dispatch_regression.py`, run pytest, save output to `.omc/logs/discord-regression-prove.log` showing the failures, then `git stash pop` and re-run to show the passes (per spec line 140).

## 5. Rollback

Single command to revert the patch if the 24h loop fails ≥3 consecutive hours:

```bash
git revert --no-edit <FIX_COMMIT_SHA> && git push origin master
```

The fix commit will be a single commit touching only the three files above (gateway + alerts/discord + new test). Reverting it restores the prior gateway behavior. The 24h verify script is committed separately (per spec line 144) so it can survive the rollback.

---

## Files this plan touches

- **Creates:** `tests/test_discord_command_dispatch_regression.py`, `scripts/discord_24h_verify.py`, `.omc/state/discord-24h-verify.json`, `.omc/logs/discord-verification-24h.log`, `.omc/logs/discord-fail-iter-*.log`, `.omc/logs/discord-regression-prove.log`, `.omc/logs/discord-fix-pytest.log`, `.omc/logs/discord-fix-restart.log`.
- **Modifies:** `consensus_engine/scanners/discord_tweetshift.py` (additions a–d), `consensus_engine/alerts/discord.py` (addition e).
- **Does NOT modify:** `config/consensus.yaml`, any non-Discord file. Spec line 152 honored.

## Smoke test (Phase 2 step 5, before declaring fix live)

`sudo systemctl restart consensus-engine.service`, wait 15s, verify `READY` log appears.
- T+15s — POST `!help` via bot token → poll for reply within 30s. Must succeed.
- T+5min — same. Must succeed.
- T+30min — same. Must succeed (this is the silent-reconnect manifest window — failure here means the fix is illusory and we return to Phase 0 with new evidence).

If T+30min passes, declare fix live and proceed to Phase 3 (24h loop).
