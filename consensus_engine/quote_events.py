"""Offline ordering, age and continuity checks for canonical Quote snapshots.

One caller owns one source/instrument/session/mode stream. There is no transport,
queue, clock read, persistence or live consumer here. Policy and continuity proof
are caller facts; passing these checks cannot establish provider or live readiness.
"""

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
from typing import Any

from .trade_alerts_models import Quote, RecordError
from .utils.time_context import as_utc, session_date_at


INTERFACE_VERSION = "M23_V1"


def _known_label(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() not in {
        "UNKNOWN", "UNSPECIFIED",
    }


def _time(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError("event evaluation requires a timestamp")
    return as_utc(value)


@dataclass(frozen=True)
class QuoteEventPolicy:
    """Explicit maximum ages/gap in seconds, inclusive at equality; no defaults."""

    version: str
    max_quote_age_seconds: float
    max_trade_age_seconds: float
    max_observation_gap_seconds: float

    def __post_init__(self) -> None:
        if not _known_label(self.version):
            raise RecordError("quote event policy requires a known version")
        for value in (self.max_quote_age_seconds, self.max_trade_age_seconds,
                      self.max_observation_gap_seconds):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise RecordError("quote event limits must be finite positive seconds")

    def as_dict(self) -> dict[str, Any]:
        return dict(version=self.version, max_quote_age_seconds=self.max_quote_age_seconds,
                    max_trade_age_seconds=self.max_trade_age_seconds,
                    max_observation_gap_seconds=self.max_observation_gap_seconds)


@dataclass(frozen=True)
class QuoteEventDecision:
    """Detached decision for a recording sink; only forward_* flags feed samples.

    Even forward_trade means a new observed last-trade snapshot, not a complete
    time-and-sales feed or a certified trade count. No acceptance is calculated.
    """

    action: str
    evaluated_at: datetime
    input_record_id: str | None
    quote: Quote | None
    policy: QuoteEventPolicy | None
    connected: bool
    continuity: str
    epoch: int
    continuity_reference: str | None
    quote_age_seconds: float | None
    trade_age_seconds: float | None
    reasons: tuple[str, ...]
    forward_quote: bool = False
    forward_trade: bool = False

    @property
    def usable(self) -> bool:
        return not self.reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "interface_version": INTERFACE_VERSION,
            "action": self.action, "evaluated_at": self.evaluated_at.isoformat(),
            "input_record_id": self.input_record_id,
            "quote": self.quote.as_dict() if self.quote else None,
            "policy": self.policy.as_dict() if self.policy else None,
            "connected": self.connected, "continuity": self.continuity,
            "epoch": self.epoch, "continuity_reference": self.continuity_reference,
            "quote_age_seconds": self.quote_age_seconds,
            "trade_age_seconds": self.trade_age_seconds, "reasons": list(self.reasons),
            "usable": self.usable, "forward_quote": self.forward_quote,
            "forward_trade": self.forward_trade,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _facts(quote: Quote) -> dict[str, Any]:
    """Local re-delivery metadata and opaque sequences cannot create a sample."""
    result = quote.as_dict()
    del result["record_id"]
    for key in ("received_time", "available_time", "normalized_time", "sequence"):
        del result["metadata"][key]
    return result


def _sides(quote: Quote) -> tuple:
    return quote.bid, quote.ask, quote.bid_size, quote.ask_size


def _trade(quote: Quote) -> tuple:
    return quote.last, quote.last_size


class QuoteEventStream:
    """Bounded synchronous snapshot checks; raw partial updates are unsupported.

    Quote and trade timestamps each move forward independently. An older component
    rejects the entire snapshot, without merging fields from different inputs.
    Same-time changed prices/sizes are ambiguous and lose continuity. Sequence
    numbers are preserved but have no assumed provider ordering/gap semantics.
    Only the most recent snapshot and two timestamp/fact watermarks are retained.
    Older repeated snapshots may be classified OUT_OF_ORDER; they never forward.
    """

    def __init__(self, *, source: str, instrument_id: str, instrument_type: str,
                 session: str, data_mode: str, policy: QuoteEventPolicy | None) -> None:
        if not all(_known_label(value) for value in (source, instrument_id, data_mode)):
            raise RecordError("quote stream requires known source, instrument and mode")
        if instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("quote stream requires an equity or ETF")
        try:
            valid_session = isinstance(session, str) and date.fromisoformat(session).isoformat() == session
        except ValueError:
            valid_session = False
        if not valid_session:
            raise RecordError("quote stream requires an ISO session date")
        if policy is not None and not isinstance(policy, QuoteEventPolicy):
            raise RecordError("policy must be QuoteEventPolicy or null")
        self._scope = source, instrument_id, instrument_type, session, data_mode
        self._policy = policy
        self._current: Quote | None = None
        self._current_epoch: int | None = None
        self._current_rejected = False
        self._quote_mark: tuple[datetime, tuple] | None = None
        self._trade_mark: tuple[datetime, tuple] | None = None
        self._connected = False
        self._continuity = "UNKNOWN"
        self._epoch = 0
        self._reference: str | None = None
        self._recovery_after: datetime | None = None
        self._last_evaluated: datetime | None = None
        self._last_observation: datetime | None = None
        self._gap_reported = False

    def _lose_continuity(self, at: datetime) -> None:
        self._continuity = "LOST"
        self._reference = None
        self._epoch += 1
        self._recovery_after = at

    def _tick(self, at: datetime) -> datetime:
        at = _time(at)
        if self._last_evaluated is not None and at < self._last_evaluated:
            raise RecordError("quote stream evaluation time cannot move backwards")
        self._last_evaluated = at
        if (self._connected and self._policy is not None
                and self._last_observation is not None and not self._gap_reported
                and (at - self._last_observation).total_seconds()
                > self._policy.max_observation_gap_seconds):
            self._lose_continuity(at)
            self._gap_reported = True
        return at

    def _data_reasons(self, at: datetime) -> tuple[str, ...]:
        reasons = []
        if self._policy is None:
            reasons.append("MISSING_POLICY")
        quote = self._current
        if quote is None:
            return (*reasons, "MISSING_QUOTE")
        if session_date_at(at).isoformat() != self._scope[3]:
            reasons.append("SESSION_MISMATCH")
        if quote.metadata.quality != "VALID":
            reasons.append("SOURCE_QUALITY_" + quote.metadata.quality)
        if quote.metadata.revision:
            reasons.append("REVISION_REQUIRES_NEW_OBSERVATION")
        if quote.status != "VALID":
            reasons.append("QUOTE_STATUS_" + quote.status)
        if quote.delayed is not False:
            reasons.append("DELAYED" if quote.delayed else "DELAY_UNKNOWN")
        if quote.metadata.source_time is None:
            reasons.append("SOURCE_TIME_UNKNOWN")
        elif quote.metadata.source_time > quote.metadata.available_time:
            reasons.append("INVALID_SOURCE_TIME")
        elif session_date_at(quote.metadata.source_time).isoformat() != self._scope[3]:
            reasons.append("SOURCE_SESSION_MISMATCH")
        elif self._recovery_after is not None and quote.metadata.source_time < self._recovery_after:
            reasons.append("SOURCE_BEFORE_RECOVERY")
        if quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask <= 0:
            reasons.append("MISSING_POSITIVE_SIDES")
        if quote.last is None or quote.last <= 0:
            reasons.append("MISSING_POSITIVE_LAST")
        for name, timestamp, limit in (
            ("QUOTE", quote.quote_time, self._policy.max_quote_age_seconds if self._policy else None),
            ("TRADE", quote.trade_time, self._policy.max_trade_age_seconds if self._policy else None),
        ):
            if timestamp is None:
                reasons.append(name + "_TIME_UNKNOWN")
            elif session_date_at(timestamp).isoformat() != self._scope[3]:
                reasons.append(name + "_SESSION_MISMATCH")
            elif limit is not None and (at - timestamp).total_seconds() > limit:
                reasons.append(name + "_STALE")
        if self._gap_reported:
            reasons.append("OBSERVATION_GAP")
        return tuple(reasons)

    def _decision(self, action: str, at: datetime, input_id: str | None = None,
                  quote_advanced: bool = False, trade_advanced: bool = False) -> QuoteEventDecision:
        reasons = self._data_reasons(at)
        if not self._connected:
            reasons += ("DISCONNECTED",)
        if self._continuity != "CONFIRMED":
            reasons += ("CONTINUITY_" + self._continuity,)
        quote = self._current
        return QuoteEventDecision(
            action, at, input_id, quote, self._policy, self._connected, self._continuity,
            self._epoch, self._reference,
            (at - quote.quote_time).total_seconds() if quote and quote.quote_time else None,
            (at - quote.trade_time).total_seconds() if quote and quote.trade_time else None,
            reasons, quote_advanced and not reasons, trade_advanced and not reasons,
        )

    def connect(self, at: datetime) -> QuoteEventDecision:
        at = self._tick(at)
        if not self._connected:
            self._connected = True
            self._lose_continuity(at)
            self._last_observation = None
            self._gap_reported = False
        return self._decision("CONNECTED", at)

    def disconnect(self, at: datetime) -> QuoteEventDecision:
        at = self._tick(at)
        if self._connected:
            self._connected = False
            self._lose_continuity(at)
        return self._decision("DISCONNECTED", at)

    def mark_gap(self, at: datetime) -> QuoteEventDecision:
        """Report externally known lost input; do not infer a numeric sequence gap."""
        at = self._tick(at)
        self._lose_continuity(at)
        self._gap_reported = True
        return self._decision("GAP", at)

    def inspect(self, at: datetime) -> QuoteEventDecision:
        """Recheck ages without refreshing data or forwarding an observation."""
        return self._decision("INSPECTED", self._tick(at))

    def confirm_continuity(self, *, at: datetime, epoch: int, record_id: str,
                           evidence_reference: str | None) -> QuoteEventDecision:
        """Record caller proof for this epoch and its current fresh snapshot.

        The evidence must cover recovery/warm-up for this exact scope. This method
        checks attribution and timing only, not the external truth of that proof.
        An old checkpoint or a socket connection is insufficient.
        """
        at = self._tick(at)
        quote = self._current
        if (not self._connected or type(epoch) is not int or epoch != self._epoch
                or self._current_epoch != self._epoch
                or not _known_label(evidence_reference) or quote is None
                or record_id != quote.record_id or self._data_reasons(at)
                or quote.metadata.source_time < self._recovery_after
                or quote.quote_time < self._recovery_after
                or quote.trade_time < self._recovery_after):
            return self._decision("CONTINUITY_REJECTED", at, record_id)
        self._continuity = "CONFIRMED"
        self._reference = evidence_reference
        return self._decision("CONTINUITY_CONFIRMED", at, record_id)

    def consume(self, quote: Quote, *, at: datetime) -> QuoteEventDecision:
        if not isinstance(quote, Quote):
            raise RecordError("quote stream consumes canonical Quote records")
        at = self._tick(at)
        metadata = quote.metadata
        scope = (metadata.source, metadata.instrument_id, metadata.instrument_type,
                 metadata.session, metadata.data_mode)
        if scope != self._scope:
            return self._decision("SCOPE_MISMATCH", at, quote.record_id)
        if metadata.available_time > at:
            return self._decision("NOT_AVAILABLE", at, quote.record_id)
        if not self._connected:
            return self._decision("DISCONNECTED", at, quote.record_id)
        if metadata.source_time is not None and metadata.source_time > metadata.available_time:
            self._current = quote
            self._current_rejected = True
            self._lose_continuity(at)
            return self._decision("INVALID_SOURCE_TIME", at, quote.record_id)
        if self._current is not None and _facts(quote) == _facts(self._current):
            return self._decision("DUPLICATE", at, quote.record_id)
        if self._current is not None and quote.record_id == self._current.record_id:
            self._lose_continuity(at)
            return self._decision("IDENTITY_CONFLICT", at, quote.record_id)
        components = ((quote.quote_time, _sides(quote), self._quote_mark),
                      (quote.trade_time, _trade(quote), self._trade_mark))
        if any(timestamp is not None and mark is not None and timestamp < mark[0]
               for timestamp, _, mark in components):
            self._lose_continuity(at)
            return self._decision("OUT_OF_ORDER", at, quote.record_id)
        if metadata.revision == 0 and any(
            timestamp is not None and mark is not None and timestamp == mark[0] and facts != mark[1]
            for timestamp, facts, mark in components
        ):
            self._lose_continuity(at)
            return self._decision("CONFLICT", at, quote.record_id)
        advanced = tuple(timestamp is not None and (mark is None or timestamp > mark[0])
                         for timestamp, _, mark in components)
        # A cache repeat cannot hide an already rejected snapshot.
        if (not any(advanced) and all(timestamp is not None for timestamp, _, _ in components)
                and metadata.revision == 0 and metadata.quality == "VALID"
                and metadata.source_time is not None
                and session_date_at(metadata.source_time).isoformat() == self._scope[3]
                and (self._current_rejected or self._recovery_after is None
                     or metadata.source_time >= self._recovery_after)
                and quote.status == "VALID" and quote.delayed is False):
            return self._decision("REPEATED_TIMESTAMPS", at, quote.record_id)
        self._current = quote
        if quote.quote_time is not None:
            self._quote_mark = quote.quote_time, _sides(quote)
        if quote.trade_time is not None:
            self._trade_mark = quote.trade_time, _trade(quote)
        if any(advanced):
            self._last_observation = metadata.available_time
            self._gap_reported = False
        action = "ACCEPTED"
        self._current_rejected = bool(self._data_reasons(at))
        if metadata.revision:
            action = "REVISION"
            self._lose_continuity(at)
            advanced = False, False
        elif self._current_rejected:
            self._lose_continuity(at)
        elif any(advanced):
            self._current_epoch = self._epoch
        return self._decision(action, at, quote.record_id, *advanced)
