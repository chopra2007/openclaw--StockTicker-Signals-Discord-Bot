"""M7.4 offline `HOD_COMP_RS` risk, confidence and suppression at one trigger.

The caller supplies the M7.3 `TriggerAssessment`, its own structural stop and
targets, the M4.4 confidence result and its own suppression policy and prior
action history. This module composes them at one evaluation instant: it re-checks
that every supplied part describes this frozen structure at this exact instant,
then reports the stop, the targets, the confidence and the suppression decision
those inputs already carry.

Nothing here adopts a number. The stop pad below the compression, the reward
minimums, the confidence floor and weights, the cooldown, the actionable-per-
structure count and the structures a session allows all stay unresolved under
PLAYBOOKS section 13 and M0.3, and `M03B_HOD_COMP_RS_V1` is not an approved
definition, so a policy must name its own definition reference. Supplying a
number neither approves a proposed rule nor proves a provider covers these
inputs.

READY means the supplied composition held together at one instant. It is not an
alert, an approved rule, proof of source coverage, a quality cutoff or permission
to act. A missing, stale or mismatched input keeps the outcome UNAVAILABLE; a
definite refusal keeps it REJECTED; a definite suppression keeps it SUPPRESSED.
Unknown never becomes a pass, and a passing confidence never repairs a refused
stop or the reverse.

Nothing here reads a clock, fetches data, opens a database, stores a record,
assembles an alert candidate or delivers anything. The `SuppressionEvent` record
keeps its M4.5 owner: this module reports the reasons that caller would record.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .confidence import ConfidenceResult
from .hod_comp_rs_trigger import (
    FAIL, FrozenStructure, MODES, PASS, STRATEGY_ID, TriggerAssessment, UNKNOWN,
)
from .strategy_interface import StrategyState
from .trade_alerts_models import ConfidenceBreakdown, RecordError, RiskLevel, TargetLevel
from .utils.time_context import as_utc


OUTCOME_VERSION = "M74_HOD_COMP_RS_RISK_CONFIDENCE_V1"
ACTIONABLE = "ALERT_TRIGGERED"
HEADS_UP_ACTION, ACTIONABLE_ACTION = "HEADS_UP", "ACTIONABLE"
ACTION_KINDS = (HEADS_UP_ACTION, ACTIONABLE_ACTION)

TRIGGER_GATE = "TRIGGER_ACTIONABLE"
RISK_GATE = "RISK_TARGETS"
CONFIDENCE_GATE = "CONFIDENCE"
SUPPRESSION_GATE = "SUPPRESSION"
OUTCOME_GATES = (TRIGGER_GATE, RISK_GATE, CONFIDENCE_GATE, SUPPRESSION_GATE)
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

READY, SUPPRESSED, REJECTED, UNAVAILABLE = "READY", "SUPPRESSED", "REJECTED", "UNAVAILABLE"
# Named suppression reasons, reported in this fixed order.
SUPPRESSION_REASONS = (
    "DUPLICATE_STRUCTURE_ACTIONABLE", "SESSION_STRUCTURE_QUOTA_REACHED",
    "ACTION_COOLDOWN_ACTIVE", "OPPOSITE_DIRECTION_CONFLICT",
)
# No approved definition supplies these, so the outcome keeps naming them instead
# of filling them in: the stop pad below the compression, the reward minimums,
# the confidence cutoff, and D-090 section 6's two undefined structures.
UNDEFINED = (
    "CONFIDENCE_FLOOR_UNDEFINED", "RUNNER_UNDEFINED", "SOFT_INVALIDATION_UNDEFINED",
    "STOP_PAD_UNDEFINED", "TARGET_REWARD_MINIMUM_UNDEFINED",
)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _threshold(value: object, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    try:
        number = Fraction(str(value))
    except (ValueError, ArithmeticError) as exc:  # non-finite text is not a threshold
        raise RecordError(f"{name} must be finite") from exc
    if number < 0:
        raise RecordError(f"{name} must be a supported threshold")
    return number


def _count(value: object, name: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise RecordError(f"{name} must be an integer of at least {minimum}")
    return value


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _identifiers(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(row, str) or not row.strip() for row in value
    ):
        raise RecordError(f"{name} must be non-empty strings")
    return value


def _seconds(first: datetime, second: datetime) -> Fraction:
    return Fraction(str((first - second).total_seconds()))


def _sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _price(value: float) -> Fraction:
    return Fraction(str(value))


@dataclass(frozen=True)
class OutcomeGate:
    name: str
    status: str
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in OUTCOME_GATES:
            raise RecordError("outcome gate name is not supported")
        if self.status not in GATE_STATUSES:
            raise RecordError("outcome gate status is not supported")
        if self.status != PASS and self.reason is None:
            raise RecordError("a gate that did not pass requires a reason")
        if self.reason is not None:
            _label(self.reason, "gate reason")
        _identifiers(self.input_record_ids, "gate input IDs")

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status, "reason": self.reason,
                "input_record_ids": list(self.input_record_ids)}


@dataclass(frozen=True)
class StructuralReading:
    """One supplied stop and target set measured for this frozen structure.

    The caller measures them under its own definition reference; this module
    reports them and never calculates a stop, a target or an R multiple. A
    missing measurement stays an explicit unknown with its own reason and carries
    no targets beside it.
    """

    definition_reference: str
    direction: str
    mode: str
    structure_number: int
    crossed_at: datetime
    evaluated_at: datetime
    available_at: datetime
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    missing_reason: str | None = None
    record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _label(self.definition_reference, "structural definition reference")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if self.mode not in MODES:
            raise RecordError("structural arm is not supported")
        _count(self.structure_number, "structure_number", minimum=1)
        for name in ("crossed_at", "evaluated_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if self.evaluated_at < self.crossed_at:
            raise RecordError("a structural reading cannot precede its crossing")
        if self.risk is not None and not isinstance(self.risk, RiskLevel):
            raise RecordError("risk must be RiskLevel or null")
        if not isinstance(self.targets, tuple) or any(
            not isinstance(row, TargetLevel) for row in self.targets
        ):
            raise RecordError("targets must be a tuple of TargetLevel")
        names = [row.name for row in self.targets]
        if len(names) != len(set(names)):
            raise RecordError("target names must be unique")
        if self.risk is None:
            if self.targets:
                raise RecordError("targets cannot stand without their own supplied risk")
            _label(self.missing_reason, "structural missing reason")
        elif self.missing_reason is not None:
            raise RecordError("a supplied risk level cannot also report a missing reason")
        _identifiers(self.record_ids, "structural record IDs")


@dataclass(frozen=True)
class SuppressionPolicy:
    """Explicitly supplied cooldown, per-structure count, quota and conflict rule.

    Every value belongs to the caller's own definition. Supplying one adopts no
    PLAYBOOKS prior and approves no proposed `HOD_COMP_RS` rule.
    """

    version: str
    definition_reference: str
    cooldown_seconds: float
    max_actionable_per_structure: int
    max_structures_per_direction: int
    suppress_opposite_direction: bool
    conflict_window_seconds: float

    def __post_init__(self) -> None:
        _label(self.version, "suppression policy version")
        _label(self.definition_reference, "suppression definition reference")
        _threshold(self.cooldown_seconds, "cooldown_seconds")
        _count(self.max_actionable_per_structure, "max_actionable_per_structure", minimum=1)
        _count(self.max_structures_per_direction, "max_structures_per_direction", minimum=1)
        if type(self.suppress_opposite_direction) is not bool:
            raise RecordError("the opposite-direction rule must be explicitly supplied")
        _threshold(self.conflict_window_seconds, "conflict_window_seconds")


@dataclass(frozen=True)
class PriorAction:
    """One earlier reported heads-up or actionable for this symbol and session."""

    record_id: str
    kind: str
    direction: str
    structure_number: int
    occurred_at: datetime
    outstanding: bool = False

    def __post_init__(self) -> None:
        _label(self.record_id, "prior action record ID")
        if self.kind not in ACTION_KINDS:
            raise RecordError("prior action kind is not supported")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        _count(self.structure_number, "structure_number", minimum=1)
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at, "occurred_at"))
        if type(self.outstanding) is not bool:
            raise RecordError("an outstanding prior action must be explicit")


@dataclass(frozen=True)
class ActionHistory:
    """The caller's own record of what this session already reported.

    `complete` and `as_of` are supplied facts, not assumptions: a history that
    does not reach this evaluation instant, or that the caller cannot vouch for,
    keeps the suppression gate unknown rather than silently allowing a duplicate.
    """

    definition_reference: str
    as_of: datetime
    complete: bool
    actions: tuple[PriorAction, ...] = ()

    def __post_init__(self) -> None:
        _label(self.definition_reference, "history definition reference")
        object.__setattr__(self, "as_of", _instant(self.as_of, "as_of"))
        if type(self.complete) is not bool:
            raise RecordError("history completeness must be explicit")
        if not isinstance(self.actions, tuple) or any(
            not isinstance(row, PriorAction) for row in self.actions
        ):
            raise RecordError("actions must be a tuple of PriorAction")
        identifiers = [row.record_id for row in self.actions]
        if len(identifiers) != len(set(identifiers)):
            raise RecordError("prior action record IDs must be unique")


@dataclass(frozen=True)
class HodCompRsOutcomeRequest:
    """One composition of one reported trigger with its supplied results.

    `strategy_version` and `definition_reference` describe the caller's own
    definition. Supplying them neither adopts a proposed rule nor claims the
    referenced definition was approved.
    """

    assessment: TriggerAssessment
    structural: StructuralReading
    confidence: ConfidenceResult
    suppression: SuppressionPolicy
    strategy_version: str
    definition_reference: str
    history: ActionHistory | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, TriggerAssessment):
            raise RecordError("assessment must be TriggerAssessment")
        if not isinstance(self.structural, StructuralReading):
            raise RecordError("structural must be StructuralReading")
        if not isinstance(self.confidence, ConfidenceResult):
            raise RecordError("confidence must be ConfidenceResult")
        if not isinstance(self.suppression, SuppressionPolicy):
            raise RecordError("suppression must be SuppressionPolicy")
        _label(self.strategy_version, "strategy version")
        _label(self.definition_reference, "definition reference")
        if self.history is not None and not isinstance(self.history, ActionHistory):
            raise RecordError("history must be ActionHistory or null")


@dataclass(frozen=True)
class HodCompRsOutcome:
    """Immutable composed result for one instant; the caller owns everything else.

    Each field is populated only by the gate that passed for it, so a refused or
    unknown input leaves its own facts absent instead of half-stated. Candidate
    assembly, the suppression record itself, options and delivery keep their
    existing owners.
    """

    evaluated_at: datetime
    status: str
    gates: tuple[OutcomeGate, ...]
    reasons: tuple[str, ...]
    structure: FrozenStructure
    crossed_at: datetime
    state: StrategyState
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    confidence: ConfidenceBreakdown | None = None
    suppression_reasons: tuple[str, ...] = ()
    structural_input_ids: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = UNDEFINED
    strategy_version: str = ""
    definition_reference: str = ""
    suppression_version: str = ""

    def gate(self, name: str) -> OutcomeGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        confidence = self.confidence
        return {
            "outcome_version": OUTCOME_VERSION, "strategy_id": STRATEGY_ID,
            "evaluated_at": _text_time(self.evaluated_at),
            "crossed_at": _text_time(self.crossed_at), "status": self.status,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "structure": self.structure.as_dict(), "mode": self.structure.mode,
            "state": self.state.state, "substate": self.state.substate,
            "risk": None if self.risk is None else {
                "entry_reference": self.risk.entry_reference,
                "hard_stop": self.risk.hard_stop,
                "risk_per_share": self.risk.risk_per_share,
                "rationale": self.risk.rationale, "source": self.risk.source,
            },
            "targets": [{"name": row.name, "price": row.price,
                         "r_multiple": row.r_multiple, "source": row.source}
                        for row in self.targets],
            "confidence": None if confidence is None else {
                "setup_score": confidence.setup_score,
                "context_score": confidence.context_score,
                "execution_score": confidence.execution_score,
                "final_score": confidence.final_score,
                "factors": [{"name": row.name, "value": row.value, "version": row.version}
                            for row in confidence.factors],
            },
            "suppression_reasons": list(self.suppression_reasons),
            "structural_input_ids": list(self.structural_input_ids),
            "unavailable": list(self.unavailable),
            "strategy_version": self.strategy_version,
            "definition_reference": self.definition_reference,
            "suppression_version": self.suppression_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _trigger(request: HodCompRsOutcomeRequest) -> OutcomeGate:
    """Only a reported actionable trigger composes a READY outcome.

    The other gates still report their own supplied facts, so a caller can see
    what the stop and confidence were while the trigger itself was refused; only
    a READY outcome says this composition held together.
    """
    assessment = request.assessment
    if assessment.state == StrategyState(ACTIONABLE):
        return OutcomeGate(TRIGGER_GATE, PASS,
                           input_record_ids=assessment.structure.input_record_ids)
    unknown = next((row for row in assessment.gates if row.status == UNKNOWN), None)
    if unknown is not None:
        return OutcomeGate(TRIGGER_GATE, UNKNOWN, "TRIGGER_UNKNOWN_" + unknown.name,
                           assessment.structure.input_record_ids)
    failing = next((row for row in assessment.gates if row.status == FAIL), None)
    return OutcomeGate(TRIGGER_GATE, FAIL, "TRIGGER_NOT_ACTIONABLE_" + (
        failing.name if failing is not None else assessment.state.state),
        assessment.structure.input_record_ids)


def _structural(request: HodCompRsOutcomeRequest) -> OutcomeGate:
    """The supplied stop and targets, re-checked against this frozen structure.

    The identity checks come first: a reading framed on another arm, direction,
    structure, crossing or instant is not this trigger's geometry, however
    complete it looks. Only then are the supplied prices compared with the frozen
    boundary and compression that this trigger actually acted on.
    """
    supplied, structure = request.structural, request.assessment.structure
    at = request.assessment.evaluated_at
    if supplied.mode != structure.mode:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_ARM_MISMATCH")
    if supplied.direction != structure.direction:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_DIRECTION_MISMATCH")
    if supplied.structure_number != structure.structure_number:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_STRUCTURE_MISMATCH")
    if supplied.crossed_at != request.assessment.crossed_at:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_CROSSING_MISMATCH")
    if supplied.evaluated_at != at:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_NOT_CURRENT")
    if supplied.available_at > at:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_NOT_YET_AVAILABLE")
    if supplied.risk is None:  # a missing measurement always names its own reason
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_" + supplied.missing_reason)
    if not supplied.targets:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_TARGETS_UNAVAILABLE")
    sign = _sign(structure.direction)
    entry = _price(supplied.risk.entry_reference)
    stop = _price(supplied.risk.hard_stop)
    risk_per_share = _price(supplied.risk.risk_per_share)
    # The entry the stop and targets are measured from must still be the price
    # this trigger acted on: at or beyond its own frozen boundary, with the stop
    # behind it and outside the coil the structure was frozen on. How far outside
    # the coil the stop sits stays the caller's own undefined number.
    if sign * (entry - _price(structure.boundary)) < 0:
        return OutcomeGate(RISK_GATE, FAIL, "ENTRY_INSIDE_FROZEN_BOUNDARY")
    if sign * (entry - stop) <= 0:
        return OutcomeGate(RISK_GATE, FAIL, "STOP_ON_THE_WRONG_SIDE")
    coil = _price(structure.compression_low if structure.direction == "LONG"
                  else structure.compression_high)
    if sign * (stop - coil) > 0:
        return OutcomeGate(RISK_GATE, FAIL, "STOP_INSIDE_FROZEN_COMPRESSION")
    for row in supplied.targets:
        reward = sign * (_price(row.price) - entry)
        if reward <= 0:
            return OutcomeGate(RISK_GATE, FAIL, "TARGET_NOT_BEYOND_ENTRY")
        # A stated reward larger than the supplied prices show is a refusal, not
        # a rounding difference; no reward minimum is applied either way.
        if _price(row.r_multiple) > reward / risk_per_share:
            return OutcomeGate(RISK_GATE, FAIL, "TARGET_R_MULTIPLE_OVERSTATED")
    return OutcomeGate(RISK_GATE, PASS, input_record_ids=supplied.record_ids)


def _confidence(request: HodCompRsOutcomeRequest) -> OutcomeGate:
    """The supplied M4.4 composition for this underlying, direction and instant."""
    supplied, structure = request.confidence, request.assessment.structure
    at = request.assessment.evaluated_at
    composition = supplied.request
    context, policy = composition.context, composition.policy
    if policy.strategy_id != STRATEGY_ID:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_STRATEGY_MISMATCH")
    if policy.strategy_version != request.strategy_version:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_VERSION_MISMATCH")
    if context.direction != structure.direction:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_DIRECTION_MISMATCH")
    if context.evaluated_at != at:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_NOT_CURRENT")
    if supplied.status != READY or supplied.confidence is None:
        reason = supplied.reasons[0] if supplied.reasons else supplied.status
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_" + reason)
    references = tuple(sorted({row.record_id for row in context.features}))
    return OutcomeGate(CONFIDENCE_GATE, PASS, input_record_ids=references)


def _suppression_reasons(request: HodCompRsOutcomeRequest,
                         history: ActionHistory) -> tuple[str, ...]:
    """Every supplied reason this action would be suppressed, in a fixed order."""
    policy, structure = request.suppression, request.assessment.structure
    at = request.assessment.evaluated_at
    mine = tuple(row for row in history.actions
                 if row.kind == ACTIONABLE_ACTION and row.direction == structure.direction)
    found = []
    same = tuple(row for row in mine if row.structure_number == structure.structure_number)
    if len(same) >= policy.max_actionable_per_structure:
        found.append(SUPPRESSION_REASONS[0])
    started = {row.structure_number for row in mine}
    if (structure.structure_number not in started
            and len(started) >= policy.max_structures_per_direction):
        found.append(SUPPRESSION_REASONS[1])
    latest = max((row.occurred_at for row in mine), default=None)
    if latest is not None and _seconds(at, latest) < _price(policy.cooldown_seconds):
        found.append(SUPPRESSION_REASONS[2])
    if policy.suppress_opposite_direction and any(
        row.kind == ACTIONABLE_ACTION and row.direction != structure.direction
        and row.outstanding
        and _seconds(at, row.occurred_at) <= _price(policy.conflict_window_seconds)
        for row in history.actions
    ):
        found.append(SUPPRESSION_REASONS[3])
    return tuple(found)


def _suppression(request: HodCompRsOutcomeRequest) -> tuple[OutcomeGate, tuple[str, ...]]:
    """Report the caller's own suppression decision over its own history.

    An unknown history never becomes an empty one: a caller that cannot say what
    this session already reported leaves the gate unknown, so a duplicate action
    can never pass on silence alone.
    """
    history = request.history
    at = request.assessment.evaluated_at
    if history is None:
        return OutcomeGate(SUPPRESSION_GATE, UNKNOWN, "SUPPRESSION_HISTORY_UNKNOWN"), ()
    if not history.complete:
        return OutcomeGate(SUPPRESSION_GATE, UNKNOWN, "SUPPRESSION_HISTORY_INCOMPLETE"), ()
    if history.as_of < at:
        return OutcomeGate(SUPPRESSION_GATE, UNKNOWN, "SUPPRESSION_HISTORY_STALE"), ()
    if any(row.occurred_at > at for row in history.actions):
        return OutcomeGate(SUPPRESSION_GATE, UNKNOWN, "SUPPRESSION_HISTORY_AHEAD"), ()
    references = tuple(sorted(row.record_id for row in history.actions))
    reasons = _suppression_reasons(request, history)
    if reasons:
        return OutcomeGate(SUPPRESSION_GATE, FAIL, reasons[0], references), reasons
    return OutcomeGate(SUPPRESSION_GATE, PASS, input_record_ids=references), ()


def compose_hod_comp_rs_outcome(request: HodCompRsOutcomeRequest) -> HodCompRsOutcome:
    """Report the supplied stop, targets, confidence and suppression decision.

    Any unknown input keeps the whole outcome UNAVAILABLE, because an incomplete
    picture of risk is not a refusal; a definite refusal with nothing unknown is
    REJECTED, and an otherwise complete action the caller's own history suppresses
    is SUPPRESSED. No quality cutoff is applied: the confidence floor stays with
    the PROPOSED definition and is reported as undefined instead.
    """
    if not isinstance(request, HodCompRsOutcomeRequest):
        raise RecordError("HodCompRsOutcomeRequest is required")
    assessment = request.assessment
    suppression, suppression_reasons = _suppression(request)
    gates = (_trigger(request), _structural(request), _confidence(request), suppression)
    decisive = tuple(row for row in gates if row.name != SUPPRESSION_GATE)
    if any(row.status == UNKNOWN for row in gates):
        status = UNAVAILABLE
    elif any(row.status == FAIL for row in decisive):
        status = REJECTED
    elif suppression.status == FAIL:
        status = SUPPRESSED
    else:
        status = READY
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}"
                    for row in gates if row.status != PASS)
    values: dict[str, object] = {}
    if next(row for row in gates if row.name == RISK_GATE).status == PASS:
        values.update(risk=request.structural.risk, targets=request.structural.targets,
                      structural_input_ids=request.structural.record_ids)
    if next(row for row in gates if row.name == CONFIDENCE_GATE).status == PASS:
        values.update(confidence=request.confidence.confidence)
    return HodCompRsOutcome(
        assessment.evaluated_at, status, gates, reasons, assessment.structure,
        assessment.crossed_at, assessment.state, suppression_reasons=suppression_reasons,
        strategy_version=request.strategy_version,
        definition_reference=request.definition_reference,
        suppression_version=request.suppression.version, **values)


__all__ = [
    "ACTIONABLE", "ACTIONABLE_ACTION", "ACTION_KINDS", "ActionHistory", "CONFIDENCE_GATE",
    "HEADS_UP_ACTION", "HodCompRsOutcome", "HodCompRsOutcomeRequest", "OUTCOME_GATES",
    "OUTCOME_VERSION", "OutcomeGate", "PriorAction", "READY", "REJECTED", "RISK_GATE",
    "STRATEGY_ID", "SUPPRESSED", "SUPPRESSION_GATE", "SUPPRESSION_REASONS",
    "StructuralReading", "SuppressionPolicy", "TRIGGER_GATE", "UNAVAILABLE", "UNDEFINED",
    "compose_hod_comp_rs_outcome",
]
