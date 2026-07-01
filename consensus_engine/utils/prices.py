"""OHLCV price-history choke-point (TODO #57).

`fetch_history` is the single wrapper that lets us serve daily/intraday bars from
Schwab `/pricehistory` (real-time, official, no Yahoo throttle) with an automatic
yfinance fallback. It returns the SAME contract callers already expect from
`yf.Ticker(t).history(...)`: a pandas DataFrame with columns
[Open, High, Low, Close, Volume] and a tz-aware `America/New_York` DatetimeIndex.

Gated by `features.schwab_ohlcv.enabled` (default OFF). Any Schwab failure (token
dead, empty, unsupported symbol, transport) silently falls back to yfinance so the
engine never loses price data.

RISK-5 (dividend adjustment): yfinance `.history()` defaults to auto_adjust=True
(dividend + split adjusted Close); Schwab `/pricehistory` is split-adjusted only.
For most consumers (relative strength, chart display, short-window levels) the
drift is immaterial. Calibration-critical, dividend-sensitive consumers
(wolf_outcomes 5d/20d labels, earnings_move 2y) deliberately keep calling
yfinance directly — see their call sites.
"""

import logging

from consensus_engine import config

log = logging.getLogger("consensus_engine.utils.prices")


def _schwab_ohlcv_enabled() -> bool:
    return bool(config.get("features.schwab_ohlcv.enabled", False))


def fetch_history(ticker: str, *, period=None, start=None, end=None, interval: str = "1d"):
    """Daily/intraday OHLCV as a yfinance-compatible DataFrame.

    Schwab PRIMARY (when the flag is on) → yfinance FALLBACK. Same shape either
    way: columns [Open, High, Low, Close, Volume], tz-aware America/New_York index.
    """
    if _schwab_ohlcv_enabled():
        try:
            from consensus_engine.scanners import schwab_client
            df = schwab_client.get_price_history(
                ticker, period=period, interval=interval, start=start, end=end
            )
            if df is not None and not df.empty:
                return df
        except Exception as ex:  # SchwabRefreshTokenExpired included → fall back
            log.debug("schwab pricehistory failed for %s: %s", ticker, ex)

    # yfinance fallback — the pre-#57 behaviour, unchanged.
    import yfinance as yf
    t = yf.Ticker(ticker)
    kwargs = {"interval": interval}
    if period is not None:
        kwargs["period"] = period
    if start is not None:
        kwargs["start"] = start
    if end is not None:
        kwargs["end"] = end
    return t.history(**kwargs)
