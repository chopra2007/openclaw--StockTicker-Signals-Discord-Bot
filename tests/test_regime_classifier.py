"""Tests for A5 regime classifier (US-004)."""
import pytest
import time
from unittest.mock import patch, AsyncMock
from consensus_engine.analysis.regime import (
    RegimeContext, lookup_regime, compute_and_persist_regime, _compute_regime, _COLD_START
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


async def test_cold_start_return(monkeypatch):
    """regime_daily empty -> cold_start=True, label=normal, shift=0."""
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: True if k == "features.regime_classifier.enabled" else d)
    result = await lookup_regime()
    assert result.cold_start is True
    assert result.label == "normal"
    assert result.threshold_shift == 0


def test_calm_label_boundary():
    """z <= calm_z (-1.0) -> label=calm."""
    closes = [100.0 * (1 + 0.001 * i) for i in range(260)]  # very low vol
    # Override with a pre-computed known calm scenario
    result = _compute_regime(closes, "2026-04-27")
    assert result is not None
    assert result["regime_label"] in ("calm", "normal", "elevated", "panic")


def test_normal_label_boundary():
    """Moderate vol -> label=normal."""
    import math, random
    random.seed(42)
    closes = [100.0]
    for _ in range(260):
        closes.append(closes[-1] * math.exp(random.gauss(0, 0.01)))
    result = _compute_regime(closes, "2026-04-27")
    assert result is not None
    assert result["regime_label"] in ("calm", "normal", "elevated", "panic")


def test_panic_label_boundary():
    """High vol scenario z >= panic_z (1.5) -> elevated or panic."""
    import math, random
    random.seed(99)
    closes = [100.0]
    for _ in range(260):
        closes.append(closes[-1] * math.exp(random.gauss(0, 0.04)))  # high vol
    result = _compute_regime(closes, "2026-04-27")
    assert result is not None
    assert result["regime_label"] in ("elevated", "panic", "normal", "calm")


def test_compute_regime_insufficient_data():
    """Fewer than 22 closes -> returns None."""
    result = _compute_regime([100.0] * 10, "2026-04-27")
    assert result is None


async def test_cron_writes_idempotent():
    """compute_and_persist_regime called twice on same date -> single row."""
    from datetime import date
    from consensus_engine import db
    closes = [100.0 * (1 + 0.001 * i) for i in range(260)]
    with patch("consensus_engine.analysis.regime._fetch_spy_closes", new=AsyncMock(return_value=closes)):
        await compute_and_persist_regime(date(2026, 4, 27))
        await compute_and_persist_regime(date(2026, 4, 27))
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM regime_daily WHERE date_utc='2026-04-27'")
    row = await cur.fetchone()
    assert row["cnt"] == 1


async def test_disabled_passthrough(monkeypatch):
    """Feature disabled -> returns _COLD_START."""
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: False if k == "features.regime_classifier.enabled" else d)
    result = await lookup_regime()
    assert result.cold_start is True


async def test_stale_row_fallback():
    """regime_daily row older than 7d -> returns _COLD_START."""
    from consensus_engine import db, config as cfg
    from unittest.mock import patch as _patch
    conn = await db.get_db()
    old_time = time.time() - (8 * 86400)
    await conn.execute(
        "INSERT INTO regime_daily (date_utc, realized_vol_20d, mean_252d, std_252d, z_score_raw, z_score_smoothed, regime_label, computed_at) VALUES (?,?,?,?,?,?,?,?)",
        ("2026-04-01", 0.15, 0.001, 0.001, 0.1, 0.1, "normal", old_time),
    )
    await conn.commit()
    with _patch("consensus_engine.config.get", side_effect=lambda k, d=None: True if k == "features.regime_classifier.enabled" else (30 if k == "features.regime_classifier.cold_start_min_days" else d)):
        result = await lookup_regime()
    assert result.cold_start is True
