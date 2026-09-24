"""M9.1DB retained request/step builders for the first two playbooks.

The builders below turn one isolated ``CandidateEventInput`` into the existing
canonical replay-step records for ``CRVOL_ORB5`` and ``HOD_COMP_RS``.  They use
only the retained session bars, trades and quotes already present on that
input.  Required non-market facts that are not present in the retained source
remain explicit unknowns, so these producers return ``UNAVAILABLE`` instead of
inventing a candidate or a no-event result.

This is the first bounded half of M9.1DB.  It does not calculate fills, returns
or supervised package results and it cannot open a held-out name.
"""

from __future__ import annotations

from dataclasses import dataclass

from .first_pullback_vwap_research_adapter import build_last_trade_from_research
from .hod_comp_rs_replay import HodCompRsReplayStep
from .orb5_replay import Orb5ReplayStep
from .orb5_research_adapter import build_orb5_bar_observations
from .retained_candidate_events import CandidateEventDecision, CandidateEventInput, Producer
from .retained_offline_producer_inputs import (
    RetainedOfflineProducerMoment, build_retained_offline_producer_inputs,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DB_RETAINED_FIRST_TWO_PRODUCERS_V1"
SUPPORTED_PLAYBOOKS = ("CRVOL_ORB5", "HOD_COMP_RS")
MISSING_REQUIRED_INPUTS = (
    "HALT_STATUS_UNAVAILABLE",
    "MACRO_BLACKOUT_UNAVAILABLE",
    "CATALYST_COVERAGE_UNAVAILABLE",
    "ATR_1M_UNAVAILABLE",
    "QUOTE_DECISION_UNAVAILABLE",
    "CONFIDENCE_UNAVAILABLE",
)


@dataclass(frozen=True)
class RetainedProducerRequest:
    """The exact canonical replay steps prepared for one retained session."""

    version: str
    playbook: str
    ticker: str
    session: str
    steps: tuple[Orb5ReplayStep | HodCompRsReplayStep, ...]
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]
    offline_inputs: tuple[RetainedOfflineProducerMoment, ...]


def _instrument_type(value: CandidateEventInput) -> str:
    bars = value.history.batch.bars
    kinds = {bar.metadata.instrument_type for bar in bars}
    if len(kinds) != 1 or next(iter(kinds)) not in ("EQUITY", "ETF"):
        raise RecordError("retained producer input needs one EQUITY or ETF instrument type")
    return next(iter(kinds))


def build_retained_first_two_request(value: CandidateEventInput) -> RetainedProducerRequest:
    """Build the existing replay-step type for one supported retained producer."""
    if not isinstance(value, CandidateEventInput):
        raise RecordError("producer input must be CandidateEventInput")
    if value.playbook not in SUPPORTED_PLAYBOOKS:
        raise RecordError("this builder supports only CRVOL_ORB5 and HOD_COMP_RS")
    if not value.decision_moments:
        raise RecordError("retained producer input needs frozen decision moments")
    kind = _instrument_type(value)
    prefix = f"{RUN_VERSION}:{value.playbook}:{value.ticker}:{value.session}"
    offline_inputs = build_retained_offline_producer_inputs(value)
    offline_by_moment = {row.evaluated_at: row for row in offline_inputs}
    steps: list[Orb5ReplayStep | HodCompRsReplayStep] = []
    for moment in value.decision_moments:
        supplied = offline_by_moment[moment]
        if value.playbook == "CRVOL_ORB5":
            observations, _label = build_orb5_bar_observations(
                record_id_prefix=f"{prefix}:{moment.isoformat()}",
                instants=(moment,),
                symbol=value.ticker,
                instrument_type=kind,
                minute_history=value.history.batch,
            )
            steps.append(Orb5ReplayStep(
                evaluated_at=moment,
                status=supplied.status,
                observations=observations,
                last_trade=observations[0],
            ))
        else:
            last = build_last_trade_from_research(
                record_id_prefix=f"{prefix}:{moment.isoformat()}",
                evaluated_at=moment,
                symbol=value.ticker,
                instrument_type=kind,
                minute_history=value.history.batch,
            ).last_trade
            steps.append(HodCompRsReplayStep(
                evaluated_at=moment,
                status=supplied.status,
                observations=(last,),
                last_trade=last,
            ))
    observed_missing = {reason for row in offline_inputs for reason in row.missing_required_inputs}
    missing = tuple(reason for reason in MISSING_REQUIRED_INPUTS if reason in observed_missing)
    return RetainedProducerRequest(
        RUN_VERSION,
        value.playbook,
        value.ticker,
        value.session,
        tuple(steps),
        value.source_record_ids,
        missing,
        offline_inputs,
    )


def _producer(value: CandidateEventInput) -> tuple[CandidateEventDecision, ...]:
    request = build_retained_first_two_request(value)
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


def retained_first_two_producers() -> dict[str, Producer]:
    """Return the concrete producers for the first bounded M9.1DB half."""
    return {playbook: _producer for playbook in SUPPORTED_PLAYBOOKS}


__all__ = [
    "MISSING_REQUIRED_INPUTS",
    "RUN_VERSION",
    "SUPPORTED_PLAYBOOKS",
    "RetainedProducerRequest",
    "build_retained_first_two_request",
    "retained_first_two_producers",
]
