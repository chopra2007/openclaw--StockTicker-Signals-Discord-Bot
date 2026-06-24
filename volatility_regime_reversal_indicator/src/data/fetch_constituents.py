"""Fetch daily adjusted-close prices for S&P 500 and Nasdaq-100 constituents.

Uses today's (as-of) membership snapshot, NOT historical. This is a deliberate
and documented limitation:

SURVIVORSHIP BIAS WARNING (pre-registered caveat):
  Today's membership applied backward DROPS delisted losers. Historical cross-
  sectional dispersion on this subset is UNDERSTATED in stress periods, because
  the names that blew up and were removed are excluded. This biases the dispersion
  series DOWN during historical crashes and makes the signal look CLEANER than it
  was in real time. The effect is:
    - Precision may be inflated relative to what a live implementation achieves.
    - A real-time system would see HIGHER dispersion in stress (more losers).
  The honest use is descriptive + directional, NOT quantitative precision claims
  from a survivorship-clean sample.

Data is cached in the store as two series:
  SP500_MEMBERS_DISP — daily cross-sectional close-price-return std for S&P 500 subset
  NDX_MEMBERS_DISP   — daily cross-sectional close-price-return std for Nasdaq-100 subset

The raw close prices for all fetched tickers are NOT stored individually (they are
large and unneeded for downstream use); only the DAILY AGGREGATE dispersion columns
are written. This avoids store bloat.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from ..config import project_root
from . import store

log = logging.getLogger(__name__)

# As-of snapshot (today's members, applied backward — see survivorship warning above).
# S&P 500 current members (representative subset of ~100 large-caps across sectors).
# Using 100 representative names across all 11 GICS sectors for computational speed.
# Coverage: ~20 per sector for the 4 largest, 5-10 for smaller sectors.
_SP500_SNAPSHOT: list[str] = [
    # Information Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CSCO", "AMAT", "AMD", "INTC", "TXN",
    "QCOM", "MU", "NOW", "INTU", "PANW", "ADBE", "CRM", "ACN", "IBM", "KLAC",
    # Health Care
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "AMGN", "PFE", "MDT",
    "DHR", "BSX", "ELV", "CI", "HUM", "ISRG", "VRTX", "ZBH", "BDX", "IQV",
    # Financials
    "BRK-B", "JPM", "BAC", "GS", "MS", "WFC", "BLK", "SCHW", "AXP", "USB",
    "PNC", "COF", "TFC", "CB", "MET", "AON", "MCO", "SPGI", "CME", "ICE",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG", "LOW", "TJX", "ABNB",
    "YUM", "DPZ", "MAR", "F", "GM",
    # Industrials
    "GE", "CAT", "RTX", "HON", "UPS", "DE", "LMT", "NOC", "BA", "MMM",
    "EMR", "ETN", "JCI", "ROK", "PH",
    # Communication Services
    "META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ", "ATVI", "TMUS",
    # Consumer Staples
    "WMT", "PG", "KO", "PEP", "COST", "CL", "MDLZ", "GIS", "K", "HSY",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "HAL", "DVN",
    # Materials
    "LIN", "APD", "ECL", "NEM", "FCX", "DOW", "DD", "PPG", "ALB", "CF",
    # Real Estate
    "PLD", "AMT", "EQIX", "PSA", "SPG", "O", "DLR", "EQR", "AVB", "WELL",
    # Utilities
    "NEE", "DUK", "SO", "AEP", "EXC", "SRE", "XEL", "ES", "WEC", "ETR",
]

# Nasdaq-100 current members (as-of snapshot, same survivorship caveat).
_NDX_SNAPSHOT: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "INTU", "CSCO", "QCOM", "INTC", "PEP", "AMAT", "AMGN",
    "TXN", "CMCSA", "HON", "SBUX", "ISRG", "VRTX", "BKNG", "ADP", "REGN", "PANW",
    "GILD", "MU", "LRCX", "KLAC", "MDLZ", "MELI", "KDP", "ABNB", "CDNS", "SNPS",
    "CEG", "WDAY", "ORLY", "CTAS", "FTNT", "MNST", "DXCM", "PCAR", "EXC", "MRVL",
    "AZN", "KHC", "WBD", "ROP", "ASML", "NXPI", "ROST", "GFS", "ODFL", "CPRT",
    "IDXX", "FAST", "PAYX", "BKR", "FANG", "TEAM", "VRSK", "GEHC", "ADSK", "EA",
    "BIIB", "ON", "ANSS", "MRNA", "ZS", "TTWO", "DLTR", "XEL", "ILMN", "SIRI",
    "ENPH", "ALGN", "OKTA", "LCID", "DDOG", "RIVN", "SGEN", "CRWD", "ZM", "MTCH",
    "GRAB", "WBA", "CTSH", "AEP", "CSX", "CHTR", "CDW", "VTRS", "INCY", "ZBRA",
]

_START = "2005-01-01"
_MAX_WORKERS = 8
_RETRY_BACKOFF_S = 2.0


def _fetch_one(ticker: str) -> Optional[pd.Series]:
    """Fetch adjusted close for one ticker; return a Series indexed by date, or None."""
    for attempt in range(2):
        try:
            df = yf.download(ticker, start=_START, auto_adjust=True,
                             progress=False, threads=False)
            if df is not None and not df.empty:
                # yfinance returns MultiIndex columns (field, ticker) when single-ticker too
                if df.columns.nlevels > 1:
                    close = df["Close"][ticker] if ticker in df["Close"].columns else df["Close"].iloc[:, 0]
                else:
                    close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
                close = close.dropna()
                if len(close) > 100:
                    close.index = pd.to_datetime(close.index).tz_localize(None)
                    close.name = ticker
                    return close
        except Exception as exc:
            log.debug("fetch %s attempt %d: %s", ticker, attempt, exc)
        if attempt == 0:
            time.sleep(_RETRY_BACKOFF_S)
    return None


def _compute_dispersion(tickers: list[str], label: str) -> tuple[pd.Series, pd.Series, int]:
    """Download all tickers in parallel, compute daily cross-sectional return std.

    Returns (dispersion_series, downside_dispersion_series, n_tickers_fetched).
    """
    closes: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            result = fut.result()
            if result is not None:
                closes[t] = result
            else:
                log.info("[%s] could not fetch %s", label, t)

    n_fetched = len(closes)
    log.info("[%s] fetched %d / %d tickers", label, n_fetched, len(tickers))

    if n_fetched < 10:
        raise RuntimeError(f"[{label}] only {n_fetched} tickers fetched — too few to compute dispersion")

    panel = pd.DataFrame(closes).sort_index()
    # Daily log returns (point-in-time: no forward look)
    rets = np.log(panel / panel.shift(1))

    # Cross-sectional std of returns (require >=10 non-NaN tickers for a valid estimate)
    min_tickers = max(10, n_fetched // 5)
    count = rets.notna().sum(axis=1)
    disp = rets.std(axis=1, ddof=0)
    disp[count < min_tickers] = np.nan

    # Downside semi-dispersion: std across only negative-return members
    def _down_std(row: pd.Series) -> float:
        neg = row[row < 0].dropna()
        if len(neg) < 5:
            return np.nan
        return float(neg.std(ddof=0))

    down_disp = rets.apply(_down_std, axis=1)

    return disp, down_disp, n_fetched


def fetch_and_store_constituents() -> dict[str, int]:
    """Main entry point: download S&P 500 and Nasdaq-100 constituent closes,
    compute dispersion series, and write to the Parquet store.

    Returns {index_name: n_tickers_fetched}.
    """
    results: dict[str, int] = {}

    for label, tickers, store_key_disp, store_key_down in [
        ("SP500", _SP500_SNAPSHOT, "SP500_DISP", "SP500_DOWN_DISP"),
        ("NDX", _NDX_SNAPSHOT, "NDX_DISP", "NDX_DOWN_DISP"),
    ]:
        log.info("Fetching %s constituents (%d tickers)…", label, len(tickers))
        disp, down_disp, n = _compute_dispersion(tickers, label)

        df_disp = pd.DataFrame({"value": disp})
        df_disp.index.name = "date"
        store.write_series(store_key_disp, df_disp,
                           source=f"yfinance/{label}_constituents_dispersion", adjusted=True)

        df_down = pd.DataFrame({"value": down_disp})
        df_down.index.name = "date"
        store.write_series(store_key_down, df_down,
                           source=f"yfinance/{label}_constituents_downside_dispersion", adjusted=True)

        results[label] = n
        log.info("[%s] stored dispersion + downside-dispersion (%d rows)", label, len(disp))

    return results


def _print_coverage(results: dict[str, int], tickers_map: dict[str, list[str]]) -> None:
    for label, n in results.items():
        total = len(tickers_map[label])
        print(f"  {label}: {n}/{total} tickers fetched ({n/total*100:.0f}% coverage)")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s",
                        stream=sys.stdout)
    res = fetch_and_store_constituents()
    _print_coverage(res, {"SP500": _SP500_SNAPSHOT, "NDX": _NDX_SNAPSHOT})
