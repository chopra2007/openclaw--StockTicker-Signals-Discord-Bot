"""Serial, supplied-rule state changes. No playbook, live loop or clock read.

The owner supplies canonical proposed transitions after evaluating a strategy.
Only a successful recording acknowledgment advances this engine. A record-store
error propagates; callers must not release dependent output before apply returns.
"""

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol

from .strategy_interface import StrategyContext, StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import RecordError, SessionRecord, StrategyStateTransition


ENGINE_VERSION = "M42_V1"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _label(value: object, name: str) -> None:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")


@dataclass(frozen=True)
class TransitionRules:
    """Exact allowed state/substate pairs, with no default trading graph."""

    version: str
    initial_state: StrategyState
    allowed: tuple[tuple[StrategyState, StrategyState], ...]

    def __post_init__(self) -> None:
        _label(self.version, "rules version")
        if not isinstance(self.initial_state, StrategyState):
            raise RecordError("initial_state must be StrategyState")
        if not isinstance(self.allowed, tuple) or any(
            not isinstance(pair, tuple) or len(pair) != 2
            or any(not isinstance(state, StrategyState) for state in pair)
            for pair in self.allowed
        ):
            raise RecordError("allowed must contain tuples of two StrategyStates")
        if any(old == new for old, new in self.allowed):
            raise RecordError("unchanged states are not meaningful transitions")
        if len(set(self.allowed)) != len(self.allowed):
            raise RecordError("allowed transitions must be unique")


@dataclass(frozen=True)
class TransitionScope:
    """Immutable session/configuration and supplied rules for one state owner."""

    session: SessionRecord
    symbol: str
    instrument_type: str
    direction: str
    strategy_id: str
    strategy_version: str
    rules: TransitionRules

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        _label(self.symbol, "symbol")
        _label(self.strategy_version, "strategy version")
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if self.strategy_id not in STRATEGY_IDS:
            raise RecordError("strategy ID is not supported")
        if not isinstance(self.rules, TransitionRules):
            raise RecordError("rules must be TransitionRules")

    @property
    def stream_id(self) -> str:
        # Versions stay in scope_json: changing them cannot silently fork a
        # running session's history under the same owner identity.
        identity = (self.session.record_id, self.symbol, self.instrument_type,
                    self.direction, self.strategy_id)
        return hashlib.sha256(_json(identity).encode()).hexdigest()

    def to_json(self) -> str:
        return _json({
            "engine_version": ENGINE_VERSION, "session": self.session.as_dict(),
            "symbol": self.symbol, "instrument_type": self.instrument_type,
            "direction": self.direction, "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version, "rules": asdict(self.rules),
        })


@dataclass(frozen=True)
class TransitionEntry:
    """Complete canonical fact plus ordered, versioned storage attribution."""

    scope: TransitionScope
    position: int
    previous_record_id: str | None
    transition: StrategyStateTransition

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TransitionScope) or not isinstance(self.transition, StrategyStateTransition):
            raise RecordError("entry requires canonical scope and transition")
        if type(self.position) is not int or self.position < 1:
            raise RecordError("entry position must be a positive integer")
        if self.position == 1:
            if self.previous_record_id is not None:
                raise RecordError("first entry cannot have a predecessor")
        else:
            _label(self.previous_record_id, "predecessor")
        if self.previous_record_id == self.transition.record_id:
            raise RecordError("entry cannot be its own predecessor")

    def to_json(self) -> str:
        return _json({
            "scope": json.loads(self.scope.to_json()), "stream_id": self.scope.stream_id,
            "position": self.position, "previous_record_id": self.previous_record_id,
            "transition": self.transition.as_dict(),
        })


class TransitionSink(Protocol):
    async def append(self, entry: TransitionEntry) -> None:
        """Acknowledge only a durably saved entry (or an identical retry).

        Recording-only test sinks implement this same boundary. A sink must reject
        conflicting IDs, scope changes and competing positions without overwrites.
        """
        ...


class StateTransitionEngine:
    """One serialized owner; accepted order is time then local position.

    Equal instants are allowed in explicit call order, never sorted by state or
    guessed provider sequence. Only the latest accepted entry is retained here.
    Older retries must be replayed from the beginning into the idempotent store;
    this is not automatic crash/state recovery or a strategy-output controller.
    """

    def __init__(self, scope: TransitionScope, sink: TransitionSink):
        if not isinstance(scope, TransitionScope):
            raise RecordError("scope must be TransitionScope")
        self._scope = scope
        self._sink = sink
        self._state = scope.rules.initial_state
        self._last: TransitionEntry | None = None
        self._lock = asyncio.Lock()

    @property
    def scope(self) -> TransitionScope:
        return self._scope

    def current_state(self) -> StrategyState:
        return self._state

    @property
    def last_entry(self) -> TransitionEntry | None:
        return self._last

    def _check(self, context: StrategyContext, transition: StrategyStateTransition) -> None:
        if not isinstance(context, StrategyContext) or not isinstance(transition, StrategyStateTransition):
            raise RecordError("canonical context and transition are required")
        scope, meta = self._scope, transition.metadata
        if (context.session != scope.session or context.symbol != scope.symbol
                or context.instrument_type != scope.instrument_type
                or context.direction != scope.direction):
            raise RecordError("transition context does not match owner scope")
        if (transition.strategy_id != scope.strategy_id
                or transition.strategy_version != scope.strategy_version
                or meta.instrument_id != scope.symbol
                or meta.instrument_type != scope.instrument_type
                or meta.session != scope.session.session):
            raise RecordError("transition identity does not match owner scope")
        at = context.evaluated_at
        if (transition.occurred_at != at or meta.available_time > at
                or meta.normalized_time > at
                or (meta.source_time is not None and meta.source_time > meta.available_time)):
            raise RecordError("transition times do not match available evaluation")
        if self._last is not None and at < self._last.transition.occurred_at:
            raise RecordError("transition time cannot move backward")
        features = {row.record_id for row in context.features}
        inputs = features | {row.record_id for row in context.catalysts}
        if context.quote is not None and context.quote.quote is not None:
            inputs.add(context.quote.quote.record_id)
        # Parent IDs remain references, not claimed resolved raw records. Full
        # input/snapshot retention and link integrity remain M5.1 work.
        for feature in context.features:
            inputs.update(feature.input_record_ids)
        if (transition.feature_snapshot_id is not None
                and transition.feature_snapshot_id not in features):
            raise RecordError("transition feature snapshot is absent from context")
        if not set(transition.input_record_ids) <= inputs:
            raise RecordError("transition input reference is absent from context")
        if (len(set(transition.input_record_ids)) != len(transition.input_record_ids)
                or transition.record_id in inputs):
            raise RecordError("transition and input IDs must be distinct and unique")

    async def apply(
        self, transition: StrategyStateTransition, *, context: StrategyContext,
    ) -> TransitionEntry:
        async with self._lock:
            self._check(context, transition)
            if self._last is not None and transition == self._last.transition:
                return self._last
            if self._last is not None and transition.record_id == self._last.transition.record_id:
                raise RecordError("transition ID cannot be reused for changed facts")
            before = StrategyState(transition.from_state, transition.from_substate)
            after = StrategyState(transition.to_state, transition.to_substate)
            if before != self._state:
                raise RecordError("transition old state does not match current state")
            if (before, after) not in self._scope.rules.allowed:
                raise RecordError("transition is not in the supplied rules")
            entry = TransitionEntry(
                self._scope, self._last.position + 1 if self._last else 1,
                self._last.transition.record_id if self._last else None, transition,
            )
            await self._sink.append(entry)
            self._state, self._last = after, entry
            return entry

    async def restore(self, entries: tuple[TransitionEntry, ...]) -> StrategyState:
        """Position an unused owner at the end of a complete stored chain (M5.5).

        Restoration reads saved facts only. It writes nothing and fails closed on
        a foreign scope, a gap, a broken predecessor chain, a state or rule
        mismatch, or backward time, so a missing entry is never repaired away.
        """
        async with self._lock:
            if self._last is not None or self._state != self._scope.rules.initial_state:
                raise RecordError("restore requires an unused transition owner")
            if not isinstance(entries, tuple):
                raise RecordError("restore requires stored entries in a tuple")
            state, previous = self._scope.rules.initial_state, None
            for position, entry in enumerate(entries, start=1):
                if not isinstance(entry, TransitionEntry) or entry.scope != self._scope:
                    raise RecordError("restored entry does not match owner scope")
                expected = previous.transition.record_id if previous is not None else None
                if entry.position != position or entry.previous_record_id != expected:
                    raise RecordError("restored entries must form one complete ordered chain")
                before = StrategyState(entry.transition.from_state, entry.transition.from_substate)
                after = StrategyState(entry.transition.to_state, entry.transition.to_substate)
                if before != state or (before, after) not in self._scope.rules.allowed:
                    raise RecordError("restored transition is not in the supplied rules")
                if (previous is not None
                        and entry.transition.occurred_at < previous.transition.occurred_at):
                    raise RecordError("restored transition time cannot move backward")
                state, previous = after, entry
            self._state, self._last = state, previous
            return state

    async def reset(self, session: SessionRecord) -> None:
        """Start an explicitly supplied later session, preserving earlier facts.

        Same-session reset must be an explicit supplied transition; it cannot
        erase history or reset its sequence. Deterministic replay uses a new
        engine instance with the original scope and the same recording store.
        """
        async with self._lock:
            if (not isinstance(session, SessionRecord)
                    or session.record_id == self._scope.session.record_id
                    or session.session <= self._scope.session.session
                    or session.started_at <= self._scope.session.started_at):
                raise RecordError("reset requires a distinct later session")
            old = self._scope
            self._scope = TransitionScope(
                session, old.symbol, old.instrument_type, old.direction,
                old.strategy_id, old.strategy_version, old.rules,
            )
            self._state, self._last = old.rules.initial_state, None
