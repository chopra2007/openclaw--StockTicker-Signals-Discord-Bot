"""M4.1's offline strategy contract; no strategy, scheduler or live registration.

Implementations own one instrument/direction/session and consume shared features.
This module checks input attribution and time, not trading eligibility, approved
policy, provider coverage or freshness. Those checks remain explicit consumers'
responsibilities. Options, storage, delivery and orders are outside this interface.
"""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from .quote_events import QuoteEventDecision
from .trade_alerts_models import (
    AlertCandidate, CatalystEvent, ConfidenceBreakdown, FeatureSnapshot,
    Quote, RecordError, RiskLevel, SessionRecord, SETUP_STATES, StrategyStateTransition,
    TargetLevel,
)
from .utils.time_context import as_utc, session_date_at


INTERFACE_VERSION = "M41_V1"


def _label(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{field} must be a non-empty string")


@dataclass(frozen=True)
class RequiredData:
    """Named input with an explicit role, definition and mode; no fallback rules.

    Names identify canonical inputs or shared features. Declarations describe an
    implementation's needs; they do not prove availability or approve a formula.
    """

    name: str
    role: str
    definition_version: str
    data_mode: str

    def __post_init__(self) -> None:
        for name in ("name", "definition_version", "data_mode"):
            _label(getattr(self, name), name)
        if self.role not in ("MANDATORY", "MODIFIER", "OPTIONAL"):
            raise RecordError("required-data role is not supported")
        for name in ("definition_version", "data_mode"):
            if getattr(self, name).strip().upper() in ("UNKNOWN", "UNSPECIFIED"):
                raise RecordError(f"{name} must identify an explicit contract")


@dataclass(frozen=True)
class StrategyState:
    """Setup state only; lifecycle, data quality and delivery remain separate."""

    state: str
    substate: str | None = None

    def __post_init__(self) -> None:
        if self.state not in SETUP_STATES:
            raise RecordError("strategy state is not supported")
        if self.substate is not None:
            _label(self.substate, "substate")


@dataclass(frozen=True)
class StrategyContext:
    """Immutable supplied inputs at one explicit evaluation instant.

    Feature snapshots may include explicitly identified reference instruments;
    implementations must select the required symbol/definition/unit/mode, never
    match a feature name alone. Older snapshots remain visible, not freshly valid.
    The optional quote decision is for this underlying at this exact instant.
    An absent or unusable quote and missing feature values remain explicit.
    """

    session: SessionRecord
    symbol: str
    instrument_type: str
    direction: str
    evaluated_at: datetime
    features: tuple[FeatureSnapshot, ...] = ()
    quote: QuoteEventDecision | None = None
    catalysts: tuple[CatalystEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        _label(self.symbol, "symbol")
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("strategy underlying must be EQUITY or ETF")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("strategy direction must be LONG or SHORT")
        if not isinstance(self.evaluated_at, datetime):
            raise RecordError("evaluation requires a timestamp")
        evaluated = as_utc(self.evaluated_at)
        object.__setattr__(self, "evaluated_at", evaluated)
        if (evaluated < self.session.started_at
                or session_date_at(evaluated).isoformat() != self.session.session):
            raise RecordError("evaluation must belong to the supplied session")
        for name, expected in (("features", FeatureSnapshot), ("catalysts", CatalystEvent)):
            records = getattr(self, name)
            if not isinstance(records, tuple) or any(not isinstance(r, expected) for r in records):
                raise RecordError(f"{name} must be a tuple of canonical records")
        records = (*self.features, *self.catalysts)
        for record in records:
            self._check_available(record)
        for feature in self.features:
            if (feature.evaluated_at > evaluated
                    or feature.metadata.session != self.session.session):
                raise RecordError("feature evaluation must be available in this session")
        for catalyst in self.catalysts:
            self._check_underlying(catalyst)
            if catalyst.classified_at is not None and catalyst.classified_at > evaluated:
                raise RecordError("catalyst classification is not yet available")
        if self.quote is not None:
            if not isinstance(self.quote, QuoteEventDecision):
                raise RecordError("quote must be QuoteEventDecision or null")
            if self.quote.evaluated_at != evaluated:
                raise RecordError("quote decision must use the current evaluation time")
            if self.quote.quote is not None:
                quote = self.quote.quote
                self._check_available(quote)
                self._check_underlying(quote)
                if quote.metadata.session != self.session.session:
                    raise RecordError("quote must belong to this session")
                records = (*records, quote)
        identifiers = [record.record_id for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise RecordError("strategy input record IDs must be unique")

    def _check_available(self, record: FeatureSnapshot | CatalystEvent | Quote) -> None:
        metadata = record.metadata
        if metadata.available_time > self.evaluated_at:
            raise RecordError("strategy input is not yet available")
        if metadata.source_time is not None and metadata.source_time > metadata.available_time:
            raise RecordError("strategy source time cannot follow original availability")

    def _check_underlying(self, record: CatalystEvent | Quote) -> None:
        if (record.metadata.instrument_id != self.symbol
                or record.metadata.instrument_type != self.instrument_type):
            raise RecordError("strategy input underlying does not match")


@runtime_checkable
class Strategy(Protocol):
    """Common synchronous interface for one serially owned strategy instance.

    update/invalidate/expire return meaningful canonical transitions for a caller
    to persist. They never write or send. Rejections return no candidate, not an
    exception; invalid contract inputs may raise RecordError. Getter methods are
    side-effect free and return the latest evaluation only, not an emission queue.
    Repeated reads are not new alerts. IDs and times are supplied/reproducible.

    Actual implementations must enforce their adopted rules and input quality,
    replace old outputs on each update, and return no actionable on mandatory
    missing/stale data. Reset clears session state and outputs using the supplied
    fixed session, without mutating earlier records. Legal transitions, expiry
    policy, suppression and durable recovery retain their later milestone owners.
    Runtime isinstance checks establish member presence only, never readiness.
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    @property
    @abstractmethod
    def strategy_version(self) -> str: ...

    @abstractmethod
    def required_data(self) -> tuple[RequiredData, ...]: ...

    @abstractmethod
    def current_state(self) -> StrategyState: ...

    @abstractmethod
    def update(self, context: StrategyContext) -> tuple[StrategyStateTransition, ...]: ...

    @abstractmethod
    def heads_up(self) -> AlertCandidate | None: ...

    @abstractmethod
    def actionable(self) -> AlertCandidate | None: ...

    @abstractmethod
    def invalidate(self, context: StrategyContext, *, reason: str) -> tuple[StrategyStateTransition, ...]: ...

    @abstractmethod
    def expire(self, context: StrategyContext, *, reason: str) -> tuple[StrategyStateTransition, ...]: ...

    @abstractmethod
    def reset(self, session: SessionRecord) -> None: ...

    @abstractmethod
    def confidence(self) -> ConfidenceBreakdown | None: ...

    @abstractmethod
    def stop(self) -> RiskLevel | None: ...

    @abstractmethod
    def targets(self) -> tuple[TargetLevel, ...]: ...
