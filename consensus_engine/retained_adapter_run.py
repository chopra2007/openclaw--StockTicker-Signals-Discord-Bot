"""M9.1BA: call the #2-4 bar-native research adapters at each planned decision moment.

For every `DecisionPlanItem` from `retained_decision_moments` this calls the
existing adapters that need only bars: the `OR_FAILURE_REV` tape/close pair and the
`FIRST_PULLBACK_VWAP` last-trade and VWAP-level readers. It counts, per playbook
input and reason, how many moments were ready and how many were not. It sets no
entry, trade or result. `atr_1m`, VWAP slope/crosses, the quote decision and the
`HOD_COMP_RS` policy-driven inputs are not called and stay recorded gaps with
dependent rules off (D-104). Nothing is read from a provider.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from .first_pullback_vwap_research_adapter import (
    build_last_trade_from_research, build_vwap_context_from_research,
)
from .or_failure_rev_research_adapter import build_or_failure_rev_bar_inputs_from_research
from .retained_decision_moments import DecisionPlanItem
from .trade_alerts_models import RecordError

ADAPTER_RUN_VERSION = "M91BA_ADAPTER_RUN_V1"
READY = "READY"
NOT_CALLED = ("atr_1m", "vwap_slope", "vwap_crosses", "quote_decision", "hod_comp_rs_policy_inputs")


@dataclass(frozen=True)
class AdapterRunCounts:
    version: str
    moments_called: int
    ready: tuple[tuple[str, str, int], ...]      # (playbook, input, count)
    not_ready: tuple[tuple[str, str, str, int], ...]  # (playbook, input, reason, count)
    not_called: tuple[str, ...] = NOT_CALLED


def _tally(playbook: str, name: str, reason: str | None, ready: Counter, not_ready: Counter) -> None:
    if reason is None:
        ready[(playbook, name)] += 1
    else:
        not_ready[(playbook, name, reason)] += 1


def run_adapters(
    plan: tuple[DecisionPlanItem, ...], *, instrument_types: Mapping[str, str],
) -> AdapterRunCounts:
    ready: Counter = Counter()
    not_ready: Counter = Counter()
    called = 0
    for item in plan:
        kind = instrument_types.get(item.ticker)
        if kind is None:
            raise RecordError(f"no instrument type supplied for {item.ticker}")
        for moment in item.moments:
            called += 1
            prefix = f"{item.ticker}-{item.session}-{moment:%H%M}"
            if item.playbook == "OR_FAILURE_REV":
                out = build_or_failure_rev_bar_inputs_from_research(
                    record_id_prefix=prefix, evaluated_at=moment, symbol=item.ticker,
                    instrument_type=kind, minute_history=item.history.batch)
                reason = None if out.last_trade.price is not None else (
                    out.last_trade.missing_reason or "NO_PRICE")
                _tally(item.playbook, "tape_and_close", reason, ready, not_ready)
            elif item.playbook == "FIRST_PULLBACK_VWAP":
                last = build_last_trade_from_research(
                    record_id_prefix=prefix, evaluated_at=moment, symbol=item.ticker,
                    instrument_type=kind, minute_history=item.history.batch)
                _tally(item.playbook, "last_trade",
                       None if last.last_trade.price is not None
                       else (last.last_trade.missing_reason or "NO_PRICE"), ready, not_ready)
                ctx = build_vwap_context_from_research(
                    record_id=prefix, evaluated_at=moment, symbol=item.ticker,
                    instrument_type=kind, minute_history=item.history.batch).context
                _tally(item.playbook, "vwap_level",
                       None if ctx.level is not None else (ctx.missing_reason or "NO_LEVEL"),
                       ready, not_ready)
    return AdapterRunCounts(
        ADAPTER_RUN_VERSION, called,
        tuple((p, n, c) for (p, n), c in sorted(ready.items())),
        tuple((p, n, r, c) for (p, n, r), c in sorted(not_ready.items())))


__all__ = ["ADAPTER_RUN_VERSION", "AdapterRunCounts", "NOT_CALLED", "run_adapters"]
