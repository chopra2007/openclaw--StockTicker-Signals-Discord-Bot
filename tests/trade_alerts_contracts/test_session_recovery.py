"""M5.5 durable session and delivery recovery over the existing store.

Covers the applicable AT-06 (nothing sent without persistence, one mechanical
event per intent, uncertain sends stay UNKNOWN, expired intents never send),
AT-07 (a continuous run and a crash/resume run store identical facts) and AT-10
(recovery reads one isolated temporary database only) slices. Delivery stays
recorded; no live sink, credential, network or application is used.
"""

from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.alert_delivery import (
    DeliveryIntent, DeliveryResult, DiscordSink, RecordingSink, RenderedAlert, SendReceipt,
    deliver_candidate,
)
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.historical_replay import (
    HistoricalReplayRunner, RecordingReplaySink,
)
from consensus_engine.session_recovery import (
    RECOVERY_VERSION, DurableSessionRecovery,
)
from consensus_engine.state_transitions import StateTransitionEngine
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_models import (
    DeliveryRecord, HumanDecisionRecord, OptionRecommendation, OutcomeRecord, RecordError,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_alert_delivery import bound_assembly, candidate
from test_historical_replay import spec
from test_state_transitions import scope
from test_strategy_interface import START, FixtureStrategy, context, quote_decision


LATER = START + timedelta(seconds=5)


async def open_db(path):
    db.DB_PATH = str(path)
    db._db = None
    return await db.init_db()


async def opened(path):
    connection = await open_db(path)
    store = ResearchEventStore(connection)
    transitions = SQLiteTransitionStore(connection)
    return store, transitions, DurableSessionRecovery(store=store, transitions=transitions)


def assembled(row, session):
    return replace(bound_assembly(row, session), candidate=row)


def counting_sink():
    """Count send requests without changing the recording-only sink type."""
    sink = RecordingSink()
    sent = []
    original = sink.send

    async def send(rendered, *, at):
        sent.append(rendered.candidate.record_id)
        return await original(rendered, at=at)

    sink.send = send
    return sink, sent


async def save_pending(store, row, session, intent_id, *, options=None, started=False):
    """Write exactly what a session persists before (and during) a send."""
    rendered = RenderedAlert(row, options)
    pending = DeliveryRecord(record_id=intent_id, candidate_id=row.record_id,
                             attempted_at=START, sink="recording", status="PENDING")
    await store.save_intent(DeliveryIntent(pending, rendered, assembled(row, session)))
    if started:
        await store.save_result(DeliveryResult(
            DeliveryRecord(record_id=intent_id + ":started", candidate_id=row.record_id,
                           attempted_at=START, sink="recording", status="SEND_STARTED"),
            rendered, "SINK_STARTED", 0))
    return rendered


async def test_versioned_state_recovery_reports_stored_position_and_state(tmp_path):
    path = tmp_path / "state.db"
    connection = await open_db(path)
    transitions = SQLiteTransitionStore(connection)
    engine = StateTransitionEngine(scope(), transitions)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=engine, store=ResearchEventStore(connection), sink=RecordingReplaySink())
    supplied = tuple(context(START + timedelta(seconds=offset),
                             quote=quote_decision(START + timedelta(seconds=offset),
                                                  stale=offset == 0))
                     for offset in (0, 1, 2))
    await runner.run(supplied)
    live = engine.current_state()
    await db.close_db()

    _, _, recovery = await opened(path)
    restored = await recovery.restore_state(scope())
    assert restored.state == live == StrategyState("ALERT_TRIGGERED", "FIXTURE_ONLY")
    assert restored.position == restored.entry_count == 3
    assert restored.last_record_id == engine.last_entry.transition.record_id
    assert restored.as_dict()["recovery_version"] == RECOVERY_VERSION
    assert restored.as_dict()["stream_id"] == scope().stream_id
    restored_engine = await recovery.restore_engine(scope())
    assert restored_engine.last_entry == engine.last_entry
    await db.close_db()


@pytest.mark.parametrize("case", ("gap", "used_owner", "foreign_scope"))
async def test_state_recovery_fails_closed_on_an_incomplete_chain(tmp_path, case):
    path = tmp_path / f"chain-{case}.db"
    connection = await open_db(path)
    transitions = SQLiteTransitionStore(connection)
    engine = StateTransitionEngine(scope(), transitions)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=engine, store=ResearchEventStore(connection), sink=RecordingReplaySink())
    await runner.run((context(START, quote=quote_decision(START, stale=True)), context(START)))
    stored = await transitions.read(scope())
    fresh = StateTransitionEngine(scope(), transitions)
    if case == "gap":
        with pytest.raises(RecordError, match="complete ordered chain"):
            await fresh.restore(stored[1:])
    elif case == "used_owner":
        await fresh.restore(stored)
        with pytest.raises(RecordError, match="unused transition owner"):
            await fresh.restore(stored)
    else:
        other = StateTransitionEngine(scope(direction="SHORT"), transitions)
        with pytest.raises(RecordError, match="owner scope"):
            await other.restore(stored)
    await db.close_db()


async def test_database_failure_before_persistence_sends_nothing(tmp_path):
    store, _, recovery = await opened(tmp_path / "no-persistence.db")
    connection = store._connection
    row, session = candidate()
    sink, sent = counting_sink()
    await connection.executescript("""
        CREATE TRIGGER m55_forced_failure BEFORE INSERT ON trade_alerts_research_events_v1
        WHEN NEW.kind = 'DELIVERY_INTENT' BEGIN
            SELECT RAISE(FAIL, 'synthetic intent write failure');
        END;
    """)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic intent write failure"):
        await deliver_candidate(row, session=session, assembly=assembled(row, session),
                                record_id="m55-unpersisted", at=START, sink=sink,
                                save_intent=store.save_intent, save_result=store.save_result)
    assert sent == []
    assert await store.read_all() == ()
    assert await recovery.plan(at=START) == ()
    await db.close_db()


async def test_crash_before_send_retries_once_and_keeps_one_final_fact(tmp_path):
    path = tmp_path / "crash-before-send.db"
    store, _, _ = await opened(path)
    row, session = candidate()
    await save_pending(store, row, session, "m55-before-send")
    await db.close_db()

    store, _, recovery = await opened(path)
    plan = await recovery.plan(at=START)
    assert [(item.action, item.reason, item.attempts) for item in plan] == [
        ("RETRY", "NO_SEND_RECORDED", 0)]
    sink, sent = counting_sink()
    applied = await recovery.resume(at=START, sink=sink)
    assert sent == [row.record_id]
    assert [(item.action, item.final_status) for item in applied] == [
        ("RETRY", "REJECTED_BEFORE_SEND")]
    assert {item.record_id: item.status
            for item in await recovery.delivery_facts(row.record_id)} == {
        "m55-before-send": "PENDING",
        "m55-before-send:recovery:1:started": "SEND_STARTED",
        "m55-before-send:result": "REJECTED_BEFORE_SEND"}

    settled = await recovery.plan(at=START)
    assert [(item.action, item.final_status) for item in settled] == [
        ("COMPLETE", "REJECTED_BEFORE_SEND")]
    before = await store.read_all()
    assert await recovery.resume(at=START, sink=sink) == settled
    assert await store.read_all() == before
    assert sent == [row.record_id]
    await db.close_db()


async def test_expired_intent_never_sends_on_recovery(tmp_path):
    path = tmp_path / "expired.db"
    store, _, _ = await opened(path)
    row, session = candidate()
    await save_pending(store, row, session, "m55-expired")
    await db.close_db()

    store, _, recovery = await opened(path)
    assert row.expires_at < LATER
    plan = await recovery.plan(at=LATER)
    assert [(item.action, item.reason) for item in plan] == [
        ("EXPIRED_NO_SEND", "EXPIRED_BEFORE_RECOVERY")]
    sink, sent = counting_sink()
    applied = await recovery.resume(at=LATER, sink=sink)
    assert sent == []
    assert applied[0].final_status == "REJECTED_BEFORE_SEND"
    final = await store.read("m55-expired:result")
    assert json.loads(final["record_json"])["status"] == "REJECTED_BEFORE_SEND"
    envelope = json.loads((await store.read("m51:result:m55-expired:result"))["record_json"])
    assert envelope["reason"] == "EXPIRED_ON_RECOVERY"
    await db.close_db()


async def test_crash_after_send_started_stays_unknown_without_resend(tmp_path):
    path = tmp_path / "crash-after-send.db"
    store, _, _ = await opened(path)
    row, session = candidate()
    await save_pending(store, row, session, "m55-uncertain", started=True)
    await db.close_db()

    store, _, recovery = await opened(path)
    plan = await recovery.plan(at=START)
    assert [(item.action, item.reason, item.attempts) for item in plan] == [
        ("UNCERTAIN_NO_RESEND", "CRASH_AFTER_SEND_STARTED", 1)]
    sink, sent = counting_sink()
    applied = await recovery.resume(at=START, sink=sink)
    assert sent == []
    assert applied[0].final_status == "UNKNOWN"
    facts = await recovery.delivery_facts(row.record_id)
    assert {item.record_id: item.status for item in facts} == {
        "m55-uncertain": "PENDING",
        "m55-uncertain:started": "SEND_STARTED",
        "m55-uncertain:result": "UNKNOWN"}
    assert all(item.message_reference is None for item in facts)
    envelope = json.loads((await store.read("m51:result:m55-uncertain:result"))["record_json"])
    assert envelope["reason"] == "UNCERTAIN_AFTER_CRASH"
    # A later restart cannot convert the uncertain fact into a blind resend.
    assert [item.action for item in await recovery.plan(at=START)] == ["COMPLETE"]
    assert (await recovery.resume(at=START, sink=sink))[0].final_status == "UNKNOWN"
    assert sent == []
    await db.close_db()


async def test_completed_delivery_is_never_resent(tmp_path):
    path = tmp_path / "complete.db"
    store, _, _ = await opened(path)
    row, session = candidate()
    result = await deliver_candidate(row, session=session, assembly=assembled(row, session),
                                     record_id="m55-complete", at=START,
                                     save_intent=store.save_intent, save_result=store.save_result)
    assert result.record.status == "REJECTED_BEFORE_SEND"
    await db.close_db()

    store, _, recovery = await opened(path)
    before = await store.read_all()
    sink, sent = counting_sink()
    applied = await recovery.resume(at=START, sink=sink)
    assert [(item.action, item.final_status) for item in applied] == [
        ("COMPLETE", "REJECTED_BEFORE_SEND")]
    assert sent == []
    assert await store.read_all() == before
    await db.close_db()


async def test_offline_test_retry_records_one_confirmation(tmp_path):
    path = tmp_path / "offline-retry.db"
    store, _, _ = await opened(path)
    row, session = candidate()
    await save_pending(store, row, session, "m55-offline")
    await db.close_db()

    store, _, recovery = await opened(path)

    async def send(rendered):
        return SendReceipt("CONFIRMED_DELIVERED", "SUPPLIED_FIXTURE_RECEIPT", START, 1,
                           "synthetic-confirmation")

    applied = await recovery.resume(at=START, sink=DiscordSink(send), mode="offline_test")
    assert [(item.action, item.final_status, item.attempts) for item in applied] == [
        ("RETRY", "CONFIRMED_DELIVERED", 1)]
    facts = {item.record_id: (item.status, item.message_reference)
             for item in await recovery.delivery_facts(row.record_id)}
    assert facts == {
        "m55-offline": ("PENDING", None),
        "m55-offline:recovery:1:started": ("SEND_STARTED", None),
        "m55-offline:result": ("CONFIRMED_DELIVERED", "synthetic-confirmation")}
    assert [item.action for item in await recovery.plan(at=START)] == ["COMPLETE"]
    await db.close_db()


@pytest.mark.parametrize("mode", ("replay", "shadow"))
async def test_recorded_modes_refuse_a_transport_sink(tmp_path, mode):
    _, _, recovery = await opened(tmp_path / f"sink-{mode}.db")

    async def send(rendered):
        raise AssertionError("must not be called")

    with pytest.raises(RecordError, match="recording sink"):
        await recovery.resume(at=START, sink=DiscordSink(send), mode=mode)
    with pytest.raises(RecordError, match="no live recovery mode"):
        await recovery.resume(at=START, mode="live")
    await db.close_db()


async def test_recovered_alert_must_match_the_stored_intent(tmp_path):
    path = tmp_path / "altered-intent.db"
    store, _, _ = await opened(path)
    row, session = candidate()

    class AlteredRendering:
        def __init__(self, original):
            self.candidate = original.candidate
            self.options = original.options
            self.text = "ALTERED SUPPLIED TEXT"

    original = RenderedAlert(row)
    pending = DeliveryRecord(record_id="m55-altered", candidate_id=row.record_id,
                             attempted_at=START, sink="recording", status="PENDING")
    await store.save_intent(DeliveryIntent(pending, AlteredRendering(original),
                                           assembled(row, session)))
    await db.close_db()

    store, _, recovery = await opened(path)
    sink, sent = counting_sink()
    with pytest.raises(RecordError, match="differs from the stored intent"):
        await recovery.resume(at=START, sink=sink)
    assert sent == []
    assert await store.read("m55-altered:result") is None
    await db.close_db()


async def test_acknowledgment_and_outcome_stay_separate_records(tmp_path):
    path = tmp_path / "acknowledgment.db"
    store, _, recovery = await opened(path)
    row, session = candidate()
    acknowledgment = HumanDecisionRecord(record_id="m55-acknowledgment",
                                         candidate_id=row.record_id, decided_at=LATER,
                                         decision="ACCEPTED", note="Synthetic review only")
    with pytest.raises(RecordError, match="stored candidate"):
        await recovery.record_acknowledgment(acknowledgment, session=session.session)
    await deliver_candidate(row, session=session, assembly=assembled(row, session),
                            record_id="m55-acknowledged", at=START,
                            save_intent=store.save_intent, save_result=store.save_result)
    stored = await recovery.record_acknowledgment(acknowledgment, session=session.session)
    assert stored["kind"] == "ACKNOWLEDGMENT"
    assert await recovery.acknowledgments() == (acknowledgment,)
    early = replace(acknowledgment, record_id="m55-early", decided_at=row.created_at
                    - timedelta(seconds=1))
    with pytest.raises(RecordError, match="cannot precede"):
        await recovery.record_acknowledgment(early, session=session.session)
    conflicting = replace(acknowledgment, decision="REJECTED")
    with pytest.raises(RecordError, match="conflicts"):
        await recovery.record_acknowledgment(conflicting, session=session.session)
    outcome = OutcomeRecord(record_id="m55-outcome", candidate_id=row.record_id,
                            evaluated_at=LATER, horizon="SESSION_CLOSE",
                            coverage_status="UNRESOLVED", result="UNKNOWN",
                            data_quality="UNKNOWN")
    await store.append(outcome, session=session.session, recorded_at=LATER)
    # Acknowledgment, outcome and delivery stay three separate stored facts.
    assert {item["kind"] for item in await store.read_all()} >= {
        "ACKNOWLEDGMENT", "OUTCOME", "DELIVERY"}
    assert {item.record_id: item.status
            for item in await recovery.delivery_facts(row.record_id)} == {
        "m55-acknowledged": "PENDING", "m55-acknowledged:started": "SEND_STARTED",
        "m55-acknowledged:result": "REJECTED_BEFORE_SEND"}
    await db.close_db()
    store, _, recovery = await opened(path)
    assert await recovery.acknowledgments() == (acknowledgment,)
    await db.close_db()


async def test_acknowledgment_requires_a_final_delivery_fact(tmp_path):
    store, _, recovery = await opened(tmp_path / "unacknowledgeable.db")
    row, session = candidate()
    await save_pending(store, row, session, "m55-unfinished")
    acknowledgment = HumanDecisionRecord(record_id="m55-premature", candidate_id=row.record_id,
                                         decided_at=LATER, decision="ACCEPTED")
    with pytest.raises(RecordError, match="final delivery fact"):
        await recovery.record_acknowledgment(acknowledgment, session=session.session)
    await db.close_db()


async def test_recovery_requires_one_shared_temporary_database(tmp_path, monkeypatch):
    store, transitions, recovery = await opened(tmp_path / "isolated.db")
    other = SQLiteTransitionStore(db.AsyncConnection(sqlite3.connect(tmp_path / "other.db")))
    with pytest.raises(RecordError, match="same isolated database"):
        await DurableSessionRecovery(store=store, transitions=other).check_isolated_storage()
    with pytest.raises(RecordError, match="isolated research store"):
        DurableSessionRecovery(store=object(), transitions=transitions)
    with pytest.raises(RecordError, match="transition store"):
        DurableSessionRecovery(store=store, transitions=object())
    with pytest.raises(RecordError, match="transition store"):
        await DurableSessionRecovery(store=store).restore_state(scope())
    monkeypatch.setenv("TMPDIR", str(tmp_path / "different-root"))
    with pytest.raises(RecordError, match="temporary storage"):
        await recovery.plan(at=START)
    await db.close_db()


async def replay_all(connection, contexts, engine=None):
    store = ResearchEventStore(connection)
    transitions = SQLiteTransitionStore(connection)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=engine or StateTransitionEngine(scope(), transitions),
        store=store, sink=RecordingReplaySink())
    result = await runner.run(contexts)
    return result, await store.read_all(), await transitions.read(scope())


async def test_crash_resume_replay_matches_the_continuous_run(tmp_path):
    supplied = tuple(context(START + timedelta(seconds=offset),
                             quote=quote_decision(START + timedelta(seconds=offset),
                                                  stale=offset in (-1, 2)))
                     for offset in (-1, 0, 1, 2))
    continuous, continuous_rows, continuous_entries = await replay_all(
        await open_db(tmp_path / "continuous.db"), supplied)
    await db.close_db()

    path = tmp_path / "crash-resume.db"
    interrupted, _, _ = await replay_all(await open_db(path), supplied[:2])
    await db.close_db()

    store, transitions, recovery = await opened(path)
    restored = await recovery.restore_state(scope())
    assert restored.position == 2
    assert restored.state == StrategyState("SETUP_FORMING", "FIXTURE_ONLY")
    assert len(interrupted.observations) == 2
    assert [entry.transition.record_id for entry in await transitions.read(scope())] == [
        entry.transition.record_id for entry in continuous_entries[:2]]
    # Saved facts are idempotent, so the resumed session replays from the start.
    resumed, resumed_rows, resumed_entries = await replay_all(store._connection, supplied)
    assert resumed.to_json() == continuous.to_json()
    assert resumed.fingerprint == continuous.fingerprint
    assert resumed_rows == continuous_rows
    assert [entry.to_json() for entry in resumed_entries] == [
        entry.to_json() for entry in continuous_entries]
    assert (await recovery.restore_state(scope())).position == 4
    await db.close_db()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_interrupted_session_recovery_recording_end_to_end(tmp_path, direction):
    path = tmp_path / f"recovery-{direction.lower()}.db"
    store, _, _ = await opened(path)
    live, session = candidate(direction=direction, record_id="m55-live-candidate",
                              expires_at=START + timedelta(minutes=10))
    stale, _ = candidate(direction=direction, record_id="m55-stale-candidate")
    uncertain, _ = candidate(direction=direction, record_id="m55-uncertain-candidate")
    options = OptionRecommendation(record_id="m55-options", candidate_id=live.record_id,
                                   status="UNAVAILABLE", ranked_at=START,
                                   reasons=("NO_SUPPLIED_CHAIN",), policy_version="FIXTURE_ONLY")
    await save_pending(store, live, session, "m55-a-live", options=options)
    await save_pending(store, stale, session, "m55-b-stale")
    await save_pending(store, uncertain, session, "m55-c-started", started=True)
    await db.close_db()

    store, _, recovery = await opened(path)
    sink, sent = counting_sink()
    plan = await recovery.plan(at=LATER)
    applied = await recovery.resume(at=LATER, sink=sink)
    settled = await recovery.plan(at=LATER)
    assert [item.action for item in plan] == [
        "RETRY", "EXPIRED_NO_SEND", "UNCERTAIN_NO_RESEND"]
    assert [item.final_status for item in applied] == [
        "REJECTED_BEFORE_SEND", "REJECTED_BEFORE_SEND", "UNKNOWN"]
    assert [item.action for item in settled] == ["COMPLETE"] * 3
    # Only the unexpired intent with no recorded send reached the recording sink.
    assert sent == [live.record_id]
    proof = {
        "recovery_version": RECOVERY_VERSION,
        "direction": direction,
        "plan": [item.as_dict() for item in plan],
        "applied": [item.as_dict() for item in applied],
        "settled": [item.as_dict() for item in settled],
        "sent": list(sent),
        "delivery_facts": {row.record_id: [item.as_dict() for item
                                           in await recovery.delivery_facts(row.record_id)]
                           for row in (live, stale, uncertain)},
    }
    rows = await store.read_all()
    await db.close_db()

    store, _, recovery = await opened(path)
    assert await store.read_all() == rows
    assert await recovery.plan(at=LATER) == settled
    proof["reopen_equal"] = True
    proof["row_count"] = len(rows)
    text = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    Path(os.environ["TMPDIR"], f"m55-session-recovery-{direction.lower()}-proof.json").write_text(
        text + "\n")
    await db.close_db()
