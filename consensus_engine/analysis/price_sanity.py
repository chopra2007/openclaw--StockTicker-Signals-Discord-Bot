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
