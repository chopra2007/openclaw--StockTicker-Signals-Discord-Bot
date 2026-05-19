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
    # W4 swing-realism additions. Old fields above stay populated for
    # back-compat (test fixtures, emergency-revert via swing_v2_enabled=false).
    next_catalyst_days: Optional[int] = None
    swing_horizon_days: Optional[int] = None
    swing_horizon_band: Optional[tuple] = None        # (lo, hi) days
    expected_move_typical: Optional[float] = None     # $ at horizon
    expected_move_high_vol: Optional[float] = None    # $ at 80th pct, None if 90d data missing
    magnitude_band_label: Optional[str] = None        # rendered string e.g. "±$5–$9 / 4-6w"


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
        # Cap the entry band at ~5 % below current price — anchors more than
        # 5 % away aren't an actionable entry zone, they're a "patience" level.
        floor = round(float(current_price) * 0.95, 2)
        if sup_prices:
            nearest = float(max(sup_prices))
            low = max(nearest, floor) if nearest >= floor else floor
        else:
            low = round(float(current_price) * 0.98, 2)
        return low, high
    if direction_u == "BEARISH":
        # supports[] argument is overloaded here as "anchors above price"
        # for bearish setups; caller flips them. Fall back to current_price.
        return None, None
    return None, None


def compute_magnitude(atr14: Optional[float], current_price: float) -> str:
    """2x ATR(14) magnitude band; "TBD" when ATR unavailable.

    Retained behind `all_command.swing_v2_enabled=false` for emergency
    revert. New code paths use `compute_magnitude_band` (W4 B-M1).
    """
    if atr14 is None:
        return "TBD"
    try:
        atr_f = float(atr14)
    except (TypeError, ValueError):
        return "TBD"
    if atr_f <= 0:
        return "TBD"
    return f"±${atr_f * 2:.2f} (2× ATR)"


# ---------------------------------------------------------------------------
# W4 swing-realism additions — compute_swing_horizon, compute_magnitude_band,
# compute_next_catalyst_days. These power the new Trade Plan rows + embed
# fields once `all_command.swing_v2_enabled` is True.
# ---------------------------------------------------------------------------

_HORIZON_DAILY_SLIPPAGE = 0.7   # 0.7×ATR/day is the empirical slippage constant
_HORIZON_BAND_PCT = 0.25        # ±25% band around the central estimate
_HORIZON_GAP_UP_GUARD_PCT = 0.005  # tp1 within 0.5% of spot → already at target
_HORIZON_LONG_CAP_DAYS = 365
_HORIZON_SWING_FLOOR_DAYS = 5   # TODO #12 — min horizon for a swing trade.
# Without this floor, ATR-fallback TPs (set at exactly 1×ATR per TODO #10)
# produce ~1.43-day horizons that clash with multi-percent SL drawdowns
# (horizon_anchor_ratio >> 1.0). Five days matches a typical swing baseline
# and is bypassed only for intraday catalysts (days_to_ER == 0).


def compute_swing_horizon(
    spot: Optional[float],
    tp1: Optional[float],
    atr14: Optional[float],
    earnings_date: Optional[str] = None,
) -> tuple[Optional[int], Optional[tuple], Optional[str]]:
    """Estimate days-to-TP1 and a ±25% band around that estimate.

    Returns `(days, band, note)` where:
      * `days` is the central estimate (rounded int), or None if not computable.
      * `band` is `(lo, hi)` (ints, ±25%), or None.
      * `note` is a short qualifier string for narrator/embed when the
        plain numeric form would mislead (e.g. "at target", "12+ months").

    Math: `|tp1 - spot| / (0.7 × atr14_daily)` then `min(est, days_to_ER)`.
    Bearish setups handled via abs() (CEF-8 fix). When tp1 within 0.5% of
    spot, returns (0, (0,0), "at target"). When estimate exceeds 365 days,
    returns (365, (300, 450), "12+ months"). When ATR is None or spot is
    missing, returns (None, None, None) and callers render `—`.
    """
    if not spot or spot <= 0 or atr14 is None or atr14 <= 0 or tp1 is None:
        return None, None, None
    try:
        atr_f = float(atr14)
        spot_f = float(spot)
        tp1_f = float(tp1)
    except (TypeError, ValueError):
        return None, None, None

    distance = abs(tp1_f - spot_f)
    if distance / spot_f < _HORIZON_GAP_UP_GUARD_PCT:
        return 0, (0, 0), "at target"

    raw_days = distance / (_HORIZON_DAILY_SLIPPAGE * atr_f)
    est_days = max(1, int(round(raw_days)))

    # TODO #12 — apply swing floor unless the catalyst is intraday.
    # Pre-fix: a 1-day ER cap turned every ATR-fallback trade into a "1-1 day"
    # horizon that didn't match the multi-percent SL (NVDA/AMD/TSLA 2026-05-19
    # iter2). Post-fix: floor=5 unless ER is today (T-0); ER between T-1 and
    # T-5 is allowed to extend horizon ABOVE the floor (trader holds through),
    # ER beyond T-5 caps as before.
    earnings_d = _parse_iso_date(earnings_date) if earnings_date else None
    days_to_er = (earnings_d - date.today()).days if earnings_d is not None else None
    if days_to_er is not None and days_to_er == 0:
        pass  # intraday catalyst — keep est_days as computed (usually 1)
    else:
        est_days = max(est_days, _HORIZON_SWING_FLOOR_DAYS)
        if days_to_er is not None and days_to_er > _HORIZON_SWING_FLOOR_DAYS:
            est_days = min(est_days, days_to_er)

    if est_days > _HORIZON_LONG_CAP_DAYS:
        return _HORIZON_LONG_CAP_DAYS, (300, 450), "12+ months"

    lo = max(1, int(round(est_days * (1 - _HORIZON_BAND_PCT))))
    hi = max(lo, int(round(est_days * (1 + _HORIZON_BAND_PCT))))
    return est_days, (lo, hi), None


def compute_magnitude_band(
    atr14: Optional[float],
    horizon_days: Optional[int],
    spot: Optional[float],
    atr_90d_high_pct: Optional[float] = None,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Compute expected move bands over the swing horizon.

    Returns `(typical, high_vol, rendered_string)` where:
      * `typical` = `atr14 × sqrt(horizon_days)` — random-walk variance over
        the horizon. Returned in $ at spot scale.
      * `high_vol` = `atr_90d_high_pct × spot` — 80th-percentile rolling
        weekly move ($), or None if 90d data is unavailable.
      * `rendered_string` is the embed-ready band, e.g. `±$5–$9 / 4-6w`
        or `±$5 (typical; high-vol data unavailable)` when high_vol is None.
    """
    if atr14 is None or atr14 <= 0 or horizon_days is None or horizon_days <= 0:
        return None, None, None
    try:
        atr_f = float(atr14)
        h_days = int(horizon_days)
    except (TypeError, ValueError):
        return None, None, None

    typical = atr_f * (h_days ** 0.5)
    high_vol: Optional[float] = None
    if atr_90d_high_pct is not None and spot is not None and spot > 0:
        try:
            high_vol = float(atr_90d_high_pct) * float(spot)
        except (TypeError, ValueError):
            high_vol = None

    if high_vol is not None and high_vol > typical:
        rendered = f"±${typical:.0f}-${high_vol:.0f} / {h_days}d"
    else:
        rendered = f"±${typical:.0f} (typical; high-vol data unavailable)" \
            if high_vol is None else f"±${typical:.0f} / {h_days}d"
    return typical, high_vol, rendered


def compute_next_catalyst_days(
    earnings_date: Optional[str],
    options_data: Optional[OptionsResult],
) -> Optional[int]:
    """Days until next material catalyst (earnings preferred, then options).

    Returns the integer day count, or None if no future catalyst is found.
    Swing-trader-friendly replacement for the 30-day breakout_timeframe.
    """
    today = date.today()
    earnings_d = _parse_iso_date(earnings_date) if earnings_date else None
    if earnings_d is not None:
        delta = (earnings_d - today).days
        if delta >= 0:
            return delta

    if options_data is not None:
        for attr in ("expiry", "top_contract"):
            value = getattr(options_data, attr, None)
            d = _parse_iso_date(value) if isinstance(value, str) else None
            if d is not None and (d - today).days >= 0:
                return (d - today).days
    return None
