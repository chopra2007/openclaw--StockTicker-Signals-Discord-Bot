"""r8 — CBOE ^SKEW tail-risk reader (STANDALONE MODULE).

The CBOE SKEW Index measures the market's implied demand for out-of-the-money
S&P 500 put protection — i.e. how much traders are paying to hedge a tail
("black swan") drop. A HIGH reading means elevated tail-demand (nervous
hedging); a LOW reading means complacency.

This module ONLY computes the current SKEW value and a plain-language band. It is
deliberately NOT wired into any alert, embed, narrator, or score yet — surfacing
is a later stage. Nothing here changes user-facing output.

Fetch pattern is a direct copy of analysis/cross_asset.py:_fetch_vix_ratio:
    - pull ^SKEW daily bars via utils/prices.fetch_history in an executor thread
    - return None on any error, empty/insufficient history, or a STALE latest bar
      (never surface a frozen weeks-old value)

Bands (from the plan):
    value >= 145  -> "elevated"  (elevated tail-demand)
    120 <= v < 145 -> "normal"
    value < 120   -> "low"       (complacency)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger("consensus_engine.analysis.skew_index")

# Band cut points (CBOE ^SKEW typically ranges ~110-170).
_ELEVATED_THRESHOLD = 145.0
_LOW_THRESHOLD = 120.0

# Latest bar must be no older than this many calendar days, else treat as stale.
# ^SKEW is a daily EOD index: on a Monday the newest close is the prior Friday, so
# the tolerance must clear a normal weekend + a holiday, but still reject a value
# that has been frozen for a week or more.
_MAX_STALE_DAYS = 5


def band_for(value: float) -> str:
    """Return the plain-language band for a SKEW value."""
    if value >= _ELEVATED_THRESHOLD:
        return "elevated"
    if value < _LOW_THRESHOLD:
        return "low"
    return "normal"


def _fetch_skew_index() -> dict | None:
    """Blocking yfinance/Schwab fetch for ^SKEW. Returns {value, band} or None.

    Called only from the async path via run_in_executor so it never blocks the
    event loop — mirrors cross_asset._fetch_vix_ratio. Returns None on error,
    empty/insufficient history, a non-positive latest close, or a stale latest bar.
    """
    try:
        from consensus_engine.utils import prices
        hist = prices.fetch_history("^SKEW", period="5d")
        if hist is None or hist.empty or len(hist) < 2:
            return None

        # Staleness guard — never show a frozen old value.
        last_ts = hist.index[-1]
        try:
            last_dt = last_ts.to_pydatetime()
        except AttributeError:
            last_dt = last_ts
        if last_dt.tzinfo is None:
            now = datetime.now()
        else:
            now = datetime.now(timezone.utc).astimezone(last_dt.tzinfo)
        if (now.date() - last_dt.date()).days > _MAX_STALE_DAYS:
            log.debug("[r8 skew] latest ^SKEW bar %s too old — no-op", last_dt.date())
            return None

        value = float(hist["Close"].iloc[-1])
        if value <= 0:
            return None
        return {"value": round(value, 2), "band": band_for(value)}
    except Exception as exc:
        log.debug("[r8 skew] _fetch_skew_index error: %s", exc)
        return None


async def compute_skew_index(executor=None) -> dict | None:
    """Return the current CBOE ^SKEW reading as {value, band}, or None when unavailable.

    ``executor`` is an optional ThreadPoolExecutor for the blocking fetch (None uses
    the loop default). Returns None on any error / stale data so a caller never
    surfaces a frozen value. This module is not yet wired into any output surface.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, _fetch_skew_index)
    except Exception as exc:
        log.debug("[r8 skew] compute_skew_index error: %s", exc)
        return None
