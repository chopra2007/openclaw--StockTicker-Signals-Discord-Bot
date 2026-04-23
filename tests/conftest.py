"""Shared pytest fixtures for the consensus_engine test suite."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def no_discord_alerts():
    """Prevent any test from firing real Discord alerts."""
    with patch(
        "consensus_engine.scanners.youtube._send_youtube_alert",
        new=AsyncMock(),
    ):
        yield
