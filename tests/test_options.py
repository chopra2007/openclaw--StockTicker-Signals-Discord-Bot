"""Tests for the options flow scanner."""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


def _make_options_chain(calls_data, puts_data):
    """Build a mock yfinance option_chain result."""
    calls = pd.DataFrame(calls_data)
    puts = pd.DataFrame(puts_data)
    chain = MagicMock()
    chain.calls = calls
    chain.puts = puts
    return chain


def test_detect_unusual_calls():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "NVDA240119C00500000", "volume": 5000, "openInterest": 1000,
             "impliedVolatility": 0.45, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "NVDA240119P00500000", "volume": 100, "openInterest": 500,
             "impliedVolatility": 0.40, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.unusual_calls is True
    assert result.unusual_puts is False
    assert result.max_call_ratio == pytest.approx(5.0)


def test_detect_no_unusual_activity():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "NVDA240119C00500000", "volume": 50, "openInterest": 1000,
             "impliedVolatility": 0.30, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "NVDA240119P00500000", "volume": 80, "openInterest": 2000,
             "impliedVolatility": 0.28, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.unusual_calls is False
    assert result.unusual_puts is False


def test_put_call_ratio():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "X", "volume": 1000, "openInterest": 5000,
             "impliedVolatility": 0.3, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "Y", "volume": 3000, "openInterest": 5000,
             "impliedVolatility": 0.3, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.put_call_ratio == pytest.approx(3.0)


def test_options_result_has_unusual_activity_property():
    from consensus_engine.models import OptionsResult
    r = OptionsResult(ticker="NVDA", unusual_calls=True)
    assert r.has_unusual_activity is True
    r2 = OptionsResult(ticker="NVDA")
    assert r2.has_unusual_activity is False
