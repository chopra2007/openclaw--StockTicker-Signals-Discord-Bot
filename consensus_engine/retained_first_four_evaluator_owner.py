"""M9.1DW canonical evaluator owners for admitted retained inputs.

This boundary constructs the existing first-four replay owners only after the
M9.1DV gate admits the complete plan.  It does not evaluate a step, confirm a
transition, write a record or release a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .first_pullback_vwap import PullbackVwapPolicy
from .first_pullback_vwap_replay import FirstPullbackVwapReplayStrategy
from .hod_comp_rs_replay import HodCompRsReplayStrategy
from .hod_comp_rs_risk_confidence import SuppressionPolicy
from .hod_comp_rs_trigger import TriggerPolicy as HodTriggerPolicy
from .impulse_pullback import PullbackPolicy
from .orb5_eligibility import EligibilityPolicy
from .orb5_replay import Orb5ReplayStrategy
from .orb5_trigger import TriggerPolicy as OrbTriggerPolicy
from .or_failure_rev import ReversalPolicy
from .or_failure_rev_replay import OrFailureRevReplayStrategy
from .retained_first_four_evaluator_plan import RetainedFirstFourEvaluatorPlan
from .retained_first_four_owner_inputs import bind_retained_first_four_owner_inputs
from .rs_trend_eligibility import RsTrendPolicy
from .trade_alerts_models import RecordError, SessionRecord
from .utils.time_context import as_utc

RUN_VERSION = "M91DW_RETAINED_FIRST_FOUR_EVALUATOR_OWNER_V1"


@dataclass(frozen=True)
class RetainedFirstFourOwnerConfig:
    """Supplied policy and identity values required by one canonical owner."""

    strategy_version: str
    definition_reference: str
    record_prefix: str
    policies: tuple[object, ...]
    impulse_window: tuple[datetime, datetime] | None = None


def _identity(plan: RetainedFirstFourEvaluatorPlan):
    identities = {
        (
            step.confidence.request.context.session,
            step.confidence.request.context.symbol,
            step.confidence.request.context.instrument_type,
            step.confidence.request.context.direction,
        )
        for step in plan.steps
    }
    if len(identities) != 1:
        raise RecordError("admitted owner steps must have one exact identity")
    session, symbol, instrument_type, direction = identities.pop()
    if not isinstance(session, SessionRecord):
        raise RecordError("admitted owner inputs require one canonical session")
    return session, symbol, instrument_type, direction


def _policies(config: RetainedFirstFourOwnerConfig, expected: tuple[type, ...]):
    if (not isinstance(config.policies, tuple)
            or len(config.policies) != len(expected)
            or any(type(value) is not kind for value, kind in zip(config.policies, expected))):
        raise RecordError("owner policies do not match the admitted evaluator")
    return config.policies


def construct_retained_first_four_evaluator_owner(
    plan: RetainedFirstFourEvaluatorPlan,
    config: RetainedFirstFourOwnerConfig,
):
    """Construct, but never advance, the canonical owner for one admitted plan."""
    if not isinstance(config, RetainedFirstFourOwnerConfig):
        raise RecordError("owner construction requires RetainedFirstFourOwnerConfig")
    admitted = bind_retained_first_four_owner_inputs(plan)
    if admitted.status != "READY" or admitted.steps != plan.steps:
        raise RecordError("evaluator owner requires admitted complete inputs")
    session, symbol, instrument_type, direction = _identity(plan)
    common = dict(
        session=session,
        symbol=symbol,
        instrument_type=instrument_type,
        strategy_version=config.strategy_version,
        definition_reference=config.definition_reference,
        steps=admitted.steps,
        record_prefix=config.record_prefix,
    )

    if plan.playbook == "CRVOL_ORB5":
        eligibility, trigger = _policies(config, (EligibilityPolicy, OrbTriggerPolicy))
        return Orb5ReplayStrategy(
            direction=direction, eligibility_policy=eligibility,
            trigger_policy=trigger, **common)
    if plan.playbook == "HOD_COMP_RS":
        eligibility, trigger, suppression = _policies(
            config, (RsTrendPolicy, HodTriggerPolicy, SuppressionPolicy))
        return HodCompRsReplayStrategy(
            direction=direction, eligibility_policy=eligibility,
            trigger_policy=trigger, suppression_policy=suppression, **common)
    if plan.playbook == "OR_FAILURE_REV":
        (policy,) = _policies(config, (ReversalPolicy,))
        return OrFailureRevReplayStrategy(direction=direction, policy=policy, **common)

    policy, measurement_policy = _policies(
        config, (PullbackVwapPolicy, PullbackPolicy))
    if policy.direction != direction:
        raise RecordError("pullback policy direction does not match the admitted inputs")
    if (not isinstance(config.impulse_window, tuple) or len(config.impulse_window) != 2
            or any(not isinstance(value, datetime) for value in config.impulse_window)):
        raise RecordError("pullback owner requires the admitted impulse window")
    started_at, frozen_at = (as_utc(value) for value in config.impulse_window)
    return FirstPullbackVwapReplayStrategy(
        policy=policy, measurement_policy=measurement_policy,
        impulse_started_at=started_at, impulse_frozen_at=frozen_at, **common)


__all__ = [
    "RUN_VERSION", "RetainedFirstFourOwnerConfig",
    "construct_retained_first_four_evaluator_owner",
]
