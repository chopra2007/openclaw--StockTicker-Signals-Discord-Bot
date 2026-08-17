"""Tests for the stateful analyst-SWARM detector (user spec 2026-06-17).

Behavior:
  - Opens when >=2 distinct analysts tweet the same ticker within window_minutes.
  - Stays open swarm_open_hours (fixed from open). Each NEW analyst re-alerts.
  - Same analyst tweeting again does nothing.
  - The 1-hour rule only gates the opening pair; later analysts count within the 24h.
  - After the window expires, a fresh pair reopens it (count resets).
Plus the embed (title span, dropped tail) and the ping payload.
"""
import json
import time
from unittest.mock import patch, AsyncMock

import pytest

from consensus_engine.analysis.herding import detect_swarm, SwarmMemberDetail, SwarmResult


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


async def _ins(
    ticker: str,
    analyst: str,
    recorded_at: float,
    *,
    direction: str | None = "long",
    raw_text: str | None = None,
    source_link: str | None = None,
    view_direction: str | None = None,
    reason_kind: str = "setup",
) -> None:
    import consensus_engine.db as dbm
    conn = await dbm.get_db()
    view_id = None
    if view_direction is not None:
        reason = raw_text if view_direction in {"long", "short"} else None
        view_cur = await conn.execute(
            """INSERT INTO analyst_post_views
               (source_post_key, source_url, analyst, ticker, detected_at, raw_text,
                raw_text_sha256, parsed_summary, display_direction, reason_text,
                reason_start, reason_end, reason_kind, decision_code, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"{ticker}-{analyst}-{recorded_at}", source_link, analyst, ticker,
                recorded_at, raw_text or "", "hash", None, view_direction, reason,
                0 if reason else None, len(reason) if reason else None,
                reason_kind if reason else "none",
                "explicit_clause" if reason else "missing", "analyst-view-v1", recorded_at,
            ),
        )
        view_id = view_cur.lastrowid
    await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at,
            source_link, analyst_post_view_id)
           VALUES ('twitter', ?, ?, ?, 0.5, ?, ?, ?)""",
        (analyst, ticker, direction, recorded_at, source_link, view_id),
    )
    if raw_text is not None:
        await conn.execute(
            """INSERT INTO ticker_signals
               (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at)
               VALUES (?, 'twitter', ?, ?, ?, ?, ?)""",
            (
                ticker,
                analyst,
                raw_text,
                "bullish" if direction == "long" else "bearish" if direction == "short" else "neutral",
                recorded_at,
                recorded_at + 7200,
            ),
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


async def test_member_details_match_the_exact_first_post_in_group_window():
    now = time.time()
    await _ins(
        "NVDA", "alice", now - 7200, direction="short", raw_text="$NVDA bearish old post",
        view_direction="short",
    )
    await _ins(
        "NVDA", "alice", now - 1800, direction="long",
        raw_text="Reclaiming the breakout level after earnings",
        source_link="https://example.test/alice/current",
        view_direction="long",
    )
    await _ins(
        "NVDA", "alice", now - 900, direction="short",
        raw_text="later reversal that must not replace the first group post",
    )
    await _ins("NVDA", "bob", now - 60, direction=None, raw_text="Watching NVDA")

    with _cfg():
        result = await detect_swarm("NVDA", "bob", now)

    details = {member.analyst: member for member in result.member_details}
    assert details["alice"].direction == "long"
    assert details["alice"].reason == "Reclaiming the breakout level after earnings"
    assert details["alice"].source_link == "https://example.test/alice/current"
    assert details["alice"].posted_at == pytest.approx(now - 1800)
    assert details["bob"].direction == "unclear"
    assert details["bob"].reason == "reason not stated"


async def test_missing_stored_text_uses_reason_not_stated():
    now = time.time()
    await _ins("AMD", "alice", now - 120, direction="long", raw_text="Breakout setup")
    await _ins("AMD", "bob", now - 60, direction="short")

    with _cfg():
        result = await detect_swarm("AMD", "bob", now)

    details = {member.analyst: member for member in result.member_details}
    assert details["bob"].reason == "reason not stated"


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


def _swarm_with_details(*directions_and_reasons):
    opened = 1_700_000_000.0
    details = [
        SwarmMemberDetail(
            analyst=f"a{i}",
            direction=direction,
            reason=reason,
            source_link=f"https://example.test/a{i}/post",
            posted_at=opened + i * 60,
        )
        for i, (direction, reason) in enumerate(directions_and_reasons, start=1)
    ]
    return SwarmResult(
        fired=True,
        reason="joined",
        ticker="NVDA",
        analysts=[member.analyst for member in details],
        member_times={member.analyst: member.posted_at for member in details},
        member_details=details,
        opened_at=opened,
        now_ts=opened + 5 * 3600,
        count=len(details),
    )


def _embed_chars(embed):
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("footer", {}).get("text", ""))
        + sum(len(field["name"]) + len(field["value"]) for field in embed.get("fields", []))
    )


@pytest.mark.parametrize(
    ("directions", "expected_bias"),
    [
        (("long", "long"), "Bullish"),
        (("short", "short"), "Bearish"),
        (("long", "short"), "Mixed"),
        (("long", "short", "unclear"), "Mixed"),
        (("long", "unclear"), "Unclear"),
        (("unclear", "unclear"), "Unclear"),
    ],
)
def test_format_swarm_alert_group_bias(directions, expected_bias):
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details(*[(direction, "explicit setup") for direction in directions])
    embed = format_swarm_alert(swarm)

    bias = next(field for field in embed["fields"] if field["name"] == "Group bias")
    assert expected_bias in bias["value"]


def test_format_swarm_alert_text_and_title():
    from consensus_engine.alerts.discord import format_swarm_alert

    sw = _swarm_with_details(
        ("long", "Earnings beat and a reclaim of resistance"),
        ("long", "reason not stated"),
        ("long", "Added calls for next month"),
        ("long", "New product launch"),
        ("long", "Watching a breakout"),
    )
    sw.member_details[0].source_link = "https://x.com/a1/1"
    embed = format_swarm_alert(sw, current_price=176.55)

    assert embed["title"].startswith("🚨 $NVDA")
    assert "SWARM" not in embed["title"]
    assert "5 analysts tweeting in 5 hours" in embed["title"]
    assert embed["color"] == 0xED4245
    assert "swarm" not in embed["footer"]["text"].lower()
    assert "UTC" not in str(embed)
    analyst_text = "\n".join(
        field["value"] for field in embed["fields"] if field["name"].startswith("Analyst views")
    )
    assert "[@a1](https://x.com/a1/1)" in analyst_text
    assert "🟢 Bullish" in analyst_text
    assert "Earnings beat and a reclaim of resistance" in analyst_text
    assert "reason not stated" in analyst_text
    assert any(f["name"] == "Price" and "176.55" in f["value"] for f in embed["fields"])


def test_format_swarm_alert_long_text_stays_inside_discord_limits():
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details(*[("long", "reason " * 500) for _ in range(20)])
    embed = format_swarm_alert(swarm)

    assert len(embed["fields"]) <= 25
    assert all(len(field["name"]) <= 256 for field in embed["fields"])
    assert all(len(field["value"]) <= 1024 for field in embed["fields"])
    assert _embed_chars(embed) <= 6000
    analyst_text = "\n".join(
        field["value"] for field in embed["fields"] if field["name"].startswith("Analyst views")
    )
    assert all(f"@a{i}" in analyst_text for i in range(1, 21))
    assert "…" in analyst_text


def test_format_swarm_alert_displays_only_the_validated_ticker_reason():
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details((
        "long", "$NVDA raised guidance after earnings and reclaimed its breakout level",
    ))

    embed = format_swarm_alert(swarm)
    analyst_text = "\n".join(
        field["value"] for field in embed["fields"] if field["name"].startswith("Analyst views")
    )

    assert "$NVDA" in analyst_text
    assert "raised guidance after earnings" in analyst_text
    assert _embed_chars(embed) <= 6000


def test_event_claim_is_visibly_attributed_to_analyst():
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details(("long", "$RDDT added to the S&P 500; buying shares"))
    swarm.member_details[0].reason_kind = "event_claim"

    embed = format_swarm_alert(swarm)
    analyst_text = "\n".join(
        field["value"] for field in embed["fields"] if field["name"].startswith("Analyst views")
    )
    assert "Analyst says: $RDDT added to the S&P 500" in analyst_text


def test_card_displays_unclear_with_exact_reason_and_direction_with_no_reason():
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details(
        ("unclear", "$NVDA reports earnings tomorrow"),
        ("long", "reason not stated"),
    )
    swarm.member_details[0].reason_kind = "event_claim"
    swarm.member_details[0].decision_code = "reason_only"
    swarm.member_details[1].decision_code = "direction_only"

    embed = format_swarm_alert(swarm)
    analyst_text = "\n".join(
        field["value"] for field in embed["fields"] if field["name"].startswith("Analyst views")
    )
    assert "⚪ Unclear — Analyst says: $NVDA reports earnings tomorrow" in analyst_text
    assert "🟢 Bullish — reason not stated" in analyst_text


async def test_swarm_uses_durable_view_and_missing_view_fails_closed():
    import consensus_engine.db as dbm

    now = time.time()
    conn = await dbm.get_db()
    reason = "$NVDA broke resistance"
    view_cur = await conn.execute(
        """INSERT INTO analyst_post_views
           (source_post_key, source_url, analyst, ticker, detected_at, raw_text,
            raw_text_sha256, parsed_summary, display_direction, reason_text,
            reason_start, reason_end, reason_kind, decision_code, parser_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("post-a", "https://example.test/a", "alice", "NVDA", now - 120, reason,
         "hash", "summary", "long", reason, 0, len(reason), "setup",
         "explicit_clause", "analyst-view-v1", now),
    )
    await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at,
            source_link, analyst_post_view_id)
           VALUES ('twitter', 'alice', 'NVDA', 'short', 0.5, ?, ?, ?)""",
        (now - 120, "https://example.test/a", view_cur.lastrowid),
    )
    await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at, source_link)
           VALUES ('twitter', 'bob', 'NVDA', 'long', 0.5, ?, ?)""",
        (now - 60, "https://example.test/b"),
    )
    await conn.commit()

    with _cfg():
        result = await detect_swarm("NVDA", "bob", now)

    details = {member.analyst: member for member in result.member_details}
    assert details["alice"].direction == "long"
    assert details["alice"].reason == reason
    assert details["alice"].analyst_post_view_id == view_cur.lastrowid
    assert details["bob"].direction == "unclear"
    assert details["bob"].reason == "reason not stated"
    history = await (await conn.execute(
        "SELECT members_json FROM cluster_events ORDER BY id DESC LIMIT 1"
    )).fetchone()
    stored_members = {item["analyst"]: item for item in json.loads(history["members_json"])}
    assert stored_members["alice"]["signal_event_id"] == details["alice"].signal_event_id
    assert stored_members["alice"]["analyst_post_view_id"] == view_cur.lastrowid


def test_group_formatter_makes_no_ai_call():
    from consensus_engine.alerts.discord import format_swarm_alert

    swarm = _swarm_with_details(("long", "$NVDA broke resistance"))
    with patch("models.text_model.chat_completion") as ai_call:
        format_swarm_alert(swarm)
    ai_call.assert_not_called()


async def test_send_swarm_alert_pings_user():
    from consensus_engine.alerts import discord as dmod
    import consensus_engine.config as cfgmod
    sw = SwarmResult(fired=True, reason="opened", ticker="NVDA",
                     analysts=["a1", "a2"], member_times={"a1": 1.0, "a2": 2.0},
                     opened_at=1.0, now_ts=120.0, count=2,
                     member_details=[
                         SwarmMemberDetail("a1", "long", "Breakout", "https://example.test/a1", 1.0),
                         SwarmMemberDetail("a2", "long", "Earnings", "https://example.test/a2", 2.0),
                     ])
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
    assert "[@a1](https://example.test/a1)" in str(p["embeds"])


async def test_send_swarm_alert_dry_run():
    from consensus_engine.alerts.discord import send_swarm_alert
    import consensus_engine.config as cfgmod
    sw = SwarmResult(fired=True, reason="opened", ticker="NVDA", analysts=["a", "b"],
                     member_times={"a": 1.0, "b": 2.0}, opened_at=1.0, now_ts=60.0, count=2)
    with patch.object(cfgmod, "dry_run", True):
        msg_id = await send_swarm_alert(sw, 0.0)
    assert msg_id == "dry_run_msg_id"
