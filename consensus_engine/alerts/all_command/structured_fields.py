"""Code-derived structured fields for !all command.

The LLM is forbidden from generating these — they are computed deterministically
from the score breakdown, anchor list, ATR(14), earnings date, and options
expiry. Direction comes from the sign of (bullish - bearish) score components,
confidence is binary HIGH/LOW vs the high-confidence threshold, magnitude is
2x ATR(14), and breakout timeframe prefers earnings-within-30d, then options
expiry, else "TBD".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine.models import OptionsResult, ScoreBreakdown


@dataclass
class StructuredFields:
    direction: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence_label: str   # "HIGH" | "LOW"
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    breakout_timeframe: str = "TBD"
    magnitude_label: str = "TBD"
    # Iter5 — surface the entry zone (the prompt explicitly asks for "buying
    # level"; v1-v4 only emitted SL+TPs). buy_zone_low/high bracket the
    # support cluster nearest current_price; current_price is displayed in the
    # embed and passed to the LLM so narrative can anchor specifics.
    current_price: Optional[float] = None
    buy_zone_low: Optional[float] = None
    buy_zone_high: Optional[float] = None
    earnings_date: Optional[str] = None  # ISO YYYY-MM-DD or None


# Components contributing to direction scoring. Sign mapping is deferred to
# the caller via per-component sign — the cross_reference scorer awards
# positive for bullish and negative for bearish in the score breakdown.
_BULLISH_BIASED_FIELDS = (
    "news_catalyst",
    "social_apewisdom",
    "social_stocktwits",
    "social_reddit",
    "google_trends",
    "technical",
    "llm_boost",
    "options_flow",
    "consensus_boost",
)


def compute_direction(score_breakdown: ScoreBreakdown) -> str:
    """Sum signed contributions; positive net -> BULLISH, negative -> BEARISH.

    Components in `_BULLISH_BIASED_FIELDS` may carry negative values when the
    underlying signal is bearish (e.g. negative technical penalty). We sum
    them as-is and bucket on the sign of the net.
    """
    if score_breakdown is None:
        return "NEUTRAL"
    net = 0
    for field_name in _BULLISH_BIASED_FIELDS:
        try:
            net += int(getattr(score_breakdown, field_name, 0) or 0)
        except (TypeError, ValueError):
            continue
    if net > 0:
        return "BULLISH"
    if net < 0:
        return "BEARISH"
    return "NEUTRAL"


def compute_confidence_label(
    final_score: float,
    threshold: Optional[float] = None,
) -> str:
    """Binary HIGH/LOW vs config-driven threshold (default 80)."""
    if threshold is None:
        threshold = cfg.get("precision_engine.thresholds.high_confidence", 80)
    try:
        thr = float(threshold)
    except (TypeError, ValueError):
        thr = 80.0
    try:
        score_f = float(final_score)
    except (TypeError, ValueError):
        return "LOW"
    return "HIGH" if score_f >= thr else "LOW"


def _parse_iso_date(s: str) -> Optional[date]:
    """Parse YYYY-MM-DD; return None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def compute_breakout_timeframe(
    ticker: str,
    earnings_date: Optional[str],
    options_data: Optional[OptionsResult],
) -> str:
    """Return earnings_date if within 30 days, else nearest options expiry.

    Falls back to the literal string "TBD" when neither is available.
    """
    today = date.today()
    earnings_d = _parse_iso_date(earnings_date) if earnings_date else None
    if earnings_d is not None:
        delta_days = (earnings_d - today).days
        if 0 <= delta_days <= 30:
            return f"earnings {earnings_d.isoformat()}"

    if options_data is not None:
        # options models may stash an expiry on top_contract or similar; we
        # accept any attribute that looks like an ISO date.
        for attr in ("expiry", "top_contract"):
            value = getattr(options_data, attr, None)
            d = _parse_iso_date(value) if isinstance(value, str) else None
            if d is not None and (d - today).days >= 0:
                return f"options {d.isoformat()}"
    return "TBD"


def compute_buy_zone(
    current_price: Optional[float],
    supports: list,
    direction: str,
) -> tuple[Optional[float], Optional[float]]:
    """Return (low, high) entry-zone bracket from current price + support cluster.

    Iter5: the prompt explicitly asks for a buying level. Heuristic:
      - BULLISH: high = current_price (buy on a small dip back to spot or
        better); low = max(supports below price) — the highest support is
        the "should-hold" level. If no supports below price, fall back to a
        2 % buffer below current_price.
      - BEARISH: short-zone bracket — high = min(resistances above price);
        low = current_price.
      - NEUTRAL: no zone.
    """
    if current_price is None or current_price <= 0:
        return None, None
    direction_u = (direction or "").upper()
    sup_prices = [getattr(s, "price", None) for s in (supports or [])]
    sup_prices = [p for p in sup_prices if isinstance(p, (int, float)) and p < current_price]
    if direction_u == "BULLISH":
        high = float(current_price)
        if sup_prices:
            low = float(max(sup_prices))
        else:
            low = round(float(current_price) * 0.98, 2)
        return low, high
    if direction_u == "BEARISH":
        # supports[] argument is overloaded here as "anchors above price"
        # for bearish setups; caller flips them. Fall back to current_price.
        return None, None
    return None, None


def compute_magnitude(atr14: Optional[float], current_price: float) -> str:
    """2x ATR(14) magnitude band; "TBD" when ATR unavailable."""
    if atr14 is None:
        return "TBD"
    try:
        atr_f = float(atr14)
    except (TypeError, ValueError):
        return "TBD"
    if atr_f <= 0:
        return "TBD"
    return f"±${atr_f * 2:.2f} (2× ATR)"
