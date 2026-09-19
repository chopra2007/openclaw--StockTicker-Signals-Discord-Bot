"""Deterministic chronological replay of supplied strategy contexts (M5.3).

This module has no clock, provider, credential, database-path or delivery lookup.
The caller supplies one fixed session, a strategy instance, isolated stores and a
recording sink.  Strategy decisions use the same ``update`` and transition-engine
paths as the live-facing contract.
"""

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from .db import AsyncConnection
from .event_store import ResearchEventStore
from .state_transitions import StateTransitionEngine
from .strategy_interface import Strategy, StrategyContext
from .trade_alerts_models import AlertCandidate, RecordError
from .transition_store import SQLiteTransitionStore
from .utils.time_context import as_utc


REPLAY_VERSION = "M53_V1"


def _label(value: str, name: str) -> None:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class ReplaySpec:
    """Frozen identity and provenance for one supplied-record replay."""

    dataset_id: str
    start_date: date
    end_date: date
    symbols: tuple[str, ...]
    strategy_versions: tuple[tuple[str, str], ...]
    config_hash: str
    feature_engine_version: str
    execution_model: str
    recorded_at: datetime
    code_revision: str | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.dataset_id, "dataset_id"),
                            (self.feature_engine_version, "feature_engine_version"),
                            (self.execution_model, "execution_model")):
            _label(value, name)
        if not isinstance(self.start_date, date) or not isinstance(self.end_date, date):
            raise RecordError("replay date range must use dates")
        if self.start_date > self.end_date:
            raise RecordError("replay start date cannot follow end date")
        if (not isinstance(self.symbols, tuple) or not self.symbols
                or len(set(self.symbols)) != len(self.symbols)):
            raise RecordError("replay symbols must be a non-empty unique tuple")
        for symbol in self.symbols:
            _label(symbol, "symbol")
        if (not isinstance(self.strategy_versions, tuple) or not self.strategy_versions
                or len({row[0] for row in self.strategy_versions}) != len(self.strategy_versions)):
            raise RecordError("replay strategy versions must be a non-empty unique tuple")
        for row in self.strategy_versions:
            if not isinstance(row, tuple) or len(row) != 2:
                raise RecordError("strategy version entries must contain ID and version")
            _label(row[0], "strategy_id")
            _label(row[1], "strategy_version")
        if (not isinstance(self.config_hash, str) or len(self.config_hash) != 64
                or any(char not in "0123456789abcdef" for char in self.config_hash)):
            raise RecordError("config_hash must be a lowercase SHA-256 value")
        object.__setattr__(self, "recorded_at", as_utc(self.recorded_at))
        if self.code_revision is not None:
            _label(self.code_revision, "code_revision")

    def as_dict(self) -> dict:
        return {
            "replay_version": REPLAY_VERSION,
            "dataset_id": self.dataset_id,
            "date_range": [self.start_date.isoformat(), self.end_date.isoformat()],
            "symbols": list(self.symbols),
            "strategy_versions": [list(row) for row in self.strategy_versions],
            "config_hash": self.config_hash,
            "feature_engine_version": self.feature_engine_version,
            "execution_model": self.execution_model,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "code_revision": self.code_revision,
        }


@dataclass(frozen=True)
class ReplayObservation:
    evaluated_at: datetime
    input_record_ids: tuple[str, ...]
    transition_json: tuple[str, ...]
    heads_up_json: str | None
    actionable_json: str | None

    def as_dict(self) -> dict:
        return {
            "evaluated_at": self.evaluated_at.isoformat().replace("+00:00", "Z"),
            "input_record_ids": list(self.input_record_ids),
            "transitions": [json.loads(row) for row in self.transition_json],
            "heads_up": json.loads(self.heads_up_json) if self.heads_up_json else None,
            "actionable": json.loads(self.actionable_json) if self.actionable_json else None,
        }


class ReplaySink(Protocol):
    async def record(self, observation: ReplayObservation) -> None: ...


class RecordingReplaySink:
    """In-memory, non-network replay output."""

    def __init__(self) -> None:
        self.observations: list[ReplayObservation] = []

    async def record(self, observation: ReplayObservation) -> None:
        self.observations.append(observation)


@dataclass(frozen=True)
class ReplayResult:
    spec: ReplaySpec
    observations: tuple[ReplayObservation, ...]

    def as_dict(self) -> dict:
        return {"spec": self.spec.as_dict(),
                "observations": [row.as_dict() for row in self.observations]}

    def to_json(self) -> str:
        return _json(self.as_dict())

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


class HistoricalReplayRunner:
    """Run already-available contexts in supplied order through common runtime."""

    def __init__(self, *, spec: ReplaySpec, strategy: Strategy,
                 transitions: StateTransitionEngine, store: ResearchEventStore,
                 sink: ReplaySink) -> None:
        if type(sink) is not RecordingReplaySink:
            raise RecordError("historical replay requires the recording-only sink")
        if type(store) is not ResearchEventStore:
            raise RecordError("historical replay requires the isolated research store")
        self._spec = spec
        self._strategy = strategy
        self._transitions = transitions
        self._store = store
        self._sink = sink

    async def _check_isolated_storage(self) -> None:
        connection = self._store._connection
        if type(connection) is not AsyncConnection:
            raise RecordError("historical replay requires isolated SQLite storage")
        transition_store = self._transitions._sink
        if type(transition_store) is not SQLiteTransitionStore:
            raise RecordError("historical replay requires isolated SQLite transition storage")
        transition_connection = transition_store._connection
        if type(transition_connection) is not AsyncConnection:
            raise RecordError("historical replay requires isolated SQLite transition storage")

        async def main_path(candidate: AsyncConnection) -> str:
            cursor = await candidate.execute("PRAGMA database_list")
            rows = await cursor.fetchall()
            paths = [row[2] for row in rows if row[1] == "main"]
            if len(paths) != 1:
                raise RecordError("historical replay requires one isolated database")
            return paths[0]

        path = await main_path(connection)
        transition_path = await main_path(transition_connection)
        if path != transition_path or (not path and connection is not transition_connection):
            raise RecordError("historical replay stores must use the same isolated database")
        if not path:
            return
        temp_root = Path(os.environ.get("TMPDIR", "/tmp")).resolve()
        database_path = Path(path).resolve()
        if database_path != temp_root and temp_root not in database_path.parents:
            raise RecordError("historical replay database must be inside temporary storage")

    @staticmethod
    def _inputs(context: StrategyContext) -> tuple[object, ...]:
        rows: list[object] = [context.session, *context.features, *context.catalysts]
        if context.quote is not None and context.quote.quote is not None:
            rows.append(context.quote.quote)
        return tuple(rows)

    @staticmethod
    def _candidate_json(candidate: AlertCandidate | None) -> str | None:
        return candidate.to_json() if candidate is not None else None

    def _check_fixed_scope(self, context: StrategyContext) -> None:
        scope = self._transitions.scope
        expected_version = dict(self._spec.strategy_versions).get(self._strategy.strategy_id)
        if expected_version != self._strategy.strategy_version:
            raise RecordError("strategy version does not match replay specification")
        if (context.session != scope.session or context.session.config_hash != self._spec.config_hash
                or context.symbol != scope.symbol or context.symbol not in self._spec.symbols
                or context.instrument_type != scope.instrument_type
                or context.direction != scope.direction
                or self._strategy.strategy_id != scope.strategy_id
                or self._strategy.strategy_version != scope.strategy_version):
            raise RecordError("replay context does not match fixed runtime scope")
        if not self._spec.start_date <= context.evaluated_at.date() <= self._spec.end_date:
            raise RecordError("replay context falls outside the supplied date range")

    async def run(self, contexts: tuple[StrategyContext, ...]) -> ReplayResult:
        if not isinstance(contexts, tuple) or not contexts:
            raise RecordError("replay requires a non-empty tuple of contexts")
        await self._check_isolated_storage()
        observations: list[ReplayObservation] = []
        previous: datetime | None = None
        for context in contexts:
            if not isinstance(context, StrategyContext):
                raise RecordError("replay inputs must be StrategyContext records")
            self._check_fixed_scope(context)
            if any(feature.feature_version != self._spec.feature_engine_version
                   for feature in context.features):
                raise RecordError("feature version does not match replay specification")
            if previous is not None and context.evaluated_at < previous:
                raise RecordError("replay contexts must be chronological")
            previous = context.evaluated_at
            inputs = self._inputs(context)
            for record in inputs:
                await self._store.append(record, session=context.session.session,
                                         recorded_at=(context.session.started_at
                                                      if record is context.session
                                                      else context.evaluated_at))
            entries = []
            for transition in self._strategy.update(context):
                entry = await self._transitions.apply(transition, context=context)
                await self._store.append(transition, session=context.session.session,
                                         recorded_at=context.evaluated_at)
                entries.append(entry)
            observation = ReplayObservation(
                context.evaluated_at,
                tuple(record.record_id for record in inputs),
                tuple(entry.to_json() for entry in entries),
                self._candidate_json(self._strategy.heads_up()),
                self._candidate_json(self._strategy.actionable()),
            )
            await self._sink.record(observation)
            observations.append(observation)
        return ReplayResult(self._spec, tuple(observations))
