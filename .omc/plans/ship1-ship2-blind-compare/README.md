# Ship 1 + Ship 2 — Blind Compare Pack

After this PR's local commit, the bot's `!all` output for **NVDA**, **AMD**, and
**TSLA** is captured in `nvda-bot.txt`, `amd-bot.txt`, `tsla-bot.txt`. Compare
each one head-to-head against Gemini using the format-matched prompt.

## Why the prompt is format-matched

A naïve "write a thesis on NVDA" prompt would let Gemini answer in free prose
while the bot is forced through a deterministic skeleton (TL;DR, Market view /
Our view / Catalyst, Catalysts, Risk Considerations, Bear Case, Risks &
mitigants, Trade Plan table). A blind judge would prefer the bot purely on
*structure*, not *substance* — that's a format win, not a quality win.

To isolate substance, [`GEMINI-PROMPT.txt`](GEMINI-PROMPT.txt) gives Gemini the
same skeleton and the same per-ticker current price as the bot used. The
comparison then turns on:

- thesis quality and conviction
- specificity of catalysts (numbers, dates, named events)
- specificity of risk levels (real invalidation prices, not "if sentiment turns")
- trade-plan reasonableness (does Buy Zone / SL / TPs hang together?)
- whether the Bear Case actually engages the opposite case instead of hedging

## Caveat: Gemini has no live evidence access

The bot is fed live news, SEC filings, options flow, and YouTube transcripts via
its xref pipeline. Gemini is answering from its training cutoff. That's a real
asymmetry — but it cuts *toward* the bot, not against it, so a tie or bot-win on
substance is still a fair signal. Treat evidence specificity as a separate axis:
note it, but don't double-count it against Gemini.

## 3-step blind compare

1. **Open** [gemini.google.com](https://gemini.google.com). For each ticker
   paste [`GEMINI-PROMPT.txt`](GEMINI-PROMPT.txt) with `<TICKER>` and `<PRICE>`
   substituted:

   | Ticker | Price (from bot capture, 2026-05-18) |
   |--------|--------------------------------------|
   | NVDA   | $222.32                              |
   | AMD    | $420.99                              |
   | TSLA   | $409.99                              |

2. **Compare** Gemini's answer side-by-side with the matching `<ticker>-bot.txt`
   file. Treat both as anonymous — don't peek at labels until you've decided
   which one you'd actually trade. Score on substance, not format (both are
   formatted now).

3. **Vote** per ticker: `prefer-bot` / `prefer-gemini` / `tie`.

## Acceptance gate (from TODO #1)

3/3 must be `prefer-bot` or `tie` for this PR to merge.

- 3/3 in those buckets → push commit `6c90ed6` (`git push origin master`).
- Any `prefer-gemini` vote → iterate. Capture the specific gap (e.g. "Gemini's
  AMD Bear Case named two specific levels; ours named one") as a new TODO.

## What this PR ships (what to look for in the bot output)

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

Since the Gemini prompt now mirrors this skeleton, look for whether the bot's
content inside each section is *more specific and better-evidenced* than
Gemini's, not whether it has more sections.

## Files

- `GEMINI-PROMPT.txt` — format-matched blind-compare prompt
- `nvda-bot.txt` / `amd-bot.txt` / `tsla-bot.txt` — bot embeds captured live
  during Phase B verification
- `_scores.txt` — Phase B heuristic auto-score + manual recount (29/30)
- `README.md` — this file
