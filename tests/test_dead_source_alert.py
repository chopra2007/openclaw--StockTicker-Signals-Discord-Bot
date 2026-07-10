"""C5 (reliability-hardening): dead-source ladder + per-source health counters +
ONE #errors alert on a closed->open transition.

Motivating case: Exa stuck in a permanent backoff, logging "0/10 tickers" 199x
and ~450 backoff lines, degrading silently. With the breaker wired in, the
source goes ABSENT (allow False) and exactly ONE alert fires; a flapping
source can't spam (30-min flap window in ops_alert).

#71: these alerts used to resolve their channel from `discord.ops_channel_id`,
a config key that has never existed — so the guard `if not channel: return` ate
every one of them and this alert never fired in production. It now goes through
`consensus_engine.alerts.ops_alert`, which owns the channel, the transition
logic, and the flap window (persisted in `ops_alert_state`, so an engine restart
mid-outage cannot re-ping). The old in-memory 30-min throttle is gone with it.
"""
import pytest

from consensus_engine import config, db
from consensus_engine.alerts import ops_alert
from consensus_engine.utils.circuit_breaker import CircuitBreaker


class _Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def cb_on(monkeypatch):
    real = config.get
    cfg = {
        "circuit_breaker.enabled": True,
        "circuit_breaker.fail_max": 5,
        "circuit_breaker.reset_timeout_s": 120,
        "circuit_breaker.hard_max_open_s": 1800,
        "dead_source.ops_alert_enabled": True,
    }
    monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, real(k, d)))


def _capture_send(monkeypatch):
    """Capture what would reach #errors. Patches the ops_alert channel lookup so the
    test never depends on a real env var."""
    sent = []
    import consensus_engine.alerts.discord as discord

    async def fake_send(channel_id, content, ping_user_id=None):
        sent.append((channel_id, content, ping_user_id))
        return "msg_id"

    monkeypatch.setattr(discord, "send_message", fake_send)
    monkeypatch.setattr(ops_alert, "errors_channel_id", lambda: "999")
    monkeypatch.setattr(ops_alert, "owner_user_id", lambda: "615525529537216513")
    return sent


async def test_note_failure_quota_opens_and_alerts_once(cb_on, monkeypatch):
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)  # 429 -> QUOTA -> opens immediately
    assert cb.allow("exa") is False, "a quota failure must open the breaker"
    assert len(sent) == 1, "exactly one #errors alert on closed->open"
    assert sent[0][0] == "999" and "exa" in sent[0][1]
    await db.close_db()


async def test_dead_source_alert_does_not_ping_the_owner(cb_on, monkeypatch):
    """A flaky scraper is informational; only Schwab/LLM outages @-mention."""
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)
    assert sent[0][2] is None
    await db.close_db()


async def test_recovery_posts_a_followup(cb_on, monkeypatch):
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)   # open  -> alert
    await cb.note_success("exa")               # close -> recovery note
    assert len(sent) == 2
    assert "responding again" in sent[1][1]
    await db.close_db()


async def test_steady_success_sends_nothing(cb_on, monkeypatch):
    """note_success runs on every healthy call — it must not touch Discord (or the
    DB) unless the breaker actually transitioned back to closed."""
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    for _ in range(20):
        await cb.note_success("exa")
    assert sent == []
    await db.close_db()


async def test_alert_throttled_across_flap(cb_on, monkeypatch):
    """A source that dies and revives repeatedly posts its first outage and that
    outage's recovery, then goes quiet for the flap window."""
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)   # open   -> alert (1)
    await cb.note_success("exa")               # closed -> recovery (2)
    await cb.note_failure("exa", status=429)   # reopen inside the window -> silent
    await cb.note_success("exa")               # its recovery -> also silent
    assert len(sent) == 2, "a flapping source must not spam"
    await db.close_db()


async def test_alert_suppressed_when_flag_off(monkeypatch):
    real = config.get
    cfg = {"circuit_breaker.enabled": True, "circuit_breaker.fail_max": 5,
           "dead_source.ops_alert_enabled": False}
    monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, real(k, d)))
    await db.init_db()
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)
    assert sent == [], "ops alert must not fire when dead_source.ops_alert_enabled is OFF"
    await db.close_db()


async def test_transient_ladder_opens_after_fail_max(cb_on, monkeypatch):
    _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    for _ in range(4):
        await cb.note_failure("brave_search", status=503)  # transient
    assert cb.allow("brave_search") is True, "4 transient failures must not open"
    await cb.note_failure("brave_search", status=503)
    assert cb.allow("brave_search") is False, "5th transient failure opens (ladder)"


async def test_health_counters_and_summary(cb_on, monkeypatch):
    _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)   # 1 failure, opens
    cb.allow("exa")                            # 1 attempt, skipped (open)
    h = cb._health["exa@v1"]
    assert h["failures"] >= 1
    assert h["skipped"] >= 1
    summary = cb.health_summary()
    assert "exa" in summary
