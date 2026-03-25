"""Stage 4 — Technical Verification.

Uses Finnhub for real-time quotes + yfinance for historical OHLCV data.
Runs all 6 technical filters. A ticker must pass ALL to proceed.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import aiohttp
import yfinance as yf

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import TechnicalResult, TechnicalFilter
from consensus_engine.analysis import indicators
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.analysis.technical")

_executor = ThreadPoolExecutor(max_workers=2)


def shutdown_executor():
    """Shut down the thread pool executor cleanly."""
    _executor.shutdown(wait=False)


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


def _fetch_yfinance_history(ticker: str, period: str = "1mo") -> Optional[dict]:
    """Fetch historical OHLCV from yfinance (runs in thread pool — blocking call)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty or len(hist) < 5:
            return None
        return {
            "o": hist["Open"].tolist(),
            "h": hist["High"].tolist(),
            "l": hist["Low"].tolist(),
            "c": hist["Close"].tolist(),
            "v": [int(v) for v in hist["Volume"].tolist()],
            "t": [int(ts.timestamp()) for ts in hist.index],
        }
    except Exception as e:
        log.warning("yfinance error for %s: %s", ticker, e)
        return None


async def _fetch_history_async(ticker: str) -> Optional[dict]:
    """Async wrapper for yfinance (runs in executor to avoid blocking)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _fetch_yfinance_history, ticker)


def _run_filters(quote: dict, candles: dict) -> list[TechnicalFilter]:
    """Run all 6 technical filters.

    quote: Finnhub quote {c, o, h, l, pc, dp, t}
    candles: yfinance history {o[], h[], l[], c[], v[], t[]}
    """
    filter_cfg = cfg.get("technical.filters", {})
    results = []

    current_price = quote.get("c", 0)
    prev_close = quote.get("pc", 0)
    closes = candles.get("c", [])
    highs = candles.get("h", [])
    lows = candles.get("l", [])
    volumes = candles.get("v", [])

    # 1. Relative Volume (RVOL)
    rvol_threshold = filter_cfg.get("rvol_threshold", 2.0)
    rvol_lookback = filter_cfg.get("rvol_lookback_days", 20)
    if volumes and len(volumes) >= rvol_lookback:
        avg_vol = sum(volumes[-rvol_lookback:]) / rvol_lookback
        current_vol = volumes[-1] if volumes else 0
        rvol_val = indicators.relative_volume(current_vol, avg_vol)
        results.append(TechnicalFilter(
            name="RVOL",
            value=round(rvol_val, 2),
            threshold=f"> {rvol_threshold}x",
            passed=rvol_val >= rvol_threshold,
        ))
    else:
        results.append(TechnicalFilter(
            name="RVOL", value=0, threshold=f"> {rvol_threshold}x", passed=False,
        ))

    # 2. Price above VWAP
    if filter_cfg.get("vwap_enabled", True) and closes and volumes:
        vwap_val = indicators.vwap(closes[-20:], volumes[-20:])
        if vwap_val and current_price:
            results.append(TechnicalFilter(
                name="VWAP",
                value=round(current_price, 2),
                threshold=f"> {round(vwap_val, 2)} (VWAP)",
                passed=current_price > vwap_val,
            ))
        else:
            results.append(TechnicalFilter(
                name="VWAP", value=0, threshold="above VWAP", passed=False,
            ))

    # 3. RSI
    rsi_period = filter_cfg.get("rsi_period", 14)
    rsi_lower = filter_cfg.get("rsi_lower", 40)
    rsi_upper = filter_cfg.get("rsi_upper", 75)
    if closes and len(closes) >= rsi_period + 1:
        rsi_val = indicators.rsi(closes, rsi_period)
        if rsi_val is not None:
            results.append(TechnicalFilter(
                name="RSI",
                value=round(rsi_val, 1),
                threshold=f"{rsi_lower}-{rsi_upper}",
                passed=rsi_lower <= rsi_val <= rsi_upper,
            ))
        else:
            results.append(TechnicalFilter(
                name="RSI", value=0, threshold=f"{rsi_lower}-{rsi_upper}", passed=False,
            ))
    else:
        results.append(TechnicalFilter(
            name="RSI", value=0, threshold=f"{rsi_lower}-{rsi_upper}", passed=False,
        ))

    # 4. EMA Crossover
    ema_fast = filter_cfg.get("ema_fast", 9)
    ema_slow = filter_cfg.get("ema_slow", 21)
    if closes and len(closes) >= ema_slow:
        crossover = indicators.ema_crossover(closes, ema_fast, ema_slow)
        fast_vals = indicators.ema(closes, ema_fast)
        slow_vals = indicators.ema(closes, ema_slow)
        diff = round(fast_vals[-1] - slow_vals[-1], 2) if fast_vals and slow_vals else 0
        results.append(TechnicalFilter(
            name="EMA Cross",
            value=diff,
            threshold=f"{ema_fast}EMA > {ema_slow}EMA",
            passed=crossover is True,
        ))
    else:
        results.append(TechnicalFilter(
            name="EMA Cross", value=0, threshold=f"{ema_fast}EMA > {ema_slow}EMA", passed=False,
        ))

    # 5. Price Change %
    min_pct = filter_cfg.get("price_change_min_pct", 2.0)
    if current_price and prev_close:
        pct = indicators.price_change_pct(current_price, prev_close)
        results.append(TechnicalFilter(
            name="Price Change",
            value=round(pct, 2),
            threshold=f"> +{min_pct}%",
            passed=pct >= min_pct,
        ))
    else:
        results.append(TechnicalFilter(
            name="Price Change", value=0, threshold=f"> +{min_pct}%", passed=False,
        ))

    # 6. ATR Breakout
    atr_period = filter_cfg.get("atr_period", 14)
    atr_mult = filter_cfg.get("atr_multiplier", 1.5)
    if highs and lows and closes and len(highs) >= atr_period + 1:
        atr_val = indicators.atr(highs, lows, closes, atr_period)
        if atr_val and prev_close and current_price:
            price_move = abs(current_price - prev_close)
            breakout_ratio = round(price_move / atr_val, 2) if atr_val > 0 else 0
            results.append(TechnicalFilter(
                name="ATR Breakout",
                value=breakout_ratio,
                threshold=f"> {atr_mult}x ATR",
                passed=price_move >= atr_val * atr_mult,
            ))
        else:
            results.append(TechnicalFilter(
                name="ATR Breakout", value=0, threshold=f"> {atr_mult}x ATR", passed=False,
            ))
    else:
        results.append(TechnicalFilter(
            name="ATR Breakout", value=0, threshold=f"> {atr_mult}x ATR", passed=False,
        ))

    return results


async def verify_technical(ticker: str) -> Optional[TechnicalResult]:
    """Run full technical verification on a ticker.

    Fetches real-time quote from Finnhub + historical OHLCV from yfinance.
    Evaluates all 6 filters.
    """
    log.info("Running technical verification for %s...", ticker)
    start = time.time()

    # Fetch quote and history concurrently
    async with aiohttp.ClientSession() as session:
        quote_coro = _fetch_finnhub_quote(ticker, session)
        history_coro = _fetch_history_async(ticker)

        quote, candles = await asyncio.gather(quote_coro, history_coro)

    if not quote:
        log.warning("Technical: no quote data for %s", ticker)
        return None

    if not candles:
        log.warning("Technical: no historical data for %s", ticker)
        return None

    filters = _run_filters(quote, candles)
    current_price = quote.get("c", 0)
    prev_close = quote.get("pc", 0)
    volumes = candles.get("v", [])

    result = TechnicalResult(
        ticker=ticker,
        filters=filters,
        price=current_price,
        volume=volumes[-1] if volumes else 0,
        price_change_pct=indicators.price_change_pct(current_price, prev_close) if prev_close else 0,
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
