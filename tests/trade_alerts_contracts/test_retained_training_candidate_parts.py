"""M9.1DH sharded candidate record and D-116 inspection contracts."""

from dataclasses import replace
from datetime import date, timedelta
from functools import lru_cache
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_first_four_candidate_run import run_retained_first_four_candidates
from consensus_engine.retained_training_candidate_parts import (
    CandidateSampleDay,
    CandidateSampleField,
    CandidateSampleMoment,
    candidate_sample_fields,
    build_retained_training_candidate_part,
    inspect_retained_candidate_sample,
    merge_retained_training_candidate_parts,
)
from consensus_engine.search_run_config import PLAYBOOKS, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from test_retained_candidate_events import MOMENT, SESSION, _market, _retained


def _part(tickers=TRAINING_TICKERS):
    market = _market() if "NVDA" in tickers else ()
    run = run_retained_first_four_candidates(
        _retained(tickers), market, expected_tickers=tickers,
    )
    return build_retained_training_candidate_part(run)


def test_disjoint_ticker_parts_merge_to_the_same_training_nine_totals():
    parts = tuple(_part((ticker,)) for ticker in TRAINING_TICKERS)
    merged = merge_retained_training_candidate_parts(parts)

    assert merged.event_count == len(PLAYBOOKS) * len(TRAINING_TICKERS)
    assert merged.session_count == len(TRAINING_TICKERS)
    assert merged.source_identity_count == len(TRAINING_TICKERS) + len(_market())
    assert all(len(value) == 64 for value in (
        merged.source_identity_sha256, merged.event_stream_sha256,
    ))
    assert merged.as_dict()["held_out_opened"] is False
    assert merged.as_dict()["gap_dependent_rules"] == "OFF_UNTESTED"


def test_merge_refuses_overlap_missing_names_and_changed_disabled_rules():
    parts = tuple(_part((ticker,)) for ticker in TRAINING_TICKERS)
    with pytest.raises(RecordError, match="overlap"):
        merge_retained_training_candidate_parts((*parts, parts[0]))
    with pytest.raises(RecordError, match="all nine"):
        merge_retained_training_candidate_parts(parts[:-1])
    with pytest.raises(RecordError, match="disabled"):
        merge_retained_training_candidate_parts((replace(parts[0], disabled_rules=()), *parts[1:]))


@lru_cache(maxsize=1)
def _sample_fixture():
    # Supplied synthetic decisions test this boundary only. Actual retained
    # producers are UNAVAILABLE and must never pass by counting those decisions.
    raw = run_retained_first_four_candidates(_retained(), _market())
    events = tuple(replace(event, status="NO_EVENT", reason="SYNTHETIC_NO_TRIGGER",
                           session="2025-11-28" if event.ticker == "SPY" else SESSION)
                   for event in raw.events)
    degraded = tuple(replace(event, session="2025-10-10",
                             retained_source_record_ids=("synthetic-degraded-bar",))
                     for event in raw.events if event.ticker == "NVDA")
    run = replace(raw, events=events + degraded)
    days = tuple(CandidateSampleDay(ticker, "2025-11-28" if ticker == "SPY" else SESSION,
                                   "HALF_DAY" if ticker == "SPY" else "NORMAL", 4)
                 for ticker in TRAINING_TICKERS) + (
        CandidateSampleDay("NVDA", "2025-10-10", "DEGRADED", 0, "DEGRADED_SESSION"),)
    history = next(row for row in _retained().histories if row.ticker == "NVDA")
    market = _market()
    source_ids = next(event.retained_source_record_ids for event in events if event.ticker == "NVDA")
    moments = []
    for playbook in PLAYBOOKS:
        inputs = CandidateEventInput(
            playbook, "NVDA", SESSION, (MOMENT,), history,
            tuple(replace(row.quote, delayed=False) for row in market if row.schema == "trades"),
            tuple(row.quote for row in market if row.schema == "bbo-1m"), source_ids,
        )
        moments.append(CandidateSampleMoment(inputs, candidate_sample_fields(inputs)))
    plan = [(row.ticker, row.session) for row in days]
    day = date(2024, 1, 2)
    while len(plan) < 500:
        if day.weekday() < 5:
            for ticker in TRAINING_TICKERS:
                if len(plan) < 500:
                    plan.append((ticker, day.isoformat()))
        day += timedelta(days=1)
    return run, days, tuple(moments), tuple(plan)


def _inspect(*, run=None, days=None, moments=None, plan=None, part=None):
    original_run, original_days, original_moments, original_plan = _sample_fixture()
    run = original_run if run is None else run
    return inspect_retained_candidate_sample(
        build_retained_training_candidate_part(run) if part is None else part,
        original_days if days is None else days,
        original_moments if moments is None else moments,
        planned_sessions=original_plan if plan is None else plan, sample_run=run,
    )


def test_d116_sample_reports_each_ticker_playbook_day_type_and_consumed_unit():
    inspection = _inspect()
    assert dict(inspection.ticker_event_counts) == {ticker: 4 for ticker in TRAINING_TICKERS}
    assert dict(inspection.playbook_event_counts) == {playbook: 9 for playbook in PLAYBOOKS}
    assert dict(inspection.day_type_counts) == {"NORMAL": 8, "HALF_DAY": 1, "DEGRADED": 1}
    report = inspection.as_dict()
    assert report["full_run_released"] is False
    assert report["sampled_session_count"] == report["required_sample_count"] == 10
    assert report["planned_session_count"] == 500
    for moment in report["adapter_moments"]:
        fields = {field["path"]: field for field in moment["fields"]}
        assert fields["history.batch.bars[0].close"]["value"] == 100.5
        assert fields["history.batch.bars[0].close"]["unit"] == "USD_PER_SHARE"
        assert fields["history.batch.bars[0].volume"]["unit"] == "SHARES"
        assert fields["trades[0].trade_time"]["unit"] == "ABSOLUTE_INSTANT"
        assert fields["quotes[0].bid_size"]["unit"] == "SHARES"
        assert fields["history.batch.conventions.finality"]["value"] == "UNKNOWN"
    assert report["gap_dependent_rules"] == "OFF_UNTESTED"


@pytest.mark.parametrize("case", ("foreign_day", "extra_day", "missing_day", "forged_count",
                                 "swapped_counts", "duplicate_day", "bad_degraded"))
def test_d116_days_and_counts_must_match_the_actual_sample_part(case):
    run, days, _moments, _plan = _sample_fixture()
    if case == "foreign_day":
        days = (*days[:-1], replace(days[-1], session="2025-10-13"))
    elif case == "extra_day":
        days = (*days, replace(days[-1], session="2025-10-13"))
    elif case == "missing_day":
        days = days[:-1]
    elif case == "forged_count":
        days = (replace(days[0], event_count=400), *days[1:])
    elif case == "swapped_counts":
        days = (replace(days[0], event_count=3), replace(days[1], event_count=5), *days[2:])
    elif case == "duplicate_day":
        days = (*days[:-1], days[0])
    else:
        days = (*days[:-1], replace(days[-1], skip_reason=None))
    with pytest.raises(RecordError):
        _inspect(run=run, days=days)


@pytest.mark.parametrize("case", ("ticker_zero", "playbook_zero", "all_unavailable"))
def test_d116_unavailable_decisions_do_not_supply_usable_events(case):
    run, days, _moments, _plan = _sample_fixture()
    events = tuple(replace(event, status="UNAVAILABLE") if (
        case == "all_unavailable" or (case == "ticker_zero" and event.ticker == "LLY")
        or (case == "playbook_zero" and event.playbook == "HOD_COMP_RS")) else event
        for event in run.events)
    run = replace(run, events=events)
    days = tuple(replace(row, event_count=sum(
        event.ticker == row.ticker and event.session == row.session and event.status != "UNAVAILABLE"
        for event in events)) for row in days)
    with pytest.raises(RecordError, match="usable"):
        _inspect(run=run, days=days)


def test_d116_part_must_be_reconstructed_from_the_sample_not_unrelated_totals():
    run, _days, _moments, _plan = _sample_fixture()
    part = build_retained_training_candidate_part(run)
    with pytest.raises(RecordError, match="reproduce"):
        _inspect(part=replace(part, status_totals=()))


@pytest.mark.parametrize("size,passes", ((449, False), (450, False), (451, True),
                                         (500, True), (501, False), (2349, False)))
def test_d116_requires_exact_two_percent_rounded_up(size, passes):
    _run, _days, _moments, plan = _sample_fixture()
    if size > len(plan):
        plan = (*plan, *(("NVDA", (date(2010, 1, 1) + timedelta(days=index)).isoformat())
                         for index in range(size - len(plan))))
    plan = plan[:size]
    if passes:
        assert _inspect(plan=plan).as_dict()["required_sample_count"] == 10
    else:
        with pytest.raises(RecordError, match="2%"):
            _inspect(plan=plan)


@pytest.mark.parametrize("case", ("duplicate", "foreign_ticker", "absent_sample"))
def test_d116_rejects_wrong_full_job_inventory(case):
    _run, _days, _moments, plan = _sample_fixture()
    if case == "duplicate":
        plan = (*plan[:-1], plan[0])
    elif case == "foreign_ticker":
        plan = (*plan[:-1], ("GOOGL", "2024-01-02"))
    else:
        plan = (("NVDA", "2024-12-03"), *plan[1:])
    with pytest.raises(RecordError):
        _inspect(plan=plan)


@pytest.mark.parametrize("playbook", PLAYBOOKS)
@pytest.mark.parametrize("case", ("bar_price_only", "missing_field", "unknown_unit", "empty_unit",
                                 "wrong_unit", "wrong_value", "duplicate_field", "empty_fields"))
def test_d116_every_playbook_needs_the_complete_field_values_and_units(playbook, case):
    _run, _days, moments, _plan = _sample_fixture()
    row = next(row for row in moments if row.inputs.playbook == playbook)
    fields = row.inspected_fields
    index = next(i for i, field in enumerate(fields) if field.path == "history.batch.bars[0].volume")
    field = fields[index]
    if case == "bar_price_only":
        fields = (CandidateSampleField("bar_price", "100.5", "USD_PER_SHARE"),)
    elif case == "missing_field":
        fields = fields[:index] + fields[index + 1:]
    elif case == "empty_fields":
        fields = ()
    elif case == "duplicate_field":
        fields = (*fields, field)
    else:
        changes = {"unknown_unit": {"unit": "UNKNOWN"}, "empty_unit": {"unit": ""},
                   "wrong_unit": {"unit": "CONTRACTS"}, "wrong_value": {"value_json": "999"}}
        fields = fields[:index] + (replace(field, **changes[case]),) + fields[index + 1:]
    moments = tuple(replace(item, inspected_fields=fields) if item is row else item for item in moments)
    with pytest.raises(RecordError, match="every adapter input field"):
        _inspect(moments=moments)


@pytest.mark.parametrize("case", ("missing_playbook", "duplicate_playbook", "foreign_session",
                                 "wrong_moment", "changed_source", "gap_switch"))
def test_d116_field_inspections_must_belong_to_this_sample(case):
    _run, _days, moments, _plan = _sample_fixture()
    if case == "missing_playbook":
        moments = moments[:-1]
    elif case == "duplicate_playbook":
        moments = (*moments[:-1], moments[0])
    else:
        inputs = moments[0].inputs
        if case == "foreign_session":
            inputs = replace(inputs, session="2024-01-02")
        elif case == "wrong_moment":
            inputs = replace(inputs, decision_moments=(MOMENT + timedelta(seconds=1),))
        elif case == "changed_source":
            inputs = replace(inputs, source_record_ids=("foreign-source",))
        else:
            inputs = replace(inputs, disabled_rules=())
        moments = (CandidateSampleMoment(inputs, candidate_sample_fields(inputs)), *moments[1:])
    with pytest.raises(RecordError):
        _inspect(moments=moments)


@pytest.mark.parametrize("case", ("missing_trade_price", "missing_bid", "missing_delay_flag",
                                 "unknown_price_unit", "unknown_volume_unit", "wrong_half_day"))
def test_d116_missing_consumed_inputs_and_calendar_labels_are_refused(case):
    _run, days, moments, _plan = _sample_fixture()
    if case == "wrong_half_day":
        days = tuple(replace(row, day_type="HALF_DAY") if row.ticker == "NVDA"
                     and row.day_type == "NORMAL" else row for row in days)
        with pytest.raises(RecordError, match="calendar"):
            _inspect(days=days)
        return
    value = next(row.inputs for row in moments if row.inputs.playbook == "OR_FAILURE_REV")
    if case == "missing_trade_price":
        value = replace(value, trades=(replace(value.trades[0], last=None),))
    elif case == "missing_bid":
        value = replace(value, quotes=(replace(value.quotes[0], bid=None),))
    elif case == "missing_delay_flag":
        value = replace(value, trades=(replace(value.trades[0], delayed=None),))
    else:
        from types import SimpleNamespace
        attribute = "price" if case == "unknown_price_unit" else "volume"
        conventions = replace(value.history.batch.conventions, **{attribute: "UNKNOWN"})
        batch = replace(value.history.batch, conventions=conventions)
        value = replace(value, history=SimpleNamespace(ticker=value.ticker, session=value.session, batch=batch))
    with pytest.raises(RecordError):
        candidate_sample_fields(value)


def test_recording_sharded_candidate_contract_is_deterministic():
    parts = tuple(_part((ticker,)) for ticker in TRAINING_TICKERS)
    proof = {
        "basis": "SYNTHETIC_CONTRACT_ONLY_NOT_REAL_D116_INSPECTION",
        "parts": [part.as_dict() for part in parts],
        "merged": merge_retained_training_candidate_parts(parts).as_dict(),
        "inspection": _inspect().as_dict(),
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dh-retained-training-candidate-parts-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert _inspect().as_dict() == proof["inspection"]
