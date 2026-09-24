"""M9.1BA/M9.1BY/M9.1BZ: call the #1-4 bar-native adapters at planned moments.

For every `DecisionPlanItem` from `retained_decision_moments` this calls the
existing adapters that need only bars: the `OR_FAILURE_REV` tape/close pair and the
`FIRST_PULLBACK_VWAP` last-trade and VWAP-level readers, plus the existing
`HOD_COMP_RS` RS, compression and five bar-role readers, and the `CRVOL_ORB5`
opening-range and latest-bar observation readers. It counts, per
playbook input and reason, how many moments were ready and how many were not.
It sets no entry, trade or result. Inputs unavailable from retained minute bars
stay named gaps with their dependent rules off (D-104). Nothing is read from a
provider.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Mapping

from .first_pullback_vwap_research_adapter import (
    build_last_trade_from_research, build_vwap_context_from_research,
)
from .hod_comp_rs_research_adapter import build_rs_trend_snapshot_from_research
from .hod_comp_rs_role_adapter import build_hod_comp_rs_role_snapshot_from_research
from .hod_compression import CompressionPolicy
from .hod_compression_research_adapter import build_hod_compression_snapshot_from_research
from .or_failure_rev_research_adapter import build_or_failure_rev_bar_inputs_from_research
from .orb5_research_adapter import build_orb5_bar_observations, opening_range_from_bars
from .retained_decision_moments import DecisionPlanItem
from .rs_trend_eligibility import RsWindowPolicy
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_bounds, session_date_at

ADAPTER_RUN_VERSION = "M91BZ_ADAPTER_RUN_V4"
READY = "READY"
NOT_CALLED = (
    "atr_1m", "vwap_slope", "vwap_crosses", "quote_decision",
    "hod_comp_rs_quote_and_status_inputs", "orb5_tape_intensity",
    "orb5_quote_and_status_inputs", "orb5_bar_finality",
)

_RS_POLICY = RsWindowPolicy(
    version="M03C_HOD_COMP_RS_RS15_V1",
    definition_reference="M0_3C_DEFINITION_PACKET.md sections 1 and 3",
    benchmark_symbol="SPY",
    lookback_bars=15,
    return_basis="FIRST_BAR_OPEN",
)
_COMPRESSION_POLICY = CompressionPolicy(
    version="M03C_HOD_COMP_RS_COMPRESSION_3X7_V1",
    definition_reference="M0_3C_DEFINITION_PACKET.md sections 1 and 4",
    recent_bars=3,
    prior_bars=7,
    prior_includes_recent=False,
)


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


def _feature(snapshot, name: str):
    return next(item for item in snapshot.features if item.name == name)


def _tally_feature(playbook: str, name: str, feature, ready: Counter,
                   not_ready: Counter) -> None:
    _tally(playbook, name,
           None if feature.value is not None else (feature.missing_reason or "NO_VALUE"),
           ready, not_ready)


def _opening_rs_history(batch, moment):
    """Fix the required intervals, while keeping availability evaluated as of now.

    The shared RS reader is rolling. Giving it only the opening request keeps
    later minutes out without substituting a later bar for a missing early one.
    Retain every overlapping revision so the reader can select the as-of version.
    """
    bounds = session_bounds(session_date_at(moment))
    if batch is None or bounds is None or batch.request.interval != "1m":
        return batch
    opened = as_utc(bounds[0])
    ended = opened + timedelta(minutes=_RS_POLICY.required_bars)
    return replace(
        batch, request=replace(batch.request, start=opened, end=ended),
        bars=tuple(bar for bar in batch.bars
                   if bar.start_time < ended and bar.end_time > opened),
    )


def _run_hod_comp_rs(item: DecisionPlanItem, moment, kind: str, prefix: str,
                     histories, ready: Counter, not_ready: Counter) -> None:
    stock = item.history.batch
    benchmark_item = histories.get((_RS_POLICY.benchmark_symbol, item.session))
    if item.ticker == _RS_POLICY.benchmark_symbol:
        _tally(item.playbook, "rs_15m", "SELF_BENCHMARK_UNDEFINED", ready, not_ready)
        _tally(item.playbook, "rs_warmup", "SELF_BENCHMARK_UNDEFINED", ready, not_ready)
    else:
        rs_stock = _opening_rs_history(stock, moment)
        rs_benchmark = _opening_rs_history(
            None if benchmark_item is None else benchmark_item.batch, moment)
        rs = build_rs_trend_snapshot_from_research(
            record_id=prefix + "-rs", evaluated_at=moment, symbol=item.ticker,
            instrument_type=kind, minute_history=rs_stock,
            benchmark_history=rs_benchmark,
            policy=_RS_POLICY,
        ).snapshot
        rs_value = _feature(rs, "RS_LOOKBACK_V1")
        warmup = _feature(rs, "RS_WARMUP_COMPLETE_V1")
        reason = rs_value.missing_reason
        # M0.3C rejects a revised required bar, even when the shared research
        # reader can calculate its return. Future and out-of-window revisions
        # are not selected inputs and cannot alter this count.
        for batch, revised_reason in (
            (rs_stock, "RS_WINDOW_REVISED"),
            (rs_benchmark, "BENCHMARK_RS_WINDOW_REVISED"),
        ):
            if reason is None and batch is not None and any(
                bar.record_id in rs.input_record_ids and bar.metadata.revision > 0
                for bar in batch.bars
            ):
                reason = revised_reason
        _tally(item.playbook, "rs_15m", reason, ready, not_ready)
        _tally(item.playbook, "rs_warmup",
               reason if warmup.value == 1 else (reason or "RS_WARMUP_INCOMPLETE"),
               ready, not_ready)

    compression = build_hod_compression_snapshot_from_research(
        record_id=prefix + "-compression", evaluated_at=moment, symbol=item.ticker,
        instrument_type=kind, minute_history=stock, policy=_COMPRESSION_POLICY,
        reference_frozen_at=moment - timedelta(minutes=_COMPRESSION_POLICY.recent_bars),
        atr_1m=None,
    ).snapshot
    reference = _feature(compression, "REFERENCE_EXTREME_COMPLETE_V1")
    reference_value = _feature(compression, "REFERENCE_HOD_V1")
    window = _feature(compression, "COMPRESSION_COMPLETE_V1")
    ratio = _feature(compression, "COMPRESSION_RANGE_RATIO_V1")
    _tally(item.playbook, "reference_extreme",
           None if reference.value == 1 else (reference_value.missing_reason or "INCOMPLETE_REFERENCE"),
           ready, not_ready)
    _tally(item.playbook, "compression",
           None if window.value == 1 and ratio.value is not None
           else (ratio.missing_reason or "INCOMPLETE_COMPRESSION"), ready, not_ready)

    roles = build_hod_comp_rs_role_snapshot_from_research(
        record_id=prefix + "-roles", evaluated_at=moment, symbol=item.ticker,
        instrument_type=kind, opening_history=stock, daily_history=None,
        minute_history=stock, opening_trade=None,
    ).snapshot
    for input_name, feature_name in (
        ("median_dollar_volume", "RESEARCH_MEDIAN_DOLLAR_VOLUME_V1"),
        ("rvol", "RESEARCH_RVOL_OPEN5_MEAN20_V1"),
        ("open_return", "RESEARCH_OPEN_RETURN_V1"),
        ("daily_atr_pct", "RESEARCH_DAILY_ATR_PCT_V1"),
        ("session_vwap", "RESEARCH_SESSION_VWAP_V1"),
    ):
        _tally_feature(item.playbook, input_name, _feature(roles, feature_name), ready, not_ready)


def run_adapters(
    plan: tuple[DecisionPlanItem, ...], *, instrument_types: Mapping[str, str],
) -> AdapterRunCounts:
    ready: Counter = Counter()
    not_ready: Counter = Counter()
    called = 0
    histories = {(item.ticker, item.session): item.history for item in plan}
    for item in plan:
        kind = instrument_types.get(item.ticker)
        if kind is None:
            raise RecordError(f"no instrument type supplied for {item.ticker}")
        for moment in item.moments:
            called += 1
            prefix = f"{item.ticker}-{item.session}-{moment:%H%M}"
            if item.playbook == "HOD_COMP_RS":
                _run_hod_comp_rs(item, moment, kind, prefix, histories, ready, not_ready)
            elif item.playbook == "CRVOL_ORB5":
                opening = opening_range_from_bars(
                    symbol=item.ticker, instrument_type=kind, minutes=5,
                    minute_history=item.history.batch)
                _tally(item.playbook, "opening_range_5m", opening.missing_reason,
                       ready, not_ready)
                observations, _ = build_orb5_bar_observations(
                    record_id_prefix=prefix, instants=(moment,), symbol=item.ticker,
                    instrument_type=kind, minute_history=item.history.batch)
                observation = observations[0]
                _tally(item.playbook, "latest_bar_observation",
                       None if observation.price is not None else (
                           observation.missing_reason or "NO_PRICE"), ready, not_ready)
            elif item.playbook == "OR_FAILURE_REV":
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
