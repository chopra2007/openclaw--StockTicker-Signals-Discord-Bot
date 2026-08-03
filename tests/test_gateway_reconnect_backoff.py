"""Regression guard for the 2026-07-20 "bot went deaf" incident.

`run()` waits before each Discord Gateway reconnect and doubles that wait every
time. The wait was never reset after a connection succeeded, so a long-lived
listener ratcheted to the ceiling and stayed there: from Jul 19 23:27 onward
every reconnect waited the full 120s. Discord asks bots to reconnect routinely
(op:7, then an INVALID_SESSION on the resume), so each event cost two ceiling
waits back to back — the bot was deaf for ~4 minutes, 10 times on Jul 20 alone
(~41 minutes total). Messages sent inside a window got no reply at all.

The fix: reaching READY means the endpoint is healthy, so the next drop starts
the escalation over. These tests pin both halves of that — the reset, and the
ceiling that bounds how long the bot can ever be deaf.
"""
import asyncio

import pytest

from consensus_engine.scanners import discord_tweetshift as mod
from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener


async def _collect_reconnect_waits(monkeypatch, *, reaches_ready: bool,
                                   rounds: int) -> list:
    """Drive run() through `rounds` reconnects, returning each wait in seconds.

    `_connect_once` returns immediately, standing in for a connection that
    dropped; when `reaches_ready` it first sets the flag READY would have set.
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    monkeypatch.setattr(listener, "_load_config", lambda: None)
    listener._token = "token"
    listener._feed_channel_id = "123"

    waits: list = []

    async def _fake_connect_once():
        if reaches_ready:
            listener._reached_ready_since_backoff_reset = True

    async def _fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()  # we never await the real stop_event.wait()
        waits.append(timeout)
        if len(waits) >= rounds:
            listener._stop = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(listener, "_connect_once", _fake_connect_once)
    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)

    await listener.run(asyncio.Event())
    return waits


async def test_backoff_resets_after_every_healthy_connection(monkeypatch):
    """A connection that reached READY must reset the wait to the floor.

    This is the actual bug: without the reset the waits climb 5, 10, 20 ...
    and never come back down, even though every connection is succeeding.
    """
    waits = await _collect_reconnect_waits(monkeypatch, reaches_ready=True, rounds=6)

    assert waits == [mod._RECONNECT_BACKOFF_START] * 6, (
        f"a healthy reconnect must always wait the floor; got {waits!r}"
    )


async def test_backoff_still_escalates_when_never_healthy(monkeypatch):
    """A genuinely broken endpoint must still back off, up to the ceiling.

    The reset must not turn the backoff into a hot reconnect loop against a
    Discord outage.
    """
    waits = await _collect_reconnect_waits(monkeypatch, reaches_ready=False, rounds=6)

    assert waits[0] == mod._RECONNECT_BACKOFF_START
    assert waits == sorted(waits), f"backoff must be non-decreasing; got {waits!r}"
    assert waits[-1] == mod._RECONNECT_BACKOFF_MAX
    assert max(waits) <= mod._RECONNECT_BACKOFF_MAX


async def test_ready_clears_the_reset_flag_so_it_is_one_shot(monkeypatch):
    """One READY resets one wait — a stale flag must not pin it at the floor.

    Rounds 2+ never reach READY here, so they must escalate normally.
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    monkeypatch.setattr(listener, "_load_config", lambda: None)
    listener._token = "token"
    listener._feed_channel_id = "123"

    waits: list = []
    connects = {"n": 0}

    async def _fake_connect_once():
        connects["n"] += 1
        if connects["n"] == 1:  # only the first connection reaches READY
            listener._reached_ready_since_backoff_reset = True

    async def _fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        waits.append(timeout)
        if len(waits) >= 4:
            listener._stop = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(listener, "_connect_once", _fake_connect_once)
    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)

    await listener.run(asyncio.Event())

    assert waits == [5, 10, 20, 30], f"expected one reset then escalation; got {waits!r}"


def test_ceiling_bounds_worst_case_deafness():
    """The ceiling is what caps how long the bot can be unreachable.

    Discord's routine reconnect is a drop plus a failed resume — two waits back
    to back. At the old 120s ceiling that was ~4 minutes of silence per event.
    """
    worst_case_seconds = mod._RECONNECT_BACKOFF_MAX * 2
    assert worst_case_seconds <= 60, (
        f"two chained reconnects would leave the bot deaf for "
        f"{worst_case_seconds}s — too long for a user-facing bot"
    )


async def test_ready_sets_the_backoff_reset_flag(monkeypatch):
    """Wire check: the flag run() consumes is the one READY sets."""
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    reports = []

    async def _fake_report(*, deaf):
        reports.append(deaf)

    monkeypatch.setattr(listener, "_report_listening", _fake_report)
    assert listener._reached_ready_since_backoff_reset is False

    await listener._handle_dispatch("READY", {
        "session_id": "s1",
        "user": {"id": "bot-1"},
    })

    assert listener._reached_ready_since_backoff_reset is True
    assert listener._last_ready_monotonic > 0
    assert listener._disconnected_since == 0.0, "READY means we can hear again"
    assert reports == [False], "READY must clear any standing deaf alert"


async def test_resume_also_clears_the_deaf_clock(monkeypatch):
    """A resumed session is a live session.

    Discord answers most reconnects with RESUMED, not READY. While only READY
    moved the clock, the gap was measured from the process's first connect, so
    after a few days of ordinary resumes every blip reported days of deafness
    (false alerts, 2026-07-26 → 2026-08-03).
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    reports = []

    async def _fake_report(*, deaf):
        reports.append(deaf)

    monkeypatch.setattr(listener, "_report_listening", _fake_report)
    listener._disconnected_since = 1.0
    listener._reached_ready_since_backoff_reset = False

    await listener._handle_dispatch("RESUMED", {})

    assert listener._disconnected_since == 0.0
    assert listener._reached_ready_since_backoff_reset is True
    assert reports == [False], "RESUMED must clear any standing deaf alert"


async def test_long_healthy_connection_does_not_report_stale_deafness(monkeypatch):
    """The bug this replaced: uptime reported as downtime.

    Connected for four days, then one routine drop. The gap is seconds, so the
    listener must stay quiet — even though the last connect was days ago.
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    monkeypatch.setattr(listener, "_load_config", lambda: None)
    listener._token = "token"
    listener._feed_channel_id = "123"
    # Connected four days ago, and still connected as of the drop.
    listener._last_ready_monotonic = 1.0
    listener._disconnected_since = 0.0

    reports = []

    async def _fake_report(*, deaf):
        reports.append(deaf)

    async def _fake_connect_once():
        return None

    monkeypatch.setattr(listener, "_report_listening", _fake_report)
    monkeypatch.setattr(listener, "_connect_once", _fake_connect_once)

    async def _fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        listener._stop = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)
    monkeypatch.setattr(mod.time, "monotonic", lambda: 1.0 + 4 * 86400)

    await listener.run(asyncio.Event())

    assert reports == [], "four days of uptime is not four days of deafness"


async def test_prolonged_deafness_raises_an_alert(monkeypatch):
    """Going deaf is invisible from outside — it has to announce itself.

    On 2026-07-20 the bot was unreachable for ~4 minutes at a time, 10 times in
    one day, and nothing said so. The user only found out by asking it something
    and getting silence.
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    monkeypatch.setattr(listener, "_load_config", lambda: None)
    listener._token = "token"
    listener._feed_channel_id = "123"
    # The session dropped well past the alert threshold ago and never came back.
    listener._disconnected_since = 1.0

    reports = []

    async def _fake_report(*, deaf):
        reports.append(deaf)

    async def _fake_connect_once():
        return None

    monkeypatch.setattr(listener, "_report_listening", _fake_report)
    monkeypatch.setattr(listener, "_connect_once", _fake_connect_once)

    async def _fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        listener._stop = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)
    monkeypatch.setattr(mod.time, "monotonic",
                        lambda: 1.0 + mod._DEAF_ALERT_AFTER_SECONDS + 1)

    await listener.run(asyncio.Event())

    assert reports == [True], f"expected one deaf alert; got {reports!r}"


async def test_routine_reconnect_does_not_cry_wolf(monkeypatch):
    """A reconnect inside the normal window must stay silent.

    Discord asks bots to reconnect all day; alerting on each one would train
    the user to ignore #errors.
    """
    listener = DiscordTweetShiftListener(on_tweet=lambda _: None)
    monkeypatch.setattr(listener, "_load_config", lambda: None)
    listener._token = "token"
    listener._feed_channel_id = "123"
    listener._disconnected_since = 1.0

    reports = []

    async def _fake_report(*, deaf):
        reports.append(deaf)

    async def _fake_connect_once():
        return None

    monkeypatch.setattr(listener, "_report_listening", _fake_report)
    monkeypatch.setattr(listener, "_connect_once", _fake_connect_once)

    async def _fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        listener._stop = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)
    # Only a few seconds since the drop — a routine reconnect.
    monkeypatch.setattr(mod.time, "monotonic", lambda: 6.0)

    await listener.run(asyncio.Event())

    assert reports == [], "a routine reconnect must not alert"
