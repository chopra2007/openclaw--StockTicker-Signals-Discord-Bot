"""Tests for Q1: calibration shadow mode + Discord honesty fix.

RED at Commit A — turns GREEN when Commit F lands.

Covers:
- calibrate() identity when no model
- calibrate() uses loaded model when present
- retrain() returns n < MIN_SAMPLES and leaves _models unchanged
- log_shadow_prediction() writes {shadow_prob} into decision_snapshots.feature_vector_json
- log_shadow_prediction() must NOT call _save_models
- _calibrated_section() returns 'score/100 (uncalibrated)' when shadow_mode enabled + no model
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import consensus_engine.analysis.calibration as cal
from consensus_engine import config as cfg


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    from consensus_engine import db
    db_path = str(tmp_path / "test.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# Already-green: identity + model-delegate (baseline unchanged by plan)
# ---------------------------------------------------------------------------

def test_calibrate_returns_identity_at_score_30_when_no_model(monkeypatch):
    """calibrate(30, '1h') returns 0.30 (score/100) when _models is empty."""
    monkeypatch.setattr(cal, "_models", {})
    monkeypatch.setattr(cal, "_loaded_at", float("inf"))
    assert cal.calibrate(30.0, "1h") == pytest.approx(0.30)


def test_calibrate_uses_loaded_model_predict_when_model_exists(monkeypatch):
    """calibrate() delegates to the model when one is loaded for the horizon."""
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.65]
    monkeypatch.setattr(cal, "_models", {"1h": mock_model})
    monkeypatch.setattr(cal, "_loaded_at", float("inf"))
    result = cal.calibrate(30.0, "1h")
    assert result == pytest.approx(0.65)
    mock_model.predict.assert_called_once()


async def test_retrain_returns_n_below_min_and_leaves_models_unchanged(monkeypatch):
    """retrain('1h') returns n<MIN_SAMPLES and leaves _models unchanged."""
    mock_rows = [
        {"final_score": 70.0, "outcome_price_at_alert": 100.0, "outcome_price_1h": 105.0}
        for _ in range(10)
    ]
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = mock_rows
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_cursor

    monkeypatch.setattr(cal, "_models", {})
    with patch("consensus_engine.analysis.calibration.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=mock_conn)
        count = await cal.retrain("1h")

    assert count == 10
    assert cal._models.get("1h") is None


# ---------------------------------------------------------------------------
# RED: log_shadow_prediction (function absent until Commit F)
# ---------------------------------------------------------------------------

async def test_log_shadow_prediction_writes_shadow_prob_into_feature_vector_json(test_db):
    """log_shadow_prediction(snapshot_id, score, calibrated_prob) writes
    {'shadow_prob': <float>} into decision_snapshots.feature_vector_json.

    RED until Commit F adds log_shadow_prediction() to calibration.py.
    """
    from consensus_engine import db

    await test_db.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, sources_json, recorded_at)
           VALUES ('NVDA', 'STRONG_ALERT', 75.0, '{}', unixepoch())"""
    )
    await test_db.commit()
    cursor = await test_db.execute(
        "SELECT id FROM decision_snapshots ORDER BY id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    snapshot_id = row["id"]

    # Fails here (assertion) until Commit F adds the function.
    log_shadow = getattr(cal, "log_shadow_prediction", None)
    assert log_shadow is not None, (
        "log_shadow_prediction not yet in calibration.py — RED until Commit F"
    )

    await log_shadow(snapshot_id, score=75.0, calibrated_prob=0.72)

    cursor = await test_db.execute(
        "SELECT feature_vector_json FROM decision_snapshots WHERE id = ?",
        (snapshot_id,),
    )
    row = await cursor.fetchone()
    assert row["feature_vector_json"] is not None
    data = json.loads(row["feature_vector_json"])
    assert "shadow_prob" in data, f"key 'shadow_prob' missing from {data!r}"
    assert abs(data["shadow_prob"] - 0.72) < 1e-6


async def test_log_shadow_prediction_does_not_call_save_models(test_db):
    """log_shadow_prediction must NOT persist a model — shadow only.

    RED until Commit F adds log_shadow_prediction() to calibration.py.
    """
    from consensus_engine import db

    await test_db.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, sources_json, recorded_at)
           VALUES ('AAPL', 'WATCHLIST', 60.0, '{}', unixepoch())"""
    )
    await test_db.commit()
    cursor = await test_db.execute(
        "SELECT id FROM decision_snapshots ORDER BY id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    snapshot_id = row["id"]

    log_shadow = getattr(cal, "log_shadow_prediction", None)
    assert log_shadow is not None, (
        "log_shadow_prediction not yet in calibration.py — RED until Commit F"
    )

    with patch.object(cal, "_save_models") as mock_save:
        await log_shadow(snapshot_id, score=60.0, calibrated_prob=0.55)
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# RED: Discord honesty fix (label wrong until Commit F)
# ---------------------------------------------------------------------------

def test_calibrated_section_returns_uncalibrated_label_when_shadow_mode_and_no_model(
    monkeypatch,
):
    """_calibrated_section() includes 'score/100 (uncalibrated)' when
    calibration.shadow_mode.enabled=true AND no trained model is loaded.

    RED until Commit F relabels the Discord field.
    """
    from consensus_engine.alerts.discord import _calibrated_section

    monkeypatch.setattr(cal, "_models", {})
    monkeypatch.setattr(cal, "_loaded_at", float("inf"))

    cfg._config.setdefault("calibration", {}).setdefault("shadow_mode", {})["enabled"] = True

    mock_xref = MagicMock()
    mock_xref.final_score = 30.0

    lines = _calibrated_section(mock_xref)
    combined = " ".join(lines)
    assert "score/100 (uncalibrated)" in combined, (
        f"Expected 'score/100 (uncalibrated)' in Discord field but got: {combined!r} — "
        "RED until Commit F relabels the lying 'Calibrated conf' field"
    )
