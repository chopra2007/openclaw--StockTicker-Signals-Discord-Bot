"""M9.1EA connection from bound retained candidates to the accepted fill model.

Only candidate rows may reach the D-106/D-107 fill boundary.  No-event and
unavailable rows are counted but never passed to the fill model.  This module
does not calculate returns, release result shards, or open held-out names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .fill_cost_model import FillCostPolicy, ModeledFill, model_fill
from .retained_first_four_evaluator_binding import (
    RUN_VERSION as BINDING_VERSION,
    RetainedFirstFourBoundDecision,
    RetainedFirstFourEvaluatorBinding,
)
from .trade_alerts_models import Quote, RecordError

RUN_VERSION = "M91EA_RETAINED_FIRST_FOUR_FILL_V1"
SessionKey = tuple[str, str]


@dataclass(frozen=True)
class RetainedFirstFourFillRow:
    """One bound candidate and its exact D-106/D-107 fill result."""

    decision: RetainedFirstFourBoundDecision
    fill: ModeledFill

    def as_dict(self) -> dict[str, object]:
        return {"decision": self.decision.as_dict(), "fill": self.fill.as_dict()}


@dataclass(frozen=True)
class RetainedFirstFourFillRun:
    """Candidate-only fills with every later release boundary sealed."""

    version: str
    binding_version: str
    rows: tuple[RetainedFirstFourFillRow, ...]
    candidate_count: int
    filled_count: int
    unfilled_count: int
    no_event_excluded_count: int
    unavailable_excluded_count: int
    return_calculated: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "binding_version": self.binding_version,
            "rows": [row.as_dict() for row in self.rows],
            "candidate_count": self.candidate_count,
            "filled_count": self.filled_count,
            "unfilled_count": self.unfilled_count,
            "no_event_excluded_count": self.no_event_excluded_count,
            "unavailable_excluded_count": self.unavailable_excluded_count,
            "return_calculated": self.return_calculated,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
        }


def _validate_binding(binding: RetainedFirstFourEvaluatorBinding) -> None:
    if (type(binding) is not RetainedFirstFourEvaluatorBinding
            or binding.version != BINDING_VERSION):
        raise RecordError("fill connection requires the accepted evaluator binding")
    if any((binding.candidate_released, binding.fill_calculated,
            binding.return_calculated, binding.result_shard_released,
            binding.held_out_opened)):
        raise RecordError("evaluator binding opened a later release boundary")
    if (binding.candidate_count != sum(row.status == "CANDIDATE" for row in binding.rows)
            or binding.no_event_count != sum(row.status == "NO_EVENT" for row in binding.rows)
            or binding.unavailable_count != sum(row.status == "UNAVAILABLE" for row in binding.rows)):
        raise RecordError("evaluator binding counts do not match its rows")
    keys = tuple((row.playbook, row.ticker, row.session) for row in binding.rows)
    if len(set(keys)) != len(keys):
        raise RecordError("evaluator binding contains duplicate decisions")
    for row in binding.rows:
        if row.retained_source_record_ids != row.evaluator_result.retained_source_record_ids:
            raise RecordError("bound decision and evaluator source identities do not match")
        if row.status == "CANDIDATE" and (
                row.alerted_at is None or row.direction not in ("LONG", "SHORT")):
            raise RecordError("bound candidate is incomplete")


def _group_market_records(
    trades: Sequence[Quote], quotes: Sequence[Quote], candidate_keys: set[SessionKey],
) -> dict[SessionKey, tuple[tuple[Quote, ...], tuple[Quote, ...]]]:
    grouped: dict[SessionKey, dict[str, list[Quote]]] = {}
    seen: set[str] = set()
    for kind, records in (("trades", trades), ("quotes", quotes)):
        for record in records:
            if type(record) is not Quote:
                raise RecordError("fill inputs must be canonical Quote records")
            key = (record.metadata.instrument_id, record.metadata.session)
            if key not in candidate_keys:
                raise RecordError("fill input does not match a bound candidate session")
            if record.record_id in seen:
                raise RecordError("duplicate fill input source identity")
            seen.add(record.record_id)
            grouped.setdefault(key, {"trades": [], "quotes": []})[kind].append(record)
    return {
        key: (tuple(values["trades"]), tuple(values["quotes"]))
        for key, values in grouped.items()
    }


def run_retained_first_four_fills(
    binding: RetainedFirstFourEvaluatorBinding,
    *,
    trades: Sequence[Quote],
    quotes: Sequence[Quote],
    policy: FillCostPolicy,
) -> RetainedFirstFourFillRun:
    """Send only exact bound candidates through the accepted fill boundary."""
    _validate_binding(binding)
    if type(policy) is not FillCostPolicy:
        raise RecordError("fill connection requires a FillCostPolicy")
    candidates = tuple(row for row in binding.rows if row.status == "CANDIDATE")
    candidate_keys = {(row.ticker, row.session) for row in candidates}
    grouped = _group_market_records(tuple(trades), tuple(quotes), candidate_keys)

    output: list[RetainedFirstFourFillRow] = []
    for decision in candidates:
        session_trades, session_quotes = grouped.get(
            (decision.ticker, decision.session), ((), ()),
        )
        source_ids = tuple(row.record_id for row in (*session_trades, *session_quotes))
        if not set(source_ids).issubset(decision.retained_source_record_ids):
            raise RecordError("fill input is outside the candidate retained source identities")
        assert decision.alerted_at is not None and decision.direction is not None
        fill = model_fill(
            alert_time=decision.alerted_at,
            direction=decision.direction,
            trades=session_trades,
            quotes=session_quotes,
            policy=policy,
        )
        output.append(RetainedFirstFourFillRow(decision, fill))

    rows = tuple(output)
    return RetainedFirstFourFillRun(
        RUN_VERSION,
        binding.version,
        rows,
        len(rows),
        sum(row.fill.status == "FILLED" for row in rows),
        sum(row.fill.status != "FILLED" for row in rows),
        binding.no_event_count,
        binding.unavailable_count,
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourFillRow",
    "RetainedFirstFourFillRun",
    "run_retained_first_four_fills",
]
