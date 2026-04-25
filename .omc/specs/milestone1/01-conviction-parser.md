# Spec 01 — Conviction Parser (Q9)

**Date:** 2026-04-24
**Branch:** `claude/multi-agent-tmux-setup-zWYEQ`
**Audit reference:** `plans/AUDIT_RESEARCH_2026-04-24.md` Q9 + M6
**Sizing verdict:** SMALL (~50 LOC). M6 already wired in `engine.py:298–305`; this spec alone activates it.

---

## Problem

99.1 % of alerts ship with `base_score=25` (MEDIUM). Reason:
1. `models/text_model.py:25` prompts the LLM with `"conviction": "high|medium|low"` and zero rubric. The model defaults to `"medium"`.
2. `consensus_engine/analysis/tweet_parser.py:55–57` reads the LLM field with `.get("conviction", "medium")` then maps unknown values to MEDIUM.
3. `_fallback_parse` (`tweet_parser.py:107–132`) hard-codes `Conviction.MEDIUM`.

Because every alert is MEDIUM (`base_score=25`), the HIGH-conviction market_ok exemption already coded at `engine.py:301–305` (`is_high_conviction = base_score >= 30`) is permanently inert. M6 is wired but never triggered.

## Fix

Add a deterministic heuristic — `_infer_conviction(text, options) -> Conviction` — that runs alongside the LLM output and is decisive when the heuristic produces a clear HIGH or LOW signal.

### Heuristic rules

**HIGH** (returns `Conviction.HIGH`) — any of:
- Options trade with strike + expiry + (target_price OR profit_target_pct) AND text contains an SL/stop reference (`/\b(sl|stop|stop loss|stop-loss)\b/i`).
- Text matches an explicit conviction keyword: `/\b(highest conviction|high conviction|HC|all in|loaded up|loading up|backing up the truck|YOLO)\b/i`.
- Text contains both an entry price ("at <number>" or "@ <number>") **and** ≥1 target price (`/\b(target|🎯|tp)\b/i`) **and** an SL reference.

**LOW** (returns `Conviction.LOW`) — any of:
- Hedging language: `/\b(watching|might|maybe|could|considering|thinking about|tentative|on watch|keeping an eye)\b/i`, AND no options trade, AND no specific entry/target/SL trio.
- Pure sentiment: text has no ticker callout AND no options details (the existing TweetType=SENTIMENT path handles this — heuristic falls through to MEDIUM in that case, as conviction is moot for non-actionable tweets, but downstream gates already filter SENTIMENT).

**MEDIUM** — default when neither HIGH nor LOW rules match.

### Application

In `_parse_model_payload`:
```python
llm_conviction = conv_map.get(raw_conv, Conviction.MEDIUM)
heuristic = _infer_conviction(original_text, options)
conviction = _resolve_conviction(llm_conviction, heuristic)
```

`_resolve_conviction(llm, heuristic)`:
- If `heuristic` is HIGH or LOW → return `heuristic` (heuristic wins when decisive).
- Else (heuristic == MEDIUM) → return `llm` (LLM is preserved when heuristic is not decisive — keeps existing `conviction="high"` / `"low"` LLM outputs intact).

In `_fallback_parse`:
```python
conviction=_infer_conviction(text, None)
```
(replaces the hard-coded `Conviction.MEDIUM`).

---

## Files touched

| File | Change | Approx delta |
|------|--------|--------------|
| `consensus_engine/analysis/tweet_parser.py` | Add `_infer_conviction`, `_resolve_conviction`; wire into `_parse_model_payload` and `_fallback_parse`. | **+45 / −2** |
| `tests/test_conviction_inference.py` | New file: heuristic table + integration with parser. | **+~140** (test, not LOC budget) |

No YAML changes. No DB migrations. No new dependencies.

---

## Verification

### Tests (RED → GREEN)
- `tests/test_conviction_inference.py` — new test file:
  - HIGH: options + strike + expiry + SL → HIGH.
  - HIGH: "highest conviction" keyword → HIGH.
  - HIGH: entry + target + SL trio → HIGH.
  - LOW: "watching $AAPL" → LOW.
  - LOW: "might buy $TSLA" → LOW.
  - MEDIUM: plain ticker callout with no signals → MEDIUM.
  - LLM HIGH preserved when heuristic is MEDIUM (LLM wins on indecisive heuristic).
  - LLM MEDIUM upgraded to HIGH when heuristic decisive (heuristic wins).
  - LLM HIGH downgraded to LOW when heuristic decisive LOW (heuristic wins).
  - Fallback path uses heuristic instead of hard-coded MEDIUM.

### Regression
- `tests/test_tweet_parser.py` MUST stay green. Specifically:
  - `test_parse_llm_response_type_a` (text="original text", LLM=medium) → MEDIUM (no heuristic signal).
  - `test_parse_llm_response_malformed_json` (text="$AAPL looking strong, buying calls", fallback) → MEDIUM (no entry/target/SL trio, no HIGH keyword).
  - `test_parse_llm_response_type_b` (macro, LLM=medium) → MEDIUM.
  - `test_parse_llm_response_type_d` (sentiment, LLM=low) → LOW preserved.
- `tests/test_require_market_confirmation_exemption.py` MUST stay green. M6-lite path unchanged.
- All 518 existing tests still pass.

### Post-deploy SQL probes
After 24 h:
```sql
-- Was 99.1% MEDIUM (base_score=25). Should now show distribution.
SELECT base_score, COUNT(*) AS n
FROM alert_history
WHERE created_at >= strftime('%s','now','-1 day')
GROUP BY base_score
ORDER BY base_score;
```
Expected: ≥10 % of alerts at `base_score=30` (HIGH) once analysts with options-with-SL formats start firing. If still ~99 % at 25, heuristic rules are too narrow — re-tune.

After 7 d:
```sql
-- HIGH-conviction alerts should now be hitting the M6-lite exemption path.
-- Look for alerts with base_score=30 that resolved despite market_ok=False.
SELECT COUNT(*) AS high_conv_market_failed_but_alerted
FROM alert_history h
WHERE h.base_score = 30
  AND h.created_at >= strftime('%s','now','-7 days');
```
Expected: non-zero, demonstrating M6-lite is now active.

---

## Out-of-scope

- LLM prompt rubric improvements (`models/text_model.py`). The heuristic is more reliable than relying on the LLM; updating the prompt is a separate concern and would risk regressing existing test cases that mock specific LLM outputs.
- Conviction tier tuning. The `_CONVICTION_SCORES` map (HIGH=30, MEDIUM=25, LOW=20) and `high_conviction_threshold=30` config are unchanged.
- M6 ("exempt HIGH from `require_market_confirmation`") — already implemented at `engine.py:298–305`. This spec activates it.
