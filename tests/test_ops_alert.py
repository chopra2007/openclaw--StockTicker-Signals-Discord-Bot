"""#71: #errors outage alerts — transition-only, persisted, never @-mentions."""
import asyncio

import pytest

from consensus_engine import db
from consensus_engine.alerts import ops_alert
from consensus_engine.scanners import schwab_health
from consensus_engine.scanners.schwab_client import SchwabError, SchwabRefreshTokenExpired


@pytest.fixture
def sent(monkeypatch):
    """Capture every Discord post instead of making one."""
    calls = []

    async def _fake_send(channel_id, content, ping_user_id=None):
        # Yield like a real Discord POST does. Without this the send never suspends,
        # concurrent callers can't interleave, and the duplicate-message race below
        # is invisible to the test.
        await asyncio.sleep(0)
        calls.append({"channel": channel_id, "content": content, "ping": ping_user_id})
        return "msg_1"

    monkeypatch.setattr("consensus_engine.alerts.discord.send_message", _fake_send)
    monkeypatch.setattr(ops_alert, "errors_channel_id", lambda: "999")
    return calls


async def _schwab_down_confirmed(exc):
    """Report a Schwab failure that outlives the confirmation window.

    Schwab holds a DOWN alert for 5 minutes so a single blown call is never
    announced. The engine gets there by checking again; a test gets there by
    reporting once, winding the episode's start back, and reporting again.
    """
    await schwab_health.note_schwab_failure(exc)
    conn = await db.get_db()
    await conn.execute(
        "UPDATE ops_alert_state SET since = since - 600 WHERE alert_key = ?",
        (schwab_health.ALERT_KEY,))
    await conn.commit()
    return await schwab_health.note_schwab_failure(exc)


# --- failure classification -------------------------------------------------

@pytest.mark.parametrize("exc,expected", [
    (SchwabRefreshTokenExpired("past its 7-day wall"), schwab_health.TOKEN_LAPSED),
    (SchwabRefreshTokenExpired('refresh failed: 400 {"error":"invalid_grant"}'),
     schwab_health.TOKEN_LAPSED),
    (SchwabError('refresh failed: 401 {"error":"invalid_client"}'), schwab_health.AUTH_REJECTED),
    (SchwabError("schwab GET /quotes HTTP 503"), schwab_health.API_DOWN),
    (SchwabError("schwab 429 rate limited"), schwab_health.API_DOWN),
    (TimeoutError("read timeout"), schwab_health.API_DOWN),
    (ConnectionError("dns failure"), schwab_health.API_DOWN),
])
def test_classify_failure(exc, expected):
    assert schwab_health.classify_failure(exc) == expected


def test_invalid_client_beats_token_expiry():
    """A refresh rejected for bad credentials must NOT tell the user to re-login —
    re-logging in would not fix it."""
    exc = SchwabRefreshTokenExpired('refresh failed: 401 {"error":"invalid_client"}')
    assert schwab_health.classify_failure(exc) == schwab_health.AUTH_REJECTED


def test_each_class_has_its_own_advice():
    fixes = {schwab_health.describe(k)[2] for k in
             (schwab_health.TOKEN_LAPSED, schwab_health.AUTH_REJECTED, schwab_health.API_DOWN)}
    assert len(fixes) == 3
    assert "schwab_login.py" in schwab_health.describe(schwab_health.TOKEN_LAPSED)[2]


# --- transition-only behaviour ----------------------------------------------

async def test_first_failure_alerts(sent):
    await db.init_db()
    assert await ops_alert.report_ops_state(
        "thing", down=True, title="It broke", detail="d", failure_class="cls") is True
    assert len(sent) == 1
    assert "It broke" in sent[0]["content"]
    await db.close_db()


async def test_repeated_failure_is_silent(sent):
    """Schwab down for an hour must post ONE alert, not sixty."""
    await db.init_db()
    for _ in range(60):
        await ops_alert.report_ops_state("thing", down=True, title="It broke",
                                         failure_class="cls")
    assert len(sent) == 1
    await db.close_db()


async def test_recovery_posts_exactly_one_followup(sent):
    await db.init_db()
    await ops_alert.report_ops_state("thing", down=True, title="It broke", failure_class="cls")
    for _ in range(5):
        await ops_alert.report_ops_state("thing", down=False, title="It broke")
    assert len(sent) == 2
    assert "Recovered" in sent[1]["content"]
    await db.close_db()


async def test_never_announces_a_recovery_that_never_broke(sent):
    """No 'restored' message for something we never said was down."""
    await db.init_db()
    assert await ops_alert.report_ops_state("thing", down=False, title="fine") is False
    assert sent == []
    await db.close_db()


async def test_state_change_within_down_realerts(sent):
    """Token lapsed, then the API starts 500ing too: the user's next action changed,
    so tell them again."""
    await db.init_db()
    await ops_alert.report_ops_state("schwab_feed", down=True, title="a",
                                     failure_class=schwab_health.TOKEN_LAPSED)
    await ops_alert.report_ops_state("schwab_feed", down=True, title="b",
                                     failure_class=schwab_health.API_DOWN)
    assert len(sent) == 2
    await db.close_db()


async def test_same_class_twice_does_not_realert(sent):
    await db.init_db()
    for _ in range(3):
        await ops_alert.report_ops_state("schwab_feed", down=True, title="a",
                                         failure_class=schwab_health.TOKEN_LAPSED)
    assert len(sent) == 1
    await db.close_db()


async def test_outage_state_survives_a_restart(sent):
    """The whole point of persisting: an engine restart mid-outage must not re-ping."""
    await db.init_db()
    await ops_alert.report_ops_state("thing", down=True, title="It broke",
                                     failure_class="cls")
    await db.close_db()

    await db.init_db()          # "restart"
    await ops_alert.report_ops_state("thing", down=True, title="It broke",
                                     failure_class="cls")
    assert len(sent) == 1
    await db.close_db()


async def test_down_since_is_preserved_across_repeats(sent):
    await db.init_db()
    await ops_alert.report_ops_state("thing", down=True, title="x", failure_class="cls")
    first = (await db.get_ops_alert_state("thing"))["since"]
    await ops_alert.report_ops_state("thing", down=True, title="x", failure_class="cls")
    assert (await db.get_ops_alert_state("thing"))["since"] == first
    await db.close_db()


# --- mention policy: nothing in #errors ever @-mentions ----------------------

async def test_schwab_outage_does_not_ping(sent):
    """2026-07-12 (user): no @-mentions in #errors at all — not even for Schwab."""
    await db.init_db()
    await _schwab_down_confirmed(SchwabRefreshTokenExpired("7-day wall"))
    assert sent[0]["ping"] is None
    assert "<@" not in sent[0]["content"]
    await db.close_db()


async def test_schwab_recovery_does_not_ping(sent):
    await db.init_db()
    await _schwab_down_confirmed(SchwabRefreshTokenExpired("wall"))
    await schwab_health.note_schwab_ok()
    assert [c["ping"] for c in sent] == [None, None]
    await db.close_db()


async def test_dead_source_does_not_ping(sent):
    await db.init_db()
    await ops_alert.report_ops_state("source:reddit", down=True,
                                     failure_class="dead_source", title="reddit died")
    assert sent[0]["ping"] is None
    await db.close_db()


# --- the duplicate-message race ----------------------------------------------

async def test_concurrent_recoveries_post_exactly_one_message(sent):
    """2026-07-12: a batch of quotes fans out over asyncio.gather, so seven
    coroutines called note_schwab_ok() at once. All seven read state='down' before
    any wrote 'up', and the user got seven identical 'Recovered' messages."""
    await db.init_db()
    await _schwab_down_confirmed(SchwabError("500 from Schwab"))
    sent.clear()
    await asyncio.gather(*(schwab_health.note_schwab_ok() for _ in range(7)))
    assert len(sent) == 1, [c["content"][:40] for c in sent]
    await db.close_db()


async def test_concurrent_failures_post_exactly_one_message(sent):
    await db.init_db()
    # First round: seven callers all see the very first failure. Nothing is said yet —
    # the confirmation window has not run out.
    await asyncio.gather(*(schwab_health.note_schwab_failure(SchwabError("500"))
                           for _ in range(7)))
    assert sent == [], [c["content"][:40] for c in sent]
    conn = await db.get_db()
    await conn.execute(
        "UPDATE ops_alert_state SET since = since - 600 WHERE alert_key = ?",
        (schwab_health.ALERT_KEY,))
    await conn.commit()
    # Second round, past the window: still exactly one message, not seven.
    await asyncio.gather(*(schwab_health.note_schwab_failure(SchwabError("500"))
                           for _ in range(7)))
    assert len(sent) == 1, [c["content"][:40] for c in sent]
    await db.close_db()


# --- flap guard --------------------------------------------------------------

async def test_a_flapping_source_cannot_spam(sent):
    """down/up/down/up every few seconds must not post a message per bounce."""
    await db.init_db()
    for _ in range(10):
        await ops_alert.report_ops_state("flap", down=True, failure_class="dead_source",
                                         title="broke")
        await ops_alert.report_ops_state("flap", down=False, title="broke")
    # Exactly the first down + its matching recovery. Every later bounce is inside
    # the 30-minute flap window.
    assert len(sent) == 2, [c["content"][:40] for c in sent]
    await db.close_db()


async def test_flap_window_expiry_allows_a_new_alert(sent, monkeypatch):
    import consensus_engine.config as cfg
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get", lambda k, d=None:
                        0.0 if k == "ops_alerts.min_interval_s" else real_get(k, d))
    await db.init_db()
    for _ in range(3):
        await ops_alert.report_ops_state("flap2", down=True, failure_class="dead_source",
                                         title="broke")
        await ops_alert.report_ops_state("flap2", down=False, title="broke")
    assert len(sent) == 6   # no window -> every transition speaks
    await db.close_db()


async def test_a_suppressed_down_gets_no_recovery_note(sent):
    """A 'recovered' reply to a message the user never saw is worse than silence."""
    await db.init_db()
    await ops_alert.report_ops_state("f3", down=True, failure_class="dead_source", title="b")
    await ops_alert.report_ops_state("f3", down=False, title="b")
    sent.clear()
    await ops_alert.report_ops_state("f3", down=True, failure_class="dead_source", title="b")
    await ops_alert.report_ops_state("f3", down=False, title="b")
    assert sent == []
    await db.close_db()


async def test_class_change_breaks_the_flap_window(sent):
    """Token lapsed then the API also dies: different fix, so say it even inside
    the quiet window."""
    await db.init_db()
    await ops_alert.report_ops_state("schwab_feed", down=True, title="a",
                                     failure_class=schwab_health.TOKEN_LAPSED)
    await ops_alert.report_ops_state("schwab_feed", down=True, title="b",
                                     failure_class=schwab_health.API_DOWN)
    assert len(sent) == 2
    await db.close_db()


async def test_a_long_outage_still_reports_its_recovery(sent, monkeypatch):
    """The flap guard must never swallow the recovery of a real, sustained outage."""
    await db.init_db()
    await ops_alert.report_ops_state("long", down=True, failure_class="dead_source", title="b")
    # Pretend the down alert happened 3 hours ago.
    conn = await db.get_db()
    import time as _t
    await conn.execute(
        "UPDATE ops_alert_state SET since=?, last_alerted_at=? WHERE alert_key='long'",
        (_t.time() - 10800, _t.time() - 10800))
    await conn.commit()
    assert await ops_alert.report_ops_state("long", down=False, title="b") is True
    assert "3.0 hours" in sent[-1]["content"]
    await db.close_db()


async def test_recovery_always_answers_its_outage(sent):
    """Don't leave a scary message hanging unanswered."""
    await db.init_db()
    await _schwab_down_confirmed(SchwabRefreshTokenExpired("wall"))
    await schwab_health.note_schwab_ok()
    assert len(sent) == 2
    assert "Recovered" in sent[1]["content"]
    await db.close_db()


async def test_schwab_breaking_every_10_min_for_2_hours_stays_quiet(sent):
    """The #errors flood the user actually saw, 2026-07-27 → 2026-08-03.

    Schwab drops one call and the next one works. That is not an outage, and it
    was posting a "servers are not responding" plus a "recovered — down for 0
    seconds" every hour, for a week. Nothing here survives the confirmation
    window, so nothing here is worth a word.
    """
    await db.init_db()
    for _ in range(12):          # 12 bounces = 2 hours at one every 10 minutes
        await schwab_health.note_schwab_failure(SchwabError("500 from Schwab"))
        await schwab_health.note_schwab_ok()
    assert sent == [], [c["content"][:40] for c in sent]
    await db.close_db()


async def test_a_real_schwab_outage_still_gets_announced(sent):
    """The other half of the confirmation window: five minutes of continuous
    failure is a real outage and must reach the user."""
    await db.init_db()
    assert await _schwab_down_confirmed(SchwabError("schwab GET /quotes HTTP 503")) is True
    assert len(sent) == 1
    assert "not responding" in sent[0]["content"]
    assert await schwab_health.note_schwab_ok() is True
    assert "Recovered" in sent[1]["content"]
    await db.close_db()


# --- safety -----------------------------------------------------------------

async def test_master_switch_off_sends_nothing(sent, monkeypatch):
    import consensus_engine.config as cfg
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get",
                        lambda k, d=None: False if k == "ops_alerts.enabled" else real_get(k, d))
    await db.init_db()
    assert await ops_alert.report_ops_state("t", down=True, title="x") is False
    assert sent == []
    await db.close_db()


async def test_no_channel_configured_records_state_without_sending(monkeypatch):
    calls = []

    async def _fake_send(channel_id, content, ping_user_id=None):
        calls.append(content)
        return "id"

    monkeypatch.setattr("consensus_engine.alerts.discord.send_message", _fake_send)
    monkeypatch.setattr(ops_alert, "errors_channel_id", lambda: "")
    await db.init_db()
    assert await ops_alert.report_ops_state("t", down=True, title="x") is False
    assert calls == []
    # State still recorded, so a later recovery doesn't fire a bogus "restored".
    assert (await db.get_ops_alert_state("t"))["state"] == "down"
    await db.close_db()


async def test_an_alerting_bug_never_breaks_the_caller(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("discord exploded")

    monkeypatch.setattr("consensus_engine.alerts.discord.send_message", _boom)
    monkeypatch.setattr(ops_alert, "errors_channel_id", lambda: "999")
    await db.init_db()
    assert await ops_alert.report_ops_state("t", down=True, title="x") is False
    await db.close_db()


def test_humanize_duration_reads_naturally():
    assert ops_alert._humanize_duration(30) == "30 seconds"
    assert ops_alert._humanize_duration(600) == "10 minutes"
    assert ops_alert._humanize_duration(7200) == "2.0 hours"
    assert ops_alert._humanize_duration(200000) == "2.3 days"
