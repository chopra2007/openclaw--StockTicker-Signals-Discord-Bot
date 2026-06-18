"""Event study: T+1-open entry (no same-close look-ahead) + episode collapsing."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.event_study import collapse_episodes, forward_returns


def _panel(n=30):
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.Series(np.arange(100, 100 + n, dtype=float), index=idx)
    openp = close - 0.5  # open distinct from close so we can detect which is used
    high = close + 1.0
    low = openp - 1.0
    vol = pd.Series(1.0, index=idx)
    return pd.DataFrame({"SPY_open": openp, "SPY_high": high, "SPY_low": low,
                         "SPY_close": close, "SPY_volume": vol})


def test_entry_is_next_open_not_signal_close() -> None:
    p = _panel()
    fwd = forward_returns(p, [1, 5])
    i = 10
    entry = p["SPY_open"].iloc[i + 1]           # open of i+1
    # h=1 -> exit close of i+1
    assert np.isclose(fwd[1].iloc[i], p["SPY_close"].iloc[i + 1] / entry - 1.0)
    # h=5 -> exit close of i+5
    assert np.isclose(fwd[5].iloc[i], p["SPY_close"].iloc[i + 5] / entry - 1.0)
    # the signal-day close is NOT the entry (would be a look-ahead)
    assert not np.isclose(fwd[1].iloc[i], p["SPY_close"].iloc[i + 1] / p["SPY_close"].iloc[i] - 1.0)


def test_forward_returns_are_nan_at_the_tail() -> None:
    p = _panel(n=12)
    fwd = forward_returns(p, [5])
    # last 5 rows cannot look 5 days forward
    assert fwd[5].iloc[-1] != fwd[5].iloc[-1]  # NaN


def test_episode_collapsing() -> None:
    idx = pd.bdate_range("2020-01-01", periods=100)
    sig = pd.Series(False, index=idx)
    # cluster A: days 5,6,7,8 within 20 -> one episode at day 5
    sig.iloc[[5, 6, 7, 8]] = True
    # cluster B: day 40 (>20 after day 5) -> new episode; day 45 collapses into it
    sig.iloc[[40, 45]] = True
    # cluster C: day 70 -> new episode
    sig.iloc[70] = True
    ep = collapse_episodes(sig, window=20)
    entries = list(np.flatnonzero(ep.to_numpy()))
    assert entries == [5, 40, 70]
