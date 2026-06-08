"""Tests for the silent-outage alarm (item #5) folded into chain_health_loop.

A feed (Wolf email, YouTube) that has ingested nothing for too long should
ping Discord once per outage and once on recovery — not every day.
"""
import time

import pytest
from unittest.mock import AsyncMock

from consensus_engine import health


def _patch_feeds(monkeypatch):
    """Use the default two-feed registry (wolf 24h, youtube 36h) via cfg.get."""
    monkeypatch.setattr(
        "consensus_engine.health.cfg.get",
        lambda k, default=None: default,
    )


def _isolate_state(monkeypatch, tmp_path):
    state_file = tmp_path / ".feed_outage_state.json"
    monkeypatch.setattr("consensus_engine.health._FEED_OUTAGE_STATE_FILE", state_file)
    return state_file


def _only_wolf_ingest_age(monkeypatch, hours):
    """Make _latest_feed_ts return a wolf ts `hours` old; youtube None (unarmed)."""
    ts = time.time() - hours * 3600.0

    async def fake_latest(feed_id):
        return ts if feed_id == "wolf" else None

    monkeypatch.setattr(health, "_latest_feed_ts", fake_latest)


@pytest.mark.asyncio
async def test_stale_feed_alerts_once(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch)
    state_file = _isolate_state(monkeypatch, tmp_path)
    _only_wolf_ingest_age(monkeypatch, hours=5 * 24)  # 5 days stale, > 24h
    post = AsyncMock()
    monkeypatch.setattr(health, "_post_to_discord", post)

    await health._check_feed_freshness()

    assert post.await_count == 1
    msg = post.await_args.args[0]
    assert "Wolf email" in msg
    assert "silent" in msg.lower()
    # State recorded so a second day stays quiet.
    assert state_file.exists()
    import json
    assert "wolf" in json.loads(state_file.read_text())


@pytest.mark.asyncio
async def test_fresh_feed_does_not_alert(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch)
    _isolate_state(monkeypatch, tmp_path)
    _only_wolf_ingest_age(monkeypatch, hours=12)  # 12h < 24h threshold
    post = AsyncMock()
    monkeypatch.setattr(health, "_post_to_discord", post)

    await health._check_feed_freshness()

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_stale_day_does_not_realert(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch)
    state_file = _isolate_state(monkeypatch, tmp_path)
    _only_wolf_ingest_age(monkeypatch, hours=5 * 24)
    post = AsyncMock()
    monkeypatch.setattr(health, "_post_to_discord", post)

    # Day 1: alerts once.
    await health._check_feed_freshness()
    assert post.await_count == 1

    # Day 2: still stale, state already set => no new ping.
    await health._check_feed_freshness()
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_recovery_posts_recovered_and_clears_state(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch)
    state_file = _isolate_state(monkeypatch, tmp_path)
    post = AsyncMock()
    monkeypatch.setattr(health, "_post_to_discord", post)

    # Outage: alert once + record state.
    _only_wolf_ingest_age(monkeypatch, hours=5 * 24)
    await health._check_feed_freshness()
    assert post.await_count == 1
    import json
    assert "wolf" in json.loads(state_file.read_text())

    # Recovery: fresh data (12h), was alerted => recovered line + clear state.
    _only_wolf_ingest_age(monkeypatch, hours=12)
    await health._check_feed_freshness()
    assert post.await_count == 2
    recovered_msg = post.await_args.args[0]
    assert "Wolf email" in recovered_msg
    assert "recovered" in recovered_msg.lower()
    assert "wolf" not in json.loads(state_file.read_text())


@pytest.mark.asyncio
async def test_never_ingested_feed_is_not_armed(monkeypatch, tmp_path):
    """A feed whose table is empty (None) must not false-alarm."""
    _patch_feeds(monkeypatch)
    _isolate_state(monkeypatch, tmp_path)

    async def fake_latest(feed_id):
        return None

    monkeypatch.setattr(health, "_latest_feed_ts", fake_latest)
    post = AsyncMock()
    monkeypatch.setattr(health, "_post_to_discord", post)

    await health._check_feed_freshness()

    post.assert_not_awaited()
