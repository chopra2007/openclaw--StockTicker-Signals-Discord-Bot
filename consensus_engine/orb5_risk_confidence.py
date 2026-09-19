"""M6.3 offline `CRVOL_ORB5` risk, targets and confidence at one frozen trigger.

The caller supplies the M6.2 assessment, the M4.3 geometry result and the M4.4
confidence result. This module composes them: it re-checks that both supplied
results describe this frozen attempt at this exact instant, then reports the
stop, targets and confidence they already carry. It calculates no stop, no
target, no score and no weight of its own, and it adopts no number: the
rule-bearing confidence floor, factor roster and target catalog still belong to
`M03B_ORB5_V1`, `M4.3` and `M4.4`, which remain PROPOSED or gated. Nothing here
reads a clock, fetches data, opens a database, stores a record, assembles an
alert candidate or delivers anything.

READY means the supplied composition held together at one evaluation instant. It
is not an alert, an approved rule, proof of source coverage, a quality cutoff or
permission to act. A missing, stale or mismatched input keeps the outcome
UNAVAILABLE; a definite refusal keeps it REJECTED. Unknown never becomes a pass,
and a passing confidence never repairs a refused geometry or the reverse.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .confidence import ConfidenceResult
from .orb5_trigger import (
    FAIL, FrozenCandidate, MODE_VARIANTS, PASS, STRATEGY_ID, TriggerAssessment, UNKNOWN,
)
from .strategy_interface import StrategyState
from .structural_risk import RiskTargetResult
from .trade_alerts_models import ConfidenceBreakdown, RecordError, RiskLevel, TargetLevel
from .utils.time_context import as_utc


OUTCOME_VERSION = "M63_ORB5_RISK_CONFIDENCE_V1"
ACTIONABLE = "ALERT_TRIGGERED"
TRIGGER_GATE = "TRIGGER_ACTIONABLE"
RISK_GATE = "RISK_TARGETS"
CONFIDENCE_GATE = "CONFIDENCE"
OUTCOME_GATES = (TRIGGER_GATE, RISK_GATE, CONFIDENCE_GATE)
GATE_STATUSES = (PASS, FAIL, UNKNOWN)
READY, REJECTED, UNAVAILABLE = "READY", "REJECTED", "UNAVAILABLE"
# Neither the quality cutoff nor the two D-090 §6 undefined structures is
# supplied by any approved definition, so the outcome keeps naming them.
UNDEFINED = ("CONFIDENCE_FLOOR_UNDEFINED",)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


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
        if not isinstance(self.input_record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.input_record_ids
        ):
            raise RecordError("gate input IDs must be non-empty strings")

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status, "reason": self.reason,
                "input_record_ids": list(self.input_record_ids)}


@dataclass(frozen=True)
class Orb5OutcomeRequest:
    """One composition of one frozen trigger with its supplied results.

    `strategy_version` and `definition_reference` describe the caller's own
    definition. Supplying them neither adopts a proposed rule nor claims the
    referenced definition was approved.
    """

    assessment: TriggerAssessment
    geometry: RiskTargetResult
    confidence: ConfidenceResult
    strategy_version: str
    definition_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, TriggerAssessment):
            raise RecordError("assessment must be TriggerAssessment")
        if not isinstance(self.geometry, RiskTargetResult):
            raise RecordError("geometry must be RiskTargetResult")
        if not isinstance(self.confidence, ConfidenceResult):
            raise RecordError("confidence must be ConfidenceResult")
        _label(self.strategy_version, "strategy version")
        _label(self.definition_reference, "definition reference")


@dataclass(frozen=True)
class Orb5Outcome:
    """Immutable composed result for one instant; the caller owns everything else.

    Each field is populated only by the gate that passed for it, so a refused or
    unknown input leaves its own facts absent instead of half-stated. Candidate
    assembly, suppression, options and delivery keep their existing owners.
    """

    evaluated_at: datetime
    status: str
    gates: tuple[OutcomeGate, ...]
    reasons: tuple[str, ...]
    candidate: FrozenCandidate
    state: StrategyState
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    target_labels: tuple[tuple[str, ...], ...] = ()
    target_input_ids: tuple[tuple[str, ...], ...] = ()
    extension_r: float | None = None
    confidence: ConfidenceBreakdown | None = None
    unavailable: tuple[str, ...] = UNDEFINED
    strategy_version: str = ""
    definition_reference: str = ""

    def gate(self, name: str) -> OutcomeGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        confidence = self.confidence
        return {
            "outcome_version": OUTCOME_VERSION, "strategy_id": STRATEGY_ID,
            "evaluated_at": _text_time(self.evaluated_at), "status": self.status,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "candidate": self.candidate.as_dict(), "state": self.state.state,
            "substate": self.state.substate,
            "risk": None if self.risk is None else {
                "entry_reference": self.risk.entry_reference,
                "hard_stop": self.risk.hard_stop,
                "risk_per_share": self.risk.risk_per_share,
                "rationale": self.risk.rationale, "source": self.risk.source,
            },
            "targets": [{"name": row.name, "price": row.price,
                         "r_multiple": row.r_multiple, "source": row.source}
                        for row in self.targets],
            "target_labels": [list(row) for row in self.target_labels],
            "target_input_ids": [list(row) for row in self.target_input_ids],
            "extension_r": self.extension_r,
            "confidence": None if confidence is None else {
                "setup_score": confidence.setup_score,
                "context_score": confidence.context_score,
                "execution_score": confidence.execution_score,
                "final_score": confidence.final_score,
                "factors": [{"name": row.name, "value": row.value, "version": row.version}
                            for row in confidence.factors],
            },
            "unavailable": list(self.unavailable),
            "strategy_version": self.strategy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _trigger(request: Orb5OutcomeRequest) -> OutcomeGate:
    """Only a current actionable trigger may carry risk, targets and confidence."""
    assessment = request.assessment
    if assessment.state == StrategyState(ACTIONABLE):
        return OutcomeGate(TRIGGER_GATE, PASS,
                           input_record_ids=assessment.candidate.input_record_ids)
    unknown = next((row for row in assessment.gates if row.status == UNKNOWN), None)
    if unknown is not None:
        return OutcomeGate(TRIGGER_GATE, UNKNOWN, "TRIGGER_UNKNOWN_" + unknown.name,
                           assessment.candidate.input_record_ids)
    failing = next((row for row in assessment.gates if row.status == FAIL), None)
    return OutcomeGate(TRIGGER_GATE, FAIL, "TRIGGER_NOT_ACTIONABLE_" + (
        failing.name if failing is not None else assessment.state.state),
        assessment.candidate.input_record_ids)


def _boundary_price(geometry: RiskTargetResult) -> Fraction | None:
    supplied = geometry.request.boundary
    value = next((row.value for row in supplied.snapshot.features
                  if row.name == supplied.feature_name), None)
    return None if value is None else Fraction(str(value))


def _geometry(request: Orb5OutcomeRequest) -> OutcomeGate:
    """The supplied M4.3 result, re-checked here against this frozen attempt.

    M6.2 checked its own copy for the trigger decision. This boundary repeats the
    identity checks on the result it was actually handed, so a later, mirrored or
    differently framed selection cannot arrive as this trigger's geometry.
    """
    supplied, candidate = request.geometry, request.assessment.candidate
    at = request.assessment.evaluated_at
    geometry = supplied.request
    if geometry.variant != MODE_VARIANTS[candidate.mode]:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_ARM_MISMATCH")
    if geometry.direction != candidate.direction:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_DIRECTION_MISMATCH")
    if geometry.crossed_at != candidate.crossed_at:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_CROSSING_MISMATCH")
    if geometry.evaluated_at != at:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_NOT_CURRENT")
    boundary = _boundary_price(supplied)
    if boundary is None or boundary != Fraction(str(candidate.boundary)):
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_BOUNDARY_MISMATCH")
    if supplied.status != "READY":
        reason = "GEOMETRY_" + (supplied.reasons[0] if supplied.reasons else supplied.status)
        return OutcomeGate(RISK_GATE, FAIL if supplied.status == "REJECTED" else UNKNOWN, reason)
    if supplied.risk is None or not supplied.targets:
        return OutcomeGate(RISK_GATE, UNKNOWN, "GEOMETRY_LEVELS_UNAVAILABLE")
    sign = _sign(candidate.direction)
    entry = Fraction(str(supplied.risk.entry_reference))
    stop = Fraction(str(supplied.risk.hard_stop))
    # The entry the stop and targets are measured from must still be the price
    # this trigger acted on: at or beyond its own frozen boundary, with the stop
    # behind it. A geometry framed on an inside-boundary entry is not this one.
    if sign * (entry - boundary) < 0:
        return OutcomeGate(RISK_GATE, FAIL, "ENTRY_INSIDE_FROZEN_BOUNDARY")
    if sign * (entry - stop) <= 0:
        return OutcomeGate(RISK_GATE, FAIL, "STOP_ON_THE_WRONG_SIDE")
    if any(sign * (Fraction(str(row.price)) - entry) <= 0 for row in supplied.targets):
        return OutcomeGate(RISK_GATE, FAIL, "TARGET_NOT_BEYOND_ENTRY")
    references = tuple(sorted({value for row in supplied.target_input_ids for value in row}))
    return OutcomeGate(RISK_GATE, PASS, input_record_ids=references)


def _confidence(request: Orb5OutcomeRequest) -> OutcomeGate:
    """The supplied M4.4 composition for this underlying, direction and instant."""
    supplied, candidate = request.confidence, request.assessment.candidate
    at = request.assessment.evaluated_at
    composition = supplied.request
    context, policy = composition.context, composition.policy
    if policy.strategy_id != STRATEGY_ID:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_STRATEGY_MISMATCH")
    if policy.strategy_version != request.strategy_version:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_VERSION_MISMATCH")
    if context.direction != candidate.direction:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_DIRECTION_MISMATCH")
    if context.evaluated_at != at:
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_NOT_CURRENT")
    if supplied.status != "READY" or supplied.confidence is None:
        reason = supplied.reasons[0] if supplied.reasons else supplied.status
        return OutcomeGate(CONFIDENCE_GATE, UNKNOWN, "CONFIDENCE_" + reason)
    references = tuple(sorted({row.record_id for row in context.features}))
    return OutcomeGate(CONFIDENCE_GATE, PASS, input_record_ids=references)


def compose_orb5_outcome(request: Orb5OutcomeRequest) -> Orb5Outcome:
    """Report the supplied stop, targets and confidence for this frozen trigger.

    Any unknown input keeps the whole outcome UNAVAILABLE, because an incomplete
    picture of risk is not a refusal; a definite refusal with nothing unknown is
    REJECTED. No quality cutoff is applied: the confidence floor stays with the
    PROPOSED definition and is reported as undefined instead.
    """
    if not isinstance(request, Orb5OutcomeRequest):
        raise RecordError("Orb5OutcomeRequest is required")
    assessment = request.assessment
    gates = (_trigger(request), _geometry(request), _confidence(request))
    if any(row.status == UNKNOWN for row in gates):
        status = UNAVAILABLE
    elif any(row.status == FAIL for row in gates):
        status = REJECTED
    else:
        status = READY
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}"
                    for row in gates if row.status != PASS)
    values: dict[str, object] = {}
    unavailable = UNDEFINED
    if next(row for row in gates if row.name == RISK_GATE).status == PASS:
        geometry = request.geometry
        values.update(risk=geometry.risk, targets=geometry.targets,
                      target_labels=geometry.target_labels,
                      target_input_ids=geometry.target_input_ids,
                      extension_r=geometry.extension_r)
        unavailable = tuple(sorted(set(unavailable) | set(geometry.unavailable)))
    if next(row for row in gates if row.name == CONFIDENCE_GATE).status == PASS:
        values.update(confidence=request.confidence.confidence)
    return Orb5Outcome(
        assessment.evaluated_at, status, gates, reasons, assessment.candidate,
        assessment.state, unavailable=unavailable,
        strategy_version=request.strategy_version,
        definition_reference=request.definition_reference, **values)


__all__ = [
    "ACTIONABLE", "CONFIDENCE_GATE", "OUTCOME_GATES", "OUTCOME_VERSION", "Orb5Outcome",
    "Orb5OutcomeRequest", "OutcomeGate", "READY", "REJECTED", "RISK_GATE", "STRATEGY_ID",
    "TRIGGER_GATE", "UNAVAILABLE", "UNDEFINED", "compose_orb5_outcome",
]
