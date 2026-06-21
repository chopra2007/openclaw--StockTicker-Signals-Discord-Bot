"""Tests for the stateful analyst-SWARM detector (user spec 2026-06-17).

Behavior:
  - Opens when >=2 distinct analysts tweet the same ticker within window_minutes.
  - Stays open swarm_open_hours (fixed from open). Each NEW analyst re-alerts.
  - Same analyst tweeting again does nothing.
  - The 1-hour rule only gates the opening pair; later analysts count within the 24h.
  - After the window expires, a fresh pair reopens it (count resets).
Plus the embed (title span, dropped tail) and the ping payload.
"""
import time
from unittest.mock import patch, AsyncMock

import pytest

from consensus_engine.analysis.herding import detect_swarm, SwarmResult


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    import consensus_engine.db as dbm
    dbm.DB_PATH = str(tmp_path / "swarm_test.db")
    dbm._db = None
    await dbm.init_db()
    yield
    await dbm.close_db()
    dbm._db = None
    dbm.DB_PATH = None


async def _ins(ticker: str, analyst: str, recorded_at: float) -> None:
    import consensus_engine.db as dbm
    conn = await dbm.get_db()
    await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at)
           VALUES ('twitter', ?, ?, 'long', 0.5, ?)""",
        (analyst, ticker, recorded_at),
    )
    await conn.commit()


def _cfg(**overrides):
    defaults = {
        "features.analyst_herding.enabled": True,
        "features.analyst_herding.window_minutes": 60,
        "features.analyst_herding.min_cluster_size": 2,
        "features.analyst_herding.swarm_open_hours": 24,
    }
    defaults.update(overrides)

    def _get(key, default=None):
        return defaults.get(key, default)

    return patch("consensus_engine.analysis.herding.cfg.get", side_effect=_get)


# --------------------------------------------------------------------------- #
# detect_swarm
# --------------------------------------------------------------------------- #

async def test_opens_at_two_within_hour():
    now = time.time()
    await _ins("NVDA", "alice", now - 1800)   # 30 min ago
    await _ins("NVDA", "bob", now - 60)        # 1 min ago
    with _cfg():
        r = await detect_swarm("NVDA", "bob", now)
    assert r.fired is True
    assert r.reason == "opened"
    assert r.count == 2
    assert set(r.analysts) == {"alice", "bob"}


async def test_single_analyst_no_open():
    now = time.time()
    await _ins("AAPL", "solo", now - 120)
    await _ins("AAPL", "solo", now - 30)   # same analyst twice
    with _cfg():
        r = await detect_swarm("AAPL", "solo", now)
    assert r.fired is False
    assert r.reason == "below_threshold"


async def test_third_analyst_joins_realerts():
    t0 = time.time() - 4 * 3600   # opened 4h ago
    await _ins("MU", "a1", t0)
    await _ins("MU", "a2", t0 + 600)   # within an hour -> opens
    with _cfg():
        r1 = await detect_swarm("MU", "a2", t0 + 600)
        assert r1.reason == "opened" and r1.count == 2
        t3 = t0 + 3 * 3600             # 3rd analyst 3 hours after open
        await _ins("MU", "a3", t3)
        r2 = await detect_swarm("MU", "a3", t3)
    assert r2.fired is True
    assert r2.reason == "joined"
    assert r2.count == 3
    assert set(r2.analysts) == {"a1", "a2", "a3"}
    assert r2.opened_at == pytest.approx(t0)   # 24h clock stays anchored at open


async def test_same_analyst_no_realert():
    t0 = time.time() - 3600
    await _ins("SPY", "x", t0)
    await _ins("SPY", "y", t0 + 300)
    with _cfg():
        await detect_swarm("SPY", "y", t0 + 300)   # opens {x, y}
        t2 = t0 + 1800
        await _ins("SPY", "x", t2)                  # x tweets again
        r = await detect_swarm("SPY", "x", t2)
    assert r.fired is False
    assert r.reason == "already_counted"
    assert r.count == 2


async def test_expired_swarm_resets():
    t0 = time.time() - 26 * 3600   # opened 26h ago -> expired
    await _ins("QQQ", "old1", t0)
    await _ins("QQQ", "old2", t0 + 300)
    with _cfg():
        await detect_swarm("QQQ", "old2", t0 + 300)   # opens long ago
        now = time.time()
        await _ins("QQQ", "new1", now - 600)
        await _ins("QQQ", "new2", now - 60)
        r = await detect_swarm("QQQ", "new2", now)
    assert r.fired is True
    assert r.reason == "opened"                    # fresh swarm, not "joined"
    assert set(r.analysts) == {"new1", "new2"}     # 26h-old analysts excluded
    assert r.count == 2


async def test_disabled_returns_no_fire():
    now = time.time()
    await _ins("TSLA", "a", now - 100)
    await _ins("TSLA", "b", now - 50)
    with _cfg(**{"features.analyst_herding.enabled": False}):
        r = await detect_swarm("TSLA", "b", now)
    assert r.fired is False
    assert r.reason == "disabled"


# --------------------------------------------------------------------------- #
# embed + ping
# --------------------------------------------------------------------------- #

def test_human_span():
    from consensus_engine.alerts.discord import _human_span
    assert _human_span(40 * 60) == "40 min"
    assert _human_span(5 * 3600) == "5 hours"
    assert _human_span(3600) == "1 hour"
    assert _human_span(90 * 60) == "2 hours"   # round(1.5) -> 2
    assert _human_span(30) == "1 min"          # floor at 1


def test_format_swarm_alert_text_and_title():
    from consensus_engine.alerts.discord import format_swarm_alert
    opened = 1_700_000_000.0
    sw = SwarmResult(
        fired=True, reason="joined", ticker="NVDA",
        analysts=["a1", "a2", "a3", "a4", "a5"],
        member_times={f"a{i}": opened + i * 60 for i in range(1, 6)},
        opened_at=opened, now_ts=opened + 5 * 3600, count=5,
    )
    embed = format_swarm_alert(sw, current_price=176.55, links={"a1": "https://x.com/a1/1"})

    assert "SWARM: $NVDA" in embed["title"]
    assert "5 analysts tweeting in 5 hours" in embed["title"]
    assert embed["color"] == 0xED4245
    assert not any(f["name"] == "Why this matters" for f in embed["fields"])  # removed: redundant boilerplate
    analysts = next(f for f in embed["fields"] if f["name"] == "Analysts")["value"]
    assert "[@a1](https://x.com/a1/1)" in analysts   # clickable when link present
    assert "@a2" in analysts                          # plain otherwise
    assert any(f["name"] == "Price" and "176.55" in f["value"] for f in embed["fields"])


async def test_send_swarm_alert_pings_user():
    from consensus_engine.alerts import discord as dmod
    import consensus_engine.config as cfgmod
    sw = SwarmResult(fired=True, reason="opened", ticker="NVDA",
                     analysts=["a1", "a2"], member_times={"a1": 1.0, "a2": 2.0},
                     opened_at=1.0, now_ts=120.0, count=2)
    captured = {}

    async def fake_send(url, headers, payload, **kw):
        captured["payload"] = payload
        return {"id": "999"}

    def fake_get(key, default=None):
        if key == "api_keys.discord_channel_id":
            return "12345"
        if key == "features.analyst_herding.ping_user_id":
            return "615525529537216513"
        return default

    with patch.object(cfgmod, "dry_run", False), \
         patch.object(dmod.cfg, "get", side_effect=fake_get), \
         patch.object(dmod.cfg, "get_api_key", return_value="tok"), \
         patch.object(dmod, "_safe_send", new=fake_send):
        msg_id = await dmod.send_swarm_alert(sw, 100.0)

    assert msg_id == "999"
    p = captured["payload"]
    assert p["content"] == "<@615525529537216513>"
    assert p["allowed_mentions"]["users"] == ["615525529537216513"]


async def test_send_swarm_alert_dry_run():
    from consensus_engine.alerts.discord import send_swarm_alert
    import consensus_engine.config as cfgmod
    sw = SwarmResult(fired=True, reason="opened", ticker="NVDA", analysts=["a", "b"],
                     member_times={"a": 1.0, "b": 2.0}, opened_at=1.0, now_ts=60.0, count=2)
    with patch.object(cfgmod, "dry_run", True):
        msg_id = await send_swarm_alert(sw, 0.0)
    assert msg_id == "dry_run_msg_id"
