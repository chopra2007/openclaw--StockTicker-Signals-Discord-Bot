"""Pure assembly of supplied alert facts; no eligibility or portfolio policy.

Keep the full confidence calculation and every supplied component candidate for
later M5 retention. A consistent record is not a detected or approved strategy.
Expiry inspection never changes a candidate or chooses a suppression reason.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math

from .confidence import ConfidenceResult, compose_confidence
from .strategy_interface import StrategyContext, StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    AlertCandidate, ConfluenceLink, RecordError, RiskLevel, SourceMetadata,
    SuppressionEvent, TargetLevel,
)
from .utils.time_context import as_utc


ASSEMBLY_VERSION = "M45_V1"


def _known(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().upper() not in ("UNKNOWN", "UNSPECIFIED"))


def _scope(context: StrategyContext, metadata: SourceMetadata,
           strategy_id: str, strategy_version: str) -> None:
    if not isinstance(context, StrategyContext) or not isinstance(metadata, SourceMetadata):
        raise RecordError("assembly requires canonical context and metadata")
    if strategy_id not in STRATEGY_IDS or not _known(strategy_version):
        raise RecordError("assembly requires explicit strategy identity and version")
    if (metadata.instrument_id != context.symbol
            or metadata.instrument_type != context.instrument_type
            or metadata.session != context.session.session):
        raise RecordError("assembly metadata does not match the context")
    if (metadata.available_time > context.evaluated_at
            or metadata.normalized_time > context.evaluated_at
            or (metadata.source_time is not None
                and metadata.source_time > metadata.available_time)):
        raise RecordError("assembly metadata is not available at evaluation")
    configured = json.loads(context.session.config_json)["strategies"][strategy_id]
    if configured["strategy_version"] not in (None, strategy_version):
        raise RecordError("assembly strategy version differs from the saved session")


def _context_ids(context: StrategyContext) -> set[str]:
    records = (*context.features, *context.catalysts)
    identifiers = {record.record_id for record in records}
    for snapshot in context.features:
        identifiers.update(snapshot.input_record_ids)
    if context.quote is not None and context.quote.quote is not None:
        identifiers.add(context.quote.quote.record_id)
    return identifiers


def _references(values: tuple[str, ...], allowed: set[str]) -> None:
    if (not isinstance(values, tuple) or any(not _known(value) for value in values)
            or len(values) != len(set(values)) or not set(values).issubset(allowed)):
        raise RecordError("assembly input references must be unique supplied records")


def _candidate_scope(candidate: AlertCandidate, context: StrategyContext) -> None:
    if not isinstance(candidate, AlertCandidate):
        raise RecordError("component must be a canonical candidate")
    _scope(context, candidate.metadata, candidate.strategy_id, candidate.strategy_version)
    saved = context.session
    if (candidate.session_record_id != saved.record_id
            or candidate.config_version != saved.config_version
            or candidate.config_hash != saved.config_hash):
        raise RecordError("candidate configuration does not match the context")
    if candidate.created_at > context.evaluated_at:
        raise RecordError("candidate is not yet available")


@dataclass(frozen=True)
class CandidateAssembly:
    """A canonical candidate plus its full supplied attribution, not a new alert."""

    context: StrategyContext
    confidence_result: ConfidenceResult | None
    component_candidates: tuple[AlertCandidate, ...]
    candidate: AlertCandidate | None
    reasons: tuple[str, ...]

    @property
    def status(self) -> str:
        return "READY" if self.candidate is not None else "UNAVAILABLE"

    def as_dict(self) -> dict[str, object]:
        # ConfidenceResult already serializes the complete fixed context. With
        # no confidence result, retain that context through the same encoder.
        supplied = self.confidence_result
        if supplied is not None:
            confidence = supplied.as_dict()
            context = confidence["request"]["context"]
        else:
            context = json.loads(json.dumps(asdict(self.context), default=lambda value:
                as_utc(value).isoformat().replace("+00:00", "Z"), allow_nan=False))
            confidence = None
        return {"assembly_version": ASSEMBLY_VERSION, "status": self.status,
                "context": context, "confidence_result": confidence,
                "component_candidates": [row.as_dict() for row in self.component_candidates],
                "candidate": self.candidate.as_dict() if self.candidate else None,
                "reasons": list(self.reasons)}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def assemble_candidate(
    *, context: StrategyContext, confidence_result: ConfidenceResult | None,
    record_id: str, metadata: SourceMetadata, strategy_id: str, strategy_version: str,
    alert_type: str, state: StrategyState, structure_id: str,
    trigger_price: float | None, alert_price: float | None, risk: RiskLevel | None,
    targets: tuple[TargetLevel, ...], feature_snapshot_id: str,
    input_record_ids: tuple[str, ...], expires_at: datetime,
    mechanically_valid: bool, data_quality: str, strategy_lifecycle: str,
    evidence_stage: str, soft_invalidation: str | None = None,
    human_checks: tuple[str, ...] = (), confluence: tuple[ConfluenceLink, ...] = (),
    component_candidates: tuple[AlertCandidate, ...] = (),
) -> CandidateAssembly:
    """Validate supplied links, then construct the unchanged canonical record.

Direction, evaluation time and configuration come from the fixed context.
Delivery starts PENDING; only later linked delivery records describe attempts.
No price, geometry, score, state, expiry duration or validity decision is chosen.
Ancestor IDs establish supplied attribution only; M5 owns actual stored links.
"""
    _scope(context, metadata, strategy_id, strategy_version)
    if not _known(record_id) or not _known(structure_id):
        raise RecordError("candidate and structure IDs must be explicit")
    if not isinstance(state, StrategyState):
        raise RecordError("candidate requires a supplied strategy state")
    allowed = _context_ids(context)
    _references(input_record_ids, allowed)
    if record_id in allowed or record_id == context.session.record_id:
        raise RecordError("candidate ID cannot reuse an input or session ID")
    if metadata.quality != data_quality:
        raise RecordError("candidate quality contradicts its metadata")
    if not isinstance(component_candidates, tuple):
        raise RecordError("component candidates must be a tuple")
    components = {}
    for row in component_candidates:
        _candidate_scope(row, context)
        if row.record_id == record_id or row.record_id in components or row.record_id in allowed:
            raise RecordError("component candidate IDs must be distinct")
        components[row.record_id] = row
    if not isinstance(confluence, tuple) or any(not isinstance(link, ConfluenceLink) for link in confluence):
        raise RecordError("confluence must contain canonical links")
    if len({link.candidate_id for link in confluence}) != len(confluence):
        raise RecordError("confluence links must be unique")
    for link in confluence:
        row = components.get(link.candidate_id)
        if row is None or row.strategy_id != link.strategy_id or row.direction != context.direction:
            raise RecordError("confluence must identify a supplied same-direction candidate")
    snapshots = {row.record_id: row for row in context.features}
    primary = snapshots.get(feature_snapshot_id)
    selected_ids = {feature_snapshot_id}
    if primary is not None and (
        primary.metadata.instrument_id != context.symbol
        or primary.metadata.instrument_type != context.instrument_type
    ):
        raise RecordError("candidate feature must belong to the underlying")
    if primary is not None and feature_snapshot_id not in input_record_ids:
        raise RecordError("candidate feature must be retained in input references")
    if risk is not None:
        if not isinstance(risk, RiskLevel):
            raise RecordError("candidate risk must be a canonical risk record")
        sign = 1 if context.direction == "LONG" else -1
        if sign * (risk.entry_reference - risk.hard_stop) <= 0:
            raise RecordError("candidate stop contradicts its direction")
    if not isinstance(targets, tuple) or any(not isinstance(row, TargetLevel) for row in targets):
        raise RecordError("candidate targets must be canonical target records")
    if len({row.name for row in targets}) != len(targets):
        raise RecordError("candidate target names must be unique")
    if risk is not None:
        for row in targets:
            expected = sign * (row.price - risk.entry_reference) / risk.risk_per_share
            if expected <= 0 or not math.isclose(row.r_multiple, expected):
                raise RecordError("candidate targets contradict its supplied risk")
    if confidence_result is not None:
        if not isinstance(confidence_result, ConfidenceResult):
            raise RecordError("candidate requires the full confidence result")
        request = confidence_result.request
        if (request.context != context or request.policy.strategy_id != strategy_id
                or request.policy.strategy_version != strategy_version):
            raise RecordError("confidence attribution does not match the candidate")
        if compose_confidence(request) != confidence_result:
            raise RecordError("confidence result contradicts its supplied calculation")
        bound_ids = {value for _, value in request.bindings if value in snapshots}
        selected_ids.update(bound_ids)
        if not bound_ids.issubset(input_record_ids):
            raise RecordError("candidate must retain all supplied confidence snapshot links")
    if data_quality == "VALID" and any(
        snapshots[identifier].metadata.quality == "DEGRADED_PROXY"
        for identifier in selected_ids if identifier in snapshots
    ):
        raise RecordError("candidate quality cannot conceal supplied degraded inputs")
    reasons = []
    if primary is None:
        reasons.append("FEATURE_SNAPSHOT_UNAVAILABLE")
    if confidence_result is None or confidence_result.confidence is None:
        reasons.append("CONFIDENCE_UNAVAILABLE")
    if alert_type == "ACTIONABLE" and mechanically_valid:
        if trigger_price is None or alert_price is None or risk is None or not targets:
            reasons.append("ACTIONABLE_FACTS_UNAVAILABLE")
        if (data_quality not in ("VALID", "DEGRADED_PROXY")
                or not _known(metadata.source) or not _known(metadata.data_mode)
                or metadata.source_time is None
                or (primary is not None and (
                    primary.metadata.quality not in ("VALID", "DEGRADED_PROXY")
                    or not _known(primary.metadata.source)
                    or not _known(primary.metadata.data_mode)
                    or primary.metadata.source_time is None))):
            reasons.append("ACTIONABLE_DATA_UNAVAILABLE")
    if reasons:
        return CandidateAssembly(context, confidence_result, component_candidates, None, tuple(reasons))
    saved = context.session
    candidate = AlertCandidate(
        record_id=record_id, metadata=metadata, strategy_id=strategy_id,
        strategy_version=strategy_version, direction=context.direction, alert_type=alert_type,
        setup_state=state.state, setup_substate=state.substate,
        strategy_lifecycle=strategy_lifecycle, evidence_stage=evidence_stage,
        delivery_status="PENDING", structure_id=structure_id, trigger_price=trigger_price,
        alert_price=alert_price, risk=risk, soft_invalidation=soft_invalidation,
        targets=targets, confidence=confidence_result.confidence, confluence=confluence,
        human_checks=human_checks, input_record_ids=input_record_ids,
        feature_snapshot_id=feature_snapshot_id, session_record_id=saved.record_id,
        config_version=saved.config_version, config_hash=saved.config_hash,
        created_at=context.evaluated_at, expires_at=expires_at,
        data_quality=data_quality, mechanically_valid=mechanically_valid,
    )
    return CandidateAssembly(context, confidence_result, component_candidates, candidate, ())


def assemble_suppression(
    *, context: StrategyContext, record_id: str, metadata: SourceMetadata,
    strategy_id: str, strategy_version: str, reason: str,
    input_record_ids: tuple[str, ...], candidate: AlertCandidate | None = None,
) -> SuppressionEvent:
    """Record the caller's reason separately, including before a candidate exists.

Later suppression may reference original candidate inputs absent from the new
evaluation context. It cannot rewrite those facts or imply a delivery result.
"""
    _scope(context, metadata, strategy_id, strategy_version)
    if not _known(record_id) or not _known(reason):
        raise RecordError("suppression requires explicit ID and reason")
    allowed = _context_ids(context)
    if candidate is not None:
        _candidate_scope(candidate, context)
        if (candidate.strategy_id != strategy_id or candidate.strategy_version != strategy_version
                or candidate.direction != context.direction):
            raise RecordError("suppression does not match the candidate")
        allowed.update((*candidate.input_record_ids, candidate.feature_snapshot_id, candidate.record_id))
    _references(input_record_ids, allowed)
    if record_id in allowed or record_id == context.session.record_id:
        raise RecordError("suppression ID cannot reuse an input, candidate or session ID")
    return SuppressionEvent(
        record_id=record_id, metadata=metadata,
        candidate_id=candidate.record_id if candidate else None,
        strategy_id=strategy_id, strategy_version=strategy_version,
        occurred_at=context.evaluated_at, reason=reason, input_record_ids=input_record_ids,
    )


def candidate_is_expired(candidate: AlertCandidate, *, at: datetime) -> bool:
    """Inspect an explicit expiry instant; equality is expired, without mutation."""
    if not isinstance(candidate, AlertCandidate) or not isinstance(at, datetime):
        raise RecordError("expiry requires a candidate and explicit timestamp")
    evaluated = as_utc(at)
    if evaluated < candidate.created_at:
        raise RecordError("expiry cannot be inspected before candidate creation")
    return evaluated >= candidate.expires_at
