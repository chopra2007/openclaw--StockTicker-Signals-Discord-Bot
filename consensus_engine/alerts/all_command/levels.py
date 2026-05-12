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


def extract_anchors_from_youtube_levels(rows: list[dict]) -> list[Anchor]:
    """Convert youtube_levels DB rows to Anchor objects.

    Expected row keys: price, channel_name, level_type, freshness_days (optional).
    W2: also reads `channel_id`, `trust_score`, `approved` (from the LEFT JOIN
    in db.get_youtube_levels_for_ticker). When trust_score >= 0.7 AND approved=1
    the anchor is tagged `yt_curated`; otherwise it falls into `yt` tier.
    Bootstrap default for missing/null trust is 0.5 (yt tier), NOT 0.2 (web tier) —
    CEF-1 amendment to keep unregistered channels from collapsing under C-C3.
    Rows missing price are skipped.
    """
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
) -> tuple[list[Anchor], list[Anchor]]:
    """Score, split into supports/resistances, and sort by descending score.

    Returns (supports_below, resistances_above). An anchor exactly at the
    current price is dropped (cannot serve as either side of a trade plan).
    """
    supports: list[Anchor] = []
    resistances: list[Anchor] = []
    for a in anchors:
        a.computed_score = _score(a)
        if a.price < current_price:
            supports.append(a)
        elif a.price > current_price:
            resistances.append(a)
    supports.sort(key=lambda a: a.computed_score, reverse=True)
    resistances.sort(key=lambda a: a.computed_score, reverse=True)
    return supports, resistances


def select_trade_plan(
    supports: list[Anchor],
    resistances: list[Anchor],
) -> dict:
    """Pick 1 best support + up to 3 best resistances per locked decision D1.

    D1 is "anchored-only ... suppress trade plan if <4 anchors after gap-fill".
    PR3 honors that total-count gate. With ≥4 total but fewer than 3
    resistances (or no support below price), populate what is available and
    pad the rest with `None`. The returned dict always has the same keys so
    callers can read `suppression_reason` to explain partial / fully empty
    plans without a None-vs-dict branch.
    """
    total = len(supports) + len(resistances)
    if total < 4:
        return {
            "sl": None, "tp1": None, "tp2": None, "tp3": None,
            "suppression_reason": f"only {total} anchors after gap-fill (need 4)",
        }

    sl = supports[0].price if supports else None
    tp_prices = [r.price for r in resistances[:3]]
    tps = tp_prices + [None] * (3 - len(tp_prices))

    reasons: list[str] = []
    if not supports:
        reasons.append("no support anchors below current price")
    if len(resistances) < 3:
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
