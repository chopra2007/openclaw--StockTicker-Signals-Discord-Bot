"""M9.1CH: connect the HOD-compression RS-report-only candidate to stage 1.

Relative strength remains measured and visible in the eligibility assessment,
but a measured value below the frozen threshold does not prevent arming.  An
absent or unusable RS value remains unavailable; this comparison never fills
one in.  Every other HOD-compression gate and the strict stage-1 measurement
boundary are unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .hod_comp_rs_replay import HodCompRsReplayStrategy
from .hod_comp_rs_stage1_run import (
    HodCompRsStage1Run, HodCompRsTrainingEvent, _evaluate_event, _histories_by_key,
    _outcome_input_ids, _validate_event,
)
from .or_failure_stage1_run import ExcludedTrainingEvent, SessionWithoutEvent
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches
from .rs_trend_eligibility import (
    ARMED_GATES, PASS, HodCompRsEligibilityMachine, RsTrendAssessment,
    RsTrendRequest, evaluate_rs_trend_eligibility,
)
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import ResolvedTrainingTrade, measure_stage1_candidate
from .strategy_interface import StrategyState
from .trade_alerts_models import RecordError, SessionRecord

RUN_VERSION = "M91CH_HOD_COMP_RS_REPORT_ONLY_STAGE1_RUN_V1"
PLAYBOOK = "HOD_COMP_RS"
REPORT_ONLY_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][1]


def _report_only_assessment(request: RsTrendRequest) -> RsTrendAssessment:
    """Keep the measured RS gate visible while removing only its cutoff veto."""
    assessment = evaluate_rs_trend_eligibility(request)
    rs_gate = assessment.gate("RS_TREND")
    if rs_gate.observed is None:
        return assessment
    gates = {row.name: row for row in assessment.gates}
    if assessment.gate("EVALUATION_WINDOW").status != PASS:
        return assessment
    state = "ARMED" if all(
        name == "RS_TREND" or gates[name].status == PASS for name in ARMED_GATES
    ) else assessment.state.state
    if state != "ARMED":
        return assessment
    reasons = tuple(reason for reason in assessment.reasons
                    if not reason.startswith("RS_TREND:"))
    return replace(assessment, state=StrategyState("ARMED"), reasons=reasons)


class _ReportOnlyEligibilityMachine(HodCompRsEligibilityMachine):
    def evaluate(self, request: RsTrendRequest) -> RsTrendAssessment:
        self._check(request)
        assessment = _report_only_assessment(request)
        self._time = request.context.evaluated_at
        return assessment


class HodCompRsReportOnlyReplayStrategy(HodCompRsReplayStrategy):
    """Research-only replay owner whose measured RS cutoff is report-only."""

    def reset(self, session: SessionRecord) -> None:
        super().reset(session)
        self._eligibility_owner = _ReportOnlyEligibilityMachine(
            session=session, symbol=self._symbol, instrument_type=self._instrument_type,
            direction=self._direction, strategy_version=self._version,
            policy=self._eligibility_policy,
        )

    def _assess_eligibility(self, context, step):
        assessment = _report_only_assessment(
            RsTrendRequest(context, self._eligibility_policy, step.status))
        self._eligibility = assessment
        return assessment


def run_report_only_hod_comp_rs_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[HodCompRsTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> HodCompRsStage1Run:
    """Measure COMP_ON_060|RS_REPORT_ONLY without opening held-out data."""
    if candidate != REPORT_ONLY_CANDIDATE:
        raise RecordError("this runner supports only COMP_ON_060|RS_REPORT_ONLY")
    histories = _histories_by_key(retained)
    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, HodCompRsTrainingEvent):
            raise RecordError("events must be HodCompRsTrainingEvent records")
        if not isinstance(event.strategy, HodCompRsReportOnlyReplayStrategy):
            raise RecordError("report-only events require HodCompRsReportOnlyReplayStrategy")
        key = _validate_event(event, histories)
        if key in supplied_sessions:
            raise RecordError("duplicate HOD-compression training event")
        supplied_sessions.add(key)

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
        key = (event.ticker, event.session)
        history = histories[key]
        direction = event.contexts[0].direction
        outcome = _evaluate_event(event)
        evaluated_sessions.add(key)
        if outcome is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, "NO_COMPOSED_OUTCOME"))
            continue
        if outcome.status != "READY":
            reason = outcome.reasons[0] if outcome.reasons else outcome.status
            excluded.append(ExcludedTrainingEvent(event.ticker, event.session, direction, reason))
            continue
        if outcome.risk is None or not outcome.targets:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, "RISK_OR_TARGETS_UNAVAILABLE"))
            continue
        evaluated = evaluate_playbook_outcome(
            record_id=f"{RUN_VERSION}:{event.ticker}:{event.session}:{direction}",
            candidate_id=candidate.candidate_id, strategy_id=PLAYBOOK,
            direction=direction, risk=outcome.risk, targets=outcome.targets,
            alert_time=outcome.evaluated_at, evaluated_at=history.batch.request.end,
            trades=event.trades, quotes=event.quotes, policy=fill_policy,
            history=history.batch,
        )
        if evaluated.resolved_r is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, evaluated.status_reason))
            continue
        input_ids = _outcome_input_ids(outcome, evaluated)
        if not input_ids:
            raise RecordError("a resolved training event must retain its input record IDs")
        resolved.append(ResolvedTrainingTrade(
            playbook=PLAYBOOK, candidate_id=candidate.candidate_id,
            ticker=event.ticker, direction=direction,
            closed_at=max(row.at for row in evaluated.unit_exits),
            resolved_r=evaluated.resolved_r, cost_model_version=fill_policy.version,
            costs_complete=evaluated.fill.status == "FILLED"
            and evaluated.fill.total_cost_per_share is not None,
            tested_axes=("D-048", "D-049"), input_record_ids=input_ids,
        ))

    evaluated_tickers = tuple(ticker for ticker in TRAINING_TICKERS
                              if any(key[0] == ticker for key in evaluated_sessions))
    measurement = measure_stage1_candidate(
        playbook=PLAYBOOK, candidate=candidate, trades=tuple(resolved),
        evaluated_tickers=evaluated_tickers, disabled_rules=disabled_rules,
    ) if resolved and evaluated_sessions == set(histories) else None
    return HodCompRsStage1Run(
        RUN_VERSION, candidate.candidate_id, measurement, tuple(resolved), tuple(excluded),
        tuple(sorted(evaluated_sessions)))


__all__ = [
    "HodCompRsReportOnlyReplayStrategy", "REPORT_ONLY_CANDIDATE", "RUN_VERSION",
    "run_report_only_hod_comp_rs_stage1",
]
