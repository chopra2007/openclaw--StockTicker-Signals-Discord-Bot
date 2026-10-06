"""Stage 4 — Technical Verification.

Uses Finnhub for real-time quotes + yfinance for historical OHLCV data.
Runs all 6 technical filters. A ticker must pass ALL to proceed.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.models import TechnicalResult, TechnicalFilter
from consensus_engine.analysis import indicators
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.analysis.technical")


async def _fetch_finnhub_quote(ticker: str, session: aiohttp.ClientSession) -> Optional[dict]:
    """Fetch real-time quote from Finnhub (free tier)."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        log.warning("Finnhub API key not configured")
        return None

    if not await rate_limiter.acquire("finnhub"):
        return None

    try:
        url = "https://finnhub.io/api/v1/quote"
        params = {"symbol": ticker, "token": api_key}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                rate_limiter.report_failure("finnhub")
                return None
            data = await resp.json()
            if data.get("c", 0) == 0:
                log.warning("Finnhub returned zero price for %s", ticker)
                return None
            rate_limiter.report_success("finnhub")
            return data
    except Exception as e:
        log.warning("Finnhub quote error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub")
        return None


async def _fetch_history_async(ticker: str) -> Optional[dict]:
    """Fetch historical OHLCV directly from Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "1mo"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        session = await get_session()
        async with session.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                log.warning("Yahoo Finance returned %d for %s", resp.status, ticker)
                return None
            data = await resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return None
            indicators_data = result[0].get("indicators", {}).get("quote", [{}])[0]
            timestamps = result[0].get("timestamp", [])
            candles = {
                "o": indicators_data.get("open", []),
                "h": indicators_data.get("high", []),
                "l": indicators_data.get("low", []),
                "c": indicators_data.get("close", []),
                "v": [int(v) for v in indicators_data.get("volume", []) if v is not None],
                "t": timestamps,
            }
            if len(candles["c"]) < 5:
                return None
            return candles
    except Exception as e:
        log.warning("Yahoo Finance history error for %s: %s", ticker, e)
        return None


def _run_filters(quote: dict, candles: dict, direction: str = "long") -> list[TechnicalFilter]:
    """Run all 6 technical filters with the configured thresholds."""
    from consensus_engine.analysis.technical_filters import run_filters
    return run_filters(quote, candles, direction, cfg.get("technical.filters", {}))


async def verify_technical(ticker: str, direction: str = "long") -> Optional[TechnicalResult]:
    """Run full technical verification on a ticker.

    Fetches real-time quote from Finnhub + historical OHLCV from yfinance.
    Evaluates all 6 filters. direction="long"|"short" flips filter logic.
    """
    log.info("Running technical verification for %s (direction=%s)...", ticker, direction)
    start = time.time()

    # Fetch quote and history concurrently
    session = await get_session()
    quote_coro = _fetch_finnhub_quote(ticker, session)
    history_coro = _fetch_history_async(ticker)

    quote, candles = await asyncio.gather(quote_coro, history_coro)

    if not quote:
        log.warning("Technical: no quote data for %s", ticker)
        return None

    if not candles:
        log.warning("Technical: no historical data for %s", ticker)
        return None

    filters = _run_filters(quote, candles, direction=direction)
    current_price = quote.get("c", 0)
    prev_close = quote.get("pc", 0)
    volumes = candles.get("v", [])

    # W4 B-M0: compute ATR(14) from the same candle window. Returns None
    # for tickers with <14 bars (post-IPO) or zero-range halted sessions.
    atr14_value: Optional[float] = None
    try:
        highs = candles.get("h", []) or []
        lows = candles.get("l", []) or []
        closes = candles.get("c", []) or []
        # indicators.atr returns None on insufficient data and never raises.
        atr14_value = indicators.atr(highs, lows, closes, period=14)
        if atr14_value is not None and atr14_value <= 0:
            atr14_value = None  # halted / zero-range guard
    except Exception:  # noqa: BLE001
        atr14_value = None

    result = TechnicalResult(
        ticker=ticker,
        filters=filters,
        price=current_price,
        volume=volumes[-1] if volumes else 0,
        price_change_pct=indicators.price_change_pct(current_price, prev_close) if prev_close else 0,
        atr14=atr14_value,
    )

    elapsed = time.time() - start
    await db.record_metric("technical_verify_seconds", elapsed)

    passed = result.passed_count
    total = result.total_count
    if result.all_passed:
        log.info("Technical PASSED for %s: %d/%d filters (%s)",
                 ticker, passed, total,
                 ", ".join(f"{f.name}={f.value}" for f in filters))
    else:
        failed = [f for f in filters if not f.passed]
        log.info("Technical FAILED for %s: %d/%d. Failed: %s",
                 ticker, passed, total,
                 ", ".join(f"{f.name}={f.value} (need {f.threshold})" for f in failed))

    return result
