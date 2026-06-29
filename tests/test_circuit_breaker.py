"""C2 (reliability-hardening): a persistent 3-state circuit breaker.

These tests encode the Pass-3 adversarial defeaters that the design MUST survive:
- opened_at is WALL-CLOCK time.time(), never time.monotonic() (the stuck-open
  defeater — a monotonic opened_at vs a persisted wall-clock value never elapses);
- half-open is SELF-DRIVEN (re-probes after reset_timeout with no external
  traffic) so a recovered source is never silently kept down;
- half-open-on-restart: a persisted-OPEN whose cooldown already elapsed probes
  immediately on reload;
- a DB read failure fails toward ALLOW (never silently blocks a source);
- flag default-OFF: when disabled, allow() never gates (signal-first), though it
  still records transitions for shadow-logging.
"""
import time

import pytest

from consensus_engine import config, db
from consensus_engine.utils.circuit_breaker import CircuitBreaker


@pytest.fixture
def enabled(monkeypatch):
    """Force the breaker flag ON (conftest leaves it at its OFF default)."""
    real = config.get
    cfg = {
        "circuit_breaker.enabled": True,
        "circuit_breaker.fail_max": 5,
        "circuit_breaker.reset_timeout_s": 120,
        "circuit_breaker.hard_max_open_s": 1800,
    }
    monkeypatch.setattr(config, "get", lambda k, d=None: cfg.get(k, real(k, d)))


class _Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


def test_closed_by_default_allows(enabled):
    cb = CircuitBreaker(now_fn=_Clock())
    assert cb.allow("brave") is True


async def test_opens_after_fail_max(enabled):
    clk = _Clock()
    cb = CircuitBreaker(now_fn=clk)
    for _ in range(4):
        await cb.record_failure("brave", reason="transient")
    assert cb.allow("brave") is True, "4 failures should not open (fail_max=5)"
    await cb.record_failure("brave", reason="transient")
    assert cb.allow("brave") is False, "5th failure must open the breaker"


async def test_immediate_open_on_definitive_failure(enabled):
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.record_failure("brave", reason="402", immediate=True)
    assert cb.allow("brave") is False, "a definitive 402 opens on the first failure"


async def test_self_driven_half_open_after_reset(enabled):
    clk = _Clock()
    cb = CircuitBreaker(now_fn=clk)
    await cb.record_failure("brave", reason="402", immediate=True)
    assert cb.allow("brave") is False
    # advance PAST reset_timeout with NO external traffic
    clk.advance(121)
    assert cb.allow("brave") is True, "must self-drive a half-open probe"
    # only ONE probe in flight until it resolves
    assert cb.allow("brave") is False, "second concurrent probe must be denied"


async def test_half_open_success_closes(enabled):
    clk = _Clock()
    cb = CircuitBreaker(now_fn=clk)
    await cb.record_failure("brave", reason="402", immediate=True)
    clk.advance(121)
    assert cb.allow("brave") is True  # probe granted
    await cb.record_success("brave")
    assert cb.allow("brave") is True, "success must close the breaker"
    assert cb._state["brave@v1"]["state"] == "closed"


async def test_half_open_failure_reopens(enabled):
    clk = _Clock()
    cb = CircuitBreaker(now_fn=clk)
    await cb.record_failure("brave", reason="402", immediate=True)
    clk.advance(121)
    assert cb.allow("brave") is True  # probe granted
    await cb.record_failure("brave", reason="402", immediate=True)
    assert cb.allow("brave") is False, "a failed probe must re-open"


async def test_disabled_never_gates_but_records(monkeypatch):
    """Flag OFF (default): allow() must never block (signal-first), but the
    breaker still tracks state so we can shadow-log before flipping ON."""
    cb = CircuitBreaker(now_fn=_Clock())  # flag not forced -> default OFF
    for _ in range(6):
        await cb.record_failure("brave", reason="transient")
    assert cb._state["brave@v1"]["state"] == "open", "state is tracked even when disabled"
    assert cb.allow("brave") is True, "disabled breaker must not gate"


async def test_durable_reason_persists_transient_does_not(enabled):
    await db.init_db()  # conftest points DB_PATH at a temp file
    cb = CircuitBreaker(now_fn=_Clock())
    await cb.record_failure("brave", reason="402", immediate=True)      # durable
    await cb.record_failure("exa", reason="transient", immediate=True)  # not durable
    rows = await db.cb_load_open()
    keys = {r["source_key"] for r in rows}
    assert "brave@v1" in keys, "402 (durable) must persist"
    assert "exa@v1" not in keys, "transient must NOT persist"


async def test_half_open_on_restart_not_stuck(enabled):
    """The monotonic-vs-wallclock defeater: a persisted OPEN row written with a
    wall-clock opened_at in the past must probe immediately on reload. If the
    code compared a fresh monotonic clock to the persisted wall-clock opened_at,
    the probe would never fire and this test would FAIL."""
    await db.init_db()
    past = time.time() - 3600  # opened an hour ago, well past reset_timeout
    await db.cb_save({
        "source_key": "brave@v1", "state": "open", "failure_count": 5,
        "opened_at": past, "open_reason": "402",
        "next_probe_at": past + 120, "last_alerted_at": None,
    })
    # a fresh breaker using the REAL wall clock (the production default)
    cb = CircuitBreaker()  # now_fn defaults to time.time
    await cb.load_persisted()
    assert cb.allow("brave") is True, "a long-elapsed persisted OPEN must probe, not stick"


async def test_db_read_failure_fails_open(enabled, monkeypatch):
    """If loading persisted state raises, the breaker must start clean (closed)
    and allow calls — a DB hiccup can never silently block a source."""
    async def boom():
        raise RuntimeError("sqlite unavailable")
    monkeypatch.setattr(db, "cb_load_open", boom)
    cb = CircuitBreaker()
    await cb.load_persisted()  # must swallow the error
    assert cb.allow("brave") is True
