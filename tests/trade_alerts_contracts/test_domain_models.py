"""M1.3 contracts for immutable, versioned trade-alert records."""

import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip(
        "Requires scripts/testing/run_trade_alerts_contracts.py",
        allow_module_level=True,
    )


from consensus_engine.trade_alerts_config import TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    AlertCandidate,
    Bar,
    CatalystEvent,
    ConfidenceBreakdown,
    ConfidenceComponent,
    ConfluenceLink,
    DeliveryRecord,
    FeatureSnapshot,
    FeatureValue,
    HumanDecisionRecord,
    OptionQuote,
    OptionRecommendation,
    OutcomeRecord,
    Quote,
    RecordError,
    RiskLevel,
    SessionRecord,
    SourceMetadata,
    StrategyStateTransition,
    SuppressionEvent,
    TargetLevel,
    TargetOutcome,
    record_from_json,
)


UTC = timezone.utc
PLUS_TWO = timezone(timedelta(hours=2))
T0 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)


def _metadata(**changes):
    values = {
        "instrument_id": "SYNTH",
        "instrument_type": "EQUITY",
        "source": "SYNTHETIC",
        "source_time": T0,
        "received_time": T0 + timedelta(seconds=1),
        "available_time": T0 + timedelta(seconds=3),
        "normalized_time": T0 + timedelta(seconds=2),
        "session": "2026-07-06",
        "sequence": 7,
        "revision": 2,
        "data_mode": "FIXTURE",
        "quality": "VALID",
    }
    values.update(changes)
    return SourceMetadata(**values)


def _bar():
    return Bar(
        record_id="bar-1",
        metadata=_metadata(
            source_time=T0 + timedelta(minutes=1),
            received_time=T0 + timedelta(minutes=1, seconds=1),
            normalized_time=T0 + timedelta(minutes=1, seconds=2),
            available_time=T0 + timedelta(minutes=1, seconds=3),
        ),
        start_time=T0,
        end_time=T0 + timedelta(minutes=1),
        is_final=True,
        open=100.0,
        high=101.0,
        low=99.5,
        close=100.5,
        volume=0,
        adjustment_basis="RAW",
        price_convention="USD_PER_SHARE",
        volume_convention="SHARES",
    )


def _quote():
    return Quote(
        record_id="quote-1",
        metadata=_metadata(),
        quote_time=T0 + timedelta(seconds=2),
        trade_time=T0 - timedelta(minutes=20),
        bid=100.0,
        ask=100.1,
        last=99.9,
        last_size=None,
        bid_size=None,
        ask_size=0,
        status="VALID",
        delayed=False,
    )


def _option_quote():
    return OptionQuote(
        record_id="option-quote-1",
        metadata=_metadata(
            instrument_id="SYNTH  260710C00100000", instrument_type="OPTION"
        ),
        contract_id="SYNTH  260710C00100000",
        underlying_id="SYNTH",
        expiry=date(2026, 7, 10),
        strike=100.0,
        option_type="CALL",
        multiplier=100.0,
        deliverable="100 SYNTH shares",
        quote_time=T0,
        trade_time=None,
        bid=1.0,
        ask=1.2,
        last=None,
        bid_size=0,
        ask_size=None,
        implied_volatility=None,
        delta=0.0,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
        open_interest=None,
        open_interest_time=None,
        volume=0,
        non_standard=False,
        status="VALID",
        delayed=False,
    )


def _snapshot():
    return FeatureSnapshot(
        record_id="snapshot-1",
        metadata=_metadata(),
        evaluated_at=T0 + timedelta(seconds=3),
        features=(
            FeatureValue("zero_feature", 0.0, "ratio", input_record_ids=("bar-1",)),
            FeatureValue("missing_feature", None, "ratio", "NO_INPUT", ()),
        ),
        feature_version="FEATURES_V1",
        input_record_ids=("bar-1", "quote-1"),
    )


def _candidate():
    return AlertCandidate(
        record_id="candidate-1",
        metadata=_metadata(),
        strategy_id="CRVOL_ORB5",
        strategy_version="STRATEGY_V1",
        direction="LONG",
        setup_state="ALERT_TRIGGERED",
        trigger_price=100.1,
        alert_price=100.2,
        alert_type="ACTIONABLE",
        strategy_lifecycle="ACTIVE",
        evidence_stage="UNIT_TESTED",
        delivery_status="PENDING",
        structure_id="structure-1",
        risk=RiskLevel(100.2, 99.5, 0.7, "STRUCTURAL_STOP", "bar-1"),
        soft_invalidation="Lose VWAP",
        targets=(TargetLevel("T1", 101.0, 1.1428571428571428, "bar-1"),),
        confidence=ConfidenceBreakdown(
            0.0,
            0.0,
            0.0,
            0.0,
            (ConfidenceComponent("setup", 0.0, "CONFIDENCE_V1"),),
        ),
        confluence=(ConfluenceLink("HOD_COMP_RS", "candidate-2"),),
        human_checks=("Confirm liquidity",),
        input_record_ids=("bar-1", "quote-1"),
        feature_snapshot_id="snapshot-1",
        session_record_id="session-1",
        config_version="FOUNDATION_V1",
        config_hash="a" * 64,
        created_at=T0 + timedelta(seconds=4),
        expires_at=T0 + timedelta(minutes=5),
        data_quality="VALID",
        mechanically_valid=True,
    )


def _all_records():
    config = TradeAlertsConfig({"schema_version": 1})
    return (
        _bar(),
        _quote(),
        _option_quote(),
        CatalystEvent(
            record_id="catalyst-1",
            metadata=_metadata(),
            event_type="NEWS",
            headline="Synthetic event",
            occurred_time=None,
            source_event_id=None,
            classification="UNKNOWN",
            confidence=None,
            classified_at=None,
            details=(("status", "unknown"),),
        ),
        _snapshot(),
        StrategyStateTransition(
            record_id="transition-1",
            metadata=_metadata(),
            strategy_id="CRVOL_ORB5",
            strategy_version="STRATEGY_V1",
            occurred_at=T0,
            from_state="WATCHING",
            to_state="ALERT_TRIGGERED",
            from_substate="FIRST_PULLBACK",
            to_substate=None,
            reason="fixture",
            input_record_ids=("bar-1",),
            feature_snapshot_id="snapshot-1",
        ),
        _candidate(),
        OptionRecommendation(
            record_id="recommendation-1",
            candidate_id="candidate-1",
            status="RECOMMENDED",
            ranked_at=T0,
            reasons=("fixture",),
            policy_version="OPTIONS_V1",
            option_quote_id="option-quote-1",
            contract_id="SYNTH  260710C00100000",
            expiry=date(2026, 7, 10),
            strike=100.0,
            option_type="CALL",
            multiplier=100.0,
            deliverable="100 SYNTH shares",
            rank=1,
            score=80.0,
        ),
        OutcomeRecord(
            record_id="outcome-1",
            candidate_id="candidate-1",
            option_recommendation_id="recommendation-1",
            evaluated_at=T0 + timedelta(days=1),
            horizon="NEXT_SESSION",
            coverage_status="COMPLETE",
            policy_version="OUTCOME_V1",
            alert_price=100.2,
            modeled_entry_price=None,
            outcome_price=101.0,
            mfe=1.2,
            mae=-0.3,
            max_r=1.1,
            stop_hit=False,
            stop_hit_at=None,
            target_outcomes=(
                TargetOutcome("T1", True, T0 + timedelta(hours=1)),
                TargetOutcome("T2", None, None),
            ),
            result="RESOLVED",
            data_quality="VALID",
            input_record_ids=("bar-1",),
        ),
        SuppressionEvent(
            record_id="suppression-1",
            metadata=_metadata(),
            candidate_id="candidate-1",
            strategy_id="CRVOL_ORB5",
            strategy_version="STRATEGY_V1",
            occurred_at=T0 + timedelta(seconds=4),
            reason="DUPLICATE_THESIS",
            input_record_ids=("candidate-2",),
        ),
        DeliveryRecord(
            record_id="delivery-1",
            candidate_id="candidate-1",
            attempted_at=T0,
            sink="recording",
            status="CONFIRMED_DELIVERED",
            message_reference=None,
        ),
        HumanDecisionRecord(
            record_id="decision-1",
            candidate_id="candidate-1",
            decided_at=T0,
            decision="REJECTED",
            note=None,
            actual_manual_trade_price=None,
        ),
        SessionRecord.from_config(
            record_id="session-1",
            session="2026-07-06",
            started_at=T0,
            config=config,
        ),
    )


@pytest.mark.parametrize("record", _all_records(), ids=lambda row: type(row).__name__)
def test_each_record_round_trips_through_its_typed_json_contract(record):
    assert type(record).from_json(record.to_json()) == record


@pytest.mark.parametrize("record", _all_records(), ids=lambda row: type(row).__name__)
def test_generic_decoder_restores_each_known_record_type(record):
    assert record_from_json(record.to_json()) == record


def test_unknown_record_type_is_rejected():
    payload = json.loads(_bar().to_json())
    payload["record_type"] = "FutureRecord"
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_unknown_schema_version_is_rejected():
    payload = json.loads(_bar().to_json())
    payload["schema_version"] = 2
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_unknown_field_is_rejected():
    payload = json.loads(_bar().to_json())
    payload["future_field"] = "not silently ignored"
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_class_decoder_rejects_a_different_known_record_type():
    with pytest.raises(RecordError):
        Quote.from_json(_bar().to_json())


def test_nested_record_envelope_is_rejected_for_metadata():
    payload = json.loads(_bar().to_json())
    payload["metadata"] = json.loads(_quote().to_json())
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_malformed_fixed_length_tuple_is_rejected():
    payload = json.loads(_all_records()[3].to_json())
    payload["details"] = [["key", "value", "extra"]]
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_duplicate_json_field_is_rejected():
    payload = _bar().to_json().replace(
        '"record_id":"bar-1"',
        '"record_id":"bar-1","record_id":"bar-duplicate"',
    )
    with pytest.raises(RecordError):
        record_from_json(payload)


def test_unhashable_record_type_is_rejected_as_a_record_error():
    with pytest.raises(RecordError):
        record_from_json('{"record_type":[],"schema_version":1}')


def test_instants_are_timezone_aware_and_normalized_to_utc():
    local_view = (T0 + timedelta(hours=2)).replace(tzinfo=PLUS_TWO)
    metadata = _metadata(source_time=local_view)
    assert metadata.source_time == T0
    assert metadata.source_time.tzinfo is UTC


def test_naive_instant_is_rejected():
    with pytest.raises(RecordError):
        _metadata(source_time=datetime(2026, 7, 6, 13, 30))


def test_option_expiry_requires_a_calendar_date_not_a_datetime():
    with pytest.raises(RecordError):
        replace(_option_quote(), expiry=T0)


def test_option_expiry_json_rejects_an_instant_string():
    payload = json.loads(_option_quote().to_json())
    payload["expiry"] = "2026-07-10T00:00:00Z"
    with pytest.raises(RecordError):
        record_from_json(json.dumps(payload))


def test_source_metadata_requires_a_typed_instrument():
    with pytest.raises(RecordError):
        _metadata(instrument_type="STOCKISH")


@pytest.mark.parametrize("instrument_type", ["EQUITY", "ETF", "OPTION", "UNKNOWN"])
def test_typed_instrument_identity_round_trips_without_collapsing(instrument_type):
    quality = "UNKNOWN" if instrument_type == "UNKNOWN" else "VALID"
    metadata = _metadata(instrument_type=instrument_type, quality=quality)
    assert metadata.instrument_type == instrument_type


def test_source_metadata_session_requires_canonical_calendar_date_text():
    with pytest.raises(RecordError):
        _metadata(session="2026-7-6")


@pytest.mark.parametrize("invalid", ["2026-02-30", "07/06/2026", "regular"])
def test_source_metadata_rejects_invalid_or_ambiguous_session_date(invalid):
    with pytest.raises(RecordError):
        _metadata(session=invalid)


def test_session_record_rejects_datetime_instead_of_calendar_date_text():
    config = TradeAlertsConfig({"schema_version": 1})
    with pytest.raises(RecordError):
        SessionRecord.from_config(
            record_id="session-bad",
            session=T0,
            started_at=T0,
            config=config,
        )


def test_metadata_rejects_receipt_after_availability():
    with pytest.raises(RecordError):
        _metadata(
            received_time=T0 + timedelta(seconds=3),
            available_time=T0 + timedelta(seconds=2),
        )


def test_metadata_rejects_normalization_before_receipt():
    with pytest.raises(RecordError):
        _metadata(
            normalized_time=T0,
            available_time=T0 + timedelta(seconds=3),
        )


def test_missing_source_time_stays_unknown_instead_of_becoming_fresh():
    metadata = _metadata(source="UNKNOWN", source_time=None, quality="UNKNOWN")
    event = CatalystEvent(
        record_id="unknown-source-event",
        metadata=metadata,
        event_type="NEWS",
        headline="Source time unavailable",
        occurred_time=None,
        source_event_id=None,
        classification="UNKNOWN",
        confidence=None,
        classified_at=None,
    )
    restored = CatalystEvent.from_json(event.to_json())
    assert metadata.source_time is None
    assert metadata.quality == "UNKNOWN"
    assert restored.metadata.source_time is None
    assert restored.metadata.quality == "UNKNOWN"


def test_missing_availability_is_rejected_instead_of_becoming_fresh():
    with pytest.raises(RecordError):
        _metadata(available_time=None)


def test_bar_rejects_end_before_start():
    with pytest.raises(RecordError):
        replace(_bar(), end_time=T0 - timedelta(seconds=1))


def test_final_bar_rejects_availability_before_its_end():
    with pytest.raises(RecordError):
        replace(_bar(), metadata=_metadata())


def test_candidate_rejects_expiry_at_creation_time():
    candidate = _candidate()
    with pytest.raises(RecordError):
        replace(candidate, expires_at=candidate.created_at)


def test_transition_preserves_canonical_states_and_optional_substates():
    transition = _all_records()[5]
    restored = StrategyStateTransition.from_json(transition.to_json())
    assert (restored.from_state, restored.to_state) == ("WATCHING", "ALERT_TRIGGERED")
    assert restored.from_substate == "FIRST_PULLBACK"
    assert restored.to_substate is None


def test_transition_rejects_unknown_base_state():
    with pytest.raises(RecordError):
        replace(_all_records()[5], to_state="ACTIONABLE")


def test_feature_snapshot_rejects_evaluation_before_inputs_are_available():
    snapshot = _snapshot()
    with pytest.raises(RecordError):
        replace(
            snapshot,
            evaluated_at=snapshot.metadata.available_time - timedelta(microseconds=1),
        )


def test_candidate_rejects_creation_before_inputs_are_available():
    candidate = _candidate()
    with pytest.raises(RecordError):
        replace(
            candidate,
            created_at=candidate.metadata.available_time - timedelta(microseconds=1),
        )


def test_zero_feature_value_remains_distinct_from_missing_value():
    restored = FeatureSnapshot.from_json(_snapshot().to_json())
    assert restored.features[0].value == 0.0
    assert restored.features[0].missing_reason is None
    assert restored.features[1].value is None
    assert restored.features[1].missing_reason == "NO_INPUT"


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
def test_non_finite_feature_value_is_rejected(invalid):
    with pytest.raises(RecordError):
        FeatureValue("bad", invalid, "ratio")


def test_boolean_is_rejected_for_numeric_value():
    with pytest.raises(RecordError):
        FeatureValue("bad", True, "ratio")


def test_boolean_is_rejected_for_integer_value():
    with pytest.raises(RecordError):
        replace(_option_quote(), open_interest=True)


def test_bar_preserves_provisional_finality_and_revision():
    bar = replace(_bar(), is_final=False, metadata=_metadata(revision=3))
    restored = Bar.from_json(bar.to_json())
    assert restored.is_final is False
    assert restored.metadata.revision == 3


def test_certified_no_trade_bar_has_zero_volume_and_no_invented_prices():
    bar = replace(
        _bar(),
        open=None,
        high=None,
        low=None,
        close=None,
        volume=0,
        certified_no_trade=True,
    )
    restored = Bar.from_json(bar.to_json())
    assert (restored.open, restored.high, restored.low, restored.close) == (None,) * 4
    assert restored.volume == 0
    assert restored.certified_no_trade is True


def test_certified_no_trade_bar_rejects_an_invented_price():
    with pytest.raises(RecordError):
        replace(_bar(), certified_no_trade=True, volume=0)


def test_certified_no_trade_bar_rejects_provisional_source_evidence():
    no_trade = replace(
        _bar(), open=None, high=None, low=None, close=None, volume=0,
        certified_no_trade=True,
    )
    with pytest.raises(RecordError):
        replace(no_trade, is_final=False)


@pytest.mark.parametrize("quality", ["UNAVAILABLE", "UNKNOWN"])
def test_certified_no_trade_bar_rejects_unconfirmed_source_quality(quality):
    no_trade = replace(
        _bar(), open=None, high=None, low=None, close=None, volume=0,
        certified_no_trade=True,
    )
    with pytest.raises(RecordError):
        replace(no_trade, metadata=replace(no_trade.metadata, quality=quality))


def test_unavailable_bar_keeps_missing_volume_distinct_from_no_trade_zero():
    unavailable = replace(
        _bar(),
        metadata=_metadata(
            quality="UNAVAILABLE",
            source_time=None,
            received_time=T0 + timedelta(minutes=1, seconds=1),
            normalized_time=T0 + timedelta(minutes=1, seconds=2),
            available_time=T0 + timedelta(minutes=1, seconds=3),
        ),
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
    )
    no_trade = replace(
        unavailable,
        record_id="bar-no-trade",
        metadata=replace(unavailable.metadata, quality="VALID"),
        volume=0,
        certified_no_trade=True,
    )
    assert Bar.from_json(unavailable.to_json()).volume is None
    assert Bar.from_json(no_trade.to_json()).volume == 0


def test_quote_keeps_fresh_bid_ask_time_separate_from_old_last_trade_time():
    restored = Quote.from_json(_quote().to_json())
    assert restored.quote_time == T0 + timedelta(seconds=2)
    assert restored.trade_time == T0 - timedelta(minutes=20)
    assert restored.bid == 100.0 and restored.ask == 100.1
    assert restored.last == 99.9


def test_quote_rejects_quote_time_after_record_availability():
    quote = _quote()
    with pytest.raises(RecordError):
        replace(
            quote,
            quote_time=quote.metadata.available_time + timedelta(microseconds=1),
        )


def test_option_quote_rejects_trade_time_after_record_availability():
    quote = _option_quote()
    with pytest.raises(RecordError):
        replace(
            quote,
            trade_time=quote.metadata.available_time + timedelta(microseconds=1),
        )


def test_quote_preserves_missing_optional_field_and_exact_zero_size():
    restored = Quote.from_json(_quote().to_json())
    assert restored.bid_size is None
    assert restored.ask_size == 0


def test_quote_preserves_missing_last_size_and_exact_zero_last_size():
    missing = Quote.from_json(_quote().to_json())
    zero = Quote.from_json(replace(_quote(), last_size=0).to_json())
    assert missing.last_size is None
    assert zero.last_size == 0


@pytest.mark.parametrize("invalid", [-1, 1.5, True])
def test_quote_rejects_invalid_last_size(invalid):
    with pytest.raises(RecordError):
        replace(_quote(), last_size=invalid)


def test_option_quote_preserves_exact_contract_identity():
    restored = OptionQuote.from_json(_option_quote().to_json())
    assert (
        restored.contract_id,
        restored.underlying_id,
        restored.expiry,
        restored.strike,
        restored.option_type,
        restored.multiplier,
        restored.deliverable,
    ) == (
        "SYNTH  260710C00100000",
        "SYNTH",
        date(2026, 7, 10),
        100.0,
        "CALL",
        100.0,
        "100 SYNTH shares",
    )


def test_option_quote_keeps_missing_greeks_and_open_interest_metadata_explicit():
    restored = OptionQuote.from_json(_option_quote().to_json())
    assert restored.implied_volatility is None
    assert restored.gamma is None
    assert restored.open_interest is None
    assert restored.open_interest_time is None


def test_option_quote_preserves_unknown_multiplier_and_deliverable():
    quote = replace(_option_quote(), multiplier=None, deliverable=None)
    restored = OptionQuote.from_json(quote.to_json())
    assert restored.multiplier is None
    assert restored.deliverable is None


def test_option_quote_keeps_exact_zero_greek_distinct_from_missing_greek():
    restored = OptionQuote.from_json(_option_quote().to_json())
    assert restored.delta == 0.0
    assert restored.gamma is None


def test_option_quote_preserves_volume_and_non_standard_identity():
    quote = replace(_option_quote(), volume=0, non_standard=True)
    restored = OptionQuote.from_json(quote.to_json())
    assert restored.volume == 0
    assert restored.non_standard is True


def test_quote_preserves_unknown_delay_instead_of_assuming_not_delayed():
    quote = replace(_quote(), delayed=None)
    assert Quote.from_json(quote.to_json()).delayed is None


def test_option_quote_preserves_unknown_delay_and_deliverable_status():
    quote = replace(_option_quote(), delayed=None, non_standard=None)
    restored = OptionQuote.from_json(quote.to_json())
    assert restored.delayed is None
    assert restored.non_standard is None


def test_catalyst_keeps_unknown_classification_and_confidence_explicit():
    event = _all_records()[3]
    restored = CatalystEvent.from_json(event.to_json())
    assert restored.classification == "UNKNOWN"
    assert restored.confidence is None
    assert restored.classified_at is None


def test_catalyst_rejects_classification_before_record_receipt():
    event = _all_records()[3]
    with pytest.raises(RecordError):
        replace(
            event,
            classified_at=event.metadata.received_time - timedelta(microseconds=1),
        )


def test_catalyst_rejects_duplicate_detail_keys():
    event = _all_records()[3]
    with pytest.raises(RecordError):
        replace(event, details=(("status", "first"), ("status", "second")))


def test_option_quote_rejects_metadata_for_a_different_contract():
    with pytest.raises(RecordError):
        replace(_option_quote(), metadata=_metadata(instrument_id="OTHER CONTRACT"))


def test_candidate_keeps_snapshot_and_configuration_attribution():
    restored = AlertCandidate.from_json(_candidate().to_json())
    assert restored.feature_snapshot_id == "snapshot-1"
    assert restored.config_version == "FOUNDATION_V1"
    assert restored.config_hash == "a" * 64
    assert restored.input_record_ids == ("bar-1", "quote-1")


def test_heads_up_candidate_preserves_structure_and_human_checks_without_action_prices():
    candidate = replace(
        _candidate(),
        alert_type="HEADS_UP",
        trigger_price=None,
        alert_price=None,
        risk=None,
        targets=(),
        mechanically_valid=False,
    )
    restored = AlertCandidate.from_json(candidate.to_json())
    assert restored.structure_id == "structure-1"
    assert restored.human_checks == ("Confirm liquidity",)
    assert restored.trigger_price is None


def test_actionable_long_candidate_rejects_stop_above_entry():
    with pytest.raises(RecordError):
        replace(_candidate(), risk=RiskLevel(100.2, 100.7, 0.5, "bad", "fixture"))


def test_actionable_short_candidate_accepts_stop_above_and_target_below_entry():
    candidate = replace(
        _candidate(),
        direction="SHORT",
        risk=RiskLevel(100.2, 100.7, 0.5, "STRUCTURAL_STOP", "bar-1"),
        targets=(TargetLevel("T1", 99.2, 2.0, "bar-1"),),
    )
    assert AlertCandidate.from_json(candidate.to_json()) == candidate


def test_mechanical_candidate_does_not_contain_a_modeled_fill():
    assert "modeled_entry_price" not in _candidate().as_dict()


@pytest.mark.parametrize(
    "field, invalid",
    [
        ("setup_state", "ALERTED_TYPO"),
        ("strategy_lifecycle", "LIVE"),
        ("evidence_stage", "BACKTESTED_MAYBE"),
        ("delivery_status", "SENTISH"),
    ],
)
def test_candidate_rejects_unknown_state_vocabulary(field, invalid):
    with pytest.raises(RecordError):
        replace(_candidate(), **{field: invalid})


def test_quote_rejects_unknown_status_vocabulary():
    with pytest.raises(RecordError):
        replace(_quote(), status="FRESHISH")


def test_option_quote_rejects_unknown_status_vocabulary():
    with pytest.raises(RecordError):
        replace(_option_quote(), status="GOOD_ENOUGH")


def test_delivery_rejects_unknown_sink_vocabulary():
    with pytest.raises(RecordError):
        replace(_all_records()[10], sink="webhookish")


def test_delivery_rejects_unknown_status_vocabulary():
    with pytest.raises(RecordError):
        replace(_all_records()[10], status="SENT")


def test_candidate_and_nested_values_are_immutable():
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.risk.hard_stop = 98.0
    detached = candidate.as_dict()
    detached["targets"][0]["price"] = 999.0
    assert candidate.targets[0].price == 101.0


@pytest.mark.parametrize("status", ["RECOMMENDED", "POOR", "UNAVAILABLE"])
def test_option_recommendation_status_round_trips_without_changing_candidate(status):
    values = {
        "record_id": f"option-{status.lower()}",
        "candidate_id": "candidate-1",
        "status": status,
        "ranked_at": T0,
        "reasons": ("fixture",),
    }
    if status == "RECOMMENDED":
        values.update(
            policy_version="OPTIONS_V1",
            option_quote_id="option-quote-1",
            contract_id="SYNTH  260710C00100000",
            expiry=date(2026, 7, 10),
            strike=100.0,
            option_type="CALL",
            multiplier=100.0,
            deliverable="100 SYNTH shares",
            rank=1,
            score=80.0,
        )
    recommendation = OptionRecommendation(**values)
    restored = OptionRecommendation.from_json(recommendation.to_json())
    assert restored.status == status
    if status != "RECOMMENDED":
        assert restored.contract_id is None
        assert restored.option_quote_id is None


def test_poor_option_preserves_rejected_contract_and_score_for_research():
    recommended = _all_records()[7]
    poor = replace(recommended, status="POOR", rank=None, reasons=("WIDE_SPREAD",))
    restored = OptionRecommendation.from_json(poor.to_json())
    assert restored.status == "POOR"
    assert restored.contract_id == recommended.contract_id
    assert restored.score == recommended.score
    assert restored.rank is None


def test_poor_option_rejects_a_selected_rank():
    recommended = _all_records()[7]
    with pytest.raises(RecordError):
        replace(recommended, status="POOR")


def test_poor_option_rejects_empty_reasons():
    recommended = _all_records()[7]
    with pytest.raises(RecordError):
        replace(recommended, status="POOR", rank=None, reasons=())


def test_poor_option_score_requires_policy_version():
    recommended = _all_records()[7]
    with pytest.raises(RecordError):
        replace(
            recommended,
            status="POOR",
            rank=None,
            policy_version=None,
            reasons=("WIDE_SPREAD",),
        )


def test_unavailable_option_rejects_invented_selection_facts():
    recommended = _all_records()[7]
    with pytest.raises(RecordError):
        replace(recommended, status="UNAVAILABLE")


def test_outcome_preserves_nullable_excursions_hits_times_and_policy():
    outcome = _all_records()[8]
    unresolved = replace(
        outcome,
        coverage_status="UNRESOLVED",
        policy_version=None,
        outcome_price=None,
        mfe=None,
        mae=None,
        max_r=None,
        stop_hit=None,
        target_outcomes=(TargetOutcome("T1", None, None),),
        result="UNKNOWN",
    )
    restored = OutcomeRecord.from_json(unresolved.to_json())
    assert restored.policy_version is None
    assert (restored.mfe, restored.mae, restored.max_r) == (None, None, None)
    assert restored.stop_hit is None
    assert restored.target_outcomes == (TargetOutcome("T1", None, None),)


@pytest.mark.parametrize("coverage_status", ["UNAVAILABLE", "UNRESOLVED"])
@pytest.mark.parametrize(
    "observed",
    [
        {"outcome_price": 101.0},
        {"mfe": 1.0},
        {"mae": -0.5},
        {"max_r": 0.5},
        {"stop_hit": False},
        {"target_outcomes": (TargetOutcome("T1", True, T0),)},
    ],
)
def test_unobserved_outcome_coverage_rejects_measured_results(
    coverage_status, observed
):
    base = replace(
        _all_records()[8],
        coverage_status=coverage_status,
        result="UNKNOWN",
        outcome_price=None,
        mfe=None,
        mae=None,
        max_r=None,
        stop_hit=None,
        stop_hit_at=None,
        target_outcomes=(TargetOutcome("T1", None, None),),
    )
    with pytest.raises(RecordError):
        replace(base, **observed)


def test_partial_outcome_preserves_observed_evidence():
    partial = replace(_all_records()[8], coverage_status="PARTIAL", result="CENSORED")
    restored = OutcomeRecord.from_json(partial.to_json())
    assert restored.outcome_price == 101.0
    assert restored.mfe == 1.2
    assert restored.target_outcomes[0].hit is True


def test_outcome_rejects_unknown_result_vocabulary():
    with pytest.raises(RecordError):
        replace(_all_records()[8], result="WINNER")


@pytest.mark.parametrize("coverage_status", ["UNAVAILABLE", "UNRESOLVED"])
def test_unobserved_outcome_coverage_rejects_resolved_result(coverage_status):
    outcome = replace(
        _all_records()[8],
        coverage_status=coverage_status,
        outcome_price=None,
        mfe=None,
        mae=None,
        max_r=None,
        stop_hit=None,
        stop_hit_at=None,
        target_outcomes=(TargetOutcome("T1", None, None),),
        result="UNKNOWN",
    )
    with pytest.raises(RecordError):
        replace(outcome, result="RESOLVED")


def test_target_outcome_rejects_timestamp_when_hit_is_unknown():
    with pytest.raises(RecordError):
        TargetOutcome("T1", None, T0)


def test_outcome_rejects_target_hit_after_evaluation():
    outcome = _all_records()[8]
    with pytest.raises(RecordError):
        replace(
            outcome,
            target_outcomes=(
                TargetOutcome("T1", True, outcome.evaluated_at + timedelta(seconds=1)),
            ),
        )


def test_invalid_human_decision_status_is_rejected():
    decision = _all_records()[11]
    with pytest.raises(RecordError):
        replace(decision, decision="BUY_NOW")


def test_invalid_data_quality_status_is_rejected():
    with pytest.raises(RecordError):
        _metadata(quality="FRESH_ENOUGH")


def test_suppression_without_candidate_keeps_instrument_session_and_strategy_version():
    suppression = replace(_all_records()[9], candidate_id=None)
    restored = SuppressionEvent.from_json(suppression.to_json())
    assert restored.candidate_id is None
    assert restored.metadata.instrument_id == "SYNTH"
    assert restored.metadata.session == "2026-07-06"
    assert restored.strategy_version == "STRATEGY_V1"


def test_suppression_rejects_event_before_inputs_are_available():
    suppression = _all_records()[9]
    with pytest.raises(RecordError):
        replace(
            suppression,
            occurred_at=suppression.metadata.available_time - timedelta(microseconds=1),
        )


def test_linked_option_delivery_outcome_and_human_choice_do_not_change_mechanical_bytes():
    candidate = _candidate()
    mechanical_bytes = candidate.to_json().encode("utf-8")
    recommendation, outcome, delivery, decision = (
        _all_records()[7],
        _all_records()[8],
        _all_records()[10],
        _all_records()[11],
    )
    assert {row.candidate_id for row in (recommendation, outcome, delivery, decision)} == {
        candidate.record_id
    }
    assert candidate.to_json().encode("utf-8") == mechanical_bytes


def test_record_json_is_canonical_across_key_order_and_equivalent_timezones():
    first = _bar()
    shifted = replace(
        first,
        metadata=replace(
            first.metadata,
            source_time=first.metadata.source_time.astimezone(PLUS_TWO),
            received_time=first.metadata.received_time.astimezone(PLUS_TWO),
            available_time=first.metadata.available_time.astimezone(PLUS_TWO),
            normalized_time=first.metadata.normalized_time.astimezone(PLUS_TWO),
        ),
        start_time=first.start_time.astimezone(PLUS_TWO),
        end_time=first.end_time.astimezone(PLUS_TWO),
    )
    reordered = dict(reversed(list(json.loads(first.to_json()).items())))
    assert record_from_json(json.dumps(reordered)).to_json() == first.to_json()
    assert shifted.to_json() == first.to_json()


def test_session_record_detaches_canonical_configuration():
    raw = {"schema_version": 1}
    config = TradeAlertsConfig(raw)
    session = SessionRecord.from_config(
        record_id="session-1", session="2026-07-06", started_at=T0, config=config
    )
    raw["config_version"] = "CHANGED"
    assert session.config_json == TradeAlertsConfig({"schema_version": 1}).canonical_json
    assert session.config_hash == config.config_hash


def test_loader_snapshot_links_session_and_candidate_without_later_reload_mutation(
    tmp_path, monkeypatch
):
    from consensus_engine import config as config_loader

    path = tmp_path / "config.yaml"
    path.write_text("trade_alerts:\n  schema_version: 1\n")
    monkeypatch.setattr(config_loader, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config_loader, "_config", None)
    first_config = config_loader.get_trade_alerts_config()
    session = SessionRecord.from_config(
        record_id="session-loader-1",
        session="2026-07-06",
        started_at=T0,
        config=first_config,
    )
    candidate = replace(
        _candidate(),
        session_record_id=session.record_id,
        config_version=session.config_version,
        config_hash=session.config_hash,
    )
    before = (session.to_json(), candidate.to_json())

    path.write_text(
        "trade_alerts:\n  schema_version: 1\n  config_version: CHANGED\n"
    )
    config_loader.reload()
    changed_config = config_loader.get_trade_alerts_config()

    assert changed_config.config_hash != first_config.config_hash
    assert (session.to_json(), candidate.to_json()) == before


def test_session_record_rejects_tampered_config_hash():
    session = _all_records()[-1]
    with pytest.raises(RecordError):
        replace(session, config_hash="b" * 64)


def test_session_record_rejects_tampered_config_version():
    session = _all_records()[-1]
    with pytest.raises(RecordError):
        replace(session, config_version="TAMPERED")


def test_session_record_rejects_noncanonical_config_json():
    session = _all_records()[-1]
    with pytest.raises(RecordError):
        replace(session, config_json=session.config_json + " ")


def test_deterministic_record_proof_is_written_under_tmp():
    records = _all_records()
    payload = {
        "record_count": len(records),
        "records": [record.to_json() for record in records],
    }
    proof = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    path = Path("/tmp/m13-domain-model-proof.json")
    path.write_text(proof)
    assert path.read_bytes() == proof.encode("utf-8")
