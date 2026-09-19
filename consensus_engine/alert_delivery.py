"""Offline candidate rendering and supplied persistence/sink boundaries (M4.6).

No live transport, credentials, clock, database or application is selected here.
M5.1/M5.5 own the durable store, replay recovery and live gate integration.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import re
from typing import Awaitable, Callable, Protocol

from consensus_engine.candidate_assembly import (
    CandidateAssembly, assemble_candidate, candidate_is_expired,
)
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_models import (
    AlertCandidate, DeliveryRecord, OptionRecommendation, RecordError, SessionRecord,
)
from consensus_engine.utils.time_context import as_utc, format_pacific

DELIVERY_VERSION = "M46_V1"


def _text(value: str) -> str:
    # Treat external text as text, including line breaks, markup and mentions.
    value = " ".join(value.split())
    value = value.replace("@", "@\u200b").replace("<", "‹").replace(">", "›")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", value)


def _number(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    return format(Decimal(str(value)), "f")


@dataclass(frozen=True)
class RenderedAlert:
    candidate: AlertCandidate
    options: OptionRecommendation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, AlertCandidate):
            raise RecordError("rendering requires an AlertCandidate")
        if self.options is not None:
            if not isinstance(self.options, OptionRecommendation):
                raise RecordError("options must be a separate OptionRecommendation")
            if self.options.candidate_id != self.candidate.record_id:
                raise RecordError("options must identify the original candidate")
            if self.options.ranked_at < self.candidate.created_at:
                raise RecordError("options cannot precede the candidate")
        # The complete fallback fits one message. Never silently trim facts or
        # claim whole-message success from a partial multi-message send.
        if len(self.text.encode("utf-16-le")) // 2 > 2000:
            raise RecordError("complete alert exceeds the single-message limit")

    @property
    def text(self) -> str:
        row = self.candidate
        risk = row.risk
        score = row.confidence
        lines = [
            f"{'HEADS-UP' if row.alert_type == 'HEADS_UP' else 'ACTIONABLE'} | "
            f"{_text(row.metadata.instrument_id)} | {row.direction}",
            f"Strategy: {_text(row.strategy_id)} ({_text(row.strategy_version)})",
            "Prepare for a possible setup." if row.alert_type == "HEADS_UP" else
            "Review this setup before any manual trade.",
            f"Stock setup: {'Valid' if row.mechanically_valid else 'Not confirmed'}",
            f"Trigger: {_number(row.trigger_price)} | Alert price: {_number(row.alert_price)}",
            f"Entry reference: {_number(risk.entry_reference if risk else None)}",
            f"Stop: {_number(risk.hard_stop if risk else None)} | "
            f"Risk per share: {_number(risk.risk_per_share if risk else None)}",
            f"Stop reason: {_text(risk.rationale) if risk else 'Unavailable'}"
            + (f" | {_text(risk.source)}" if risk else ""),
            f"Soft invalidation: {_text(row.soft_invalidation) if row.soft_invalidation else 'Unavailable'}",
        ]
        lines.extend(
            f"{_text(target.name)}: {_number(target.price)} "
            f"({_number(target.r_multiple)}R) | {_text(target.source)}"
            for target in row.targets
        )
        if not row.targets:
            lines.append("Targets: Unavailable")
        lines.extend([
            f"Quality: {_number(score.final_score)}/100; not a win probability",
            f"Setup {_number(score.setup_score)} | Context {_number(score.context_score)} | "
            f"Execution {_number(score.execution_score)}",
            f"Data: {_text(row.data_quality)} | {_text(row.metadata.data_mode)}",
            f"Created: {format_pacific(row.created_at)}",
            f"Expires: {format_pacific(row.expires_at)}",
            "Human checks: " + ("; ".join(_text(item) for item in row.human_checks) or "None supplied"),
        ])
        if row.confluence:
            lines.append("Supporting setups: " + "; ".join(_text(link.strategy_id) for link in row.confluence))
        option = self.options
        if option is None:
            lines.append("Options: Unavailable; no option result supplied")
        elif option.status == "UNAVAILABLE":
            lines.append("Options: Unavailable; " + "; ".join(_text(reason) for reason in option.reasons))
        elif option.status == "POOR":
            lines.append("Options quality: Poor; " + "; ".join(_text(reason) for reason in option.reasons))
        else:
            lines.append(f"Option: {_text(option.contract_id)} | {option.option_type} | "
                         f"Strike {_number(option.strike)} | Expiry {option.expiry.isoformat()}")
            lines.append(f"Option quality: {_number(option.score)}/100 | "
                         + "; ".join(_text(reason) for reason in option.reasons))
        # No AI dependency: optional prose cannot replace or delay these facts.
        return "\n".join(lines)

    def payload(self, *, plain: bool = False) -> dict:
        content = {"content": self.text} if plain else {"embeds": [{"description": self.text}]}
        return {**content, "allowed_mentions": {"parse": [], "replied_user": False}}


@dataclass(frozen=True)
class SendReceipt:
    """One complete payload's result, never a legacy last-successful-chunk ID."""

    status: str
    reason: str
    attempted_at: datetime
    attempts: int = 0
    message_reference: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"CONFIRMED_DELIVERED", "FAILED", "UNKNOWN", "REJECTED_BEFORE_SEND"}:
            raise RecordError("unsupported send receipt status")
        if not isinstance(self.reason, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.reason):
            raise RecordError("receipt reason must be a fixed code")
        if type(self.attempts) is not int or self.attempts < 0:
            raise RecordError("attempts must be a nonnegative integer")
        object.__setattr__(self, "attempted_at", as_utc(self.attempted_at))
        if self.status == "CONFIRMED_DELIVERED":
            if (not isinstance(self.message_reference, str) or not self.message_reference.strip()
                    or self.attempts == 0):
                raise RecordError("confirmation requires a complete-message reference and attempt")
        elif self.message_reference is not None:
            raise RecordError("an unconfirmed payload cannot claim a message reference")


@dataclass(frozen=True)
class DeliveryIntent:
    record: DeliveryRecord
    rendered: RenderedAlert
    assembly: CandidateAssembly


@dataclass(frozen=True)
class DeliveryResult:
    record: DeliveryRecord
    rendered: RenderedAlert
    reason: str
    attempts: int

    def as_dict(self) -> dict:
        return {"delivery_version": DELIVERY_VERSION, "record": self.record.as_dict(),
                "candidate": self.rendered.candidate.as_dict(), "text": self.rendered.text,
                "options": self.rendered.options.as_dict() if self.rendered.options else None,
                "reason": self.reason, "attempts": self.attempts}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AlertSink(Protocol):
    name: str

    async def send(self, rendered: RenderedAlert, *, at: datetime) -> SendReceipt: ...


class RecordingSink:
    """The injected store receives the complete text; no remote send occurs."""

    name = "recording"

    async def send(self, rendered: RenderedAlert, *, at: datetime) -> SendReceipt:
        return SendReceipt("REJECTED_BEFORE_SEND", "RECORDING_ONLY", at)


class DiscordSink:
    """Explicit test transport boundary; no implicit sender or credential lookup."""

    name = "discord"

    def __init__(self, sender: Callable[[RenderedAlert], Awaitable[SendReceipt]]) -> None:
        self._sender = sender

    async def send(self, rendered: RenderedAlert, *, at: datetime) -> SendReceipt:
        try:
            result = await self._sender(rendered)
        except Exception:
            # Never copy transport exceptions (which can contain credentials).
            return SendReceipt("UNKNOWN", "TRANSPORT_EXCEPTION", at, 1)
        if not isinstance(result, SendReceipt):
            return SendReceipt("UNKNOWN", "UNSTRUCTURED_RECEIPT", at, 1)
        return result


class DeliveryPersistenceError(RuntimeError):
    def __init__(self, result: DeliveryResult) -> None:
        super().__init__("delivery result storage failed; do not resend without reconciliation")
        self.result = result


def _validate_assembly(assembly: CandidateAssembly, candidate: AlertCandidate) -> None:
    """A copied assembly must still satisfy the original assembly contract."""
    checked = assemble_candidate(
        context=assembly.context, confidence_result=assembly.confidence_result,
        component_candidates=assembly.component_candidates,
        record_id=candidate.record_id, metadata=candidate.metadata,
        strategy_id=candidate.strategy_id, strategy_version=candidate.strategy_version,
        alert_type=candidate.alert_type,
        state=StrategyState(candidate.setup_state, candidate.setup_substate),
        structure_id=candidate.structure_id, trigger_price=candidate.trigger_price,
        alert_price=candidate.alert_price, risk=candidate.risk, targets=candidate.targets,
        feature_snapshot_id=candidate.feature_snapshot_id,
        input_record_ids=candidate.input_record_ids, expires_at=candidate.expires_at,
        mechanically_valid=candidate.mechanically_valid, data_quality=candidate.data_quality,
        strategy_lifecycle=candidate.strategy_lifecycle, evidence_stage=candidate.evidence_stage,
        soft_invalidation=candidate.soft_invalidation, human_checks=candidate.human_checks,
        confluence=candidate.confluence,
    )
    if checked != assembly:
        raise RecordError("delivery requires the original validated candidate assembly")


async def deliver_candidate(
    candidate: AlertCandidate, *, session: SessionRecord, assembly: CandidateAssembly,
    record_id: str, at: datetime,
    save_intent: Callable[[DeliveryIntent], Awaitable[None]],
    save_result: Callable[[DeliveryResult], Awaitable[None]],
    sink: AlertSink | None = None, mode: str = "replay",
    options: OptionRecommendation | None = None,
) -> DeliveryResult:
    """Persist supplied complete facts/intent before any sink call.

    Replay and shadow can only record. OFFLINE_TEST is the explicit fake-transport
    exercise; the protected launcher enforces network denial. There is no live
    mode. The supplied store must atomically retain intent facts and refuse an
    already-started intent; actual durable implementation/recovery belongs to M5.
    """
    if mode not in {"replay", "shadow", "offline_test"}:
        raise RecordError("no live delivery mode is implemented")
    sink = sink if sink is not None else RecordingSink()
    if not isinstance(sink, (RecordingSink, DiscordSink)):
        raise RecordError("unsupported sink")
    if mode in {"replay", "shadow"} and type(sink) is not RecordingSink:
        raise RecordError("replay and shadow require the recording sink")
    if not isinstance(session, SessionRecord) or not isinstance(candidate, AlertCandidate):
        raise RecordError("delivery requires canonical candidate and session records")
    if (candidate.session_record_id, candidate.metadata.session, candidate.config_version, candidate.config_hash) != (
            session.record_id, session.session, session.config_version, session.config_hash):
        raise RecordError("candidate must match the fixed session")
    if (not isinstance(assembly, CandidateAssembly) or assembly.candidate != candidate
            or assembly.context.session != session or assembly.confidence_result is None
            or assembly.confidence_result.request.context != assembly.context
            or assembly.confidence_result.confidence != candidate.confidence or assembly.reasons):
        raise RecordError("delivery requires the matching complete candidate assembly")
    _validate_assembly(assembly, candidate)
    at = as_utc(at)
    expired = candidate_is_expired(candidate, at=at)
    rendered = RenderedAlert(candidate, options)
    if options is not None and options.ranked_at > at:
        raise RecordError("future options cannot enter an earlier delivery")
    if record_id == candidate.record_id:
        raise RecordError("delivery and candidate IDs must be distinct")
    pending = DeliveryRecord(record_id=record_id, candidate_id=candidate.record_id,
                             attempted_at=at, sink=sink.name, status="PENDING")
    # Real atomic storage is deliberately injected. Failure here sends nothing.
    await save_intent(DeliveryIntent(pending, rendered, assembly))
    if expired or (candidate.alert_type == "ACTIONABLE" and not candidate.mechanically_valid):
        receipt = SendReceipt("REJECTED_BEFORE_SEND", "EXPIRED" if expired else "INVALID_SETUP", at)
    else:
        started = DeliveryResult(
            DeliveryRecord(record_id=record_id + ":started", candidate_id=candidate.record_id,
                           attempted_at=at, sink=sink.name, status="SEND_STARTED"),
            rendered, "SINK_STARTED", 0)
        await save_result(started)
        receipt = await sink.send(rendered, at=at)
        if receipt.attempted_at < at:
            receipt = SendReceipt("UNKNOWN", "INVALID_RECEIPT_TIME", at, receipt.attempts)
    result = DeliveryResult(
        DeliveryRecord(record_id=record_id + ":result", candidate_id=candidate.record_id,
                       attempted_at=receipt.attempted_at, sink=sink.name, status=receipt.status,
                       message_reference=receipt.message_reference),
        rendered, receipt.reason, receipt.attempts)
    try:
        await save_result(result)
    except Exception:
        raise DeliveryPersistenceError(result) from None
    return result
