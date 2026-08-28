#!/usr/bin/env python3
"""Daily price panel, data-integrity guards, and the as-of-date rules.

The daily cache (`data/mmhl_daily/<SYMBOL>.json`) is split-adjusted and NOT
dividend-adjusted; that was proved against the raw 15:59 minute close in
`current-state.json`.  Every number here comes from completed sessions only.

Three guards live here because they are the difference between a real result
and a fabricated one:

* placeholder rows (a $0.0001 close years before a company listed);
* early-close sessions, taken from a hard-coded exchange calendar because the
  minute files are wrong about them from 2025 onward;
* a symbol whose price jumps more than 20% overnight, which is treated as a
  possible split or symbol change rather than a trade.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
DAILY_DIR = WORKSPACE / "data" / "mmhl_daily"
MARKET_STORE = WORKSPACE / "data" / "market_store"

VOL_LOOKBACK = 50           # sessions for the abnormal-volume measure
VOL_MIN_PRESENT = 40
VOL_SD_FLOOR = 0.10
LIQ_LOOKBACK = 60           # sessions for the as-of-date liquidity check
LIQ_MIN_PRESENT = 55
MIN_MEDIAN_DOLLAR_VOLUME = 50_000_000
SHORT_MIN_MEDIAN_DOLLAR_VOLUME = 200_000_000
MIN_CLOSE = 1.0             # a valid session's close
MIN_PRICE = 5.0             # price on the session before the signal
SHORT_MIN_PRICE = 10.0
MIN_FILE_SESSIONS = 250
SPLIT_GUARD_JUMP = 0.20
SPLIT_GUARD_DAYS = 5

# NYSE 1:00 p.m. Eastern early closes, 2015-2026.  Hard-coded on purpose: the
# minute files still carry stray odd-lot prints after the close from 2025 on,
# so the data cannot be trusted to say when a session was short.
EARLY_CLOSE_DATES = {
    "2015-11-27", "2015-12-24",
    "2016-11-25",
    "2017-07-03", "2017-11-24",
    "2018-07-03", "2018-11-23", "2018-12-24",
    "2019-07-03", "2019-11-29", "2019-12-24",
    "2020-11-27", "2020-12-24",
    "2021-11-26",
    "2022-11-25",
    "2023-07-03", "2023-11-24",
    "2024-07-03", "2024-11-29", "2024-12-24",
    "2025-07-03", "2025-11-28", "2025-12-24",
    "2026-11-27", "2026-12-24",
}

# The owner asked for a SHARE-trading rule. These are funds, not companies -
# four of them are triple-leveraged or volatility products that lose value
# structurally whatever the market does. A 3% move in a triple-leveraged
# semiconductor fund is a 1% move in semiconductors, which is a different event
# from a company's own 3% move and is not what any of these papers describe.
NOT_A_COMPANY = {
    "ARKK", "DIA", "GDX", "GLD", "IWM", "QQQ", "RSP", "SLV", "SMH", "SOXL",
    "SPY", "SQQQ", "TLT", "TQQQ", "UPRO", "USO", "UVXY", "VOO", "VTI", "XBI",
    "XLE", "XLF", "XLK", "XLV",
}

_PANEL = None


# --------------------------------------------------------------------------- #
def load_daily_panel(force: bool = False) -> pd.DataFrame:
    """One row per (date, symbol) with return, volume state and volatility.

    Placeholder rows are marked `valid_session = False` rather than deleted, so
    a lookback can count how many real sessions it actually saw.
    """
    global _PANEL
    if _PANEL is not None and not force:
        return _PANEL
    frames = []
    for f in sorted(DAILY_DIR.glob("*.json")):
        if f.stem.startswith("_"):          # _meta.json is not a stock
            continue
        if f.stem in NOT_A_COMPANY:         # a fund is not a share
            continue
        d = json.loads(f.read_text())
        if not d:
            continue
        ks = sorted(d)
        arr = np.array([d[k] for k in ks], dtype=float)
        frames.append(pd.DataFrame({
            "date": ks,
            "symbol": f.stem,
            "open": arr[:, 0], "high": arr[:, 1], "low": arr[:, 2],
            "close": arr[:, 3], "volume": arr[:, 4],
        }))
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["symbol", "date"], ignore_index=True)

    df["valid_session"] = (
        (df["close"] > MIN_CLOSE) & (df["volume"] > 0)
        & np.isfinite(df["open"]) & (df["open"] > MIN_CLOSE)
    )

    g = df.groupby("symbol", sort=False)
    df["prev_close"] = g["close"].shift(1)
    df["ret"] = df["close"] / df["prev_close"] - 1.0
    df["dollar_volume"] = df["close"] * df["volume"]
    df["sessions_before"] = g.cumcount()

    # possible split or symbol change: a >20% overnight jump into this session
    jump = (df["open"] / df["prev_close"] - 1.0).abs()
    flag = (jump > SPLIT_GUARD_JUMP) & df["valid_session"] & df["prev_close"].notna()
    df["split_guard"] = (
        g["symbol"].transform(lambda s: pd.Series(flag.loc[s.index]).rolling(
            SPLIT_GUARD_DAYS + 1, min_periods=1).max()).astype(bool)
    )

    lv = np.log(df["volume"].where(df["volume"] > 0) + 1.0)
    df["_lv"] = lv.where(df["valid_session"])
    g = df.groupby("symbol", sort=False)
    m = g["_lv"].transform(
        lambda s: s.shift(1).rolling(VOL_LOOKBACK, min_periods=VOL_MIN_PRESENT).mean())
    sd = g["_lv"].transform(
        lambda s: s.shift(1).rolling(VOL_LOOKBACK, min_periods=VOL_MIN_PRESENT).std())
    df["v"] = (df["_lv"] - m) / np.maximum(sd, VOL_SD_FLOOR)

    # 20-session average true range, complete at this session's close
    pc = df["prev_close"].where(df["prev_close"] > MIN_CLOSE).to_numpy()
    tr = np.maximum.reduce([
        (df["high"] - df["low"]).to_numpy(),
        (df["high"] - df["prev_close"]).abs().to_numpy(),
        (df["low"] - df["prev_close"]).abs().to_numpy(),
    ]) / pc
    df["_tr"] = np.where(df["valid_session"], tr, np.nan)
    df["atr20"] = df.groupby("symbol", sort=False)["_tr"].transform(
        lambda s: s.rolling(20, min_periods=15).mean())
    df = df.drop(columns=["_lv", "_tr"])
    _PANEL = df
    return df


def as_of_liquid_daily(panel: pd.DataFrame) -> pd.DataFrame:
    """Eligibility on date d, judged only on the 60 completed sessions before it."""
    df = panel[["date", "symbol", "close", "dollar_volume", "valid_session",
                "sessions_before", "split_guard"]].copy()
    df = df.sort_values(["symbol", "date"], ignore_index=True)
    g = df.groupby("symbol", sort=False)

    dv = df["dollar_volume"].where(df["valid_session"])
    df["_dv"] = dv
    med_dv = g["_dv"].transform(
        lambda s: s.shift(1).rolling(LIQ_LOOKBACK, min_periods=LIQ_MIN_PRESENT)
        .median())
    n_valid = g["valid_session"].transform(
        lambda s: s.shift(1).rolling(LIQ_LOOKBACK, min_periods=1).sum())
    prev_close = g["close"].shift(1)

    base = (
        (n_valid >= LIQ_MIN_PRESENT)
        & (df["sessions_before"] >= MIN_FILE_SESSIONS)
        & (~df["split_guard"].fillna(False))
        & (~df["date"].isin(EARLY_CLOSE_DATES))
    )
    df["prior60_median_dollar_volume"] = med_dv
    df["liquid"] = (base & (med_dv >= MIN_MEDIAN_DOLLAR_VOLUME)
                    & (prev_close >= MIN_PRICE)).fillna(False)
    df["shortable_proxy"] = (
        base & (med_dv >= SHORT_MIN_MEDIAN_DOLLAR_VOLUME)
        & (prev_close >= SHORT_MIN_PRICE)).fillna(False)
    return df[["date", "symbol", "liquid", "shortable_proxy",
               "prior60_median_dollar_volume"]]


def as_of_liquid_minute(daily_from_bars: pd.DataFrame) -> pd.DataFrame:
    """Method 1's liquidity, built from the minute panel itself.

    Eleven of the sixty minute names have no daily file, so the daily rule
    cannot be used.  `daily_from_bars` needs columns
    date, symbol, session_dollar_volume, session_bars, last_close.
    """
    df = daily_from_bars.sort_values(["symbol", "date"], ignore_index=True).copy()
    df["ok_session"] = (df["session_bars"] >= 300) & (df["session_dollar_volume"] > 0)
    g = df.groupby("symbol", sort=False)
    df["_dv"] = df["session_dollar_volume"].where(df["ok_session"])
    med = g["_dv"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=18).median())
    n_ok = g["ok_session"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    prev_close = g["last_close"].shift(1)
    df["prior20_median_dollar_volume"] = med
    df["liquid"] = (
        (n_ok >= 18) & (med >= 10_000_000) & (prev_close >= MIN_PRICE)
        & (~df["date"].isin(EARLY_CLOSE_DATES))
    ).fillna(False)
    return df[["date", "symbol", "liquid", "prior20_median_dollar_volume"]]


def load_spy() -> pd.DataFrame:
    df = pd.read_parquet(MARKET_STORE / "SPY.parquet").reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date", ignore_index=True)
    df["ret"] = df["close"] / df["close"].shift(1) - 1.0
    return df[["date", "open", "high", "low", "close", "ret"]]
