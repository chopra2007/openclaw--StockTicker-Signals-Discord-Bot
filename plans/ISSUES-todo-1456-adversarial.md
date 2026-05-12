# Post-Batch Issues — must investigate in a fresh session

User feedback after `discover: todo-1456-adversarial` batch landed (commits
`5d15dca..a96e51f`): "the bot either doesn't reply to a mention, or gives
very dumb replies." User explicitly believes these are NOT pre-existing —
they're regressions from this batch.

This document logs the observed problems verbatim so a fresh session can
investigate. **Do not assume any of the claims below are correct without
re-testing.**

---

## Observed problems

### Problem 1 — `!ask` answers confidently wrong on simple factual queries

**Observed (2026-05-11 23:30 PT, after-hours):**

```
USER: !ask is the market open right now?
BOT:  **Yes – the U.S. equity markets are currently open.**
      - **Regular trading hours:** 9:30 AM – 4:00 PM Eastern Time, Monday-Friday.
      - **Date:** 2026-05-12 is a Wednesday (a regular trading day) and not a listed holiday.
      So, assuming the server's clock is set to Eastern Time …
```

Two compounding bugs:
1. **No current-time/market-calendar context** in the LLM prompt → confident
   wrong answer.
2. **Bot got the day-of-week wrong** ("2026-05-12 is a Wednesday" — it's a
   Tuesday).

User's reading: "any LLM would search and get the answer right." They believe
the wrong answer is mechanical — the LLM is not being given the tools/context
it needs.

### Problem 2 — `@-mention` reply preamble pollution + ignoring the question

**Observed (2026-05-11 23:30 PT):**

```
USER: @<BOT> what time is it?
BOT:  [secrets] agent: gateway secrets.resolve unavailable
      (gateway closed (1000 normal closure): no close reason
      Gateway target: ws://127.0.0.1:18789
      Source: local loopback
      Config: /home/openclaw/.openclaw/openclaw.json
      Bind: loopback); resolved command secrets locally.
      <agent then searches the VPS for system time instead of just answering>
```

User's reading: "it searches the VPS for time rather than acting like an LLM."
Plus the entire `[secrets]` block is verbose preamble pollution that pollutes
every single reply.

**Also reproduced verbatim during smoke testing:**

```
USER: @<BOT> please reply with the single word PONG
BOT:  [secrets] agent: gateway secrets.resolve unavailable …
      SMOKE TEST OK   ← (note: NOT "PONG"; agent did something other than
                         literally reply with PONG)

USER: @<BOT> echo back the word ALPHA
BOT:  [secrets] agent: gateway secrets.resolve unavailable …
      ALPHA
      The word ECHO BACK was a bit unclear. Please tell me what you'd like
      me to echo!
```

Three sub-bugs to disentangle:
- Preamble pollution (the `[secrets]` block) appears on every reply, every
  time.
- Agent occasionally substitutes its own interpretation instead of literal
  replies (PONG → "SMOKE TEST OK").
- Agent picks shell tools when a pure-LLM answer would suffice ("what time
  is it" → VPS time lookup instead of "I don't have your local timezone").

### Problem 3 — sometimes no reply at all

User reported "the bot either doesn't reply to a mention" — not reproduced
during the structured smoke (every mention I posted got a reply within
25-33s, `attempt=1` per engine log). Likely intermittent, possibly tied to:
- Engine subprocess timeout (125s)
- Agent's WS-to-local-gateway race
- TweetShift listener missing a mention event

**Suggested next-session repro:** post 20 mentions over 10 min, count
non-replies vs replies, correlate with `journalctl -u consensus-engine -u
openclaw-gateway --since "10 min ago"`.

---

## What this batch actually touched on the !ask / @-mention path

Files changed by commits `5d15dca..a96e51f` that participate in these paths:

| File | Lines changed | Risk |
|---|---|---|
| `consensus_engine/scanners/discord_tweetshift.py` | 14 | `_connect_once` now uses `await get_session()` + `session.ws_connect(headers=…)`. Discord gateway WS now shares the process TCPConnector(limit=30). |
| `consensus_engine/llm_client.py` | 53 | `call_with_fallback` now uses `await get_session()` instead of per-call `ClientSession`. Same TCPConnector. |
| `consensus_engine/alerts/discord.py` | 195 | `send_command_reply` + all post helpers migrated to singleton. |
| `consensus_engine/alerts/commands.py` | 35 | Migrated to singleton. !ask handler lives here. |
| `consensus_engine/main.py` | 45 | `_handle_mention` body NOT touched; surrounding fetches migrated. yfinance batch + max_workers=8 also here. |

`_handle_mention` itself was not edited by this batch (verified by reading
the diff). The mention path goes: TweetShift listener (migrated) →
`_handle_mention` (unchanged) → `openclaw agent` subprocess (separate
binary, not in repo) → `send_command_reply` (migrated).

---

## Hypotheses worth investigating

Listed in order of likelihood, with how to verify each:

### H1 — `[secrets]` preamble pollution is a pre-existing openclaw-CLI quirk, surfaced now because the engine restart racing the gateway changed timing

Check:
```bash
# Stop consensus engine; leave gateway up; manually invoke openclaw agent
# and see if the preamble appears even without engine involvement
sudo systemctl stop consensus-engine.service
sudo -u openclaw bash -c 'cd /home/openclaw/.openclaw/workspace && openclaw agent --agent main --message "what time is it" --timeout 60'
sudo systemctl start consensus-engine.service
```

If the preamble appears with consensus-engine STOPPED, the bug is entirely
in the openclaw CLI's secrets resolver — not in this batch.

### H2 — Singleton TCPConnector(limit=30) is starving the LLM client of connections, causing partial responses / truncations

Check:
- The `llm_client.call_with_fallback` test suite passes (10 tests) — so basic
  payload + response handling is intact.
- But under live load, the connector pool may be saturated by scanners +
  Discord WS + LLM calls. `aiohttp.TCPConnector(limit=30)` is per-host.
- Verify by raising `limit` to 100 in `consensus_engine/utils/http.py:30` and
  re-running !ask. If reply quality improves, this is it.

### H3 — !ask was previously injecting current-time / date context that I accidentally removed in `alerts/commands.py` migration

Check:
```bash
git show pre-batch-1456-20260511-2054:consensus_engine/alerts/commands.py \
  > /tmp/commands_pre.py
diff /tmp/commands_pre.py consensus_engine/alerts/commands.py | less
```

Look for prompt-construction differences in the `!ask` handler. If the
pre-batch version added "Current UTC time: {now}" to the system prompt
and the migrated version dropped that, that's the bug.

### H4 — Discord Gateway WS sharing the singleton's connector causes stale connections / dropped mention events

Check:
- Discord Gateway uses one persistent WebSocket; sharing the connector
  shouldn't degrade it.
- But `aiohttp.ws_connect` with `headers=` on the request call (vs
  ClientSession constructor) MAY behave differently in error recovery.
- Check `journalctl -u consensus-engine -f` for mention events that arrive
  but never trigger `_handle_mention`. If found, the listener is dropping
  events somewhere between WS recv and dispatch.

### H5 — Agent's tool-call decisions are dumber because the system prompt or tool list changed

Likely candidate file: `/home/openclaw/.openclaw/openclaw.json` or the
agent system prompt baked into the `openclaw` binary. Neither is in this
repo. Check `git log --all --since=2026-05-01` on the openclaw repo.

---

## Recommended next-session triage order

1. **Reproduce H1 first** (preamble pollution with engine stopped). Cheap
   to verify; if true, removes the biggest distraction.
2. **H3 next** — diff `alerts/commands.py` pre- and post-batch and look for
   any system-prompt edits I made by accident.
3. **H2 next** — bump `utils/http.py` connector limit and re-test.
4. **H5 last** — if 1–3 don't explain it, the agent itself needs work
   outside this repo.

---

## State before investigation

- Engine: `active`, PID 1493198 (restarted 2026-05-11 23:16 PT)
- Gateway: `active`, PID 1349512 (since 2026-05-11 18:20 PT, NOT restarted by
  this batch)
- Pre-batch SHA tag: `pre-batch-1456-20260511-2054` → f956c59
- Full diff of batch: `git diff pre-batch-1456-20260511-2054..HEAD`
- All pytests passing (1037 / 0 fail)
- HTTP singleton acceptance grep returns zero

## What this batch claims to have shipped

(Per `final-plan.md`; some claims may be wrong if H1-H5 above are correct.)

- Item 1 — calibration `_ensure_loaded` cache gate fix → 2 RED tests turned
  green. **Probably still correct.**
- Item 4-A — max_workers=8 + rate_limiter slot drift. **Probably still correct.**
- Item 4-B — 25-site HTTP singleton migration. **Suspect (H2, H4).**
- Item 4-C — parallel news cascade + Brave daily-cap + yfinance batch.
  **Probably correct; not on !ask/@-mention path.**
- Item 5 — `_handle_mention` retry tests. **Probably still correct (unit only).**
- Item 6 — systemd units check-in. **Definitely correct (additive only).**

---

## Rollback plan if H2/H3/H4 are confirmed regressions

```bash
# Revert just the HTTP migration commit, keep the rest:
git revert 0a0309e
git push origin master
sudo systemctl restart consensus-engine.service
```

The HTTP migration is the highest-suspicion piece. Reverting it leaves
Items 1, 4-A, 4-C, 5, 6 intact.

If !ask quality returns after that revert, H2/H3/H4 is confirmed and
the migration needs a careful redo with explicit testing of LLM reply
quality at every step.
