"""M9.1ER development-only readiness counts for the audited saved bars.

This boundary accepts already-built development-session histories, checks them
against the M9.1EQ input binding, and calls the existing first-four adapter
runner.  It reports availability counts only.  It cannot accept a held-out
ticker, open a held-out result, calculate a return, or release anything live.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from .retained_adapter_run import ADAPTER_RUN_VERSION, run_adapters
from .retained_decision_moments import PLAYBOOKS, plan_decision_moments
from .retained_history_batches import RetainedHistoryBatches
from .saved_market_data_binding import BINDING_VERSION, ENABLED_IF_COMPLETE, OFF_UNTESTED
from .search_run_config import HELD_OUT_TICKERS, TRAINING_TICKERS
from .trade_alerts_models import RecordError


READINESS_VERSION = "M91ER_SAVED_BAR_READINESS_V1"


@dataclass(frozen=True)
class SavedReadinessCounts:
    version: str
    binding_version: str
    adapter_run_version: str
    development_tickers: tuple[str, ...]
    development_dates: tuple[str, ...]
    missing_tickers: tuple[str, ...]
    sessions_requested: int
    sessions_used: int
    skipped: tuple[tuple[str, str, str], ...]
    moments_called: int
    enabled_input_counts: tuple[dict[str, Any], ...]
    disabled_inputs: tuple[dict[str, Any], ...]
    d104_gaps: dict[str, dict[str, str]]
    held_out_evaluation: str = "CLOSED"
    return_calculated: bool = False
    promotion_or_live_release: bool = False
    network_used: bool = False
    spend_usd: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "binding_version": self.binding_version,
            "adapter_run_version": self.adapter_run_version,
            "development_tickers": list(self.development_tickers),
            "development_dates": list(self.development_dates),
            "missing_tickers": list(self.missing_tickers),
            "sessions_requested": self.sessions_requested,
            "sessions_used": self.sessions_used,
            "skipped": [list(row) for row in self.skipped],
            "moments_called": self.moments_called,
            "enabled_input_counts": list(self.enabled_input_counts),
            "disabled_inputs": list(self.disabled_inputs),
            "d104_gaps": self.d104_gaps,
            "held_out_evaluation": self.held_out_evaluation,
            "return_calculated": self.return_calculated,
            "promotion_or_live_release": self.promotion_or_live_release,
            "network_used": self.network_used,
            "spend_usd": self.spend_usd,
        }


def _binding_rows(binding: Mapping[str, Any], name: str) -> tuple[dict[str, Any], ...]:
    rows = binding.get(name)
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise RecordError(f"binding {name} must be a list of objects")
    return tuple(dict(row) for row in rows)


def count_saved_bar_readiness(
    binding: Mapping[str, Any], batches: RetainedHistoryBatches, *,
    development_dates: tuple[str, ...], instrument_types: Mapping[str, str],
) -> SavedReadinessCounts:
    """Count only M9.1EQ-enabled inputs over the frozen training-name scope."""
    if binding.get("version") != BINDING_VERSION:
        raise RecordError("saved-bar binding version mismatch")
    if binding.get("adapter_run_version") != ADAPTER_RUN_VERSION:
        raise RecordError("saved-bar binding adapter version mismatch")
    if binding.get("held_out_evaluation", {}).get("status") != "CLOSED":
        raise RecordError("held-out evaluation must remain closed")
    if not development_dates or tuple(sorted(set(development_dates))) != development_dates:
        raise RecordError("development dates must be a non-empty sorted unique tuple")
    if set(instrument_types) != set(TRAINING_TICKERS):
        raise RecordError("instrument types must name exactly the frozen training tickers")
    if set(instrument_types) & set(HELD_OUT_TICKERS):
        raise RecordError("held-out ticker cannot enter development readiness counts")
    if any(history.ticker not in TRAINING_TICKERS for history in batches.histories):
        raise RecordError("saved histories contain a non-training ticker")
    if any(history.session not in development_dates for history in batches.histories):
        raise RecordError("saved histories contain a non-development date")

    enabled = _binding_rows(binding, "enabled_inputs")
    disabled = _binding_rows(binding, "disabled_inputs")
    if any(row.get("status") != ENABLED_IF_COMPLETE for row in enabled):
        raise RecordError("enabled input binding status mismatch")
    if any(row.get("status") != OFF_UNTESTED for row in disabled):
        raise RecordError("disabled input binding status mismatch")

    plan = plan_decision_moments(batches, playbooks=PLAYBOOKS)
    raw = run_adapters(plan, instrument_types=instrument_types)
    ready = {(playbook, name): count for playbook, name, count in raw.ready}
    reasons: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for playbook, name, reason, count in raw.not_ready:
        reasons[(playbook, name)].append({"reason": reason, "count": count})
    counts = []
    for row in enabled:
        key = (row["playbook"], row["input"])
        counts.append({
            "playbook": key[0],
            "input": key[1],
            "ready": ready.get(key, 0),
            "not_ready": reasons.get(key, []),
        })

    present = {history.ticker for history in batches.histories}
    gaps = binding.get("d104_gaps")
    if not isinstance(gaps, Mapping) or any(
        not isinstance(value, Mapping)
        or value.get("status") != "GAP"
        or value.get("dependent_rules") != OFF_UNTESTED
        for value in gaps.values()
    ):
        raise RecordError("D-104 gaps must remain explicit and off")
    return SavedReadinessCounts(
        READINESS_VERSION, BINDING_VERSION, ADAPTER_RUN_VERSION,
        TRAINING_TICKERS, development_dates,
        tuple(ticker for ticker in TRAINING_TICKERS if ticker not in present),
        len(TRAINING_TICKERS) * len(development_dates), len(batches.histories),
        batches.skipped, raw.moments_called, tuple(counts), disabled,
        {name: dict(gaps[name]) for name in sorted(gaps)},
    )


__all__ = ["READINESS_VERSION", "SavedReadinessCounts", "count_saved_bar_readiness"]
