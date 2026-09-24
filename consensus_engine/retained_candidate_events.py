"""M9.1DA retained training-nine alert-time candidate-event connection.

This boundary gives each supplied first-four producer only the matching retained
bar, trade and quote records for one training ticker-session.  Producers return
candidate, no-event or unavailable decisions.  The connection validates the
scope, alert time and exact retained source identities before preserving them.

It does not calculate a fill, return, stage-1 measurement or package, and it
never opens a held-out name.  Missing original-availability, correction/finality
and point-in-time membership fields remain OFF and untested under D-104.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Sequence

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS, DecisionPlanItem, plan_decision_moments
from .retained_history_batches import RetainedHistoryBatches
from .retained_quote_trade_reader import RetainedQuoteTradeRecord
from .search_run_config import TRAINING_TICKERS
from .trade_alerts_models import Quote, RecordError
from .utils.time_context import as_utc

RUN_VERSION = "M91DA_RETAINED_CANDIDATE_EVENTS_V1"
DECISION_STATUSES = frozenset({"CANDIDATE", "NO_EVENT", "UNAVAILABLE"})


@dataclass(frozen=True)
class CandidateEventInput:
    """Exact retained inputs visible to one playbook producer for one session."""

    playbook: str
    ticker: str
    session: str
    decision_moments: tuple[datetime, ...]
    history: object
    trades: tuple[Quote, ...]
    quotes: tuple[Quote, ...]
    source_record_ids: tuple[str, ...]
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES


@dataclass(frozen=True)
class CandidateEventDecision:
    """One producer decision; CANDIDATE is an alert-time event, not a result."""

    status: str
    producer_version: str
    reason: str
    alerted_at: datetime | None = None
    direction: str | None = None
    input_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetainedCandidateEvent:
    version: str
    playbook: str
    ticker: str
    session: str
    status: str
    producer_version: str
    reason: str
    alerted_at: datetime | None
    direction: str | None
    input_record_ids: tuple[str, ...]
    retained_source_record_ids: tuple[str, ...]
    disabled_rules: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "playbook": self.playbook,
            "ticker": self.ticker,
            "session": self.session,
            "status": self.status,
            "producer_version": self.producer_version,
            "reason": self.reason,
            "alerted_at": None if self.alerted_at is None else self.alerted_at.isoformat(),
            "direction": self.direction,
            "input_record_ids": list(self.input_record_ids),
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "disabled_rules": list(self.disabled_rules),
        }


Producer = Callable[[CandidateEventInput], Sequence[CandidateEventDecision]]


def _market_records(
    records: Sequence[RetainedQuoteTradeRecord], histories: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, list[Quote]]]:
    grouped: dict[tuple[str, str], dict[str, list[Quote]]] = {}
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, RetainedQuoteTradeRecord):
            raise RecordError("quote/trade inputs must be retained reader records")
        quote = record.quote
        key = (quote.metadata.instrument_id, quote.metadata.session)
        if key not in histories:
            raise RecordError("quote/trade input does not match a retained training session")
        if quote.record_id in seen:
            raise RecordError("duplicate retained quote/trade source identity")
        seen.add(quote.record_id)
        grouped.setdefault(key, {"trades": [], "bbo-1m": []})[record.schema].append(quote)
    for values in grouped.values():
        values["trades"].sort(key=lambda row: (row.trade_time, row.record_id))
        values["bbo-1m"].sort(key=lambda row: (row.quote_time, row.record_id))
    return grouped


def _validate_decision(
    supplied: CandidateEventDecision, item: DecisionPlanItem, source_ids: tuple[str, ...],
) -> CandidateEventDecision:
    if not isinstance(supplied, CandidateEventDecision):
        raise RecordError("producer outputs must be CandidateEventDecision records")
    if supplied.status not in DECISION_STATUSES:
        raise RecordError("producer decision status is unsupported")
    if not supplied.producer_version.strip() or not supplied.reason.strip():
        raise RecordError("producer version and decision reason are required")
    if len(set(supplied.input_record_ids)) != len(supplied.input_record_ids):
        raise RecordError("producer input record identities must be unique")
    if not set(supplied.input_record_ids).issubset(source_ids):
        raise RecordError("producer decision cites a record outside its retained session")
    if supplied.status == "CANDIDATE":
        if supplied.alerted_at is None or supplied.direction not in ("LONG", "SHORT"):
            raise RecordError("candidate decisions need an alert time and direction")
        alerted_at = as_utc(supplied.alerted_at)
        if alerted_at not in item.moments:
            raise RecordError("candidate alert time is outside the frozen decision moments")
        if not supplied.input_record_ids:
            raise RecordError("candidate decisions must retain source record identities")
        return CandidateEventDecision(
            supplied.status, supplied.producer_version, supplied.reason,
            alerted_at, supplied.direction, supplied.input_record_ids,
        )
    if supplied.alerted_at is not None or supplied.direction is not None:
        raise RecordError("no-event and unavailable decisions cannot carry a candidate")
    return supplied


def build_retained_candidate_events(
    retained: RetainedHistoryBatches,
    quote_trade_records: Sequence[RetainedQuoteTradeRecord],
    *,
    producers: Mapping[str, Producer],
    expected_tickers: Sequence[str] = TRAINING_TICKERS,
) -> tuple[RetainedCandidateEvent, ...]:
    """Run the four supplied producers over isolated retained session inputs."""
    if not isinstance(retained, RetainedHistoryBatches):
        raise RecordError("retained histories are required")
    if set(producers) != set(PLAYBOOKS):
        raise RecordError("producers must name exactly the frozen first four playbooks")
    expected = tuple(expected_tickers)
    if (not expected or len(set(expected)) != len(expected)
            or not set(expected).issubset(TRAINING_TICKERS)):
        raise RecordError("expected tickers must be a non-empty training-name subset")
    histories: dict[tuple[str, str], object] = {}
    for row in retained.histories:
        key = (row.ticker, row.session)
        if row.ticker not in TRAINING_TICKERS:
            raise RecordError("retained histories contain a held-out ticker")
        if key in histories:
            raise RecordError("duplicate retained training session")
        histories[key] = row
    if {ticker for ticker, _session in histories} != set(expected):
        raise RecordError("candidate-event scope must contain exactly the expected training names")

    market = _market_records(tuple(quote_trade_records), set(histories))
    plan = plan_decision_moments(retained)
    output: list[RetainedCandidateEvent] = []
    session_inputs: dict[tuple[str, str], tuple[tuple[Quote, ...], tuple[Quote, ...], tuple[str, ...]]] = {}
    for item in plan:
        values = market.get((item.ticker, item.session), {"trades": [], "bbo-1m": []})
        key = (item.ticker, item.session)
        if key not in session_inputs:
            trades = tuple(values["trades"])
            quotes = tuple(values["bbo-1m"])
            bar_ids = tuple(bar.record_id for bar in item.history.batch.bars)
            source_ids = tuple(dict.fromkeys(
                (*bar_ids, *(row.record_id for row in trades), *(row.record_id for row in quotes))))
            session_inputs[key] = trades, quotes, source_ids
        trades, quotes, source_ids = session_inputs[key]
        event_input = CandidateEventInput(
            item.playbook, item.ticker, item.session, item.moments, item.history,
            trades, quotes, source_ids,
        )
        decisions = tuple(producers[item.playbook](event_input))
        if not decisions:
            raise RecordError("each producer must return a decision for every retained session")
        keys: set[tuple[datetime | None, str | None]] = set()
        for decision in decisions:
            checked = _validate_decision(decision, item, source_ids)
            if (not trades or not quotes) and checked.status != "UNAVAILABLE":
                raise RecordError("missing retained trades or quotes require UNAVAILABLE")
            key = (checked.alerted_at, checked.direction)
            if key in keys:
                raise RecordError("duplicate producer decision for a session, time and direction")
            keys.add(key)
            output.append(RetainedCandidateEvent(
                RUN_VERSION, item.playbook, item.ticker, item.session,
                checked.status, checked.producer_version, checked.reason,
                checked.alerted_at, checked.direction, checked.input_record_ids,
                source_ids, REQUIRED_DISABLED_RULES,
            ))
    return tuple(output)


__all__ = [
    "CandidateEventDecision", "CandidateEventInput", "DECISION_STATUSES", "Producer",
    "RUN_VERSION", "RetainedCandidateEvent", "build_retained_candidate_events",
]
