"""M4.2 software proof with explicit test-only rules and protected storage."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.state_transitions import (
    ENGINE_VERSION, StateTransitionEngine, TransitionEntry, TransitionRules, TransitionScope,
)
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_config import TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    Bar, FeatureSnapshot, RecordError, SETUP_STATES, StrategyStateTransition,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_strategy_interface import (
    START, VERSION, FixtureStrategy, context, history, metadata, quote_decision, session,
)


INITIAL = StrategyState("NOT_ELIGIBLE")
WATCHING = StrategyState("WATCHING", "FIXTURE_ONLY")
FORMING = StrategyState("SETUP_FORMING", "FIXTURE_ONLY")
TRIGGERED = StrategyState("ALERT_TRIGGERED", "FIXTURE_ONLY")
INVALID = StrategyState("INVALIDATED", "FIXTURE_ONLY")
EXPIRED = StrategyState("EXPIRED", "FIXTURE_ONLY")


def rules():
    return TransitionRules("M42_FIXTURE_RULES_V1", INITIAL, (
        (INITIAL, WATCHING), (WATCHING, FORMING), (FORMING, TRIGGERED),
        (TRIGGERED, WATCHING), (WATCHING, INVALID), (FORMING, EXPIRED),
        (INVALID, INITIAL), (EXPIRED, INITIAL),
    ))


def scope(**changes):
    values = dict(session=session(), symbol="SYNTH", instrument_type="EQUITY",
                  direction="LONG", strategy_id="CRVOL_ORB5", strategy_version=VERSION,
                  rules=rules())
    values.update(changes)
    return TransitionScope(**values)


def proposal(supplied=None, before=INITIAL, after=WATCHING, record_id="change-1", **changes):
    supplied = supplied or context()
    values = dict(
        record_id=record_id, metadata=metadata(supplied.evaluated_at),
        strategy_id="CRVOL_ORB5", strategy_version=VERSION, occurred_at=supplied.evaluated_at,
        from_state=before.state, from_substate=before.substate,
        to_state=after.state, to_substate=after.substate, reason="SYNTHETIC_SUPPLIED_RULE",
        input_record_ids=tuple(row.record_id for row in supplied.features),
        feature_snapshot_id=supplied.features[0].record_id if supplied.features else None,
    )
    values.update(changes)
    return StrategyStateTransition(**values)


class RecordingSink:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)


def engine(**changes):
    sink = RecordingSink()
    return StateTransitionEngine(scope(**changes), sink), sink


@pytest.mark.parametrize("state", sorted(SETUP_STATES))
async def test_each_canonical_state_accepts_only_explicit_entry_and_exit(state):
    old, new = StrategyState(state, "BEFORE"), StrategyState(state, "AFTER")
    subject, sink = engine(rules=TransitionRules("TEST_V1", old, ((old, new), (new, old))))
    first = proposal(before=old, after=new)
    await subject.apply(first, context=context())
    assert subject.current_state() == new
    await subject.apply(proposal(before=new, after=old, record_id="back"), context=context())
    assert subject.current_state() == old
    assert [entry.position for entry in sink.entries] == [1, 2]
    assert sink.entries[1].previous_record_id == first.record_id


@pytest.mark.parametrize("case", ["unknown_version", "mutable", "self_edge", "duplicate", "state"])
def test_rules_reject_ambiguous_or_mutable_contracts(case):
    changes = {
        "unknown_version": {"version": " unknown "},
        "mutable": {"allowed": [(INITIAL, WATCHING)]},
        "self_edge": {"allowed": ((INITIAL, INITIAL),)},
        "duplicate": {"allowed": ((INITIAL, WATCHING), (INITIAL, WATCHING))},
        "state": {"initial_state": "WATCHING"},
    }[case]
    with pytest.raises(RecordError):
        replace(rules(), **changes)


@pytest.mark.parametrize("changes", [
    {"strategy_version": "UNKNOWN"}, {"symbol": ""}, {"strategy_id": "OTHER"},
    {"direction": "SIDEWAYS"}, {"instrument_type": "OPTION"}, {"rules": None},
])
def test_scope_requires_explicit_canonical_identity(changes):
    with pytest.raises(RecordError):
        scope(**changes)


async def test_exact_substates_and_rules_reject_shortcuts_without_changing_facts():
    subject, sink = engine()
    first = await subject.apply(proposal(), context=context())
    frozen = first.to_json()
    for before, after in ((INITIAL, FORMING), (StrategyState("WATCHING"), FORMING),
                          (WATCHING, TRIGGERED), (WATCHING, WATCHING)):
        with pytest.raises(RecordError):
            await subject.apply(proposal(before=before, after=after, record_id="bad"), context=context())
        assert subject.last_entry is first and subject.current_state() == WATCHING
    assert len(sink.entries) == 1 and first.to_json() == frozen


@pytest.mark.parametrize("case", [
    "strategy", "version", "symbol", "type", "session", "context_direction", "context_config", "context_session",
    "context_symbol", "occurred", "availability", "normalization", "source",
    "unknown_feature", "unknown_input", "duplicate_input", "input_id_collision",
])
async def test_inconsistent_identity_time_and_references_never_reach_sink(case):
    supplied = context()
    change = proposal(supplied)
    edits = {
        "strategy": {"strategy_id": "OR_FAILURE_REV"}, "version": {"strategy_version": "OTHER_V1"},
        "symbol": {"metadata": metadata(instrument_id="OTHER")},
        "type": {"metadata": metadata(instrument_type="ETF")},
        "session": {"metadata": metadata(session="2026-07-07")},
        "occurred": {"occurred_at": START + timedelta(seconds=1)},
        "availability": {"metadata": metadata(available_time=START + timedelta(seconds=1))},
        "normalization": {"metadata": metadata(normalized_time=START + timedelta(seconds=1))},
        "source": {"metadata": metadata(source_time=START + timedelta(seconds=1))},
        "unknown_feature": {"feature_snapshot_id": "missing"},
        "unknown_input": {"input_record_ids": ("missing",)},
        "duplicate_input": {"input_record_ids": change.input_record_ids * 2},
        "input_id_collision": {"record_id": supplied.features[0].record_id},
    }
    if case in edits:
        change = replace(change, **edits[case])
    elif case == "context_direction":
        supplied = replace(supplied, direction="SHORT")
    elif case == "context_session":
        supplied = replace(supplied, session=replace(session(), record_id="other-session"))
    elif case == "context_config":
        cfg = TradeAlertsConfig({"schema_version": 1, "config_version": "OTHER_V1"})
        supplied = replace(supplied, session=replace(
            session(), config_version=cfg.config_version, config_hash=cfg.config_hash,
            config_json=cfg.canonical_json))
    else:
        supplied = context(symbol="OTHER", features=(), quote=None)
    subject, sink = engine()
    with pytest.raises(RecordError):
        await subject.apply(change, context=supplied)
    assert subject.current_state() == INITIAL and subject.last_entry is None and sink.entries == []


async def test_backward_time_and_changed_id_rejected_but_exact_latest_retry_is_harmless():
    subject, sink = engine()
    at = START + timedelta(seconds=1)
    supplied = context(at)
    change = proposal(supplied)
    first = await subject.apply(change, context=supplied)
    assert await subject.apply(StrategyStateTransition.from_json(change.to_json()), context=supplied) is first
    with pytest.raises(RecordError, match="backward"):
        await subject.apply(proposal(before=WATCHING, after=FORMING, record_id="old"), context=context())
    with pytest.raises(RecordError, match="ID"):
        await subject.apply(replace(change, reason="changed"), context=supplied)
    assert sink.entries == [first] and subject.current_state() == WATCHING


async def test_equal_time_explicit_call_order_is_preserved_across_awaited_writes():
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedSink(RecordingSink):
        async def append(self, entry):
            if not self.entries:
                entered.set()
                await release.wait()
            await super().append(entry)

    sink = PausedSink()
    subject = StateTransitionEngine(scope(), sink)
    first = asyncio.create_task(subject.apply(proposal(), context=context()))
    await entered.wait()
    second = asyncio.create_task(subject.apply(
        proposal(before=WATCHING, after=FORMING, record_id="change-2"), context=context()))
    assert subject.current_state() == INITIAL and subject.last_entry is None
    release.set()
    results = await asyncio.gather(first, second)
    assert [entry.position for entry in results] == [1, 2]
    assert sink.entries == results and subject.current_state() == FORMING


async def test_recording_failure_cannot_advance_state_and_retry_keeps_identity():
    class FailingSink(RecordingSink):
        fail = True

        async def append(self, entry):
            if self.fail:
                raise OSError("synthetic recording failure")
            await super().append(entry)

    sink = FailingSink()
    subject = StateTransitionEngine(scope(), sink)
    with pytest.raises(OSError, match="synthetic recording failure"):
        await subject.apply(proposal(), context=context())
    assert subject.current_state() == INITIAL and subject.last_entry is None
    sink.fail = False
    saved = await subject.apply(proposal(), context=context())
    assert saved.position == 1 and saved.transition.record_id == "change-1"


async def test_expiry_invalidation_and_same_session_reset_require_supplied_edges():
    subject, sink = engine()
    for index, (old, new) in enumerate(((INITIAL, WATCHING), (WATCHING, INVALID),
                                      (INVALID, INITIAL), (INITIAL, WATCHING),
                                      (WATCHING, FORMING), (FORMING, EXPIRED), (EXPIRED, INITIAL))):
        await subject.apply(proposal(before=old, after=new, record_id=f"edge-{index}"), context=context())
    frozen = [row.to_json() for row in sink.entries]
    with pytest.raises(RecordError, match="later session"):
        await subject.reset(session())
    await subject.reset(session("2026-07-07"))
    assert subject.last_entry is None and subject.current_state() == INITIAL
    with pytest.raises(RecordError, match="scope"):
        await subject.apply(proposal(), context=context())
    new_context = context(START + timedelta(days=1), session=session("2026-07-07"))
    new_entry = await subject.apply(proposal(new_context, record_id="new-day"), context=new_context)
    assert new_entry.position == 1 and new_entry.previous_record_id is None
    assert new_entry.scope.stream_id != sink.entries[0].scope.stream_id
    assert [row.to_json() for row in sink.entries[:-1]] == frozen


async def test_scope_entries_and_original_configuration_are_immutable():
    subject, sink = engine()
    config_json = subject.scope.session.config_json
    result = await subject.apply(proposal(), context=context())
    with pytest.raises(FrozenInstanceError):
        result.scope.direction = "SHORT"
    detached = json.loads(result.to_json())
    detached["transition"]["reason"] = "changed"
    assert result.transition.reason == "SYNTHETIC_SUPPLIED_RULE"
    assert subject.scope.session.config_json == config_json
    cfg = json.loads(config_json)
    assert not cfg["evaluation_enabled"] and not cfg["alerts"]["delivery_enabled"]
    assert all(not item["enabled"] for item in cfg["strategies"].values())
    assert not cfg["data"]["collection_enabled"] and not cfg["options"]["enabled"]
    assert not cfg["research"]["enabled"] and len(sink.entries) == 1


@pytest.mark.parametrize("position,previous", [(0, None), (True, None), (1, "old"),
                                               (2, None), (2, "change-1")])
def test_entry_requires_valid_order_and_distinct_predecessor(position, previous):
    with pytest.raises(RecordError):
        TransitionEntry(scope(), position, previous, proposal())


async def test_missing_market_inputs_can_record_an_explicit_invalidation():
    supplied = context(features=(), quote=None)
    subject, sink = engine(rules=TransitionRules("TEST_V1", INITIAL, ((INITIAL, INVALID),)))
    change = proposal(supplied, after=INVALID, reason="MANDATORY_INPUT_UNAVAILABLE")
    entry = await subject.apply(change, context=supplied)
    assert entry.transition.feature_snapshot_id is None and entry.transition.input_record_ids == ()
    assert sink.entries == [entry] and subject.current_state() == INVALID


async def test_sqlite_complete_record_round_trip_replay_and_conflicting_scope():
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    subject = StateTransitionEngine(scope(), store)
    first = await subject.apply(proposal(), context=context())
    second_change = proposal(before=WATCHING, after=FORMING, record_id="change-2")
    second = await subject.apply(second_change, context=context())
    assert await store.read(scope()) == (first, second)
    replay = StateTransitionEngine(scope(), store)
    assert await replay.apply(proposal(), context=context()) == first
    assert await replay.apply(second_change, context=context()) == second
    assert len(await store.read(scope())) == 2
    # Same stream identity cannot silently acquire a new version or new rules.
    for changed_scope in (scope(strategy_version="OTHER_V1"),
                          scope(rules=replace(rules(), version="OTHER_V1")),
                          scope(session=replace(session(), started_at=session().started_at - timedelta(seconds=1)))):
        assert changed_scope.stream_id == scope().stream_id
        with pytest.raises(RecordError, match="scope"):
            await store.read(changed_scope)
        bad = replace(first, scope=changed_scope)
        with pytest.raises(RecordError, match="conflicts"):
            await store.append(bad)
    assert await store.read(scope()) == (first, second)


async def test_sqlite_rejects_competing_position_reused_id_and_missing_predecessor():
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    subject = StateTransitionEngine(scope(), store)
    first = await subject.apply(proposal(), context=context())
    entries = (
        replace(first, transition=replace(first.transition, reason="different")),
        replace(first, transition=replace(first.transition, record_id="competing")),
        TransitionEntry(scope(), 2, "not-present", proposal(before=WATCHING, after=FORMING, record_id="orphan")),
        TransitionEntry(scope(), 3, "change-1", proposal(before=WATCHING, after=FORMING, record_id="gap")),
    )
    for entry in entries:
        with pytest.raises((RecordError, sqlite3.IntegrityError)):
            await store.append(entry)
    assert await store.read(scope()) == (first,)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_sqlite_transition_facts_cannot_be_overwritten_or_deleted(operation):
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    subject = StateTransitionEngine(scope(), store)
    first = await subject.apply(proposal(), context=context())
    sql = ("UPDATE trade_alerts_transitions_v1 SET transition_json='{}'" if operation == "UPDATE"
           else "DELETE FROM trade_alerts_transitions_v1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await conn.execute(sql)
    assert await store.read(scope()) == (first,)


async def test_sqlite_failure_rolls_back_side_effect_and_preserves_prior_state():
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    subject = StateTransitionEngine(scope(), store)
    first = await subject.apply(proposal(), context=context())
    await conn.executescript("""
        CREATE TABLE m42_probe (value INTEGER);
        CREATE TRIGGER m42_forced_failure BEFORE INSERT ON trade_alerts_transitions_v1
        WHEN NEW.position = 2 BEGIN
            INSERT INTO m42_probe VALUES (1);
            SELECT RAISE(FAIL, 'synthetic transition write failure');
        END;
    """)
    second = proposal(before=WATCHING, after=FORMING, record_id="change-2")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic transition write failure"):
        await subject.apply(second, context=context())
    assert subject.last_entry is first and subject.current_state() == WATCHING
    assert await store.read(scope()) == (first,)
    assert (await (await conn.execute("SELECT COUNT(*) FROM m42_probe")).fetchone())[0] == 0
    await conn.execute("DROP TRIGGER m42_forced_failure")
    assert (await subject.apply(second, context=context())).position == 2


async def test_saved_but_unacknowledged_write_can_retry_without_duplicate_fact():
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)

    class LostAcknowledgment:
        fail = True

        async def append(self, entry):
            await store.append(entry)
            if self.fail:
                self.fail = False
                raise OSError("synthetic lost acknowledgment")

    subject = StateTransitionEngine(scope(), LostAcknowledgment())
    with pytest.raises(OSError, match="lost acknowledgment"):
        await subject.apply(proposal(), context=context())
    assert subject.current_state() == INITIAL and len(await store.read(scope())) == 1
    first = await subject.apply(proposal(), context=context())
    assert await store.read(scope()) == (first,) and subject.current_state() == WATCHING


async def test_additive_migration_preserves_legacy_rows_and_reopens_saved_records(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(legacy_path)
    legacy.execute("CREATE TABLE m42_legacy_fact (value TEXT)")
    legacy.execute("INSERT INTO m42_legacy_fact VALUES ('unchanged')")
    legacy.commit()
    legacy.close()
    db.DB_PATH = str(legacy_path)
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    first = await StateTransitionEngine(scope(), store).apply(proposal(), context=context())
    schema = [tuple(row) for row in await (await conn.execute(
        "SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()]
    await db.close_db()
    reopened = await db.init_db()
    assert [tuple(row) for row in await (await reopened.execute(
        "SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()] == schema
    assert (await (await reopened.execute("SELECT value FROM m42_legacy_fact")).fetchone())[0] == "unchanged"
    assert (await (await reopened.execute("SELECT COUNT(*) FROM schema_version WHERE version=35")).fetchone())[0] == 1
    assert await SQLiteTransitionStore(reopened).read(scope()) == (first,)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
async def test_market_features_strategy_transition_database_recording_end_to_end(direction):
    conn = await db.init_db()
    store = SQLiteTransitionStore(conn)
    saved_scope = scope(direction=direction)
    subject = StateTransitionEngine(saved_scope, store)
    fixture = FixtureStrategy(session(), direction)
    supplied_history = history()
    supplied_history = replace(supplied_history, bars=tuple(
        Bar.from_json(bar.to_json()) for bar in supplied_history.bars))
    entries, observed, contexts, changes = [], [], [], []
    for seconds in (-1, 0, 1, 2):
        at = START + timedelta(seconds=seconds)
        snapshot = build_opening_range_snapshot(
            record_id=f"range-{seconds}", evaluated_at=at, symbol="SYNTH",
            instrument_type="EQUITY", minute_history=supplied_history)
        snapshot = FeatureSnapshot.from_json(snapshot.to_json())
        supplied = context(at, direction=direction, features=(snapshot,),
                           quote=quote_decision(at, stale=seconds == 2))
        proposed = fixture.update(supplied)
        assert len(proposed) == 1
        change = StrategyStateTransition.from_json(proposed[0].to_json())
        entry = await subject.apply(change, context=supplied)
        assert (await store.read(saved_scope))[-1] == entry
        candidate = fixture.actionable() or fixture.heads_up()
        observed.append({"state": subject.current_state().state,
                         "candidate": candidate.as_dict() if candidate else None,
                         "feature_hash": hashlib.sha256(snapshot.to_json().encode()).hexdigest()})
        entries.append(entry)
        contexts.append(supplied)
        changes.append(change)
    assert [row["state"] for row in observed] == [
        "WATCHING", "SETUP_FORMING", "ALERT_TRIGGERED", "WATCHING"]
    assert [row["candidate"]["alert_type"] if row["candidate"] else None for row in observed] == [
        None, "HEADS_UP", "ACTIONABLE", None]
    later = context(START + timedelta(seconds=3), direction=direction)
    invalidation = fixture.invalidate(later, reason="SYNTHETIC_INVALIDATION")[0]
    entries.append(await subject.apply(invalidation, context=later))
    frozen = tuple(entry.to_json() for entry in entries)
    # An explicit supplied edge resets within this session; expiry is another
    # supplied edge, not a newly selected duration or trading policy.
    for index, (old, new) in enumerate(((INVALID, INITIAL), (INITIAL, WATCHING),
                                      (WATCHING, FORMING), (FORMING, EXPIRED))):
        entries.append(await subject.apply(proposal(
            later, before=old, after=new, record_id=f"{direction}-tail-{index}"), context=later))
    assert tuple(entry.to_json() for entry in entries[:5]) == frozen
    replay = StateTransitionEngine(saved_scope, store)
    for change, supplied in zip(changes, contexts):
        await replay.apply(change, context=supplied)
    assert len(await store.read(saved_scope)) == 9
    await db.close_db()
    reopened = SQLiteTransitionStore(await db.init_db())
    restored = await reopened.read(saved_scope)
    assert restored == tuple(entries)
    assert [row.position for row in restored] == list(range(1, 10))
    payload = {
        "evidence": "SYNTHETIC_STATE_TRANSITION_STORAGE_ONLY", "engine_version": ENGINE_VERSION,
        "direction": direction, "observed": observed,
        "entries": [json.loads(row.to_json()) for row in restored],
        "repeated_prefix_added_rows": 0, "reopened_records_match": True,
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path(f"/tmp/m42-state-transitions-{direction.lower()}-proof.json").write_text(rendered)
