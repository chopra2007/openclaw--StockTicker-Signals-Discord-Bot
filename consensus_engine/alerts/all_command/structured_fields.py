"""Code-derived structured fields for !all command.

The LLM is forbidden from generating these — they are computed deterministically
from the score breakdown, anchor list, ATR(14), earnings date, and options
expiry. Direction comes from the sign of (bullish - bearish) score components,
confidence is binary HIGH/LOW vs the high-confidence threshold, magnitude is
2x ATR(14), and breakout timeframe prefers earnings-within-30d, then options
expiry, else "TBD".
"""
from __future__ import annotations

import math
import statistics
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
    # TODO #13 — surface the catalyst kind + mechanism string so the narrator
    # can name what the catalyst IS, not just when (closes the D3 catalyst-
    # quality gap from the 2026-05-18 blind-compare).
    next_catalyst_kind: Optional[str] = None        # "earnings" | "dividend_ex" | "options_expiry" | ...
    next_catalyst_mechanism: Optional[str] = None    # "earnings on 2026-05-20", "ex-dividend $0.04"
    # #6 !all levers — code-derived, embed-only (peer_strength also feeds the
    # narrator when its mode is the clean curated-peer mean; see narrator.py).
    max_pain: Optional[dict] = None       # {"spot", "weekly": {...}|None, "monthly": {...}|None}
    peer_strength: Optional[dict] = None  # {stock_pct, benchmark_pct, delta, verdict, benchmark_label, mode, narrator_ok, ...}
    snapshot: Optional[dict] = None       # #6 analyst target + rating + fwd P/E + short interest (yfinance .info); embed-only
    risk_reward: Optional[float] = None   # #6 reward:risk of the computed plan (reward per 1.0 risk); embed-only
    relative_volume: Optional[float] = None  # #6 last day's volume vs prior 20-day average (e.g. 1.8 = 1.8×); embed-only
    earnings_move: Optional[dict] = None  # {"avg_pct": float, "n": int} avg abs % earnings reaction; embed-only
    tweets_today: Optional[dict] = None   # Issue 3a — {"total", "bull", "bear", "example"} of today's TweetShift msgs; embed-only
    stocktwits: Optional[dict] = None     # #6 Lever 2 — {"bull_pct", "delta_5d", "watchers"} retail crowd sentiment; embed-only


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
    "youtube",
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


def compute_risk_reward(current_price, sl, tp1, direction,
                        trade_plan_confidence=None) -> Optional[float]:
    """#6 — reward:risk of the computed plan as reward-per-1.0-risk (e.g. 2.4
    renders 'R:R 1:2.4'). Direction-aware. Returns None — so the embed field is
    omitted — when not meaningfully computable:
      * NEUTRAL (levels are wiped) or unknown direction,
      * the plan is an ATR-fallback (trade_plan confidence == "low") whose SL/TP
        are synthetic and would yield an authoritative-looking but meaningless
        ratio (Pass-3 critic M3),
      * any of spot/sl/tp1 missing, zero/negative risk or reward (incl. spot==sl),
      * absurd ratio outside [0.1, 20] (degenerate SL≈spot).
    Entry is anchored on current_price (spot) — there is no separate 'entry'
    level in the trade plan (Pass-3 critic M2).
    """
    if direction not in ("BULLISH", "BEARISH"):
        return None
    if str(trade_plan_confidence).lower() == "low":
        return None
    if current_price is None or sl is None or tp1 is None:
        return None
    try:
        spot = float(current_price)
        s = float(sl)
        t = float(tp1)
    except (TypeError, ValueError):
        return None
    if direction == "BULLISH":
        risk, reward = spot - s, t - spot
    else:  # BEARISH
        risk, reward = s - spot, spot - t
    if risk <= 0 or reward <= 0:
        return None
    rr = reward / risk
    if rr < 0.1 or rr > 20:
        return None
    return round(rr, 1)


def compute_levels_provenance(trade_plan) -> str:
    """Wave 2 smart-levels — one-line embed footer naming the method behind each
    level (e.g. "entry: spot; stop: tech_sr swing-S/R x3; tp1: tech_fib ext 1.272").

    Reads `trade_plan["levels"]` (populated only when the technical engine is
    live). Returns "" when there is no provenance to show, so the caller can
    omit the footer. Never raises.
    """
    if not isinstance(trade_plan, dict):
        return ""
    levels = trade_plan.get("levels")
    if not levels:
        return ""
    parts: list[str] = []
    for lvl in levels:
        try:
            role = lvl.get("role")
            method = lvl.get("method") or ""
            label = lvl.get("label") or ""
            if role == "entry":
                parts.append("entry: %s" % (label or method))
            else:
                tag = ("%s %s" % (method, label)).strip()
                if lvl.get("is_filler"):
                    tag += " (filler)"
                parts.append("%s: %s" % (role, tag))
        except AttributeError:
            continue
    return "; ".join(parts)


def compute_relative_volume(candles, lookback: int = 20) -> Optional[float]:
    """#6 — last day's volume as a multiple of the prior `lookback`-day average
    (e.g. 1.8 renders 'Rel Vol 1.8×'). Returns None — so the embed field is
    omitted — when not meaningfully computable:
      * fewer than lookback+1 candles with numeric volume,
      * the prior-`lookback` average is <= 0.
    Tolerates missing/None/NaN volume entries by dropping them before counting.
    """
    if not isinstance(candles, list):
        return None
    vols: list[float] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        v = c.get("volume")
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f) or math.isinf(f):
            continue
        vols.append(f)
    if len(vols) < lookback + 1:
        return None
    last_vol = vols[-1]
    prior = vols[-(lookback + 1):-1]
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return round(last_vol / avg, 2)


def compute_realized_daily_move(candles, lookback: int = 10) -> Optional[float]:
    """#25 (full-audit-2026-06-06) — realized daily price move in dollars,
    estimated from the recent close-to-close volatility.

    Returns `stdev(log returns of CLOSES over the last `lookback` returns)
    × last close` — i.e. a typical one-day dollar swing. Returns None — so the
    caller falls back to the ATR-only horizon — when not computable:
      * candles isn't a list,
      * fewer than `lookback + 1` candles with a numeric, positive close,
      * the close series has no variance (stdev == 0) or last close <= 0.

    Candle dicts have NO 'open' key, so this uses 'close' only. Tolerates
    missing/None/NaN closes by dropping them before counting.
    """
    if not isinstance(candles, list):
        return None
    closes: list[float] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        v = c.get("close")
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f) or math.isinf(f) or f <= 0:
            continue
        closes.append(f)
    if len(closes) < lookback + 1:
        return None
    window = closes[-(lookback + 1):]
    log_returns = [
        math.log(window[i] / window[i - 1]) for i in range(1, len(window))
    ]
    if len(log_returns) < 2:
        return None
    try:
        sigma = statistics.stdev(log_returns)
    except statistics.StatisticsError:
        return None
    last_close = closes[-1]
    if sigma <= 0 or last_close <= 0:
        return None
    return round(sigma * last_close, 4)


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
    realized_daily_move: Optional[float] = None,
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

    # #25 (full-audit-2026-06-06) — blend realized close-to-close volatility
    # into the per-day slippage denominator. Default-OFF flag. When on AND a
    # positive realized move is supplied, use max(realized, 0.7×ATR) so a
    # calm tape (realized < ATR) keeps the ATR floor while a volatile tape
    # (realized > ATR) shortens the horizon. Flag OFF or no realized move →
    # the original ATR-only denominator (byte-identical).
    atr_slippage = _HORIZON_DAILY_SLIPPAGE * atr_f
    daily_slippage = atr_slippage
    if (
        cfg.get("all_command.horizon_realized_vol", False)
        and realized_daily_move is not None
    ):
        try:
            rdm = float(realized_daily_move)
        except (TypeError, ValueError):
            rdm = 0.0
        if rdm > 0:
            daily_slippage = max(rdm, atr_slippage)

    raw_days = distance / daily_slippage
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

    # Commit 16: 0.7x calibration. ATR is the true range (high-low incl
    # gaps), which is ~1.4x larger than close-to-close σ that traders mean
    # by "expected move." Multiplying ATR×√N gives a typical-price-range
    # value, not a statistical expected move. Empirical verification
    # 2026-05-19 vs yfinance σ on NVDA / AMD / TSLA: bot was 1.37×, 1.08×,
    # 1.82× the σ-derived 5-day move. 0.7 ≈ 1/1.43 brings the formula
    # close to σ×spot×√N for the typical stock without needing to compute
    # close-to-close stdev separately.
    _ATR_TO_SIGMA_FACTOR = 0.7
    typical = atr_f * (h_days ** 0.5) * _ATR_TO_SIGMA_FACTOR
    high_vol: Optional[float] = None
    if atr_90d_high_pct is not None and spot is not None and spot > 0:
        try:
            high_vol = float(atr_90d_high_pct) * float(spot)
        except (TypeError, ValueError):
            high_vol = None

    # Commit 17: include the exact calibrated formula in the rendered
    # label so the LLM's rationale column paraphrases the right math
    # (iter16 surfaced the LLM writing "ATR × 1.5" — an invented
    # multiplier — instead of the actual 0.7×√N). Showing the formula
    # in-band gives the model a literal string to copy.
    _formula = f"0.7×ATR×√{h_days}"
    if high_vol is not None and high_vol > typical:
        rendered = f"±${typical:.0f}-${high_vol:.0f} / {h_days}d ({_formula})"
    else:
        rendered = (
            f"±${typical:.0f} / {h_days}d ({_formula})"
            if high_vol is not None
            else f"±${typical:.0f} / {h_days}d ({_formula}; high-vol data unavailable)"
        )
    return typical, high_vol, rendered


def compute_next_catalyst_days(
    earnings_date: Optional[str],
    options_data: Optional[OptionsResult],
    extra_events: Optional[list] = None,
) -> Optional[int]:
    """Days until next material catalyst (earnings preferred, then options).

    Returns the integer day count, or None if no future catalyst is found.
    Swing-trader-friendly replacement for the 30-day breakout_timeframe.

    TODO #13: `extra_events` accepts CatalystEvent-shaped objects from the
    new nasdaq_calendar scanner. Earnings and dividends from there get
    merged into the candidate set; nearest forward-dated wins.
    """
    days, _, _ = compute_next_catalyst(
        earnings_date, options_data, extra_events,
    )
    return days


def compute_next_catalyst(
    earnings_date: Optional[str],
    options_data: Optional[OptionsResult],
    extra_events: Optional[list] = None,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Like compute_next_catalyst_days but also returns kind + mechanism.

    Returns `(days_to_next, kind_label, mechanism_string)` so the narrator
    can name what the catalyst actually is (e.g. "Q1 2026 earnings on
    2026-05-20" vs. just "in 2 days"). TODO #13 closes the catalyst-
    quality gap by giving the narrator material to write specific bullets.

    Priority: earnings > product/analyst events > options expiry >
    dividend ex-date > IPO. Within priority, nearest date wins.
    """
    today = date.today()
    candidates: list[tuple[date, str, str, int]] = []  # (date, kind, mechanism, priority)

    _PRIO = {
        "earnings": 0, "product_launch": 1, "analyst_day": 1, "fda_pdufa": 1,
        "options_expiry": 3, "dividend_ex": 5, "ipo": 5, "ipo_lockup_or_listing": 5,
    }

    earnings_d = _parse_iso_date(earnings_date) if earnings_date else None
    if earnings_d is not None and (earnings_d - today).days >= 0:
        candidates.append((earnings_d, "earnings", f"earnings on {earnings_d.isoformat()}", 0))

    for ev in (extra_events or []):
        ev_date = getattr(ev, "date", None)
        ev_kind = getattr(ev, "kind", None)
        ev_mech = getattr(ev, "mechanism", None) or ev_kind or "event"
        if not isinstance(ev_date, date) or not ev_kind:
            continue
        if (ev_date - today).days < 0:
            continue
        candidates.append((ev_date, ev_kind, ev_mech, _PRIO.get(ev_kind, 4)))

    if options_data is not None:
        for attr in ("expiry", "top_contract"):
            value = getattr(options_data, attr, None)
            d = _parse_iso_date(value) if isinstance(value, str) else None
            if d is not None and (d - today).days >= 0:
                candidates.append((d, "options_expiry", f"options expiry {d.isoformat()}", 3))
                break

    if not candidates:
        return None, None, None

    # Sort by (priority asc, date asc) — picks the highest-priority nearest event.
    candidates.sort(key=lambda c: (c[3], c[0]))
    pick = candidates[0]
    return (pick[0] - today).days, pick[1], pick[2]


# ---------------------------------------------------------------------------
# Dict-based helpers — callable before ScoreBreakdown is available (Step 9).
# These accept plain dicts so aggregator.py can invoke them pre-gap_fill.
# ---------------------------------------------------------------------------

_HIGH_CONVICTION_TIERS = ("HIGH", "high", "High")
_HIGH_CONVICTION_MULTIPLIER = 1.5
_LOW_CONVICTION_MULTIPLIER = 1.0


def compute_direction_from_fields(fields: dict) -> str:
    """Sum _BULLISH_BIASED_FIELDS from a plain dict; return LONG | SHORT | NEUTRAL.

    Positive net -> LONG, negative -> SHORT, zero -> NEUTRAL.
    Missing or non-numeric values are treated as zero.
    """
    net = 0
    for key in _BULLISH_BIASED_FIELDS:
        try:
            net += int(fields.get(key) or 0)
        except (TypeError, ValueError):
            continue
    if net > 0:
        return "LONG"
    if net < 0:
        return "SHORT"
    return "NEUTRAL"


def compute_expected_move(
    fields: dict,
    conviction_tier: str,
    recent_vol_pct: float,
) -> float:
    """Return expected % move as recent_vol_pct scaled by conviction multiplier.

    High conviction (tier == "HIGH") scales by 1.5; all others scale by 1.0.
    Missing conviction_tier or non-positive recent_vol_pct returns 0.0.
    """
    try:
        vol = float(recent_vol_pct)
    except (TypeError, ValueError):
        return 0.0
    if vol <= 0:
        return 0.0
    multiplier = (
        _HIGH_CONVICTION_MULTIPLIER
        if conviction_tier in _HIGH_CONVICTION_TIERS
        else _LOW_CONVICTION_MULTIPLIER
    )
    return round(vol * multiplier, 4)
