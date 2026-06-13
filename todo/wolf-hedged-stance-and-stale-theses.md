# Catch Wolf's hedged direction changes + retire stale theses

**Status:** OPEN
**Created:** 2026-06-08

## The goal (plain English)
When Wolf changes his mind about a stock in a soft, hedged way — or when an old call
of his goes stale because the move already happened — the bot should notice and update,
instead of keeping showing his old view.

## What this is (the IGV story that prompted it)
The 2026-06-08 session shipped the "direction guard" fix (item #1) so the bot reports
Wolf's TRADE STANCE, not the near-term price tick. That part is built and live
(`wolf.direction_guard.enabled: true`). But verifying against Wolf's real emails showed
the IGV-shows-bull problem had a DIFFERENT root cause than the plan assumed:

1. **Hedged stance-shifts are dropped.** Wolf was bullish-to-target on software (IGV) —
   "trade up to the $97–100 / 200-day" — through ~06-01. By 06-04/06-05 he flipped
   bearish: "the surge is technicals and positioning, not fundamentals," "now that the
   move up is done… I'm looking for leading signals to short," "IGV breaking its 200-day."
   The extractor (gpt-oss-120b, deliberately conservative to avoid over-extraction)
   captured his CLEAR semis short (SOX → SMH bear, "acting") but NOT the hedged IGV
   bearish lean — it produced no fresh IGV thesis at all from the 06-04/06-05 emails.
2. **No staleness decay.** Because no new IGV thesis was extracted, the old 06-01 IGV
   BULL thesis just persisted as "active," even though Wolf's own words said the move was
   already done. Nothing retires a thesis when the author moves on.

Net effect: every other tech/semis thesis read correctly bearish (NDX, SMH, TECHNOLOGY,
SPX all bear by 06-05) — only the stale IGV bull was wrong, and it had to be invalidated
by hand this session.

## What was done this session (stop-gap)
- Manually invalidated the stale IGV bull (macro_theses id was 97 pre-rebuild; the rebuild
  renumbers ids, so re-find it by `scope_key='IGV' status='active' direction='bull'`).
- The direction-guard prompt rule is live and correct for CLEAR stances; it is not the
  bottleneck here.

## Possible next steps (priority-ordered)
1. **Hedged stance-shift extraction.** Teach the extractor (a gated clause in
   `_DIRECTION_GUARD_RULE`, `consensus_engine/analysis/wolf_email_parser.py`) to capture a
   stance SHIFT even when wrapped in performance language: "now that price finished the
   move up to <level>, the risk/reward favors shorting" / "I'm watching for signals to
   short" = a fresh BEAR stance on that instrument. MUST A/B against several real emails to
   confirm it doesn't re-introduce over-extraction (the whole reason gpt-oss-120b was
   chosen was that it does NOT over-extract — see config comment near `wolf.extraction_models`).
2. **Staleness decay.** Add a rule that an active thesis whose target/level has been
   reached, or that hasn't been re-affirmed in N days while the rest of its sector flipped,
   gets demoted/invalidated. Careful: must not wrongly kill valid long-running theses.
3. Consider letting a clear SECTOR flip (e.g. SMH bear "acting") cast doubt on a stale
   same-complex thesis of the opposite direction (IGV bull) — a cross-thesis consistency check.

## Files / code involved
- `consensus_engine/analysis/wolf_email_parser.py` — `_EXTRACTION_USER_TMPL` rules block
  (~83-99), `_DIRECTION_GUARD_RULE` (~104), `_extract_theses_llm` (305), `_coerce_thesis`.
- `consensus_engine/analysis/wolf_theses.py` — ingest/flip path (181-189), staleness would
  live here or in a new sweep.
- Evidence: Wolf emails 06-04 `19e93fa7362eb2d4`, 06-05 `19e96023b60514d2` /
  `19e991ef58f54757` (fetch via gmail_watcher; bodies are HTML — use `wep.decode_html`).

## Open questions
- Is "hedged bearish lean" even a thesis the bot should fire on, or is "no active thesis"
  (what invalidation leaves) the honest state until Wolf actually shorts? Arguably the
  latter is correct for IGV specifically — he says he's *watching to* short, not short yet.
- Staleness threshold (days) and whether "target reached" is detectable from stored levels.

### Session notes — 2026-06-13 (discover run todo-sweep)
- **The TODO's proposed prompt-clause fix was tested on the 3 real emails (+3 more) and it BACKFIRES** — never catches the hedged IGV bear (0/3), manufactures a WRONG IGV bull (2/3), and over-extracts/suppresses on other emails. **Do NOT ship it.** (Verified independently by a second agent.)
- **User-decision (recommended):** "no active thesis" is the honest state for IGV — he's *watching* to short, and the next day he's still bull-to-target. Don't force a hedged bear.
- **Real wins instead:** (a) a clean prompt clause for "bounce to a **lower high** / **H&S top** / failed breakout to fade" = BEAR (verifier tested it: fixes the live SPX/NDX mislabel 5/5, zero false positives); (b) a nightly **staleness sweep** (demote-not-delete; **tiered age caps** 90d acting/imminent + 30d forming/diverging per Gemini review; clock-reset-on-reaffirm). Also a hygiene fix: clear wolf_beneficiaries rows when a thesis is invalidated (orphan COIN-short rows exist for ids 114/126).
- Full plan: .claude/discover/todo-sweep-2026-06-13/research/wolf.md + final-plan.md §3/§4/§5.
