"""D-110 offline research accessor: PROVISIONAL bars, labelled, live contract untouched.

See `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md` section 59 (D-110).
`historical_bars.HistoryBatch.complete` and `.final_bars` keep their exact
present meaning; this module does not import from or modify anything a live
caller reads. It is the only place offline research may treat a `PROVISIONAL`
interval (finality unknown, per the open D-104 "corrections and finality" gap)
as usable. Every result carries `ResearchCoverage.label()`, which any research
output must include; a result missing that label is invalid under D-110.

No live path may import this module. No data is fetched, no parameter is
searched or chosen from a result, and no order/alert/delivery action occurs
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .historical_bars import HistoryBatch, HistoryCoverage, IntervalCoverage
from .trade_alerts_models import Bar, RecordError

_USABLE = ("FINAL", "NO_TRADE", "PROVISIONAL")


@dataclass(frozen=True)
class ResearchCoverage:
    """Research-only view of a `HistoryCoverage`, admitting `PROVISIONAL` bars.

    `bars` is ordered by interval start and includes `FINAL`/`NO_TRADE` bars
    unchanged plus every `PROVISIONAL` bar. `MISSING`/`CONFLICT`/`NOT_ENDED`/
    quality-and-convention-rejected intervals are excluded exactly as they are
    from the live `final_bars`, since D-110 only extends usability to the
    finality gap, not to any other rejection reason.
    """

    coverage: HistoryCoverage
    bars: tuple[Bar, ...]
    final_count: int
    no_trade_count: int
    provisional_count: int
    other_count: int

    @property
    def total_usable(self) -> int:
        return self.final_count + self.no_trade_count + self.provisional_count

    def label(self) -> dict[str, Any]:
        """The D-110 condition-2 label every research output must carry."""
        return {
            "finality": "RESEARCH_PROVISIONAL_PERMITTED",
            "decision": "D-110",
            "gap_field": "corrections and finality (was a bar/trade later revised or busted)",
            "total_usable_intervals": self.total_usable,
            "final_intervals": self.final_count,
            "no_trade_intervals": self.no_trade_count,
            "provisional_intervals": self.provisional_count,
            "other_excluded_intervals": self.other_count,
        }


def research_coverage_at(history: HistoryBatch, evaluated_at: datetime) -> ResearchCoverage:
    """Compute the D-110 research view for one `HistoryBatch` at one instant.

    Delegates entirely to the untouched `HistoryBatch.coverage_at` for the
    revision-selection, conflict and convention logic; only the final
    admission decision (which statuses count as usable) differs from
    `HistoryCoverage.final_bars`.
    """
    if not isinstance(history, HistoryBatch):
        raise RecordError("research coverage requires a HistoryBatch")
    coverage = history.coverage_at(evaluated_at)
    ordered: list[IntervalCoverage] = sorted(coverage.intervals, key=lambda item: item.interval.start)
    bars: list[Bar] = []
    final_count = no_trade_count = provisional_count = other_count = 0
    for item in ordered:
        if item.status == "FINAL":
            final_count += 1
        elif item.status == "NO_TRADE":
            no_trade_count += 1
        elif item.status == "PROVISIONAL":
            provisional_count += 1
        else:
            other_count += 1
            continue
        if item.bar is not None:
            bars.append(item.bar)
    return ResearchCoverage(
        coverage=coverage, bars=tuple(bars), final_count=final_count,
        no_trade_count=no_trade_count, provisional_count=provisional_count,
        other_count=other_count,
    )


__all__ = ["ResearchCoverage", "research_coverage_at"]
