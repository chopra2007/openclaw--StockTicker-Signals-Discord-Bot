"""Tests for A1 contradiction-penalty (US-003)."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch


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


def test_below_threshold_no_op():
    """contradiction_index below threshold → apply_penalty=False."""
    from consensus_engine.analysis.contradiction import evaluate_contradiction
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_contradiction(0.3, now)  # threshold default is 0.5
    assert verdict.apply_penalty is False
    assert verdict.reason == "below_threshold"


def test_above_threshold_downgrade():
    """contradiction_index >= threshold + feature enabled → apply_penalty=True."""
    from consensus_engine.analysis.contradiction import evaluate_contradiction, _YAML_PATH
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    # Patch yaml to return empty (no macro events)
    with patch("consensus_engine.analysis.contradiction._load_macro_events", return_value={}):
        verdict = evaluate_contradiction(0.6, now)
    assert verdict.apply_penalty is True
    assert verdict.reason == "applied"


def test_macro_blackout_skips_penalty():
    """A1 should NOT fire during macro blackout window."""
    from consensus_engine.analysis.contradiction import evaluate_contradiction
    now = datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc)  # 14:00 ET = 18:00 UTC
    # 2026-05-07T14:00-04:00 is in the yaml
    verdict = evaluate_contradiction(0.7, now)
    # If in blackout window, penalty is skipped
    assert verdict.apply_penalty is False
    assert verdict.reason in ("macro_blackout", "below_threshold", "disabled")


def test_disabled_flag_no_op(monkeypatch):
    """Feature disabled → apply_penalty=False with reason='disabled'."""
    from consensus_engine import config as cfg
    from consensus_engine.analysis.contradiction import evaluate_contradiction
    monkeypatch.setattr(cfg, "get", lambda k, d=None: False if k == "features.contradiction_penalty.enabled" else d)
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_contradiction(0.9, now)
    assert verdict.apply_penalty is False
    assert verdict.reason == "disabled"


def test_yaml_missing_graceful(tmp_path, monkeypatch):
    """Missing yaml → no blackout, A1 still evaluates on threshold."""
    import consensus_engine.analysis.contradiction as mod
    monkeypatch.setattr(mod, "_YAML_PATH", tmp_path / "nonexistent.yaml")
    monkeypatch.setattr(mod, "_YAML_CACHE", None)
    monkeypatch.setattr(mod, "_YAML_LOADED_AT", 0.0)
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    verdict = mod.evaluate_contradiction(0.7, now)
    # Missing file: no blackout fired, A1 evaluates normally
    assert verdict.reason in ("applied", "below_threshold", "disabled")


def test_yaml_stale_90d_warning(tmp_path, monkeypatch, caplog):
    """yaml older than 90 days → log warning."""
    import time
    import yaml
    import consensus_engine.analysis.contradiction as mod
    stale_path = tmp_path / "macro_events.yaml"
    stale_path.write_text("schema_version: 1\n")
    old_mtime = time.time() - (91 * 86400)
    import os
    os.utime(stale_path, (old_mtime, old_mtime))
    monkeypatch.setattr(mod, "_YAML_PATH", stale_path)
    monkeypatch.setattr(mod, "_YAML_CACHE", None)
    monkeypatch.setattr(mod, "_YAML_LOADED_AT", 0.0)
    import logging
    with caplog.at_level(logging.WARNING, logger="consensus_engine.analysis.contradiction"):
        mod._load_macro_events()
    assert any("overdue" in r.message or "days old" in r.message for r in caplog.records)
