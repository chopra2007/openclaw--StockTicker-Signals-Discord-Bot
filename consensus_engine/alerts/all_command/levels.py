"""Anchor pipeline for !all command.

Extracts price levels from YouTube DB rows, swing high/low candle data, and web
search snippets. Clusters within 0.5%, ranks by composite score, and selects a
trade plan (1 support + 3 resistances) when at least 4 anchors are available.

Ranking formula (Pass 1 best practice):
    score = (touches * 2) + (volume_strength * 1.5) + (source_count * 3)
            + freshness_bonus
    freshness_bonus = max(0, 5 * (1 - days_old / 30))
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from consensus_engine.analysis import indicators  # smart-levels engine (full-audit Wave 2)

from consensus_engine.utils.obs_log import obs_log


# 60-char context window price extraction
PRICE_RE = re.compile(r"\$\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)")
TRIGGER_WORDS = {"target", "support", "resistance", "level", "stop", "price"}
NEGATIVE_CONTEXT = {"billion", "million", "eps", "p/e", "revenue",
                    "market cap", "shares", "%"}


# Tier ordering for source_type collisions when clustering merges anchors with
# different provenance. yt_curated wins over swing wins over yt wins over web.
# CEF-3 fix: previous code inherited source_type from cluster[0] which gave
# first-arrival-wins semantics — a web anchor sorted ahead of a yt_curated
# anchor would permanently down-tier the cluster.
# Wave 2 (smart-levels): the four tech_* families are inserted BETWEEN swing and
# yt so a flag-OFF swing+yt cluster still resolves to swing (relative order of
# the pre-existing types yt_curated > swing > yt > web is preserved).
SOURCE_TIER_ORDER: tuple[str, ...] = (
    "yt_curated",   # human-curated YouTuber level
    "swing",        # raw 3-bar pivot (legacy)
    "tech_sr",      # clustered multi-touch pivot S/R
    "tech_vp",      # volume node / VWAP
    "tech_vpoc",    # virgin/naked POC (untested prior-session magnet)
    "tech_zone",    # supply/demand zone
    "tech_fib",     # fib level
    "yt",           # parsed YouTube mention
    "web",          # web snippet
)


def _max_tier(source_types: list[str]) -> str:
    """Return the highest-priority source_type from a cluster."""
    for tier in SOURCE_TIER_ORDER:
        if tier in source_types:
            return tier
    # Anything unrecognised falls back to web (most conservative).
    return source_types[0] if source_types else "web"


@dataclass
class Anchor:
    """A single price anchor with provenance and ranking metadata."""
    price: float
    source: str               # e.g. "youtube:LunaTrades", "swing_high", "web:reuters.com"
    source_type: str          # "yt_curated" | "swing" | "yt" | "web"
    touches: int = 0
    volume_strength: float = 0.0
    freshness_days: int = 0
    computed_score: float = 0.0
    source_count: int = 1     # increases when anchors merge in clustering
    # W2 provenance plumbing additions
    channel_id: Optional[str] = None        # join key for trust lookup (CEF-10)
    trust_score: Optional[float] = None     # pre-fetched at query time
    distance_pct: Optional[float] = None    # populated at rank time (W3)
    cluster_source_types: Optional[set] = None  # retained tier set for C-C8 (W5)
    # Wave 2 (smart-levels engine) — per-method confidence + human label.
    # Additive only; existing constructors are unaffected.
    method_strength: Optional[float] = None  # 0-100 strength from the producing method (§3)
    method_label: Optional[str] = None       # e.g. "golden-pocket 0.618", "POC", "swing-low x3"


def _freshness_bonus(days_old: int) -> float:
    """Linear decay over 30 days. Today=+5, 30d=+0, beyond=+0."""
    return max(0.0, 5.0 * (1.0 - days_old / 30.0))


def _score(anchor: Anchor) -> float:
    return (
        anchor.touches * 2.0
        + anchor.volume_strength * 1.5
        + anchor.source_count * 3.0
        + _freshness_bonus(anchor.freshness_days)
    )


# W3 C-C1/C-C3 — distance penalty + source-tier multiplier (shadow mode).
# Values per final-plan §2; carve-outs match Codex amendment.
SCORE_V2_TIER_MULTIPLIERS: dict[str, float] = {
    "yt_curated": 1.0,
    "swing": 0.7,
    # Wave 2 (smart-levels): clustered multi-touch pivot ~ as trustworthy as a
    # curated human level; a bare fib is the weakest technical (only matters with
    # confluence — which the confluence bonus already rewards).
    "tech_sr": 0.75,
    "tech_vpoc": 0.70,
    "tech_vp": 0.65,
    "tech_zone": 0.6,
    "tech_fib": 0.55,
    "yt": 0.5,
    "web": 0.2,
}

# Default exponent for the distance penalty 1/(1 + alpha * distance_pct).
# Tuned per Codex commentary: alpha=4 gives 0.71 @ 10%, 0.50 @ 25%, 0.20 @ 100%.
_SCORE_V2_DEFAULT_ALPHA = 4.0
# Penny-stock skip threshold: distance penalty becomes degenerate when the
# spot price is tiny because every anchor is at high % distance.
_SCORE_V2_PENNY_SKIP_PRICE = 5.0
# High-priced ticker gentler-tail threshold (alpha=2 instead of 4).
_SCORE_V2_HIGH_PRICE_BAND = 1000.0
_SCORE_V2_HIGH_PRICE_ALPHA = 2.0


def _distance_penalty(distance_pct: Optional[float], current_price: float) -> float:
    """1/(1 + alpha * distance_pct) with carve-outs.

    Penny stocks (`current_price < $5`) skip the penalty (multiplier 1.0)
    because distance_pct dynamics are degenerate at small spots. High-priced
    stocks (`current_price > $1000`) get a softer tail (alpha=2) because
    a $200 anchor 10% away on a $2000 stock is informationally similar to
    a $20 anchor 10% away on a $200 stock and shouldn't be punished harder.
    """
    if distance_pct is None or distance_pct < 0:
        return 1.0
    if current_price is None or current_price <= 0:
        return 1.0
    if current_price < _SCORE_V2_PENNY_SKIP_PRICE:
        return 1.0
    alpha = (
        _SCORE_V2_HIGH_PRICE_ALPHA
        if current_price > _SCORE_V2_HIGH_PRICE_BAND
        else _SCORE_V2_DEFAULT_ALPHA
    )
    return 1.0 / (1.0 + alpha * distance_pct)


# W5 C-C8 confluence bonus — applied on top of v2 score when a cluster
# contains anchors from multiple source tiers. Default OFF per plan §7
# (flip after W4 is stable for 48h). Bonus = 1.0 + (num_distinct_tiers - 1)
# * SCORE_V2_CONFLUENCE_PER_TIER, capped at SCORE_V2_CONFLUENCE_MAX_MULT.
SCORE_V2_CONFLUENCE_PER_TIER = 0.10
SCORE_V2_CONFLUENCE_MAX_MULT = 1.5


def _confluence_bonus(cluster_source_types) -> float:
    """1.0 when cluster has only one tier; up to 1.5x when 3+ tiers diverge."""
    if not cluster_source_types or len(cluster_source_types) <= 1:
        return 1.0
    bonus = 1.0 + (len(cluster_source_types) - 1) * SCORE_V2_CONFLUENCE_PER_TIER
    return min(bonus, SCORE_V2_CONFLUENCE_MAX_MULT)


def _score_v2(
    anchor: Anchor,
    *,
    current_price: float,
    tier_multipliers: dict[str, float] = None,
    confluence_bonus_enabled: bool = False,
) -> float:
    """Anchor score with C-C1 distance penalty + C-C3 source-tier multiplier.

    W5 extension: when `confluence_bonus_enabled` is True and the anchor's
    cluster spans multiple source tiers, multiply by a confluence bonus
    (capped at 1.5x). This rewards anchors confirmed by independent source
    types (e.g. yt_curated + swing + web all landing on the same level).

    Compared to v1, multiplies the base score by `distance_penalty *
    tier_multiplier * confluence_bonus`.
    """
    base = _score(anchor)
    mults = tier_multipliers or SCORE_V2_TIER_MULTIPLIERS
    tier_mult = mults.get(anchor.source_type, mults.get("yt", 0.5))
    if anchor.distance_pct is None and current_price and current_price > 0:
        anchor.distance_pct = abs(anchor.price - current_price) / current_price
    penalty = _distance_penalty(anchor.distance_pct, current_price)
    cbonus = (
        _confluence_bonus(getattr(anchor, "cluster_source_types", None))
        if confluence_bonus_enabled
        else 1.0
    )
    return base * penalty * tier_mult * cbonus


def extract_anchors_from_youtube_levels(rows: list[dict]) -> list[Anchor]:
    """Convert youtube_levels DB rows to Anchor objects.

    Expected row keys: price, channel_name, level_type, freshness_days (optional).
    W2: also reads `channel_id`, `trust_score`, `approved` (from the LEFT JOIN
    in db.get_youtube_levels_for_ticker). When trust_score >= 0.7 AND approved=1
    the anchor is tagged `yt_curated`; otherwise it falls into `yt` tier.
    Bootstrap default for missing/null trust is 0.5 (yt tier), NOT 0.2 (web tier) —
    CEF-1 amendment to keep unregistered channels from collapsing under C-C3.
    Rows missing price are skipped.

    TODO #10: rows where freshness_days exceeds
    `all_command.levels.youtube_freshness_max_days` (default 30) are skipped
    so stale double-bottom anchors (e.g. AMD $203.79 from 30d+ ago) don't
    become the SL anchor for a fresh trade. Defaults to 30 days; set to None
    or 0 in config to disable cutoff.
    """
    from consensus_engine import config as _cfg
    max_freshness = _cfg.get("all_command.levels.youtube_freshness_max_days", 30)

    anchors: list[Anchor] = []
    for row in rows or []:
        price = row.get("price")
        if price is None:
            continue
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        if not (0.01 < price_f < 100000):
            continue
        channel = row.get("channel_name") or "unknown"
        freshness = row.get("freshness_days")
        if freshness is None:
            freshness = 0
        # TODO #10 freshness cutoff
        if max_freshness and int(freshness) > int(max_freshness):
            continue

        channel_id = row.get("channel_id")
        approved = row.get("approved")
        trust_raw = row.get("trust_score")
        trust = float(trust_raw) if trust_raw is not None else 0.5
        if trust >= 0.7 and (approved == 1 or approved is True):
            source_type = "yt_curated"
        else:
            source_type = "yt"

        anchors.append(Anchor(
            price=price_f,
            source=f"youtube:{channel}",
            source_type=source_type,
            touches=int(row.get("touches", 0) or 0),
            volume_strength=float(row.get("volume_strength", 0.0) or 0.0),
            freshness_days=int(freshness),
            channel_id=channel_id,
            trust_score=trust,
        ))
    return anchors


def extract_swing_levels(candles: list[dict]) -> list[Anchor]:
    """Find recent swing highs and lows from a list of OHLC candle dicts.

    Each candle dict should have keys: high, low, (optional) timestamp_index.
    A swing high/low is a local extremum over a 3-bar window (i-1, i, i+1).
    Returns Anchor objects with source_type='swing'.
    """
    anchors: list[Anchor] = []
    if not candles or len(candles) < 3:
        return anchors

    n = len(candles)
    for i in range(1, n - 1):
        try:
            prev_h = float(candles[i - 1]["high"])
            cur_h = float(candles[i]["high"])
            next_h = float(candles[i + 1]["high"])
            prev_l = float(candles[i - 1]["low"])
            cur_l = float(candles[i]["low"])
            next_l = float(candles[i + 1]["low"])
        except (KeyError, TypeError, ValueError):
            continue

        # bars from end → freshness in trading days (rough proxy)
        days_old = max(0, n - 1 - i)
        if cur_h > prev_h and cur_h > next_h and 0.01 < cur_h < 100000:
            anchors.append(Anchor(
                price=cur_h,
                source="swing_high",
                source_type="swing",
                touches=1,
                freshness_days=days_old,
            ))
        if cur_l < prev_l and cur_l < next_l and 0.01 < cur_l < 100000:
            anchors.append(Anchor(
                price=cur_l,
                source="swing_low",
                source_type="swing",
                touches=1,
                freshness_days=days_old,
            ))
    return anchors


# ===========================================================================
# Smart technical-levels engine (full-audit Wave 2)
# ---------------------------------------------------------------------------
# Five extractors compute real chart levels from ~63 daily bars and return them
# as Anchor objects with the four tech_* source_types so they flow through the
# SAME cluster_anchors / rank_anchors / select_trade_plan machinery as crowd
# anchors. Each sets method_strength (0-100) + method_label and maps
# method_strength -> touches/volume_strength/source_count so the EXISTING v1
# _score ranks them without any _score rewrite.
#   candles: list of {high, low, close, volume} dicts (NO 'open' key — open[i]
#            is approximated as close[i-1] where a body is needed).
# ===========================================================================


def _atr14(candles: list[dict]) -> Optional[float]:
    """ATR(14) from candles; falls back to mean(high-low) over the window."""
    if not candles:
        return None
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    val = indicators.atr(highs, lows, closes, 14)
    if val is not None and val > 0:
        return val
    ranges = [h - l for h, l in zip(highs, lows) if h is not None and l is not None]
    if ranges:
        m = sum(ranges) / len(ranges)
        return m if m > 0 else None
    return None


def _tol(atr14: float, price: float) -> float:
    """Cluster/merge band: half an ATR, floored at 0.5% of price."""
    return max(0.5 * (atr14 or 0.0), 0.005 * (price or 0.0))


def _vol(candle: dict) -> float:
    v = candle.get("volume")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _median(xs: list[float]) -> float:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return 0.0
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _method_anchor(price: float, source_type: str, *, strength: float,
                   label: str, freshness_days: int) -> Anchor:
    """Build an Anchor from a method, mapping method_strength -> v1 _score inputs.

    touches         = round(strength / 20)   (0..5, mirrors touch caps)
    volume_strength = strength / 50           (0..2 range used by _score)
    source_count    = 1                       (bumps when clustered, existing)
    """
    s = _clamp(float(strength), 0.0, 100.0)
    return Anchor(
        price=round(float(price), 2),
        source=f"{source_type}:{label}",
        source_type=source_type,
        touches=round(s / 20.0),
        volume_strength=s / 50.0,
        freshness_days=max(0, int(freshness_days)),
        source_count=1,
        method_strength=round(s, 1),
        method_label=label,
    )


def _fractal_pivots(candles: list[dict], n: int = 2) -> tuple[list[dict], list[dict]]:
    """Symmetric fractal pivots (window n on each side).

    Returns (swing_highs, swing_lows) as lists of {price, idx, volume}. The last
    n bars cannot be confirmed pivots (look-ahead guard) and are never emitted.
    """
    highs_out: list[dict] = []
    lows_out: list[dict] = []
    if not candles or len(candles) < 2 * n + 1:
        return highs_out, lows_out
    N = len(candles)
    for i in range(n, N - n):
        try:
            h = float(candles[i]["high"])
            l = float(candles[i]["low"])
        except (KeyError, TypeError, ValueError):
            continue
        is_high = all(
            h > float(candles[i + d]["high"])
            for d in range(-n, n + 1) if d != 0
        )
        is_low = all(
            l < float(candles[i + d]["low"])
            for d in range(-n, n + 1) if d != 0
        )
        if is_high:
            highs_out.append({"price": h, "idx": i, "volume": _vol(candles[i])})
        if is_low:
            lows_out.append({"price": l, "idx": i, "volume": _vol(candles[i])})
    return highs_out, lows_out


def _avwap(candles: list[dict], anchor_idx: int) -> tuple[Optional[float], float]:
    """Anchored VWAP + 1-sigma dispersion from anchor_idx to the latest bar."""
    if not candles or anchor_idx < 0 or anchor_idx >= len(candles):
        return None, 0.0
    num = 0.0
    den = 0.0
    tps: list[tuple[float, float]] = []
    for i in range(anchor_idx, len(candles)):
        c = candles[i]
        try:
            tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        except (KeyError, TypeError, ValueError):
            continue
        v = _vol(c)
        if v <= 0:
            v = 1.0  # equal-weight when volume missing
        num += tp * v
        den += v
        tps.append((tp, v))
    if den <= 0:
        return None, 0.0
    avwap = num / den
    var = sum(v * (tp - avwap) ** 2 for tp, v in tps) / den
    return avwap, var ** 0.5


def _value_area(bins: list[float], value_area_pct: float = 0.70) -> tuple[int, int, int]:
    """Volume-by-price value area. Returns (poc_idx, vah_idx, val_idx).

    Starts at the POC (max-volume bin) and grows by adding the heavier of the
    next-two-bins-above vs next-two-bins-below until cumulative >= pct of total.
    """
    if not bins:
        return 0, 0, 0
    total = sum(bins)
    poc = max(range(len(bins)), key=lambda k: bins[k])
    if total <= 0:
        return poc, poc, poc
    lo = hi = poc
    cum = bins[poc]
    target = value_area_pct * total
    while cum < target and (lo > 0 or hi < len(bins) - 1):
        up = bins[hi + 1] + (bins[hi + 2] if hi + 2 < len(bins) else 0.0) if hi < len(bins) - 1 else -1.0
        dn = bins[lo - 1] + (bins[lo - 2] if lo - 2 >= 0 else 0.0) if lo > 0 else -1.0
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi += 1
            cum += bins[hi]
        else:
            lo -= 1
            cum += bins[lo]
    return poc, hi, lo


def _round_magnitude(price: float) -> float:
    if price < 20:
        return 1.0
    if price < 100:
        return 5.0
    if price < 500:
        return 10.0
    if price < 1000:
        return 50.0
    return 100.0


def extract_sr_levels(candles: list[dict], current_price: float, atr14: float,
                      wk52_high: float, wk52_low: float,
                      pivot_n: int = 2) -> list[Anchor]:
    """§3a — swing-pivot S/R + round numbers -> source_type='tech_sr'."""
    out: list[Anchor] = []
    if not candles or len(candles) < 2 * pivot_n + 1 or not atr14 or current_price <= 0:
        return out
    N = len(candles)
    closes = [float(c["close"]) for c in candles]
    median_vol = _median([_vol(c) for c in candles]) or 1.0
    highs, lows = _fractal_pivots(candles, pivot_n)
    pivots = (
        [{**p, "kind": "high"} for p in highs]
        + [{**p, "kind": "low"} for p in lows]
    )
    if not pivots:
        return out
    pivots.sort(key=lambda p: p["price"])
    tol = _tol(atr14, current_price)

    # Greedy single-linkage clustering on pivot price.
    clusters: list[list[dict]] = []
    for p in pivots:
        if clusters and (p["price"] - clusters[-1][0]["price"]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    round_mag = _round_magnitude(current_price)
    for cl in clusters:
        vols = [c["volume"] for c in cl]
        vsum = sum(vols)
        if vsum > 0:
            level_price = sum(c["price"] * c["volume"] for c in cl) / vsum
        else:
            level_price = sum(c["price"] for c in cl) / len(cl)
        touches = len(cl)
        most_recent_idx = max(c["idx"] for c in cl)
        bars_since = N - 1 - most_recent_idx

        # round-number overlay
        nearest_round = round(level_price / round_mag) * round_mag
        round_flag = (
            abs(level_price - nearest_round) <= tol
            and wk52_low <= nearest_round <= wk52_high
        )
        is_52wk_extreme = (
            abs(level_price - wk52_high) <= tol or abs(level_price - wk52_low) <= tol
        )

        # role-reversal flip detection
        flipped = False
        below = [i for i, c in enumerate(closes) if c < level_price - tol]
        above = [i for i, c in enumerate(closes) if c > level_price + tol]
        if below and above:
            # a later close on the opposite side of an earlier breach => flip
            if (min(below) < max(above)) or (min(above) < max(below)):
                flipped = True

        # touches<2 only survives if 52wk-extreme or round-number (capped 40)
        capped = False
        if touches < 2:
            if not (is_52wk_extreme or round_flag):
                continue
            capped = True

        touch_score = min(touches, 5) / 5.0
        recency_score = 0.5 ** (bars_since / 21.0)
        avg_vol = vsum / len(cl) if cl else 0.0
        volume_score = _clamp(avg_vol / median_vol, 0.0, 2.0) / 2.0
        round_bonus = 0.15 if round_flag else 0.0
        flip_bonus = 0.15 if flipped else 0.0
        raw = (0.40 * touch_score + 0.25 * recency_score + 0.20 * volume_score
               + round_bonus + flip_bonus)
        strength = round(100.0 * _clamp(raw, 0.0, 1.0))
        if capped:
            strength = min(strength, 40)
        if strength < 45:
            continue

        label = "swing-%s x%d" % ("R" if flipped else ("S/R"), touches)
        if round_flag:
            label += " round"
        out.append(_method_anchor(
            level_price, "tech_sr", strength=strength, label=label,
            freshness_days=bars_since,
        ))
    return out


def extract_supply_demand_zones(candles: list[dict], current_price: float,
                                atr14: float) -> list[Anchor]:
    """§3b — supply/demand zones -> source_type='tech_zone'.

    Emits two anchors per surviving zone (proximal entry edge + distal stop edge).
    """
    out: list[Anchor] = []
    if not candles or len(candles) < 8 or not atr14 or current_price <= 0:
        return out
    from consensus_engine import config as _cfg
    base_tightness = float(_cfg.get("all_command.levels.base_tightness_atr", 0.5))
    impulse_mult = float(_cfg.get("all_command.levels.impulse_atr_mult", 1.0))

    N = len(candles)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    ranges = [highs[i] - lows[i] for i in range(N)]
    # body uses open ~ prior close
    bodies = [abs(closes[i] - (closes[i - 1] if i > 0 else closes[i])) for i in range(N)]
    true_ranges = [
        max(highs[i] - lows[i],
            abs(highs[i] - (closes[i - 1] if i > 0 else closes[i])),
            abs(lows[i] - (closes[i - 1] if i > 0 else closes[i])))
        for i in range(N)
    ]

    def _sma(arr: list[float], end: int, window: int = 20) -> float:
        lo = max(0, end - window + 1)
        seg = arr[lo:end + 1]
        return sum(seg) / len(seg) if seg else 0.0

    K = 3   # impulse window
    zones: list[dict] = []
    # leave last K bars unconfirmed (look-ahead guard on the departure leg)
    for s in range(1, N - K):
        for B in range(1, 6):
            e = s + B - 1
            if e >= N - K:
                break
            base_high = max(highs[s:e + 1])
            base_low = min(lows[s:e + 1])
            base_width = base_high - base_low
            if base_width > base_tightness * atr14:
                continue
            # indecision: every base candle body <= 0.5 * range
            if any(bodies[i] > 0.5 * ranges[i] for i in range(s, e + 1) if ranges[i] > 0):
                continue

            dep = candles[e + 1:e + 1 + K]
            if len(dep) < 1:
                continue
            dep_closes = closes[e + 1:e + 1 + K]
            avg_range20 = _sma(ranges, e) or 1e-9
            avg_vol20 = _sma([_vol(c) for c in candles], e)

            # DEMAND
            demand_move = max(dep_closes) - base_high
            supply_move = base_low - min(dep_closes)
            for kind, move in (("demand", demand_move), ("supply", supply_move)):
                if move < impulse_mult * atr14:
                    continue
                want_up = kind == "demand"
                erc = 0
                for j in range(e + 1, min(e + 1 + K, N)):
                    same_dir = (closes[j] > closes[j - 1]) if want_up else (closes[j] < closes[j - 1])
                    if (bodies[j] >= 0.5 * ranges[j] if ranges[j] > 0 else False) \
                            and true_ranges[j] >= 1.0 * avg_range20 and same_dir:
                        erc += 1
                if erc < 2:
                    continue

                # leg-in classification over L=3 bars before s
                L = 3
                pre = closes[max(0, s - L):s]
                if kind == "demand":
                    reversal = bool(pre) and pre[-1] < base_high  # drop-in -> DBR
                    ztype = "DBR" if reversal else "RBR"
                    proximal, distal = base_high, base_low
                else:
                    reversal = bool(pre) and pre[-1] > base_low   # rise-in -> RBD
                    ztype = "RBD" if reversal else "DBD"
                    proximal, distal = base_low, base_high

                # freshness T: re-entries after price first moved >= 1 ATR away
                impulse_end = min(e + K, N - 1)
                moved_away = False
                T = 0
                for q in range(impulse_end + 1, N):
                    if not moved_away:
                        if abs(closes[q] - proximal) >= 1.0 * atr14:
                            moved_away = True
                        continue
                    if kind == "demand" and lows[q] <= proximal:
                        T += 1
                    elif kind == "supply" and highs[q] >= proximal:
                        T += 1
                if T >= 3:
                    continue

                # scoring
                impulse_atr = move / atr14
                s_impulse = 35.0 * _clamp((impulse_atr - 1.0) / (3.0 - 1.0), 0.0, 1.0)
                vol_factor_ok = avg_vol20 > 0
                if vol_factor_ok:
                    dep_vols = [_vol(candles[j]) for j in range(e + 1, min(e + 1 + K, N))]
                    vol_ratio = (max(dep_vols) / avg_vol20) if dep_vols else 0.0
                    s_volume = 25.0 * _clamp((vol_ratio - 1.0) / (2.0 - 1.0), 0.0, 1.0)
                else:
                    s_volume = 0.0
                s_fresh = {0: 25.0, 1: 12.0, 2: 4.0}.get(T, 0.0)
                s_type = 10.0 if ztype in ("DBR", "RBD") else 5.0
                s_tight = 5.0 * _clamp((0.5 * atr14 - base_width) / (0.5 * atr14), 0.0, 1.0)
                total = s_impulse + s_volume + s_fresh + s_type + s_tight
                if not vol_factor_ok:
                    total = total / 0.75   # renormalize over remaining 75
                strength = round(_clamp(total, 0.0, 100.0))
                if strength < 50:
                    continue
                bars_since = N - 1 - impulse_end
                zones.append({
                    "kind": kind, "ztype": ztype, "proximal": proximal,
                    "distal": distal, "strength": strength, "freshness": bars_since,
                })

    if not zones:
        return out
    # dedup overlapping zones (>50% overlap -> keep higher score)
    zones.sort(key=lambda z: z["strength"], reverse=True)
    kept: list[dict] = []
    for z in zones:
        zlo, zhi = sorted((z["proximal"], z["distal"]))
        overlap = False
        for k in kept:
            klo, khi = sorted((k["proximal"], k["distal"]))
            inter = max(0.0, min(zhi, khi) - max(zlo, klo))
            span = max(zhi - zlo, 1e-9)
            if inter / span > 0.5:
                overlap = True
                break
        if not overlap:
            kept.append(z)

    for z in kept:
        # discard zones whose distal is within 0.5*ATR of P
        if abs(z["distal"] - current_price) < 0.5 * atr14:
            continue
        out.append(_method_anchor(
            z["proximal"], "tech_zone", strength=z["strength"],
            label="%s demand" % z["ztype"] if z["kind"] == "demand" else "%s supply" % z["ztype"],
            freshness_days=z["freshness"],
        ))
        out.append(_method_anchor(
            z["distal"], "tech_zone", strength=max(0, z["strength"] - 10),
            label="%s distal" % z["ztype"], freshness_days=z["freshness"],
        ))
    return out


def extract_fib_levels(candles: list[dict], current_price: float, atr14: float,
                       wk52_high: float, wk52_low: float,
                       pivot_k: int = 3) -> list[Anchor]:
    """§3c — Fibonacci retracement + extension -> source_type='tech_fib'.

    Invariant (unit-tested): long targets are above entry, short targets below.
    """
    out: list[Anchor] = []
    if not candles or len(candles) < 2 * pivot_k + 1 or not atr14 or current_price <= 0:
        return out
    N = len(candles)
    highs, lows = _fractal_pivots(candles, pivot_k)
    pivots = (
        [{**p, "kind": "high"} for p in highs]
        + [{**p, "kind": "low"} for p in lows]
    )
    pivots.sort(key=lambda p: p["idx"])

    fallback_penalty = 0.0
    leg = None
    best_score = -1.0
    for a, b in zip(pivots, pivots[1:]):
        if a["kind"] == b["kind"]:
            continue
        leg_size = abs(b["price"] - a["price"])
        if leg_size / atr14 < 2.0:
            continue
        recency_weight = max(0.0, 1.0 - (N - 1 - b["idx"]) / 30.0)
        leg_score = (leg_size / atr14) * (0.5 + 0.5 * recency_weight)
        if leg_score > best_score:
            best_score = leg_score
            leg = (a, b, recency_weight)

    if leg is None:
        # fallback: rolling extremes, direction = later extreme; -15 penalty
        hi_idx = max(range(N), key=lambda i: float(candles[i]["high"]))
        lo_idx = min(range(N), key=lambda i: float(candles[i]["low"]))
        a_idx, b_idx = (lo_idx, hi_idx) if hi_idx > lo_idx else (hi_idx, lo_idx)
        a = {"price": float(candles[a_idx]["high"] if a_idx == hi_idx else candles[a_idx]["low"]),
             "idx": a_idx, "kind": "high" if a_idx == hi_idx else "low",
             "volume": _vol(candles[a_idx])}
        b = {"price": float(candles[b_idx]["high"] if b_idx == hi_idx else candles[b_idx]["low"]),
             "idx": b_idx, "kind": "high" if b_idx == hi_idx else "low",
             "volume": _vol(candles[b_idx])}
        recency_weight = max(0.0, 1.0 - (N - 1 - b["idx"]) / 30.0)
        leg = (a, b, recency_weight)
        fallback_penalty = -15.0

    a, b, recency_weight = leg
    up_leg = b["price"] > a["price"]   # low->high => LONG
    H = max(a["price"], b["price"])
    Lp = min(a["price"], b["price"])
    R = H - Lp
    if R <= 0:
        return out
    leg_size = R

    retr_ratios = [0.236, 0.382, 0.5, 0.618, 0.65, 0.786]
    ext_ratios = [1.0, 1.272, 1.414, 1.618, 2.0, 2.618]

    def _ratio_base(r: float) -> float:
        if r in (0.618, 0.65, 1.618):
            return 40.0
        if r in (0.5, 0.786, 1.272):
            return 30.0
        if r in (0.382, 2.0):
            return 20.0
        return 10.0

    # anchor pivot volume bump
    avg_vol = (sum(_vol(c) for c in candles) / N) if N else 0.0
    vol_bump = 8.0 if (b.get("volume", 0.0) > 1.5 * avg_vol and avg_vol > 0) else 0.0
    anchor_quality = min(20.0, 10.0 * (leg_size / atr14 - 2.0)) + 15.0 * recency_weight
    thin_penalty = -10.0 if N < 30 else 0.0

    def _emit(price: float, ratio: float, role_label: str, extra_penalty: float = 0.0):
        strength = (_ratio_base(ratio) + anchor_quality + vol_bump
                    + fallback_penalty + thin_penalty + extra_penalty)
        strength = _clamp(strength, 0.0, 100.0)
        if strength < 40:
            return
        bars_since = N - 1 - b["idx"]
        out.append(_method_anchor(
            price, "tech_fib", strength=strength,
            label="%s %.3f" % (role_label, ratio), freshness_days=bars_since,
        ))

    # retracements
    for r in retr_ratios:
        level = (H - r * R) if up_leg else (Lp + r * R)
        label = "golden-pocket" if r in (0.618, 0.65) else "retr"
        _emit(level, r, label)

    # extensions: C = P if inside pullback else most-recent opposite pivot after B
    inside = Lp <= current_price <= H
    C = current_price if inside else (H if up_leg else Lp)
    for e in ext_ratios:
        if up_leg:
            target = C + e * R
            clamp_tripped = target > wk52_high * 1.5
        else:
            target = C - e * R
            clamp_tripped = target < wk52_low / 1.5
        if clamp_tripped:
            continue
        _emit(target, e, "ext", extra_penalty=-10.0 if (not inside) else 0.0)
    return out


def extract_volume_profile_levels(candles: list[dict], current_price: float,
                                  atr14: float) -> list[Anchor]:
    """§3d — volume profile (POC/VAH/VAL/HVN/LVN) + anchored VWAP -> tech_vp.

    LVN anchors carry method_label 'LVN' so the assembler excludes them as stops.
    """
    out: list[Anchor] = []
    if not candles or len(candles) < 5 or not atr14 or current_price <= 0:
        return out
    from consensus_engine import config as _cfg
    va_pct = float(_cfg.get("all_command.levels.vp_value_area_pct", 0.70))

    N = len(candles)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    r_low, r_high = min(lows), max(highs)
    span = r_high - r_low
    if span <= 0:
        return out
    bin_w = max(span / 50.0, 0.25 * atr14)
    if bin_w <= 0:
        return out
    n_bins = int(_clamp((span / bin_w), 20, 60))
    bin_w = span / n_bins
    bins = [0.0] * n_bins
    bin_centers = [r_low + (k + 0.5) * bin_w for k in range(n_bins)]

    def _bin_idx(price: float) -> int:
        return int(_clamp((price - r_low) / bin_w, 0, n_bins - 1))

    for c in candles:
        lo = float(c["low"])
        hi = float(c["high"])
        v = _vol(c)
        if v <= 0:
            continue
        if hi <= lo:
            bins[_bin_idx(float(c["close"]))] += v
            continue
        k0, k1 = _bin_idx(lo), _bin_idx(hi)
        rng = hi - lo
        for k in range(k0, k1 + 1):
            b_lo = r_low + k * bin_w
            b_hi = b_lo + bin_w
            overlap = max(0.0, min(hi, b_hi) - max(lo, b_lo))
            if overlap > 0:
                bins[k] += v * overlap / rng

    max_bin = max(bins) if bins else 0.0
    if max_bin <= 0:
        return out
    poc_idx, vah_idx, val_idx = _value_area(bins, va_pct)
    mean_bin = sum(bins) / len(bins)

    # smooth for node detection (3-bin moving average)
    smooth = [
        sum(bins[max(0, k - 1):min(n_bins, k + 2)]) / len(bins[max(0, k - 1):min(n_bins, k + 2)])
        for k in range(n_bins)
    ]

    def _touches(price: float) -> int:
        t = 0
        for c in candles:
            if float(c["low"]) - 0.25 * atr14 <= price <= float(c["high"]) + 0.25 * atr14:
                t += 1
        return t

    def _emit_node(k: int, label: str, is_lvn: bool = False, always: bool = False):
        price = bin_centers[k]
        conc = 35.0 * (bins[k] / max_bin)
        touch = min(20.0, _touches(price) * 5.0)
        strength = _clamp((conc + touch) * 0.90, 0.0, 100.0)  # 10% intrabar discount
        if is_lvn:
            label = "LVN"
        # POC/VAH/VAL are the canonical value-area anchors (always emitted);
        # generic HVN nodes still respect the >=50 emit floor.
        if strength < 50 and not is_lvn and not always:
            return
        if is_lvn:
            strength = max(strength, 30.0)  # keep LVNs in the pool to block stops
        bars_since = 0
        out.append(_method_anchor(
            price, "tech_vp", strength=strength, label=label,
            freshness_days=bars_since,
        ))

    _emit_node(poc_idx, "POC", always=True)
    if vah_idx != poc_idx:
        _emit_node(vah_idx, "VAH", always=True)
    if val_idx != poc_idx:
        _emit_node(val_idx, "VAL", always=True)
    for k in range(1, n_bins - 1):
        if k in (poc_idx, vah_idx, val_idx):
            continue
        if smooth[k] > smooth[k - 1] and smooth[k] > smooth[k + 1] and bins[k] >= 1.3 * mean_bin:
            _emit_node(k, "HVN")
        elif smooth[k] < smooth[k - 1] and smooth[k] < smooth[k + 1] and bins[k] <= 0.6 * mean_bin:
            _emit_node(k, "LVN", is_lvn=True)

    # anchored VWAP: anchor at most-recent swing low (long) within last ~20 bars,
    # fallback 63-bar low.
    _, lows_piv = _fractal_pivots(candles, 2)
    anchor_idx = None
    recent = [p for p in lows_piv if p["idx"] >= N - 20]
    if recent:
        anchor_idx = max(recent, key=lambda p: p["idx"])["idx"]
    elif lows_piv:
        anchor_idx = min(lows_piv, key=lambda p: p["price"])["idx"]
    else:
        anchor_idx = min(range(N), key=lambda i: lows[i])
    avwap, sigma = _avwap(candles, anchor_idx)
    if avwap and avwap > 0:
        out.append(_method_anchor(
            avwap, "tech_vp", strength=55.0, label="AVWAP",
            freshness_days=N - 1 - anchor_idx,
        ))
        if sigma > 0:
            for mult, lbl in ((1, "AVWAP+1σ"), (-1, "AVWAP-1σ")):
                out.append(_method_anchor(
                    avwap + mult * sigma, "tech_vp", strength=50.0, label=lbl,
                    freshness_days=N - 1 - anchor_idx,
                ))
    return out


def extract_virgin_poc_levels(candles: list[dict], current_price: float,
                              atr14: float, period: str = "week") -> list[Anchor]:
    """§3e — virgin / naked Point of Control -> source_type='tech_vpoc'.

    Weekly periods (group 5 daily bars). A period POC stays 'virgin' until a
    LATER bar's [low,high] overlaps it (within TOL); survivors are emitted.
    """
    out: list[Anchor] = []
    if not candles or len(candles) < 5 or not atr14 or current_price <= 0:
        return out
    from consensus_engine import config as _cfg
    half_life = float(_cfg.get("all_command.levels.vpoc_half_life_periods", 4))
    survival_bonus = float(_cfg.get("all_command.levels.vpoc_survival_bonus", 7))
    period = _cfg.get("all_command.levels.vpoc_period", period) or period

    N = len(candles)
    group = 5 if period == "week" else 1
    tol = _tol(atr14, current_price)

    # build per-period POCs (chronological)
    periods: list[dict] = []
    p_idx = 0
    for start in range(0, N, group):
        seg = candles[start:start + group]
        if not seg:
            continue
        if group == 1 or len(seg) == 1:
            c = seg[0]
            poc = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
            pvol = _vol(c)
            last_idx = start
        else:
            seg_low = min(float(c["low"]) for c in seg)
            seg_high = max(float(c["high"]) for c in seg)
            sp = seg_high - seg_low
            if sp <= 0:
                poc = (seg_high + seg_low + float(seg[-1]["close"])) / 3.0
                pvol = sum(_vol(c) for c in seg)
            else:
                bw = max(sp / 20.0, 0.25 * atr14)
                nb = int(_clamp(sp / bw, 5, 20))
                bw = sp / nb
                sb = [0.0] * nb
                centers = [seg_low + (k + 0.5) * bw for k in range(nb)]
                for c in seg:
                    lo, hi, v = float(c["low"]), float(c["high"]), _vol(c)
                    if v <= 0:
                        continue
                    if hi <= lo:
                        k = int(_clamp((float(c["close"]) - seg_low) / bw, 0, nb - 1))
                        sb[k] += v
                        continue
                    k0 = int(_clamp((lo - seg_low) / bw, 0, nb - 1))
                    k1 = int(_clamp((hi - seg_low) / bw, 0, nb - 1))
                    rng = hi - lo
                    for k in range(k0, k1 + 1):
                        b_lo = seg_low + k * bw
                        b_hi = b_lo + bw
                        ov = max(0.0, min(hi, b_hi) - max(lo, b_lo))
                        if ov > 0:
                            sb[k] += v * ov / rng
                if max(sb) <= 0:
                    poc = (seg_high + seg_low + float(seg[-1]["close"])) / 3.0
                else:
                    poc = centers[max(range(nb), key=lambda k: sb[k])]
                pvol = sum(_vol(c) for c in seg)
            last_idx = start + len(seg) - 1
        periods.append({"poc": poc, "vol": pvol, "last_idx": last_idx, "pidx": p_idx})
        p_idx += 1

    if not periods:
        return out
    max_pvol = max(p["vol"] for p in periods) or 1.0
    total_periods = len(periods)

    for p in periods:
        poc = p["poc"]
        # virginity test: any LATER bar whose [low,high] overlaps poc (within TOL)
        crossed_tol = False
        graze_tol = False
        graze_2tol = False
        for q in range(p["last_idx"] + 1, N):
            lo = float(candles[q]["low"])
            hi = float(candles[q]["high"])
            if lo - tol <= poc <= hi + tol:
                crossed_tol = True
                break
            if lo - 2 * tol <= poc <= hi + 2 * tol:
                graze_2tol = True
        if crossed_tol:
            continue  # filled -> not virgin
        # cleanliness scaling
        if not graze_2tol:
            cleanliness = 15.0
        elif not graze_tol:
            cleanliness = 8.0
        else:
            cleanliness = 3.0

        if abs(poc - current_price) < 0.5 * atr14:
            continue

        periods_since = total_periods - 1 - p["pidx"]
        s_vol = 40.0 * (p["vol"] / max_pvol)
        s_rec = 25.0 * (0.5 ** (periods_since / half_life)) if half_life > 0 else 0.0
        if periods_since >= 2 * half_life:
            s_rec += survival_bonus   # overdue-magnet branch (§3e)
        dist_pct = abs(poc - current_price) / current_price
        s_dist = 20.0 * _clamp(1.0 - dist_pct / 0.5, 0.0, 1.0)
        strength = _clamp(s_vol + s_rec + s_dist + cleanliness, 0.0, 100.0)
        if strength < 45:
            continue
        bars_since = N - 1 - p["last_idx"]
        out.append(_method_anchor(
            poc, "tech_vpoc", strength=strength,
            label="vPOC p%d" % p["pidx"], freshness_days=bars_since,
        ))
    return out


def build_technical_anchors(candles: list[dict], current_price: float, atr14: float,
                            wk52_high: float, wk52_low: float) -> list[Anchor]:
    """Orchestrator: run the five extractors and return the concatenated tech_*
    anchors. No clustering here — the aggregator clusters tech + crowd (§4).

    Recomputes ATR from candles when the passed atr14 is missing/zero so the
    engine never silently no-ops on a stale ATR.
    """
    if not candles or current_price is None or current_price <= 0:
        return []
    atr = atr14 if (atr14 and atr14 > 0) else (_atr14(candles) or 0.0)
    if atr <= 0:
        return []
    wk_hi = wk52_high if (wk52_high and wk52_high > 0) else current_price
    wk_lo = wk52_low if (wk52_low and wk52_low > 0) else current_price
    if wk_hi < wk_lo:
        wk_hi, wk_lo = wk_lo, wk_hi

    from consensus_engine import config as _cfg
    pivot_n = int(_cfg.get("all_command.levels.pivot_n", 2))
    pivot_k = int(_cfg.get("all_command.levels.pivot_k", 3))
    vpoc_period = _cfg.get("all_command.levels.vpoc_period", "week")

    out: list[Anchor] = []
    out += extract_sr_levels(candles, current_price, atr, wk_hi, wk_lo, pivot_n=pivot_n)
    out += extract_supply_demand_zones(candles, current_price, atr)
    out += extract_fib_levels(candles, current_price, atr, wk_hi, wk_lo, pivot_k=pivot_k)
    out += extract_volume_profile_levels(candles, current_price, atr)
    out += extract_virgin_poc_levels(candles, current_price, atr, period=vpoc_period)
    return out


def extract_anchors_from_search_snippets(
    snippets: list[str],
    current_price: float,
) -> list[Anchor]:
    """Parse web search snippets for $-prefixed prices near trigger words.

    Applies the price regex with a 60-char context window. Rejects matches
    near negative-context tokens (billion, million, EPS, P/E, revenue,
    market cap, shares, %). Requires a trigger word ("target", "support",
    "resistance", "level", "stop", "price") within ±3 tokens. Clamps
    0.01 < price < 100000.
    """
    anchors: list[Anchor] = []
    for snippet in snippets or []:
        if not snippet or not isinstance(snippet, str):
            continue
        for m in PRICE_RE.finditer(snippet):
            raw_price = m.group(1).replace(",", "")
            try:
                price_f = float(raw_price)
            except ValueError:
                continue
            if not (0.01 < price_f < 100000):
                continue

            start = max(0, m.start() - 60)
            end = min(len(snippet), m.end() + 60)
            window = snippet[start:end].lower()

            # Reject negative context
            if any(neg in window for neg in NEGATIVE_CONTEXT):
                continue

            # Tokenize ±3 words around the match
            pre_text = snippet[start:m.start()].lower()
            post_text = snippet[m.end():end].lower()
            pre_tokens = re.findall(r"\w+", pre_text)[-3:]
            post_tokens = re.findall(r"\w+", post_text)[:3]
            nearby = set(pre_tokens) | set(post_tokens)
            if not (nearby & TRIGGER_WORDS):
                continue

            anchors.append(Anchor(
                price=price_f,
                source="web",
                source_type="web",
                touches=1,
                freshness_days=0,
            ))
    return anchors


def cluster_anchors(
    anchors: list[Anchor],
    threshold_pct: float = 0.005,
) -> list[Anchor]:
    """Cluster anchors within 0.5% of each other.

    Merged anchor takes the average price, summed source_count, max touches,
    max volume_strength, min freshness_days. Sources are concatenated in
    the source field (semicolon-separated).
    """
    if not anchors:
        return []

    # Sort by price, then sweep with linear cluster window
    sorted_anchors = sorted(anchors, key=lambda a: a.price)
    clusters: list[list[Anchor]] = []
    for a in sorted_anchors:
        if not clusters:
            clusters.append([a])
            continue
        cluster_prices = [c.price for c in clusters[-1]]
        centroid = sum(cluster_prices) / len(cluster_prices)
        if abs(a.price - centroid) / max(centroid, 1e-9) <= threshold_pct:
            clusters[-1].append(a)
        else:
            clusters.append([a])

    merged: list[Anchor] = []
    for cluster in clusters:
        if len(cluster) == 1:
            singleton = cluster[0]
            if singleton.cluster_source_types is None:
                singleton.cluster_source_types = {singleton.source_type}
            merged.append(singleton)
            continue
        avg_price = sum(c.price for c in cluster) / len(cluster)
        merged_sources = ";".join(sorted({c.source for c in cluster}))
        tier_set = {c.source_type for c in cluster}
        # W2 CEF-3 fix: max-tier-in-cluster instead of cluster[0] first-arrival.
        merged_type = _max_tier([c.source_type for c in cluster])
        # Prefer the highest trust score among the cluster's contributors.
        trust_values = [c.trust_score for c in cluster if c.trust_score is not None]
        merged_trust = max(trust_values) if trust_values else None
        # Channel attribution: pick a channel_id from the contributing
        # anchor that matches the winning tier, if any.
        merged_channel_id = next(
            (c.channel_id for c in cluster
             if c.source_type == merged_type and c.channel_id),
            None,
        )
        # Wave 2: carry the strongest method_strength/label through the merge so
        # technical anchors keep their per-method confidence after clustering
        # (rung-2 strength gate + per-level embed provenance depend on it).
        # Prefer the strongest contributor whose type matches the winning tier
        # so the label stays coherent with the displayed source_type.
        _typed = [c for c in cluster
                  if c.source_type == merged_type and c.method_strength is not None]
        _any = [c for c in cluster if c.method_strength is not None]
        _strong = (max(_typed, key=lambda c: c.method_strength) if _typed
                   else (max(_any, key=lambda c: c.method_strength) if _any else None))
        merged_method_strength = _strong.method_strength if _strong else None
        merged_method_label = _strong.method_label if _strong else None
        merged.append(Anchor(
            price=avg_price,
            source=merged_sources,
            source_type=merged_type,
            touches=max(c.touches for c in cluster),
            volume_strength=max(c.volume_strength for c in cluster),
            freshness_days=min(c.freshness_days for c in cluster),
            source_count=sum(c.source_count for c in cluster),
            channel_id=merged_channel_id,
            trust_score=merged_trust,
            cluster_source_types=tier_set,
            method_strength=merged_method_strength,
            method_label=merged_method_label,
        ))
    return merged


def rank_anchors(
    anchors: list[Anchor],
    current_price: float,
    *,
    ticker: Optional[str] = None,
) -> tuple[list[Anchor], list[Anchor]]:
    """Score, split into supports/resistances, and sort by descending score.

    Returns (supports_below, resistances_above). An anchor exactly at the
    current price is dropped (cannot serve as either side of a trade plan).

    W3 shadow mode: computes both v1 (base touches/volume/source/freshness)
    and v2 (with distance penalty + tier multiplier) scores. v1 drives the
    actual sort; v2 is stashed on `anchor.score_v2` and emitted via a
    structured log line (`score_v1`, `score_v2`, `delta`) for observability.
    The `ticker` kwarg is passed by the aggregator so review scripts can
    group log lines by !all invocation. Flip `all_command.score_v2_shadow_mode`
    to false in config once the distribution is validated.
    """
    import logging as _logging
    log = _logging.getLogger("consensus_engine.alerts.all_command.levels")

    from consensus_engine import config as _cfg
    shadow_mode = bool(_cfg.get("all_command.score_v2_shadow_mode", True))
    confluence_enabled = bool(_cfg.get("all_command.confluence_bonus_enabled", False))

    supports: list[Anchor] = []
    resistances: list[Anchor] = []
    for a in anchors:
        v1 = _score(a)
        a.computed_score = v1
        if shadow_mode and current_price and current_price > 0:
            v2 = _score_v2(
                a,
                current_price=current_price,
                confluence_bonus_enabled=confluence_enabled,
            )
            # Stash v2 so callers (and W5 confluence bonus) can inspect.
            setattr(a, "score_v2", v2)
            log.info(
                "score_shadow ticker=%s current_price=%.2f anchor_price=%.2f source_type=%s "
                "score_v1=%.2f score_v2=%.2f delta=%.2f distance_pct=%s",
                ticker or "UNKNOWN", float(current_price), a.price, a.source_type,
                v1, v2, v2 - v1,
                f"{a.distance_pct:.4f}" if a.distance_pct is not None else "None",
            )
        if a.price < current_price:
            supports.append(a)
        elif a.price > current_price:
            resistances.append(a)
    supports.sort(key=lambda a: a.computed_score, reverse=True)
    resistances.sort(key=lambda a: a.computed_score, reverse=True)
    return supports, resistances


# TODO #10 / #12 — drawdown sanity gate + ATR fallback + horizon-aware rerank.
_SL_MAX_DRAWDOWN_PCT_DEFAULT = 0.20  # 20% — sane for swing horizons
_SHORT_HORIZON_DAYS = 5
_HORIZON_RERANK_TIGHT_BAND_MULT = 1.5
_HORIZON_RERANK_FAR_PENALTY_PCT = 0.05


def _compute_atr_fallback(
    spot: float, atr14: float, direction: str,
) -> tuple[float, list[float]]:
    """Direction-aware ATR fallback levels.

    BULLISH/NEUTRAL: SL = spot − 2×ATR, TPs = spot + 1/2/3×ATR
    BEARISH: SL = spot + 2×ATR, TPs = spot − 1/2/3×ATR

    Why: anchor scarcity + drawdown-gate rejection both produce all-None
    plans (AMD/TSLA 2026-05-18 baseline). ATR fallback ensures every
    embed renders complete numeric levels with a footer flag for the
    user.
    """
    # Round to 2 decimals at source: prevents float-precision leak into the
    # LLM prompt (e.g. "$205.80005428716825" — TODO #7-style regression caught
    # in iter3 NVDA). Matches the precision the embed renderer expects.
    def _r(x): return round(x, 2)
    if (direction or "").upper() == "BEARISH":
        return _r(spot + 2 * atr14), [
            _r(spot - 1 * atr14), _r(spot - 2 * atr14), _r(spot - 3 * atr14),
        ]
    return _r(spot - 2 * atr14), [
        _r(spot + 1 * atr14), _r(spot + 2 * atr14), _r(spot + 3 * atr14),
    ]


def _rerank_short_horizon(
    anchors: list[Anchor], spot: float, atr14: float,
) -> list[Anchor]:
    """Re-rank anchors for short-horizon trades (TODO #12).

    Bumps anchors within ±1.5×ATR of spot; penalises anchors implying >5%
    drawdown. Triggered when earnings_days ≤ 5 so SL doesn't anchor to a
    20-day support level (NVDA 2026-05-18 $178 SL with 2-day catalyst horizon).
    """
    tight = _HORIZON_RERANK_TIGHT_BAND_MULT * atr14
    far_pct = _HORIZON_RERANK_FAR_PENALTY_PCT

    def adj_score(a: Anchor) -> float:
        dist = abs(a.price - spot)
        dist_pct = dist / spot if spot else 0.0
        adj = 0.0
        if dist <= tight:
            adj += 0.5
        if dist_pct > far_pct:
            adj -= 0.3
        return (a.computed_score or 0.0) + adj

    return sorted(anchors, key=adj_score, reverse=True)


def _is_lvn(anchor: Anchor) -> bool:
    return getattr(anchor, "method_label", None) == "LVN"


def _stop_inside_lvn(stop: float, anchors: list[Anchor], atr14: float) -> bool:
    """True if the proposed stop sits within 0.5*ATR of any LVN level."""
    if stop is None or not atr14:
        return False
    band = 0.5 * atr14
    return any(_is_lvn(a) and abs(a.price - stop) <= band for a in anchors)


def _select_trade_plan_ladder(
    supports: list[Anchor],
    resistances: list[Anchor],
    *,
    spot: Optional[float] = None,
    atr14: Optional[float] = None,
    direction: str = "BULLISH",
    earnings_days: Optional[int] = None,
) -> dict:
    """3-rung trade-plan ladder (Wave 2 smart-levels).

    RUNG 1  real + technical anchors clustered >= min_anchors_for_plan, with a
            structure stop + >=1 TP surviving the gates and R:R >= floor.
    RUNG 2  technical-only structure plan (entry-support strength >= min_entry_
            strength) when rung 1 fails the count gate but tech levels exist.
    RUNG 3  existing ATR fallback (UNCHANGED) — delegated to the legacy path.

    Returns the 6 legacy keys PLUS entry/risk_reward/rung/levels and richer
    confidence values (high/medium/low).
    """
    from consensus_engine import config as _cfg

    def _legacy_rung3() -> dict:
        # Rung 3 is the PURE ATR last-resort (design §2.3). Pass NO anchors so
        # the legacy path deterministically hits _compute_atr_fallback (monotonic
        # spot±N×ATR) instead of the score-ordered ≥4-anchor branch — which, fed
        # the tech-enriched anchor set, could emit non-monotonic TPs.
        base = select_trade_plan(
            [], [], spot=spot, atr14=atr14,
            direction=direction, earnings_days=earnings_days, engine_on=False,
        )
        base["entry"] = round(spot, 2) if spot else None
        base["risk_reward"] = None
        base["rung"] = 3
        base["levels"] = None
        return base

    direction_u = (direction or "").upper()
    if direction_u == "NEUTRAL" or not spot or spot <= 0 or not atr14 or atr14 <= 0:
        return _legacy_rung3()

    min_anchors = int(_cfg.get("all_command.levels.min_anchors_for_plan", 4))
    min_entry_strength = float(_cfg.get("all_command.levels.min_entry_strength", 55))
    min_rr = float(_cfg.get("all_command.levels.min_reward_risk", 1.5))
    sl_max_drawdown = float(_cfg.get(
        "all_command.levels.sl_max_drawdown_pct", _SL_MAX_DRAWDOWN_PCT_DEFAULT))

    is_long = direction_u != "BEARISH"
    # profit side: long -> resistances above; short -> supports below.
    profit = resistances if is_long else supports
    stop_side = supports if is_long else resistances
    all_anchors = list(supports) + list(resistances)

    def _strength(a: Anchor) -> float:
        return float(getattr(a, "method_strength", None) or 0.0)

    # rank profit/stop sides by score (already sorted by caller, but re-stable).
    stop_side = [a for a in stop_side if not _is_lvn(a)]  # never stop at an LVN
    stop_side_sorted = sorted(stop_side, key=lambda a: a.computed_score, reverse=True)
    profit_sorted = sorted(
        [a for a in profit], key=lambda a: abs(a.price - spot))  # nearest-first ladder

    def _build_stop(candidates: list[Anchor]) -> tuple[Optional[float], Optional[Anchor]]:
        buffer = max(0.10 * atr14, 0.001 * spot)
        for cand in candidates:
            if is_long:
                struct = cand.price - buffer
                dist = spot - struct
            else:
                struct = cand.price + buffer
                dist = struct - spot
            if dist <= 0:
                continue
            chosen = struct if dist >= 1.0 * atr14 else (
                spot - 1.0 * atr14 if is_long else spot + 1.0 * atr14)
            # drawdown gate
            if abs(spot - chosen) / spot > sl_max_drawdown:
                continue
            if _stop_inside_lvn(chosen, all_anchors, atr14):
                continue
            return round(chosen, 2), cand
        return None, None

    def _build_tps(risk_r: float) -> list[dict]:
        """Profit ladder. Each TP prefers the next REAL profit-side level beyond
        the previous TP; TP1 must clear the min R:R floor (so a too-close level
        is skipped, NOT demoted to a 1.0R filler — that would peg R:R at 1.0 and
        the gate would reject everything). Missing slots are filled with the
        R-multiple defaults (1R/2R/3R) and flagged as fillers (design §5)."""
        out: list[dict] = []
        floors = [1.0, 2.0, 3.0]
        # min distance each slot must satisfy: TP1 honors the R:R floor.
        min_dist = [min_rr * risk_r, 2.0 * risk_r, 3.0 * risk_r]
        consumed: set[int] = set()
        last_price = spot
        for i in range(3):
            level = None
            level_idx = None
            for idx, a in enumerate(profit_sorted):
                if idx in consumed:
                    continue
                beyond_prev = (a.price > last_price) if is_long else (a.price < last_price)
                far_enough = abs(a.price - spot) >= min_dist[i] - 1e-9
                if beyond_prev and far_enough:
                    level = a
                    level_idx = idx
                    break
            if level is not None:
                consumed.add(level_idx)
                price = round(level.price, 2)
                is_filler = False
                method = level.source_type
                label = getattr(level, "method_label", None) or method
                strength = _strength(level)
                conf_src = sorted(getattr(level, "cluster_source_types", None)
                                  or {level.source_type})
            else:
                base = (spot + floors[i] * risk_r) if is_long else (spot - floors[i] * risk_r)
                # keep the ladder monotonic: a filler must sit BEYOND the prior TP.
                if i > 0:
                    step = max(0.5 * risk_r, 0.001 * spot)
                    base = (max(base, last_price + step) if is_long
                            else min(base, last_price - step))
                price = round(base, 2)
                is_filler = True
                method = "atr"
                label = "%dR" % int(floors[i])
                strength = 0.0
                conf_src = []
            last_price = price
            out.append({
                "role": "tp%d" % (i + 1), "price": price, "method": method,
                "label": label, "strength": strength,
                "confluence_sources": conf_src, "is_filler": is_filler,
            })
        return out

    def _try_rung(stop_candidates: list[Anchor], rung: int) -> Optional[dict]:
        stop, stop_anchor = _build_stop(stop_candidates)
        if stop is None:
            return None
        risk_r = abs(spot - stop)
        if risk_r <= 0:
            return None
        tps = _build_tps(risk_r)
        tp1 = tps[0]["price"]
        # nearest-TP R:R floor — REJECT, never shrink the stop.
        rr_nearest = abs(tp1 - spot) / risk_r
        if rr_nearest < min_rr:
            return None
        # require a profit-side level inside the 52wk range proxy (skip pure fillers)
        if all(t["is_filler"] for t in tps):
            return None
        # entry cluster confluence (nearest stop anchor's cluster)
        entry_cluster = sorted(
            getattr(stop_anchor, "cluster_source_types", None) or {stop_anchor.source_type})
        distinct_types = len(entry_cluster)
        no_filler = not any(t["is_filler"] for t in tps)
        if distinct_types >= 3 and rr_nearest >= 2.0 and no_filler:
            conf = "high"
        elif rung == 1 and (distinct_types == 2 or rr_nearest >= 1.5):
            conf = "medium" if rr_nearest < 2.0 or distinct_types < 3 else "high"
        else:
            conf = "medium"
        levels_meta = [{
            "role": "entry", "price": round(spot, 2), "method": "spot",
            "label": "spot", "strength": None, "confluence_sources": [],
            "is_filler": False,
        }, {
            "role": "stop", "price": stop, "method": stop_anchor.source_type,
            "label": getattr(stop_anchor, "method_label", None) or stop_anchor.source_type,
            "strength": _strength(stop_anchor), "confluence_sources": entry_cluster,
            "is_filler": False,
        }] + tps
        reasons: list[str] = []
        if any(t["is_filler"] for t in tps):
            reasons.append("some TPs filled with R-multiple defaults")
        return {
            "sl": stop, "tp1": tps[0]["price"], "tp2": tps[1]["price"],
            "tp3": tps[2]["price"],
            "suppression_reason": "; ".join(reasons) if reasons else None,
            "confidence": conf,
            "entry": round(spot, 2),
            "risk_reward": round(rr_nearest, 1),
            "rung": rung,
            "levels": levels_meta,
        }

    # RUNG 1 — real + technical clustered >= min_anchors_for_plan.
    total = len(supports) + len(resistances)
    if total >= min_anchors and stop_side_sorted and profit_sorted:
        plan = _try_rung(stop_side_sorted, rung=1)
        if plan is not None:
            return plan

    # RUNG 2 — technical-only structure plan.
    tech_stops = [a for a in stop_side_sorted
                  if a.source_type.startswith("tech_") and _strength(a) >= min_entry_strength]
    tech_profit = [a for a in profit_sorted if a.source_type.startswith("tech_")]
    if tech_stops and tech_profit:
        plan = _try_rung(tech_stops, rung=2)
        if plan is not None:
            # rung-2 caps at medium confidence
            if plan["confidence"] == "high":
                plan["confidence"] = "medium"
            return plan

    # RUNG 3 — ATR last resort (unchanged).
    return _legacy_rung3()


def select_trade_plan(
    supports: list[Anchor],
    resistances: list[Anchor],
    *,
    spot: Optional[float] = None,
    atr14: Optional[float] = None,
    direction: str = "BULLISH",
    earnings_days: Optional[int] = None,
    engine_on: bool = False,
) -> dict:
    """Pick 1 best support + up to 3 best resistances per locked decision D1.

    D1 is "anchored-only ... suppress trade plan if <4 anchors after gap-fill".
    PR3 honored that total-count gate; TODO #10 extends it with an ATR
    fallback so the embed never silently renders "—" when ATR is available.

    Kwargs (TODO #10 / #12 — all default None preserves prior behavior for
    existing callers and tests that pass only the two positional args):
      spot          — current price (required for drawdown gate + ATR fallback)
      atr14         — ATR(14) value (required for ATR fallback + horizon rerank)
      direction     — BULLISH/BEARISH/NEUTRAL; NEUTRAL disables ATR fallback
      earnings_days — when ≤5, triggers horizon-aware re-rank of anchors
      engine_on     — Wave 2 smart-levels switch. When False (default), the
                      LEGACY path runs unchanged and the dict has exactly the
                      6 historical keys (byte-identical to today). When True, a
                      3-rung ladder runs and the dict gains entry/risk_reward/
                      rung/levels plus richer confidence (high/medium/low).

    The returned dict always has the same 6 keys; `suppression_reason` is
    populated when ATR fallback fires or when the original gates trip.
    """
    if engine_on:
        return _select_trade_plan_ladder(
            supports, resistances, spot=spot, atr14=atr14,
            direction=direction, earnings_days=earnings_days,
        )
    from consensus_engine import config as _cfg
    sl_max_drawdown = float(_cfg.get(
        "all_command.levels.sl_max_drawdown_pct",
        _SL_MAX_DRAWDOWN_PCT_DEFAULT,
    ))

    # TODO #12 — horizon-aware re-rank when short catalyst window known.
    if (
        earnings_days is not None
        and earnings_days <= _SHORT_HORIZON_DAYS
        and atr14 is not None
        and spot
    ):
        supports = _rerank_short_horizon(supports, spot, atr14)
        resistances = _rerank_short_horizon(resistances, spot, atr14)

    total = len(supports) + len(resistances)

    if total >= 4:
        sl = supports[0].price if supports else None
        tp_prices = [r.price for r in resistances[:3]]
        # TODO #10 — drawdown sanity gate (default 20%)
        if (
            sl is not None and spot is not None
            and abs(spot - sl) / spot > sl_max_drawdown
        ):
            sl = None  # forces ATR fallback below
        # TODO #12 — horizon-aware drawdown gate: when a short catalyst
        # window is known, SL must be within ~3×ATR of spot or it's
        # incoherent with the horizon (NVDA $178 SL with 2-day catalyst).
        elif (
            sl is not None and spot is not None
            and atr14 is not None
            and earnings_days is not None
            and earnings_days <= _SHORT_HORIZON_DAYS
            and abs(spot - sl) > 3 * atr14
        ):
            sl = None  # ATR fallback (2×ATR) is more coherent
    else:
        sl = None
        tp_prices = []

    tps: list[Optional[float]] = list(tp_prices) + [None] * (3 - len(tp_prices))

    # TODO #10 — ATR fallback for any missing SL/TP. Requires ATR + spot.
    # NEUTRAL direction is left alone (callers wipe levels for NEUTRAL anyway).
    used_fallback = False
    if (
        (sl is None or any(t is None for t in tps))
        and atr14 is not None
        and spot
        and (direction or "").upper() != "NEUTRAL"
    ):
        sl_fb, tps_fb = _compute_atr_fallback(spot, atr14, direction)
        if sl is None:
            sl = sl_fb
            used_fallback = True
        for i in range(3):
            if tps[i] is None:
                tps[i] = tps_fb[i]
                used_fallback = True

    reasons: list[str] = []
    if used_fallback:
        reasons.append("atr_fallback (low anchor confluence)")
    if total < 4 and not used_fallback:
        reasons.append(f"only {total} anchors after gap-fill (need 4)")
    elif total >= 4:
        if not supports and not used_fallback:
            reasons.append("no support anchors below current price")
        if len(resistances) < 3 and not used_fallback:
            reasons.append(
                f"fewer than 3 resistances ({len(resistances)} found); "
                "TP2/TP3 padded with None"
            )

    if used_fallback:
        obs_log({"ts": time.time(), "event": "sltp_atr_fallback", "spot": spot, "atr14": atr14})
    return {
        "sl": sl,
        "tp1": tps[0],
        "tp2": tps[1],
        "tp3": tps[2],
        "suppression_reason": "; ".join(reasons) if reasons else None,
        # Pass 5 Step 11 — confidence annotation: "low" when ATR fallback fires
        # (candle-pivot scarcity), None otherwise (anchor-derived levels).
        "confidence": "low" if used_fallback else None,
    }
