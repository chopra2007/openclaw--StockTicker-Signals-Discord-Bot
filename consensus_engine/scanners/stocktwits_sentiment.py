"""Stocktwits retail-sentiment reader for `!all` (#6 Lever 2).

Reads the public (no-key) Stocktwits API for a ticker's crowd bull%/5-day trend and
watcher count. Stocktwits sits behind Cloudflare, which blocks aiohttp's TLS fingerprint
(403 "Just a moment...") regardless of User-Agent — but the `requests`/urllib stack
passes. So the two endpoints are fetched with `requests` in a thread executor (same
blocking-in-executor pattern snapshot.py uses for yfinance), each with its OWN timeout —
render whatever succeeds. A 15-min positive cache + a short negative cache + per-ticker
in-flight coalescing keep a burst of concurrent `!all <T>` calls from each hammering
Stocktwits (and a down API from being re-hit every request). Never raises; returns None
on any failure so `!all` just omits the field.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

log = logging.getLogger(__name__)

_SENTIMENT_URL = "https://api.stocktwits.com/api/2/symbols/{t}/sentiment.json"
_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{t}.json"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_TIMEOUT_S = 4.0          # per endpoint
_POS_TTL_S = 900.0        # 15 min — sentiment moves slowly
_NEG_TTL_S = 90.0         # don't re-hammer a down/rate-limiting API

_session = requests.Session()
_session.headers.update({"User-Agent": _UA, "Accept": "application/json"})
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stocktwits")

_cache: dict[str, tuple[float, Optional[dict]]] = {}   # ticker -> (expires_at, value|None)
_inflight: dict[str, "asyncio.Future"] = {}            # ticker -> in-flight fetch


def _fetch_sentiment_sync(ticker: str) -> tuple[Optional[float], Optional[float]]:
    """(latest bull %, 5-day delta in pts) or (None, None). Blocking (requests)."""
    try:
        r = _session.get(_SENTIMENT_URL.format(t=ticker), timeout=_TIMEOUT_S)
        if r.status_code != 200:
            return None, None
        data = (r.json().get("data") or [])
        if not data or data[0].get("bullish") is None:
            return None, None
        latest = float(data[0]["bullish"])
        delta = None
        if len(data) > 1:
            prior = data[min(5, len(data) - 1)].get("bullish")  # ~5 trading-days back (newest-first)
            if prior is not None:
                delta = latest - float(prior)
        return latest, delta
    except Exception as e:  # noqa: BLE001
        log.debug("stocktwits sentiment fetch failed for %s: %s", ticker, e)
        return None, None


def _fetch_watchers_sync(ticker: str) -> Optional[int]:
    """Watchlist count, or None. Independent of the sentiment call. Blocking (requests)."""
    try:
        r = _session.get(_STREAM_URL.format(t=ticker), timeout=_TIMEOUT_S)
        if r.status_code != 200:
            return None
        w = ((r.json().get("symbol") or {}).get("watchlist_count"))
        return int(w) if w is not None else None
    except Exception as e:  # noqa: BLE001
        log.debug("stocktwits watchers fetch failed for %s: %s", ticker, e)
        return None


def _blocking_fetch(ticker: str) -> Optional[dict]:
    """Both endpoints (each its own timeout); dict from whatever succeeded, else None."""
    bull, delta = _fetch_sentiment_sync(ticker)
    watchers = _fetch_watchers_sync(ticker)
    if bull is None and watchers is None:
        return None
    return {"bull_pct": bull, "delta_5d": delta, "watchers": watchers}


async def _fetch_raw(ticker: str) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _blocking_fetch, ticker)


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
    existing = _inflight.get(ticker)        # coalesce concurrent callers
    if existing is not None:
        return await existing
    fut = asyncio.ensure_future(_fetch_and_cache(ticker))
    _inflight[ticker] = fut
    try:
        return await fut
    finally:
        _inflight.pop(ticker, None)
