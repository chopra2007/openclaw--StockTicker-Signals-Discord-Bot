"""M8.5 offline cross-strategy interaction facts over supplied alert candidates.

PLAYBOOKS section 11 names how the first playbooks meet on one symbol: a failed
ORB can hand over to an OR failure, same-direction candidates close in time and
price merge into one primary plus confluence, and an opposite-direction conflict
suppresses the lower-confidence thesis unless it is an explicit reversal
transition. This module reports the facts those rules would read, for every pair
of supplied canonical `AlertCandidate` records on the same symbol: how far apart
they are in time, how far their triggers and stops are apart in supplied ATR, how
their confidence compares, whether their lifetimes overlap, which documented
playbook relationship the pair has and whether a declared ORB-to-failure
transition is backed by the real M8.1 or M8.2 result.

The caller supplies the merge window, the ATR multiple and whether the trigger
and the stop must both be close or either one. The playbook's time and ATR priors
are approximate and unapproved, and the M4.7 portfolio gate is still open,
so this module adopts no number of its own. It never chooses a primary thesis,
breaks an equal-score tie, merges candidates, records confluence, suppresses a
conflict or decides reversal ownership; those stay named in `unavailable`.
Every supplied candidate is retained unchanged in the result.

A reported overlap, conflict or transition describes supplied records at one
instant. It is not a dedup decision, an alert, an approved rule or permission to
act. Nothing here reads a clock, fetches data, opens a database, stores a record
or sends anything.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .or_failure_handoff import (
    FAILURE_FORMING, HandoffAssessment, SOURCE_ORB_STRATEGY_ID, STRATEGY_ID as FAILURE_STRATEGY_ID,
)
from .or_failure_rev import HANDOFF_GATE, ReversalAssessment
from .trade_alerts_models import AlertCandidate, Bar, FeatureSnapshot, Quote, RecordError, SessionRecord
from .utils.time_context import as_utc


INTERACTION_VERSION = "M85_CROSS_STRATEGY_INTERACTION_V1"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

WINDOW_GATE = "MERGE_WINDOW"
TRIGGER_GATE = "TRIGGER_REGION"
STOP_GATE = "STOP_REGION"
REGION_GATE = "PRICE_REGION"
PAIR_GATES = (WINDOW_GATE, TRIGGER_GATE, STOP_GATE, REGION_GATE)

# Whether the caller's own definition needs both the trigger and the stop inside
# its region, or either one. The playbook's "trigger/stop region" leaves it open.
BOTH_REGIONS = "TRIGGER_AND_STOP"
EITHER_REGION = "TRIGGER_OR_STOP"
REGION_RULES = (BOTH_REGIONS, EITHER_REGION)

SAME_THESIS_OVERLAP = "SAME_THESIS_OVERLAP"
SAME_DIRECTION_SEPARATE = "SAME_DIRECTION_SEPARATE"
SAME_DIRECTION_UNKNOWN = "SAME_DIRECTION_UNKNOWN"
OPPOSITE_DIRECTION_CONFLICT = "OPPOSITE_DIRECTION_CONFLICT"
OPPOSITE_DIRECTION_SEQUENTIAL = "OPPOSITE_DIRECTION_SEQUENTIAL"
DECLARED_TRANSITION = "DECLARED_TRANSITION"
RELATIONS = (
    SAME_THESIS_OVERLAP, SAME_DIRECTION_SEPARATE, SAME_DIRECTION_UNKNOWN,
    OPPOSITE_DIRECTION_CONFLICT, OPPOSITE_DIRECTION_SEQUENTIAL, DECLARED_TRANSITION,
)

SAME_STRATEGY = "SAME_STRATEGY"
VOLUME_PROFILE_CONTEXT = "VOLUME_PROFILE_CONTEXT"
# The pairings PLAYBOOKS section 11 names, as labels only. None of them decides
# which candidate is primary.
PLAYBOOK_RELATIONSHIPS = (
    (frozenset(("CRVOL_ORB5", "OR_FAILURE_REV")), "ORB_TO_OR_FAILURE"),
    (frozenset(("CRVOL_ORB5", "GAP_FADE_FAILED_OPEN")), "ORB_TO_GAP_FADE"),
    (frozenset(("OR_FAILURE_REV", "GAP_FADE_FAILED_OPEN")), "OR_FAILURE_WITH_GAP_FADE"),
    (frozenset(("CAT_FIRST_CONSOL", "HOD_COMP_RS")), "CATALYST_CONSOLIDATION_THEN_HOD_COMPRESSION"),
)

ACCEPTED, REFUSED = "ACCEPTED", "REFUSED"
TRANSITION_STATUSES = (ACCEPTED, REFUSED)
# Only the ORB-to-failure handoff has a built owner that can back a declaration.
# The ORB-to-gap-fade transition keeps its M12 owner.
SUPPORTED_TRANSITIONS = ((SOURCE_ORB_STRATEGY_ID, FAILURE_STRATEGY_ID),)
_REVERSAL_STATES = ("ARMED", "ALERT_TRIGGERED")

UNDEFINED = (
    "PRIMARY_THESIS_SELECTION_UNDEFINED",
    "EQUAL_SCORE_TIE_BREAK_UNDEFINED",
    "CONFLUENCE_MERGE_UNDEFINED",
    "OPPOSITE_DIRECTION_SUPPRESSION_UNDEFINED",
    "REVERSAL_OWNERSHIP_AFTER_ORB_UNDEFINED",
    "ORB_TO_GAP_FADE_TRANSITION_OWNER_UNAVAILABLE",
    "VOLUME_PROFILE_CONTEXT_ROLE_UNDEFINED",
)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _threshold(value: object, name: str, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    try:
        number = Fraction(str(value))
    except (ValueError, ArithmeticError) as exc:  # non-finite text is not a threshold
        raise RecordError(f"{name} must be finite") from exc
    if number < 0 or (positive and number <= 0):
        raise RecordError(f"{name} must be a supported threshold")
    return number


def _count(value: object, name: str, *, minimum: int = 0) -> int:
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


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _price(value: float) -> Fraction:
    return Fraction(str(value))


def _seconds(first: datetime, second: datetime) -> Fraction:
    delta = abs(second - first)
    return Fraction((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds, 1000000)


def playbook_relationship(first: str, second: str) -> str | None:
    """The documented section 11 label for one strategy pair, or none."""
    if first == second:
        return SAME_STRATEGY
    if "VP_ACCEPT_LVN" in (first, second):
        return VOLUME_PROFILE_CONTEXT
    pair = frozenset((first, second))
    return next((name for members, name in PLAYBOOK_RELATIONSHIPS if members == pair), None)


@dataclass(frozen=True)
class InteractionPolicy:
    """The caller's own merge window, ATR multiple and region rule.

    Nothing is defaulted. Supplying the values neither adopts the playbook's
    approximate priors nor claims the referenced definition was approved.
    """

    version: str
    definition_reference: str
    merge_window_seconds: int
    region_atr_multiple: float
    region_rule: str

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        _count(self.merge_window_seconds, "merge_window_seconds")
        _threshold(self.region_atr_multiple, "region_atr_multiple", positive=True)
        if self.region_rule not in REGION_RULES:
            raise RecordError("region rule is not supported")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version, "definition_reference": self.definition_reference,
            "merge_window_seconds": self.merge_window_seconds,
            "region_atr_multiple": self.region_atr_multiple, "region_rule": self.region_rule,
        }


@dataclass(frozen=True)
class SymbolAtr:
    """One supplied ATR for one symbol, or the reason it is missing."""

    record_id: str
    symbol: str
    definition_reference: str
    available_at: datetime
    value: float | None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.record_id, "ATR record ID")
        _label(self.symbol, "ATR symbol")
        _label(self.definition_reference, "ATR definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        if (self.value is None) == (self.missing_reason is None):
            raise RecordError("an ATR carries either a value or its missing reason")
        if self.value is not None:
            _threshold(self.value, "ATR value", positive=True)
        else:
            _label(self.missing_reason, "ATR missing reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "symbol": self.symbol,
            "definition_reference": self.definition_reference,
            "available_at": _text_time(self.available_at), "value": self.value,
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class DeclaredTransition:
    """The caller's claim that one candidate hands its structure to another.

    The evidence is the real M8.1 handoff or M8.2 reversal result the caller
    already holds. A declaration is checked, never assumed.
    """

    record_id: str
    from_candidate_id: str
    to_candidate_id: str
    evidence: HandoffAssessment | ReversalAssessment
    session: SessionRecord | None = None
    supporting_records: tuple[Bar | Quote | FeatureSnapshot, ...] = ()

    def __post_init__(self) -> None:
        _label(self.record_id, "transition record ID")
        _label(self.from_candidate_id, "from candidate ID")
        _label(self.to_candidate_id, "to candidate ID")
        if self.from_candidate_id == self.to_candidate_id:
            raise RecordError("a transition links two different candidates")
        if not isinstance(self.evidence, (HandoffAssessment, ReversalAssessment)):
            raise RecordError("transition evidence must be the M8.1 or M8.2 result")
        if self.session is not None and not isinstance(self.session, SessionRecord):
            raise RecordError("transition session must be a saved SessionRecord")
        if (not isinstance(self.supporting_records, tuple)
                or any(not isinstance(item, (Bar, Quote, FeatureSnapshot))
                       for item in self.supporting_records)):
            raise RecordError("transition supporting records must be canonical input records")
        ids = [item.record_id for item in self.supporting_records]
        if len(ids) != len(set(ids)):
            raise RecordError("transition supporting record IDs must be unique")


@dataclass(frozen=True)
class InteractionRequest:
    """Every supplied candidate of one saved session at one evaluation instant."""

    evaluated_at: datetime
    policy: InteractionPolicy
    candidates: tuple[AlertCandidate, ...]
    atrs: tuple[SymbolAtr, ...] = ()
    transitions: tuple[DeclaredTransition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if not isinstance(self.policy, InteractionPolicy):
            raise RecordError("policy must be InteractionPolicy")
        for name, expected in (("candidates", AlertCandidate), ("atrs", SymbolAtr),
                               ("transitions", DeclaredTransition)):
            rows = getattr(self, name)
            if not isinstance(rows, tuple) or any(not isinstance(row, expected) for row in rows):
                raise RecordError(f"{name} must be a tuple of supplied records")
        identifiers = [row.record_id for row in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise RecordError("candidate record IDs must be unique")
        if len({row.session_record_id for row in self.candidates}) > 1:
            raise RecordError("candidates must belong to one saved session")
        if any(row.created_at > self.evaluated_at for row in self.candidates):
            raise RecordError("a candidate is not yet available")
        symbols = [row.symbol for row in self.atrs]
        if len(symbols) != len(set(symbols)):
            raise RecordError("one ATR may be supplied per symbol")
        if any(row.available_at > self.evaluated_at for row in self.atrs):
            raise RecordError("a supplied ATR is not yet available")
        others = [row.record_id for row in (*self.atrs, *self.transitions)]
        if len(others) != len(set(others)) or set(others) & set(identifiers):
            raise RecordError("supplied record IDs must be unique")
        known = set(identifiers)
        links = set()
        for row in self.transitions:
            if row.from_candidate_id not in known or row.to_candidate_id not in known:
                raise RecordError("a transition must link supplied candidates")
            pair = frozenset((row.from_candidate_id, row.to_candidate_id))
            if pair in links:
                raise RecordError("one transition may be declared per candidate pair")
            links.add(pair)
            if row.evidence.evaluated_at > self.evaluated_at:
                raise RecordError("transition evidence is not yet available")


@dataclass(frozen=True)
class PairGate:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.name not in PAIR_GATES:
            raise RecordError("gate name is not supported")
        if self.status not in GATE_STATUSES:
            raise RecordError("gate status is not supported")
        if self.status != PASS and self.reason is None:
            raise RecordError("a gate that did not pass requires a reason")
        if self.reason is not None:
            _label(self.reason, "gate reason")

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status, "observed": self.observed,
                "threshold": self.threshold, "reason": self.reason}


@dataclass(frozen=True)
class TransitionFinding:
    record_id: str
    from_candidate_id: str
    to_candidate_id: str
    status: str
    reason: str | None = None
    evidence_state: str = ""
    evidence_substate: str | None = None
    evidence: HandoffAssessment | ReversalAssessment | None = None
    session: SessionRecord | None = None
    supporting_records: tuple[Bar | Quote | FeatureSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in TRANSITION_STATUSES:
            raise RecordError("transition status is not supported")
        if (self.status == REFUSED) != (self.reason is not None):
            raise RecordError("only a refused transition carries a reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "from_candidate_id": self.from_candidate_id,
            "to_candidate_id": self.to_candidate_id, "status": self.status,
            "reason": self.reason, "evidence_state": self.evidence_state,
            "evidence_substate": self.evidence_substate,
            "evidence": None if self.evidence is None else self.evidence.as_dict(),
            "session": None if self.session is None else self.session.as_dict(),
            "supporting_records": [item.as_dict() for item in sorted(
                self.supporting_records, key=lambda item: item.record_id)],
        }


@dataclass(frozen=True)
class PairFinding:
    """The reported facts for one candidate pair, ordered by record ID."""

    symbol: str
    first_candidate_id: str
    second_candidate_id: str
    first_strategy_id: str
    second_strategy_id: str
    first_direction: str
    second_direction: str
    relation: str
    playbook_relationship: str | None
    seconds_apart: float
    lifetimes_overlap: bool
    gates: tuple[PairGate, ...]
    trigger_distance_atr: float | None
    stop_distance_atr: float | None
    higher_confidence_candidate_id: str | None
    equal_confidence: bool
    transition_record_id: str | None

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise RecordError("pair relation is not supported")
        if self.first_candidate_id >= self.second_candidate_id:
            raise RecordError("a pair is ordered by candidate record ID")
        if (self.relation == DECLARED_TRANSITION) != (self.transition_record_id is not None):
            raise RecordError("only a declared transition names its record")

    def gate(self, name: str) -> PairGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol, "first_candidate_id": self.first_candidate_id,
            "second_candidate_id": self.second_candidate_id,
            "first_strategy_id": self.first_strategy_id,
            "second_strategy_id": self.second_strategy_id,
            "first_direction": self.first_direction, "second_direction": self.second_direction,
            "relation": self.relation, "playbook_relationship": self.playbook_relationship,
            "seconds_apart": self.seconds_apart, "lifetimes_overlap": self.lifetimes_overlap,
            "gates": [row.as_dict() for row in self.gates],
            "trigger_distance_atr": self.trigger_distance_atr,
            "stop_distance_atr": self.stop_distance_atr,
            "higher_confidence_candidate_id": self.higher_confidence_candidate_id,
            "equal_confidence": self.equal_confidence,
            "transition_record_id": self.transition_record_id,
        }


@dataclass(frozen=True)
class InteractionReport:
    """Immutable result of one evaluation; every supplied candidate is retained."""

    evaluated_at: datetime
    candidates: tuple[AlertCandidate, ...]
    atrs: tuple[SymbolAtr, ...]
    transitions: tuple[TransitionFinding, ...]
    pairs: tuple[PairFinding, ...]
    policy: InteractionPolicy
    unavailable: tuple[str, ...] = UNDEFINED

    def pair(self, first: str, second: str) -> PairFinding:
        low, high = sorted((first, second))
        return next(row for row in self.pairs
                    if (row.first_candidate_id, row.second_candidate_id) == (low, high))

    def as_dict(self) -> dict[str, object]:
        return {
            "interaction_version": INTERACTION_VERSION,
            "evaluated_at": _text_time(self.evaluated_at),
            "candidates": [row.as_dict() for row in self.candidates],
            "atrs": [row.as_dict() for row in self.atrs],
            "transitions": [row.as_dict() for row in self.transitions],
            "pairs": [row.as_dict() for row in self.pairs],
            "policy": self.policy.as_dict(), "unavailable": list(self.unavailable),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _refusal(row: DeclaredTransition, source: AlertCandidate, target: AlertCandidate) -> str | None:
    evidence = row.evidence
    if (source.strategy_id, target.strategy_id) not in SUPPORTED_TRANSITIONS:
        return "TRANSITION_PAIR_NOT_SUPPORTED"
    if (source.metadata.instrument_id != target.metadata.instrument_id
            or source.metadata.instrument_type != target.metadata.instrument_type):
        return "TRANSITION_SYMBOL_MISMATCH"
    if isinstance(evidence, HandoffAssessment):
        reached = (evidence.state.state == "SETUP_FORMING"
                   and evidence.state.substate == FAILURE_FORMING)
        break_direction = evidence.candidate.direction
    else:
        handoff = next((gate for gate in evidence.gates if gate.name == HANDOFF_GATE), None)
        reached = (handoff is not None and handoff.status == PASS
                   and evidence.state.state in _REVERSAL_STATES)
        break_direction = evidence.break_direction
    if not reached:
        return "TRANSITION_EVIDENCE_NOT_HANDED_OVER"
    frozen = evidence.candidate
    original_ids = {frozen.anchor_bar_id, *frozen.input_record_ids}
    evaluation_ids = {value for gate in evidence.gates for value in gate.input_record_ids}
    if isinstance(evidence, ReversalAssessment):
        evaluation_ids.update(evidence.structural_input_ids)
    required_ids = original_ids | evaluation_ids
    inputs = {item.record_id: item for item in row.supporting_records}
    if row.session is None or not frozen.input_record_ids or not required_ids <= inputs.keys():
        return "TRANSITION_EVIDENCE_IDENTITY_UNAVAILABLE"
    if any(item.metadata.instrument_id != source.metadata.instrument_id
           or item.metadata.instrument_type != source.metadata.instrument_type
           for item in inputs.values()):
        return "TRANSITION_EVIDENCE_SYMBOL_MISMATCH"
    if (source.session_record_id != row.session.record_id
            or target.session_record_id != row.session.record_id
            or source.metadata.session != row.session.session
            or target.metadata.session != row.session.session
            or any(item.metadata.session != row.session.session for item in inputs.values())):
        return "TRANSITION_EVIDENCE_SESSION_MISMATCH"
    if (source.structure_id != target.structure_id
            or not original_ids <= set(source.input_record_ids)
            or not original_ids <= set(target.input_record_ids)
            or source.record_id not in target.input_record_ids
            or source.trigger_price != frozen.boundary):
        return "TRANSITION_EVIDENCE_SETUP_MISMATCH"
    if (row.session.started_at > frozen.crossed_at
            or frozen.crossed_at > source.created_at
            or any(inputs[record_id].metadata.available_time > frozen.crossed_at
                   for record_id in original_ids)
            or any(item.metadata.available_time > evidence.evaluated_at
                   for item in inputs.values())):
        return "TRANSITION_ORDER_MISMATCH"
    if break_direction != source.direction:
        return "TRANSITION_BREAK_DIRECTION_MISMATCH"
    if evidence.direction != target.direction or source.direction == target.direction:
        return "TRANSITION_REVERSAL_DIRECTION_MISMATCH"
    if not source.created_at <= evidence.evaluated_at <= target.created_at:
        return "TRANSITION_ORDER_MISMATCH"
    return None


def _transitions(request: InteractionRequest) -> tuple[TransitionFinding, ...]:
    rows = {row.record_id: row for row in request.candidates}
    findings = []
    for row in sorted(request.transitions, key=lambda item: item.record_id):
        reason = _refusal(row, rows[row.from_candidate_id], rows[row.to_candidate_id])
        findings.append(TransitionFinding(
            row.record_id, row.from_candidate_id, row.to_candidate_id,
            REFUSED if reason else ACCEPTED, reason,
            row.evidence.state.state, row.evidence.state.substate,
            row.evidence, row.session, row.supporting_records))
    return tuple(findings)


def _distance(name: str, first: float | None, second: float | None, atr: SymbolAtr | None,
              limit: Fraction, missing: str) -> tuple[PairGate, Fraction | None]:
    threshold = float(limit)
    if first is None or second is None:
        return PairGate(name, UNKNOWN, None, threshold, missing), None
    if atr is None:
        return PairGate(name, UNKNOWN, None, threshold, "ATR_NOT_SUPPLIED"), None
    if atr.value is None:
        return PairGate(name, UNKNOWN, None, threshold, atr.missing_reason), None
    distance = abs(_price(first) - _price(second)) / _price(atr.value)
    status = PASS if distance <= limit else FAIL
    return PairGate(name, status, float(distance), threshold,
                    None if status == PASS else "BEYOND_SUPPLIED_REGION"), distance


def _region(rule: str, trigger: PairGate, stop: PairGate) -> PairGate:
    statuses = (trigger.status, stop.status)
    if rule == BOTH_REGIONS:
        if FAIL in statuses:
            return PairGate(REGION_GATE, FAIL, reason="A_SUPPLIED_REGION_FAILED")
        if UNKNOWN in statuses:
            return PairGate(REGION_GATE, UNKNOWN, reason="A_SUPPLIED_REGION_UNKNOWN")
        return PairGate(REGION_GATE, PASS)
    if PASS in statuses:
        return PairGate(REGION_GATE, PASS)
    if UNKNOWN in statuses:
        return PairGate(REGION_GATE, UNKNOWN, reason="A_SUPPLIED_REGION_UNKNOWN")
    return PairGate(REGION_GATE, FAIL, reason="BOTH_SUPPLIED_REGIONS_FAILED")


def _pair(request: InteractionRequest, first: AlertCandidate, second: AlertCandidate,
          atr: SymbolAtr | None, accepted: dict[frozenset, str]) -> PairFinding:
    policy = request.policy
    seconds = _seconds(first.created_at, second.created_at)
    window = PairGate(
        WINDOW_GATE, PASS if seconds <= policy.merge_window_seconds else FAIL, float(seconds),
        float(policy.merge_window_seconds),
        None if seconds <= policy.merge_window_seconds else "BEYOND_SUPPLIED_WINDOW")
    limit = _threshold(policy.region_atr_multiple, "region_atr_multiple", positive=True)
    trigger, trigger_distance = _distance(
        TRIGGER_GATE, first.trigger_price, second.trigger_price, atr, limit,
        "TRIGGER_PRICE_UNAVAILABLE")
    stop, stop_distance = _distance(
        STOP_GATE, None if first.risk is None else first.risk.hard_stop,
        None if second.risk is None else second.risk.hard_stop, atr, limit, "STOP_UNAVAILABLE")
    region = _region(policy.region_rule, trigger, stop)
    overlap = first.created_at < second.expires_at and second.created_at < first.expires_at
    link = accepted.get(frozenset((first.record_id, second.record_id)))
    if first.direction == second.direction:
        if not overlap or window.status == FAIL or region.status == FAIL:
            relation = SAME_DIRECTION_SEPARATE
        elif region.status == PASS:
            relation = SAME_THESIS_OVERLAP
        else:
            relation = SAME_DIRECTION_UNKNOWN
        link = None
    elif link is not None:
        relation = DECLARED_TRANSITION
    else:
        relation = OPPOSITE_DIRECTION_CONFLICT if overlap else OPPOSITE_DIRECTION_SEQUENTIAL
    scores = (_price(first.confidence.final_score), _price(second.confidence.final_score))
    higher = None if scores[0] == scores[1] else (
        first.record_id if scores[0] > scores[1] else second.record_id)
    return PairFinding(
        first.metadata.instrument_id, first.record_id, second.record_id, first.strategy_id,
        second.strategy_id, first.direction, second.direction, relation,
        playbook_relationship(first.strategy_id, second.strategy_id), float(seconds), overlap,
        (window, trigger, stop, region),
        None if trigger_distance is None else float(trigger_distance),
        None if stop_distance is None else float(stop_distance),
        higher, higher is None, link)


def report_cross_strategy_interaction(request: InteractionRequest) -> InteractionReport:
    """Report every same-symbol pair; the supplied input order never matters."""
    if not isinstance(request, InteractionRequest):
        raise RecordError("request must be InteractionRequest")
    candidates = tuple(sorted(request.candidates, key=lambda row: row.record_id))
    atrs = {row.symbol: row for row in request.atrs}
    transitions = _transitions(request)
    accepted = {frozenset((row.from_candidate_id, row.to_candidate_id)): row.record_id
                for row in transitions if row.status == ACCEPTED}
    pairs = []
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            symbol = first.metadata.instrument_id
            if second.metadata.instrument_id == symbol:
                pairs.append(_pair(request, first, second, atrs.get(symbol), accepted))
    pairs.sort(key=lambda row: (row.symbol, row.first_candidate_id, row.second_candidate_id))
    return InteractionReport(
        request.evaluated_at, candidates,
        tuple(sorted(request.atrs, key=lambda row: row.symbol)), transitions, tuple(pairs),
        request.policy)
