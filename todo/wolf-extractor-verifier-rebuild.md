# Rebuild the Wolf newsletter reader as a trap-proof extractor→verifier

**Status:** OPEN
**Created:** 2026-07-05

## What this is
From the #61 research run (deepest lens; user pick "rebuild Wolf reader"). The daily "Wolf on Wall
Street" newsletter reader still can't reliably tell a genuine trend reversal from an EXPECTED
counter-trend bounce inside an unchanged bearish view (the IGV incident: bot showed IGV as an
active BULLISH call when Wolf was waiting to SHORT the bounce at resistance). A prior "conditional
language" prompt attempt BACKFIRED (invented false bulls 2/3, missed the real bear 0/3). This is a
LARGE build (~3+ days) — both adversarial reviewers said do it AFTER the measurement work, which is
why it wasn't built in the research session.

## The design (ready — full detail in `.omc/plans/bot-research-build/lens3-wolf-nlp.md` §3)
Today's extractor (`consensus_engine/analysis/wolf_email_parser.py`) is a SINGLE-SHOT prompt with
the IGV case literally hard-coded in `_DIRECTION_GUARD_RULE:108`. Replace with:
1. A first-class **`phase` axis** beside `direction`: pending / active / counter_trend_bounce /
   reversal / invalidated / neutral_context — a small state machine with evidence-guarded
   transitions (`bear→bull` ONLY via an entailed reversal cue, so an up-tick can't silently become
   a bull).
2. An **extractor→verifier pipeline**: extract ×3 (consistency vote) → a DISCRIMINATIVE verifier
   that can only VETO (never mint) using entailment (NLI) + assertion-status (planned vs active) →
   a selective-prediction confidence gate (emit / downgrade-to-pending / abstain) → deterministic
   state update. Trap-proof by construction: the verifier can only remove a thesis, never invent one.

## Critical constraints (verified 2026-07-05)
- **Do NOT use a local torch/DeBERTa NLI model** — the box has torch NOT installed, 7.6GB RAM with
  the engine already at ~2.7GB → OOM risk. Use a **hosted different-family free model** as the
  cross-family NLI/entailment judge instead (lens3 §2.8). Same anti-trap property, no heavy install.
- **HARD EVAL GATE** — must pass the eval set already snapshotted to
  `.omc/plans/bot-research-build/wolf-eval-corpus/` (5 emails: IGV incident `19e7291f`, the missed
  hedged-bear `19e96023`, + A/B emails 06-04/06-05b/06-12). Gold labels + protocol in lens3 §3.3.
  Score BOTH recall AND false-positive count: **zero IGV false bulls, no net increase in invented
  theses** vs the current extractor — the exact two-sided test the failed A/B skipped. A change that
  raises recall but adds ANY IGV false bull FAILS. Add the fixtures as `tests/` cases.
- Blast radius is LOW (Wolf is a separate `#news` pipeline, never imported by scoring) but
  `wolf_call_outcomes` has only 39 scored rows — you can prove the eval-set gate, NOT a real-outcome
  improvement. Frame success as "passes the trap-proof eval," not "improves live P&L."

## Files
- `consensus_engine/analysis/wolf_email_parser.py` (extractor + `_DIRECTION_GUARD_RULE` +
  `_EXTRACTION_USER_TMPL`), the wolf `macro_theses` schema (add `phase`), `consensus_engine/db.py`.
- Eval corpus + design: `.omc/plans/bot-research-build/wolf-eval-corpus/` + `lens3-wolf-nlp.md`.

## Open questions
- Which hosted free model as the NLI judge (must be a DIFFERENT family from the Groq extractor for
  uncorrelated errors)?
- Re-fetch the 2 unpinned A/B emails ("06-12 Afternoon", "06-11 Worm Turning") for a fuller eval set
  (Gmail OAuth token is 7-day; snapshot early).
