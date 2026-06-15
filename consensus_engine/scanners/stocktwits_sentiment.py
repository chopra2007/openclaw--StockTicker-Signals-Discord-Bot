"""Stocktwits retail-sentiment reader for `!all` (#6 Lever 2).

Reads the public (no-key) Stocktwits API for a ticker's crowd bull%/5-day trend and
watcher count. Two independent endpoints, each with its OWN timeout — render whatever
succeeds. A 15-min positive cache + a short negative cache + per-ticker in-flight
coalescing keep a burst of concurrent `!all <T>` calls from each hammering Stocktwits
(and keep a down API from being re-hit every request). Never raises; returns None on
any failure so `!all` just omits the field.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

_SENTIMENT_URL = "https://api.stocktwits.com/api/2/symbols/{t}/sentiment.json"
_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{t}.json"

_TIMEOUT_S = 4.0          # per endpoint
_POS_TTL_S = 900.0        # 15 min — sentiment moves slowly
_NEG_TTL_S = 90.0         # don't re-hammer a down/rate-limiting API

_cache: dict[str, tuple[float, Optional[dict]]] = {}   # ticker -> (expires_at, value|None)
_inflight: dict[str, "asyncio.Future"] = {}            # ticker -> in-flight fetch


async def _session() -> aiohttp.ClientSession:
    from consensus_engine.utils.http import get_session
    return await get_session()


async def _fetch_sentiment(ticker: str) -> tuple[Optional[float], Optional[float]]:
    """(latest bull %, 5-day delta in pts) or (None, None)."""
    try:
        sess = await _session()
        async with sess.get(_SENTIMENT_URL.format(t=ticker),
                            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_S)) as r:
            if r.status != 200:
                return None, None
            data = (await r.json()).get("data") or []
        if not data:
            return None, None
        latest = data[0].get("bullish")
        if latest is None:
            return None, None
        latest = float(latest)
        delta = None
        if len(data) > 1:
            prior_idx = min(5, len(data) - 1)   # ~5 trading-days back, newest-first series
            prior = data[prior_idx].get("bullish")
            if prior is not None:
                delta = latest - float(prior)
        return latest, delta
    except Exception as e:  # noqa: BLE001
        log.debug("stocktwits sentiment fetch failed for %s: %s", ticker, e)
        return None, None


async def _fetch_watchers(ticker: str) -> Optional[int]:
    """Watchlist count, or None. Independent of the sentiment call."""
    try:
        sess = await _session()
        async with sess.get(_STREAM_URL.format(t=ticker),
                            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_S)) as r:
            if r.status != 200:
                return None
            sym = (await r.json()).get("symbol") or {}
        w = sym.get("watchlist_count")
        return int(w) if w is not None else None
    except Exception as e:  # noqa: BLE001
        log.debug("stocktwits watchers fetch failed for %s: %s", ticker, e)
        return None


async def _fetch_raw(ticker: str) -> Optional[dict]:
    """Both endpoints concurrently; build a dict from whatever succeeded, else None."""
    (bull, delta), watchers = await asyncio.gather(
        _fetch_sentiment(ticker), _fetch_watchers(ticker))
    if bull is None and watchers is None:
        return None
    return {"bull_pct": bull, "delta_5d": delta, "watchers": watchers}


async def _fetch_and_cache(ticker: str) -> Optional[dict]:
    val = await _fetch_raw(ticker)
    ttl = _POS_TTL_S if val is not None else _NEG_TTL_S
    _cache[ticker] = (time.time() + ttl, val)
    return val


async def fetch_stocktwits_sentiment(ticker: str) -> Optional[dict]:
    """Return {"bull_pct", "delta_5d", "watchers"} (any may be None) or None.

    Cached 15 min (90 s on failure); concurrent calls for the same ticker share one
    in-flight request."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None
    now = time.time()
    hit = _cache.get(ticker)
    if hit and hit[0] > now:
        return hit[1]
    # coalesce: first caller does the fetch, the rest await the same future.
    existing = _inflight.get(ticker)
    if existing is not None:
        return await existing
    fut = asyncio.ensure_future(_fetch_and_cache(ticker))
    _inflight[ticker] = fut
    try:
        return await fut
    finally:
        _inflight.pop(ticker, None)
