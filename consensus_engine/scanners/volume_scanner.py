"""Volume breakout scanner.

Detects stocks with RVOL >5x during market hours.
Volume precedes price — this is the earliest possible signal.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.volume")


@dataclass
class BreakoutResult:
    ticker: str
    current_price: float
    prev_close: float
    price_change_pct: float
    volume: int
    avg_volume: int
    rvol: float


def _detect_breakouts(
    quote_data: dict[str, dict],
    avg_volumes: dict[str, int],
    rvol_threshold: float = 5.0,
    min_price_change_pct: float = 1.0,
) -> list[BreakoutResult]:
    """Detect volume breakouts from quote + avg volume data."""
    results = []
    for ticker, q in quote_data.items():
        current = q.get("c", 0)
        prev_close = q.get("pc", 0)
        volume = int(q.get("v", 0))
        avg_vol = avg_volumes.get(ticker, 0)

        if not prev_close or prev_close == 0 or avg_vol == 0:
            continue

        price_change_pct = ((current - prev_close) / prev_close) * 100
        rvol = volume / avg_vol

        if rvol >= rvol_threshold and abs(price_change_pct) >= min_price_change_pct:
            results.append(BreakoutResult(
                ticker=ticker,
                current_price=current,
                prev_close=prev_close,
                price_change_pct=round(price_change_pct, 2),
                volume=volume,
                avg_volume=avg_vol,
                rvol=round(rvol, 1),
            ))

    results.sort(key=lambda r: r.rvol, reverse=True)
    return results


async def _fetch_avg_volume(ticker: str, executor) -> tuple[str, int]:
    """Fetch 20-day avg volume via yfinance (blocking)."""
    def _fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="1mo")
            if hist.empty:
                return 0
            return int(hist["Volume"].tail(20).mean())
        except Exception:
            return 0

    loop = asyncio.get_running_loop()
    try:
        avg = await loop.run_in_executor(executor, _fetch)
        return ticker, avg
    except Exception:
        return ticker, 0


async def scan_volume_breakouts(executor=None) -> list[BreakoutResult]:
    """Scan watchlist for volume breakouts using Finnhub quotes + yfinance avg volumes."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return []

    watchlist = cfg.get("volume_scanner.watchlist", cfg.get("premarket.watchlist", []))
    if not watchlist:
        return []

    rvol_threshold = cfg.get("volume_scanner.rvol_threshold", 5.0)
    min_pct = cfg.get("volume_scanner.min_price_change_pct", 1.0)

    from consensus_engine.scanners.premarket import _fetch_quote
    quotes = {}
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(watchlist), 30):
            batch = watchlist[i:i+30]
            results = await asyncio.gather(
                *[_fetch_quote(session, t, api_key) for t in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, tuple) and r[1]:
                    quotes[r[0]] = r[1]

    avg_volumes = {}
    vol_tasks = [_fetch_avg_volume(t, executor) for t in quotes]
    vol_results = await asyncio.gather(*vol_tasks, return_exceptions=True)
    for r in vol_results:
        if isinstance(r, tuple) and r[1] > 0:
            avg_volumes[r[0]] = r[1]

    breakouts = _detect_breakouts(quotes, avg_volumes, rvol_threshold, min_pct)
    if breakouts:
        log.info("Volume scanner: %d breakouts found", len(breakouts))
    return breakouts


def format_volume_digest(breakouts: list[BreakoutResult]) -> str:
    """Format breakout results as a Discord message."""
    if not breakouts:
        return "No volume breakouts detected."
    lines = ["**Volume Breakout Scanner**"]
    for b in breakouts[:10]:
        sign = "+" if b.price_change_pct > 0 else ""
        lines.append(
            f"`${b.ticker}` **{b.rvol:.1f}x RVOL** | "
            f"{sign}{b.price_change_pct:.1f}% | "
            f"Vol: {b.volume:,} (avg {b.avg_volume:,})"
        )
    return "\n".join(lines)
