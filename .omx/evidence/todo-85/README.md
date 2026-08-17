# TODO #85 evidence pack — "Make feature questions get grounded, smart answers"

**Captured:** 2026-08-17
**Purpose:** give a future session a point-in-time, grounded snapshot so it can build a
test-question set *and an answer key* for TODO #85 without re-deriving anything.
**Scope:** research only. No feature code was written, no tests were run, no live config was
touched, nothing was posted to Discord.

Task detail file this supports: `todo/discord-feature-questions-from-code.md`

---

## What was pulled

### Owner questions (the test set raw material)

| File | What it is |
|---|---|
| `chat-last-100.txt` | The last 100 `#chat` Discord messages, pulled before this pass. 69 KB, 737 lines. |
| `feature-questions-extracted.md` | **Start here.** Every real owner question found, verbatim with timestamp, plus the bot reply that followed. Also quotes the live rendered output for each feature TODO #85 names. |
| `chat-memory-rollups-dump.txt` | All 6 rows of the `chat_memory_rollups` table in `consensus.db` — the agent's own redacted summaries of past `#chat` conversations, 2026-05-19 → 2026-06-02 UTC. This is where the real owner questions came from. |

### Code snapshots (the answer-key material)

Each file starts with a header naming its original path and today's date, so it is obvious
these are point-in-time copies, not live files.

| File | Original path | Why it matters to #85 |
|---|---|---|
| `main.py-agent-mention-path.txt` | `consensus_engine/main.py`, **lines 780–1189 of 2914** | Holds `_STEERING_TEMPLATE` (line 912) — the prompt that tells the agent to read real code — and `_handle_mention` (line 990) through its end (line 1188), including the retry/model-walk logic. Only this range was saved; the file is 2914 lines. |
| `internal_breadth.py.txt` | `consensus_engine/analysis/internal_breadth.py` | **Full file (333 lines).** The truth source for the worked "Our own signal breadth" example — the key question in #85. |
| `market_daily.py.txt` | `scripts/market_daily.py` | **Full file (971 lines).** The scheduled job that reads `signal_events` and writes the daily `internal_breadth_daily` row the `!market` dashboard displays. |
| `consensus.yaml-agent-model-section.txt` | `config/consensus.yaml`, lines 360–380 | The agent's model chain: `llm.agent_model` + `llm.agent_fallback_models`, with the inline history of why each model was chosen. This is the "control" #85 step 3 races against. |
| `openclaw.json-agent-model-section.txt` | `/home/openclaw/.openclaw/openclaw.json`, `agents.defaults` | The **live** gateway model chain, workspace path, and allow-map. Must match the yaml above. **No API keys, tokens, or secrets exist in this section; a scrubber was run over it anyway.** |
| `test_handle_mention.py.txt` | `tests/test_handle_mention.py` | **Full file (419 lines).** Existing mention + room-context coverage — the place a new grading test would live. |

---

## Grounded facts worth carrying forward

Verified by reading the saved files, not from memory.

**The breadth answer key.** In `internal_breadth.py`: breadth counts **distinct tickers**, not a
watchlist. A ticker counts if its `signal_events` row has a bullish direction (`long`/`bull`/
`bullish`) or bearish (`short`/`bear`/`bearish`), and its `source_type` is **not** in
`EXCLUDED_SOURCES = {"apewisdom", "form4", "sec_form4", "sec"}`. Neutral/NULL directions are
dropped. Rows with a timestamp below `1_000_000_000.0` (~2001) are treated as garbage. The
window is **5 calendar days** (`features.internal_breadth.window`, default `5` — no explicit
value is set in the yaml, so the default applies), the same ticker inside the window counts
**once**, and the series is EMA-smoothed with `ema_alpha` `0.4` then turned into an
expanding-window z-score. So the honest answer to "can you add 2 more tickers to the list" is
**there is no list** — qualifying tickers join automatically.

**A trap for the answer key.** `config/consensus.yaml` line 954 sets
`internal_breadth: { enabled: false, shadow: true, … }`, yet `!market` printed real breadth
numbers on 2026-08-17. Both are true: the `enabled` flag only gates
`lookup_internal_breadth()` (`internal_breadth.py:289`), which is the reader that feeds *alert
context*. The `!market` dashboard reads the `internal_breadth_daily` table **directly** at
`consensus_engine/alerts/commands.py:2565`, bypassing the flag. A grader who checks only the
flag would wrongly mark a correct bot answer as wrong, or accept "the feature is off" as
correct. **Both halves must be in the answer key.**

**A stale-answer trap.** The June 2026 rollup shows the bot answering that options flow comes
from yfinance in `consensus_engine/scanners/options.py`. That was right then. Options flow has
since moved to the Schwab feed (`features.schwab_options`, `schwab_quotes`, `schwab_ohlcv` all
`enabled: true`). Any replayed historical question must be graded against **today's** code,
not the answer that was correct when it was asked.

---

## Gaps and limits — read before planning the next step

1. **`#chat`'s last 100 messages contain zero usable feature questions.** 95 of 100 messages
   are the bot's own output. The 5 owner messages are all bare commands (`!market`,
   `!scan tsla`, `!em tsla`, `!emw tsla`, `!em spy`). No `@`-mentions, no `!ask`, no questions.
   **Usable feature questions from `#chat`: 0.**

2. **100 messages is the hard ceiling of the existing tool.** `consensus_engine/tools/read_channel.py`
   clamps its limit at 100 (`min(limit, 100)`, line 62) and does not paginate — `--limit 400`
   still returns exactly 100. Going deeper needs the Discord API `before=` cursor, which that
   tool does not support. That is a small change, but it is a code change, so it was **not** made
   here.

3. **The rollup table saved this task, partially.** `chat_memory_rollups` yielded **3 real owner
   feature questions** with **3 real follow-up chains** (asked 3, 5, and 2 times respectively).
   That is enough to honour step 1's "do not rely on invented easy questions alone" — but only
   just.

4. **Rollup answers are truncated.** Every bot answer in the rollups is cut off at a trailing
   `…` by the rollup writer. You can grade *whether* the bot answered and *what file it named*,
   but you cannot grade the full wording or plain-English quality from these rows.

5. **The rollups are 2.5 months old** (2026-05-19 → 2026-06-02) and predate the TODO #79
   reliability fixes. The failures they record — a turn that produced no content, an answer to
   the *previous* question, an invented file path, leaked Gmail/DB IDs — may already be fixed.
   They are valuable as **test cases**, not as a current verdict.

6. **Most of #85's named coverage still has to be authored.** Step 1 lists breadth, VVIX vs VIX,
   expected move, alert scores, analyst groups, and a wrong-premise question. Only breadth has a
   near-match among the recovered questions. The rest must be written from scratch, grounded in
   the live rendered output quoted in `feature-questions-extracted.md`. **This should be stated
   plainly in the TODO instead of implying the set came from real history.**

7. **A ready-made real follow-up exists and is worth using.** On 2026-08-17 the owner ran
   `!em tsla`, `!emw tsla`, and `!em spy` at 02:06–02:07 and all three replied "too illiquid for
   a reliable expected move." Roughly 29 minutes later the same three came back with real
   numbers. "Why did `!em tsla` say illiquid and then work half an hour later?" is a genuine,
   grounded, hard question the owner could plausibly ask — and it is not invented.

---

## Suggested next actions (not taken here)

- Decide whether to teach `read_channel.py` to paginate past 100 messages before authoring the
  test set. That single change may recover many more real questions and would make step 1
  honest.
- Have Codex independently write the expected plain-English facts for each question from the
  saved code files — #85's "Historical verification required before DONE" asks for this, and it
  must happen **before** any candidate bot answer is seen.
- When grading breadth, include both halves of the `enabled: false` trap described above.
