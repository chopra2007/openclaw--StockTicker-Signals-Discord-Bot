"""M9.1DF concrete first-four retained candidate-event run.

This boundary connects the accepted first-four retained producers to the
isolated training-nine candidate-event builder.  The remaining two producers
run the accepted M0.3D and M0.3E parent scans before returning their exact
candidate, no-event or unavailable decision.

The run does not calculate fills, returns or supervised packages and cannot
open a held-out name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .retained_candidate_events import (
    RetainedCandidateEvent,
    build_retained_candidate_events,
)
from .retained_first_two_producers import retained_first_two_producers
from .retained_history_batches import RetainedHistoryBatches
from .retained_quote_trade_reader import RetainedQuoteTradeRecord
from .retained_remaining_producers import retained_remaining_producers
from .search_run_config import TRAINING_TICKERS

RUN_VERSION = "M91DF_RETAINED_FIRST_FOUR_CANDIDATE_RUN_V1"


@dataclass(frozen=True)
class RetainedFirstFourCandidateRun:
    """The exact decisions emitted by all four concrete retained producers."""

    version: str
    events: tuple[RetainedCandidateEvent, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "events": [event.as_dict() for event in self.events],
        }


def run_retained_first_four_candidates(
    retained: RetainedHistoryBatches,
    quote_trade_records: Sequence[RetainedQuoteTradeRecord],
    *,
    expected_tickers: Sequence[str] = TRAINING_TICKERS,
) -> RetainedFirstFourCandidateRun:
    """Run the concrete first-four producers over isolated retained inputs."""
    producers = {
        **retained_first_two_producers(),
        **retained_remaining_producers(),
    }
    events = build_retained_candidate_events(
        retained,
        quote_trade_records,
        producers=producers,
        expected_tickers=expected_tickers,
    )
    return RetainedFirstFourCandidateRun(RUN_VERSION, events)


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourCandidateRun",
    "run_retained_first_four_candidates",
]
