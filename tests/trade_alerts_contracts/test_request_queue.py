"""M0.2D recorded-load contracts for the offline shared request queue."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine.request_queue import (
    OfflineRequestQueue, QueueError, QueuePolicy, RecordedProvider, RecordedReply,
    REQUEST_LIMITS,
)


NOW = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)


def _queue(tmp_path, **changes):
    return OfflineRequestQueue(tmp_path / "shared.sqlite3", QueuePolicy(enabled=True, **changes))


def _reply(*ids, elapsed=0.1, status=200):
    return RecordedProvider({key: RecordedReply(status, elapsed) for key in ids})


def test_queue_is_off_by_default_and_cannot_accept_work(tmp_path):
    queue = OfflineRequestQueue(tmp_path / "off.sqlite3")
    with pytest.raises(QueueError, match="disabled"):
        queue.enqueue("i1", "command", "interactive", "quote", NOW)


def test_fixed_policy_records_priorities_expiry_and_timeouts():
    assert QueuePolicy().__dict__ == {
        "enabled": False, "account_ceiling": 110, "ceiling_window_seconds": 60,
        "maximum_length": 256, "version": "M02D_REQUEST_QUEUE_V1",
    }


@pytest.mark.parametrize("elapsed", [float("nan"), float("inf"), -0.1])
def test_recorded_reply_time_must_be_finite_and_non_negative(elapsed):
    with pytest.raises(QueueError, match="finite and non-negative"):
        RecordedReply(200, elapsed)
    assert {name: (int(row.priority), row.expiry_seconds, row.timeout_seconds)
            for name, row in REQUEST_LIMITS.items()} == {
        "interactive": (0, 5, 2), "actionable": (1, 10, 5),
        "background": (2, 60, 15), "research": (3, 300, 15),
    }


def test_interactive_and_actionable_requests_win_over_older_research(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue("research", "replay", "research", "history", NOW)
    queue.enqueue("background", "scanner", "background", "quotes", NOW + timedelta(milliseconds=1))
    queue.enqueue("actionable", "alert", "actionable", "chain", NOW + timedelta(milliseconds=2))
    queue.enqueue("interactive", "command", "interactive", "quote", NOW + timedelta(milliseconds=3))
    provider = _reply("research", "background", "actionable", "interactive")
    for offset in range(4):
        assert queue.dispatch_next(NOW + timedelta(seconds=1, milliseconds=offset), provider) == "COMPLETED"
    assert provider.calls == ["interactive", "actionable", "background", "research"]


def test_expired_research_is_dropped_without_a_recorded_call(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue("stale", "replay", "research", "history", NOW)
    provider = _reply("stale")
    assert queue.dispatch_next(NOW + timedelta(seconds=300), provider) == "EMPTY"
    assert provider.calls == []
    assert queue.records()[0]["status"] == "EXPIRED"


def test_queue_overload_is_bounded_and_interactive_displaces_research(tmp_path):
    queue = _queue(tmp_path)
    for number in range(256):
        assert queue.enqueue(f"r{number:03}", "replay", "research", "history", NOW) == "QUEUED"
    assert queue.enqueue("interactive", "command", "interactive", "quote", NOW) == "QUEUED"
    assert queue.depth() == 256
    rows = {row["request_id"]: row for row in queue.records()}
    assert rows["interactive"]["status"] == "QUEUED"
    assert sum(row["status"] == "OVERLOAD_DROPPED" for row in rows.values()) == 1
    assert queue.enqueue("overflow", "replay", "research", "history", NOW) == "OVERLOAD_REJECTED"
    assert queue.depth() == 256
    assert {row["request_id"]: row for row in queue.records()}["overflow"]["status"] == "OVERLOAD_REJECTED"


def test_shared_account_ceiling_survives_reopen(tmp_path):
    queue = _queue(tmp_path)
    provider = _reply(*(f"i{number:03}" for number in range(111)))
    for number in range(111):
        queue.enqueue(f"i{number:03}", "command", "interactive", "quote", NOW)
    for _ in range(110):
        assert queue.dispatch_next(NOW + timedelta(seconds=1), provider) == "COMPLETED"
    reopened = _queue(tmp_path)
    assert reopened.dispatch_next(NOW + timedelta(seconds=1), provider) == "ACCOUNT_CEILING"
    assert len(provider.calls) == 110
    assert reopened.dispatch_next(NOW + timedelta(seconds=62), provider) == "EMPTY"
    assert len(provider.calls) == 110


def test_slow_recorded_reply_times_out_without_wall_clock_wait(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue("slow", "command", "interactive", "quote", NOW)
    assert queue.dispatch_next(NOW + timedelta(seconds=1), _reply("slow", elapsed=2.01)) == "TIMEOUT"
    row = queue.records()[0]
    assert row["timeout_seconds"] == 2
    assert row["status"] == "TIMEOUT"


@pytest.mark.parametrize(("status_code", "expected"), [
    (429, "THROTTLED"), (401, "AUTH_FAILURE"), (403, "AUTH_FAILURE"),
    (500, "PROVIDER_ERROR"),
])
def test_recorded_provider_failures_are_bounded_and_observable(tmp_path, status_code, expected):
    queue = _queue(tmp_path)
    queue.enqueue("failure", "scanner", "background", "quotes", NOW)
    assert queue.dispatch_next(
        NOW + timedelta(seconds=1), _reply("failure", status=status_code)
    ) == expected
    assert queue.records()[0]["status"] == expected


def test_arbitrary_callable_cannot_cross_the_offline_boundary(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue("i1", "command", "interactive", "quote", NOW)
    with pytest.raises(QueueError, match="recorded replies only"):
        queue.dispatch_next(NOW + timedelta(seconds=1), lambda request: RecordedReply(200, 0.1))
    assert queue.records()[0]["status"] == "QUEUED"


def test_duplicate_request_id_is_rejected_and_original_record_is_unchanged(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue("same", "command", "interactive", "quote", NOW)
    with pytest.raises(QueueError, match="already exists"):
        queue.enqueue("same", "replay", "research", "history", NOW + timedelta(seconds=1))
    row = queue.records()[0]
    assert row["consumer"] == "command"
    assert row["request_class"] == "interactive"


def test_recorded_load_proof_is_deterministic_and_contains_every_consumer(tmp_path):
    queue = _queue(tmp_path)
    rows = (
        ("research", "historical-replay", "research", "history"),
        ("collector", "forward-collector", "background", "chain"),
        ("scanner", "engine-scanner", "background", "quotes"),
        ("actionable", "trade-alert", "actionable", "chain"),
        ("interactive", "all-command", "interactive", "quote"),
    )
    for offset, row in enumerate(rows):
        queue.enqueue(*row, NOW + timedelta(milliseconds=offset))
    provider = _reply(*(row[0] for row in rows))
    while queue.dispatch_next(NOW + timedelta(seconds=1), provider) != "EMPTY":
        pass
    proof = {
        "policy": QueuePolicy().__dict__,
        "class_limits": {
            name: {"priority": int(limit.priority), "expiry_seconds": limit.expiry_seconds,
                   "timeout_seconds": limit.timeout_seconds}
            for name, limit in sorted(REQUEST_LIMITS.items())
        },
        "recorded_call_order": provider.calls,
        "records": queue.records(),
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    assert provider.calls == ["interactive", "actionable", "collector", "scanner", "research"]
    assert {row["consumer"] for row in proof["records"]} == {
        "historical-replay", "forward-collector", "engine-scanner", "trade-alert", "all-command",
    }
    Path(os.environ["TMPDIR"], "m02d-request-queue-proof.json").write_text(rendered)
