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


@pytest.mark.asyncio
async def test_check_unusual_options_empty_expirations():
    """Returns None cleanly when ticker has no listed options."""
    from consensus_engine.scanners.options import check_unusual_options
    from unittest.mock import MagicMock, patch
    import concurrent.futures

    mock_ticker = MagicMock()
    mock_ticker.options = []  # no expirations

    with patch("yfinance.Ticker", return_value=mock_ticker):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        result = await check_unusual_options("NOOPT", executor)
        assert result is None
        executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_check_unusual_options_stamps_ticker():
    """Result has ticker stamped onto it by the caller."""
    from consensus_engine.scanners.options import check_unusual_options
    from unittest.mock import MagicMock, patch
    import concurrent.futures
    import pandas as pd

    mock_chain = MagicMock()
    mock_chain.calls = pd.DataFrame([
        {"contractSymbol": "NVDA240119C00500000", "volume": 5000,
         "openInterest": 1000, "impliedVolatility": 0.45, "inTheMoney": False},
    ])
    mock_chain.puts = pd.DataFrame([
        {"contractSymbol": "NVDA240119P00500000", "volume": 50,
         "openInterest": 500, "impliedVolatility": 0.40, "inTheMoney": False},
    ])

    mock_ticker = MagicMock()
    mock_ticker.options = ["2024-01-19"]
    mock_ticker.option_chain.return_value = mock_chain

    with patch("yfinance.Ticker", return_value=mock_ticker):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        result = await check_unusual_options("NVDA", executor)
        assert result is not None
        assert result.ticker == "NVDA"
        assert result.unusual_calls is True
        executor.shutdown(wait=False)


@pytest.mark.asyncio
async def test_check_unusual_options_yfinance_error_returns_none():
    """Returns None when yfinance raises inside the executor."""
    from consensus_engine.scanners.options import check_unusual_options
    from unittest.mock import patch
    import concurrent.futures

    def _raise():
        raise ValueError("yfinance internal error")

    with patch("yfinance.Ticker", side_effect=ValueError("yfinance internal error")):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        result = await check_unusual_options("FAIL", executor)
        assert result is None
        executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------

from consensus_engine.scanners.options import _is_sweep


def test_is_sweep_high_volume_ratio():
    assert _is_sweep(vol=600, oi=100, min_ratio=5.0, min_notional=0) is True


def test_is_sweep_below_threshold():
    assert _is_sweep(vol=200, oi=100, min_ratio=5.0, min_notional=0) is False


def test_is_sweep_zero_oi():
    assert _is_sweep(vol=1000, oi=0, min_ratio=5.0, min_notional=0) is False
