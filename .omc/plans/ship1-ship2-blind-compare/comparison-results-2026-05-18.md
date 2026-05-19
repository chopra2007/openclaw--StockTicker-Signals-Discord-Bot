# Blind compare result — 2026-05-18

**Outcome: 0/3 prefer-bot or tie** (TODO #1 acceptance gate fails)

Bot lost all three tickers on substance. The format-pack delivered by
Ship 1 + Ship 2 (commit 6c90ed6, already on origin/master) does land —
narratives have correct skeleton, evidence tags, level arrows, relative
dates. The losses are not about formatting.

The losses cluster around four substance gaps now tracked as TODOs
#10 (`levels.py` returns no SL/TP for some tickers), #11 (narrator
falls back to "analysts are calling long" prose when evidence is
thin), #12 (horizon-anchor mismatch — NVDA SL $178 framed as 2-day
catalyst trade), and #13 (no forward-dated catalyst ingest beyond
earnings).

## Per-ticker reasoning

### NVDA — Gemini wins (substance)

| Axis | Bot | Gemini |
|------|-----|--------|
| Thesis | "Short-term breakout above current range is possible" — vague | "Underpriced Blackwell volume shipments + hyperscaler commitments not captured in conservative Q1 metrics; revenue beat to $83B vs $79.2B consensus" — falsifiable |
| Catalysts | Real revenue ($68.13B +73.2% YoY) + earnings date — but also leans on "Multiple high-conviction YouTube analysts (Wicked Stocks, Lottery Stocks, CheddarFlow, Real Shadow Trader) calling long" | Earnings on May 20 *plus* a second dated catalyst (May 28 supply confirmations). No appeal-to-influencer. |
| Levels | SL $178 (-21% drawdown — 20-day support anchor, doesn't match a swing thesis); TPs $227 / $231 / $266 (ATR-based, $227 is +2.2% — too tight) | SL $209 (-6%, realistic); TPs $236 / $245 / $255 with named rationale (psych resistance / 1.618 fib / 28x P/E target) |
| Bear Case | "If guidance is cut or growth slows below +73.2% YoY" — citing itself; `[evidence:youtube]` tags don't tie to specific clips | Three named failure scenarios each with a price floor ($198 / $195 / cap below $82B) |

Bot has the live evidence; Gemini has the thesis. → tied to TODO #11
(influencer prose), TODO #12 (horizon-anchor mismatch), TODO #13
(forward-dated catalysts).

### AMD — Gemini wins (decisively)

| Axis | Bot | Gemini |
|------|-----|--------|
| Levels | **SL $130 — that's -69% from spot $420.99.** TP1/TP2/TP3 all `—`. | SL $395 (-6%); TPs $448 / $465 / $485 with named technical reasoning |
| Catalysts | Revenue $10.27B + a chart pattern at $203.79 | Meta 6-gigawatt partnership + MI450 accelerators + sequential rev guidance $11.2B + two dated catalysts |
| Bear Case | Two sentences, both about "below $203.79" — same level twice | Three named failure scenarios with distinct price floors ($365 / $350 / $335) |

A trade plan with no TP levels is not a trade plan. → tied to TODO #10
(SL/TP completeness), TODO #13 (forward dated catalysts).

### TSLA — Gemini wins (decisively)

| Axis | Bot | Gemini |
|------|-----|--------|
| Levels | **SL `—`. TP1/TP2/TP3 all `—`.** Body text literally said "no specific stop-loss or target levels are supplied". | SL $435 (-6% from spot, against a bearish thesis); TPs $385 / $368 / $350 with structural rationale |
| Direction | Bullish | Bearish — and Gemini actually defends it ("Model Y price hike is margin-defense not demand strength; subsidized Model 3 leases + casting inventory logjams") |
| Catalysts | Revenue $22.39B + "unusual options activity" — that's the whole list | Two dated catalysts (May 26 registration data, June 5 delivery data) with mechanism |
| Bear Case for own thesis | Cites itself ("price decline back below $392.66 indicates potential weakness") | Three named bull-case scenarios with prices ($445 / $452 / $470) |

→ tied to TODO #10, #13.

## Methodology note (added 2026-05-18 mid-session)

The original `GEMINI-PROMPT.txt` was a 5-line free-prose ask — that
would let Gemini answer unstructured while the bot is forced through a
deterministic skeleton, producing a format-driven bot-win that wouldn't
isolate substance. The prompt was rewritten mid-session to:

1. Hand Gemini the same skeleton (TL;DR / variant-perception / Catalysts
   / Risk Considerations / Bear Case / Risks & mitigants / Trade Plan
   table with named columns).
2. Inject each ticker's current price ($222.32 / $420.99 / $409.99) so
   levels start from the same anchor.
3. Require commit-to-numeric levels, no "—" placeholders, no hedge
   boilerplate.

This isolates substance. The bot's lossesabove are not formatting
artifacts.

## Verification trail

- Bot captures: `nvda-bot.txt`, `amd-bot.txt`, `tsla-bot.txt`
  (rendered 2026-05-18 via direct `aggregator._compute_all()` calls
  bypassing Discord — same code path as a real `!all`, no cache).
- Gemini captures: `nvda-gemini.txt`, `amd-gemini.txt`, `tsla-gemini.txt`
  (pasted from gemini.google.com using the format-matched prompt).
- Heuristic + manual recount: `_scores.txt` (28/30 against the
  internal sub-change checklist — passes the original ≥27/30 floor;
  fails the substance gate above).
- Engine telemetry: all 3 runs logged `narrative_status=ok`; zero
  contradict-retries, zero missing-section retries.

## What to do next (in priority order)

1. **TODO #10** — fix `levels.py` so AMD/TSLA-style anchor-density
   failures produce a fallback band rather than `—` placeholders. The
   highest-leverage single fix; would have made both AMD and TSLA
   captures meaningful.
2. **TODO #11** — `quality_bar.py` guard against appeal-to-influencer
   prose. Smallest surface area, biggest visible substance win.
3. **TODO #13** — forward-catalyst ingest (new scanner). Highest-effort
   but addresses the consistent gap Gemini exploits across all 3
   tickers. Per TODO #7 discipline, pre-flight each data source from
   this VPS before writing code.
4. **TODO #12** — horizon-anchor reconciliation in `levels.py` +
   `narrator.py`. Smaller in scope than #10, but specifically targets
   the NVDA loss.

Re-run this blind compare (TODO #1) after the next 1–2 substance
fixes land. Acceptance gate stays at 3/3 prefer-bot or tie.
