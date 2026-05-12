"""Tests for analysis/calibration.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Identity fallback tests
# ---------------------------------------------------------------------------

def test_calibrate_identity_when_no_model(tmp_path, monkeypatch):
    """When no model exists, calibrate() returns score/100."""
    import consensus_engine.analysis.calibration as cal
    monkeypatch.setattr(cal, "_models", {})
    monkeypatch.setattr(cal, "MODEL_PATH", tmp_path / "calibration_model.pkl")

    assert cal.calibrate(75.0, "1h") == pytest.approx(0.75)
    assert cal.calibrate(50.0, "24h") == pytest.approx(0.50)
    assert cal.calibrate(0.0) == pytest.approx(0.0)
    assert cal.calibrate(100.0) == pytest.approx(1.0)


def test_calibrate_identity_clamps(tmp_path, monkeypatch):
    """Identity fallback clamps values outside [0, 1]."""
    import consensus_engine.analysis.calibration as cal
    monkeypatch.setattr(cal, "_models", {})
    monkeypatch.setattr(cal, "MODEL_PATH", tmp_path / "calibration_model.pkl")

    assert cal.calibrate(110.0) == pytest.approx(1.0)
    assert cal.calibrate(-10.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Insufficient samples — model unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrain_skips_when_insufficient_samples(monkeypatch):
    """retrain() returns sample count and does not add a model when rows < MIN_SAMPLES."""
    import consensus_engine.analysis.calibration as cal

    # Only 10 rows — below MIN_SAMPLES=50
    mock_rows = [
        {"final_score": 70.0, "outcome_price_at_alert": 100.0, "outcome_price_1h": 105.0}
        for _ in range(10)
    ]
    _setup_mock_db(monkeypatch, mock_rows)

    monkeypatch.setattr(cal, "_models", {})
    count = await cal.retrain("1h")

    assert count == 10
    # No model should have been inserted
    assert cal._models.get("1h") is None


# ---------------------------------------------------------------------------
# Monotonicity preservation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calibrate_monotonicity_after_retrain(monkeypatch):
    """After retraining, calibrate() is monotone: higher score → higher probability."""
    import consensus_engine.analysis.calibration as cal

    rows = _make_labeled_rows(80)
    _setup_mock_db(monkeypatch, rows)

    monkeypatch.setattr(cal, "_models", {})

    with patch.object(cal, "_save_models"):
        await cal.retrain("1h")

    c20 = cal.calibrate(20.0, "1h")
    c50 = cal.calibrate(50.0, "1h")
    c80 = cal.calibrate(80.0, "1h")

    assert c20 <= c50, f"monotonicity violated: c20={c20:.3f} > c50={c50:.3f}"
    assert c50 <= c80, f"monotonicity violated: c50={c50:.3f} > c80={c80:.3f}"


@pytest.mark.asyncio
async def test_calibrate_output_in_unit_interval(monkeypatch):
    """Calibrated output is always in [0, 1]."""
    import consensus_engine.analysis.calibration as cal

    rows = _make_labeled_rows(80)
    _setup_mock_db(monkeypatch, rows)

    monkeypatch.setattr(cal, "_models", {})
    with patch.object(cal, "_save_models"):
        await cal.retrain("1h")

    for score in (0.0, 10.0, 50.0, 90.0, 100.0):
        result = cal.calibrate(score, "1h")
        assert 0.0 <= result <= 1.0, f"out-of-range result {result} for score={score}"


# ---------------------------------------------------------------------------
# 24h horizon
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrain_24h(monkeypatch):
    """retrain('24h') trains a separate model using outcome_price_24h column."""
    import consensus_engine.analysis.calibration as cal

    rows = _make_labeled_rows(60, price_col="outcome_price_24h")
    _setup_mock_db(monkeypatch, rows, price_col="outcome_price_24h")

    monkeypatch.setattr(cal, "_models", {})
    with patch.object(cal, "_save_models"):
        count = await cal.retrain("24h")

    assert count == 60
    assert cal._models.get("24h") is not None


# ---------------------------------------------------------------------------
# retrain_all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrain_all_returns_both_horizons(monkeypatch):
    """retrain_all() returns a dict with both 1h and 24h sample counts."""
    import consensus_engine.analysis.calibration as cal

    monkeypatch.setattr(cal, "_models", {})

    async def _fake_retrain(h):
        return {"1h": 60, "24h": 55}.get(h, 0)

    with patch.object(cal, "retrain", side_effect=_fake_retrain):
        result = await cal.retrain_all()

    assert result == {"1h": 60, "24h": 55}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_labeled_rows(n: int, price_col: str = "outcome_price_1h") -> list[dict]:
    """Create n labeled rows where scores 0-49 go down, 50-100 go up."""
    rows = []
    for i in range(n):
        score = (i / (n - 1)) * 100
        outcome = 105.0 if score >= 50 else 95.0
        rows.append({
            "final_score": score,
            "outcome_price_at_alert": 100.0,
            price_col: outcome,
        })
    return rows


def _setup_mock_db(monkeypatch, rows: list[dict], price_col: str = "outcome_price_1h"):
    """Patch db.get_db() to return a mock conn that returns given rows."""
    import consensus_engine.analysis.calibration as cal

    mock_cursor = MagicMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.get_db = AsyncMock(return_value=mock_conn)
    monkeypatch.setattr(cal, "db", mock_db)
