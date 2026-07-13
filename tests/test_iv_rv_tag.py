"""k7 (vol-context) — unit tests for compute_iv_rv_tag.

Covers the rich/fair/cheap boundaries, the NaN/non-finite atm_iv guard, the
short-history guard, custom thresholds, and the ratio math vs a hand-computed
realized vol. The helper is pure (no config, no network), so it is exercised
directly regardless of the flag state.
"""
import math

import pytest

from consensus_engine.alerts.all_command.structured_fields import compute_iv_rv_tag


def _alt_return_candles(a: float = 0.01, n_returns: int = 20) -> list[dict]:
    """Build candles whose daily log returns alternate +a, -a, ... so the
    population variance of the last 20 returns is exactly a**2 and the
    annualized realized vol is exactly a*sqrt(252) (mean return == 0)."""
    closes = [100.0]
    for i in range(n_returns):
        step = a if i % 2 == 0 else -a
        closes.append(closes[-1] * math.exp(step))
    return [{"high": c, "low": c, "close": c} for c in closes]


def test_realized_vol_matches_hand_computed():
    a = 0.01
    candles = _alt_return_candles(a)  # 21 closes, 20 returns
    res = compute_iv_rv_tag(0.20, candles)
    assert res is not None
    # RV = a * sqrt(252) since the alternating returns have mean 0 and |r| == a.
    assert res["realized_vol"] == pytest.approx(a * math.sqrt(252), rel=1e-9)
    # ratio is round(atm_iv / realized_vol, 3).
    assert res["ratio"] == pytest.approx(round(0.20 / res["realized_vol"], 3), rel=1e-9)
    assert set(res) == {"tag", "atm_iv", "realized_vol", "ratio"}
    assert res["atm_iv"] == 0.20


def test_rich_above_threshold():
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    res = compute_iv_rv_tag(1.30 * rv, candles)
    assert res["tag"] == "rich"


def test_rich_boundary_inclusive():
    # ratio exactly == rich_threshold -> rich (the comparison is >=). Pin the
    # threshold to the exact internally-computed ratio so float rounding of the
    # division can't push the boundary either way.
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    iv = 1.30 * rv
    internal_ratio = iv / rv  # bit-identical to the helper's iv/realized_vol
    res = compute_iv_rv_tag(iv, candles, rich_threshold=internal_ratio)
    assert res["tag"] == "rich"


def test_fair_between_thresholds():
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    res = compute_iv_rv_tag(1.00 * rv, candles)
    assert res["tag"] == "fair"


def test_cheap_below_threshold():
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    res = compute_iv_rv_tag(0.80 * rv, candles)
    assert res["tag"] == "cheap"


def test_cheap_boundary_inclusive():
    # ratio exactly == cheap_threshold -> cheap (the comparison is <=). Pin the
    # threshold to the exact internally-computed ratio so float rounding of the
    # division can't push the boundary either way.
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    iv = 0.80 * rv
    internal_ratio = iv / rv  # bit-identical to the helper's iv/realized_vol
    res = compute_iv_rv_tag(iv, candles, cheap_threshold=internal_ratio)
    assert res["tag"] == "cheap"


def test_custom_thresholds():
    candles = _alt_return_candles()
    rv = compute_iv_rv_tag(0.20, candles)["realized_vol"]
    # ratio 1.1: fair under defaults, but rich when rich_threshold lowered to 1.05.
    res = compute_iv_rv_tag(1.10 * rv, candles, rich_threshold=1.05, cheap_threshold=0.90)
    assert res["tag"] == "rich"


def test_nan_iv_returns_none():
    candles = _alt_return_candles()
    assert compute_iv_rv_tag(float("nan"), candles) is None


def test_nonpositive_iv_returns_none():
    candles = _alt_return_candles()
    assert compute_iv_rv_tag(0.0, candles) is None
    assert compute_iv_rv_tag(-0.2, candles) is None


def test_none_iv_returns_none():
    candles = _alt_return_candles()
    assert compute_iv_rv_tag(None, candles) is None


def test_short_history_returns_none():
    # 20 closes -> only 19 returns -> fewer than 21 closes -> None.
    candles = _alt_return_candles(n_returns=18)  # 19 closes
    assert len(candles) == 19
    assert compute_iv_rv_tag(0.20, candles) is None


def test_flat_series_zero_rv_returns_none():
    # All identical closes -> realized_vol 0 -> None (never a fabricated 'fair').
    candles = [{"high": 100.0, "low": 100.0, "close": 100.0} for _ in range(30)]
    assert compute_iv_rv_tag(0.20, candles) is None


def test_non_list_candles_returns_none():
    assert compute_iv_rv_tag(0.20, None) is None
    assert compute_iv_rv_tag(0.20, "nope") is None
