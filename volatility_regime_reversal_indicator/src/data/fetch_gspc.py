"""Fetch the long-history S&P 500 INDEX (^GSPC) daily close into the Parquet store.

WHY a separate fetcher from fetch_prices.py: the ETF universe (SPY etc.) only starts
1993, but the Phase-4 capitulation->thrust bottom test needs a price series that spans
the 55-year NYSE up/down-VOLUME archive (NYSE_UDVOL, 1965-2020). The S&P 500 index
^GSPC has free daily history back to 1927 on yfinance, so it is the natural long-window
price for the bottom outcome label (does an 8%/15% rally happen within 60 trading days?)
and for drawdown/eligibility.

^GSPC is a PRICE index (not total-return), unadjusted for dividends — fine here: the
8%/15% rally outcome and the drawdown eligibility are PRICE moves, and dividends over a
60-trading-day window are tiny relative to an 8% swing. Stored same as the ETFs
(open/high/low/close/volume, lowercase) so store.load_panel and forward_event_hits work
unchanged with ticker="GSPC".

Point-in-time / append-only: same write_series contract as every other series; each row
is one settled session's own OHLCV, no look-ahead. Persisted append-only so committed
history is never silently restated.
"""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

from . import store

_SYMBOL = "^GSPC"
_START = "1962-01-01"          # comfortably covers NYSE_UDVOL's 1965-03 start
_RETRY_BACKOFF_S = 3.0


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if df.columns.nlevels > 1:
        df = df.copy()
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
    return df


def fetch_gspc_frame() -> pd.DataFrame | None:
    """Download ^GSPC daily OHLCV; flatten to lowercase columns; drop all-NaN rows."""
    for attempt in range(2):
        df = yf.download(_SYMBOL, start=_START, auto_adjust=False, progress=False)
        if df is not None and not df.empty:
            df = _flatten(df)
            df = df.dropna(how="all")
            if not df.empty:
                return df
        if attempt == 0:
            time.sleep(_RETRY_BACKOFF_S)
    return None


def fetch_gspc(append_only: bool = True) -> bool:
    """Fetch ^GSPC into the store as series 'GSPC'.

    append_only: keep every committed historical row unchanged and only add genuinely
    new dates (silent-restatement guard), mirroring fetch_updown_volume.
    """
    fresh = fetch_gspc_frame()
    if fresh is None or fresh.empty:
        return False
    if append_only and store.series_exists("GSPC"):
        existing = store.read_series("GSPC")
        new_dates = fresh.index.difference(existing.index)
        if len(new_dates) == 0:
            return False
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("GSPC", merged, source="yfinance:^GSPC", adjusted=False)
        return True
    store.write_series("GSPC", fresh, source="yfinance:^GSPC", adjusted=False)
    return True


if __name__ == "__main__":
    ok = fetch_gspc()
    print("GSPC updated" if ok else "GSPC: no new rows")
