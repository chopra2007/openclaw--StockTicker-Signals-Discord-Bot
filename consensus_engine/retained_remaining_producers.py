"""M9.1DC retained producer boundary for the remaining two playbooks.

The retained source has bars, trades and quotes.  M9.1DD now scans those exact
records for a frozen M0.3D ended ORB parent and builds the canonical handoff and
reversal step when one exists.  The M0.3E impulse parent remains unavailable.
Every missing parent or later required input stays explicit; no record is
fabricated merely to make a replay step constructible.

No fill, return or supervised package result is calculated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .first_pullback_vwap_replay import PullbackReplayStep
from .or_failure_handoff import HandoffRequest
from .or_failure_rev_replay import OrFailureRevReplayStep
from .retained_candidate_events import CandidateEventDecision, CandidateEventInput, Producer
from .retained_offline_producer_inputs import (
    RetainedOfflineProducerMoment, build_retained_offline_producer_inputs,
)
from .retained_or_failure_parent_scan import TradeCoverage, scan_retained_or_failure_parents
from .retained_first_pullback_parent_scan import (
    ImpulseScanEvidence, scan_retained_first_pullback_parents,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DC_RETAINED_REMAINING_PRODUCERS_V1"
SUPPORTED_PLAYBOOKS = ("OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")
OR_FAILURE_MISSING_INPUTS = (
    "ENDED_ORB_ATTEMPT_UNAVAILABLE",
    "ORB_HANDOFF_POLICY_UNAVAILABLE",
    "QUOTE_DECISION_UNAVAILABLE",
    "CONFIDENCE_UNAVAILABLE",
)


@dataclass(frozen=True)
class RetainedRemainingProducerRequest:
    """Canonical step slots and their retained source boundary.

    Empty step tuples are deliberate when the matching frozen parent cannot be
    derived from the retained records.
    """

    version: str
    playbook: str
    ticker: str
    session: str
    decision_moments: tuple[datetime, ...]
    handoff_requests: tuple[HandoffRequest, ...]
    reversal_steps: tuple[OrFailureRevReplayStep, ...]
    pullback_steps: tuple[PullbackReplayStep, ...]
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]
    offline_inputs: tuple[RetainedOfflineProducerMoment, ...]


def build_retained_remaining_request(
    value: CandidateEventInput, *, trade_coverage: tuple[TradeCoverage, ...] = (),
    impulse_evidence: tuple[ImpulseScanEvidence, ...] = (),
) -> RetainedRemainingProducerRequest:
    """Record why a canonical remaining-playbook step cannot yet be built."""
    if not isinstance(value, CandidateEventInput):
        raise RecordError("producer input must be CandidateEventInput")
    if value.playbook not in SUPPORTED_PLAYBOOKS:
        raise RecordError("this builder supports only OR_FAILURE_REV and FIRST_PULLBACK_VWAP")
    if not value.decision_moments:
        raise RecordError("retained producer input needs frozen decision moments")
    bars = value.history.batch.bars
    kinds = {bar.metadata.instrument_type for bar in bars}
    if len(kinds) != 1 or next(iter(kinds)) not in ("EQUITY", "ETF"):
        raise RecordError("retained producer input needs one EQUITY or ETF instrument type")
    offline_inputs = build_retained_offline_producer_inputs(value)
    if value.playbook == "OR_FAILURE_REV":
        selected = scan_retained_or_failure_parents(value, trade_coverage=trade_coverage)
        handoffs = selected.handoff_requests
        reversal_steps = selected.reversal_steps
        missing = (("QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")
                   if reversal_steps else (*OR_FAILURE_MISSING_INPUTS, *selected.unavailable_reasons))
    else:
        handoffs = ()
        reversal_steps = ()
        selected = scan_retained_first_pullback_parents(value, evidence=impulse_evidence)
        missing = (*selected.unavailable_reasons,
                   "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")
    return RetainedRemainingProducerRequest(
        RUN_VERSION,
        value.playbook,
        value.ticker,
        value.session,
        value.decision_moments,
        handoffs,
        reversal_steps,
        selected.pullback_steps if value.playbook == "FIRST_PULLBACK_VWAP" else (),
        value.source_record_ids,
        missing,
        offline_inputs,
    )


def _producer(value: CandidateEventInput) -> tuple[CandidateEventDecision, ...]:
    request = build_retained_remaining_request(value)
    missing = list(request.missing_required_inputs)
    if not value.trades:
        missing.append("RETAINED_TRADES_UNAVAILABLE")
    if not value.quotes:
        missing.append("RETAINED_QUOTES_UNAVAILABLE")
    return (CandidateEventDecision(
        status="UNAVAILABLE",
        producer_version=RUN_VERSION,
        reason="|".join(missing),
        input_record_ids=(),
    ),)


def retained_remaining_producers() -> dict[str, Producer]:
    """Return concrete, fail-closed producers for playbooks three and four."""
    return {playbook: _producer for playbook in SUPPORTED_PLAYBOOKS}


__all__ = [
    "OR_FAILURE_MISSING_INPUTS",
    "RUN_VERSION",
    "SUPPORTED_PLAYBOOKS",
    "RetainedRemainingProducerRequest",
    "build_retained_remaining_request",
    "retained_remaining_producers",
]
