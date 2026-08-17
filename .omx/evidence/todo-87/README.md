# Evidence pack — TODO #87 "Make the morning brief a compact card with expected-move charts"

Gathered 2026-08-17. Read-only research pass — no feature code was written, nothing outside this
folder was touched, no tests run, nothing posted to Discord.

Detail file this supports: `todo/morning-brief-embed-expected-move-images.md`
(sections "Next steps, in order" and "Historical verification required before DONE").

---

## Files in this folder

### Data pulled from the live database (`consensus.db`)

| File | What's in it | Why it matters |
|---|---|---|
| `briefing_runs.json` | **79 rows**, every column, oldest first (`created_at` ascending). Dates run **2026-04-22 → 2026-08-17**. All 79 have status `archived`. | This is the "formatting and size corpus" the detail file asks for (it says 78; the real count today is 79 — one more brief has been posted since that note was written). Each row holds the exact text that was posted, plus the Discord message id, so a new card builder can be replayed against every real past brief. |
| `iv_snapshots_full.json` | **3,355 rows** — 371 tickers across 49 trading dates (2026-06-29 → 2026-08-16). Columns: `snapshot_date, ticker, spot, atm_iv, straddle_em, iv_em_to_expiry, expiry, captured_at`. | The saved expected-move numbers. Lets the daily chart's numbers be checked against history for any ticker, not just SPY. |
| `iv_snapshots_spy.json` | The **47 SPY rows** only, oldest first (2026-06-29 → 2026-08-16). | The specific set the detail file names for independently checking the daily SPY chart numbers. All 47 rows have a real `spot`, `atm_iv` and `straddle_em` — no blanks to work around. Every row's `expiry` is the *next* session, not the snapshot day itself (e.g. snapshot 2026-08-16, expiry 2026-08-17), confirming these are nearest-expiration daily snapshots. |

### Discord history

| File | What's in it |
|---|---|
| `briefing-channel-last-100.txt` | Full output of `python3 -m consensus_engine.tools.read_channel --channel briefing --limit 100`. Covers **2026-05-07 → 2026-08-17**. Includes the July 30 reference brief and every recent live brief. |

### Code copies (each has a 3-line header naming the original path and today's date)

| File | Original | Scope |
|---|---|---|
| `alfred.py` | `consensus_engine/briefing/alfred.py` | Full file, 343 lines |
| `expected_move.py` | `consensus_engine/scanners/expected_move.py` | Full file, 757 lines |
| `commands_em_excerpt.py` | `consensus_engine/alerts/commands.py` | Lines **1213–1246** — `_handle_em` (1213–1224) and `_em_and_reply` (1227–1246). There are no other helpers local to this pair; everything else it uses lives in `expected_move.py` and `discord.py`, both also copied here. |
| `discord_embed_image_excerpt.py` | `consensus_engine/alerts/discord.py` | Lines **36–93**, **1020–1051**, **1133–1243**. That is: the embed size caps (`_EMBED_LIMITS`, `_FIELD_LIMITS`), the guard that clips over-long embed text (`_clip` / `_clamp_embeds` / `_safe_send_kwargs`), the 2000-character plain-text splitter (`_DISCORD_MSG_LIMIT`, `_split_for_discord`), the plain embed reply (`send_command_embed_reply`), and the multipart embed+PNG uploader (`send_command_embed_with_image`, 1161–1243). |
| `test_alfred_render.py` | `tests/test_alfred_render.py` | Full file, 67 lines |
| `test_alfred_vault.py` | `tests/test_alfred_vault.py` | Full file, 17 lines |
| `test_expected_move.py` | `tests/test_expected_move.py` | Full file, 504 lines |

---

## Findings worth carrying into the build

**The cut-off problem is real and measurable.** `alfred.py` line 222 sends
`{"content": content[:1990]}` — it chops the text at 1,990 characters. Of the 79 stored briefs,
**27 are longer than that**, so their last sections were cut off in Discord. The longest was
2026-07-23 at 2,795 characters — roughly 800 characters, about two whole sections, lost. Others
over the limit: 2026-05-12 (2,551), 2026-06-12 (2,560), 2026-07-16 (2,679), 2026-08-11 (2,526),
2026-08-05 (2,409), 2026-06-16 (2,400), 2026-06-22 (2,416), 2026-08-14 (2,318), 2026-07-20 (2,334),
2026-07-01 (2,276), 2026-07-07 (2,258), 2026-07-13 (2,222), 2026-05-22 (2,230), 2026-06-29 (2,204),
2026-07-10 (2,203), 2026-06-05 (2,183), 2026-07-06 (2,165), 2026-05-20 (2,134), 2026-05-14 (2,117),
2026-06-30 (2,114), 2026-07-08 (2,113), 2026-06-26 (2,080), 2026-08-10 (2,072), 2026-07-27 (2,056),
2026-06-11 (2,043), 2026-07-22 (2,025). Stored lengths overall: shortest 480, longest 2,795,
average about 1,700 characters. You can see the damage directly in
`briefing-channel-last-100.txt` — one brief ends mid-sentence at
"**SE** – Bearish pressure from options".

**Format varies a lot day to day**, which is the other thing the detail file flags. The July 30
reference is fenced markdown with `##` headings. The very next day, July 31, is bold text with a
"Top Story" block and a markdown table. The most recent brief (2026-08-17) uses `###` headings plus
a table. Any new card builder has to cope with all three shapes, or stop letting the AI choose.

**The stored text matches Discord exactly.** For 2026-07-30 the `rendered_content` in the database
is character-for-character the same as what `read_channel` pulled back from Discord (1,075
characters, message id `1532370090983559188`), including the trailing
"⚠️ 2 levels hidden as out-of-range." line. So the database corpus is a trustworthy stand-in for
the posted output when checking formatting and length.

---

## Gaps and limits — read before planning verification

**(a) The July 30 reference message WAS recovered, by timestamp.** No guessing or reconstruction
was needed. `read_channel --limit 100` reached back to 2026-05-07, well past July 30, so the
reference brief is in `briefing-channel-last-100.txt` at line 2279, timestamped
`2026-07-30 05:51 AM PDT`. It is also stored in the database as `briefing_runs` row
`session_key = 2026-07-30`. Two independent copies, and they agree exactly.

**(b) An exact historical source replay is NOT possible.** The `briefing_runs` table stores only
the finished text that was posted (`rendered_content`) plus delivery bookkeeping — session window,
Discord message id, status, and timestamps. It does **not** store the input records the brief was
built from: the alerts, price levels, analyst calls, and macro rows that went in. Those live in
other tables and get pruned over time. So the corpus proves *what was said and how long it was* —
useful for checking section completeness, ordering, and cut-off — but it cannot prove a rebuilt
brief would have picked the same facts from the same day's raw data. The detail file states this
limit itself, and nothing found today changes it: **do not claim an exact historical source
replay.** Where a date's source rows genuinely still exist, that date can be replayed; where they
don't, say so rather than filling the hole.

**(c) A multi-date weekly (`!emw`) replay is NOT possible from stored data.** `iv_snapshots` keeps
one row per ticker per day, and for SPY every one of the 47 rows points at the *next session's*
expiry — a daily snapshot. There is no stored weekly option chain and no second row per ticker for a
week-out expiry. So the weekly chart can only be checked against a live chain fetched now, the same
one `!emw` uses. If a multi-date weekly backtest is actually wanted, weekly snapshot storage has to
be added first and then collected going forward — that history cannot be filled in for the past.

**(d) Daily SPY coverage starts 2026-06-29.** The expected-move snapshots only go back seven weeks,
while the briefs go back to 2026-04-22. Briefs from 2026-04-22 through 2026-06-26 have no matching
saved expected-move numbers, so the daily-chart accuracy check can only cover the 47 SPY dates from
2026-06-29 onward.

**(e) `read_channel` cannot page further back than 100 messages.** Today that reached 2026-05-07,
which covers the whole request. If a brief older than that is ever needed for comparison, the
database corpus is the only source — and that has text only, no rendered card.
