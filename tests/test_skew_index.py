"""Tests for the r8 CBOE ^SKEW standalone reader.

Covers band thresholds, and that the fetch returns None on empty / insufficient /
stale data (never a frozen old value). Network is fully mocked.
"""
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from consensus_engine.analysis import skew_index as sk


def _fresh_df(closes):
    """DataFrame with a recent tz-aware NY DatetimeIndex and given Close values."""
    end = pd.Timestamp.now(tz="America/New_York").normalize()
    idx = pd.date_range(end=end, periods=len(closes), freq="D", tz="America/New_York")
    return pd.DataFrame({"Close": list(closes)}, index=idx)


# ------------------------------------------------------------------------- banding

@pytest.mark.parametrize("value,band", [
    (170.0, "elevated"),
    (145.0, "elevated"),   # boundary: >= 145 is elevated
    (144.99, "normal"),
    (130.0, "normal"),
    (120.0, "normal"),     # boundary: >= 120 is normal
    (119.99, "low"),
    (110.0, "low"),
])
def test_band_for(value, band):
    assert sk.band_for(value) == band


# --------------------------------------------------------------------------- fetch

def test_fetch_returns_value_and_band():
    df = _fresh_df([130.0, 140.0, 145.74])
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        out = sk._fetch_skew_index()
    assert out == {"value": 145.74, "band": "elevated"}


def test_fetch_normal_band():
    df = _fresh_df([128.0, 129.0, 130.5])
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        out = sk._fetch_skew_index()
    assert out["band"] == "normal"
    assert out["value"] == 130.5


def test_fetch_none_on_empty():
    with patch("consensus_engine.utils.prices.fetch_history", return_value=pd.DataFrame()):
        assert sk._fetch_skew_index() is None


def test_fetch_none_on_insufficient_history():
    df = _fresh_df([145.0])  # only one bar
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        assert sk._fetch_skew_index() is None


def test_fetch_none_on_stale_latest():
    # Latest bar is weeks old -> must be rejected (never surface a frozen value).
    end = pd.Timestamp.now(tz="America/New_York").normalize() - timedelta(days=30)
    idx = pd.date_range(end=end, periods=3, freq="D", tz="America/New_York")
    df = pd.DataFrame({"Close": [130.0, 140.0, 150.0]}, index=idx)
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        assert sk._fetch_skew_index() is None


def test_fetch_none_on_nonpositive():
    df = _fresh_df([100.0, 100.0, 0.0])
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        assert sk._fetch_skew_index() is None


def test_fetch_none_on_error():
    with patch("consensus_engine.utils.prices.fetch_history", side_effect=RuntimeError("boom")):
        assert sk._fetch_skew_index() is None


# ------------------------------------------------------------------- async wrapper

@pytest.mark.asyncio
async def test_compute_skew_index_via_executor():
    df = _fresh_df([130.0, 140.0, 148.0])
    with patch("consensus_engine.utils.prices.fetch_history", return_value=df):
        out = await sk.compute_skew_index(None)
    assert out == {"value": 148.0, "band": "elevated"}
