"""M9.1BB: one offline entry point from retained minute files to adapter counts.

Chains the M9.1AY loader, the M9.1AZ decision-moment plan and the M9.1BA adapter run
for the named ticker-days and returns counts only, with the skipped and no-prior lists.
It does not choose files or tickers, sets no entry and produces no trade or result.
Reading real retained files needs a separate, explicitly assigned run; nothing here
calls it. Gaps in `NOT_CALLED` stay recorded with dependents off (D-104).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .core17_bar_loader import open_core17_ohlcv_1m_file
from .historical_bars import HistoryConventions
from .retained_adapter_run import AdapterRunCounts, run_adapters
from .retained_decision_moments import PLAYBOOKS, plan_decision_moments
from .retained_history_batches import Opener, load_retained_history_batches

COUNT_RUN_VERSION = "M91BB_RETAINED_COUNT_RUN_V1"


@dataclass(frozen=True)
class RetainedCountRun:
    version: str
    counts: AdapterRunCounts
    skipped: tuple[tuple[str, str, str], ...]
    without_prior_session: tuple[tuple[str, str], ...]
    sessions_used: int


def run_retained_counts(
    job_dir: Path, filenames: Iterable[str], *, pairs: Iterable[tuple[str, str]],
    conventions: HistoryConventions, instrument_types: Mapping[str, str],
    playbooks: tuple[str, ...] = PLAYBOOKS, opener: Opener = open_core17_ohlcv_1m_file,
) -> RetainedCountRun:
    batches = load_retained_history_batches(
        job_dir, filenames, pairs=pairs, conventions=conventions, opener=opener)
    plan = plan_decision_moments(batches, playbooks=playbooks)
    counts = run_adapters(plan, instrument_types=instrument_types)
    return RetainedCountRun(COUNT_RUN_VERSION, counts, batches.skipped,
                            batches.without_prior_session, len(batches.histories))


__all__ = ["COUNT_RUN_VERSION", "RetainedCountRun", "run_retained_counts"]
