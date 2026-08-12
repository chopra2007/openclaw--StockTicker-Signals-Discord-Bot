"""Append-only Batch 1 trade measurement ledger."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from consensus_engine import db


_DIRECTIONS = {"long", "short"}
_DECISION_STATES = {
    "pending", "scored", "suppressed", "attempt_created", "send_started",
    "confirmed_delivered", "rejected_before_send", "timed_out", "failed",
}
_DELIVERY_STATES = {
    "attempt_created", "send_started", "confirmed_delivered", "rejected_before_send",
    "timed_out", "failed",
}
_ALERT_STATES = _DELIVERY_STATES | {"scored", "suppressed"}
_OUTCOME_STATES = {"pending", "resolved", "missing_data", "timed_out", "failed"}


def _new_id(kind: str) -> str:
    return f"{kind}_{uuid.uuid4().hex}"


def _direction(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in _DIRECTIONS:
        raise ValueError("trade direction must be 'long' or 'short'")
    return normalized


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_score_cache_key(
    *, ticker: str, direction: str, analyst: str = "", source: str = "",
    catalyst: str = "", base_score: float = 0, rule_version: str = "v1",
    time_bucket: int | str | None = None, input_fingerprint: str = "",
) -> str:
    """Return a process-stable key for a fully scored trade situation."""
    payload = {
        "ticker": ticker.upper(), "direction": _direction(direction),
        "analyst": analyst.strip().lower(), "source": source.strip().lower(),
        "catalyst": catalyst.strip().lower(), "base_score": float(base_score),
        "rule_version": rule_version, "time_bucket": time_bucket,
        "input_fingerprint": input_fingerprint,
    }
    return _fingerprint(payload)


def classify_analyst_alignment(candidate_direction: str, analyst_direction: str) -> str:
    """Classify a signed analyst view against the candidate trade direction."""
    candidate = _direction(candidate_direction)
    analyst = str(analyst_direction).strip().lower()
    if analyst not in _DIRECTIONS:
        return "neutral"
    return "agreement" if analyst == candidate else "disagreement"


def _candidate_values(values: dict) -> tuple:
    direction = _direction(values["direction"])
    created_at = float(values.get("created_at") or time.time())
    fingerprint = values.get("input_fingerprint") or _fingerprint({
        "ticker": values["ticker"].upper(), "direction": direction,
        "analyst": values.get("analyst", ""), "catalyst": values.get("catalyst", ""),
        "base_score": float(values.get("base_score", 0)), "created_at": created_at,
    })
    return (
        values.get("candidate_id") or _new_id("cand"), values["ticker"].upper(), direction,
        values.get("analyst", ""), values.get("catalyst", ""),
        float(values.get("base_score", 0)), values.get("rule_version", "v1"),
        fingerprint, created_at,
    )


async def record_candidate(**values) -> str:
    row = _candidate_values(values)
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO measurement_candidates_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    await conn.commit()
    return row[0]


async def _require_candidate(conn, candidate_id: str) -> None:
    cur = await conn.execute(
        "SELECT 1 FROM measurement_candidates_v1 WHERE candidate_id=? LIMIT 1",
        (candidate_id,),
    )
    if await cur.fetchone() is None:
        raise ValueError(f"unknown candidate_id: {candidate_id}")


async def _require_decision(conn, decision_id: str) -> None:
    cur = await conn.execute(
        "SELECT 1 FROM measurement_decision_events_v1 WHERE decision_id=? LIMIT 1",
        (decision_id,),
    )
    if await cur.fetchone() is None:
        raise ValueError(f"unknown decision_id: {decision_id}")


def _decision_values(values: dict) -> tuple:
    status = str(values["status"]).strip().lower()
    if status not in _DECISION_STATES:
        raise ValueError(f"invalid decision status: {status}")
    if status in {"rejected_before_send", "timed_out", "failed"} and not values.get("reason"):
        raise ValueError(f"decision status {status} requires a reason")
    return (
        values.get("event_id") or _new_id("decision_event"),
        values.get("decision_id") or _new_id("dec"), values["candidate_id"], status,
        values.get("reason", ""), values.get("owner_visible_score"),
        values.get("scorer_version", ""), values.get("rule_version", "v1"),
        values.get("input_fingerprint", ""), float(values.get("created_at") or time.time()),
    )


async def transition_decision(**values) -> str:
    row = _decision_values(values)
    conn = await db.get_db()
    await _require_candidate(conn, row[2])
    await conn.execute(
        "INSERT INTO measurement_decision_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    await conn.commit()
    return row[1]


def _delivery_values(values: dict) -> tuple:
    status = str(values["status"]).strip().lower()
    if status not in _DELIVERY_STATES:
        raise ValueError(f"invalid delivery status: {status}")
    if status in {"rejected_before_send", "timed_out", "failed"} and not values.get("reason"):
        raise ValueError(f"delivery status {status} requires a reason")
    delivery_id = values.get("delivery_id") or _new_id("delivery")
    return (
        values.get("event_id") or _new_id("delivery_event"), delivery_id,
        values["decision_id"], values.get("attempt_id") or delivery_id,
        status, values.get("reason", ""), values.get("external_message_id"),
        (float(values.get("confirmed_at") or time.time())
         if status == "confirmed_delivered" else None),
        float(values.get("created_at") or time.time()),
    )


async def record_delivery(**values) -> str:
    row = _delivery_values(values)
    conn = await db.get_db()
    await _require_decision(conn, row[2])
    await conn.execute(
        "INSERT INTO measurement_delivery_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    await conn.commit()
    return row[1]


async def record_alert(
    *, decision_id: str, status: str, reason: str = "",
    owner_visible_score: float | None = None, legacy_alert_id: int | None = None,
    alert_id: str | None = None, event_id: str | None = None,
    created_at: float | None = None,
) -> str:
    """Append an alert lifecycle fact while keeping one stable alert ID."""
    status = str(status).strip().lower()
    if status not in _ALERT_STATES:
        raise ValueError(f"invalid alert status: {status}")
    if status in {"rejected_before_send", "timed_out", "failed"} and not reason:
        raise ValueError(f"alert status {status} requires a reason")
    stable_id = alert_id or _new_id("alert")
    conn = await db.get_db()
    await _require_decision(conn, decision_id)
    await conn.execute(
        "INSERT INTO measurement_alert_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id or _new_id("alert_event"), stable_id, decision_id, status, reason,
         owner_visible_score, legacy_alert_id, created_at or time.time()),
    )
    await conn.commit()
    return stable_id


def _outcome_values(values: dict) -> tuple:
    return (
        values.get("event_id") or _new_id("outcome_event"),
        values.get("outcome_id") or _new_id("outcome"), values["decision_id"],
        _direction(values["direction"]), values["horizon"], values["status"],
        values.get("value"), values.get("error_reason", ""), values.get("analyst", ""),
        float(values.get("created_at") or time.time()),
    )


async def record_outcome(**values) -> str:
    status = str(values["status"]).strip().lower()
    if status not in _OUTCOME_STATES:
        raise ValueError(f"invalid outcome status: {status}")
    if status in {"missing_data", "timed_out", "failed"} and not values.get("error_reason"):
        raise ValueError(f"outcome status {status} requires error_reason")
    conn = await db.get_db()
    await _require_decision(conn, values["decision_id"])
    candidate_direction = await _decision_direction(conn, values["decision_id"])
    if candidate_direction is not None and _direction(values["direction"]) != candidate_direction:
        raise ValueError("outcome direction must match its trade candidate")
    row = _outcome_values(values)
    await conn.execute(
        "INSERT INTO measurement_outcome_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    await conn.commit()
    return row[1]


async def _decision_direction(conn, decision_id: str) -> str | None:
    cur = await conn.execute(
        """SELECT c.direction
           FROM measurement_decision_events_v1 d
           JOIN measurement_candidates_v1 c ON c.candidate_id=d.candidate_id
           WHERE d.decision_id=? ORDER BY d.created_at LIMIT 1""",
        (decision_id,),
    )
    row = await cur.fetchone()
    return row["direction"] if row else None


async def write_initial_trade_bundle(
    *, candidate: dict, decision: dict, alert: dict | None = None,
    delivery: dict | None = None, outcome: dict | None = None,
) -> dict[str, str]:
    """Write linked initial facts together, rolling the whole group back on error."""
    candidate_row = _candidate_values(candidate)
    decision_row = _decision_values({**decision, "candidate_id": candidate_row[0]})
    statements = [
        ("INSERT INTO measurement_candidates_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", candidate_row),
        ("INSERT INTO measurement_decision_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", decision_row),
    ]
    ids = {"candidate_id": candidate_row[0], "decision_id": decision_row[1]}
    if alert is not None:
        alert_status = str(alert.get("status", "attempt_created")).strip().lower()
        if alert_status not in _ALERT_STATES:
            raise ValueError(f"invalid alert status: {alert_status}")
        if alert_status in {"rejected_before_send", "timed_out", "failed"} and not alert.get("reason"):
            raise ValueError(f"alert status {alert_status} requires a reason")
        alert_id = alert.get("alert_id") or _new_id("alert")
        alert_row = (
            alert.get("event_id") or _new_id("alert_event"), alert_id, decision_row[1],
            alert_status,
            alert.get("reason", ""),
            alert.get("owner_visible_score", alert.get("displayed_score")),
            alert.get("legacy_alert_id"), float(alert.get("created_at") or time.time()),
        )
        statements.append(("INSERT INTO measurement_alert_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", alert_row))
        ids["alert_id"] = alert_id
    if delivery is not None:
        delivery_row = _delivery_values({**delivery, "decision_id": decision_row[1]})
        statements.append(("INSERT INTO measurement_delivery_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", delivery_row))
        ids["delivery_id"] = delivery_row[1]
    if outcome is not None:
        outcome_status = str(outcome["status"]).strip().lower()
        if outcome_status not in _OUTCOME_STATES:
            raise ValueError(f"invalid outcome status: {outcome_status}")
        if outcome_status in {"missing_data", "timed_out", "failed"} and not outcome.get("error_reason"):
            raise ValueError(f"outcome status {outcome_status} requires error_reason")
        if _direction(outcome["direction"]) != candidate_row[2]:
            raise ValueError("outcome direction must match its trade candidate")
        outcome_row = _outcome_values({**outcome, "decision_id": decision_row[1]})
        statements.append(("INSERT INTO measurement_outcome_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", outcome_row))
        ids["outcome_id"] = outcome_row[1]
    conn = await db.get_db()
    await conn.execute_transaction(statements)
    return ids


async def write_alert_delivery_bundle(
    *, decision_id: str, legacy_alert_id: int, displayed_score: float,
    created_at: float | None = None, alert_id: str | None = None,
    delivery_id: str | None = None,
) -> dict[str, str]:
    """Atomically append alert, attempt-created, and send-started facts."""
    at = float(created_at or time.time())
    alert_id = alert_id or _new_id("alert")
    delivery_id = delivery_id or _new_id("delivery")
    alert_row = (
        _new_id("alert_event"), alert_id, decision_id, "attempt_created", "",
        float(displayed_score), legacy_alert_id, at,
    )
    created_row = _delivery_values({
        "decision_id": decision_id, "delivery_id": delivery_id,
        "attempt_id": delivery_id, "status": "attempt_created", "created_at": at,
    })
    started_row = _delivery_values({
        "decision_id": decision_id, "delivery_id": delivery_id,
        "attempt_id": delivery_id, "status": "send_started", "created_at": at,
    })
    conn = await db.get_db()
    await _require_decision(conn, decision_id)
    identity_cur = await conn.execute(
        """SELECT c.direction, c.analyst
           FROM measurement_decision_events_v1 d
           JOIN measurement_candidates_v1 c ON c.candidate_id=d.candidate_id
           WHERE d.decision_id=? ORDER BY d.created_at LIMIT 1""",
        (decision_id,),
    )
    identity = await identity_cur.fetchone()
    if identity is None:
        raise ValueError(f"decision has no candidate identity: {decision_id}")
    outcome_row = _outcome_values({
        "decision_id": decision_id,
        "direction": identity["direction"],
        "analyst": identity["analyst"],
        "horizon": "primary",
        "status": "pending",
        "created_at": at,
    })
    await conn.execute_transaction([
        ("INSERT INTO measurement_alert_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", alert_row),
        ("INSERT INTO measurement_delivery_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", created_row),
        ("INSERT INTO measurement_delivery_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", started_row),
        ("INSERT INTO measurement_outcome_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", outcome_row),
    ])
    return {"alert_id": alert_id, "delivery_id": delivery_id, "outcome_id": outcome_row[1]}


async def append_correction(
    *, entity_type: str, entity_id: str, prior_event_id: str, reason: str,
    corrected_fields: dict, actor_version: str, created_at: float | None = None,
) -> str:
    if not reason or not actor_version:
        raise ValueError("correction reason and actor_version are required")
    correction_id = _new_id("correction")
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO measurement_corrections_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (correction_id, entity_type, entity_id, prior_event_id, reason,
         json.dumps(corrected_fields, sort_keys=True), actor_version, created_at or time.time()),
    )
    await conn.commit()
    return correction_id


async def get_trade_chain(candidate_id: str) -> dict[str, Any]:
    conn = await db.get_db()
    tables = {
        "candidates": ("measurement_candidates_v1", "candidate_id = ?"),
        "decisions": ("measurement_decision_events_v1", "candidate_id = ?"),
    }
    result: dict[str, list[dict]] = {}
    decision_ids: list[str] = []
    for name, (table, where) in tables.items():
        cur = await conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY created_at", (candidate_id,))
        result[name] = [dict(row) for row in await cur.fetchall()]
        if name == "decisions":
            decision_ids = list(dict.fromkeys(row["decision_id"] for row in result[name]))
    for name, table in (("alerts", "measurement_alert_events_v1"),
                        ("deliveries", "measurement_delivery_events_v1"),
                        ("outcomes", "measurement_outcome_events_v1")):
        result[name] = []
        for decision_id in decision_ids:
            cur = await conn.execute(
                f"SELECT * FROM {table} WHERE decision_id = ? ORDER BY created_at", (decision_id,))
            result[name].extend(dict(row) for row in await cur.fetchall())
    for alert in result["alerts"]:
        alert["owner_visible_score"] = alert["displayed_score"]
    entity_ids = {candidate_id, *decision_ids}
    entity_ids.update(row.get("alert_id") for row in result["alerts"])
    entity_ids.update(row.get("delivery_id") for row in result["deliveries"])
    entity_ids.update(row.get("outcome_id") for row in result["outcomes"])
    result["corrections"] = []
    for entity_id in filter(None, entity_ids):
        cur = await conn.execute(
            "SELECT * FROM measurement_corrections_v1 WHERE entity_id = ? ORDER BY created_at",
            (entity_id,),
        )
        for row in await cur.fetchall():
            item = dict(row)
            item["corrected_fields"] = json.loads(item["corrected_fields_json"])
            result["corrections"].append(item)
    result["candidate"] = result.pop("candidates")[0] if result["candidates"] else None
    return result


async def reconcile_dual_writes(*, since: float, until: float | None = None) -> dict:
    """Compare old alert rows with the additive ledger without guessing old facts."""
    conn = await db.get_db()
    end = float(until or time.time())
    old_cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM alert_history WHERE alerted_at >= ? AND alerted_at < ?",
        (since, end),
    )
    new_cur = await conn.execute(
        """SELECT COUNT(DISTINCT a.legacy_alert_id) AS n
           FROM measurement_alert_events_v1 a
           WHERE a.created_at >= ? AND a.created_at < ?
             AND a.legacy_alert_id IS NOT NULL
             AND EXISTS (
                 SELECT 1 FROM measurement_delivery_events_v1 de
                 WHERE de.decision_id=a.decision_id
                   AND de.status='confirmed_delivered'
             )""",
        (since, end),
    )
    old_count = int((await old_cur.fetchone())["n"])
    new_count = int((await new_cur.fetchone())["n"])
    candidate_cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM measurement_candidates_v1 WHERE created_at >= ? AND created_at < ?",
        (since, end),
    )
    candidate_count = int((await candidate_cur.fetchone())["n"])
    missing_decision_cur = await conn.execute(
        """SELECT COUNT(*) AS n FROM measurement_candidates_v1 c
           WHERE c.created_at >= ? AND c.created_at < ?
             AND NOT EXISTS (SELECT 1 FROM measurement_decision_events_v1 d
                             WHERE d.candidate_id=c.candidate_id)""",
        (since, end),
    )
    candidates_missing_decision = int((await missing_decision_cur.fetchone())["n"])
    terminal = ("scored", "suppressed", "rejected_before_send", "timed_out", "failed")
    missing_terminal_cur = await conn.execute(
        """SELECT COUNT(*) AS n FROM measurement_candidates_v1 c
           WHERE c.created_at >= ? AND c.created_at < ?
             AND NOT EXISTS (SELECT 1 FROM measurement_decision_events_v1 d
                             WHERE d.candidate_id=c.candidate_id AND d.status IN (?,?,?,?,?))""",
        (since, end, *terminal),
    )
    candidates_missing_terminal_status = int((await missing_terminal_cur.fetchone())["n"])
    lifecycle_cur = await conn.execute(
        """SELECT d.status, COUNT(DISTINCT d.candidate_id) AS n
           FROM measurement_decision_events_v1 d
           JOIN measurement_candidates_v1 c ON c.candidate_id=d.candidate_id
           WHERE c.created_at >= ? AND c.created_at < ?
             AND d.created_at=(SELECT MAX(d2.created_at) FROM measurement_decision_events_v1 d2
                               WHERE d2.candidate_id=d.candidate_id)
           GROUP BY d.status""",
        (since, end),
    )
    lifecycle_counts = {row["status"]: int(row["n"]) for row in await lifecycle_cur.fetchall()}
    mismatch_cur = await conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM measurement_candidates_v1 c
               WHERE c.created_at >= ? AND c.created_at < ?
                 AND c.direction NOT IN ('long','short')) AS missing_direction,
             (SELECT COUNT(*) FROM measurement_decision_events_v1 d
               JOIN measurement_candidates_v1 c ON c.candidate_id=d.candidate_id
               WHERE c.created_at >= ? AND c.created_at < ?
                 AND d.status='scored' AND d.owner_visible_score IS NULL) AS missing_score,
             (SELECT COUNT(*) FROM measurement_alert_events_v1 a
               LEFT JOIN measurement_decision_events_v1 d ON d.decision_id=a.decision_id
               WHERE a.created_at >= ? AND a.created_at < ?
                 AND d.decision_id IS NULL) AS missing_link""",
        (since, end, since, end, since, end),
    )
    mismatch = dict(await mismatch_cur.fetchone())
    field_mismatches = {key: int(value or 0) for key, value in mismatch.items()}
    field_mismatches["missing_side"] = field_mismatches["missing_direction"]
    field_mismatches["candidates_missing_decision"] = candidates_missing_decision
    field_mismatches["candidates_missing_terminal_status"] = candidates_missing_terminal_status
    mismatches = []
    if old_count != new_count:
        mismatches.append({
            "field": "alert_count",
            "old_count": old_count,
            "new_count": new_count,
            "missing_side": "old" if new_count > old_count else "new",
        })
    for field, count in field_mismatches.items():
        if count and field != "missing_side":
            mismatches.append({"field": field, "count": count, "missing_side": "new"})
    return {
        "old_count": old_count, "new_count": new_count,
        "count_difference": new_count - old_count,
        "matches": not mismatches,
        "mismatches": len(mismatches),
        "mismatch_details": mismatches,
        "field_mismatches": field_mismatches,
        "candidate_count": candidate_count,
        "candidates_missing_decision": candidates_missing_decision,
        "candidates_missing_terminal_status": candidates_missing_terminal_status,
        "lifecycle_counts": lifecycle_counts,
    }
