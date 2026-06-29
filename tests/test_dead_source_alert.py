"""C5 (reliability-hardening): dead-source ladder + per-source health counters +
ONE throttled (30-min) ops-channel alert on a closed->open transition.

Motivating case: Exa stuck in a permanent backoff, logging "0/10 tickers" 199x
and ~450 backoff lines, degrading silently. With the breaker wired in, the
source goes ABSENT (allow False) and exactly ONE ops alert fires; a flapping
source can't spam (30-min throttle, preserved across open/close cycles)."""
import pytest

from consensus_engine import config
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
        "discord.ops_channel_id": "999",
    }
    monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, real(k, d)))


def _capture_send(monkeypatch):
    sent = []
    import consensus_engine.alerts.discord as discord

    async def fake_send(channel_id, content):
        sent.append((channel_id, content))
        return "msg_id"

    monkeypatch.setattr(discord, "send_message", fake_send)
    return sent


async def test_note_failure_quota_opens_and_alerts_once(cb_on, monkeypatch):
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)  # 429 -> QUOTA -> opens immediately
    assert cb.allow("exa") is False, "a quota failure must open the breaker"
    assert len(sent) == 1, "exactly one ops alert on closed->open"
    assert "999" == sent[0][0] and "exa" in sent[0][1]


async def test_alert_throttled_across_flap(cb_on, monkeypatch):
    sent = _capture_send(monkeypatch)
    clk = _Clock()
    cb = CircuitBreaker(now_fn=clk)
    await cb.note_failure("exa", status=429)          # open -> alert (1)
    await cb.note_success("exa")                       # recovers
    await cb.note_failure("exa", status=429)          # reopen within 30m -> throttled
    assert len(sent) == 1, "a flapping source must not spam (30-min throttle)"
    clk.advance(1801)
    await cb.note_success("exa")
    await cb.note_failure("exa", status=429)          # reopen after 30m -> alert (2)
    assert len(sent) == 2


async def test_alert_suppressed_when_flag_off(monkeypatch):
    real = config.get
    cfg = {"circuit_breaker.enabled": True, "circuit_breaker.fail_max": 5,
           "dead_source.ops_alert_enabled": False, "discord.ops_channel_id": "999"}
    monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, real(k, d)))
    sent = _capture_send(monkeypatch)
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.note_failure("exa", status=429)
    assert sent == [], "ops alert must not fire when dead_source.ops_alert_enabled is OFF"


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
