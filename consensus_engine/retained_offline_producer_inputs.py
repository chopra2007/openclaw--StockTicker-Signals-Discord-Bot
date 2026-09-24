"""Point-in-time offline inputs for the retained first-four producers.

This module connects only facts present in the retained minute bars, BBO-1m and
trade records.  It deliberately leaves halt, macro, catalyst, daily-history,
continuity and confidence facts unknown when the retained files cannot prove
them.  No unknown is converted to a favorable value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache

from .core_price_features import build_core_price_snapshot
from .historical_bars import HistoryBatch
from .orb5_eligibility import MandatoryStatus
from .quote_events import QuoteEventDecision, QuoteEventStream
from .retained_candidate_events import CandidateEventInput
from .trade_alerts_models import FeatureSnapshot, Quote, RecordError
from .utils.time_context import as_utc


RUN_VERSION = "M91DR_RETAINED_OFFLINE_PRODUCER_INPUTS_V2"
ALWAYS_UNKNOWN = (
    "HALT_STATUS_UNAVAILABLE",
    "MACRO_BLACKOUT_UNAVAILABLE",
    "CATALYST_COVERAGE_UNAVAILABLE",
    "DAILY_ATR_UNAVAILABLE",
    "CONFIDENCE_UNAVAILABLE",
)


@dataclass(frozen=True)
class RetainedOfflineProducerMoment:
    """Facts visible at one frozen decision moment."""

    version: str
    evaluated_at: datetime
    status: MandatoryStatus
    measurement: FeatureSnapshot
    quote_decision: QuoteEventDecision | None
    quote_trade_combination: RetainedQuoteTradeCombination
    missing_required_inputs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "evaluated_at": self.evaluated_at.isoformat(),
            "status": {
                "halted": self.status.halted,
                "macro_blackout_active": self.status.macro_blackout_active,
                "catalyst_coverage": self.status.catalyst_coverage,
                "definition_reference": self.status.definition_reference,
                "evidence_reference": self.status.evidence_reference,
                "available_at": self.status.available_at.isoformat(),
            },
            "measurement": self.measurement.as_dict(),
            "quote_decision": (
                self.quote_decision.as_dict() if self.quote_decision is not None else None
            ),
            "quote_trade_combination": self.quote_trade_combination.as_dict(),
            "missing_required_inputs": list(self.missing_required_inputs),
        }


@dataclass(frozen=True)
class RetainedQuoteTradeCombination:
    """The separately retained BBO and trade selected at one decision time.

    The two records keep their own identities.  They are never merged into a
    synthetic market record, and unknown source quality keeps the combination
    unusable.
    """

    evaluated_at: datetime
    quote_record_id: str | None
    trade_record_id: str | None
    last_trade: Quote | None
    reasons: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return not self.reasons

    @property
    def input_record_ids(self) -> tuple[str, ...]:
        return tuple(
            value for value in (self.quote_record_id, self.trade_record_id)
            if value is not None
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "quote_record_id": self.quote_record_id,
            "trade_record_id": self.trade_record_id,
            "last_trade": None if self.last_trade is None else self.last_trade.as_dict(),
            "reasons": list(self.reasons),
            "usable": self.usable,
            "input_record_ids": list(self.input_record_ids),
        }


def _status(at: datetime) -> MandatoryStatus:
    return MandatoryStatus(
        halted=None,
        macro_blackout_active=None,
        catalyst_coverage="UNKNOWN",
        definition_reference=RUN_VERSION,
        evidence_reference="RETAINED_FILES_DO_NOT_PROVE_STATUS_OR_CATALYST_COVERAGE",
        available_at=at,
    )


def _feature(snapshot: FeatureSnapshot, name: str):
    return next(value for value in snapshot.features if value.name == name)


@lru_cache(maxsize=512)
def _measurement(batch: HistoryBatch, moment: datetime) -> FeatureSnapshot:
    """Reuse only identical immutable history and the exact evaluation instant.

    All four playbooks request these same price facts. The complete batch is
    the key, including request, conventions, record identities and every bar
    revision/availability/quality field. Quote state is never cached here.
    The bounded cache retains no more than 512 snapshots across session runs.
    """
    return build_core_price_snapshot(
        record_id=RUN_VERSION,
        evaluated_at=moment,
        minute_history=batch,
        daily_history=None,
        premarket_history=None,
    )


def _market_scope(value: CandidateEventInput, records: tuple[Quote, ...], name: str) -> None:
    if not records:
        return
    instrument_types = {bar.metadata.instrument_type for bar in value.history.batch.bars}
    if len(instrument_types) != 1:
        raise RecordError("retained history must have one instrument type")
    scopes = {
        (
            record.metadata.source,
            record.metadata.instrument_id,
            record.metadata.instrument_type,
            record.metadata.session,
        )
        for record in records
    }
    expected = {
        (
            value.history.batch.source,
            value.ticker,
            next(iter(instrument_types)),
            value.session,
        )
    }
    if len(scopes) != 1 or scopes != expected:
        raise RecordError(f"retained {name} must share the candidate history scope")


def _quote_stream(value: CandidateEventInput) -> QuoteEventStream | None:
    if not value.quotes:
        return None
    _market_scope(value, value.quotes, "quotes")
    data_modes = {quote.metadata.data_mode for quote in value.quotes}
    if len(data_modes) != 1:
        raise RecordError("retained quotes must share one data mode")
    quote = value.quotes[0]
    return QuoteEventStream(
        source=quote.metadata.source,
        instrument_id=quote.metadata.instrument_id,
        instrument_type=quote.metadata.instrument_type,
        session=quote.metadata.session,
        data_mode=next(iter(data_modes)),
        policy=None,
    )


def _combine_quote_trade(
    moment: datetime, decision: QuoteEventDecision | None, trade: Quote | None,
) -> RetainedQuoteTradeCombination:
    reasons: list[str] = []
    if decision is None:
        reasons.append("QUOTE_DECISION_UNAVAILABLE")
    else:
        reasons.extend("QUOTE_" + reason for reason in decision.reasons)
    if trade is None:
        reasons.append("TRADE_UNAVAILABLE")
    else:
        if trade.last is None or trade.trade_time is None:
            reasons.append("TRADE_LAST_UNAVAILABLE")
        if trade.status != "VALID":
            reasons.append("TRADE_STATUS_" + trade.status)
        if trade.metadata.quality != "VALID":
            reasons.append("TRADE_SOURCE_QUALITY_" + trade.metadata.quality)
        if trade.delayed is not False:
            reasons.append("TRADE_DELAYED" if trade.delayed else "TRADE_DELAY_UNKNOWN")
    return RetainedQuoteTradeCombination(
        moment,
        None if decision is None or decision.quote is None else decision.quote.record_id,
        None if trade is None else trade.record_id,
        trade,
        tuple(reasons),
    )


def build_retained_offline_producer_inputs(
    value: CandidateEventInput,
) -> tuple[RetainedOfflineProducerMoment, ...]:
    """Build exact bar features and fail-closed quote views for one session."""
    if not isinstance(value, CandidateEventInput):
        raise RecordError("producer input must be CandidateEventInput")
    if not value.decision_moments:
        raise RecordError("producer input needs frozen decision moments")
    supplied_moments = tuple(as_utc(moment) for moment in value.decision_moments)
    if len(set(supplied_moments)) != len(supplied_moments):
        raise RecordError("decision moments must be distinct")
    moments = tuple(sorted(supplied_moments))

    stream = _quote_stream(value)
    _market_scope(value, value.trades, "trades")
    ordered_quotes: tuple[Quote, ...] = tuple(sorted(
        value.quotes,
        key=lambda quote: (quote.metadata.available_time, quote.record_id),
    ))
    ordered_trades: tuple[Quote, ...] = tuple(sorted(
        value.trades,
        key=lambda trade: (trade.metadata.available_time, trade.record_id),
    ))
    quote_index = 0
    trade_index = 0
    latest_trade: Quote | None = None
    if stream is not None:
        stream.connect(min(moments[0], ordered_quotes[0].metadata.available_time))

    output = []
    for index, moment in enumerate(moments):
        decision = None
        if stream is not None:
            while (quote_index < len(ordered_quotes)
                   and ordered_quotes[quote_index].metadata.available_time <= moment):
                quote = ordered_quotes[quote_index]
                stream.consume(quote, at=quote.metadata.available_time)
                quote_index += 1
            decision = stream.inspect(moment)
        while (trade_index < len(ordered_trades)
               and ordered_trades[trade_index].metadata.available_time <= moment):
            latest_trade = ordered_trades[trade_index]
            trade_index += 1

        combined = _combine_quote_trade(moment, decision, latest_trade)

        measurement = replace(
            _measurement(value.history.batch, moment),
            record_id=(
                f"{RUN_VERSION}:{value.playbook}:{value.ticker}:{value.session}:{index}"
            ),
        )
        missing = list(ALWAYS_UNKNOWN)
        if _feature(measurement, "ATR_1M_20_SMA_V1").value is None:
            missing.append("ATR_1M_UNAVAILABLE")
        if _feature(measurement, "SESSION_VWAP_BAR_HLC3_V1").value is None:
            missing.append("VWAP_UNAVAILABLE")
        if decision is None or not decision.usable:
            missing.append("QUOTE_DECISION_UNAVAILABLE")
        if not combined.usable:
            missing.append("QUOTE_TRADE_COMBINATION_UNAVAILABLE")
        output.append(RetainedOfflineProducerMoment(
            RUN_VERSION,
            moment,
            _status(moment),
            measurement,
            decision,
            combined,
            tuple(missing),
        ))
    return tuple(output)


__all__ = [
    "ALWAYS_UNKNOWN",
    "RUN_VERSION",
    "RetainedOfflineProducerMoment",
    "RetainedQuoteTradeCombination",
    "build_retained_offline_producer_inputs",
]
