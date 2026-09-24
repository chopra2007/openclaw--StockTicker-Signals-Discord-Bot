"""M9.1EC resolved retained outcomes at the strict stage-1 input boundary.

Only fully resolved outcomes with a complete accepted cost model become the
``ResolvedTrainingTrade`` records consumed by stage-1 measurement.  Unknown,
unresolved and incomplete-cost outcomes remain counted exclusions.  This
boundary does not measure or rank a candidate, release a result shard, inspect
held-out names, send an alert, or perform a live action.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .orb5_trade_walk import Orb5QuoteFilledRecord
from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .playbook_outcome_evaluator import PlaybookOutcomeEvaluation, UnitExit
from .retained_decision_moments import PLAYBOOKS
from .retained_first_four_outcome import (
    RUN_VERSION as OUTCOME_VERSION,
    RetainedFirstFourOutcomeRow,
    RetainedFirstFourOutcomeRun,
)
from .retained_first_four_fill import RetainedFirstFourFillRow
from .search_run_config import (
    STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate,
)
from .stage1_training_measurement import ResolvedTrainingTrade
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EC_RETAINED_FIRST_FOUR_STAGE1_RESULT_V1"


@dataclass(frozen=True)
class RetainedFirstFourStage1ResultRun:
    version: str
    outcome_version: str
    rows: tuple[ResolvedTrainingTrade, ...]
    outcome_count: int
    resolved_outcome_count: int
    fully_costed_count: int
    unresolved_excluded_count: int
    incomplete_cost_excluded_count: int
    unfilled_excluded_count: int
    no_event_excluded_count: int
    unavailable_excluded_count: int
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "outcome_version": self.outcome_version,
            "rows": [
                {
                    "playbook": row.playbook,
                    "candidate_id": row.candidate_id,
                    "ticker": row.ticker,
                    "direction": row.direction,
                    "closed_at": row.closed_at.isoformat(),
                    "resolved_r": row.resolved_r,
                    "cost_model_version": row.cost_model_version,
                    "costs_complete": row.costs_complete,
                    "tested_axes": list(row.tested_axes),
                    "input_record_ids": list(row.input_record_ids),
                }
                for row in self.rows
            ],
            "outcome_count": self.outcome_count,
            "resolved_outcome_count": self.resolved_outcome_count,
            "fully_costed_count": self.fully_costed_count,
            "unresolved_excluded_count": self.unresolved_excluded_count,
            "incomplete_cost_excluded_count": self.incomplete_cost_excluded_count,
            "unfilled_excluded_count": self.unfilled_excluded_count,
            "no_event_excluded_count": self.no_event_excluded_count,
            "unavailable_excluded_count": self.unavailable_excluded_count,
            "disabled_rules": list(self.disabled_rules),
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_outcome_run(run: RetainedFirstFourOutcomeRun) -> None:
    if type(run) is not RetainedFirstFourOutcomeRun or run.version != OUTCOME_VERSION:
        raise RecordError("stage-1 connection requires the accepted outcome run")
    if any((run.result_shard_released, run.held_out_opened,
            run.alert_released, run.live_action)):
        raise RecordError("outcome run opened a later release boundary")
    resolved = 0
    for row in run.rows:
        if type(row) is not RetainedFirstFourOutcomeRow:
            raise RecordError("outcome run rows must use the accepted row type")
        if type(row.fill_row) is not RetainedFirstFourFillRow:
            raise RecordError("outcome row must preserve the accepted fill row")
        decision = row.fill_row.decision
        if (decision.playbook not in PLAYBOOKS
                or decision.ticker not in TRAINING_TICKERS
                or decision.direction not in ("LONG", "SHORT")):
            raise RecordError("outcome row is outside the frozen training boundary")
        if row.fill_row.fill.status != "FILLED" or row.outcome.fill != row.fill_row.fill:
            raise RecordError("outcome row does not preserve its accepted fill")
        if decision.disabled_rules != REQUIRED_DISABLED_RULES:
            raise RecordError("source-gap dependent rules must remain OFF and untested")
        if type(row.outcome) is Orb5QuoteFilledRecord:
            resolved += row.outcome.record.resolved
        elif type(row.outcome) is PlaybookOutcomeEvaluation:
            resolved += row.outcome.resolved_r is not None
        else:
            raise RecordError("outcome run contains an unsupported outcome type")
    if (run.outcome_count != len(run.rows)
            or run.filled_candidate_count != len(run.rows)
            or run.resolved_return_count != resolved):
        raise RecordError("outcome run counts do not match its rows")


def _validate_candidates(candidates: Mapping[str, Candidate]) -> None:
    if not isinstance(candidates, Mapping) or tuple(candidates) != PLAYBOOKS:
        raise RecordError("stage-1 candidates must name the first four in order")
    for playbook, candidate in candidates.items():
        if type(candidate) is not Candidate or candidate not in STAGE1_CANDIDATES[playbook]:
            raise RecordError("stage-1 candidate is outside the frozen catalog")


def _validate_shared_return(outcome: PlaybookOutcomeEvaluation, direction: str) -> None:
    """Check the entry-cost-only return; this does not prove exit costs."""
    record = outcome.outcome
    entry = outcome.fill.modeled_price
    risk = outcome.actual_risk
    numbers = (entry, risk, record.modeled_entry_price, record.outcome_price,
               outcome.resolved_r)
    if (any(type(value) not in (int, float) or not math.isfinite(value)
            for value in numbers)
            or entry <= 0 or risk <= 0
            or record.modeled_entry_price != entry
            or outcome.fill.direction != direction):
        raise RecordError("resolved return has invalid entry, direction or actual risk")
    exits = outcome.unit_exits
    targets = record.target_outcomes
    if (not targets or len(exits) != len(targets)
            or any(type(row) is not UnitExit for row in exits)
            or tuple(row.unit for row in exits) != tuple(range(1, len(targets) + 1))
            or any(type(row.price) not in (int, float) or not math.isfinite(row.price)
                   or row.price <= 0 or row.reason not in ("TARGET", "STOP", "HORIZON")
                   or row.target_name not in {target.target_name for target in targets}
                   for row in exits)):
        raise RecordError("resolved return has invalid unit exits")
    if (outcome.fill.trade_print_time is None
            or any(not outcome.fill.trade_print_time <= row.at <= record.evaluated_at
                   for row in exits)
            or tuple(row.at for row in exits) != tuple(sorted(row.at for row in exits))):
        raise RecordError("resolved return has invalid exit times")
    average_exit = sum(row.price for row in exits) / len(exits)
    sign = 1 if direction == "LONG" else -1
    expected_r = sum(sign * (row.price - entry) for row in exits) / (len(exits) * risk)
    if (not math.isclose(record.outcome_price, average_exit, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(outcome.resolved_r, expected_r,
                                rel_tol=1e-12, abs_tol=1e-12)):
        raise RecordError("resolved R or outcome price does not match unit exits")


def run_retained_first_four_stage1_results(
    outcome_run: RetainedFirstFourOutcomeRun,
    *, candidates: Mapping[str, Candidate],
) -> RetainedFirstFourStage1ResultRun:
    """Build strict stage-1 input rows from resolved, fully costed outcomes."""
    _validate_outcome_run(outcome_run)
    _validate_candidates(candidates)

    output: list[ResolvedTrainingTrade] = []
    resolved_count = 0
    unresolved_count = 0
    incomplete_cost_count = 0
    for item in outcome_run.rows:
        decision = item.fill_row.decision
        candidate = candidates[decision.playbook]
        outcome = item.outcome

        # The accepted ORB5 outcome still states that its per-trade R is gross
        # of exit-side costs.  It cannot cross this fully costed boundary.
        if type(outcome) is Orb5QuoteFilledRecord:
            if outcome.resolved:
                resolved_count += 1
                incomplete_cost_count += 1
            else:
                unresolved_count += 1
            continue

        assert type(outcome) is PlaybookOutcomeEvaluation
        if outcome.resolved_r is None:
            unresolved_count += 1
            continue
        resolved_count += 1
        if (outcome.outcome.coverage_status != "COMPLETE"
                or outcome.outcome.result not in ("RESOLVED", "AMBIGUOUS")
                or outcome.outcome.data_quality != "VALID"
                or not outcome.unit_exits):
            raise RecordError("resolved outcome does not prove a complete result")
        _validate_shared_return(outcome, decision.direction)
        if outcome.outcome.candidate_id != candidate.candidate_id:
            raise RecordError("resolved outcome does not match the frozen stage-1 candidate")
        input_ids = tuple(dict.fromkeys(
            (*decision.input_record_ids, *outcome.outcome.input_record_ids)))
        if (not input_ids
                or not set(input_ids).issubset(decision.retained_source_record_ids)):
            raise RecordError("stage-1 result cites a record outside the retained session")
        # The shared evaluator also exits at raw bar prices.  Its fill cost
        # proves only entry friction; no accepted exit-cost evidence exists.
        # Keep even arithmetically consistent returns out of stage 1.
        incomplete_cost_count += 1

    rows = tuple(output)
    return RetainedFirstFourStage1ResultRun(
        RUN_VERSION,
        outcome_run.version,
        rows,
        outcome_run.outcome_count,
        resolved_count,
        len(rows),
        unresolved_count,
        incomplete_cost_count,
        outcome_run.unfilled_excluded_count,
        outcome_run.no_event_excluded_count,
        outcome_run.unavailable_excluded_count,
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourStage1ResultRun",
    "run_retained_first_four_stage1_results",
]
