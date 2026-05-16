# Ship 1 + Ship 2 — Blind Compare Pack

After this PR's local commit, the bot's `!all` output for **NVDA**, **AMD**, and
**TSLA** is captured in `nvda-bot.txt`, `amd-bot.txt`, `tsla-bot.txt`. Compare
each one head-to-head against Gemini using the canonical prompt below.

## 3-step blind compare

1. **Open** [gemini.google.com](https://gemini.google.com) in a browser. For
   each ticker (NVDA, AMD, TSLA) paste the contents of
   [`GEMINI-PROMPT.txt`](GEMINI-PROMPT.txt) with `<TICKER>` substituted, e.g.:

   ```
   Look at NVDA stock and come up with a bullish or bearish thesis, along with a trade plan composed of:
   1. buying level
   2. stop-loss level
   3. take profit level.
   ```

2. **Compare** Gemini's answer side-by-side with the matching `<ticker>-bot.txt`
   file in this directory. Treat both as anonymous outputs — don't peek at
   the labels until you've decided which one you'd actually trade.

3. **Vote** per ticker: `prefer-bot` / `prefer-gemini` / `tie`.

## Acceptance gate (from TODO #1)

3/3 must be `prefer-bot` or `tie` for this PR to merge.

- 3/3 in those buckets → push the commit (`git push origin master`) and
  mark TODO #7 done.
- Any `prefer-gemini` vote → iterate. Open a new TODO entry capturing the
  specific gap (e.g. "Gemini gave deeper macro context for NVDA — add
  macro_context section to narrator").

## What's new in this PR (so you know what to look for)

Ship 1 (format pack):
- N1 cashtag — `$NVDA` everywhere
- N2 direction emoji — 🟢 / 🔴 / ⚪
- N3 compact money — `$2.4M` / `$437K` / `$1.2B`
- N4 level arrows — ↑ above spot, ↓ below, ⇄ at spot
- N5 plain-English one-liner under each level
- N7 relative dates — `in 3 sessions` instead of ISO

Ship 2 (narrative pack):
- M1 TL;DR — one-line thesis at the top of the embed
- M2 Bear Case — `**What could go wrong:**` with `[evidence:N]` citations
- M3 Variant perception — `Market view: … Our view: … Catalyst: …`
- M6 Risks & mitigants — `- <risk> → <mitigant>` bullet list

## Files

- `GEMINI-PROMPT.txt` — canonical blind-compare prompt
- `nvda-bot.txt` / `amd-bot.txt` / `tsla-bot.txt` — bot embeds captured live
  during Phase B verification
- `README.md` — this file
