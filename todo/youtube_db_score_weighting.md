# YouTube DB Score Weighting Research

**Status:** OPEN
**Created:** 2026-05-30

## Goal

Decide whether YouTube database signals (captions, ticker mentions, chart levels from videos) should be explicitly weighted in the `!all` scoring formula, and if so, figure out how to do it.

## Background

The `!all` footer currently shows a score breakdown like:
`Score: 45 (news=15, ape=10, tech=6, llm=14)`

YouTube sources (`youtube_signals_db`, `youtube_levels_db`, `youtube_evidence_db`) show up in the **sources** list, meaning they were fetched and passed to the narrator — but their contribution to the numeric score is unclear or absent from the visible breakdown.

## Questions to answer

1. Does the scorer currently receive YouTube DB data as an input? If so, is it weighted at all, or silently ignored?
2. If YouTube data IS reaching the scorer, why doesn't it appear in the score breakdown?
3. What weight would be appropriate? YouTube mentions tend to lag (video posted hours before the move), so over-weighting could introduce noise.
4. Should levels extracted from YouTube (buy zone, TP) influence the score, or only the text thesis?

## Files to start with

- `consensus_engine/scoring/` — find the main score computation
- `consensus_engine/alerts/all_command/aggregator.py` — where youtube_* keys are gathered
- `consensus_engine/alerts/all_command/narrator.py` — how YouTube data feeds the LLM

## Possible next steps (priority order)

1. Grep the scorer for `youtube` to see if it's referenced at all.
2. Add a test: monkeypatch a non-empty `youtube_signals_db` and assert the score changes.
3. If unweighted: decide on a weight (suggest starting at 5–10 pts, capped) and add it.
4. Add `yt=N` to the score breakdown display so it's visible.

---

## RESOLVED 2026-05-31 (run `all-quality-and-yt-score`)

**The premise was wrong: YouTube is NOT ignored — it's weighted, just mislabeled.**

### Answers (with code evidence)
1. **Does the scorer receive YouTube data?** Yes. `cross_reference.score_ticker` calls `_get_youtube_context(ticker)` (cross_reference.py:306) which queries `get_youtube_signals_for_ticker` + `get_youtube_evidence_for_ticker` and computes `score_boost = {high:15, medium:10, low:5}[top_conviction]` (cross_reference.py:248). NOTE: it's the scorer's OWN query — the aggregator's separately-fetched `youtube_levels_db`/`youtube_options_db`/`youtube_visual_db` go only to the narrator/embed, never the score.
2. **Why didn't it show in the breakdown?** It was folded into `llm`: `breakdown.llm_boost += youtube_pts` (cross_reference.py:362, now changed). `ScoreBreakdown` had no `youtube` field.
3. **What weight?** It's ALREADY 5/10/15, conviction-tiered, capped at 15. (No new weight to invent.)
4. **Levels vs text?** YouTube *levels* influence the trade plan via `levels.extract_anchors_from_youtube_levels` (anchor tiers), separate from the score. The score boost comes from signal *conviction*, not levels.

### SHIPPED — visibility fix (commit `2196ba5`, live-verified)
Split YouTube into its own `ScoreBreakdown.youtube` field → footer now shows `yt=N`. **Display-only: `total` and `compute_direction` are provably unchanged** (youtube added to the total property AND `_BULLISH_BIASED_FIELDS`; serializer + vault_writer updated; regression test `tests/test_yt_score_visibility.py` asserts total + direction parity). **Live:** `!all NVDA` → `Score: 58 (news=15, tech=4, llm=9, yt=15)`; `!all AMD` → `yt=5`.

### Weight-VALUE change — REVIEW GATE, recommend NO change (pending user blessing)
The 5/10/15 values live in the SHARED `score_ticker` (main alerting engine uses it too), so changing them alters which alerts fire — kickoff gate #2. Recommendation: **leave as-is.** They are already conviction-tiered, capped at 15 (≈ the same ceiling as `llm_boost_max=15`), and the original lag concern is mitigated by the 7-day query window + conviction gating. No evidence the current values are miscalibrated. Adding visibility (done) ≠ changing alert behavior (not done, not recommended).

**STATUS: DONE 2026-05-31.** Research settled (YouTube already weighted 5/10/15, was mislabeled as `llm`); visibility fix shipped & live-verified (commit `2196ba5`, `yt=N` footer); weight values **blessed UNCHANGED by the user** at the review gate. No further work.
