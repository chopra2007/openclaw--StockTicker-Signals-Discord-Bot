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


@dataclass
class Anchor:
    """A single price anchor with provenance and ranking metadata."""
    price: float
    source: str               # e.g. "youtube:LunaTrades", "swing_high", "web:reuters.com"
    source_type: str          # "yt" | "swing" | "web"
    touches: int = 0
    volume_strength: float = 0.0
    freshness_days: int = 0
    computed_score: float = 0.0
    source_count: int = 1     # increases when anchors merge in clustering


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
        anchors.append(Anchor(
            price=price_f,
            source=f"youtube:{channel}",
            source_type="yt",
            touches=int(row.get("touches", 0) or 0),
            volume_strength=float(row.get("volume_strength", 0.0) or 0.0),
            freshness_days=int(freshness),
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
            merged.append(cluster[0])
            continue
        avg_price = sum(c.price for c in cluster) / len(cluster)
        merged_sources = ";".join(sorted({c.source for c in cluster}))
        merged.append(Anchor(
            price=avg_price,
            source=merged_sources,
            source_type=cluster[0].source_type,
            touches=max(c.touches for c in cluster),
            volume_strength=max(c.volume_strength for c in cluster),
            freshness_days=min(c.freshness_days for c in cluster),
            source_count=sum(c.source_count for c in cluster),
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
) -> Optional[dict]:
    """Pick 1 best support + 3 best resistances.

    If fewer than 4 total anchors are available across both lists, return None
    (signals suppression to the caller). Otherwise return a dict with keys
    'sl', 'tp1', 'tp2', 'tp3' as float prices.
    """
    total = len(supports) + len(resistances)
    if total < 4:
        return None
    if not supports or len(resistances) < 3:
        return None
    return {
        "sl": supports[0].price,
        "tp1": resistances[0].price,
        "tp2": resistances[1].price,
        "tp3": resistances[2].price,
    }
