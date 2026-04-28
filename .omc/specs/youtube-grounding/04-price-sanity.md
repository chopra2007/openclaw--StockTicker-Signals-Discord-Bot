# Spec 04 — Price Sanity at Alert Time (Layer 4)

**Goal:** Block Discord alerts where the cited price level deviates wildly from the current live price, allowing for stock splits via ratio-bucket detection. Catches numerical hallucinations even when ticker grounding succeeded (e.g., model spelled the ticker correctly but invented the price levels).

**Sizing:** SMALL (~90 LOC + ~80 test LOC).

**Important:** This layer applies *only at alert time*, never at persistence time. We keep audit rows in DB so future investigators can replay.

---

## Why alert-time only

Three reasons:

1. **Audit trail.** Every row in `youtube_levels` and `youtube_setups` is forensically valuable; deleting them would hide pattern-of-failure data we need for Layer 1/2 effectiveness measurement.
2. **Live price flakiness.** Finnhub free tier rate-limits at ~60 req/min. Persistence runs unattended; if Finnhub is rate-limited, we'd erroneously kill legitimate persistence. Alert path has time to retry / fail gracefully (skip alert, log warning).
3. **Codex's plan was over-aggressive here.** Persistence-time price gates are a category error: the row is correct in the *historical* sense ("this is what the model said") and only *operationally* wrong (don't alert humans on it).

---

## (a) New module: `consensus_engine/analysis/price_sanity.py`

```python
"""Price-level sanity checks for alert-time gating.

A hallucinated price level usually deviates by >2× from the live price.
A real one is usually within ±30%, with occasional stock-split factors
(2, 3, 4, 5, 10, 20× either direction).

This module checks the deviation and tolerates split factors so we don't
falsely reject pre-split levels in re-aired or re-uploaded videos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("consensus_engine.analysis.price_sanity")

# Stock split factors observed historically. Bidirectional: includes 1/N for
# pre-split levels in re-aired videos, plus N for post-split levels in
# previously-cached videos.
_SPLIT_FACTORS: tuple[float, ...] = (
    1.0,
    2.0, 1 / 2,
    3.0, 1 / 3,
    4.0, 1 / 4,
    5.0, 1 / 5,
    10.0, 1 / 10,
    20.0, 1 / 20,
)

# Tolerance band around each ratio. ±25% means a level priced at 850 is
# acceptable against a 145 live price if 850/145 is within 25% of 5x → fails;
# but 730/145 ≈ 5.03 would pass. NVDA's actual hallucinated 850 vs live 145
# (~5.86×) sits between 5× and 10× and outside ±25% of either, so → blocks.
_RATIO_TOLERANCE = 0.25


@dataclass(frozen=True)
class SanityResult:
    accepted: bool
    reason: str  # "ok", "no_live_price", "implausible_ratio", "implausible_zero"


def check_price_plausible(
    level_price: float,
    live_price: float | None,
) -> SanityResult:
    """Return SanityResult for one (level, live) pair.

    Caller decides what to do with `accepted=False`. Common policy: skip
    Discord alert, log warning at WARNING level, mark row suppressed=1
    with reason='price_sanity'.

    Note: when live_price is None or 0 (Finnhub error / rate limit), we
    accept (fail-open). The alternative — fail-closed — would gate every
    alert behind a 3rd-party API and break alerts whenever Finnhub is down.
    """
    if not isinstance(level_price, (int, float)) or level_price <= 0:
        return SanityResult(False, "implausible_zero")
    if not live_price or live_price <= 0:
        return SanityResult(True, "no_live_price")

    ratio = level_price / live_price
    for factor in _SPLIT_FACTORS:
        if abs(ratio - factor) / factor <= _RATIO_TOLERANCE:
            return SanityResult(True, "ok")
    return SanityResult(False, "implausible_ratio")
```

**LOC delta:** +50 lines.

---

## (b) Wire into Path A alerts (`_send_two_stage_alerts`)

**File:** `consensus_engine/scanners/youtube.py`
**Current function:** lines 395–479

Currently iterates HIGH-conviction signals and constructs a Discord message. Add a price-sanity gate that runs once per alert candidate, before formatting.

```diff
 async def _send_two_stage_alerts(
     display_name: str,
     signals,
     levels,
     setups,
     catalysts,
     bundle_spans,
     min_confidence: float,
     require_verified: bool,
 ) -> None:
     """Fire one Discord alert per HIGH-conviction, unsuppressed ticker."""
     from consensus_engine.alerts.commands import _format_ts, _format_verified
+    from consensus_engine.analysis.price_sanity import check_price_plausible
+    from consensus_engine.api_adapters import get_live_quote_price

     sent: set[str] = set()
     for sig in signals:
         if sig.suppressed or sig.ticker in sent:
             continue
         if sig.conviction.value != "high" or sig.direction.value not in ("long", "short"):
             continue
         if sig.classifier_confidence < min_confidence:
             continue

+        # ── Price sanity: fetch live price ONCE per ticker, gate per-setup ──
+        # Critic note: previous draft suppressed all of a ticker's setups when
+        # any one failed. Per-setup gating now: only the failing setups (and
+        # their absorbed levels) are suppressed. Alert proceeds if ANY setup
+        # remains plausible. Sanity-failed setups still persist for audit.
+        tkr_setups = [s for s in setups if s.ticker == sig.ticker and not s.suppressed]
+        if tkr_setups:
+            live_price = await _safe_live_price(sig.ticker)
+            surviving_setups = []
+            for s in tkr_setups:
+                if s.entry_low is None:
+                    surviving_setups.append(s)
+                    continue
+                res = check_price_plausible(s.entry_low, live_price)
+                if res.accepted:
+                    surviving_setups.append(s)
+                else:
+                    log.warning(
+                        "price_sanity: suppressing setup %s entry=%.2f live=%s reason=%s",
+                        sig.ticker, s.entry_low, live_price, res.reason,
+                    )
+                    s.suppressed = True
+                    s.suppression_reason = "price_sanity"
+                    # Cascade-suppress any levels absorbed by this setup. Levels
+                    # share the ticker; price-sanity-bad levels get the same tag.
+                    for lv in levels:
+                        if (
+                            lv.ticker == sig.ticker
+                            and lv.price == s.entry_low
+                            and not lv.suppressed
+                        ):
+                            lv.suppressed = True
+                            lv.suppression_reason = "price_sanity"
+            if not surviving_setups:
+                # All setups failed sanity — block the signal alert entirely.
+                sig.suppressed = True
+                sig.suppression_reason = "price_sanity"
+                continue
+            # Replace tkr_setups with the surviving ones for downstream
+            # alert formatting (Discord message uses tkr_setups[0]).
+            tkr_setups = surviving_setups

         sent.add(sig.ticker)
         lines = [...
```

Helpers near top of file:

```python
async def _safe_live_price(ticker: str) -> float | None:
    """Return live quote price or None on any error. Logs at debug level."""
    try:
        from consensus_engine.api_adapters import get_live_quote_price
        return await get_live_quote_price(ticker)
    except Exception as e:
        log.debug("price_sanity: live quote failed for %s: %s", ticker, e)
        return None
```

**Note on `get_live_quote_price`:** the existing Finnhub real-time wrapper per CLAUDE.md ("Finnhub free tier: real-time quotes only (`/quote`)") is exposed today as `FinnhubAdapter._fetch_quote` (private, returns raw dict). The implementer should add a small public wrapper:

```python
async def get_live_quote_price(ticker: str) -> float | None:
    """Public price-only accessor over FinnhubAdapter._fetch_quote."""
    from consensus_engine.api_adapters import FinnhubAdapter
    raw = await FinnhubAdapter()._fetch_quote(ticker)
    return float(raw.get("c") or 0) or None
```

…or call the adapter directly inside `_safe_live_price`. Either way, no new dependency. The 5–10 line wrapper is in scope for this PR.

**LOC delta:** +25 lines (was +30; removed the redundant `_mark_price_sanity_failure` helper now that per-setup suppression happens inline).

---

## (c) Wire into Path B/C alerts

**File:** `consensus_engine/scanners/youtube.py`
**Current location:** lines 716–758 (the legacy alert block in `process_video`)

Apply the same gate to legacy alerts. Each ticker that reaches alert formatting also gets a price-sanity check.

```diff
                 for ticker_data in parsed.tickers:
                     if (
                         ticker_data.get("conviction") == "high"
                         and ticker_data.get("direction") in ("long", "short")
                     ):
                         sym = ticker_data.get("symbol", "")
+                        # Price sanity — per-setup gating (parity with Path A §b).
+                        # Tag failing setups in-memory so they don't appear in the
+                        # alert summary; only block the whole alert if NO setup survives.
+                        tkr_setups = [s for s in parsed.setups if s.ticker == sym]
+                        if tkr_setups:
+                            from consensus_engine.analysis.price_sanity import check_price_plausible
+                            live_price = await _safe_live_price(sym)
+                            survived = []
+                            for s in tkr_setups:
+                                if s.entry_low is None:
+                                    survived.append(s)
+                                    continue
+                                res = check_price_plausible(s.entry_low, live_price)
+                                if res.accepted:
+                                    survived.append(s)
+                                else:
+                                    log.warning(
+                                        "price_sanity: legacy suppressing setup %s entry=%.2f live=%s reason=%s",
+                                        sym, s.entry_low, live_price, res.reason,
+                                    )
+                                    s.suppressed = True
+                                    s.suppression_reason = "price_sanity"
+                            if not survived:
+                                log.warning(
+                                    "price_sanity: BLOCKING legacy alert for %s — all setups failed sanity",
+                                    sym,
+                                )
+                                continue
+                            # Only show survivors in the alert message:
+                            tkr_setups = survived
                         direction_label = ticker_data["direction"].upper()
                         lines = [f"🎬 **${sym} [{direction_label}]** — {display_name}"]
```

Path B/C does not write `suppressed` to DB, so we just `continue` past the alert send.

**LOC delta:** +10 lines.

---

## Verification

```bash
python3 -m pytest tests/analysis/test_price_sanity.py -v
python3 -m pytest tests/scanners/test_youtube_alerts.py::test_price_sanity_blocks_nvda_850 -v
```

Test cases (full set in Spec 06):
- `check_price_plausible(850, 145)` → accepted=False ("implausible_ratio" — 5.86× not within ±25% of 5× or 10×).
- `check_price_plausible(145, 145)` → accepted=True ("ok" — 1.0×).
- `check_price_plausible(14.5, 145)` → accepted=True ("ok" — 0.1× = 1/10, post-split mismatch direction).
- `check_price_plausible(290, 145)` → accepted=True ("ok" — 2.0×, possible split).
- `check_price_plausible(180, 145)` → accepted=True ("ok" — 1.24× ≈ 1.0× + 25%).
- `check_price_plausible(220, 145)` → accepted=False (~1.52×, outside ±25% of 1× and 2×).
- `check_price_plausible(850, None)` → accepted=True ("no_live_price", fail-open).
- `check_price_plausible(0, 145)` → accepted=False ("implausible_zero").
- Real NVDA incident replay: setup entry=850, live=145 (or whatever Finnhub returns at test time) → block alert.

---

## Out of scope

- Real-time price caching (over-engineering for one-shot alerts; existing Finnhub adapter is already cached for ~30s in `api_adapters`).
- Backtesting price sanity against historical alert tape — separate analysis spec.
- Sector ETF grouping (e.g., "QQQ levels around $500 must reference NDX-style price not splits") — overkill.
- The Codex-proposed `support > live → reject` and `resistance < live → reject` directional rules. **Explicitly skipped** because real analyst commentary often references broken levels (an old support that's now resistance, or vice versa) — see README Pre-mortem #2.
