# Two small live-path fixes: social-source de-dup + alert idempotency

**Status:** DONE 2026-07-05
**Created:** 2026-07-05

**CURRENT STATUS (2026-07-05):** Both SHIPPED.
- **Fix 1 (idempotency) — LIVE.** Reordered `main.py`: `insert_alert` now write-ahead-arms the
  `alert_history` cooldown row BEFORE `send_instant_ping`, and a new `db.delete_alert()` rolls the
  row back if the send returns None. The UNIQUE-hash alternative was rejected — the bug is a
  *missing* insert (crash before write), which a UNIQUE key can't fix. Correctness fix in the safe
  direction (a rare missed ping instead of a lost cooldown). Test added; 13 related tests green.
- **Fix 2 (social family de-dup) — BUILT flag-OFF, intentionally not flipped.** Same-crowd social
  sources (ApeWisdom/StockTwits/Reddit) collapse to one independent vote in `_compute_social_breakdown`,
  behind `features.social_family_dedup.enabled` (default false, demotion-only). Blast radius measured
  on `decision_snapshots`: **0 of 3,134 past alerts would change** (1,706 had one retail-crowd term,
  none ever had two at once — StockTwits scanner is off, Reddit needs ≥2). So it's correct + safe but
  a no-op on current data → stays OFF, answering the item's own "is it worth the risk?" (no, defer the
  flip until source mix changes).

## What this is
Two small, related refinements from the #61 research run that both touch the LIVE alert path, so
each needs a shadow/staged check before flipping (that's why they weren't shipped in the research
session). Lower priority than the honest-alert overhaul (#63) and the forward-loggers (#62).

## 1. Trim correlated social "agreement" (smaller than first pitched)
- **Re-verified 2026-07-05:** the bot ALREADY enforces actor-independence + distinct-actor
  safeguards and requires an actor-independent hard corroborator (SEC/news/options) before trusting
  agreement — `consensus_engine/cross_reference.py:890`, `has_independent_corroboration` at `:783`,
  the I3 safeguard. So the crude "any 2 sources = confirmation" double-count is LARGELY already
  handled. The residual gap is narrow: two SOCIAL crowds (StockTwits ≈ Reddit/ApeWisdom) in the same
  family still count as two independent votes.
- **Fix:** a deterministic source-family rule — sources in the same family collapse to one
  independent vote for the confirmation count. Do NOT cluster on ~1 month of data (unstable); use a
  hand-set family map first, measure later with a nested-logistic LR test once more history accrues.
- **Value caveat:** the honesty eval showed the score has ~no measurable edge anyway, so this
  refinement's real impact is modest. Build behind a flag, measure the historical blast radius (how
  many past alerts change), then decide whether to flip.

## 2. Alert idempotency (crash-safe)
- **Verified:** `alert_history` (`db.py:94`) is append-only with NO UNIQUE key; dedup is a
  COUNT-based cooldown (`db.py:1626-1693`), and `main.py:1382` sends the Discord ping BEFORE
  `main.py:1386 insert_alert` writes the cooldown row. A crash between send and insert leaves a sent
  alert with no cooldown armed → the next different tweet on that ticker isn't throttled. The Wolf
  `#news` lane already does this right (`wolf_news_alerts.dedupe_key UNIQUE`).
- **Fix (cheapest):** move `insert_alert` BEFORE `send_instant_ping` (write-ahead the cooldown row),
  or add a content-hash `UNIQUE` on `alert_history` + `INSERT OR IGNORE`. Longer term, fold the
  tweet lane onto the proven Wolf outbox shape.
- **Gate:** LIVE alert path → shadow/staged check before shipping (DoD).

## Files
- `consensus_engine/cross_reference.py` (independence logic), `consensus_engine/main.py:1382-1386`
  (send/insert ordering), `consensus_engine/db.py` (alert_history schema, cooldown query).

## Open questions
- Given the ~nil measured edge, is the social-dedup worth the live-path risk at all, or defer
  indefinitely? (The idempotency fix is worth doing regardless — it prevents lost throttling.)
