"""Options flow scanner.

Uses yfinance options chain to detect unusual activity:
- Volume/OpenInterest ratio > 3x with volume > 100 contracts
- Computes put/call ratio from total volumes

Runs in a ThreadPoolExecutor since yfinance is blocking.
"""

import logging
import time
from typing import Optional

from consensus_engine.models import OptionsResult, FlowHit

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


# ---------------------------------------------------------------------------
# #18: near-real-time unusual options FLOW (autonomous watcher + !all feed)
# ---------------------------------------------------------------------------

def _ts_to_epoch(ts) -> float:
    """Convert a yfinance lastTradeDate (pandas Timestamp) to epoch seconds."""
    try:
        return float(ts.timestamp())
    except Exception:
        return 0.0


def _scan_chain_for_flow(
    ticker, chain, expiry, spot, *,
    min_vol_oi, min_volume, min_premium, max_stale_sec, now,
) -> list:
    """Pull qualifying FlowHits out of one expiry's calls+puts DataFrames.

    A contract qualifies when it traded >= min_vol_oi x its open interest, at
    least min_volume contracts, and >= min_premium notional (lastPrice*vol*100).
    Contracts whose last trade is older than max_stale_sec are skipped so we
    never alert on stale / closed-market data.
    """
    hits = []
    for df, side in ((chain.calls, "CALL"), (chain.puts, "PUT")):
        if df is None or getattr(df, "empty", True):
            continue
        for _, row in df.iterrows():
            vol = float(row.get("volume", 0) or 0)
            oi = float(row.get("openInterest", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)
            if oi <= 0 or vol < min_volume:
                continue
            ratio = vol / oi
            premium = last_price * vol * 100.0
            if ratio < min_vol_oi or premium < min_premium:
                continue
            lt = _ts_to_epoch(row.get("lastTradeDate"))
            if max_stale_sec and lt and (now - lt) > max_stale_sec:
                continue  # stale / closed-market data — don't alert on it
            hits.append(FlowHit(
                ticker=ticker, side=side,
                strike=float(row.get("strike", 0) or 0), expiry=expiry,
                volume=int(vol), open_interest=int(oi),
                vol_oi_ratio=round(ratio, 2), premium_usd=round(premium, 2),
                last_trade_ts=lt, spot=spot,
                contract_symbol=str(row.get("contractSymbol", "")),
            ))
    return hits


async def _fetch_flow_chains(ticker: str, executor, nearest: int):
    """Fetch spot + the nearest `nearest` expirations' chains (blocking yf in executor)."""
    import asyncio

    def _f():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            exps = t.options
            if not exps:
                return 0.0, []
            spot = 0.0
            fi = getattr(t, "fast_info", None)
            if fi is not None:
                for k in ("lastPrice", "last_price", "regularMarketPrice"):
                    try:
                        v = fi.get(k) if hasattr(fi, "get") else getattr(fi, k, None)
                    except Exception:
                        v = None
                    if v:
                        spot = float(v)
                        break
            chains = []
            for e in exps[:nearest]:
                try:
                    chains.append((e, t.option_chain(e)))
                except Exception:
                    pass
            return spot, chains
        except Exception as ex:
            log.debug("flow fetch error for %s: %s", ticker, ex)
            return 0.0, []

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, _f)
    except Exception as ex:
        log.debug("flow executor error for %s: %s", ticker, ex)
        return 0.0, []


async def scan_options_flow(
    tickers: list[str], executor=None, *,
    min_vol_oi: float = 5.0, min_volume: int = 500,
    min_premium: float = 250_000.0, max_staleness_min: int = 60,
    nearest_expirations: int = 2,
) -> list:
    """Scan tickers for unusual options FLOW (free yfinance ~15-min data).

    Returns every qualifying FlowHit across all tickers, sorted by premium
    (largest first). The caller dedups to one alert per ticker. This revives
    the dormant scan_unusual_options_market with premium sizing, multi-expiry
    coverage, staleness filtering, and a structured return type.
    """
    now = time.time()
    max_stale_sec = max_staleness_min * 60 if max_staleness_min else 0
    out: list = []
    for tk in tickers:
        try:
            spot, chains = await _fetch_flow_chains(tk, executor, nearest_expirations)
            for expiry, chain in chains:
                out.extend(_scan_chain_for_flow(
                    tk, chain, expiry, spot or 0.0,
                    min_vol_oi=min_vol_oi, min_volume=min_volume,
                    min_premium=min_premium, max_stale_sec=max_stale_sec, now=now,
                ))
        except Exception as ex:
            log.debug("scan_options_flow error for %s: %s", tk, ex)
    out.sort(key=lambda h: h.premium_usd, reverse=True)
    if out:
        log.info("options_flow: %d qualifying contract(s) across %d ticker(s)",
                 len(out), len({h.ticker for h in out}))
    return out


def format_flow_alert(hit) -> str:
    """Render a FlowHit as an instant-trigger Discord alert (Alert Philosophy)."""
    direction = "🟢 BULLISH" if hit.side == "CALL" else "🔴 BEARISH"
    prem_m = hit.premium_usd / 1_000_000.0
    spot_txt = f" | spot ${hit.spot:,.2f}" if hit.spot else ""
    return (
        f"⚡ **UNUSUAL OPTIONS FLOW** — `${hit.ticker}` {direction}\n"
        f"**{hit.side}** {hit.expiry} ${hit.strike:g} strike{spot_txt}\n"
        f"Volume **{hit.volume:,}** vs OI {hit.open_interest:,} "
        f"(**{hit.vol_oi_ratio:.1f}x** — fresh positioning) | "
        f"premium **${prem_m:.2f}M**\n"
        f"_Free ~15-min-delayed chain data; unusual-flow instant trigger._"
    )


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
