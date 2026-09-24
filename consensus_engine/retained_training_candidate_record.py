"""M9.1DG retained training-nine candidate-boundary record.

This module runs the accepted first-four candidate boundary on supplied retained
training inputs and writes a small immutable summary.  The summary commits to
the complete event stream and complete source-identity set with SHA-256 hashes;
it does not copy the retained market records into the result file.

No fill, return, supervised package, held-out result or later search stage is
calculated here.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence

from .retained_first_four_candidate_run import (
    RUN_VERSION as CANDIDATE_RUN_VERSION,
    run_retained_first_four_candidates,
)
from .retained_history_batches import RetainedHistoryBatches
from .retained_quote_trade_reader import RetainedQuoteTradeRecord
from .trade_alerts_models import RecordError

RECORD_VERSION = "M91DH_RETAINED_TRAINING_CANDIDATE_RECORD_V2"
STATUSES = ("CANDIDATE", "NO_EVENT", "UNAVAILABLE")

@dataclass(frozen=True)
class RetainedTrainingCandidateRecord:
    version: str
    candidate_run_version: str
    event_count: int
    session_count: int
    status_totals: tuple[tuple[str, str, int], ...]
    ticker_totals: tuple[tuple[str, str, int], ...]
    source_identity_count: int
    source_identity_sha256: str
    event_stream_sha256: str
    disabled_rules: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "candidate_run_version": self.candidate_run_version,
            "event_count": self.event_count,
            "session_count": self.session_count,
            "status_totals": [
                {"playbook": playbook, "status": status, "count": count}
                for playbook, status, count in self.status_totals
            ],
            "ticker_totals": [
                {"ticker": ticker, "status": status, "count": count}
                for ticker, status, count in self.ticker_totals
            ],
            "source_identity_count": self.source_identity_count,
            "source_identity_sha256": self.source_identity_sha256,
            "event_stream_sha256": self.event_stream_sha256,
            "disabled_rules": list(self.disabled_rules),
            "held_out_opened": False,
            "fills_or_returns_calculated": False,
            "supervised_package_calculated": False,
            "gap_dependent_rules": "OFF_UNTESTED",
        }


def build_retained_training_candidate_record(
    retained: RetainedHistoryBatches,
    quote_trade_records: Sequence[RetainedQuoteTradeRecord],
) -> RetainedTrainingCandidateRecord:
    """Run and summarize the concrete first-four training-only boundary."""
    run = run_retained_first_four_candidates(retained, quote_trade_records)
    # Local import avoids a module cycle: the part type returns this record type.
    from .retained_training_candidate_parts import (
        build_retained_training_candidate_part,
        merge_retained_training_candidate_parts,
    )
    return merge_retained_training_candidate_parts((
        build_retained_training_candidate_part(run),
    ))


def write_retained_training_candidate_record(
    path: Path, record: RetainedTrainingCandidateRecord,
) -> None:
    """Write once, allow an identical retry, and reject a conflicting retry."""
    if not isinstance(record, RetainedTrainingCandidateRecord):
        raise RecordError("retained training candidate record is required")
    rendered = json.dumps(record.as_dict(), sort_keys=True, indent=2) + "\n"
    try:
        with Path(path).open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    except FileExistsError:
        if Path(path).read_text(encoding="utf-8") != rendered:
            raise RecordError("retained training candidate record conflicts with existing output")


__all__ = [
    "RECORD_VERSION", "STATUSES", "RetainedTrainingCandidateRecord",
    "build_retained_training_candidate_record", "write_retained_training_candidate_record",
]
