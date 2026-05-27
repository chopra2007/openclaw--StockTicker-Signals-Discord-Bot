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


@pytest.fixture(autouse=True)
def _reset_http_singleton():
    """Reset the shared aiohttp session globals between tests.

    Some tests patch `aiohttp.ClientSession` globally to intercept the
    singleton creation inside `consensus_engine.utils.http.get_session`. When
    the patch is reverted, the polluted `_session` global persists into the
    next test, causing AttributeError on `_session.closed` checks. Reset both
    `_session` and `_lock` so every test starts from a clean slate.
    """
    yield
    from consensus_engine.utils import http as _http
    _http._session = None
    _http._lock = None


@pytest.fixture(autouse=True)
def _flush_narrator_cache():
    """Pass 5 Step 11 added a module-level synthesis cache to narrator.py
    (see _synthesis_cache). Without this, cached narratives leak between
    tests and break expectations like "synthesize returns empty on failure"."""
    from consensus_engine.alerts.all_command import narrator as _narrator
    _narrator.flush_synthesis_cache()
    yield
    _narrator.flush_synthesis_cache()
