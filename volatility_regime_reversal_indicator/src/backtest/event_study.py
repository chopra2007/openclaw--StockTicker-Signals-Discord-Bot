"""Event study: T+1-open entry, forward returns, target-event hits, episodes.

Entry convention (fixed, look-ahead-safe): signal on CLOSE of day i -> ENTER at
the adjusted OPEN of day i+1 -> forward return to the CLOSE of day i+h. Forward
outcomes use negative shifts on purpose — they measure what happened AFTER the
signal and are never used as features (the look-ahead test guards features only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import get
from ..features import utils as U
from ..signals.conditions import RISK_OFF_SIDES

PRICE = "SPY"  # Phase 1 universe


def entry_exit_prices(panel: pd.DataFrame, ticker: str = PRICE) -> tuple[pd.Series, pd.Series]:
    """entry = open of i+1 (aligned to signal day i); close = close of i."""
    entry = panel[f"{ticker}_open"].shift(-1)
    close = panel[f"{ticker}_close"]
    return entry, close


def forward_returns(panel: pd.DataFrame, horizons: list[int], ticker: str = PRICE) -> pd.DataFrame:
    """fwd_ret[i, h] = close[i+h] / open[i+1] - 1  (enter next open, exit close h days later)."""
    entry, close = entry_exit_prices(panel, ticker)
    out = {}
    for h in horizons:
        exit_h = close.shift(-h)
        out[h] = exit_h / entry - 1.0
    return pd.DataFrame(out, index=panel.index)


def forward_event_hits(
    panel: pd.DataFrame, tiers: list[int], window: int, ticker: str = PRICE
) -> tuple[dict[tuple[str, int], pd.Series], pd.Series, pd.Series]:
    """For each day i, did a peak-to-trough drop (top) / trough-to-peak rally (bottom)
    of >= tier% occur in the close path over (i, i+window]? Requires a FULL window
    (incomplete trailing windows -> NaN, excluded from rates)."""
    close = panel[f"{ticker}_close"].to_numpy()
    n = len(close)
    fdd = np.full(n, np.nan)  # most negative running-peak drawdown in window (<=0)
    fru = np.full(n, np.nan)  # most positive running-trough runup in window (>=0)
    for i in range(n):
        j0, j1 = i + 1, i + 1 + window
        if j1 > n:
            break
        seg = close[j0:j1]
        fdd[i] = float((seg / np.maximum.accumulate(seg) - 1.0).min())
        fru[i] = float((seg / np.minimum.accumulate(seg) - 1.0).max())
    idx = panel.index
    fdd_s, fru_s = pd.Series(fdd, index=idx), pd.Series(fru, index=idx)
    hits: dict[tuple[str, int], pd.Series] = {}
    for tier in tiers:
        t = tier / 100.0
        top = pd.Series(np.where(np.isnan(fdd), np.nan, (fdd <= -t).astype(float)), index=idx)
        bot = pd.Series(np.where(np.isnan(fru), np.nan, (fru >= t).astype(float)), index=idx)
        hits[("top", tier)] = top
        hits[("bottom", tier)] = bot
    return hits, fdd_s, fru_s


def forward_atr_move(panel: pd.DataFrame, horizon: int, ticker: str = PRICE) -> pd.Series:
    """Signed forward move at `horizon` expressed in trailing-ATR units (magnitude/risk)."""
    entry, close = entry_exit_prices(panel, ticker)
    atr = U.atr(panel[f"{ticker}_high"], panel[f"{ticker}_low"], panel[f"{ticker}_close"],
                get("features.atr_window", 14))
    move = close.shift(-horizon) - entry
    return move / atr


def collapse_episodes(signal: pd.Series, window: int) -> pd.Series:
    """Collapse same-side alert days within `window` trading-day positions to ONE
    episode (the FIRST alert is the entry). Returns a boolean Series: True only on
    episode-entry days."""
    pos = np.flatnonzero(signal.to_numpy())
    keep: list[int] = []
    last = -10**9
    for p in pos:
        if p - last >= window:
            keep.append(p)
            last = p
    out = pd.Series(False, index=signal.index)
    if keep:
        out.iloc[keep] = True
    return out


def edge_sign(side: str) -> float:
    """+1 if higher forward return = the signal's intent (risk-on), -1 if lower (risk-off)."""
    return -1.0 if side in RISK_OFF_SIDES else 1.0


def event_side(side: str) -> str:
    """Map a condition side onto the target-event side it is meant to precede."""
    return "top" if side in RISK_OFF_SIDES else "bottom"
