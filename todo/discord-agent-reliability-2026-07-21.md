# Bot went unreachable and answered from its own mistakes (2026-07-21)

**Status:** DONE 2026-07-21
**Created:** 2026-07-21

**CURRENT STATUS (2026-07-21):** All four bugs fixed, committed (`e7d3479`), and verified
live in Discord — `!ask` and `@-mention` both answer in 14-17s on the first attempt,
reading real data. 104 tests pass across every touched file. Two follow-ups are logged
elsewhere and are NOT part of this item: the remaining tool-loop guard is **#45**
(reopened), and the Schwab browser re-login is **#78**.

## What the user reported
"openclaw crashed, wouldn't respond, and I had to restart the gateway. Also, it was unable
to answer my questions... it shouldn't have crashed or said '2 attempts failed' and left it
at that... once I restarted the gateway, it said it was unable to retrieve the message
content."

Four independent bugs. None of them was a model outage, and no backup model would have
helped — the model was healthy throughout (it answered a different question in 4s while
this was happening).

## Bug 1 — the "crash" was a 4-minute deaf window
`consensus_engine/scanners/discord_tweetshift.py` `run()`: the reconnect wait doubled every
drop (`backoff = min(backoff * 2, 120)`) and was **never reset after a successful
connection**. It was pinned at the 120s ceiling from Jul 19 23:27 onward.

Discord's routine reconnect is a drop plus a failed resume — two ceiling waits back to
back — so each event cost ~4 minutes of deafness. **10 times on Jul 20 alone, ~41 minutes
total.** The user's messages at 23:27:00 and 23:27:36 landed inside one.

The gateway restart did not fix it: the timer expired on its own 26s later (23:29:08), and
the existing replay then routed the 3 missed messages. Restart was coincidence.

**Fixed:** READY sets a flag that `run()` consumes to reset the wait to the 5s floor;
ceiling cut 120s -> 30s (worst case ~1 min, not ~4). Going deaf >180s now raises an
#errors alert via `ops_alert` — previously this failure was completely silent, which is
why it ran for over a day unnoticed.
Tests: `tests/test_gateway_reconnect_backoff.py` (7).

## Bug 2 — the retry reproduced the failure
See **#45** for the full loop story. Wrapper-side fix here: every retry now moves to the
next model down the chain AND a wiped scratch session, so it cannot inherit the failed
attempt's transcript. Cheap failures (empty/crash) walk the whole chain since a dead model
errors in seconds; timed-out runs stop at 2 since each costs a full 120s wall. Live
transcript rolled past 400KB.

## Bug 3 — the channel poisoned itself
`_fetch_channel_history` feeds the last 10 chat messages to the agent as context. That
block contained the bot's own "⚠️ Agent unavailable after 2 attempts" line, which the model
read back as a live system status and reported to the user as a diagnosis. Every bad answer
became the source for the next one.

**Fixed** in `consensus_engine/alerts/commands.py`. Note this needed *two* passes: the first
filter only caught the structured notices this code posts. It recurred, because the second
shape is free prose a model invents about its own state ("I cannot access...", "the agent
was unavailable after multiple attempts"). Both are now stripped, scoped to bot-authored
messages (`author.bot`) so a **user** saying "I can't access X" survives untouched.
Tests: `tests/test_channel_history_filter.py` (11).

## Bug 4 — right data, wrong answer (the subtlest one)
After Bug 3 was fixed the bot still answered wrong. Diagnosis chain, worth keeping:

1. Gave it a tool to read other rooms (`consensus_engine/tools/read_channel.py`) and
   advertised it in the steering prompt. **It didn't call it** — answered from chat history.
2. So the room's messages were injected deterministically instead of relying on the model
   to fetch them (`_referenced_room_context`). It then read real data but named the
   *second*-newest alert as "most recent".
3. Called the newest message out explicitly at the end of the block. **Still wrong.**
4. Probed the same model on a **fresh session with no chat history** — it answered
   **correctly and instantly**. So the model was capable all along.

Root cause: the injected data sat *before* the user message, and the chat-history block
(carrying the bot's own earlier wrong answers) sat immediately next to the question. The
model copied whatever was nearest.

**Fixed:** room context moved to *after* the user message — last thing read before
answering — and it states outright that it outranks the chat block, which "can contain your
own earlier replies, which are not evidence of anything." Verified live: correct answer
even with three of its own wrong answers still in the history.

**The transferable lesson:** when a weak model needs data to be correct, hand it the data,
place it adjacent to the question, and say what it outranks. Advertising a tool is
advisory; position is mechanical. Recorded in memory as
`project_discord_agent_reliability_2026-07-21`.

## Files
- `consensus_engine/scanners/discord_tweetshift.py` — backoff reset, ceiling, deaf alert
- `consensus_engine/main.py` — retry policy, session roll, `<#id>` expansion, room context
- `consensus_engine/alerts/commands.py` — history self-talk filter
- `consensus_engine/tools/read_channel.py` — NEW, also usable by hand:
  `python3 -m consensus_engine.tools.read_channel --channel errors --contains schwab`
- Tests: `test_gateway_reconnect_backoff.py`, `test_channel_history_filter.py`,
  `test_handle_mention.py`

## Caveat
The full regression suite was NOT run for this work — the user deferred it to session
close. Only the 9 touched-file test files were run (104 passed). Baseline before the work
was clean (3001 passed, 1 skipped).

Also: ~5 near-identical test questions were left in #chat by the live verification. They
roll off the 10-message history window naturally but briefly degrade the context block.
