"""Pre-market gap scanner.

Scans watchlist tickers for >3% gaps using Finnhub /quote.
Runs 8:00-9:25am ET, posts digest to Discord.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.premarket")


@dataclass
class GapResult:
    ticker: str
    current_price: float
    prev_close: float
    gap_pct: float


def _detect_gaps(quotes: dict[str, dict], threshold_pct: float = 3.0) -> list[GapResult]:
    """Detect gaps from Finnhub quote data. Returns sorted by abs(gap_pct) descending."""
    results = []
    for ticker, q in quotes.items():
        current = q.get("c", 0)
        prev_close = q.get("pc", 0)
        if not prev_close or prev_close == 0:
            continue
        gap_pct = ((current - prev_close) / prev_close) * 100
        if abs(gap_pct) >= threshold_pct:
            results.append(GapResult(
                ticker=ticker,
                current_price=current,
                prev_close=prev_close,
                gap_pct=round(gap_pct, 2),
            ))
    results.sort(key=lambda r: abs(r.gap_pct), reverse=True)
    return results


async def _fetch_quote(session: aiohttp.ClientSession, ticker: str, api_key: str) -> tuple[str, dict]:
    """Fetch a single Finnhub quote. Returns (ticker, quote_data)."""
    if not await rate_limiter.acquire("finnhub"):
        return ticker, {}
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={api_key}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return ticker, {}
            data = await resp.json()
            rate_limiter.report_success("finnhub")
            return ticker, data
    except Exception as e:
        log.debug("Finnhub quote error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub")
        return ticker, {}


async def scan_premarket_gaps() -> list[GapResult]:
    """Scan watchlist for pre-market gaps using Finnhub /quote."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        log.warning("Pre-market scanner: no Finnhub API key")
        return []

    watchlist = cfg.get("premarket.watchlist", [])
    if not watchlist:
        log.debug("Pre-market scanner: empty watchlist")
        return []

    threshold = cfg.get("premarket.gap_threshold_pct", 3.0)

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

    gaps = _detect_gaps(quotes, threshold)
    if gaps:
        log.info("Pre-market: %d gaps found (>%.1f%%)", len(gaps), threshold)
    return gaps


def format_gap_digest(gaps: list[GapResult]) -> str:
    """Format gap results as a Discord message."""
    if not gaps:
        return "No significant pre-market gaps detected."
    lines = ["**Pre-Market Gap Scanner**"]
    for g in gaps[:15]:
        direction = "UP" if g.gap_pct > 0 else "DOWN"
        sign = "+" if g.gap_pct > 0 else ""
        lines.append(
            f"`${g.ticker}` {direction} **{sign}{g.gap_pct:.1f}%** "
            f"(${g.prev_close:.2f} -> ${g.current_price:.2f})"
        )
    return "\n".join(lines)
