"""Earnings-move history for the !all command (#6 lever).

Average ABSOLUTE % price reaction over the last N reported earnings prints —
a one-glance read on how violently this name moves on earnings (e.g. NVDA ±3.7%
vs AMD ±8.5%). All from TWO free yfinance calls (get_earnings_dates + history;
pre-flight GREEN on NVDA/AMD/TSLA 2026-05-31).

Design (regression-safe + latency-bounded — mirrors snapshot.py):
  * Own SMALL bounded ThreadPoolExecutor so the two blocking calls can't starve
    the shared default pool the rest of !all uses.
  * asyncio.wait_for bounds the fetch; an empty/throttled result returns None ->
    the embed field is omitted.
  * Every value is guarded; reaction-day selection uses the report TIME (AMC ->
    next trading day, BMO -> report day), verified in preflight_earnmove_v3.py.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger(__name__)

# Dedicated bounded pool — keeps the blocking yfinance calls off the shared executor.
_EARNINGS_MOVE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="earnmove")

_FETCH_TIMEOUT_S = 10.0


def _compute_earnings_move(ticker: str, n: int) -> Optional[dict]:
    """Blocking yfinance fetch + reaction math. Returns dict or None on any error/empty.

    Reaction move = |close[reaction_day] / close[prev_trading_day] - 1|.
    AMC (report hour >= 16, or 00:00 default) -> reaction is the NEXT trading day;
    BMO / intraday (< 16:00) -> reaction is the report date's trading day.
    """
    try:
        import pandas as pd
        import yfinance as yf

        t = yf.Ticker(ticker)
        ed = t.get_earnings_dates(limit=24)
        # #57: stays on yfinance — coupled to yfinance's get_earnings_dates() (no
        # Schwab equivalent) and uses dividend-ADJUSTED 2y closes for earnings-
        # reaction stats; Schwab /pricehistory is split-only (RISK-5). Historical
        # read, no real-time benefit.
        hist = t.history(period="2y")
        if ed is None or ed.empty or hist is None or hist.empty:
            return None

        closes = hist["Close"].copy()
        cidx = closes.index.tz_localize(None).normalize()
        closes.index = cidx

        now = pd.Timestamp.now()
        rows = [(ts, ts.tz_localize(None)) for ts in ed.index if ts.tz_localize(None) < now]
        rows = sorted(rows, key=lambda r: r[1], reverse=True)[:n]

        moves = []
        for _ts_aware, ts in rows:
            amc = ts.hour >= 16 or ts.hour == 0
            d = ts.normalize()
            pos = cidx.searchsorted(d)  # first trading day >= report date
            react = pos + 1 if amc else pos
            if react <= 0 or react >= len(cidx):
                continue
            cprev = closes.iloc[react - 1]
            creact = closes.iloc[react]
            if not cprev:
                continue
            moves.append(float(abs(creact / cprev - 1) * 100))  # native float, not np.float64

        if not moves:
            return None
        # round(float(...)) keeps it a native float so np.float64 never reaches the
        # cache-key JSON or the LLM prompt (this repo has a float-precision history).
        return {"avg_pct": round(float(sum(moves) / len(moves)), 1), "n": len(moves)}
    except Exception as e:  # noqa: BLE001
        log.warning("earnings_move: fetch/compute failed for %s: %s", ticker, e)
        return None


async def fetch_earnings_move(ticker: str, n: int = 8) -> Optional[dict]:
    """Return {"avg_pct": float, "n": int} or None when unavailable.

    avg_pct = mean of the absolute % earnings reactions over the last `n`
    reported prints. None on empty/throttled data -> the embed field is omitted.
    """
    from consensus_engine import config as cfg
    if not cfg.get("features.earnings_move.enabled", True):
        return None

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_EARNINGS_MOVE_EXECUTOR, _compute_earnings_move, ticker, n),
            timeout=_FETCH_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        log.warning("earnings_move: fetch timed out/failed for %s: %s", ticker, e)
        return None
