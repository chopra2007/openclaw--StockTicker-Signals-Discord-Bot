"""Tests for consensus_engine.utils.obs_log pipeline observability helper."""
import json
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from consensus_engine.utils.obs_log import obs_log, _LOG_PATH


def test_obs_log_writes_valid_json(tmp_path, monkeypatch):
    """obs_log appends a valid JSON line to the log file."""
    log_file = tmp_path / "pipeline-obs.jsonl"
    monkeypatch.setattr(
        "consensus_engine.utils.obs_log._LOG_PATH", log_file
    )
    record = {"ts": 1234567890.0, "event": "test_event", "ticker": "AAPL"}
    obs_log(record)

    assert log_file.exists()
    line = log_file.read_text().strip()
    parsed = json.loads(line)
    assert parsed["event"] == "test_event"
    assert parsed["ticker"] == "AAPL"
    assert parsed["ts"] == 1234567890.0


def test_obs_log_ignores_oserror(monkeypatch):
    """obs_log silently swallows OSError and does not raise."""
    # Patch open to raise OSError; also patch mkdir so it doesn't fail first.
    monkeypatch.setattr(
        "consensus_engine.utils.obs_log._LOG_PATH",
        Path("/nonexistent/path/pipeline-obs.jsonl"),
    )
    with patch("builtins.open", side_effect=OSError("disk full")):
        # Should not raise
        obs_log({"ts": 0.0, "event": "error_test"})
