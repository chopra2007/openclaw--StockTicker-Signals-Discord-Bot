"""M0.2D durable offline request queue for recorded load tests.

This module has no provider adapter or runtime registration.  It accepts only a
``RecordedProvider`` whose replies were supplied before dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
import json
import math
import sqlite3
from pathlib import Path
from typing import Mapping


POLICY_VERSION = "M02D_REQUEST_QUEUE_V1"


class QueueError(ValueError):
    """A rejected offline queue operation."""


class RequestPriority(IntEnum):
    INTERACTIVE = 0
    ACTIONABLE = 1
    BACKGROUND = 2
    RESEARCH = 3


@dataclass(frozen=True)
class ClassLimit:
    priority: RequestPriority
    expiry_seconds: int
    timeout_seconds: int


REQUEST_LIMITS = {
    "interactive": ClassLimit(RequestPriority.INTERACTIVE, 5, 2),
    "actionable": ClassLimit(RequestPriority.ACTIONABLE, 10, 5),
    "background": ClassLimit(RequestPriority.BACKGROUND, 60, 15),
    "research": ClassLimit(RequestPriority.RESEARCH, 300, 15),
}


@dataclass(frozen=True)
class QueuePolicy:
    enabled: bool = False
    account_ceiling: int = 110
    ceiling_window_seconds: int = 60
    maximum_length: int = 256
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise QueueError("enabled must be true or false")
        if self.account_ceiling != 110 or self.ceiling_window_seconds != 60:
            raise QueueError("M0.2D account ceiling must be 110 requests per 60 seconds")
        if self.maximum_length != 256:
            raise QueueError("M0.2D maximum queue length must be 256")
        if self.version != POLICY_VERSION:
            raise QueueError("M0.2D policy version is unsupported")


@dataclass(frozen=True)
class QueuedRequest:
    request_id: str
    consumer: str
    request_class: str
    operation: str
    enqueued_at: datetime
    expires_at: datetime
    timeout_seconds: int


@dataclass(frozen=True)
class RecordedReply:
    status_code: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise QueueError("recorded status code must be an integer from 100 through 599")
        if isinstance(self.elapsed_seconds, bool) or not isinstance(self.elapsed_seconds, (int, float)):
            raise QueueError("recorded elapsed seconds must be a number")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise QueueError("recorded elapsed seconds must be finite and non-negative")


class RecordedProvider:
    """A finite set of offline replies; it cannot make an outside call."""

    def __init__(self, replies: Mapping[str, RecordedReply]) -> None:
        if not isinstance(replies, Mapping) or any(
            not isinstance(key, str) or not key or not isinstance(value, RecordedReply)
            for key, value in replies.items()
        ):
            raise QueueError("recorded replies require non-empty request IDs and RecordedReply values")
        self._replies = dict(replies)
        self.calls: list[str] = []

    def call(self, request: QueuedRequest) -> RecordedReply:
        if request.request_id not in self._replies:
            raise QueueError("recorded reply is missing")
        self.calls.append(request.request_id)
        return self._replies[request.request_id]


def _instant(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise QueueError(f"{name} must include a time zone")
    return value.astimezone(timezone.utc)


def _text(value: datetime) -> str:
    return _instant(value, "time").isoformat(timespec="microseconds")


def _request(row: sqlite3.Row) -> QueuedRequest:
    return QueuedRequest(
        request_id=row["request_id"], consumer=row["consumer"],
        request_class=row["request_class"], operation=row["operation"],
        enqueued_at=datetime.fromisoformat(row["enqueued_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        timeout_seconds=row["timeout_seconds"],
    )


class OfflineRequestQueue:
    """A SQLite-backed queue shared by offline processes using the same path."""

    def __init__(self, path: str | Path, policy: QueuePolicy = QueuePolicy()) -> None:
        self.path = Path(path)
        self.policy = policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS request_queue (
                    request_id TEXT PRIMARY KEY,
                    consumer TEXT NOT NULL,
                    request_class TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    finished_at TEXT,
                    result TEXT
                );
                CREATE INDEX IF NOT EXISTS request_queue_order
                    ON request_queue(status, priority, enqueued_at, request_id);
                CREATE TABLE IF NOT EXISTS request_dispatches (
                    request_id TEXT PRIMARY KEY,
                    dispatched_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS request_dispatches_time
                    ON request_dispatches(dispatched_at);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def _begin(self, db: sqlite3.Connection) -> None:
        db.execute("BEGIN IMMEDIATE")

    def _drop_expired(self, db: sqlite3.Connection, now_text: str) -> int:
        cursor = db.execute(
            "UPDATE request_queue SET status='EXPIRED', finished_at=?, result='EXPIRED_IN_QUEUE' "
            "WHERE status='QUEUED' AND expires_at<=?", (now_text, now_text),
        )
        return cursor.rowcount

    def enqueue(self, request_id: str, consumer: str, request_class: str,
                operation: str, now: datetime) -> str:
        if not self.policy.enabled:
            raise QueueError("offline request queue is disabled")
        if request_class not in REQUEST_LIMITS:
            raise QueueError("request class is unsupported")
        if any(not isinstance(value, str) or not value for value in
               (request_id, consumer, operation)):
            raise QueueError("request ID, consumer and operation must be non-empty")
        current = _instant(now, "enqueue time")
        limit = REQUEST_LIMITS[request_class]
        expires = current + timedelta(seconds=limit.expiry_seconds)
        with self._connect() as db:
            self._begin(db)
            try:
                self._drop_expired(db, _text(current))
                if db.execute(
                    "SELECT 1 FROM request_queue WHERE request_id=?", (request_id,)
                ).fetchone() is not None:
                    raise QueueError("request ID already exists")
                depth = db.execute(
                    "SELECT count(*) FROM request_queue WHERE status='QUEUED'"
                ).fetchone()[0]
                if depth >= self.policy.maximum_length:
                    displaced = db.execute(
                        "SELECT request_id, priority FROM request_queue WHERE status='QUEUED' "
                        "ORDER BY priority DESC, enqueued_at DESC, request_id DESC LIMIT 1"
                    ).fetchone()
                    if displaced is None or displaced["priority"] <= int(limit.priority):
                        db.execute(
                            "INSERT INTO request_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
                            "'OVERLOAD_REJECTED', ?, 'QUEUE_FULL')",
                            (request_id, consumer, request_class, int(limit.priority), operation,
                             _text(current), _text(expires), limit.timeout_seconds, _text(current)),
                        )
                        db.execute("COMMIT")
                        return "OVERLOAD_REJECTED"
                    db.execute(
                        "UPDATE request_queue SET status='OVERLOAD_DROPPED', finished_at=?, "
                        "result='DISPLACED_BY_HIGHER_PRIORITY' WHERE request_id=?",
                        (_text(current), displaced["request_id"]),
                    )
                try:
                    db.execute(
                        "INSERT INTO request_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', NULL, NULL)",
                        (request_id, consumer, request_class, int(limit.priority), operation,
                         _text(current), _text(expires), limit.timeout_seconds),
                    )
                except sqlite3.IntegrityError as error:
                    raise QueueError("request ID already exists") from error
                db.execute("COMMIT")
                return "QUEUED"
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def dispatch_next(self, now: datetime, provider: RecordedProvider) -> str:
        if not self.policy.enabled:
            raise QueueError("offline request queue is disabled")
        if not isinstance(provider, RecordedProvider):
            raise QueueError("M0.2D dispatch accepts recorded replies only")
        current = _instant(now, "dispatch time")
        now_text = _text(current)
        cutoff = _text(current - timedelta(seconds=self.policy.ceiling_window_seconds))
        with self._connect() as db:
            self._begin(db)
            try:
                self._drop_expired(db, now_text)
                used = db.execute(
                    "SELECT count(*) FROM request_dispatches WHERE dispatched_at>? AND dispatched_at<=?",
                    (cutoff, now_text),
                ).fetchone()[0]
                if used >= self.policy.account_ceiling:
                    db.execute("COMMIT")
                    return "ACCOUNT_CEILING"
                row = db.execute(
                    "SELECT * FROM request_queue WHERE status='QUEUED' "
                    "ORDER BY priority, enqueued_at, request_id LIMIT 1"
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return "EMPTY"
                request = _request(row)
                # The transaction serializes the final expiry/ceiling check and
                # dispatch record across every process using this database.
                db.execute(
                    "INSERT INTO request_dispatches VALUES (?, ?)",
                    (request.request_id, now_text),
                )
                db.execute(
                    "UPDATE request_queue SET status='DISPATCHED', finished_at=? WHERE request_id=?",
                    (now_text, request.request_id),
                )
                reply = provider.call(request)
                if reply.elapsed_seconds > request.timeout_seconds:
                    result = "TIMEOUT"
                elif reply.status_code == 429:
                    result = "THROTTLED"
                elif reply.status_code in (401, 403):
                    result = "AUTH_FAILURE"
                elif reply.status_code >= 400:
                    result = "PROVIDER_ERROR"
                else:
                    result = "COMPLETED"
                db.execute(
                    "UPDATE request_queue SET status=?, result=? WHERE request_id=?",
                    (result, json.dumps({"status_code": reply.status_code,
                                         "elapsed_seconds": reply.elapsed_seconds},
                                        sort_keys=True, separators=(",", ":")),
                     request.request_id),
                )
                db.execute("COMMIT")
                return result
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def records(self) -> tuple[dict[str, object], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT request_id, consumer, request_class, operation, enqueued_at, expires_at, "
                "timeout_seconds, status, finished_at, result FROM request_queue "
                "ORDER BY enqueued_at, request_id"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def depth(self) -> int:
        with self._connect() as db:
            return db.execute(
                "SELECT count(*) FROM request_queue WHERE status='QUEUED'"
            ).fetchone()[0]
