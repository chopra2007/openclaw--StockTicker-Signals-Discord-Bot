"""M9.1CF: connect the research-only FASTER OR-failure candidate to stage 1.

The frozen FASTER arm is deliberately separate from the production
``OR_FAILURE_REV`` confirmation choices.  It uses the existing supplied-record
assessment for every shared gate, but does not treat either a completed minute
close or a failure-bar break as its entry.  Instead, the underlying failed-break
handoff gates must pass, the supplied last trade must be back inside, and the
inside-acceptance gate must pass at the same instant.

This module reads no files and changes no live strategy rule.  Missing quote,
fill or outcome inputs remain visible exclusions and never become estimates.
"""

from __future__ import annotations

from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .or_failure_handoff import (
    ENDED_GATE, EXCURSION_GATE, OWNERSHIP_GATE, PASS, RANGE_GATE,
    REACCEPTANCE_GATE, UNKNOWN,
)
from .or_failure_rev import (
    ACCEPTANCE_GATE, CONFIRMATION_GATE, HANDOFF_GATE, REVERSAL_GATES,
    ReversalAssessment, evaluate_or_failure_rev,
)
from .or_failure_stage1_run import (
    ExcludedTrainingEvent, OrFailureStage1Run, OrFailureTrainingEvent,
    SessionWithoutEvent, _histories_by_key,
)
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import ResolvedTrainingTrade, measure_stage1_candidate
from .trade_alerts_models import Quote, RecordError

RUN_VERSION = "M91CF_OR_FAILURE_FASTER_STAGE1_RUN_V1"
PLAYBOOK = "OR_FAILURE_REV"
FASTER_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][1]
_BASE_BREAK_GATES = (ENDED_GATE, OWNERSHIP_GATE, RANGE_GATE, EXCURSION_GATE)
_FASTER_REVERSAL_GATES = tuple(
    name for name in REVERSAL_GATES if name not in (HANDOFF_GATE, CONFIRMATION_GATE)
)


def _faster_assessment(request) -> tuple[ReversalAssessment, str | None]:
    """Return the shared assessment and why the faster arm did not trigger."""
    if request.confirmation_close is not None or request.failure_bar is not None:
        raise RecordError("the FASTER candidate cannot use a completed-close confirmation")
    assessment = evaluate_or_failure_rev(request)
    handoff = request.handoff
    for name in _BASE_BREAK_GATES:
        gate = handoff.gate(name)
        if gate.status != PASS:
            return assessment, f"{name}:{gate.status}:{gate.reason}"
    reacceptance = handoff.gate(REACCEPTANCE_GATE)
    if reacceptance.status == PASS:
        raise RecordError("the FASTER candidate cannot substitute the confirmed handoff")
    if reacceptance.status != UNKNOWN:
        return assessment, (
            f"{REACCEPTANCE_GATE}:{reacceptance.status}:{reacceptance.reason}")
    for name in _FASTER_REVERSAL_GATES:
        gate = assessment.gate(name)
        if gate.status != PASS:
            return assessment, f"{name}:{gate.status}:{gate.reason}"
    # LAST_BACK_INSIDE_RANGE and INSIDE_ACCEPTANCE are both in the required
    # set above.  The passed base handoff gates prove the real failed break.
    assert assessment.gate(ACCEPTANCE_GATE).status == PASS
    return assessment, None


def run_faster_or_failure_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[OrFailureTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> OrFailureStage1Run:
    """Measure FASTER using break/reject plus inside acceptance, never a close."""
    if candidate != FASTER_CANDIDATE:
        raise RecordError("this runner connection supports only the frozen FASTER candidate")
    histories = _histories_by_key(retained)

    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, OrFailureTrainingEvent):
            raise RecordError("events must be OrFailureTrainingEvent records")
        if (event.ticker, event.session) not in histories:
            raise RecordError("event does not match a retained training session")
        if event.request.confirmation_close is not None or event.request.failure_bar is not None:
            raise RecordError("the FASTER candidate cannot use a completed-close confirmation")
        supplied_sessions.add((event.ticker, event.session))
        for records in (event.trades, event.quotes):
            for record in records:
                if not isinstance(record, Quote):
                    raise RecordError("trade and quote inputs must be Quote records")
                if (record.metadata.instrument_id != event.ticker
                        or record.metadata.session != event.session):
                    raise RecordError(
                        "trade or quote metadata does not match the event ticker and session")

    dispositions: dict[tuple[str, str], SessionWithoutEvent] = {}
    for row in sessions_without_events:
        if not isinstance(row, SessionWithoutEvent):
            raise RecordError("session dispositions must be SessionWithoutEvent records")
        key = (row.ticker, row.session)
        if key not in histories:
            raise RecordError("session disposition does not match a retained training session")
        if key in dispositions or key in supplied_sessions:
            raise RecordError("duplicate or conflicting session disposition")
        dispositions[key] = row
    missing = sorted(set(histories) - supplied_sessions - set(dispositions))
    if missing:
        raise RecordError(f"missing candidate evaluation coverage for retained sessions: {missing}")

    resolved: list[ResolvedTrainingTrade] = []
    excluded: list[ExcludedTrainingEvent] = [
        ExcludedTrainingEvent(ticker, session, "UNKNOWN", reason)
        for ticker, session, reason in retained.skipped
    ]
    excluded.extend(ExcludedTrainingEvent(
        row.ticker, row.session, "UNKNOWN", f"{row.status}:{row.reason}")
        for row in dispositions.values())
    evaluated_sessions = {key for key, row in dispositions.items() if row.status == "NO_EVENT"}

    for event in events:
        history = histories[(event.ticker, event.session)]
        assessment, reason = _faster_assessment(event.request)
        evaluated_sessions.add((event.ticker, event.session))
        if reason is not None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, assessment.direction, reason))
            continue
        if assessment.risk is None or not assessment.targets:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, assessment.direction,
                "RISK_OR_TARGETS_UNAVAILABLE"))
            continue

        outcome = evaluate_playbook_outcome(
            record_id=f"{RUN_VERSION}:{event.ticker}:{event.session}:{assessment.direction}",
            candidate_id=candidate.candidate_id, strategy_id=PLAYBOOK,
            direction=assessment.direction, risk=assessment.risk,
            targets=assessment.targets, alert_time=assessment.evaluated_at,
            evaluated_at=history.batch.request.end, trades=event.trades,
            quotes=event.quotes, policy=fill_policy, history=history.batch,
        )
        if outcome.resolved_r is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, assessment.direction, outcome.status_reason))
            continue
        input_ids = tuple(dict.fromkeys(
            (*assessment.structural_input_ids, *outcome.outcome.input_record_ids)))
        if not input_ids:
            raise RecordError("a resolved training event must retain its input record IDs")
        resolved.append(ResolvedTrainingTrade(
            playbook=PLAYBOOK, candidate_id=candidate.candidate_id,
            ticker=event.ticker, direction=assessment.direction,
            closed_at=max(row.at for row in outcome.unit_exits),
            resolved_r=outcome.resolved_r,
            cost_model_version=fill_policy.version,
            costs_complete=outcome.fill.status == "FILLED"
            and outcome.fill.total_cost_per_share is not None,
            tested_axes=("D-052",), input_record_ids=input_ids,
        ))

    evaluated_tickers = tuple(ticker for ticker in TRAINING_TICKERS
                              if any(key[0] == ticker for key in evaluated_sessions))
    measurement = measure_stage1_candidate(
        playbook=PLAYBOOK, candidate=candidate, trades=tuple(resolved),
        evaluated_tickers=evaluated_tickers, disabled_rules=disabled_rules,
    ) if resolved and evaluated_sessions == set(histories) else None
    return OrFailureStage1Run(
        RUN_VERSION, candidate.candidate_id, measurement, tuple(resolved), tuple(excluded),
        tuple(sorted(evaluated_sessions)))


__all__ = ["RUN_VERSION", "FASTER_CANDIDATE", "run_faster_or_failure_stage1"]
