"""F3 — price-trend regime leg added beside the A5 vol z-score in regime.py.

Tests:
  * deterministic synthetic SPY series for each trend_state (green/yellow/red)
  * the trend leg persists to trend_daily and lookup_regime returns it
  * REGRESSION GUARD: the A5 vol-regime output is byte-identical for a fixed
    input whether the trend flag is OFF or ON (trend must NOT change vol math).
"""
import time
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock

from consensus_engine.analysis.regime import (
    RegimeContext,
    lookup_regime,
    compute_and_persist_regime,
    compute_and_persist_trend,
    _compute_regime,
    _compute_trend,
    _COLD_START,
)


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


# ---- synthetic series builders -------------------------------------------

def _rising(n=313, start=100.0, rate=0.003):
    return [start * (1 + rate) ** i for i in range(n)]


def _falling(n=313, start=200.0, rate=0.003):
    return [start * (1 - rate) ** i for i in range(n)]


def _rising_then_flat(rise=250, flat=63, start=100.0, rate=0.003):
    """Rise then a flat tail >= 50 days: close > 200DMA (1 bull) but 50DMA
    slope == 0 and 63d momentum == 0 (0 bull) -> exactly one bullish vote ->
    yellow."""
    closes = [start * (1 + rate) ** i for i in range(rise)]
    peak = closes[-1]
    closes.extend([peak] * flat)
    return closes


# ---- trend_state classification ------------------------------------------

def test_trend_green_strong_uptrend():
    r = _compute_trend(_rising(), "2026-04-27")
    assert r is not None
    assert r["trend_state"] == "green"
    assert r["close"] > r["sma_200"]
    assert r["sma_50_slope"] > 0
    assert r["tsmom_3m"] > 0


def test_trend_red_strong_downtrend():
    r = _compute_trend(_falling(), "2026-04-27")
    assert r is not None
    assert r["trend_state"] == "red"
    assert r["close"] < r["sma_200"]
    assert r["sma_50_slope"] < 0
    assert r["tsmom_3m"] < 0


def test_trend_yellow_mixed():
    r = _compute_trend(_rising_then_flat(), "2026-04-27")
    assert r is not None
    assert r["trend_state"] == "yellow"
    # exactly the "above 200DMA, but momentum/slope dead" mix
    assert r["close"] > r["sma_200"]
    assert r["sma_50_slope"] == pytest.approx(0.0, abs=1e-9)
    assert r["tsmom_3m"] == pytest.approx(0.0, abs=1e-9)


def test_trend_insufficient_data_returns_none():
    assert _compute_trend([100.0] * 100, "2026-04-27") is None


def test_trend_dist_z_present_and_finite():
    r = _compute_trend(_rising(), "2026-04-27")
    assert r is not None
    assert isinstance(r["dist_200_z"], float)
    assert r["dist_200_z"] == r["dist_200_z"]  # not NaN


# ---- persistence + lookup ------------------------------------------------

async def test_compute_and_persist_trend_idempotent():
    from consensus_engine import db
    closes = _rising()
    with patch("consensus_engine.analysis.regime._fetch_trend_closes",
               new=AsyncMock(return_value=closes)):
        await compute_and_persist_trend(date(2026, 4, 27))
        await compute_and_persist_trend(date(2026, 4, 27))
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM trend_daily WHERE date_utc='2026-04-27'")
    row = await cur.fetchone()
    assert row["cnt"] == 1
    cur = await conn.execute(
        "SELECT trend_state FROM trend_daily WHERE date_utc='2026-04-27'")
    assert (await cur.fetchone())["trend_state"] == "green"


async def test_lookup_regime_returns_trend_when_enabled():
    """trend flag ON + a trend_daily row -> RegimeContext carries trend fields."""
    from consensus_engine import db
    closes = _rising()
    with patch("consensus_engine.analysis.regime._fetch_trend_closes",
               new=AsyncMock(return_value=closes)):
        await compute_and_persist_trend(date(2026, 4, 27))

    def _get(k, d=None):
        if k == "features.trend_regime.enabled":
            return True
        if k == "features.regime_classifier.enabled":
            return False
        return d

    with patch("consensus_engine.config.get", side_effect=_get):
        ctx = await lookup_regime()
    assert ctx.trend_state == "green"
    assert ctx.trend_cold_start is False
    assert ctx.sma_200 is not None


async def test_lookup_regime_trend_off_no_trend_fields():
    """trend flag OFF -> trend fields stay None even if a row exists."""
    closes = _rising()
    with patch("consensus_engine.analysis.regime._fetch_trend_closes",
               new=AsyncMock(return_value=closes)):
        await compute_and_persist_trend(date(2026, 4, 27))

    def _get(k, d=None):
        if k == "features.regime_classifier.enabled":
            return False
        return d  # trend_regime.enabled -> False

    with patch("consensus_engine.config.get", side_effect=_get):
        ctx = await lookup_regime()
    assert ctx.trend_state is None
    assert ctx.trend_cold_start is True


async def test_lookup_regime_trend_stale_row_cold_start():
    """A trend_daily row older than 7d -> trend cold-start (no fields)."""
    from consensus_engine import db
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO trend_daily
           (date_utc, index_symbol, close, sma_200, sma_50, sma_50_slope,
            tsmom_3m, dist_200_z, trend_state, computed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("2026-01-01", "SPY", 200.0, 180.0, 195.0, 0.01, 0.05, 0.5, "green",
         time.time() - 8 * 86400),
    )
    await conn.commit()

    def _get(k, d=None):
        if k == "features.trend_regime.enabled":
            return True
        if k == "features.regime_classifier.enabled":
            return False
        return d

    with patch("consensus_engine.config.get", side_effect=_get):
        ctx = await lookup_regime()
    assert ctx.trend_state is None
    assert ctx.trend_cold_start is True


# ---- A5 REGRESSION GUARD --------------------------------------------------

def test_a5_compute_regime_unchanged_for_fixed_input():
    """_compute_regime output is byte-identical to the frozen A5 snapshot."""
    closes = [100.0 * (1 + 0.001 * i) for i in range(260)]
    r = _compute_regime(closes, "2026-04-27")
    assert r is not None
    # frozen vol-regime fields — these must not drift when F3 is added.
    assert r["regime_label"] == "normal"
    assert r["date_utc"] == "2026-04-27"
    # numeric snapshot (low-vol rising ramp)
    assert r["z_score_raw"] == pytest.approx(-0.9353626513123796, rel=1e-9)
    assert r["z_score_smoothed"] == pytest.approx(-0.9353626513123796, rel=1e-9)
    assert r["realized_vol_20d"] == pytest.approx(5.868019787218245e-05, rel=1e-9)


async def test_a5_vol_fields_identical_regardless_of_trend_flag():
    """lookup_regime's vol fields are identical whether trend is OFF or ON."""
    from consensus_engine import db
    conn = await db.get_db()
    # seed one regime_daily row + flip cold_start_min_days to 1
    await conn.execute(
        """INSERT INTO regime_daily
           (date_utc, realized_vol_20d, mean_252d, std_252d, z_score_raw,
            z_score_smoothed, regime_label, computed_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("2026-04-27", 0.15, 0.001, 0.001, 0.7, 0.7, "elevated", time.time()),
    )
    await conn.commit()

    def _base(k, d=None):
        if k == "features.regime_classifier.enabled":
            return True
        if k == "features.regime_classifier.cold_start_min_days":
            return 1
        if k == "features.regime_classifier.regime_shifts":
            return {"calm": -5, "elevated": 5, "panic": 10}
        return d

    def _trend_off(k, d=None):
        if k == "features.trend_regime.enabled":
            return False
        return _base(k, d)

    def _trend_on(k, d=None):
        if k == "features.trend_regime.enabled":
            return True
        return _base(k, d)

    with patch("consensus_engine.config.get", side_effect=_trend_off):
        off = await lookup_regime()
    with patch("consensus_engine.config.get", side_effect=_trend_on):
        on = await lookup_regime()

    # vol fields byte-identical
    assert (off.label, off.z_score, off.threshold_shift,
            off.cold_start, off.as_of_date) == \
           (on.label, on.z_score, on.threshold_shift,
            on.cold_start, on.as_of_date)
    assert off.label == "elevated"
    assert off.threshold_shift == 5
    # trend OFF -> no trend fields; ON path is allowed to add them
    assert off.trend_state is None
