"""Options flow scanner.

Uses yfinance options chain to detect unusual activity:
- Volume/OpenInterest ratio > 3x with volume > 100 contracts
- Computes put/call ratio from total volumes

Runs in a ThreadPoolExecutor since yfinance is blocking.
"""

import logging
from typing import Optional

from consensus_engine.models import OptionsResult

log = logging.getLogger("consensus_engine.scanner.options")

_UNUSUAL_RATIO_THRESHOLD = 3.0
_MIN_VOLUME = 100
_SWEEP_RATIO_THRESHOLD = 5.0


def _is_sweep(vol: float, oi: float, min_ratio: float = 5.0, min_notional: float = 0) -> bool:
    """Check if volume/OI ratio qualifies as a sweep."""
    if oi == 0:
        return False
    return (vol / oi) >= min_ratio


def _detect_unusual_activity(chain) -> OptionsResult:
    """Detect unusual activity from a yfinance option_chain result.

    Args:
        chain: yfinance option_chain namedtuple with .calls and .puts DataFrames

    Returns:
        OptionsResult with detected unusual activity. ticker field is empty — caller fills it.
    """
    calls = chain.calls
    puts = chain.puts

    unusual_calls = False
    unusual_puts = False
    max_call_ratio = 0.0
    max_put_ratio = 0.0
    top_contract = ""
    total_call_vol = 0.0
    total_put_vol = 0.0

    if calls is not None and not calls.empty:
        for _, row in calls.iterrows():
            vol = float(row.get("volume", 0) or 0)
            oi = float(row.get("openInterest", 0) or 0)
            total_call_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_call_ratio:
                max_call_ratio = ratio
                top_contract = str(row.get("contractSymbol", ""))
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_calls = True

    if puts is not None and not puts.empty:
        for _, row in puts.iterrows():
            vol = float(row.get("volume", 0) or 0)
            oi = float(row.get("openInterest", 0) or 0)
            total_put_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_put_ratio:
                max_put_ratio = ratio
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_puts = True

    put_call_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else 0.0

    return OptionsResult(
        ticker="",  # filled in by caller
        unusual_calls=unusual_calls,
        unusual_puts=unusual_puts,
        max_call_ratio=round(max_call_ratio, 2),
        max_put_ratio=round(max_put_ratio, 2),
        put_call_ratio=round(put_call_ratio, 2),
        top_contract=top_contract,
    )


async def check_unusual_options(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity on a ticker.

    Fetches nearest-expiry options chain via yfinance (blocking, runs in executor).
    Returns None if no data or on error (including executor errors).
    """
    import asyncio

    def _fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            expirations = t.options
            if not expirations:
                return None
            chain = t.option_chain(expirations[0])
            return chain
        except Exception as e:
            log.debug("yfinance options fetch error for %s: %s", ticker, e)
            return None

    loop = asyncio.get_running_loop()
    try:
        chain = await loop.run_in_executor(executor, _fetch)
    except Exception as e:
        log.debug("run_in_executor error for %s: %s", ticker, e)
        return None
    if chain is None:
        return None

    result = _detect_unusual_activity(chain)
    result.ticker = ticker

    if result.has_unusual_activity:
        log.info(
            "Unusual options for $%s: calls=%s (max_ratio=%.1f) puts=%s (max_ratio=%.1f) p/c=%.2f",
            ticker, result.unusual_calls, result.max_call_ratio,
            result.unusual_puts, result.max_put_ratio, result.put_call_ratio,
        )
    else:
        log.debug("No unusual options for $%s (max_call_ratio=%.1f)", ticker, result.max_call_ratio)

    return result


async def scan_unusual_options_market(watchlist: list[str], executor=None) -> list[dict]:
    """Scan a watchlist for unusual options activity across all tickers.

    Returns list of dicts: {ticker, direction, max_ratio, top_contract, put_call_ratio}.
    """
    results = []
    for ticker in watchlist:
        try:
            result = await check_unusual_options(ticker, executor)
            if result and result.has_unusual_activity:
                direction = "CALL" if result.unusual_calls else "PUT"
                results.append({
                    "ticker": ticker,
                    "direction": direction,
                    "max_ratio": max(result.max_call_ratio, result.max_put_ratio),
                    "top_contract": result.top_contract,
                    "put_call_ratio": result.put_call_ratio,
                })
        except Exception as e:
            log.debug("Options sweep scan error for %s: %s", ticker, e)
    results.sort(key=lambda r: r["max_ratio"], reverse=True)
    return results


def format_options_sweep_digest(sweeps: list[dict]) -> str:
    """Format sweep results as Discord message."""
    if not sweeps:
        return "No unusual options sweeps detected."
    lines = ["**Options Sweep Scanner**"]
    for s in sweeps[:10]:
        lines.append(
            f"`${s['ticker']}` **{s['direction']}** sweep -- "
            f"{s['max_ratio']:.1f}x vol/OI | P/C: {s['put_call_ratio']:.2f}"
        )
    return "\n".join(lines)
