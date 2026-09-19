"""M4.1 supplied-input contracts. FixtureStrategy is not a trading playbook."""

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.quote_events import QuoteEventPolicy, QuoteEventStream
from consensus_engine.strategy_interface import (
    INTERFACE_VERSION, RequiredData, Strategy, StrategyContext, StrategyState,
)
from consensus_engine.trade_alerts_config import STRATEGY_IDS, TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, CatalystEvent, ConfidenceBreakdown, ConfidenceComponent,
    FeatureSnapshot, FeatureValue, Quote, RecordError, RiskLevel, SessionRecord,
    SourceMetadata, StrategyStateTransition, TargetLevel,
)
from test_opening_range_features import history


PACIFIC = ZoneInfo("America/Los_Angeles")
START = datetime(2026, 7, 6, 6, 35, tzinfo=PACIFIC)
VERSION = "M41_FIXTURE_ONLY_V1"
FEATURE = "OPENING_RANGE_COMPLETE_5M_V1"


def session(day="2026-07-06"):
    return SessionRecord.from_config(
        record_id="session-" + day, session=day,
        started_at=datetime.fromisoformat(day + "T06:30:00").replace(tzinfo=PACIFIC),
        config=TradeAlertsConfig({"schema_version": 1}),
    )


def metadata(at=START, **changes):
    values = dict(
        instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
        source_time=at, received_time=at, available_time=at, normalized_time=at,
        session=at.astimezone(PACIFIC).date().isoformat(), data_mode="FIXTURE", quality="VALID",
    )
    values.update(changes)
    return SourceMetadata(**values)


def feature(at=START, value=1, **changes):
    values = dict(
        record_id="features-" + at.isoformat(),
        metadata=metadata(at, data_mode="SUPPLIED_BAR_OPENING_RANGE"), evaluated_at=at,
        feature_version="D090_OPENING_RANGE_5M_V1",
        features=(FeatureValue(FEATURE, value, "BOOLEAN", "MISSING" if value is None else None),),
    )
    values.update(changes)
    return FeatureSnapshot(**values)


def quote_decision(at=START, *, stale=False):
    policy = QuoteEventPolicy(VERSION, 3, 3, 10)
    subject = QuoteEventStream(
        source="SYNTHETIC", instrument_id="SYNTH", instrument_type="EQUITY",
        session=at.astimezone(PACIFIC).date().isoformat(), data_mode="FIXTURE", policy=policy,
    )
    observed = at - timedelta(seconds=4) if stale else at
    supplied = Quote(
        record_id="quote-" + observed.isoformat(), metadata=metadata(observed),
        quote_time=observed, trade_time=observed, bid=100, ask=100.1, last=100.05,
        status="VALID", delayed=False,
    )
    supplied = Quote.from_json(supplied.to_json())
    subject.connect(observed)
    subject.consume(supplied, at=observed)
    current = subject.inspect(observed)
    subject.confirm_continuity(
        at=observed, epoch=current.epoch, record_id=supplied.record_id,
        evidence_reference="M41_SYNTHETIC_CONTINUITY",
    )
    return subject.inspect(at)


def context(at=START, **changes):
    values = dict(
        session=session(), symbol="SYNTH", instrument_type="EQUITY", direction="LONG",
        evaluated_at=at,
        features=changes["features"] if "features" in changes else (feature(at),),
        quote=changes["quote"] if "quote" in changes else quote_decision(at),
    )
    values.update(changes)
    return StrategyContext(**values)


class FixtureStrategy(Strategy):
    """Test-only script: first ready input gives heads-up, second actionable.

    Fixed geometry/scores are test facts. This does not implement CRVOL_ORB5 or
    choose a trigger, confidence formula, stop, target, expiry or cooldown policy.
    """

    strategy_id = "CRVOL_ORB5"
    strategy_version = VERSION

    def __init__(self, saved_session, direction="LONG"):
        self.direction = direction
        self.reset(saved_session)

    def required_data(self):
        return (
            RequiredData(FEATURE, "MANDATORY", "D090_OPENING_RANGE_5M_V1",
                         "SUPPLIED_BAR_OPENING_RANGE"),
            RequiredData("quote", "MANDATORY", VERSION, "FIXTURE"),
            RequiredData("context", "MODIFIER", VERSION, "FIXTURE"),
            RequiredData("catalyst", "OPTIONAL", VERSION, "FIXTURE"),
        )

    def current_state(self):
        return self._state

    def _check(self, supplied):
        if (supplied.session != self._session or supplied.direction != self.direction
                or supplied.symbol != "SYNTH" or supplied.instrument_type != "EQUITY"):
            raise RecordError("fixture scope mismatch")
        if self._time is not None and supplied.evaluated_at < self._time:
            raise RecordError("fixture evaluation order")
        self._time = supplied.evaluated_at

    def _transition(self, supplied, state, reason):
        before = self._state
        self._state = StrategyState(state, "FIXTURE_ONLY")
        if self._state == before:
            return ()
        return (StrategyStateTransition(
            record_id=f"{self.direction}-{supplied.evaluated_at.isoformat()}-{state}",
            metadata=metadata(supplied.evaluated_at), strategy_id=self.strategy_id,
            strategy_version=self.strategy_version, occurred_at=supplied.evaluated_at,
            from_state=before.state, to_state=state, from_substate=before.substate,
            to_substate=self._state.substate, reason=reason,
            feature_snapshot_id=supplied.features[0].record_id if supplied.features else None,
            input_record_ids=tuple(row.record_id for row in supplied.features),
        ),)

    def update(self, supplied):
        self._check(supplied)
        self._candidate = None
        if self._state.state in ("INVALIDATED", "EXPIRED"):
            return ()
        matching = [row for row in supplied.features if (
            row.metadata.instrument_id == supplied.symbol
            and row.metadata.instrument_type == supplied.instrument_type
            and row.feature_version == "D090_OPENING_RANGE_5M_V1"
            and row.metadata.data_mode == "SUPPLIED_BAR_OPENING_RANGE"
            and row.metadata.quality == "VALID"
            and row.evaluated_at == supplied.evaluated_at
        )]
        ready = any(item.name == FEATURE and item.unit == "BOOLEAN" and item.value == 1
                    for row in matching for item in row.features)
        if not ready or supplied.quote is None or not supplied.quote.usable:
            return self._transition(supplied, "WATCHING", "FIXTURE_MANDATORY_INPUT_UNAVAILABLE")
        kind = "HEADS_UP" if self._ready_count == 0 else "ACTIONABLE"
        self._ready_count += 1
        state = "SETUP_FORMING" if kind == "HEADS_UP" else "ALERT_TRIGGERED"
        sign = 1 if self.direction == "LONG" else -1
        self._candidate = AlertCandidate(
            record_id=f"{self.direction}-{supplied.evaluated_at.isoformat()}-{kind}",
            metadata=metadata(supplied.evaluated_at), strategy_id=self.strategy_id,
            strategy_version=self.strategy_version, direction=self.direction,
            alert_type=kind, setup_state=state, setup_substate="FIXTURE_ONLY",
            strategy_lifecycle="DEVELOPMENT", evidence_stage="IMPLEMENTED",
            delivery_status="PENDING", structure_id="FIXTURE_STRUCTURE",
            trigger_price=100, alert_price=100,
            risk=RiskLevel(100, 100 - sign, 1, "SUPPLIED_FIXTURE_STOP", "FIXTURE"),
            soft_invalidation="Supplied fixture invalidation",
            targets=(TargetLevel("T1", 100 + 2 * sign, 2, "FIXTURE"),),
            confidence=ConfidenceBreakdown(60, 60, 60, 60, (
                ConfidenceComponent("supplied", 60, VERSION),)),
            human_checks=("Synthetic interface example only",),
            feature_snapshot_id=matching[0].record_id,
            input_record_ids=tuple(row.record_id for row in supplied.features),
            session_record_id=self._session.record_id,
            config_version=self._session.config_version, config_hash=self._session.config_hash,
            created_at=supplied.evaluated_at,
            expires_at=supplied.evaluated_at + timedelta(seconds=30),
            data_quality="VALID", mechanically_valid=kind == "ACTIONABLE",
        )
        return self._transition(supplied, state, "FIXTURE_SCRIPT_" + kind)

    def heads_up(self):
        return self._candidate if self._candidate and self._candidate.alert_type == "HEADS_UP" else None

    def actionable(self):
        return self._candidate if self._candidate and self._candidate.alert_type == "ACTIONABLE" else None

    def invalidate(self, supplied, *, reason):
        self._check(supplied)
        self._candidate = None
        return self._transition(supplied, "INVALIDATED", reason)

    def expire(self, supplied, *, reason):
        self._check(supplied)
        self._candidate = None
        return self._transition(supplied, "EXPIRED", reason)

    def reset(self, saved_session):
        self._session = saved_session
        self._state = StrategyState("NOT_ELIGIBLE")
        self._candidate = None
        self._ready_count = 0
        self._time = None

    def confidence(self):
        return self._candidate.confidence if self._candidate else None

    def stop(self):
        return self._candidate.risk if self._candidate else None

    def targets(self):
        return self._candidate.targets if self._candidate else ()


def collect(strategy: Strategy, supplied: StrategyContext):
    """Same test consumer for any conforming strategy; only records, never I/O."""
    transitions = strategy.update(supplied)
    candidate = strategy.heads_up() or strategy.actionable()
    for transition in transitions:
        assert StrategyStateTransition.from_json(transition.to_json()) == transition
    if candidate:
        assert AlertCandidate.from_json(candidate.to_json()) == candidate
        assert (strategy.confidence(), strategy.stop(), strategy.targets()) == (
            candidate.confidence, candidate.risk, candidate.targets)
    return {
        "state": asdict(strategy.current_state()),
        "transitions": [row.as_dict() for row in transitions],
        "candidate": candidate.as_dict() if candidate else None,
    }


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_all_existing_strategy_identities_share_one_interface_without_registration(strategy_id):
    subject = FixtureStrategy(session())
    subject.strategy_id = strategy_id
    assert isinstance(subject, Strategy)
    result = collect(subject, context())
    assert result["candidate"]["strategy_id"] == strategy_id
    assert result["candidate"]["strategy_version"] == VERSION


def test_incomplete_implementation_cannot_inherit_abstract_operations():
    class Incomplete(Strategy):
        strategy_id = "CRVOL_ORB5"
        strategy_version = VERSION
    with pytest.raises(TypeError, match="abstract"):
        Incomplete()
    assert not isinstance(object(), Strategy)


@pytest.mark.parametrize("role", ["MANDATORY", "MODIFIER", "OPTIONAL"])
def test_required_data_has_explicit_roles_and_immutable_definitions(role):
    requirement = RequiredData("quote", role, VERSION, "FIXTURE")
    with pytest.raises(FrozenInstanceError):
        requirement.role = "OPTIONAL"


@pytest.mark.parametrize("changes", [
    {"role": "REQUIRED"}, {"name": ""}, {"definition_version": "unknown"},
    {"data_mode": " unspecified "}, {"definition_version": ""},
])
def test_required_data_rejects_ambiguous_declarations(changes):
    values = dict(name="quote", role="MANDATORY", definition_version=VERSION, data_mode="FIXTURE")
    values.update(changes)
    with pytest.raises(RecordError):
        RequiredData(**values)


@pytest.mark.parametrize("state", ["ACTIVE", "STALE", "PENDING", "BREAKOUT_ATTEMPT"])
def test_setup_state_does_not_accept_lifecycle_quality_delivery_or_substate(state):
    with pytest.raises(RecordError):
        StrategyState(state)
    assert StrategyState("WATCHING", state).substate == state


@pytest.mark.parametrize("changes", [
    {"symbol": ""}, {"instrument_type": "OPTION"}, {"direction": "BUY"},
    {"session": None}, {"features": []}, {"catalysts": []}, {"quote": {}},
    {"evaluated_at": START.replace(tzinfo=None)},
    {"evaluated_at": START - timedelta(minutes=6)},
    {"evaluated_at": START + timedelta(days=1)},
])
def test_context_rejects_bad_scope_time_and_mutable_input_containers(changes):
    with pytest.raises((RecordError, ValueError)):
        context(**changes)


def test_context_keeps_missing_zero_unknown_and_reference_features_separate():
    missing = feature(value=None)
    reference = feature(record_id="reference", value=0,
                        metadata=metadata(instrument_id="SPY", instrument_type="ETF"))
    catalyst = CatalystEvent(record_id="news", metadata=metadata(), event_type="NEWS",
                             headline="Synthetic unknown event", classification="UNKNOWN")
    supplied = context(features=(missing, reference), quote=None, catalysts=(catalyst,))
    assert supplied.features[0].features[0].value is None
    assert supplied.features[1].features[0].value == 0
    assert supplied.catalysts[0].classification == "UNKNOWN"
    assert supplied.quote is None
    with pytest.raises(FrozenInstanceError):
        supplied.direction = "SHORT"
    detached = supplied.features[0].as_dict()
    detached["features"][0]["value"] = 99
    assert supplied.features[0] == missing


@pytest.mark.parametrize("case", ["available", "evaluated", "session", "source", "duplicate"])
def test_context_rejects_future_misattributed_and_duplicate_features(case):
    current = feature()
    if case == "available":
        current = feature(START + timedelta(seconds=1))
    elif case == "evaluated":
        current = replace(current, evaluated_at=START + timedelta(seconds=1))
    elif case == "session":
        current = replace(current, metadata=metadata(session="2026-07-03"))
    elif case == "source":
        current = replace(current, metadata=metadata(source_time=START + timedelta(seconds=1)))
    with pytest.raises(RecordError):
        context(features=(current, current) if case == "duplicate" else (current,))


@pytest.mark.parametrize("case", ["old_decision", "future_decision", "symbol", "type", "session"])
def test_quote_context_cannot_relabel_an_old_decision_or_another_underlying(case):
    decision = quote_decision()
    if case == "old_decision":
        decision = replace(decision, evaluated_at=START - timedelta(seconds=1))
    elif case == "future_decision":
        decision = replace(decision, evaluated_at=START + timedelta(seconds=1))
    else:
        changes = {"symbol": {"instrument_id": "OTHER"}, "type": {"instrument_type": "ETF"},
                   "session": {"session": "2026-07-03"}}[case]
        decision = replace(decision, quote=replace(
            decision.quote, metadata=replace(decision.quote.metadata, **changes)))
    with pytest.raises(RecordError):
        context(quote=decision)


@pytest.mark.parametrize("case", ["late_classification", "wrong_symbol"])
def test_catalyst_future_classification_and_wrong_identity_are_rejected(case):
    catalyst = CatalystEvent(
        record_id="news", metadata=metadata(), event_type="NEWS", headline="Synthetic event",
        classified_at=START + timedelta(seconds=1) if case == "late_classification" else None,
    )
    if case == "wrong_symbol":
        catalyst = replace(catalyst, metadata=metadata(instrument_id="OTHER"))
    with pytest.raises(RecordError):
        context(catalysts=(catalyst,))


@pytest.mark.parametrize("failure", [
    "missing", "incomplete", "stale_quote", "no_quote", "reference_only",
    "wrong_mode", "wrong_version", "wrong_unit",
])
def test_fixture_consumer_clears_previous_output_when_mandatory_input_fails(failure):
    subject = FixtureStrategy(session())
    collect(subject, context())
    collect(subject, context(START + timedelta(seconds=1)))
    earlier = subject.actionable()
    frozen = earlier.to_json()
    at = START + timedelta(seconds=2)
    changes = {
        "missing": {"features": (feature(at, value=None),)},
        "incomplete": {"features": (feature(at, value=0),)},
        "stale_quote": {"quote": quote_decision(at, stale=True)},
        "no_quote": {"quote": None},
        "reference_only": {"features": (feature(at, metadata=metadata(
            at, instrument_id="SPY", instrument_type="ETF",
            data_mode="SUPPLIED_BAR_OPENING_RANGE")),)},
        "wrong_mode": {"features": (feature(at, metadata=metadata(at, data_mode="OTHER")),)},
        "wrong_version": {"features": (feature(at, feature_version="OTHER_V1"),)},
        "wrong_unit": {"features": (feature(at, features=(FeatureValue(FEATURE, 1, "USD"),)),)},
    }[failure]
    collect(subject, context(at, **changes))
    assert subject.heads_up() is None and subject.actionable() is None
    assert subject.confidence() is None and subject.stop() is None and subject.targets() == ()
    assert earlier.to_json() == frozen


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_shared_feature_to_strategy_records_end_to_end(direction):
    supplied_history = history()
    supplied_history = replace(supplied_history, bars=tuple(
        Bar.from_json(row.to_json()) for row in supplied_history.bars))
    saved_session = SessionRecord.from_json(session().to_json())
    subject: Strategy = FixtureStrategy(saved_session, direction)
    outputs = []
    contexts = []
    for seconds in (-1, 0, 1):
        at = START + timedelta(seconds=seconds)
        snapshot = build_opening_range_snapshot(
            record_id=f"range-{seconds}", evaluated_at=at, symbol="SYNTH",
            instrument_type="EQUITY", minute_history=supplied_history,
        )
        snapshot = FeatureSnapshot.from_json(snapshot.to_json())
        supplied = context(at, session=saved_session, direction=direction, features=(snapshot,))
        contexts.append(supplied)
        outputs.append(collect(subject, supplied))
    assert [row["state"]["state"] for row in outputs] == [
        "WATCHING", "SETUP_FORMING", "ALERT_TRIGGERED"]
    assert [row["candidate"]["alert_type"] if row["candidate"] else None for row in outputs] == [
        None, "HEADS_UP", "ACTIONABLE"]
    alert = subject.actionable()
    frozen = alert.to_json()
    assert subject.actionable() is alert  # Reads neither emit nor mutate.
    assert alert.session_record_id == saved_session.record_id
    assert alert.config_hash == saved_session.config_hash
    assert alert.risk.hard_stop == (99 if direction == "LONG" else 101)
    assert alert.targets[0].price == (102 if direction == "LONG" else 98)
    stale_at = START + timedelta(seconds=2)
    rejected = [collect(subject, context(
        stale_at, direction=direction, quote=quote_decision(stale_at, stale=True)))]
    missing_at = START + timedelta(seconds=3)
    rejected.append(collect(subject, context(missing_at, direction=direction, features=())))
    assert all(row["candidate"] is None for row in rejected)
    ended = context(START + timedelta(seconds=4), direction=direction)
    invalidated = subject.invalidate(ended, reason="FIXTURE_INVALIDATION")
    assert invalidated[0].to_state == "INVALIDATED" and subject.actionable() is None
    assert collect(subject, ended)["candidate"] is None
    subject.reset(saved_session)
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
    repeated = [collect(subject, supplied) for supplied in contexts]
    assert repeated == outputs
    expired = subject.expire(ended, reason="FIXTURE_EXPIRY")
    assert expired[0].to_state == "EXPIRED" and subject.actionable() is None
    assert collect(subject, ended)["candidate"] is None
    assert alert.to_json() == frozen
    next_session = session("2026-07-07")
    subject.reset(next_session)
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
    with pytest.raises(RecordError, match="scope mismatch"):
        subject.update(contexts[-1])
    new_day_input = context(START + timedelta(days=1), session=next_session,
                            direction=direction, quote=None, features=())
    new_day = collect(subject, new_day_input)
    assert new_day["state"]["state"] == "WATCHING" and new_day["candidate"] is None
    for transition in (*invalidated, *expired):
        assert StrategyStateTransition.from_json(transition.to_json()) == transition
    payload = {
        "evidence": "SYNTHETIC_INTERFACE_PROOF_ONLY", "interface_version": INTERFACE_VERSION,
        "strategy_version": VERSION, "direction": direction,
        "session": saved_session.as_dict(),
        "requirements": [asdict(item) for item in subject.required_data()],
        "feature_hashes": [hashlib.sha256(item.features[0].to_json().encode()).hexdigest()
                           for item in contexts],
        "outputs": outputs, "rejected_inputs": rejected,
        "invalidation": invalidated[0].as_dict(), "expiry": expired[0].as_dict(),
        "next_session_output": new_day,
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path(f"/tmp/m41-strategy-interface-{direction.lower()}-proof.json").write_text(rendered)


def test_session_settings_remain_off_and_interface_use_does_not_mutate_them():
    saved = session()
    frozen = saved.to_json()
    collect(FixtureStrategy(saved), context(session=saved))
    config = json.loads(saved.config_json)
    assert config["evaluation_enabled"] is False
    assert all(not row["enabled"] for row in config["strategies"].values())
    assert config["data"]["collection_enabled"] is False
    assert config["options"]["enabled"] is False
    assert config["alerts"]["delivery_enabled"] is False
    assert config["research"]["enabled"] is False
    assert saved.to_json() == frozen
