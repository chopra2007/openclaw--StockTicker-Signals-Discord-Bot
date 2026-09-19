"""Append-only typed research event store (M5.1).

Persists supplied immutable canonical records and the full supplied attribution
(raw inputs, feature snapshots, candidates, components, suppression,
configuration, option result, delivery intent and result) through the host
database transaction wrapper. This module never opens a database, reads
credentials, chooses a path, calculates a score, selects an option, computes an
outcome rule, sends anything, or mutates a record. The caller owns the injected
connection and the existing migrations.

Append-only tables reject UPDATE/DELETE. A stored record_id cannot change kind
or facts; a link to an already-stored record of a kind outside its allowed role
is a conflicting link and is rejected; missing linked inputs stay visible as
unresolved ids and are never converted into favourable facts. Each assembly or
delivery intent is committed as one atomic transaction, so a failure on one row
leaves no partial bundle behind. Deterministic offline reopen preserves every
stored byte. M4.7 reuses this append-only boundary for its supplied candidate
projection. This store still builds no option ranker, outcome rule, live sender,
dedup rule or full M5.5 recovery.
"""

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

from .alert_delivery import _validate_assembly
from .candidate_assembly import CandidateAssembly
from .db import AsyncConnection
from .historical_bars import HistoryBatch
from .outcome_evaluator import BarOutcomeEvaluation
from .trade_alerts_models import RecordError, record_from_json
from .utils.time_context import as_utc


EVENT_STORE_VERSION = "M51_V1"
TABLE = "trade_alerts_research_events_v1"
ROW_FIELDS = ("record_id", "record_type", "kind", "session", "fingerprint",
              "links_json", "recorded_at", "record_json")

# Record class name -> stored kind.
_KIND = {
    "SessionRecord": "CONFIGURATION", "Bar": "RAW_INPUT", "Quote": "RAW_INPUT",
    "OptionQuote": "RAW_INPUT", "CatalystEvent": "RAW_INPUT",
    "StrategyStateTransition": "STATE_TRANSITION", "AlertCandidate": "CANDIDATE",
    "FeatureSnapshot": "FEATURE_SNAPSHOT", "SuppressionEvent": "SUPPRESSION",
    "OptionRecommendation": "OPTION_RESULT", "OutcomeRecord": "OUTCOME",
    "DeliveryRecord": "DELIVERY", "HumanDecisionRecord": "ACKNOWLEDGMENT",
}


def _json(value: Any) -> str:
    if hasattr(value, "to_json"):
        return value.to_json()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    raise RecordError(f"cannot serialize {type(value).__name__}")


def _fingerprint(record_json: str) -> str:
    return hashlib.sha256(record_json.encode("utf-8")).hexdigest()


def _from_row(row) -> dict[str, Any]:
    return dict(zip(ROW_FIELDS, row))


def _links_for(record):
    name = type(record).__name__
    if name in ("SessionRecord", "Bar", "Quote", "OptionQuote", "CatalystEvent"):
        return []
    if name == "FeatureSnapshot":
        return [(ident, "INPUTLINK") for ident in record.input_record_ids]
    if name == "StrategyStateTransition":
        links = [(ident, "INPUTLINK") for ident in record.input_record_ids]
        if record.feature_snapshot_id:
            links.append((record.feature_snapshot_id, "FEATURELINK"))
        return links
    if name == "AlertCandidate":
        links = [(ident, "INPUTLINK") for ident in record.input_record_ids]
        links.append((record.feature_snapshot_id, "FEATURELINK"))
        links.append((record.session_record_id, "CONFIGLINK"))
        links.extend((link.candidate_id, "CANDIDATELINK") for link in record.confluence)
        return links
    if name == "SuppressionEvent":
        links = [(ident, "SUPPRESSIONLINK") for ident in record.input_record_ids]
        if record.candidate_id:
            links.append((record.candidate_id, "CANDIDATELINK"))
        return links
    if name == "OptionRecommendation":
        links = [(record.candidate_id, "CANDIDATELINK")]
        if record.option_quote_id:
            links.append((record.option_quote_id, "OPTIONLINK"))
        return links
    if name == "OutcomeRecord":
        links = [(record.candidate_id, "CANDIDATELINK")]
        links.extend((ident, "INPUTLINK") for ident in record.input_record_ids)
        return links
    if name in ("DeliveryRecord", "HumanDecisionRecord"):
        # An acknowledgment stays a separate record beside its delivery fact.
        return [(record.candidate_id, "CANDIDATELINK")]
    return []


class ResearchEventStore:
    """Append-only typed persistence through the host database transaction."""

    def __init__(self, connection: AsyncConnection):
        self._connection = connection

    async def _fetch(self, record_id):
        cursor = await self._connection.execute(
            f"SELECT {', '.join(ROW_FIELDS)} FROM {TABLE} WHERE record_id = ?", (record_id,))
        row = await cursor.fetchone()
        return _from_row(row) if row is not None else None

    def _prepare(self, record, *, session: str, recorded_at, links=()):
        record_json = _json(record)
        if type(record).__name__ not in _KIND or record_from_json(record_json) != record:
            raise RecordError("research storage requires a canonical record")
        actual_session = record.metadata.session if hasattr(record, "metadata") else getattr(record, "session", session)
        if actual_session != session:
            raise RecordError("research record conflicts with supplied session")
        return {
            "record_id": record.record_id,
            "record_type": type(record).__name__,
            "kind": _KIND[type(record).__name__],
            "session": session,
            "fingerprint": _fingerprint(record_json),
            "links_json": json.dumps([[ident, role] for ident, role in links],
                                     sort_keys=True, separators=(",", ":")),
            "recorded_at": as_utc(recorded_at).isoformat().replace("+00:00", "Z"),
            "record_json": record_json,
        }

    def _insert_stmt(self, value):
        return (
            f"""INSERT INTO {TABLE}
               (record_id, record_type, kind, session, fingerprint, links_json,
                recorded_at, record_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (value["record_id"], value["record_type"], value["kind"],
             value["session"], value["fingerprint"], value["links_json"],
             value["recorded_at"], value["record_json"]),
        )

    async def _write(self, rows: list[dict[str, Any]]) -> None:
        # Identity and forward/reverse link checks execute inside the database
        # transaction, including when two store instances share a connection.
        try:
            await self._connection.execute_transaction([
                self._insert_stmt(row) for row in rows
            ])
        except sqlite3.IntegrityError as error:
            if "research event conflicts" in str(error):
                raise RecordError("stored research event conflicts with supplied facts or links") from error
            raise

    async def append(self, record: Any, *, session: str,
                     recorded_at: datetime) -> dict[str, Any]:
        """Append a canonical fact; identical retries retain its original row."""
        row = self._prepare(record, session=session, recorded_at=recorded_at,
                            links=_links_for(record))
        await self._write([row])
        return await self.read(record.record_id)

    def _envelope(self, record_id: str, kind: str, facts: dict[str, Any],
                  session: str, recorded_at: datetime, links=()) -> dict[str, Any]:
        payload = _json({"store_version": EVENT_STORE_VERSION, **facts})
        return dict(record_id=record_id, record_type=kind, kind=kind,
                    session=session, fingerprint=_fingerprint(payload),
                    links_json=_json([list(link) for link in links]),
                    recorded_at=as_utc(recorded_at).isoformat().replace("+00:00", "Z"),
                    record_json=payload)

    @staticmethod
    def _assembly_records(assembly):
        candidate = assembly.candidate
        records = [assembly.context.session]
        records += list(assembly.context.features)
        records += list(assembly.context.catalysts)
        if assembly.context.quote is not None and assembly.context.quote.quote is not None:
            records.append(assembly.context.quote.quote)
        records += list(assembly.component_candidates)
        records.append(candidate)
        return records

    def _assembly_rows(self, assembly):
        _validate_assembly(assembly, assembly.candidate)
        session = assembly.context.session
        at = assembly.candidate.created_at
        rows = [self._prepare(record, session=record.metadata.session
                              if hasattr(record, "metadata") else session.session,
                              recorded_at=at, links=_links_for(record))
                for record in self._assembly_records(assembly)]
        rows.append(self._envelope(
            "m51:assembly:" + assembly.candidate.record_id, "ASSEMBLY",
            assembly.as_dict(), session.session, at,
            [(assembly.candidate.record_id, "CANDIDATELINK")]))
        return rows

    async def store_history(self, history: HistoryBatch, *, record_id: str,
                            session: str, recorded_at: datetime) -> None:
        """Retain the supplied request, conventions, revisions and original Bars."""
        rows = [self._prepare(bar, session=bar.metadata.session,
                              recorded_at=recorded_at) for bar in history.bars]
        rows.append(self._envelope(record_id, "HISTORY", history.as_dict(), session,
                                   recorded_at, [(bar.record_id, "RAWLINK")
                                                 for bar in history.bars]))
        await self._write(rows)

    async def store_assembly(self, assembly: CandidateAssembly) -> dict[str, Any]:
        """Persist all supplied attribution atomically; identical retries add nothing."""
        if assembly.candidate is None:
            raise RecordError("assembly without a candidate has nothing to store")
        await self._write(self._assembly_rows(assembly))
        return await self.read(assembly.candidate.record_id)

    async def store_outcome(self, evaluation: BarOutcomeEvaluation, *, session: str) -> None:
        """Atomically retain the canonical outcome and all evaluation details."""
        record = evaluation.outcome
        await self._write([
            self._prepare(record, session=session, recorded_at=record.evaluated_at,
                          links=_links_for(record)),
            self._envelope("m52:evaluation:" + record.record_id, "OUTCOME_EVALUATION",
                           evaluation.as_dict(), session, record.evaluated_at,
                           _links_for(record)),
        ])

    async def store_portfolio_projection(self, projection, candidates,
                                         *, session: str,
                                         recorded_at: datetime) -> dict[str, Any]:
        """Atomically retain every M4.7 candidate and its complete projection."""
        from .options_portfolio import PortfolioProjection

        if not isinstance(projection, PortfolioProjection):
            raise RecordError("portfolio storage requires an M4.7 projection")
        if not isinstance(candidates, tuple):
            raise RecordError("portfolio candidates must be a complete tuple")
        identifiers = tuple(sorted(row.record_id for row in candidates))
        if identifiers != projection.retained_candidate_ids:
            raise RecordError("portfolio projection does not retain the supplied candidates")
        rows = [self._prepare(record, session=session, recorded_at=recorded_at,
                              links=_links_for(record)) for record in candidates]
        record_id = "m47:portfolio:" + projection.manifest_hash
        rows.append(self._envelope(
            record_id, "PORTFOLIO_PROJECTION",
            json.loads(projection.to_json()), session, recorded_at,
            [(identifier, "CANDIDATELINK") for identifier in identifiers]))
        await self._write(rows)
        return await self.read(record_id)

    async def restore_portfolio_projection(self, manifest_hash: str) -> dict[str, Any]:
        """Read and verify one exact M4.7 recovery bundle; missing facts fail closed."""
        if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
            raise RecordError("portfolio restore requires an exact manifest hash")
        row = await self.read("m47:portfolio:" + manifest_hash)
        if row is None:
            raise RecordError("portfolio recovery record is unavailable")
        if row["fingerprint"] != _fingerprint(row["record_json"]):
            raise RecordError("portfolio recovery record fingerprint does not match")
        facts = json.loads(row["record_json"])
        if facts.get("manifest_hash") != manifest_hash or facts.get("status") != "RECORDED":
            raise RecordError("portfolio recovery record conflicts with its manifest")
        recovery = facts.get("recovery")
        retained = facts.get("retained_candidate_ids")
        if not isinstance(recovery, list) or not isinstance(retained, list):
            raise RecordError("portfolio recovery facts are unavailable")
        recovered_ids = []
        for item in recovery:
            if not isinstance(item, dict):
                raise RecordError("portfolio recovery facts are unavailable")
            semantic = item.get("semantic_candidate_json")
            fingerprint = item.get("fingerprint")
            key = item.get("candidate_key")
            producer = item.get("producer")
            if (not isinstance(semantic, str) or not isinstance(fingerprint, str)
                    or not isinstance(key, dict) or not isinstance(producer, dict)
                    or not item.get("intent_expires_at") or not item.get("session_close")):
                raise RecordError("portfolio recovery facts are unavailable")
            encoded = json.dumps(key, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != fingerprint:
                raise RecordError("portfolio recovery wrapper fingerprint does not match")
            candidate_id = json.loads(semantic).get("record_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise RecordError("portfolio recovery candidate identity is unavailable")
            recovered_ids.append(candidate_id)
        if sorted(recovered_ids) != sorted(retained):
            raise RecordError("portfolio recovery does not retain every candidate")
        return facts

    async def save_intent(self, intent: Any) -> None:
        """Retain the complete supplied delivery intent before any send."""
        assembly = intent.assembly
        candidate = assembly.candidate
        if candidate is None or intent.record.candidate_id != candidate.record_id:
            raise RecordError("delivery intent requires its original candidate")
        if intent.rendered.candidate != candidate or intent.record.status != "PENDING":
            raise RecordError("delivery intent conflicts with supplied candidate or status")
        rows = self._assembly_rows(assembly)
        pending = intent.record
        session = assembly.context.session.session
        if intent.rendered.options is not None:
            option = intent.rendered.options
            rows.append(self._prepare(option, session=session, recorded_at=pending.attempted_at,
                                      links=_links_for(option)))
        rows.append(self._prepare(pending, session=session, recorded_at=pending.attempted_at,
                                  links=_links_for(pending)))
        rows.append(self._envelope(
            "m51:intent:" + pending.record_id, "DELIVERY_INTENT",
            {"record": pending.as_dict(), "assembly": assembly.as_dict(),
             "text": intent.rendered.text,
             "options": intent.rendered.options.as_dict() if intent.rendered.options else None},
            session, pending.attempted_at, [(candidate.record_id, "CANDIDATELINK")]))
        await self._write(rows)

    async def save_result(self, result: Any) -> None:
        """Append the separate delivery fact and complete receipt details together."""
        record = result.record
        session = result.rendered.candidate.metadata.session
        await self._write([
            self._prepare(record, session=session, recorded_at=record.attempted_at,
                          links=_links_for(record)),
            self._envelope("m51:result:" + record.record_id, "DELIVERY_RESULT",
                           result.as_dict(), session, record.attempted_at,
                           [(record.candidate_id, "CANDIDATELINK")]),
        ])

    async def links(self, record_id: str) -> tuple[dict[str, Any], ...]:
        """Resolve stored links without inventing missing input records."""
        row = await self.read(record_id)
        if row is None:
            raise RecordError("research record is unavailable")
        result = []
        for ident, role in json.loads(row["links_json"]):
            target = await self.read(ident)
            result.append({"record_id": ident, "role": role,
                           "status": "RESOLVED" if target else "UNAVAILABLE",
                           "kind": target["kind"] if target else None})
        return tuple(result)

    async def read(self, record_id: str) -> dict[str, Any] | None:
        return await self._fetch(record_id)

    async def read_all(self, *, kind: str | None = None) -> tuple[dict[str, Any], ...]:
        if kind is None:
            cursor = await self._connection.execute(
                f"SELECT {', '.join(ROW_FIELDS)} FROM {TABLE} ORDER BY record_id")
        else:
            cursor = await self._connection.execute(
                f"SELECT {', '.join(ROW_FIELDS)} FROM {TABLE} WHERE kind = ? ORDER BY record_id",
                (kind,))
        return tuple(_from_row(row) for row in await cursor.fetchall())
