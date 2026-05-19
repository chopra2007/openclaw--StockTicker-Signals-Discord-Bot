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
from dataclasses import dataclass, field
from typing import Optional


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
SOURCE_TIER_ORDER: tuple[str, ...] = ("yt_curated", "swing", "yt", "web")


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
    if (direction or "").upper() == "BEARISH":
        return spot + 2 * atr14, [
            spot - 1 * atr14, spot - 2 * atr14, spot - 3 * atr14,
        ]
    return spot - 2 * atr14, [
        spot + 1 * atr14, spot + 2 * atr14, spot + 3 * atr14,
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


def select_trade_plan(
    supports: list[Anchor],
    resistances: list[Anchor],
    *,
    spot: Optional[float] = None,
    atr14: Optional[float] = None,
    direction: str = "BULLISH",
    earnings_days: Optional[int] = None,
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

    The returned dict always has the same keys; `suppression_reason` is
    populated when ATR fallback fires or when the original gates trip.
    """
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
        # TODO #10 — drawdown sanity gate
        if (
            sl is not None and spot is not None
            and abs(spot - sl) / spot > sl_max_drawdown
        ):
            sl = None  # forces ATR fallback below
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

    return {
        "sl": sl,
        "tp1": tps[0],
        "tp2": tps[1],
        "tp3": tps[2],
        "suppression_reason": "; ".join(reasons) if reasons else None,
    }
