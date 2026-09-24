"""M9.1DY restart boundary for the retained first-four evaluator sample.

Each retained session is rebuilt as an evaluator plan.  Incomplete plans stay
unavailable without requiring invented owner settings or a recording boundary.
Complete plans may run only when both exact dependencies are supplied, and the
M9.1DX drive still requires every transition to be recorded before state moves.
This boundary releases no candidate, fill, return, shard, or held-out input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_candidate_events import CandidateEventInput
from .retained_decision_moments import PLAYBOOKS
from .retained_first_four_evaluator_drive import (
    RetainedFirstFourDriveResult,
    TransitionRecorder,
    execute_retained_first_four_evaluator_drive,
)
from .retained_first_four_evaluator_owner import RetainedFirstFourOwnerConfig
from .retained_first_four_evaluator_plan import build_retained_first_four_evaluator_plan
from .retained_first_four_owner_inputs import bind_retained_first_four_owner_inputs
from .search_run_config import TRAINING_TICKERS
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DY_RETAINED_FIRST_FOUR_SAMPLE_RESTART_V1"
SampleKey = tuple[str, str, str]


@dataclass(frozen=True)
class RetainedFirstFourSampleRow:
    """One retained session/playbook result and its exact sample identity."""

    playbook: str
    ticker: str
    session: str
    result: RetainedFirstFourDriveResult

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "ticker": self.ticker,
            "session": self.session,
            "result": self.result.as_dict(),
        }


@dataclass(frozen=True)
class RetainedFirstFourSampleRestart:
    """Evaluator results from one bounded restart, with later releases sealed."""

    version: str
    status: str
    planned_sessions: tuple[tuple[str, str], ...]
    rows: tuple[RetainedFirstFourSampleRow, ...]
    evaluated_step_count: int
    proposed_transition_count: int
    acknowledged_transition_count: int
    candidate_released: bool = False
    fill_calculated: bool = False
    return_calculated: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "status": self.status,
            "planned_sessions": [list(row) for row in self.planned_sessions],
            "rows": [row.as_dict() for row in self.rows],
            "evaluated_step_count": self.evaluated_step_count,
            "proposed_transition_count": self.proposed_transition_count,
            "acknowledged_transition_count": self.acknowledged_transition_count,
            "candidate_released": self.candidate_released,
            "fill_calculated": self.fill_calculated,
            "return_calculated": self.return_calculated,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
        }


def _key(value: CandidateEventInput) -> SampleKey:
    return value.playbook, value.ticker, value.session


def restart_retained_first_four_sample(
    inputs: tuple[CandidateEventInput, ...],
    *,
    planned_sessions: tuple[tuple[str, str], ...],
    owner_configs: Mapping[SampleKey, RetainedFirstFourOwnerConfig] | None = None,
    recorders: Mapping[SampleKey, TransitionRecorder] | None = None,
) -> RetainedFirstFourSampleRestart:
    """Restart exact retained inputs and keep every later release boundary off."""
    if not inputs or any(type(value) is not CandidateEventInput for value in inputs):
        raise RecordError("sample restart requires retained candidate inputs")
    keys = tuple(_key(value) for value in inputs)
    if len(set(keys)) != len(keys):
        raise RecordError("sample restart inputs must have unique playbook sessions")
    if any(value.playbook not in PLAYBOOKS for value in inputs):
        raise RecordError("sample restart supports exactly the frozen first four playbooks")
    if any(value.ticker not in TRAINING_TICKERS for value in inputs):
        raise RecordError("sample restart cannot open a held-out ticker")
    if any(value.disabled_rules != REQUIRED_DISABLED_RULES for value in inputs):
        raise RecordError("sample restart must preserve all source-gap disabled rules")
    plan = tuple(planned_sessions)
    if (not plan or len(set(plan)) != len(plan)
            or any(ticker not in TRAINING_TICKERS for ticker, _session in plan)):
        raise RecordError("sample restart needs unique planned training sessions")
    expected = {
        (playbook, ticker, session)
        for ticker, session in plan
        for playbook in PLAYBOOKS
    }
    if set(keys) != expected:
        raise RecordError("sample restart inputs must exactly cover every planned playbook session")
    by_key = dict(zip(keys, inputs))
    ordered_keys = tuple(
        (playbook, ticker, session)
        for ticker, session in plan
        for playbook in PLAYBOOKS
    )
    ordered_inputs = tuple(by_key[key] for key in ordered_keys)

    supplied_configs = {} if owner_configs is None else owner_configs
    supplied_recorders = {} if recorders is None else recorders
    plans = tuple(
        build_retained_first_four_evaluator_plan(value) for value in ordered_inputs
    )
    ready = {
        key for key, built in zip(ordered_keys, plans)
        if bind_retained_first_four_owner_inputs(built).status == "READY"
    }
    if set(supplied_configs) != ready or set(supplied_recorders) != ready:
        raise RecordError(
            "sample restart needs exact owner config and recorder keys for ready plans"
        )

    rows = []
    for key, value, built in zip(ordered_keys, ordered_inputs, plans):
        result = execute_retained_first_four_evaluator_drive(
            built,
            supplied_configs.get(key),
            supplied_recorders.get(key),
        )
        rows.append(RetainedFirstFourSampleRow(
            value.playbook, value.ticker, value.session, result,
        ))
    results = tuple(row.result for row in rows)
    return RetainedFirstFourSampleRestart(
        RUN_VERSION,
        "EVALUATED" if all(row.status == "EVALUATED" for row in results) else "UNAVAILABLE",
        plan,
        tuple(rows),
        sum(row.evaluated_step_count for row in results),
        sum(row.proposed_transition_count for row in results),
        sum(row.acknowledged_transition_count for row in results),
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourSampleRestart",
    "RetainedFirstFourSampleRow",
    "SampleKey",
    "restart_retained_first_four_sample",
]
