# Make the morning brief a compact card with expected-move charts

**Status:** DONE
**Created:** 2026-08-17
**Completed:** 2026-08-18

**CURRENT STATUS (2026-08-18):** DONE and live. The morning brief is now a real Discord card:
one embed with the five fixed sections (Overnight, Levels to Watch (SPY), High-Conviction Calls,
Macro, Top Tickers), the SPY daily expected-move chart attached under Levels, and the weekly chart
in a second embed in the same message. The date/time on the card is always Pacific and is computed
by the code, never written by the AI.

Proof, not just tests:
- **The old brief was cutting itself off.** 27 of 79 archived briefs were longer than the old
  1,990-character slice, so roughly 1 in 3 real briefs silently lost Macro and Top Tickers. All 79
  replayed through the new builder lose nothing: 0 over the limit, all 5 sections present.
- **Live check:** posted to Discord and read back off the API (messages 1539043951812542464 and
  1539044550272614492) — 2 embeds, both charts served from Discord's CDN, all 5 sections.
- **Independent adversarial review** found 7 defects; all 7 are fixed (see
  `.omx/evidence/todo-87/independent-verification.md`). The important one: an Eastern-time label
  could reach the card through the no-AI fallback path — 4 real archived briefs literally say
  "All times EST". The card now strips the label while leaving the time itself untouched.
- **Next scheduled post** (05:50 PDT) is checked automatically by
  `scripts/check_morning_brief_card.py`, which writes its verdict to the task-system notification log.

## What the user wants

Use the visual style of the referenced morning brief:

- Overnight.
- Levels to Watch.
- High-Conviction Calls.
- Macro.
- Top Tickers.

Turn that into a clean Discord embed that can be read quickly. Under `Levels to Watch (SPY)`, include
the same daily expected-move image produced by `!em SPY`. If Discord space and valid options data allow
it, include the weekly `!emw SPY` image too.

## What worked so far

- The referenced July 30 message is compact and has the preferred section order.
- `consensus_engine/briefing/alfred.py` already gathers overnight alerts, levels, analyst calls, macro,
  and top tickers.
- `consensus_engine/scanners/expected_move.py` already computes daily and weekly expected moves,
  builds the detailed embed, and renders the PNG chart used by `!em` and `!emw`.
- `consensus_engine/alerts/discord.py::send_command_embed_with_image` proves that Discord accepts the
  generated chart as an attached image.
- The morning brief has a pending -> posted -> archived record so failed delivery can retry without
  double-posting.

## What does not work and why

- `_send_discord_briefing()` sends only `content`, not an embed.
- It slices the text to 1,990 characters. Recent briefs are long enough to be cut off, so the last
  sections can disappear.
- The AI returns free-form markdown, so headings and density vary from day to day.
- The morning path does not call the expected-move code or upload images.
- A Discord embed can hold one main image. Showing both daily and weekly charts cleanly may require
  multiple embeds and two attachments in the same message, or a compact combined image. This should
  be proven with a real render instead of guessed.

## Next steps, in order

1. Define a stable morning-card shape with short fields matching the reference order. Keep the top
   story only when it is material; do not let it bury the five requested sections.
2. Make the AI return structured section text, or parse and validate its output before building the
   embed. Keep a deterministic fallback so an AI failure still produces a complete card.
3. Reuse `expected_move.compute_em`, `build_em_embed`, and `render_chart` for SPY. Do not create a
   second calculation with different rules.
4. Daily expected move is required when usable quotes exist. Weekly is best effort: include it when
   its data and Discord payload fit, but never delay or block the whole brief if it is unavailable.
5. Add a reusable sender for one main embed plus one or two PNG attachments. Preserve the existing
   retry behavior, mention blocking, size guards, and single-message delivery record.
6. Keep the archive useful: save the readable brief text plus the daily/weekly expected-move numbers
   or image metadata needed to understand what was posted.
7. Make the displayed date and time deterministic from `ZoneInfo("America/Los_Angeles")`; do not let
   the AI invent a clock time or the wrong seasonal Pacific label.
8. Test embed limits, image failure, daily-data failure, weekly-data failure, retry/idempotency, and
   the plain fallback.
9. Post a clearly labeled test in `#chat`, inspect the actual mobile/desktop card, and compare it to
   the July 30 reference. After deployment, inspect the next real `#brief` post before marking done.

## Historical verification required before DONE

- Use all 78 archived briefing texts as the formatting and size corpus for the new card builder.
  Confirm every recoverable requested section survives, no text is silently cut off, and empty
  sections degrade clearly rather than disappear. The run table saved rendered text, not a full copy
  of every input, so do not claim an exact historical source replay where the old source rows are gone.
- Have Codex compare the replayed section text to stored source records for every date that can be
  reconstructed, covering busy, quiet, missing-data, and fallback days. Any invented catalyst, wrong
  direction, stale level, or missing major item must be explained and fixed.
- Independently check the daily SPY chart numbers against the 47 saved nearest-expiration SPY
  snapshots. The table does not preserve a full weekly option chain, so it cannot honestly backtest
  old weekly charts. Verify weekly output against the same live chain used by `!emw`, and add weekly
  snapshot storage first if a multi-date weekly replay is required. Never fabricate missing history.
- Compare recoverable old Discord briefs to the new renders, including the owner's July 30 reference.
  The new card must be at least as quick to scan while preserving the underlying facts.
- After historical replay passes, inspect a real current `#chat` test and the next scheduled brief in
  Discord. Local image files and unit tests alone do not close this task.

## Files / code involved

- `consensus_engine/briefing/alfred.py` — gathers, renders, sends, retries, and archives the brief.
- `consensus_engine/scanners/expected_move.py` — daily/weekly calculation, embed data, chart image.
- `consensus_engine/alerts/commands.py::_em_and_reply` — proven `!em` / `!emw` integration pattern.
- `consensus_engine/alerts/discord.py` — safe Discord sending, embed limits, and image upload.
- `tests/test_alfred_render.py` and `tests/test_alfred_vault.py` — current brief tests.
- `tests/test_expected_move.py` — current daily/weekly embed and image expectations.

## Open questions

- Whether two separate chart embeds or one combined daily/weekly chart reads better on a phone. Use
  actual Discord test renders to decide.
- The reference message is visually compact but technically plain text. The goal is its readability,
  not preserving the code block around it.
