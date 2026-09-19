"""Durable session and delivery recovery over the existing store (M5.5).

The caller owns the injected isolated connection, the existing migrations and the
recording sink. This module opens no database, reads no credentials, contacts no
network, starts no application and chooses no strategy fact. It reads already
stored mechanical facts and delivery intent, restores the versioned transition
state, and decides what a restarted session may still do.

Fixed recovery rules:

* Facts and delivery intent are written by the M5.1 store in one transaction, so
  a database failure before persistence leaves nothing stored and sends nothing.
* One intent produces at most one final delivery fact. A crash before any send
  may retry while the candidate is unexpired; a crash after the send started
  stays UNKNOWN and is never blindly replayed.
* An expired intent never sends on recovery; it is closed as rejected instead.
* Acknowledgment and outcome stay separate records and never rewrite a delivery
  fact.

M18 still owns full load and failure hardening and the operator runbooks.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path

from .alert_delivery import (
    DELIVERY_VERSION, AlertSink, DeliveryResult, DiscordSink, RecordingSink, RenderedAlert,
)
from .candidate_assembly import candidate_is_expired
from .db import AsyncConnection
from .event_store import EVENT_STORE_VERSION, ResearchEventStore
from .state_transitions import ENGINE_VERSION, StateTransitionEngine, TransitionScope
from .strategy_interface import StrategyState
from .trade_alerts_models import (
    AlertCandidate, DeliveryRecord, HumanDecisionRecord, OptionRecommendation, RecordError,
)
from .transition_store import SQLiteTransitionStore
from .utils.time_context import as_utc


RECOVERY_VERSION = "M55_V1"
INTENT_PREFIX = "m51:intent:"
FINAL_SUFFIX = ":result"
STARTED_SUFFIX = ":started"

# Actions a restarted session may take for one stored delivery intent.
COMPLETE = "COMPLETE"
RETRY = "RETRY"
EXPIRED_NO_SEND = "EXPIRED_NO_SEND"
UNCERTAIN_NO_RESEND = "UNCERTAIN_NO_RESEND"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RestoredState:
    """Versioned state rebuilt from stored transition facts only."""

    scope: TransitionScope
    state: StrategyState
    position: int
    last_record_id: str | None
    entry_count: int

    def as_dict(self) -> dict:
        return {
            "recovery_version": RECOVERY_VERSION,
            "engine_version": ENGINE_VERSION,
            "store_version": EVENT_STORE_VERSION,
            "stream_id": self.scope.stream_id,
            "state": self.state.state,
            "substate": self.state.substate,
            "position": self.position,
            "last_record_id": self.last_record_id,
            "entry_count": self.entry_count,
        }


@dataclass(frozen=True)
class DeliveryRecovery:
    """One stored intent and the only action a restart may take for it."""

    intent_id: str
    candidate_id: str
    action: str
    reason: str
    attempts: int
    expires_at: datetime
    final_status: str | None = None

    def as_dict(self) -> dict:
        return {
            "recovery_version": RECOVERY_VERSION,
            "delivery_version": DELIVERY_VERSION,
            "intent_id": self.intent_id,
            "candidate_id": self.candidate_id,
            "action": self.action,
            "reason": self.reason,
            "attempts": self.attempts,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "final_status": self.final_status,
        }


class DurableSessionRecovery:
    """Read stored facts and close or continue an interrupted session."""

    def __init__(self, *, store: ResearchEventStore,
                 transitions: SQLiteTransitionStore | None = None) -> None:
        if type(store) is not ResearchEventStore:
            raise RecordError("recovery requires the isolated research store")
        if transitions is not None and type(transitions) is not SQLiteTransitionStore:
            raise RecordError("recovery requires the isolated SQLite transition store")
        self._store = store
        self._transitions = transitions

    # The M5.3 replay runner keeps its own copy of this boundary so neither
    # milestone can silently relax the other's AT-10 storage proof.
    async def _main_path(self, connection: AsyncConnection) -> str:
        if type(connection) is not AsyncConnection:
            raise RecordError("recovery requires isolated SQLite storage")
        cursor = await connection.execute("PRAGMA database_list")
        paths = [row[2] for row in await cursor.fetchall() if row[1] == "main"]
        if len(paths) != 1:
            raise RecordError("recovery requires one isolated database")
        return paths[0]

    async def check_isolated_storage(self) -> None:
        """Recovery may only read a temporary database shared by both stores."""
        path = await self._main_path(self._store._connection)
        if self._transitions is not None:
            transition_path = await self._main_path(self._transitions._connection)
            if path != transition_path or (
                    not path and self._store._connection is not self._transitions._connection):
                raise RecordError("recovery stores must use the same isolated database")
        if not path:
            return
        temp_root = Path(os.environ.get("TMPDIR", "/tmp")).resolve()
        database_path = Path(path).resolve()
        if database_path != temp_root and temp_root not in database_path.parents:
            raise RecordError("recovery database must be inside temporary storage")

    async def restore_state(self, scope: TransitionScope) -> RestoredState:
        """Rebuild the owner state from the complete stored chain, or fail closed."""
        engine = await self.restore_engine(scope)
        last = engine.last_entry
        return RestoredState(scope, engine.current_state(),
                             last.position if last else 0,
                             last.transition.record_id if last else None,
                             last.position if last else 0)

    async def restore_engine(self, scope: TransitionScope) -> StateTransitionEngine:
        """Return an owner positioned exactly where the stored facts stopped."""
        await self.check_isolated_storage()
        if self._transitions is None:
            raise RecordError("state recovery requires the transition store")
        entries = await self._transitions.read(scope)
        engine = StateTransitionEngine(scope, self._transitions)
        await engine.restore(entries)
        return engine

    async def _canonical(self, record_id: str, expected: type):
        row = await self._store.read(record_id)
        return None if row is None else expected.from_json(row["record_json"])

    async def _delivery_ids(self) -> tuple[str, ...]:
        rows = await self._store.read_all(kind="DELIVERY")
        return tuple(row["record_id"] for row in rows)

    async def _intents(self) -> tuple[tuple[str, dict], ...]:
        rows = await self._store.read_all(kind="DELIVERY_INTENT")
        return tuple((row["record_id"][len(INTENT_PREFIX):], json.loads(row["record_json"]))
                     for row in rows if row["record_id"].startswith(INTENT_PREFIX))

    async def plan(self, *, at: datetime) -> tuple[DeliveryRecovery, ...]:
        """Classify every stored intent without sending or writing anything."""
        await self.check_isolated_storage()
        at = as_utc(at)
        stored = await self._delivery_ids()
        plans = []
        for base, envelope in await self._intents():
            record = DeliveryRecord.from_json(json.dumps(envelope["record"],
                                                         sort_keys=True, separators=(",", ":")))
            candidate = await self._canonical(record.candidate_id, AlertCandidate)
            final = await self._store.read(base + FINAL_SUFFIX)
            attempts = sum(1 for ident in stored if ident.startswith(base + ":")
                           and ident.endswith(STARTED_SUFFIX))
            if candidate is None:
                plans.append(DeliveryRecovery(
                    base, record.candidate_id, BLOCKED, "CANDIDATE_UNAVAILABLE",
                    attempts, record.attempted_at))
                continue
            if at < candidate.created_at:
                raise RecordError("recovery time precedes the stored candidate")
            if final is not None:
                status = json.loads(final["record_json"])["status"]
                plans.append(DeliveryRecovery(base, candidate.record_id, COMPLETE,
                                              "FINAL_FACT_ALREADY_STORED", attempts,
                                              candidate.expires_at, status))
            elif attempts:
                plans.append(DeliveryRecovery(base, candidate.record_id, UNCERTAIN_NO_RESEND,
                                              "CRASH_AFTER_SEND_STARTED", attempts,
                                              candidate.expires_at))
            elif candidate_is_expired(candidate, at=at):
                plans.append(DeliveryRecovery(base, candidate.record_id, EXPIRED_NO_SEND,
                                              "EXPIRED_BEFORE_RECOVERY", attempts,
                                              candidate.expires_at))
            else:
                plans.append(DeliveryRecovery(base, candidate.record_id, RETRY,
                                              "NO_SEND_RECORDED", attempts, candidate.expires_at))
        return tuple(plans)

    async def _rendered(self, envelope: dict, candidate: AlertCandidate) -> RenderedAlert:
        options = None
        if envelope.get("options") is not None:
            options = await self._canonical(envelope["options"]["record_id"], OptionRecommendation)
            if options is None or options.as_dict() != envelope["options"]:
                raise RecordError("recovered option facts differ from the stored intent")
        rendered = RenderedAlert(candidate, options)
        if rendered.text != envelope["text"]:
            raise RecordError("recovered alert text differs from the stored intent")
        return rendered

    async def _close(self, base: str, rendered: RenderedAlert, *, status: str, reason: str,
                     at: datetime, attempts: int, sink_name: str) -> None:
        """Close an intent with a final fact only; this path never sends."""
        record = DeliveryRecord(record_id=base + FINAL_SUFFIX,
                                candidate_id=rendered.candidate.record_id, attempted_at=at,
                                sink=sink_name, status=status)
        await self._store.save_result(DeliveryResult(record, rendered, reason, attempts))

    async def resume(self, *, at: datetime, sink: AlertSink | None = None,
                     mode: str = "replay") -> tuple[DeliveryRecovery, ...]:
        """Apply the only permitted action per intent; expired intents never send."""
        if mode not in {"replay", "shadow", "offline_test"}:
            raise RecordError("no live recovery mode is implemented")
        sink = sink if sink is not None else RecordingSink()
        if not isinstance(sink, (RecordingSink, DiscordSink)):
            raise RecordError("unsupported sink")
        if mode in {"replay", "shadow"} and type(sink) is not RecordingSink:
            raise RecordError("replay and shadow require the recording sink")
        at = as_utc(at)
        plans = await self.plan(at=at)
        envelopes = dict(await self._intents())
        applied = []
        for row in plans:
            if row.action in (COMPLETE, BLOCKED):
                applied.append(row)
                continue
            envelope = envelopes[row.intent_id]
            candidate = await self._canonical(row.candidate_id, AlertCandidate)
            rendered = await self._rendered(envelope, candidate)
            intent_sink = envelope["record"]["sink"]
            if row.action == UNCERTAIN_NO_RESEND:
                # An uncertain send stays UNKNOWN: no blind replay, no invented receipt.
                await self._close(row.intent_id, rendered, status="UNKNOWN",
                                  reason="UNCERTAIN_AFTER_CRASH", at=at, attempts=row.attempts,
                                  sink_name=intent_sink)
                applied.append(DeliveryRecovery(
                    row.intent_id, row.candidate_id, row.action, row.reason,
                    row.attempts, row.expires_at, "UNKNOWN"))
                continue
            if row.action == EXPIRED_NO_SEND:
                await self._close(row.intent_id, rendered, status="REJECTED_BEFORE_SEND",
                                  reason="EXPIRED_ON_RECOVERY", at=at, attempts=row.attempts,
                                  sink_name=intent_sink)
                applied.append(DeliveryRecovery(row.intent_id, row.candidate_id, row.action,
                                                row.reason, row.attempts, row.expires_at,
                                                "REJECTED_BEFORE_SEND"))
                continue
            attempt = row.attempts + 1
            started = DeliveryRecord(
                record_id=f"{row.intent_id}:recovery:{attempt}{STARTED_SUFFIX}",
                candidate_id=row.candidate_id, attempted_at=at, sink=sink.name,
                status="SEND_STARTED")
            # The started fact is durable before the send, so a further crash is
            # recovered as uncertain instead of resent.
            await self._store.save_result(
                DeliveryResult(started, rendered, "RECOVERY_STARTED", row.attempts))
            receipt = await sink.send(rendered, at=at)
            if receipt.attempted_at < at:
                status, reason = "UNKNOWN", "INVALID_RECEIPT_TIME"
                reference, attempts = None, receipt.attempts
            else:
                status, reason = receipt.status, receipt.reason
                reference, attempts = receipt.message_reference, receipt.attempts
            record = DeliveryRecord(record_id=row.intent_id + FINAL_SUFFIX,
                                    candidate_id=row.candidate_id, attempted_at=at, sink=sink.name,
                                    status=status, message_reference=reference)
            await self._store.save_result(DeliveryResult(record, rendered, reason, attempts))
            applied.append(DeliveryRecovery(row.intent_id, row.candidate_id, row.action, reason,
                                            attempt, row.expires_at, status))
        return tuple(applied)

    async def record_acknowledgment(self, record: HumanDecisionRecord, *,
                                    session: str) -> dict:
        """Store a separate acknowledgment that never rewrites a delivery fact."""
        if not isinstance(record, HumanDecisionRecord):
            raise RecordError("acknowledgment requires a canonical HumanDecisionRecord")
        candidate = await self._canonical(record.candidate_id, AlertCandidate)
        if candidate is None:
            raise RecordError("acknowledgment requires its stored candidate")
        if record.decided_at < candidate.created_at:
            raise RecordError("acknowledgment cannot precede its candidate")
        delivered = [row for row in await self._store.read_all(kind="DELIVERY")
                     if json.loads(row["record_json"])["candidate_id"] == candidate.record_id
                     and row["record_id"].endswith(FINAL_SUFFIX)]
        if not delivered:
            raise RecordError("acknowledgment requires a stored final delivery fact")
        return await self._store.append(record, session=session, recorded_at=record.decided_at)

    async def acknowledgments(self) -> tuple[HumanDecisionRecord, ...]:
        rows = await self._store.read_all(kind="ACKNOWLEDGMENT")
        return tuple(HumanDecisionRecord.from_json(row["record_json"]) for row in rows)

    async def delivery_facts(self, candidate_id: str) -> tuple[DeliveryRecord, ...]:
        """Every stored delivery fact for one candidate, in stored order."""
        rows = await self._store.read_all(kind="DELIVERY")
        return tuple(DeliveryRecord.from_json(row["record_json"]) for row in rows
                     if json.loads(row["record_json"])["candidate_id"] == candidate_id)
