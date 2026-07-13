"""r9 (vol-context) — unit tests for compute_squeeze (Bollinger inside Keltner).

Covers nested-bands -> True, wide-Bollinger -> False, insufficient candles ->
None, and determinism on a fixed input. The helper is pure (no config, no
network), so it is exercised directly regardless of the flag state.
"""
from consensus_engine.analysis.patterns import compute_squeeze


def _coiling_candles(n: int = 30) -> list[dict]:
    """Near-flat closes (tiny stdev -> narrow Bollinger) with WIDE intraday
    high-low ranges (large ATR -> wide Keltner) => Bollinger nested in Keltner."""
    candles = []
    for i in range(n):
        close = 100.0 + (0.01 if i % 2 else -0.01)
        candles.append({"high": close + 5.0, "low": close - 5.0, "close": close})
    return candles


def _expanding_candles(n: int = 30) -> list[dict]:
    """Smoothly rising closes (large stdev over the window -> wide Bollinger)
    with tiny consecutive gaps and tiny intraday ranges (small ATR -> narrow
    Keltner) => Bollinger NOT nested in Keltner (no squeeze)."""
    candles = []
    for i in range(n):
        close = 100.0 + float(i)
        candles.append({"high": close + 0.05, "low": close - 0.05, "close": close})
    return candles


def test_nested_bands_squeeze_true():
    res = compute_squeeze(_coiling_candles())
    assert res is not None
    assert res["squeeze"] is True
    # A real squeeze means the Bollinger channel is narrower than Keltner.
    assert res["bb_width"] < res["kc_width"]
    assert set(res) == {"squeeze", "bb_width", "kc_width"}


def test_wide_bollinger_squeeze_false():
    res = compute_squeeze(_expanding_candles())
    assert res is not None
    assert res["squeeze"] is False
    assert res["bb_width"] > res["kc_width"]


def test_insufficient_candles_returns_none():
    # Fewer than period+1 (21) candles -> None.
    assert compute_squeeze(_coiling_candles(n=20)) is None
    assert compute_squeeze(_coiling_candles(n=10)) is None
    assert compute_squeeze([]) is None


def test_custom_period_insufficient():
    # 30 candles but period=40 -> need 41 -> None.
    assert compute_squeeze(_coiling_candles(n=30), period=40) is None


def test_non_list_returns_none():
    assert compute_squeeze(None) is None
    assert compute_squeeze("nope") is None


def test_determinism_same_input():
    candles = _coiling_candles()
    first = compute_squeeze(candles)
    second = compute_squeeze(candles)
    assert first == second


def test_skips_non_numeric_rows():
    # Rows with missing/None closes are dropped; enough valid rows remain.
    candles = _coiling_candles(n=30)
    candles.insert(5, {"high": None, "low": None, "close": None})
    candles.insert(10, {"high": 100.0, "low": 100.0, "close": "bad"})
    res = compute_squeeze(candles)
    assert res is not None
    assert res["squeeze"] is True
