# Raise Wolf email extraction input cap (12,000 → 40,000 chars)

**Status:** DONE
**Created:** 2026-06-05

Goal: stop silently dropping the back half of long Wolf newsletters. The thesis
extractor only read the first 12,000 chars of each email body; the big "Daily
Wrap" editions front-load macro text and put the actual trade calls *after* that,
so those calls were invisible.

## Evidence (measured 2026-06-05)
- Counted all Wolf emails live from Gmail: **94 total**, **26 over 12,000 chars**
  (largest 31,934; median of all 94 is ~4,212 — most are fine).
- Before/after on the largest real email: **0 theses at the 12,000 cap → 6–7 at
  40,000** (recovered real ideas: WTI Crude, REMX, URA, BTC — all past char 12,000).
- 40,000 chars ≈ 10k tokens, trivial for the chain's 130k–1M context. Output
  stays small (~700 tokens), so `extraction_max_tokens=4096` is still ample.

## What shipped (commit 12d242a)
- New config `wolf.extraction_input_cap: 40000` (was a hardcoded 12000).
- Applied in BOTH `_extract_theses_llm` AND `_verify_quotes_against_body`
  (`consensus_engine/analysis/wolf_email_parser.py`) — they must use the same cap
  or quotes from the email tail get falsely rejected.
- Live-verified through the engine; 211 Wolf tests + full suite (1707) pass.

## Files
- `config/consensus.yaml` (wolf.extraction_input_cap)
- `consensus_engine/analysis/wolf_email_parser.py` (both cap sites)

## Follow-ups / if revisited (set back to Active)
- **Latency:** a 40k-char email takes ~30–35s on the free lead (gpt-oss-120b:free)
  vs the 60s timeout — fine, but the big emails are now slower. If timeouts ever
  appear, lead the `wolf.extraction_models` chain with a paid model (deepseek-v4-flash
  is faster) instead of the free one.
- Extraction count varies run-to-run (saw 7 then 4 on the same email) — free model
  + selective prompt + temp 0.1, not the cap.
- Separate lever NOT changed: this is the INPUT cap. Output cap
  (`extraction_max_tokens=4096`) was checked and left alone (output stays ~700 tok).
