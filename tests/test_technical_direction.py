"""Tests for direction-aware technical filters."""
import pytest
from consensus_engine.analysis.technical import _run_filters


def _make_quote(current_price=150.0, prev_close=145.0):
    return {"c": current_price, "o": 146.0, "h": 152.0, "l": 144.0, "pc": prev_close, "dp": 3.4, "t": 0}


def _make_candles(n=25, base_close=145.0, trend="up"):
    """Generate synthetic OHLCV candles."""
    closes = []
    for i in range(n):
        if trend == "up":
            closes.append(base_close + i * 0.5)
        elif trend == "down":
            closes.append(base_close - i * 0.5)
        else:
            closes.append(base_close)
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    volumes = [1_000_000 + i * 50_000 for i in range(n)]
    # Make last volume very high for RVOL
    volumes[-1] = 5_000_000
    return {
        "o": [c - 0.5 for c in closes],
        "h": highs,
        "l": lows,
        "c": closes,
        "v": volumes,
        "t": list(range(n)),
    }


def test_long_filters_basic():
    """Long direction should use standard bullish logic."""
    quote = _make_quote(current_price=160.0, prev_close=155.0)
    candles = _make_candles(25, base_close=145.0, trend="up")
    filters = _run_filters(quote, candles, direction="long")
    assert len(filters) == 6
    names = {f.name for f in filters}
    assert names == {"RVOL", "VWAP", "RSI", "EMA Cross", "Price Change", "ATR Breakout"}


def test_short_filters_basic():
    """Short direction should use bearish logic."""
    quote = _make_quote(current_price=140.0, prev_close=150.0)
    candles = _make_candles(25, base_close=155.0, trend="down")
    filters = _run_filters(quote, candles, direction="short")
    assert len(filters) == 6


def test_vwap_long_above_passes():
    """LONG: price above VWAP should pass."""
    candles = _make_candles(25, base_close=100.0, trend="flat")
    quote = _make_quote(current_price=200.0, prev_close=195.0)
    filters = _run_filters(quote, candles, direction="long")
    vwap_f = next(f for f in filters if f.name == "VWAP")
    assert vwap_f.passed is True
    assert ">" in vwap_f.threshold


def test_vwap_short_below_passes():
    """SHORT: price below VWAP should pass."""
    candles = _make_candles(25, base_close=200.0, trend="flat")
    quote = _make_quote(current_price=100.0, prev_close=105.0)
    filters = _run_filters(quote, candles, direction="short")
    vwap_f = next(f for f in filters if f.name == "VWAP")
    assert vwap_f.passed is True
    assert "<" in vwap_f.threshold


def test_vwap_short_above_fails():
    """SHORT: price above VWAP should fail."""
    candles = _make_candles(25, base_close=100.0, trend="flat")
    quote = _make_quote(current_price=200.0, prev_close=195.0)
    filters = _run_filters(quote, candles, direction="short")
    vwap_f = next(f for f in filters if f.name == "VWAP")
    assert vwap_f.passed is False


def test_price_change_long_positive_passes():
    """LONG: positive price change should pass."""
    quote = _make_quote(current_price=150.0, prev_close=145.0)
    candles = _make_candles(25)
    filters = _run_filters(quote, candles, direction="long")
    pc_f = next(f for f in filters if f.name == "Price Change")
    assert pc_f.value > 0
    assert pc_f.passed is True


def test_price_change_short_negative_passes():
    """SHORT: negative price change should pass."""
    quote = _make_quote(current_price=140.0, prev_close=145.0)
    candles = _make_candles(25)
    filters = _run_filters(quote, candles, direction="short")
    pc_f = next(f for f in filters if f.name == "Price Change")
    assert pc_f.value < 0
    assert pc_f.passed is True


def test_price_change_short_positive_fails():
    """SHORT: positive price change should fail."""
    quote = _make_quote(current_price=150.0, prev_close=145.0)
    candles = _make_candles(25)
    filters = _run_filters(quote, candles, direction="short")
    pc_f = next(f for f in filters if f.name == "Price Change")
    assert pc_f.passed is False


def test_ema_cross_short_death_cross():
    """SHORT: fast < slow (death cross) should pass."""
    candles = _make_candles(25, base_close=155.0, trend="down")
    quote = _make_quote(current_price=140.0, prev_close=145.0)
    filters = _run_filters(quote, candles, direction="short")
    ema_f = next(f for f in filters if f.name == "EMA Cross")
    assert ema_f.value < 0  # fast below slow
    assert ema_f.passed is True
    assert "<" in ema_f.threshold


def test_ema_cross_long_golden_cross():
    """LONG: fast > slow (golden cross) should pass."""
    candles = _make_candles(25, base_close=100.0, trend="up")
    quote = _make_quote(current_price=115.0, prev_close=110.0)
    filters = _run_filters(quote, candles, direction="long")
    ema_f = next(f for f in filters if f.name == "EMA Cross")
    assert ema_f.value > 0
    assert ema_f.passed is True
    assert ">" in ema_f.threshold


def test_rsi_short_uses_overbought_range():
    """SHORT: RSI config should use the 60-85 overbought range."""
    candles = _make_candles(25, base_close=100.0, trend="up")
    quote = _make_quote()
    filters = _run_filters(quote, candles, direction="short")
    rsi_f = next(f for f in filters if f.name == "RSI")
    assert "60" in rsi_f.threshold
    assert "85" in rsi_f.threshold


def test_rsi_long_uses_standard_range():
    """LONG: RSI config should use the 40-75 standard range."""
    candles = _make_candles(25, base_close=100.0, trend="up")
    quote = _make_quote()
    filters = _run_filters(quote, candles, direction="long")
    rsi_f = next(f for f in filters if f.name == "RSI")
    assert "40" in rsi_f.threshold
    assert "75" in rsi_f.threshold


def test_default_direction_is_long():
    """Omitting direction should default to long."""
    quote = _make_quote(current_price=150.0, prev_close=145.0)
    candles = _make_candles(25, base_close=100.0, trend="up")
    filters_default = _run_filters(quote, candles)
    filters_long = _run_filters(quote, candles, direction="long")
    for fd, fl in zip(filters_default, filters_long):
        assert fd.name == fl.name
        assert fd.passed == fl.passed
        assert fd.threshold == fl.threshold
