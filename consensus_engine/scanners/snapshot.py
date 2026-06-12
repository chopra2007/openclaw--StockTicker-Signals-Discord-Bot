"""Ticker fundamentals/analyst snapshot for the !all command (#6 lever).

Surfaces the single most-ubiquitous thing competitor ticker pages show that
`!all` lacked: the Wall-Street analyst price target + rating, plus forward P/E
and short interest. All from ONE yfinance `.info` fetch (free; pre-flight
GREEN on NVDA/AMD/SOFI 2026-05-31).

Design (regression-safe + latency-bounded — mirrors peer_comparison.py):
  * Own SMALL bounded ThreadPoolExecutor so the single blocking `.info` call
    can't starve the shared default pool the rest of !all uses (Pass-3 critic
    M1). `.info` measured at 0.4-0.7s.
  * asyncio.wait_for bounds the fetch; an empty/throttled `.info` (yfinance
    returns {} indistinguishably from a delisted ticker) logs a warning so the
    throttle rate is observable, and returns None -> the embed field is omitted.
  * Every key is .get()-guarded and NaN-filtered; returns None when neither the
    analyst block nor the fundamentals block has any data, so the field never
    renders empty.
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger(__name__)

# Dedicated bounded pool — keeps the blocking .info call off the shared executor.
_SNAPSHOT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot")

_FETCH_TIMEOUT_S = 8.0

_RATING_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
}


def _num(val) -> Optional[float]:
    """Coerce to float, dropping None / NaN / non-numeric."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _fetch_info(ticker: str) -> dict:
    """Blocking yfinance fetch: ``.info`` plus the current-fiscal-year EPS estimate.

    Returns {} on any error. The current-FY consensus EPS is stashed under the
    synthetic key ``_eps_cfy`` so the caller can build a forward P/E from
    price ÷ current-FY EPS. yfinance's own ``forwardPE`` divides price by the
    NEXT full fiscal year's EPS estimate, which for a Jan-fiscal-year name like
    NVDA reads ~a year too far out (e.g. ~16 when the rolling figure is ~24).
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        try:
            est = t.earnings_estimate  # separate yfinance endpoint
            if est is not None and "0y" in est.index and "avg" in est.columns:
                eps_cfy = _num(est.loc["0y", "avg"])
                if eps_cfy is not None:
                    info["_eps_cfy"] = eps_cfy
        except Exception:  # noqa: BLE001 — sparse/missing estimate table is normal
            pass
        return info
    except Exception as e:  # noqa: BLE001
        log.warning("snapshot: .info fetch failed for %s: %s", ticker, e)
        return {}


async def fetch_ticker_snapshot(ticker: str) -> Optional[dict]:
    """Return an analyst+fundamentals snapshot dict, or None when unavailable.

    Keys (all optional): target_mean/high/low, n_analysts, rating, fwd_pe,
    short_pct (fraction, e.g. 0.0092), short_days (days-to-cover).
    """
    from consensus_engine import config as cfg
    if not cfg.get("features.snapshot.enabled", True):
        return None

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(_SNAPSHOT_EXECUTOR, _fetch_info, ticker),
            timeout=_FETCH_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        log.warning("snapshot: fetch timed out/failed for %s: %s", ticker, e)
        return None

    if not info:
        # Empty .info == throttled or delisted; indistinguishable. Logged so the
        # throttle rate is visible; field omits cleanly.
        log.warning("snapshot: empty .info for %s (throttled or no data)", ticker)
        return None

    rating_key = (info.get("recommendationKey") or "").strip().lower()
    rating = _RATING_LABELS.get(rating_key) if rating_key and rating_key != "none" else None

    snap = {
        "target_mean": _num(info.get("targetMeanPrice")),
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
        "n_analysts": int(info["numberOfAnalystOpinions"]) if _num(info.get("numberOfAnalystOpinions")) else None,
        "rating": rating,
        "fwd_pe": None,  # set below from current-FY EPS once price is known
        "short_pct": _num(info.get("shortPercentOfFloat")),
        "short_days": _num(info.get("shortRatio")),
    }

    # #6 lever — 52-week high/low distance, from the SAME .info call.
    # wk52_high_pct negative = below the high; wk52_low_pct positive = above the low.
    wk52_high = _num(info.get("fiftyTwoWeekHigh"))
    wk52_low = _num(info.get("fiftyTwoWeekLow"))
    price = (_num(info.get("currentPrice"))
             or _num(info.get("regularMarketPrice"))
             or _num(info.get("previousClose")))
    snap["wk52_high_pct"] = (price / wk52_high - 1) * 100 if price and wk52_high and wk52_high > 0 else None
    snap["wk52_low_pct"] = (price / wk52_low - 1) * 100 if price and wk52_low and wk52_low > 0 else None
    # full-audit smart-levels: expose RAW 52wk prices (not just % distances) for the
    # technical-levels engine; present whenever snap is returned (before the early None below).
    snap["wk52_high"] = wk52_high
    snap["wk52_low"] = wk52_low

    # Forward P/E on a rolling current-fiscal-year basis: price ÷ current-FY
    # consensus EPS (yfinance earnings_estimate '0y' avg). Honest "Fwd P/E"
    # that tracks the next ~12 months of earnings rather than the year-out
    # figure yfinance's forwardPE field reports. Omits when EPS is missing or
    # ≤ 0 (unprofitable → P/E meaningless).
    eps_cfy = _num(info.get("_eps_cfy"))
    snap["fwd_pe"] = (price / eps_cfy) if (price and eps_cfy and eps_cfy > 0) else None

    has_analyst = snap["target_mean"] is not None or snap["rating"] is not None
    has_fundamentals = snap["fwd_pe"] is not None or snap["short_pct"] is not None
    if not has_analyst and not has_fundamentals:
        return None
    return snap
