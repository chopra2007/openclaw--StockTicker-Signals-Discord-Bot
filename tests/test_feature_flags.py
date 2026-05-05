"""Tests for feature flag helpers (US-001)."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from consensus_engine.utils.feature_flags import (
    read_feature_state,
    flip_feature,
    audit_history,
    KNOWN_FEATURES,
)


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp DB for each test."""
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


async def test_read_feature_state_default_false(monkeypatch):
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: d)
    state = await read_feature_state("regime_classifier")
    assert state is False


async def test_read_feature_state_enabled(monkeypatch):
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: True if k == "features.contradiction_penalty.enabled" else d)
    state = await read_feature_state("contradiction_penalty")
    assert state is True


async def test_flip_feature_writes_audit_row():
    await flip_feature("regime_classifier", True, reason="test enable")
    history = await audit_history(limit=5)
    assert len(history) == 1
    assert history[0]["feature"] == "regime_classifier"
    assert history[0]["new_state"] == 1
    assert history[0]["reason"] == "test enable"


async def test_flip_feature_false_writes_row():
    await flip_feature("analyst_herding", False, reason="test disable")
    history = await audit_history(limit=5)
    assert history[0]["new_state"] == 0


async def test_double_flip_both_rows_present():
    await flip_feature("regime_classifier", True, reason="first")
    await flip_feature("regime_classifier", False, reason="second")
    history = await audit_history(limit=5)
    assert len(history) == 2


async def test_audit_history_limit():
    for i in range(5):
        await flip_feature("regime_classifier", bool(i % 2), reason=f"flip {i}")
    history = await audit_history(limit=3)
    assert len(history) == 3


async def test_audit_history_empty():
    history = await audit_history()
    assert history == []


async def test_audit_history_newest_first():
    await flip_feature("regime_classifier", True, reason="first")
    await flip_feature("sector_confirmation", False, reason="second")
    history = await audit_history(limit=2)
    assert history[0]["feature"] == "sector_confirmation"


async def test_flip_feature_records_flipped_by_system():
    await flip_feature("form4_cluster", True)
    history = await audit_history(limit=1)
    assert history[0]["flipped_by"] == "system"


async def test_known_features_list():
    assert "contradiction_penalty" in KNOWN_FEATURES
    assert "regime_classifier" in KNOWN_FEATURES
    assert "analyst_herding" in KNOWN_FEATURES
    assert len(KNOWN_FEATURES) == 6


async def test_read_feature_state_unknown_returns_false():
    state = await read_feature_state("nonexistent_feature_xyz")
    assert state is False


async def test_flip_feature_prior_state_recorded(monkeypatch):
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: d)
    await flip_feature("analyst_herding", True, reason="enable")
    history = await audit_history(limit=1)
    # prior_state should be 0 since config default is False
    assert history[0]["prior_state"] == 0
