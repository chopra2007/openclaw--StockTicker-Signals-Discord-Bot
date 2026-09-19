"""Pure supplied confidence composition; no factor formulas or live policy.

Scores and factor contributions are already calculated upstream. This boundary
checks their declared attribution, combines the three scores with exact supplied
weights, and retains the entire calculation for M5 storage. It does not normalize
factors, choose weights, omit missing factors, or decide trading eligibility.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from fractions import Fraction
import json
import math

from .strategy_interface import StrategyContext
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    ConfidenceBreakdown, ConfidenceComponent, FeatureSnapshot, RecordError,
)
from .utils.time_context import as_utc


COMPOSITION_VERSION = "M44_V1"
COMPONENTS = ("SETUP", "CONTEXT", "EXECUTION")


def _known(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().upper() not in ("UNKNOWN", "UNSPECIFIED"))


@dataclass(frozen=True)
class ConfidenceTerm:
    """One required supplied score or factor, identified without a formula.

    All values use SCORE_POINTS. A SCORE must already be within 0–100; a FACTOR
    is a finite signed contribution in its component's declared upstream formula.
    No additive relationship between factors and scores is assumed here.
    """

    name: str
    component: str
    kind: str
    feature_name: str
    definition_version: str
    data_mode: str

    def __post_init__(self) -> None:
        for field in ("name", "feature_name", "definition_version", "data_mode"):
            if not _known(getattr(self, field)):
                raise RecordError(f"confidence {field} must be explicit")
        if self.component not in COMPONENTS or self.kind not in ("SCORE", "FACTOR"):
            raise RecordError("confidence term component and kind must be explicit")


@dataclass(frozen=True)
class ConfidencePolicy:
    """Explicit weights and complete required-term roster, never approval.

    Callers must supply the governing playbook weights. No defaults, rescaling,
    score cutoff, missing-factor substitute or factor transformation is provided.
    """

    strategy_id: str
    strategy_version: str
    version: str
    setup_weight: float
    context_weight: float
    execution_weight: float
    terms: tuple[ConfidenceTerm, ...]

    def __post_init__(self) -> None:
        if self.strategy_id not in STRATEGY_IDS:
            raise RecordError("confidence strategy ID is not supported")
        for field in ("strategy_version", "version"):
            if not _known(getattr(self, field)):
                raise RecordError(f"confidence {field} must be explicit")
        weights = (self.setup_weight, self.context_weight, self.execution_weight)
        for value in weights:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise RecordError("confidence weights must be finite fractions from 0 to 1")
        if sum(Fraction(str(value)) for value in weights) != 1:
            raise RecordError("confidence weights must sum exactly to one")
        if not isinstance(self.terms, tuple) or any(
            not isinstance(term, ConfidenceTerm) for term in self.terms
        ):
            raise RecordError("confidence terms must be a tuple of ConfidenceTerm")
        names = [term.name for term in self.terms]
        if len(names) != len(set(names)):
            raise RecordError("confidence term names must be unique")
        for component in COMPONENTS:
            if sum(t.component == component and t.kind == "SCORE" for t in self.terms) != 1:
                raise RecordError("each confidence component needs exactly one score")
            if not any(t.component == component and t.kind == "FACTOR" for t in self.terms):
                raise RecordError("each confidence component needs declared factor attribution")


@dataclass(frozen=True)
class ConfidenceRequest:
    """Bind each policy term to a canonical snapshot in the supplied context.

    A missing binding or missing snapshot is observable missing data. Unlisted
    bindings and duplicate names are malformed contracts. Reference-market raw
    inputs may be ancestors of a score; the supplied score itself belongs to the
    evaluated underlying. No current settings or clock are read.
    """

    context: StrategyContext
    policy: ConfidencePolicy
    bindings: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context, StrategyContext) or not isinstance(self.policy, ConfidencePolicy):
            raise RecordError("confidence requires canonical context and explicit policy")
        if not isinstance(self.bindings, tuple) or any(
            not isinstance(pair, tuple) or len(pair) != 2 or any(not _known(v) for v in pair)
            for pair in self.bindings
        ):
            raise RecordError("confidence bindings must be term/snapshot ID pairs")
        names = [name for name, _ in self.bindings]
        if len(names) != len(set(names)):
            raise RecordError("confidence binding names must be unique")
        if set(names) - {term.name for term in self.policy.terms}:
            raise RecordError("confidence binding is not declared in policy")
        configured = json.loads(self.context.session.config_json)["strategies"][self.policy.strategy_id]
        if (configured["strategy_version"] is not None
                and configured["strategy_version"] != self.policy.strategy_version):
            raise RecordError("confidence strategy version differs from the saved session")


@dataclass(frozen=True)
class ConfidenceResult:
    """READY means supplied composition only, never approval or win probability.

    Persist the full result alongside its candidate in M5. The canonical compact
    breakdown alone lacks weights, component membership and source attribution.
    """

    request: ConfidenceRequest
    status: str
    reasons: tuple[str, ...]
    confidence: ConfidenceBreakdown | None

    def as_dict(self) -> dict[str, object]:
        return json.loads(self.to_json())

    def to_json(self) -> str:
        def instant(value: datetime) -> str:
            return as_utc(value).isoformat().replace("+00:00", "Z")
        return json.dumps({"composition_version": COMPOSITION_VERSION, **asdict(self)},
                          default=instant, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _value(term: ConfidenceTerm, snapshot: FeatureSnapshot,
           context: StrategyContext) -> tuple[Fraction | None, str | None]:
    meta = snapshot.metadata
    if (meta.instrument_id != context.symbol or meta.instrument_type != context.instrument_type
            or meta.session != context.session.session):
        return None, "IDENTITY_MISMATCH"
    if snapshot.feature_version != term.definition_version:
        return None, "DEFINITION_MISMATCH"
    if meta.data_mode != term.data_mode:
        return None, "MODE_MISMATCH"
    if not _known(meta.source) or meta.source_time is None:
        return None, "SOURCE_UNAVAILABLE"
    if meta.quality not in ("VALID", "DEGRADED_PROXY"):
        return None, "QUALITY_UNAVAILABLE"
    # These are supplied current scores/contributions, not a primitive's lookback.
    # A new request cannot refresh an earlier calculation. Raw ancestors may be old.
    if snapshot.evaluated_at != context.evaluated_at:
        return None, "NOT_CURRENT_EVALUATION"
    feature = next((f for f in snapshot.features if f.name == term.feature_name), None)
    if feature is None:
        return None, "FEATURE_UNAVAILABLE"
    if feature.value is None:
        return None, feature.missing_reason
    if feature.unit != "SCORE_POINTS":
        return None, "WRONG_UNIT"
    if not feature.input_record_ids or any(not _known(ref) for ref in feature.input_record_ids):
        return None, "INPUT_REFERENCES_UNAVAILABLE"
    if not set(feature.input_record_ids).issubset(snapshot.input_record_ids):
        return None, "INPUT_REFERENCES_MISMATCH"
    if term.kind == "SCORE" and not 0 <= feature.value <= 100:
        return None, "SCORE_OUT_OF_RANGE"
    return Fraction(str(feature.value)), None


def compose_confidence(request: ConfidenceRequest) -> ConfidenceResult:
    """Combine all three supplied scores, or return explicit missing reasons.

    Fractions use canonical decimal text; weighting does not round for display.
    All declared factors remain mandatory even at zero weight. Their upstream
    normalization and score formula are intentionally outside this mechanism.
    """
    if not isinstance(request, ConfidenceRequest):
        raise RecordError("confidence request is required")
    context, policy = request.context, request.policy
    snapshots = {snapshot.record_id: snapshot for snapshot in context.features}
    bindings = dict(request.bindings)
    scores: dict[str, Fraction] = {}
    factors = []
    reasons = []
    for term in policy.terms:
        snapshot = snapshots.get(bindings.get(term.name))
        if snapshot is None:
            reasons.append(term.name + ":SNAPSHOT_UNAVAILABLE")
            continue
        value, reason = _value(term, snapshot, context)
        if reason is not None:
            reasons.append(term.name + ":" + reason)
        elif term.kind == "SCORE":
            scores[term.component] = value
        else:
            factors.append(ConfidenceComponent(term.name, float(value), term.definition_version))
    if reasons:
        return ConfidenceResult(request, "UNAVAILABLE", tuple(reasons), None)
    weights = (policy.setup_weight, policy.context_weight, policy.execution_weight)
    final = sum(scores[name] * Fraction(str(weight)) for name, weight in zip(COMPONENTS, weights))
    # Valid bounded scores and convex weights already imply these limits. Clamp
    # only the final normalized result, never malformed inputs or missing data.
    final = min(Fraction(100), max(Fraction(0), final))
    confidence = ConfidenceBreakdown(
        *(float(scores[name]) for name in COMPONENTS), float(final), tuple(factors),
    )
    return ConfidenceResult(request, "READY", (), confidence)
