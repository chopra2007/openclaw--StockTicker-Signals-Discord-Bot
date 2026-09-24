"""M9.1CV contracts for strict retained ORB5 stage-1 results."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.orb5_stage1_result as subject
from consensus_engine.search_run_config import HELD_OUT_TICKERS, STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.stage1_training_measurement import ResolvedTrainingTrade
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
CANDIDATES = STAGE1_CANDIDATES[subject.PLAYBOOK]
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)
DISABLED = (
    "ORIGINAL_AVAILABILITY_GAP", "CORRECTIONS_FINALITY_GAP",
    "POINT_IN_TIME_MEMBERSHIP_GAP",
)


def event(candidate, *, ticker="NVDA", direction="LONG", resolved_r=1.0,
          costs_complete=True, tested_axes=None, alert_offset=0):
    axes = tuple(name for name, _value in candidate.settings)
    trade = ResolvedTrainingTrade(
        subject.PLAYBOOK, candidate.candidate_id, ticker, direction,
        START + timedelta(minutes=5), resolved_r, "D106_D107_COSTS_V1",
        costs_complete, axes if tested_axes is None else tested_axes,
        (f"{candidate.candidate_id}:{ticker}:{direction}",),
    )
    return subject.Orb5Stage1Event(
        "2026-01-05", START + timedelta(seconds=alert_offset), trade)


def run(order, *, resolved_r=None, sessions=SESSIONS, disabled=DISABLED, events=None):
    candidate = CANDIDATES[order]
    rows = (event(candidate, resolved_r=float(18 - order if resolved_r is None else resolved_r)),) \
        if events is None else events
    return subject.run_orb5_candidate_stage1(
        candidate=candidate, events=rows, evaluated_sessions=sessions,
        disabled_rules=disabled,
    )


def runs(**changes):
    rows = [run(order) for order in range(18)]
    for order, replacement in changes.items():
        rows[int(order)] = replacement
    return tuple(rows)


def test_all_18_costed_results_rank_and_preserve_winner_alert_events():
    result = subject.compare_orb5_stage1(tuple(reversed(runs())))

    assert result.version == subject.COMPARISON_VERSION
    assert result.status == "RANKED" and not result.blockers
    assert tuple(row.candidate_id for row in result.runs) == tuple(
        row.candidate_id for row in CANDIDATES)
    assert result.winner.measurement.candidate == CANDIDATES[0]
    assert result.accepted_winner.measurement == result.winner
    assert len(result.accepted_winner.candidate_measurements) == 18
    preserved = result.accepted_winner.events[0]
    assert preserved.alerted_at == START
    assert preserved.trade.input_record_ids == (f"{CANDIDATES[0].candidate_id}:NVDA:LONG",)
    assert preserved.trade.costs_complete


def test_frozen_ties_end_with_preregistered_candidate_order():
    result = subject.compare_orb5_stage1(tuple(run(order, resolved_r=1.0) for order in range(18)))
    assert result.winner.measurement.candidate == CANDIDATES[0]
    assert tuple(row.measurement.candidate.table_order for row in result.ranked) == tuple(range(18))


@pytest.mark.parametrize("case", (
    "held_out", "incomplete_cost", "axis_off", "late_alert", "uncovered_session",
    "duplicate_event", "disabled_axis", "incomplete_training_scope",
))
def test_candidate_result_refuses_unproved_or_incomplete_inputs(case):
    candidate = CANDIDATES[0]
    rows = (event(candidate),)
    sessions = SESSIONS
    disabled = DISABLED
    if case == "held_out":
        rows = (event(candidate, ticker=HELD_OUT_TICKERS[0]),)
    elif case == "incomplete_cost":
        rows = (event(candidate, costs_complete=False),)
    elif case == "axis_off":
        rows = (event(candidate, tested_axes=("D-043", "D-044")),)
    elif case == "late_alert":
        with pytest.raises(RecordError, match="alert time cannot be after"):
            event(candidate, alert_offset=360)
        return
    elif case == "uncovered_session":
        sessions = tuple((ticker, "2026-01-06") for ticker in TRAINING_TICKERS)
    elif case == "duplicate_event":
        rows = (event(candidate), event(candidate))
    elif case == "disabled_axis":
        disabled = DISABLED + ("D-043",)
    else:
        sessions = SESSIONS[:-1]
    with pytest.raises(RecordError):
        subject.run_orb5_candidate_stage1(
            candidate=candidate, events=rows, evaluated_sessions=sessions,
            disabled_rules=disabled,
        )


@pytest.mark.parametrize("case", (
    "missing", "duplicate", "wrong_version", "missing_measurement", "coverage", "disabled",
))
def test_comparison_refuses_forgery_or_keeps_missing_results_not_rankable(case):
    rows = list(runs())
    if case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows[1] = rows[0]
    elif case == "wrong_version":
        rows[1] = replace(rows[1], version="FORGED")
    elif case == "missing_measurement":
        rows[1] = replace(rows[1], measurement=None, events=())
    elif case == "coverage":
        rows[1] = replace(rows[1], evaluated_sessions=rows[1].evaluated_sessions[:-1])
    else:
        rows[1] = replace(rows[1], measurement=replace(
            rows[1].measurement, disabled_rules=("ANOTHER_GAP",)))

    if case in {"missing", "duplicate", "wrong_version"}:
        with pytest.raises(RecordError):
            subject.compare_orb5_stage1(rows)
    else:
        result = subject.compare_orb5_stage1(rows)
        assert result.status == "NOT_RANKABLE"
        assert result.winner is None and result.accepted_winner is None
        assert result.blockers


def test_empty_candidate_run_is_visible_and_never_ranked():
    empty = run(0, events=())
    assert empty.measurement is None and not empty.events
    result = subject.compare_orb5_stage1((empty, *runs()[1:]))
    assert result.status == "NOT_RANKABLE"
    assert result.blockers == (f"{CANDIDATES[0].candidate_id}:MEASUREMENT_UNAVAILABLE",)


@pytest.mark.parametrize("case", ("session", "alert", "close"))
def test_session_must_match_both_alert_and_resolved_trade_dates(case):
    original = event(CANDIDATES[0])
    changes = {"session": "2026-01-06"}
    if case == "alert":
        changes = {"alerted_at": START - timedelta(days=1)}
    elif case == "close":
        changes = {"trade": replace(original.trade, closed_at=START + timedelta(days=1))}
    with pytest.raises(RecordError, match="match the alert and trade close Pacific dates"):
        replace(original, **changes)


def test_session_date_uses_pacific_date_across_utc_midnight():
    original = event(CANDIDATES[0])
    close = datetime(2026, 1, 6, 0, 5, tzinfo=timezone.utc)
    row = replace(original, alerted_at=close - timedelta(minutes=10),
                  trade=replace(original.trade, closed_at=close))
    assert row.session == "2026-01-05"
    assert run(0, events=(row,)).measurement is not None
    with pytest.raises(RecordError, match="Pacific dates"):
        replace(row, session="2026-01-06")


@pytest.mark.parametrize("field,value", (
    ("mean_profit_r", 1000.0), ("weekly_win_rate", 0.0),
    ("drawdown_recovery_weeks", 100.0), ("bootstrap_lower_bound", 1000.0),
    ("trade_count", 999), ("week_count", 999),
    ("policy_version", "FORGED"), ("evaluated_tickers", TRAINING_TICKERS[:-1]),
))
def test_comparison_recomputes_every_measurement_field(field, value):
    rows = list(runs())
    measured = rows[-1].measurement
    if field in {"mean_profit_r", "weekly_win_rate", "drawdown_recovery_weeks"}:
        forged = replace(measured, measurement=replace(measured.measurement, **{field: value}))
    else:
        forged = replace(measured, **{field: value})
    rows[-1] = replace(rows[-1], measurement=forged)
    result = subject.compare_orb5_stage1(rows)
    assert result.status == "NOT_RANKABLE"
    assert result.winner is None and result.accepted_winner is None
    assert f"{rows[-1].candidate_id}:MEASUREMENT_EVENTS_MISMATCH" in result.blockers


@pytest.mark.parametrize("case", (
    "removed", "added", "replaced_return", "wrong_candidate", "incomplete_cost",
    "axis_off", "duplicate", "uncovered", "hidden_measurement",
))
def test_comparison_revalidates_supplied_event_sets(case):
    rows = list(runs())
    candidate = CANDIDATES[0]
    original = rows[0].events[0]
    replacements = {
        "removed": (),
        "added": (original, event(candidate, ticker="AAPL", resolved_r=-2.0)),
        "replaced_return": (event(candidate, resolved_r=-100.0),),
        "wrong_candidate": (event(CANDIDATES[1]),),
        "incomplete_cost": (event(candidate, costs_complete=False),),
        "axis_off": (event(candidate, tested_axes=("D-043",)),),
        "duplicate": (original, original),
        "uncovered": (original,),
        "hidden_measurement": (original,),
    }
    rows[0] = replace(rows[0], events=replacements[case])
    if case == "uncovered":
        rows[0] = replace(rows[0], evaluated_sessions=tuple(
            (ticker, "2026-01-06") for ticker in TRAINING_TICKERS))
    elif case == "hidden_measurement":
        rows[0] = replace(rows[0], measurement=None)
    result = subject.compare_orb5_stage1(rows)
    assert result.status == "NOT_RANKABLE" and result.blockers
    assert result.winner is None and result.accepted_winner is None


@pytest.mark.parametrize("empty", (False, True))
def test_default_required_gaps_are_visible_on_every_run(empty):
    rows = tuple(subject.run_orb5_candidate_stage1(
        candidate=candidate, events=() if empty else (event(candidate),),
        evaluated_sessions=SESSIONS,
    ) for candidate in CANDIDATES)
    for row in rows:
        assert row.disabled_rules == DISABLED
        if not empty:
            assert row.measurement.disabled_rules == DISABLED
    result = subject.compare_orb5_stage1(rows)
    if not empty:
        assert result.status == "RANKED"
        assert result.accepted_winner.measurement.disabled_rules == DISABLED


@pytest.mark.parametrize("disabled", ((), DISABLED[1:], DISABLED[:1] + DISABLED[2:], DISABLED[:-1]))
@pytest.mark.parametrize("empty", (False, True))
def test_required_gaps_cannot_be_omitted_explicitly_or_forged(disabled, empty):
    with pytest.raises(RecordError, match="OFF and untested"):
        run(0, disabled=disabled, events=() if empty else None)
    rows = list(runs())
    for index, row in enumerate(rows):
        rows[index] = replace(row, disabled_rules=disabled,
                              measurement=None if empty else replace(row.measurement, disabled_rules=disabled),
                              events=() if empty else row.events)
    result = subject.compare_orb5_stage1(rows)
    assert result.status == "NOT_RANKABLE"
    assert result.winner is None and result.accepted_winner is None
    assert any("OFF and untested" in blocker for blocker in result.blockers)
