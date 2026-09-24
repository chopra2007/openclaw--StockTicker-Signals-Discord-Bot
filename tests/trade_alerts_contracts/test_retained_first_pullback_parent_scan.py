"""M9.1DE frozen M0.3E parent-selection contracts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_first_pullback_parent_scan import (
    DEFINITION_REFERENCE, RUN_VERSION, ImpulseScanEvidence,
    scan_retained_first_pullback_parents,
)
from consensus_engine.retained_remaining_producers import build_retained_remaining_request
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata

UTC = timezone.utc
DAY = "2026-01-05"
OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
CONVENTIONS = HistoryConventions(
    timestamp="END", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="SYNTHETIC_FINAL", publication="SYNTHETIC_TEST",
    evidence_reference="synthetic-test",
)


def _metadata(at):
    return SourceMetadata(
        instrument_id="NVDA", instrument_type="EQUITY", source="EQUS.MINI",
        source_time=at, received_time=at, available_time=at, normalized_time=at,
        session=DAY, quality="VALID", data_mode="SYNTHETIC_TEST",
    )


def _bar(number, *, open_=100.0, high=100.1, low=99.9, close=100.0):
    start = OPEN + timedelta(minutes=number)
    end = start + timedelta(minutes=1)
    return Bar(
        record_id=f"bar-{number}", metadata=_metadata(end), start_time=start,
        end_time=end, is_final=True, open=open_, high=high, low=low, close=close,
        volume=1000.0, adjustment_basis="SYNTHETIC_TEST",
        price_convention="USD_PER_SHARE", volume_convention="SHARES",
    )


def _input(direction="LONG"):
    bars = [_bar(i) for i in range(10)]
    if direction == "LONG":
        bars[4] = _bar(4, open_=100.3, high=101.0, low=100.2, close=100.9)
        bars[5] = _bar(5, open_=100.8, high=100.95, low=100.5, close=100.7)
        bars[6] = _bar(6, open_=100.7, high=100.9, low=100.3, close=100.5)
    else:
        bars[4] = _bar(4, open_=99.7, high=99.8, low=99.0, close=99.1)
        bars[5] = _bar(5, open_=99.2, high=99.5, low=99.05, close=99.3)
        bars[6] = _bar(6, open_=99.3, high=99.7, low=99.1, close=99.5)
    batch = HistoryBatch(
        HistoryRequest("NVDA", OPEN, OPEN + timedelta(minutes=10)),
        "EQUS.MINI", CONVENTIONS, tuple(bars),
    )
    history = SimpleNamespace(ticker="NVDA", session=DAY, batch=batch)
    return CandidateEventInput(
        "FIRST_PULLBACK_VWAP", "NVDA", DAY, (OPEN + timedelta(minutes=8),),
        history, (), (), tuple(bar.record_id for bar in bars),
    )


def _evidence(value):
    return (ImpulseScanEvidence(
        value.ticker, value.session, OPEN + timedelta(minutes=7), 1.0, 4.0,
        100.0, tuple(bar.record_id for bar in value.history.batch.bars[:7]),
        "SYNTHETIC_TEST_ONLY",
    ),)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_confirmed_impulse_builds_a_canonical_pullback_step(direction):
    value = _input(direction)
    result = scan_retained_first_pullback_parents(value, evidence=_evidence(value))
    assert result.version == RUN_VERSION
    assert result.directions == (direction,)
    assert len(result.pullback_steps) == 1
    step = result.pullback_steps[0]
    assert step.measurement.feature_version == "M83_IMPULSE_PULLBACK_V1"
    assert step.measurement.input_record_ids
    assert result.unavailable_reasons == ()
    connected = build_retained_remaining_request(value, impulse_evidence=_evidence(value))
    assert connected.pullback_steps == result.pullback_steps
    assert connected.missing_required_inputs == (
        "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")


def test_missing_required_numeric_evidence_stays_explicit():
    result = scan_retained_first_pullback_parents(_input())
    assert result.pullback_steps == ()
    assert result.unavailable_reasons == (
        "ATR_1M_UNAVAILABLE", "DAILY_ATR_UNAVAILABLE", "VWAP_UNAVAILABLE")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_numeric_evidence_without_a_qualifying_impulse_names_only_parent_gap(direction):
    value = _input(direction)
    facts = (replace(_evidence(value)[0], daily_atr=100.0),)
    result = scan_retained_first_pullback_parents(value, evidence=facts)
    assert result.pullback_steps == ()
    assert result.unavailable_reasons == ("CONFIRMED_IMPULSE_UNAVAILABLE",)


@pytest.mark.parametrize("case,reason", (
    ("provisional", "IMPULSE_WINDOW_PROVISIONAL"),
    ("revision", "IMPULSE_WINDOW_REVISION_UNAVAILABLE"),
    ("missing", "IMPULSE_WINDOW_MISSING"),
    ("conflict", "IMPULSE_WINDOW_CONFLICT"),
))
def test_final_available_complete_bars_are_required(case, reason):
    value = _input()
    bars = list(value.history.batch.bars)
    if case == "provisional":
        bars[0] = replace(bars[0], is_final=False)
    elif case == "revision":
        bars[0] = replace(bars[0], metadata=replace(bars[0].metadata, revision=1))
    elif case == "missing":
        del bars[0]
    else:
        bars.append(replace(bars[0], record_id="conflict", high=101.0))
    batch = replace(value.history.batch, bars=tuple(bars))
    value = replace(value, history=SimpleNamespace(ticker="NVDA", session=DAY, batch=batch),
                    source_record_ids=tuple(bar.record_id for bar in bars))
    result = scan_retained_first_pullback_parents(value, evidence=_evidence(value))
    assert result.pullback_steps == ()
    assert result.unavailable_reasons == (reason,)
    connected = build_retained_remaining_request(value, impulse_evidence=_evidence(value))
    assert connected.pullback_steps == ()
    assert connected.missing_required_inputs == (
        reason, "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")


def test_wrong_playbook_and_source_scope_are_refused():
    value = _input()
    with pytest.raises(RecordError, match="FIRST_PULLBACK_VWAP"):
        scan_retained_first_pullback_parents(replace(value, playbook="CRVOL_ORB5"))
    bad = replace(value.history.batch.bars[0], metadata=replace(
        value.history.batch.bars[0].metadata, instrument_id="AAPL"))
    with pytest.raises(RecordError, match="history record source or symbol contradicts its batch"):
        replace(value.history.batch, bars=(bad, *value.history.batch.bars[1:]))
    # A consistent foreign batch reaches the scan's own producer-scope check.
    batch = replace(
        value.history.batch,
        request=replace(value.history.batch.request, symbol="AAPL"),
        bars=tuple(replace(bar, metadata=replace(bar.metadata, instrument_id="AAPL"))
                   for bar in value.history.batch.bars),
    )
    with pytest.raises(RecordError, match="match the producer"):
        scan_retained_first_pullback_parents(replace(
            value, history=SimpleNamespace(ticker="NVDA", session=DAY, batch=batch)))


def _with_bars(value, bars):
    batch = replace(value.history.batch, bars=tuple(bars))
    return replace(value, history=SimpleNamespace(ticker=value.ticker, session=DAY, batch=batch))


def _late_input(direction, kind):
    value = _input(direction)
    early = OPEN + timedelta(minutes=8)
    late = OPEN + timedelta(minutes=10)
    arrived = OPEN + timedelta(minutes=9)
    value = replace(value, decision_moments=(late, early))
    facts = _evidence(value)
    if kind == "bar":
        bars = list(value.history.batch.bars)
        bars[6] = replace(bars[6], metadata=replace(
            bars[6].metadata, available_time=arrived, received_time=arrived,
            normalized_time=arrived))
        value = _with_bars(value, bars)
    elif kind == "evidence":
        facts = (replace(facts[0], available_at=arrived),)
    else:
        # Later qualifying numbers must not replace the earlier failing gates.
        facts = (replace(facts[0], available_at=arrived),
                 replace(facts[0], daily_atr=100.0))
    return value, facts, early, late


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("kind", ("bar", "evidence", "qualifying_evidence"))
def test_later_available_facts_cannot_create_an_earlier_step(direction, kind):
    value, facts, early, late = _late_input(direction, kind)
    earlier = scan_retained_first_pullback_parents(
        replace(value, decision_moments=(early,)), evidence=facts)
    assert earlier.pullback_steps == ()
    result = scan_retained_first_pullback_parents(value, evidence=facts)
    assert result.directions == (direction,)
    assert result.pullback_steps[0].evaluated_at == late
    assert result.pullback_steps[0].measurement.evaluated_at == late
    assert build_retained_remaining_request(value, impulse_evidence=facts).pullback_steps == result.pullback_steps


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("index", (6, 7, 9))
def test_only_gaps_through_confirmation_can_block_the_parent(direction, index):
    value = replace(_input(direction), decision_moments=(OPEN + timedelta(minutes=10),))
    facts = _evidence(value)
    value = _with_bars(value, [bar for i, bar in enumerate(value.history.batch.bars) if i != index])
    result = scan_retained_first_pullback_parents(value, evidence=facts)
    if index == 6:
        assert result.pullback_steps == ()
        assert result.unavailable_reasons == ("IMPULSE_WINDOW_MISSING",)
    else:
        assert result.directions == (direction,)
        assert result.impulse_windows == ((OPEN, OPEN + timedelta(minutes=5)),)
        assert result.unavailable_reasons == ()
        # A known parent does not make incomplete later pullback data complete.
        assert any(feature.missing_reason == "PULLBACK_MISSING"
                   for feature in result.pullback_steps[0].measurement.features)
        assert build_retained_remaining_request(value, impulse_evidence=facts).pullback_steps == result.pullback_steps


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_later_revision_and_numeric_evidence_do_not_rewrite_a_frozen_parent(direction):
    value = replace(_input(direction), decision_moments=(OPEN + timedelta(minutes=7),))
    facts = _evidence(value)
    original = scan_retained_first_pullback_parents(value, evidence=facts)
    arrived = OPEN + timedelta(minutes=9)
    revised = replace(value.history.batch.bars[4], record_id="later-revision", metadata=replace(
        value.history.batch.bars[4].metadata, revision=1, available_time=arrived,
        received_time=arrived, normalized_time=arrived))
    later = _with_bars(value, (*value.history.batch.bars, revised))
    later = replace(later, decision_moments=(OPEN + timedelta(minutes=10), *value.decision_moments))
    result = scan_retained_first_pullback_parents(
        later, evidence=(replace(facts[0], available_at=arrived, atr_1m=100.0), *facts))
    assert result.pullback_steps == original.pullback_steps
    assert result.impulse_windows == original.impulse_windows


def test_recorded_impulse_parent_scan_is_deterministic():
    # Synthetic contract only. Retained finality and numeric parent facts remain gaps.
    value = _input()
    result = scan_retained_first_pullback_parents(value, evidence=_evidence(value))
    proof = {
        "version": result.version,
        "definition": DEFINITION_REFERENCE,
        "evidence_kind": "SYNTHETIC_CONTRACT_ONLY",
        "real_retained_session_match": False,
        "directions": list(result.directions),
        "windows": [[a.isoformat(), b.isoformat()] for a, b in result.impulse_windows],
        "source_record_ids": list(result.source_record_ids),
        "retained_gaps": ["ORIGINAL_AVAILABILITY", "CORRECTION_FINALITY",
                          "ATR_1M", "DAILY_ATR", "VWAP"],
    }
    proof["availability_boundaries"] = []
    proof["supplied_evidence_no_parent"] = []
    for direction in ("LONG", "SHORT"):
        for case, reason in (("no_parent", "CONFIRMED_IMPULSE_UNAVAILABLE"),
                             ("incomplete_window", "IMPULSE_WINDOW_MISSING")):
            missing_parent = _input(direction)
            facts = _evidence(missing_parent)
            if case == "no_parent":
                facts = (replace(facts[0], daily_atr=100.0),)
            else:
                missing_parent = _with_bars(missing_parent, missing_parent.history.batch.bars[1:])
            connected = build_retained_remaining_request(missing_parent, impulse_evidence=facts)
            assert connected.pullback_steps == ()
            assert connected.missing_required_inputs == (
                reason, "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")
            proof["supplied_evidence_no_parent"].append({
                "direction": direction, "case": case,
                "missing_required_inputs": list(connected.missing_required_inputs),
                "source_record_ids": list(connected.retained_source_record_ids),
            })
        for kind in ("bar", "evidence", "qualifying_evidence"):
            delayed, facts, early, late = _late_input(direction, kind)
            before = scan_retained_first_pullback_parents(
                replace(delayed, decision_moments=(early,)), evidence=facts)
            after = scan_retained_first_pullback_parents(delayed, evidence=facts)
            assert before.pullback_steps == ()
            assert after.pullback_steps[0].evaluated_at == late
            proof["availability_boundaries"].append({
                "direction": direction, "kind": kind, "early_steps": len(before.pullback_steps),
                "evaluated_at": after.pullback_steps[0].evaluated_at.isoformat(),
                "measurement": after.pullback_steps[0].measurement.to_json(),
            })
        incomplete = _input(direction)
        facts = _evidence(incomplete)
        incomplete = _with_bars(incomplete, incomplete.history.batch.bars[:7])
        kept = scan_retained_first_pullback_parents(incomplete, evidence=facts)
        assert kept.directions == (direction,)
        proof["availability_boundaries"].append({
            "direction": direction, "kind": "missing_after_confirmation",
            "evaluated_at": kept.pullback_steps[0].evaluated_at.isoformat(),
            "measurement": kept.pullback_steps[0].measurement.to_json(),
        })
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91de-retained-first-pullback-parent-scan-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
