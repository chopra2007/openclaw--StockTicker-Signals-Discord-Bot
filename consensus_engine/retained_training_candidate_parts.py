"""M9.1DH bounded parts for the real retained training-nine candidate run.

The retained trade files are too large to hold as one in-memory event stream.
This module reduces one ticker/month batch to small session commitments, then
merges disjoint parts into the accepted M9.1DG record shape. Source identities
and candidate decisions are committed separately, so the result never needs to
copy millions of retained record ids into the final JSON file.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
import hashlib
import json
from typing import Iterable, Sequence

from .retained_candidate_events import CandidateEventInput
from .retained_decision_moments import decision_moments
from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_first_four_candidate_run import RetainedFirstFourCandidateRun
from .retained_training_candidate_record import (
    CANDIDATE_RUN_VERSION,
    RECORD_VERSION,
    STATUSES,
    RetainedTrainingCandidateRecord,
)
from .search_run_config import PLAYBOOKS, TRAINING_TICKERS
from .trade_alerts_models import RecordError
from .utils.time_context import session_bounds

PART_VERSION = "M91DH_RETAINED_TRAINING_CANDIDATE_PART_V1"
SAMPLE_VERSION = "M91DH_RETAINED_TRAINING_CANDIDATE_SAMPLE_V2"
DAY_TYPES = ("NORMAL", "HALF_DAY", "DEGRADED")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_values(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _decision_projection(event) -> dict[str, object]:
    return {
        "version": event.version,
        "playbook": event.playbook,
        "ticker": event.ticker,
        "session": event.session,
        "status": event.status,
        "producer_version": event.producer_version,
        "reason": event.reason,
        "alerted_at": None if event.alerted_at is None else event.alerted_at.isoformat(),
        "direction": event.direction,
        "input_record_ids": list(event.input_record_ids),
        "disabled_rules": list(event.disabled_rules),
    }


@dataclass(frozen=True)
class RetainedTrainingCandidatePart:
    version: str
    tickers: tuple[str, ...]
    sessions: tuple[tuple[str, str], ...]
    status_totals: tuple[tuple[str, str, int], ...]
    ticker_totals: tuple[tuple[str, str, int], ...]
    source_sessions: tuple[tuple[str, str, int, str], ...]
    event_sessions: tuple[tuple[str, str, int, str], ...]
    disabled_rules: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "tickers": list(self.tickers),
            "sessions": [{"ticker": ticker, "session": session}
                         for ticker, session in self.sessions],
            "status_totals": [
                {"playbook": playbook, "status": status, "count": count}
                for playbook, status, count in self.status_totals
            ],
            "ticker_totals": [
                {"ticker": ticker, "status": status, "count": count}
                for ticker, status, count in self.ticker_totals
            ],
            "source_sessions": [
                {"ticker": ticker, "session": session, "count": count, "sha256": sha256}
                for ticker, session, count, sha256 in self.source_sessions
            ],
            "event_sessions": [
                {"ticker": ticker, "session": session, "count": count, "sha256": sha256}
                for ticker, session, count, sha256 in self.event_sessions
            ],
            "disabled_rules": list(self.disabled_rules),
            "held_out_opened": False,
            "fills_or_returns_calculated": False,
            "supervised_package_calculated": False,
            "gap_dependent_rules": "OFF_UNTESTED",
        }


@dataclass(frozen=True)
class CandidateSampleDay:
    ticker: str
    session: str
    day_type: str
    event_count: int
    skip_reason: str | None = None


@dataclass(frozen=True)
class CandidateSampleField:
    path: str
    value_json: str
    unit: str


@dataclass(frozen=True)
class CandidateSampleMoment:
    """A complete input snapshot checked at one frozen moment for one adapter."""

    inputs: CandidateEventInput
    inspected_fields: tuple[CandidateSampleField, ...]


def candidate_sample_fields(value: CandidateEventInput) -> tuple[CandidateSampleField, ...]:
    """Print the entire adapter input, not a caller-selected field subset.

    Both retained request builders consume CandidateEventInput. Including every
    input leaf (even unused leaves) covers their bar adapters, coverage checks
    and parent scans without guessing which branch a future sample will take.
    Empty/optional slots are printed too; they never supply missing facts.
    """
    if not isinstance(value, CandidateEventInput) or len(value.decision_moments) != 1:
        raise RecordError("field inspection needs one adapter input moment")
    if value.playbook not in PLAYBOOKS or not value.history.batch.bars:
        raise RecordError("field inspection needs a first-four adapter and bars")
    conventions = value.history.batch.conventions
    if (conventions.price != "USD_PER_SHARE" or conventions.volume != "SHARES"
            or any(bar.price_convention != conventions.price or bar.volume_convention != conventions.volume
                   for bar in value.history.batch.bars)):
        raise RecordError("sample price and volume units must be known and compatible")
    if not value.trades or not value.quotes:
        raise RecordError("sample moment needs retained trades and quotes")
    if any(row.last is None or row.trade_time is None for row in value.trades):
        raise RecordError("sample trade fields are missing")
    if any(row.bid is None or row.ask is None or row.quote_time is None for row in value.quotes):
        raise RecordError("sample quote fields are missing")
    if any(not bar.certified_no_trade and any(getattr(bar, name) is None
           for name in ("open", "high", "low", "close", "volume"))
           for bar in value.history.batch.bars):
        raise RecordError("sample bar fields are missing")
    if any(row.metadata.source_time is None
           for row in (*value.history.batch.bars, *value.trades, *value.quotes)):
        raise RecordError("sample source timestamps are missing")
    if value.playbook == "OR_FAILURE_REV" and any(row.delayed is None for row in value.trades):
        raise RecordError("sample consumed trade delay flag is missing")
    result = []

    def visit(path, item):
        if is_dataclass(item):
            for field in fields(item):
                visit(f"{path}.{field.name}" if path else field.name, getattr(item, field.name))
            return
        if isinstance(item, tuple) and item:
            for index, child in enumerate(item):
                visit(f"{path}[{index}]", child)
            return
        name = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if isinstance(item, datetime):
            unit, rendered = "ABSOLUTE_INSTANT", item.isoformat()
        elif isinstance(item, time):
            unit, rendered = "CLOCK_TIME", item.isoformat()
        elif type(item) is bool:
            unit, rendered = "BOOLEAN", item
        elif type(item) in (int, float):
            if name in {"open", "high", "low", "close", "last", "bid", "ask"}:
                unit = "USD_PER_SHARE"
            elif name in {"volume", "last_size", "bid_size", "ask_size"}:
                unit = "SHARES"
            elif name in {"schema_version", "revision", "sequence"}:
                unit = "INTEGER"
            else:
                raise RecordError(f"sample field has no defined unit: {path}")
            rendered = item
        elif item is None:
            unit, rendered = "ABSENT_OPTIONAL_SLOT", None
        elif item == ():
            unit, rendered = "EMPTY_COLLECTION", []
        elif isinstance(item, str) and item.strip():
            unit, rendered = "LABEL", item
        else:
            raise RecordError(f"sample field is missing or unsupported: {path}")
        result.append(CandidateSampleField(path, _canonical(rendered), unit))

    # SessionHistory is a wrapper; the batch contains the complete typed source
    # data, request and conventions actually read by the retained producers.
    for field in fields(value):
        if field.name != "history":
            visit(field.name, getattr(value, field.name))
    visit("history.ticker", value.history.ticker)
    visit("history.session", value.history.session)
    visit("history.batch", value.history.batch)
    return tuple(sorted(result, key=lambda row: row.path))


@dataclass(frozen=True)
class RetainedCandidateSampleInspection:
    version: str
    ticker_event_counts: tuple[tuple[str, int], ...]
    playbook_event_counts: tuple[tuple[str, int], ...]
    day_type_counts: tuple[tuple[str, int], ...]
    planned_session_count: int
    sampled_session_count: int
    plan_sha256: str
    sample_part_sha256: str
    adapter_moments: tuple[CandidateSampleMoment, ...]
    sampled_days: tuple[CandidateSampleDay, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "ticker_event_counts": dict(self.ticker_event_counts),
            "playbook_event_counts": dict(self.playbook_event_counts),
            "day_type_counts": dict(self.day_type_counts),
            "count_basis": "CANDIDATE_OR_NO_EVENT_EXCLUDING_UNAVAILABLE",
            "planned_session_count": self.planned_session_count,
            "sampled_session_count": self.sampled_session_count,
            "required_sample_count": (self.planned_session_count + 49) // 50,
            "plan_sha256": self.plan_sha256,
            "sample_part_sha256": self.sample_part_sha256,
            "sampled_days": [dict(ticker=row.ticker, session=row.session,
                                  day_type=row.day_type, event_count=row.event_count,
                                  skip_reason=row.skip_reason) for row in self.sampled_days],
            "adapter_moments": [{
                "playbook": row.inputs.playbook, "ticker": row.inputs.ticker,
                "session": row.inputs.session,
                "moment": row.inputs.decision_moments[0].isoformat(),
                "fields": [{"path": field.path, "value": json.loads(field.value_json),
                            "unit": field.unit} for field in row.inspected_fields],
            } for row in self.adapter_moments],
            "inspection_passed": True,
            "full_run_released": False,
            "held_out_opened": False,
            "gap_dependent_rules": "OFF_UNTESTED",
        }


def inspect_retained_candidate_sample(
    part: RetainedTrainingCandidatePart,
    sampled_days: Sequence[CandidateSampleDay],
    adapter_moments: Sequence[CandidateSampleMoment],
    *,
    planned_sessions: Sequence[tuple[str, str]],
    sample_run: RetainedFirstFourCandidateRun,
) -> RetainedCandidateSampleInspection:
    """Bind the D-116 inspection to its full job and exact sampled decisions.

    Sample size rounds 2% up to a whole ticker-session. The supplied full-job
    inventory is committed in the result; its real-file provenance remains a
    supervisor obligation. A zero-event degraded session still needs actual
    UNAVAILABLE decisions in the sample, not an unrelated annotation.
    """
    if not isinstance(part, RetainedTrainingCandidatePart):
        raise RecordError("candidate sample part is required")
    if build_retained_training_candidate_part(sample_run) != part:
        raise RecordError("sample run does not reproduce the supplied part")
    plan = tuple(planned_sessions)
    if (not plan or len(set(plan)) != len(plan)
            or {ticker for ticker, _session in plan} != set(TRAINING_TICKERS)):
        raise RecordError("full sample plan needs unique sessions across all nine training names")
    days = tuple(sampled_days)
    keys = {(row.ticker, row.session) for row in days}
    if not days or len(keys) != len(days):
        raise RecordError("sample days must be non-empty and unique")
    if keys != set(part.sessions) or not keys.issubset(plan):
        raise RecordError("sample days must exactly match the part and belong to the full plan")
    if len(days) != (len(plan) + 49) // 50:
        raise RecordError("sample must contain the rounded-up 2% of planned ticker-sessions")
    if {row.ticker for row in days} != set(TRAINING_TICKERS):
        raise RecordError("sample must be spread across all nine training names")
    if any(row.day_type not in DAY_TYPES or type(row.event_count) is not int
           or row.event_count < 0 for row in days):
        raise RecordError("sample day type or event count is invalid")
    if {row.day_type for row in days} != set(DAY_TYPES):
        raise RecordError("sample must include normal, half-day and degraded sessions")
    usable = tuple(event for event in sample_run.events if event.status != "UNAVAILABLE")
    for row in days:
        measured = sum(event.ticker == row.ticker and event.session == row.session for event in usable)
        if row.event_count != measured:
            raise RecordError("sample event count differs from its session's usable decisions")
        if row.day_type == "DEGRADED":
            if row.event_count != 0 or row.skip_reason != "DEGRADED_SESSION":
                raise RecordError("degraded sample days must be explicitly skipped")
        elif row.event_count == 0 or row.skip_reason is not None:
            raise RecordError("normal and half-day sample rows need usable events")
        else:
            bounds = session_bounds(date.fromisoformat(row.session))
            if bounds is None:
                raise RecordError("sample day must be a trading session")
            expected_type = "HALF_DAY" if (bounds[1] - bounds[0]).total_seconds() < 23400 else "NORMAL"
            if row.day_type != expected_type:
                raise RecordError("sample day type differs from the session calendar")

    ticker_counts = tuple((ticker, sum(row.event_count for row in days if row.ticker == ticker))
                          for ticker in TRAINING_TICKERS)
    if any(count == 0 for _ticker, count in ticker_counts):
        raise RecordError("each assigned ticker needs usable sample events")
    playbook_counts = tuple((playbook, sum(event.playbook == playbook for event in usable))
                           for playbook in PLAYBOOKS)
    if any(count == 0 for _playbook, count in playbook_counts):
        raise RecordError("each playbook needs usable sample events")
    moments = tuple(adapter_moments)
    if len(moments) != len(PLAYBOOKS) or {row.inputs.playbook for row in moments} != set(PLAYBOOKS):
        raise RecordError("every playbook needs its own complete one-moment field inspection")
    for row in moments:
        value = row.inputs
        expected_fields = candidate_sample_fields(value)
        key = (value.ticker, value.session)
        if key not in keys or not any(event.playbook == value.playbook
                                     and (event.ticker, event.session) == key for event in usable):
            raise RecordError("adapter field inspection must belong to a usable sampled session")
        if (value.decision_moments[0] not in decision_moments(value.session)
                or value.disabled_rules != REQUIRED_DISABLED_RULES
                or (value.history.ticker, value.history.session) != key):
            raise RecordError("adapter field inspection has an invalid moment or scope")
        records = (*value.history.batch.bars, *value.trades, *value.quotes)
        ids = tuple(record.record_id for record in records)
        if (len(set(ids)) != len(ids) or set(ids) != set(value.source_record_ids)
                or any((record.metadata.instrument_id, record.metadata.session) != key for record in records)):
            raise RecordError("adapter field inspection has foreign or duplicate source records")
        source = next(entry for entry in part.source_sessions if entry[:2] == key)
        if (len(ids), _hash_values(sorted(ids))) != source[2:]:
            raise RecordError("adapter field inspection does not match the part's source identities")
        if (len({field.path for field in row.inspected_fields}) != len(row.inspected_fields)
                or tuple(sorted(row.inspected_fields, key=lambda field: field.path)) != expected_fields):
            raise RecordError("every adapter input field, value and exact unit must be inspected")
    return RetainedCandidateSampleInspection(
        SAMPLE_VERSION, ticker_counts, playbook_counts,
        tuple((day_type, sum(row.day_type == day_type for row in days)) for day_type in DAY_TYPES),
        len(plan), len(days), _hash_values(_canonical(key) for key in sorted(plan)),
        hashlib.sha256(_canonical(part.as_dict()).encode("utf-8")).hexdigest(),
        tuple(sorted(moments, key=lambda row: row.inputs.playbook)),
        tuple(sorted(days, key=lambda row: (row.ticker, row.session))),
    )


def build_retained_training_candidate_part(
    run: RetainedFirstFourCandidateRun,
) -> RetainedTrainingCandidatePart:
    """Reduce one non-empty, training-only run without retaining raw ids."""
    if not isinstance(run, RetainedFirstFourCandidateRun) or not run.events:
        raise RecordError("non-empty retained first-four candidate run is required")
    grouped: dict[tuple[str, str], list[object]] = {}
    for event in run.events:
        if event.status not in STATUSES:
            raise RecordError("candidate part has an unsupported decision status")
        if event.ticker not in TRAINING_TICKERS:
            raise RecordError("candidate part cannot contain a held-out ticker")
        if event.disabled_rules != REQUIRED_DISABLED_RULES:
            raise RecordError("candidate part cannot enable a D-104 gap-dependent rule")
        grouped.setdefault((event.ticker, event.session), []).append(event)

    source_sessions = []
    event_sessions = []
    for (ticker, session), events in sorted(grouped.items()):
        if {event.playbook for event in events} != set(PLAYBOOKS):
            raise RecordError("each candidate part session needs all first four playbooks")
        source_ids = events[0].retained_source_record_ids
        if (not source_ids or len(set(source_ids)) != len(source_ids)
                or any(event.retained_source_record_ids != source_ids for event in events[1:])):
            raise RecordError("playbooks must share one non-empty retained source set per session")
        source_sessions.append((ticker, session, len(source_ids), _hash_values(sorted(source_ids))))
        decisions = tuple(sorted(_canonical(_decision_projection(event)) for event in events))
        event_sessions.append((ticker, session, len(decisions), _hash_values(decisions)))

    tickers = tuple(ticker for ticker in TRAINING_TICKERS
                    if ticker in {key[0] for key in grouped})
    return RetainedTrainingCandidatePart(
        PART_VERSION,
        tickers,
        tuple(sorted(grouped)),
        tuple((playbook, status, sum(event.playbook == playbook and event.status == status
                                     for event in run.events))
              for playbook in PLAYBOOKS for status in STATUSES),
        tuple((ticker, status, sum(event.ticker == ticker and event.status == status
                                   for event in run.events))
              for ticker in tickers for status in STATUSES),
        tuple(source_sessions),
        tuple(event_sessions),
        REQUIRED_DISABLED_RULES,
    )


def merge_retained_training_candidate_parts(
    parts: Sequence[RetainedTrainingCandidatePart],
) -> RetainedTrainingCandidateRecord:
    """Merge disjoint ticker/session parts into the durable training-nine record."""
    if not parts or any(not isinstance(part, RetainedTrainingCandidatePart) for part in parts):
        raise RecordError("candidate parts are required")
    sessions = [row for part in parts for row in part.sessions]
    if len(set(sessions)) != len(sessions):
        raise RecordError("candidate parts overlap a ticker-session")
    if {ticker for ticker, _session in sessions} != set(TRAINING_TICKERS):
        raise RecordError("merged candidate parts must contain all nine training names")
    if any(part.disabled_rules != REQUIRED_DISABLED_RULES for part in parts):
        raise RecordError("candidate parts disagree on disabled rules")

    def total(rows, first, second):
        return sum(count for part in parts for row_first, row_second, count in rows(part)
                   if row_first == first and row_second == second)

    source_sessions = sorted(row for part in parts for row in part.source_sessions)
    event_sessions = sorted(row for part in parts for row in part.event_sessions)
    source_commitments = tuple(_canonical({
        "ticker": ticker, "session": session, "count": count, "sha256": sha256,
    }) for ticker, session, count, sha256 in source_sessions)
    event_commitments = tuple(_canonical({
        "ticker": ticker, "session": session, "count": count, "sha256": sha256,
    }) for ticker, session, count, sha256 in event_sessions)
    return RetainedTrainingCandidateRecord(
        RECORD_VERSION,
        CANDIDATE_RUN_VERSION,
        sum(count for _ticker, _session, count, _sha256 in event_sessions),
        len(sessions),
        tuple((playbook, status, total(lambda part: part.status_totals, playbook, status))
              for playbook in PLAYBOOKS for status in STATUSES),
        tuple((ticker, status, total(lambda part: part.ticker_totals, ticker, status))
              for ticker in TRAINING_TICKERS for status in STATUSES),
        sum(count for _ticker, _session, count, _sha256 in source_sessions),
        _hash_values(source_commitments),
        _hash_values(event_commitments),
        REQUIRED_DISABLED_RULES,
    )


__all__ = [
    "DAY_TYPES", "PART_VERSION", "SAMPLE_VERSION", "CandidateSampleDay",
    "CandidateSampleField", "CandidateSampleMoment", "candidate_sample_fields",
    "RetainedCandidateSampleInspection", "RetainedTrainingCandidatePart",
    "build_retained_training_candidate_part", "merge_retained_training_candidate_parts",
    "inspect_retained_candidate_sample",
]
