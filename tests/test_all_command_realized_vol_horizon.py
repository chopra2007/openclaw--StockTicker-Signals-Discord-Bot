"""#25 (full-audit-2026-06-06) — realized-volatility swing horizon.

`compute_realized_daily_move(candles, lookback=10)` estimates a typical
one-day dollar move from close-to-close log-return volatility. When
`all_command.horizon_realized_vol` is ON and a positive realized move is
supplied, `compute_swing_horizon` uses max(realized, 0.7×ATR) as the per-day
denominator instead of ATR-only. Flag OFF (default) OR no realized move OR
too-few candles → identical old ATR-based horizon (no regression).

Asserts:
  * realized move: calm series < spike series; too-few candles → None
  * flag OFF → horizon byte-identical with vs without realized move
  * flag ON, spike realized move > ATR slippage → SHORTER horizon
  * flag ON, calm realized move < ATR slippage → unchanged (ATR floor wins)
"""
from __future__ import annotations

from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.alerts.all_command import structured_fields as sf


def _flag_cfg(enabled: bool):
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.horizon_realized_vol":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


def _series(prices):
    """Close-only candle dicts (no 'open' key, matching fetch_daily_candles)."""
    return [{"high": p + 1, "low": p - 1, "close": p, "volume": 1000} for p in prices]


# ---------------------------------------------------------------------------
# compute_realized_daily_move
# ---------------------------------------------------------------------------

def test_realized_move_none_when_too_few_candles():
    """Fewer than lookback+1 closes → None (caller falls back to ATR)."""
    assert sf.compute_realized_daily_move(_series([100.0] * 5), lookback=10) is None


def test_realized_move_none_for_flat_series():
    """No variance in closes → stdev 0 → None."""
    assert sf.compute_realized_daily_move(_series([100.0] * 12), lookback=10) is None


def test_realized_move_calm_lt_spike():
    """A choppy (high-vol) series yields a larger realized daily move than a
    gently-trending (low-vol) one at the same price level."""
    calm = _series([100.0 + 0.05 * i for i in range(12)])     # tiny steps
    spike = _series([100, 108, 96, 110, 94, 112, 92, 114, 90, 116, 88, 118])
    calm_move = sf.compute_realized_daily_move(calm, lookback=10)
    spike_move = sf.compute_realized_daily_move(spike, lookback=10)
    assert calm_move is not None and spike_move is not None
    assert spike_move > calm_move


def test_realized_move_tolerates_bad_closes():
    """None / NaN-like / non-positive closes are dropped, not fatal."""
    candles = _series([100.0 + i for i in range(12)])
    candles[3]["close"] = None
    candles[7]["close"] = -5.0
    # 10 good closes remain → still computable with lookback=8
    assert sf.compute_realized_daily_move(candles, lookback=8) is not None


# ---------------------------------------------------------------------------
# compute_swing_horizon blend
# ---------------------------------------------------------------------------

# spot=100, tp1=110 → distance 10. ATR=2 → 0.7×ATR slippage = 1.4/day.
_SPOT, _TP1, _ATR = 100.0, 110.0, 2.0


def test_flag_off_byte_identical_with_realized_move():
    """Flag OFF: supplying a realized move must NOT change the horizon."""
    with _flag_cfg(False):
        base = sf.compute_swing_horizon(_SPOT, _TP1, _ATR)
        with_move = sf.compute_swing_horizon(
            _SPOT, _TP1, _ATR, realized_daily_move=5.0,
        )
    assert base == with_move


def test_flag_on_no_realized_move_byte_identical():
    """Flag ON but realized move None → ATR-only horizon (unchanged)."""
    with _flag_cfg(True):
        base = sf.compute_swing_horizon(_SPOT, _TP1, _ATR)
        none_move = sf.compute_swing_horizon(
            _SPOT, _TP1, _ATR, realized_daily_move=None,
        )
    assert base == none_move


def test_flag_on_spike_shortens_horizon():
    """Flag ON + realized move > 0.7×ATR (1.4) → larger denominator → fewer
    days than ATR-only. realized=5.0 → 10/5=2 days vs 10/1.4≈7 days."""
    with _flag_cfg(True):
        atr_only = sf.compute_swing_horizon(_SPOT, _TP1, _ATR)
        blended = sf.compute_swing_horizon(
            _SPOT, _TP1, _ATR, realized_daily_move=5.0,
        )
    assert blended[0] is not None and atr_only[0] is not None
    assert blended[0] < atr_only[0]


def test_flag_on_calm_keeps_atr_floor():
    """Flag ON + realized move < 0.7×ATR → max() keeps the ATR slippage, so
    the horizon is unchanged vs ATR-only (calm tape doesn't lengthen it)."""
    with _flag_cfg(True):
        atr_only = sf.compute_swing_horizon(_SPOT, _TP1, _ATR)
        blended = sf.compute_swing_horizon(
            _SPOT, _TP1, _ATR, realized_daily_move=0.5,  # below 1.4 slippage
        )
    assert blended == atr_only


def test_flag_on_non_positive_realized_move_ignored():
    """Flag ON but realized move <= 0 → ATR-only (defensive)."""
    with _flag_cfg(True):
        atr_only = sf.compute_swing_horizon(_SPOT, _TP1, _ATR)
        zero = sf.compute_swing_horizon(
            _SPOT, _TP1, _ATR, realized_daily_move=0.0,
        )
    assert zero == atr_only
