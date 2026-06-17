"""Tests for A2: Analyst herding detector (schema v12).

8 scenarios per spec §8.2:
  (a) <3 analysts → no fire (below_threshold)
  (b) trust floor fails → no fire (trust_floor_failed)
  (c) panic regime requires 4 members → no fire with 3
  (d) consumed_by_cluster_id written on member rows on fire
  (e) swarm-edit — cluster result has fired=True and cluster_id set
  (f) data-derived correlation discount reduces effective_size
  (g) window_minutes param honored (events outside window not counted)
  (h) members_cap=20 limits stored members
"""
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.analysis.herding import (
    ClusterMember,
    ClusterResult,
    detect_cluster,
    refresh_correlation_matrix,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


async def _insert_signal_event(ticker: str, analyst: str, recorded_at: float) -> int:
    """Helper: insert a twitter signal_event row, return its id."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    cur = await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at)
           VALUES ('twitter', ?, ?, 'long', 0.5, ?)""",
        (analyst, ticker, recorded_at),
    )
    await conn.commit()
    return cur.lastrowid


async def _insert_performance(analyst: str, accuracy: float) -> None:
    """Helper: insert source_performance row."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO source_performance
           (entity_id, horizon, rolling_accuracy, sample_count, updated_at)
           VALUES (?, 'short', ?, 10, ?)""",
        (analyst, accuracy, time.time()),
    )
    await conn.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cfg_enabled(**overrides):
    """Return a cfg.get patch that enables analyst_herding and applies overrides."""
    defaults = {
        "features.analyst_herding.enabled": True,
        "features.analyst_herding.window_minutes": 30,
        "features.analyst_herding.min_cluster_size": 3,
        "features.analyst_herding.min_trusted_accuracy": 0.5,
        "features.analyst_herding.panic_min_cluster_size": 4,
        "features.analyst_herding.members_cap": 20,
        "features.regime_classifier.enabled": False,
    }
    defaults.update(overrides)

    def _get(key, default=None):
        return defaults.get(key, default)

    return patch("consensus_engine.analysis.herding.cfg.get", side_effect=_get)


# ---------------------------------------------------------------------------
# (a) <3 analysts → below_threshold
# ---------------------------------------------------------------------------

async def test_below_threshold_no_fire():
    """Fewer than min_cluster_size unique analysts → below_threshold."""
    now = _now()
    ts = now.timestamp()
    await _insert_signal_event("NVDA", "analyst_a", ts - 100)
    await _insert_signal_event("NVDA", "analyst_b", ts - 50)
    # Only 2 analysts, need 3

    with _cfg_enabled():
        result = await detect_cluster("NVDA", new_event_id=0, now_utc=now)

    assert result.fired is False
    assert result.cluster_id is None
    assert result.reason == "below_threshold"


# ---------------------------------------------------------------------------
# (b) trust floor fails → trust_floor_failed
# ---------------------------------------------------------------------------

async def test_trust_floor_failed():
    """3 analysts present but <2 with rolling_accuracy >= min_trusted_accuracy."""
    now = _now()
    ts = now.timestamp()
    for i, name in enumerate(["alpha", "beta", "gamma"]):
        await _insert_signal_event("AAPL", name, ts - (i + 1) * 60)
        # All have accuracy 0.0 (below 0.5 floor) — no source_performance row
        # means rolling_accuracy defaults to 0.0

    # Trust floor is now opt-in (I7); enable it for this test.
    with _cfg_enabled(**{"features.analyst_herding.require_trusted": True}):
        result = await detect_cluster("AAPL", new_event_id=0, now_utc=now)

    assert result.fired is False
    assert result.reason == "trust_floor_failed"


# ---------------------------------------------------------------------------
# (c) panic regime requires 4 — no fire with effective_size=3
# ---------------------------------------------------------------------------

async def test_panic_regime_requires_4():
    """panic regime: effective_size=3 < panic_min_cluster_size=4 → no fire."""
    now = _now()
    ts = now.timestamp()
    for i, name in enumerate(["p1", "p2", "p3"]):
        await _insert_signal_event("TSLA", name, ts - (i + 1) * 60)
        await _insert_performance(name, 0.8)  # all trusted

    from consensus_engine.analysis.regime import RegimeContext

    panic_regime = RegimeContext(
        label="panic", z_score=2.0, threshold_shift=10, cold_start=False, as_of_date="2026-04-27"
    )

    with _cfg_enabled():
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=panic_regime)):
            result = await detect_cluster("TSLA", new_event_id=0, now_utc=now)

    assert result.fired is False
    assert result.reason == "regime_panic_min_4"


# ---------------------------------------------------------------------------
# (d) consumed_by_cluster_id written on member rows on fire
# ---------------------------------------------------------------------------

async def test_consumed_by_cluster_id_written():
    """On fire, signal_events members get consumed_by_cluster_id set."""
    import consensus_engine.db as db_module
    now = _now()
    ts = now.timestamp()
    ids = []
    for i, name in enumerate(["d1", "d2", "d3"]):
        sid = await _insert_signal_event("SPY", name, ts - (i + 1) * 60)
        ids.append(sid)
        await _insert_performance(name, 0.75)

    from consensus_engine.analysis.regime import RegimeContext
    normal_regime = RegimeContext(
        label="normal", z_score=0.0, threshold_shift=0, cold_start=False, as_of_date="2026-04-27"
    )

    with _cfg_enabled():
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=normal_regime)):
            result = await detect_cluster("SPY", new_event_id=0, now_utc=now)

    assert result.fired is True
    assert result.cluster_id is not None

    conn = await db_module.get_db()
    cur = await conn.execute(
        "SELECT consumed_by_cluster_id FROM signal_events WHERE id IN ({})".format(
            ",".join("?" * len(ids))
        ),
        ids,
    )
    rows = await cur.fetchall()
    for row in rows:
        assert row["consumed_by_cluster_id"] == result.cluster_id


# ---------------------------------------------------------------------------
# (e) fired=True with cluster_id set
# ---------------------------------------------------------------------------

async def test_cluster_fires_and_has_id():
    """With 3 trusted analysts, normal regime → fired=True, cluster_id is int."""
    now = _now()
    ts = now.timestamp()
    for i, name in enumerate(["x", "y", "z"]):
        await _insert_signal_event("MSFT", name, ts - (i + 1) * 30)
        await _insert_performance(name, 0.9)

    from consensus_engine.analysis.regime import RegimeContext
    normal_regime = RegimeContext(
        label="normal", z_score=0.0, threshold_shift=0, cold_start=False, as_of_date="2026-04-27"
    )

    with _cfg_enabled():
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=normal_regime)):
            result = await detect_cluster("MSFT", new_event_id=0, now_utc=now)

    assert result.fired is True
    assert isinstance(result.cluster_id, int)
    assert result.cluster_id > 0
    assert result.reason == "fired"


# ---------------------------------------------------------------------------
# (f) correlation discount reduces effective_size
# ---------------------------------------------------------------------------

async def test_correlation_discount_reduces_effective_size():
    """Pair correlation data → effective_size < raw_count."""
    import consensus_engine.db as db_module
    now = _now()
    ts = now.timestamp()
    analysts = ["corr_a", "corr_b", "corr_c"]
    for i, name in enumerate(analysts):
        await _insert_signal_event("AMZN", name, ts - (i + 1) * 60)
        await _insert_performance(name, 0.8)

    # Insert correlation: corr_a and corr_b have co_post_rate=0.5
    conn = await db_module.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO analyst_pair_correlations
           (analyst_a, analyst_b, co_post_rate, sample_count, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("corr_a", "corr_b", 0.5, 10, time.time()),
    )
    await conn.commit()

    from consensus_engine.analysis.regime import RegimeContext
    normal_regime = RegimeContext(
        label="normal", z_score=0.0, threshold_shift=0, cold_start=False, as_of_date="2026-04-27"
    )

    with _cfg_enabled():
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=normal_regime)):
            result = await detect_cluster("AMZN", new_event_id=0, now_utc=now)

    # raw_count=3, discount=0.5 → effective_size=2.5
    assert result.effective_size < 3.0
    assert abs(result.effective_size - 2.5) < 0.01


# ---------------------------------------------------------------------------
# (g) window_minutes honored — events outside window not counted
# ---------------------------------------------------------------------------

async def test_window_minutes_honored():
    """Events older than window_minutes are excluded from cluster detection."""
    now = _now()
    ts = now.timestamp()
    # 3 analysts — 2 within window (30 min), 1 outside (35 min ago)
    await _insert_signal_event("GLD", "in_window_1", ts - 5 * 60)
    await _insert_signal_event("GLD", "in_window_2", ts - 10 * 60)
    await _insert_signal_event("GLD", "out_of_window", ts - 35 * 60)
    for name in ["in_window_1", "in_window_2", "out_of_window"]:
        await _insert_performance(name, 0.9)

    with _cfg_enabled():
        result = await detect_cluster("GLD", new_event_id=0, now_utc=now)

    # Only 2 in-window analysts, below min_cluster_size=3
    assert result.fired is False
    assert result.reason == "below_threshold"


# ---------------------------------------------------------------------------
# (h) members_cap=20 limits stored members
# ---------------------------------------------------------------------------

async def test_members_cap_limits_stored():
    """With members_cap=5, only 5 members written to cluster_events.members_json."""
    import consensus_engine.db as db_module
    now = _now()
    ts = now.timestamp()
    # Insert 8 analysts
    analyst_names = [f"cap_analyst_{i}" for i in range(8)]
    for i, name in enumerate(analyst_names):
        await _insert_signal_event("QQQ", name, ts - (i + 1) * 60)
        await _insert_performance(name, 0.8)

    from consensus_engine.analysis.regime import RegimeContext
    normal_regime = RegimeContext(
        label="normal", z_score=0.0, threshold_shift=0, cold_start=False, as_of_date="2026-04-27"
    )

    with _cfg_enabled(**{"features.analyst_herding.members_cap": 5}):
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=normal_regime)):
            result = await detect_cluster("QQQ", new_event_id=0, now_utc=now)

    assert result.fired is True
    assert result.cluster_id is not None

    conn = await db_module.get_db()
    cur = await conn.execute(
        "SELECT members_json FROM cluster_events WHERE id = ?", (result.cluster_id,)
    )
    row = await cur.fetchone()
    assert row is not None
    stored = json.loads(row["members_json"])
    assert len(stored) == 5


# ---------------------------------------------------------------------------
# I7 (2026-06-17): loud SWARM alert — 4 distinct analysts in 60 min, trust floor OFF
# ---------------------------------------------------------------------------

async def test_swarm_4_analysts_fires_without_trust_floor():
    """I7: 4 distinct analysts in 60 min fire a cluster with require_trusted OFF
    (production default) even though none are 'trusted' (source_performance empty)."""
    now = _now()
    ts = now.timestamp()
    for i, name in enumerate(["sw1", "sw2", "sw3", "sw4"]):
        await _insert_signal_event("NVDA", name, ts - (i + 1) * 60)  # all within 60 min
        # NO source_performance rows -> all rolling_accuracy 0.0 (untrusted)

    from consensus_engine.analysis.regime import RegimeContext
    normal_regime = RegimeContext(
        label="normal", z_score=0.0, threshold_shift=0, cold_start=False, as_of_date="2026-06-17"
    )

    with _cfg_enabled(**{
        "features.analyst_herding.min_cluster_size": 4,
        "features.analyst_herding.window_minutes": 60,
        "features.analyst_herding.require_trusted": False,
    }):
        with patch("consensus_engine.analysis.herding.lookup_regime", new=AsyncMock(return_value=normal_regime)):
            result = await detect_cluster("NVDA", new_event_id=0, now_utc=now)

    assert result.fired is True
    assert result.reason == "fired"
    assert len(result.members) == 4


async def test_swarm_3_analysts_below_new_threshold():
    """I7: with min_cluster_size=4, only 3 analysts no longer fires (was the old
    threshold). Confirms the threshold bump took effect."""
    now = _now()
    ts = now.timestamp()
    for i, name in enumerate(["t1", "t2", "t3"]):
        await _insert_signal_event("AAPL", name, ts - (i + 1) * 60)

    with _cfg_enabled(**{
        "features.analyst_herding.min_cluster_size": 4,
        "features.analyst_herding.window_minutes": 60,
        "features.analyst_herding.require_trusted": False,
    }):
        result = await detect_cluster("AAPL", new_event_id=0, now_utc=now)

    assert result.fired is False
    assert result.reason == "below_threshold"


def test_swarm_embed_shape():
    """I7: format_cluster_alert produces the loud SWARM embed — title, clickable +
    plain analyst handles, window span, price, and the framing line."""
    from consensus_engine.alerts.discord import format_cluster_alert
    from consensus_engine.analysis.herding import ClusterResult, ClusterMember
    base = 1_700_000_000.0
    members = [
        ClusterMember(analyst=f"an{i}", rolling_accuracy=0.0, signal_event_id=i, posted_at=base + i * 60)
        for i in range(4)
    ]
    cluster = ClusterResult(fired=True, cluster_id=7, ticker="NVDA", members=members,
                            effective_size=4.0, reason="fired")
    links = {"an0": "https://x.com/an0/status/1"}
    embed = format_cluster_alert(cluster, current_price=123.45, links=links)

    assert "SWARM" in embed["title"]
    assert "$NVDA" in embed["title"]
    assert "4 analysts" in embed["title"]
    assert embed["color"] == 0xED4245
    analysts_field = next(f for f in embed["fields"] if f["name"] == "Analysts")["value"]
    assert "[@an0](https://x.com/an0/status/1)" in analysts_field  # clickable when link present
    assert "@an1" in analysts_field                                # plain when no link
    assert any(f["name"] == "Window" for f in embed["fields"])
    assert any("independent analysts" in f["value"] for f in embed["fields"])
    assert any(f["name"] == "Price" and "123.45" in f["value"] for f in embed["fields"])


async def test_swarm_send_cluster_alert_dry_run():
    """I7: send_cluster_alert returns the dry-run sentinel (no network) when dry_run."""
    from unittest.mock import patch as _patch
    from consensus_engine.alerts.discord import send_cluster_alert
    from consensus_engine.analysis.herding import ClusterResult, ClusterMember
    import consensus_engine.config as cfg_mod
    members = [
        ClusterMember(analyst=f"a{i}", rolling_accuracy=0.0, signal_event_id=i, posted_at=1.0)
        for i in range(4)
    ]
    cluster = ClusterResult(fired=True, cluster_id=1, ticker="NVDA", members=members,
                            effective_size=4.0, reason="fired")
    with _patch.object(cfg_mod, "dry_run", True):
        msg_id = await send_cluster_alert(cluster, 0.0)
    assert msg_id == "dry_run_msg_id"
