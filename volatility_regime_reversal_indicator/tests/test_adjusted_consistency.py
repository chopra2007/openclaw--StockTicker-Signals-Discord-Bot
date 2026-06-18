"""Guard the adjusted-OHLCV contract by reading the populated store.

A raw/adjusted MIX (e.g. an adjusted close glued to a raw open) breaks intrabar
OHLC ordering, so these ordering checks are the "open and close share the same
adjustment factor" guard. Tests skip on a clean checkout (empty store).
"""
from __future__ import annotations

import pytest

from src.config import get
from src.data import store


def _etfs():
    return list(get("data.etfs", []))


@pytest.mark.skipif(not store.series_exists("SPY"), reason="store not populated; run `python -m src.run_update`")
@pytest.mark.parametrize("name", _etfs())
def test_ohlc_ordering(name):
    """high >= max(open, close) and low <= min(open, close) on every non-NaN row."""
    if not store.series_exists(name):
        pytest.skip(f"{name} not in store")
    df = store.read_series(name)
    for col in ("open", "high", "low", "close"):
        assert col in df.columns, f"{name} missing column {col}"
    sub = df[["open", "high", "low", "close"]].dropna()
    assert len(sub) > 0, f"{name} has no complete OHLC rows"

    hi_ok = sub["high"] >= sub[["open", "close"]].max(axis=1) - 1e-6
    lo_ok = sub["low"] <= sub[["open", "close"]].min(axis=1) + 1e-6
    assert hi_ok.all(), f"{name}: high < max(open, close) on {(~hi_ok).sum()} rows (raw/adjusted mix?)"
    assert lo_ok.all(), f"{name}: low > min(open, close) on {(~lo_ok).sum()} rows (raw/adjusted mix?)"


@pytest.mark.skipif(not store.series_exists("SPY"), reason="store not populated; run `python -m src.run_update`")
def test_spy_provenance():
    prov = store.provenance("SPY")
    assert prov.get("adjusted") is True
    assert prov.get("source") == "yfinance"


@pytest.mark.skipif(not store.series_exists("SPY"), reason="store not populated; run `python -m src.run_update`")
def test_deep_history_present():
    assert store.provenance("SPY").get("rows", 0) > 5000, "SPY should have deep daily history (>5000 rows)"


@pytest.mark.skipif(not store.series_exists("BAA10Y"), reason="store not populated; run `python -m src.run_update`")
def test_baa10y_history_present():
    assert store.provenance("BAA10Y").get("rows", 0) > 8000, "BAA10Y should have deep daily history (>8000 rows)"
