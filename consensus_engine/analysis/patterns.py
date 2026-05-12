"""Chart pattern detection for !all narrative grounding.

Each detector takes a list of dict candles where each row contains at
minimum `high` and `low` (and optionally `close`). When `close` is
absent the midpoint (high+low)/2 is used.

Detectors return either None (pattern absent) or
    {"pattern": str, "confidence": float in [0,1], "key_level": float}

`key_level` is the actionable price level a trader would watch:
  - breakout_above_n_day_high: the prior N-day max high
  - bull_flag: top of the consolidation channel (breakout target)
  - double_bottom: the intervening peak (neckline)
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.analysis.patterns")


async def fetch_daily_candles(ticker: str, range_str: str = "3mo") -> list[dict]:
    """Fetch ~60 days of daily OHLC bars via Yahoo Finance chart endpoint.

    Returns list-of-dict in chronological order with `high`, `low`, `close`
    keys per bar — the shape consumed by the pattern detectors below.
    """
    if not ticker:
        return []
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": range_str}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        session = await get_session()
        async with session.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return []
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]
            highs = quote.get("high", []) or []
            lows = quote.get("low", []) or []
            closes = quote.get("close", []) or []
    except Exception as e:
        log.debug("yfinance chart fetch error for %s: %s", ticker, e)
        return []
    n = min(len(highs), len(lows), len(closes))
    out: list[dict] = []
    for i in range(n):
        h, l, c = highs[i], lows[i], closes[i]
        if h is None or l is None:
            continue
        out.append({"high": float(h), "low": float(l),
                    "close": float(c) if c is not None else (float(h) + float(l)) / 2})
    return out


def _close(candle: dict) -> float:
    c = candle.get("close")
    if c is not None:
        return float(c)
    return (float(candle["high"]) + float(candle["low"])) / 2


def breakout_above_n_day_high(candles: list[dict], n: int = 20) -> Optional[dict]:
    """Latest close > max(highs of prior `n` candles)."""
    if not candles or len(candles) < n + 1:
        return None
    prior = candles[-(n + 1):-1]
    latest = candles[-1]
    prior_max = max(float(c["high"]) for c in prior)
    latest_close = _close(latest)
    if latest_close <= prior_max:
        return None
    over_pct = (latest_close - prior_max) / prior_max
    confidence = min(1.0, 0.5 + over_pct * 5)
    return {
        "pattern": "breakout_above_n_day_high",
        "confidence": round(confidence, 3),
        "key_level": round(prior_max, 2),
    }


def bull_flag(candles: list[dict]) -> Optional[dict]:
    """Strong upward leg (pole, ≥+5%) followed by tight consolidation (flag).

    Splits the latest 20 candles 50/50: first half is the pole, second
    half is the flag. Pole must rise ≥5%; flag must consolidate within
    ≤5% range and not break above the pole's peak.
    """
    if len(candles) < 20:
        return None
    window = candles[-20:]
    pole, flag = window[:10], window[10:]
    pole_start = _close(pole[0])
    pole_end = _close(pole[-1])
    if pole_start <= 0:
        return None
    pole_gain_pct = (pole_end - pole_start) / pole_start
    if pole_gain_pct < 0.05:
        return None

    flag_high = max(float(c["high"]) for c in flag)
    flag_low = min(float(c["low"]) for c in flag)
    if flag_high <= 0:
        return None
    flag_range_pct = (flag_high - flag_low) / flag_high
    if flag_range_pct > 0.05:
        return None

    flag_end = _close(flag[-1])
    if flag_end > pole_end:
        return None

    confidence = min(1.0, 0.4 + pole_gain_pct * 2 + (0.05 - flag_range_pct) * 4)
    return {
        "pattern": "bull_flag",
        "confidence": round(confidence, 3),
        "key_level": round(flag_high, 2),
    }


def double_bottom(candles: list[dict], tolerance_pct: float = 0.02) -> Optional[dict]:
    """Two similar troughs separated by an intervening peak.

    Walks the candles to find the lowest low (low #1), then searches
    after a separating peak for a second low within `tolerance_pct` of
    low #1. The neckline (intervening peak) is the breakout level.
    """
    if len(candles) < 6:
        return None
    lows = [float(c["low"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    n = len(lows)

    low1_idx = min(range(n), key=lambda i: lows[i])
    low1 = lows[low1_idx]
    if low1 <= 0:
        return None

    if low1_idx >= n - 3:
        return None
    after = lows[low1_idx + 2:]
    candidate_idx_relative = min(range(len(after)), key=lambda i: after[i])
    low2_idx = low1_idx + 2 + candidate_idx_relative
    low2 = lows[low2_idx]
    if low2_idx - low1_idx < 3:
        return None

    if abs(low2 - low1) / low1 > tolerance_pct:
        return None

    between = highs[low1_idx + 1:low2_idx]
    if not between:
        return None
    neckline = max(between)
    rebound_pct = (neckline - low1) / low1
    if rebound_pct < 0.05:
        return None

    confidence = min(1.0, 0.4 + rebound_pct + (tolerance_pct - abs(low2 - low1) / low1) * 10)
    return {
        "pattern": "double_bottom",
        "confidence": round(confidence, 3),
        "key_level": round(neckline, 2),
    }


def detect_all(candles: list[dict]) -> Optional[dict]:
    """Run all detectors and return the highest-confidence hit, or None."""
    if not candles:
        return None
    hits = []
    for fn in (breakout_above_n_day_high, bull_flag, double_bottom):
        result = fn(candles)
        if result is not None:
            hits.append(result)
    if not hits:
        return None
    hits.sort(key=lambda r: r["confidence"], reverse=True)
    return hits[0]
