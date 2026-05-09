"""Gap 3 — Chart pattern detection.

Library at consensus_engine/analysis/patterns.py with one detector per
classical pattern. Each detector takes a list of dict candles (each row
has at minimum `high`, `low`; `close` optional) and returns either
None (pattern absent) or a dict
    {"pattern": "<name>", "confidence": float in [0, 1],
     "key_level": float}

Per RESUME-after-compact.md Gap 3 acceptance:
> synthesize 20 candles forming a textbook bull flag (rising consolidation
> channel after a strong leg up); assert detector returns
> {"pattern": "bull_flag", "key_level": <x>}.
"""
from __future__ import annotations

import pytest


def _candle(h, l, c=None):
    return {"high": h, "low": l, "close": c if c is not None else (h + l) / 2}


# ---------------------------------------------------------------------------
# breakout_above_n_day_high
# ---------------------------------------------------------------------------

def test_breakout_above_20day_high_fires_when_close_exceeds_prior_max():
    from consensus_engine.analysis import patterns
    base = [_candle(100, 95, 98) for _ in range(20)]
    breakout = base + [_candle(108, 102, 107)]
    out = patterns.breakout_above_n_day_high(breakout, n=20)
    assert out is not None
    assert out["pattern"] == "breakout_above_n_day_high"
    assert out["key_level"] == 100  # max prior high
    assert 0.0 < out["confidence"] <= 1.0


def test_breakout_does_not_fire_when_close_inside_range():
    from consensus_engine.analysis import patterns
    candles = [_candle(100, 95, 98) for _ in range(21)]
    assert patterns.breakout_above_n_day_high(candles, n=20) is None


def test_breakout_returns_none_with_too_few_candles():
    from consensus_engine.analysis import patterns
    short = [_candle(100, 95, 98) for _ in range(5)]
    assert patterns.breakout_above_n_day_high(short, n=20) is None


# ---------------------------------------------------------------------------
# bull_flag
# ---------------------------------------------------------------------------

def test_bull_flag_textbook_pattern_detected():
    """Strong leg up (pole) followed by tight downward-sloping consolidation."""
    from consensus_engine.analysis import patterns

    # Pole: 10 candles climbing 100 → 130 (+30%)
    pole = [_candle(100 + 3*i + 1, 100 + 3*i - 1, 100 + 3*i) for i in range(10)]
    # Flag: 10 candles consolidating 130 → 126 with low volatility (downward drift)
    flag = []
    for i in range(10):
        c = 130 - 0.4 * i
        flag.append(_candle(c + 0.6, c - 0.6, c))

    out = patterns.bull_flag(pole + flag)
    assert out is not None, "bull flag should be detected"
    assert out["pattern"] == "bull_flag"
    # Breakout level = top of flag consolidation
    assert 128 <= out["key_level"] <= 131, (
        f"key_level should be near top of flag (~130); got {out['key_level']}"
    )
    assert 0 < out["confidence"] <= 1.0


def test_bull_flag_rejects_pure_downtrend():
    from consensus_engine.analysis import patterns
    downtrend = [_candle(100 - i, 99 - i, 99.5 - i) for i in range(20)]
    assert patterns.bull_flag(downtrend) is None


def test_bull_flag_rejects_no_consolidation_after_pole():
    """Strong rise that keeps rising (not flag/consolidation)."""
    from consensus_engine.analysis import patterns
    rip = [_candle(100 + 3*i + 1, 100 + 3*i - 1, 100 + 3*i) for i in range(20)]
    assert patterns.bull_flag(rip) is None


# ---------------------------------------------------------------------------
# double_bottom
# ---------------------------------------------------------------------------

def test_double_bottom_two_similar_lows_with_intervening_peak():
    from consensus_engine.analysis import patterns
    # First low at idx 3, peak at idx 8, second low at idx 13
    candles = [
        _candle(102, 100), _candle(101, 99), _candle(100, 98),
        _candle(99, 90),                                # low #1: 90
        _candle(100, 95), _candle(102, 98),
        _candle(106, 102), _candle(108, 104),
        _candle(110, 105),                              # peak: 110
        _candle(108, 103), _candle(105, 100),
        _candle(102, 96), _candle(99, 92),
        _candle(98, 90.5),                              # low #2: 90.5 (within 1.5%)
        _candle(100, 96), _candle(103, 99),
    ]
    out = patterns.double_bottom(candles)
    assert out is not None
    assert out["pattern"] == "double_bottom"
    # Key level = the neckline (intervening peak)
    assert 108 <= out["key_level"] <= 112


def test_double_bottom_rejects_unrelated_lows():
    """Two lows that are too far apart in price are not a double bottom."""
    from consensus_engine.analysis import patterns
    candles = [
        _candle(102, 100), _candle(99, 80),  # low at 80
        _candle(105, 100), _candle(110, 105),  # peak
        _candle(102, 95), _candle(99, 60),  # low at 60 — way off
    ]
    assert patterns.double_bottom(candles) is None
