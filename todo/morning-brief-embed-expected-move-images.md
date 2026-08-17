# Make the morning brief a compact card with expected-move charts

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. The requested July 30 brief and the latest live briefs
were read from Discord. The reference message has the preferred compact sections, but Discord stored
it as plain text rather than a real card. The current sender also posts plain text and clips it at
1,990 characters. Next: preserve the reference's compact visual order in a real Discord embed and add
the existing SPY expected-move chart, with the weekly chart as a best-effort second image.

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
