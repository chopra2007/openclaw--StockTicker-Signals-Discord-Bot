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
    # 5.0 intentionally excluded: the ±25% band around 5× extends to 6.25×,
    # which would accept the vkqchQQnm88 hallucination (850 on a $145 stock ≈ 5.86×).
    # Legitimate 5× post-split levels fall within 25% of 4× (boundary case 5.0 = 4×1.25).
    1 / 5,
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
    reason: str  # "ok", "no_live_price", "implausible_ratio", "implausible_zero", "no_live_price_year_range"


def _looks_like_calendar_year(level_price: float, source_snippet: str | None) -> bool:
    """Narrow fail-closed condition for the live-quote-missing branch.

    Only when both:
      * `level_price` is an integer in (1900, 2100), and
      * `source_snippet` mentions a calendar marker (Q1-4, fiscal, FY,
        month name, or 'in'/'by')
    do we suppress instead of fail-open. Anything outside the year window
    keeps the prior fail-open behaviour, so Finnhub outages don't gate
    legitimate alerts.
    """
    if not isinstance(level_price, (int, float)):
        return False
    if not (1900 < level_price < 2100):
        return False
    if abs(level_price - round(level_price)) > 1e-6:
        return False
    if not source_snippet:
        return False
    # Defer regex to calendar_filter so the marker list stays in one place.
    from consensus_engine.analysis.calendar_filter import _CALENDAR_MARKERS
    return bool(_CALENDAR_MARKERS.search(source_snippet))


def check_price_plausible(
    level_price: float,
    live_price: float | None,
    source_snippet: str | None = None,
) -> SanityResult:
    """Return SanityResult for one (level, live) pair.

    Caller decides what to do with `accepted=False`. Common policy: skip
    Discord alert, log warning at WARNING level, mark row suppressed=1
    with reason='price_sanity'.

    Note: when live_price is None or 0 (Finnhub error / rate limit), we
    accept (fail-open) by default. The narrow exception is the
    year-range-in-calendar-context case (W1 A-T0 hardening): if
    `level_price` is an integer in the calendar year window AND the
    surrounding snippet mentions a calendar marker, we fail-closed with
    `reason='no_live_price_year_range'` so the MSFT-$2024 class doesn't
    leak through whenever Finnhub is down.
    """
    if not isinstance(level_price, (int, float)) or level_price <= 0:
        return SanityResult(False, "implausible_zero")
    if not live_price or live_price <= 0:
        if _looks_like_calendar_year(level_price, source_snippet):
            return SanityResult(False, "no_live_price_year_range")
        return SanityResult(True, "no_live_price")

    ratio = level_price / live_price
    for factor in _SPLIT_FACTORS:
        if abs(ratio - factor) / factor <= _RATIO_TOLERANCE:
            return SanityResult(True, "ok")
    return SanityResult(False, "implausible_ratio")
