"""M4.7 pure offline option selection and first-four portfolio recording.

The functions in this module consume supplied canonical records.  They do not
fetch a chain, send an alert, size a position or change stock validity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo

from .trade_alerts_models import AlertCandidate, OptionQuote, OptionRecommendation, Quote, RecordError
from .utils.time_context import as_utc
from .cross_strategy_interaction import (
    ACCEPTED, BOTH_REGIONS, DeclaredTransition, InteractionPolicy, InteractionRequest,
    report_cross_strategy_interaction,
)
from .or_failure_handoff import FAILURE_FORMING, HandoffRequest, evaluate_or_failure_handoff
from .or_failure_rev import HANDOFF_GATE, PASS, ReversalRequest, evaluate_or_failure_rev
from .orb5_trigger import TriggerRequest, evaluate_orb5_trigger
from .trade_alerts_models import Bar, FeatureSnapshot, SessionRecord


OPTION_SCORE_VERSION = "OPTION_SCORE_INTRADAY_LONG_PREMIUM_V1"
ORB_POLICY = "CRVOL_ORB5_OPTION_POLICY_V1"
FIRST4_POLICIES = {
    "CRVOL_ORB5": ORB_POLICY,
    "HOD_COMP_RS": "HOD_COMP_RS_OPTION_ORDINARY_RESEARCH_V1",
    "OR_FAILURE_REV": "OR_FAILURE_REV_OPTION_ORDINARY_RESEARCH_V1",
    "FIRST_PULLBACK_VWAP": "FIRST_PULLBACK_VWAP_OPTION_ORDINARY_RESEARCH_V1",
}
CANDIDATE_KEY_VERSION = "M47_CANDIDATE_KEY_V1"
GROUP_POLICY_VERSION = "M47_FIRST4_GROUP_RECORDING_V1"
PACIFIC = ZoneInfo("America/Los_Angeles")


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise RecordError(f"{name} must be a number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise RecordError(f"{name} must be finite")
    return result


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(100), max(Decimal(0), value))


@dataclass(frozen=True)
class OptionRowEvidence:
    quote: OptionQuote
    reported_age_seconds: float
    units_proved: bool
    standard_deliverable_proved: bool
    greek_snapshot_proved: bool

    def __post_init__(self) -> None:
        if not isinstance(self.quote, OptionQuote):
            raise RecordError("option row requires an OptionQuote")
        age = _decimal(self.reported_age_seconds, "reported option age")
        if age < 0:
            raise RecordError("reported option age cannot be negative")
        for name in ("units_proved", "standard_deliverable_proved", "greek_snapshot_proved"):
            if type(getattr(self, name)) is not bool:
                raise RecordError(f"{name} must be true or false")


@dataclass(frozen=True)
class OptionChainEvidence:
    record_id: str
    candidate: AlertCandidate
    underlying_quote: Quote
    rows: tuple[OptionRowEvidence, ...]
    evaluated_at: datetime
    underlying_reported_age_seconds: float
    complete_eligible_chain: bool
    regular_session: bool
    same_day_membership: bool | None = None
    missing_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id:
            raise RecordError("chain record ID must be explicit")
        if not isinstance(self.candidate, AlertCandidate) or not isinstance(self.underlying_quote, Quote):
            raise RecordError("chain evidence requires canonical candidate and underlying quote")
        if not isinstance(self.rows, tuple) or any(not isinstance(row, OptionRowEvidence) for row in self.rows):
            raise RecordError("chain rows must be supplied option evidence")
        record_ids = [row.quote.record_id for row in self.rows]
        contract_ids = [row.quote.contract_id for row in self.rows]
        if len(record_ids) != len(set(record_ids)) or len(contract_ids) != len(set(contract_ids)):
            raise RecordError("one complete chain snapshot may contain one row per contract")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        if self.candidate.created_at > self.evaluated_at:
            raise RecordError("candidate is not yet available")
        if self.underlying_quote.metadata.available_time > self.evaluated_at:
            raise RecordError("underlying quote is not yet available")
        age = _decimal(self.underlying_reported_age_seconds, "reported underlying age")
        if age < 0:
            raise RecordError("reported underlying age cannot be negative")
        if type(self.complete_eligible_chain) is not bool or type(self.regular_session) is not bool:
            raise RecordError("chain completeness and session flags must be true or false")
        if self.same_day_membership is not None and type(self.same_day_membership) is not bool:
            raise RecordError("same-day membership must be true, false or null")
        if any(not isinstance(reason, str) or not reason for reason in self.missing_reasons):
            raise RecordError("missing reasons must be explicit")


@dataclass(frozen=True)
class OptionScore:
    option_quote_id: str
    contract_id: str
    score: Decimal
    spread_fit: Decimal
    delta_fit: Decimal
    liquidity_fit: Decimal
    dte_fit: Decimal
    iv_fit: Decimal
    greek_fit: Decimal
    spread_ratio: Decimal
    delta_distance: Decimal
    minimum_size: int
    volume: int
    open_interest: int
    same_week: bool

    def as_dict(self) -> dict[str, object]:
        return {name: (str(value) if isinstance(value, Decimal) else value)
                for name, value in self.__dict__.items()}


@dataclass(frozen=True)
class OptionSelection:
    recommendation: OptionRecommendation
    scores: tuple[OptionScore, ...]
    rejection_counts: tuple[tuple[str, int], ...]
    stock_validity_unchanged: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "recommendation": self.recommendation.as_dict(),
            "scores": [score.as_dict() for score in self.scores],
            "rejection_counts": [list(row) for row in self.rejection_counts],
            "stock_validity_unchanged": self.stock_validity_unchanged,
        }


def _unavailable(chain: OptionChainEvidence, policy: str, *reasons: str) -> OptionSelection:
    unique = tuple(dict.fromkeys(reason for reason in reasons if reason)) or ("OPTIONS_UNAVAILABLE",)
    return OptionSelection(OptionRecommendation(
        record_id=f"m47:options:{chain.candidate.record_id}", candidate_id=chain.candidate.record_id,
        status="UNAVAILABLE", ranked_at=chain.evaluated_at, reasons=unique,
        policy_version=policy,
    ), (), ())


def _effective_age(evaluated_at: datetime, provider_time: datetime | None,
                   reported_age: float) -> Decimal | None:
    if provider_time is None or provider_time > evaluated_at:
        return None
    elapsed = Decimal(str((evaluated_at - provider_time).total_seconds()))
    return max(elapsed, _decimal(reported_age, "reported age"))


def _score(row: OptionRowEvidence, underlying_mid: Decimal, median_iv: Decimal,
           current_date) -> OptionScore:
    quote = row.quote
    bid, ask = _decimal(quote.bid, "bid"), _decimal(quote.ask, "ask")
    midpoint = (bid + ask) / 2
    spread = (ask - bid) / midpoint
    delta = abs(_decimal(quote.delta, "delta"))
    oi, volume = int(quote.open_interest), int(quote.volume)
    minimum_size = min(int(quote.bid_size), int(quote.ask_size))
    iv = _decimal(quote.implied_volatility, "implied volatility")
    gamma, theta = _decimal(quote.gamma, "gamma"), _decimal(quote.theta, "theta")
    spread_fit = _clamp(Decimal(100) * (Decimal("0.10") - spread) / Decimal("0.10"))
    delta_fit = _clamp(Decimal(100) * (1 - abs(delta - Decimal("0.60")) / Decimal("0.10")))
    oi_fit = _clamp(Decimal(100) * (Decimal(oi) - 100) / 900)
    volume_fit = _clamp(Decimal(100) * Decimal(volume) / 1000)
    size_fit = _clamp(Decimal(100) * (Decimal(minimum_size) - 2) / 8)
    liquidity_fit = Decimal("0.40") * oi_fit + Decimal("0.40") * volume_fit + Decimal("0.20") * size_fit
    same_week = quote.expiry.isocalendar()[:2] == current_date.isocalendar()[:2]
    dte_fit = Decimal(100) if same_week else Decimal(0)
    iv_fit = _clamp(Decimal(100) * (1 - abs(iv / median_iv - 1)))
    if theta == 0:
        greek_fit = Decimal(100) if gamma > 0 else Decimal(0)
    else:
        x = Decimal("0.5") * gamma * (Decimal("0.01") * underlying_mid) ** 2 / abs(theta)
        greek_fit = Decimal(100) * x / (1 + x)
    score = (Decimal("0.30") * spread_fit + Decimal("0.25") * delta_fit
             + Decimal("0.25") * liquidity_fit + Decimal("0.10") * dte_fit
             + Decimal("0.05") * iv_fit + Decimal("0.05") * greek_fit)
    return OptionScore(quote.record_id, quote.contract_id, score, spread_fit, delta_fit,
                       liquidity_fit, dte_fit, iv_fit, greek_fit, spread,
                       abs(delta - Decimal("0.60")), minimum_size, volume, oi, same_week)


def select_option(chain: OptionChainEvidence) -> OptionSelection:
    """Apply the frozen first-four policy without changing the stock candidate."""
    candidate = chain.candidate
    policy = FIRST4_POLICIES.get(candidate.strategy_id)
    if policy is None:
        return _unavailable(chain, GROUP_POLICY_VERSION, "STRATEGY_OPTION_POLICY_UNAVAILABLE")
    if not chain.complete_eligible_chain:
        return _unavailable(chain, policy, *chain.missing_reasons, "ELIGIBLE_CHAIN_INCOMPLETE")
    if (not chain.regular_session or chain.underlying_quote.delayed is not False
            or chain.underlying_quote.status != "VALID"
            or chain.underlying_quote.metadata.quality != "VALID"):
        return _unavailable(chain, policy, "UNDERLYING_QUOTE_CONTEXT_UNAVAILABLE")
    if (chain.underlying_quote.metadata.instrument_id != candidate.metadata.instrument_id
            or chain.underlying_quote.metadata.session != candidate.metadata.session):
        return _unavailable(chain, policy, "UNDERLYING_IDENTITY_MISMATCH")
    evaluated = chain.evaluated_at
    underlying_time = chain.underlying_quote.quote_time
    underlying_age = _effective_age(evaluated, underlying_time, chain.underlying_reported_age_seconds)
    if underlying_age is None:
        return _unavailable(chain, policy, "UNDERLYING_QUOTE_TIME_UNAVAILABLE")
    if chain.underlying_quote.bid is None or chain.underlying_quote.ask is None:
        return _unavailable(chain, policy, "UNDERLYING_MIDPOINT_UNAVAILABLE")
    underlying_mid = (_decimal(chain.underlying_quote.bid, "underlying bid")
                      + _decimal(chain.underlying_quote.ask, "underlying ask")) / 2
    current_date = evaluated.astimezone(PACIFIC).date()
    wanted_right = "CALL" if candidate.direction == "LONG" else "PUT"
    references: dict[object, list[Decimal]] = {}
    fatal: list[str] = list(chain.missing_reasons)
    eligible: list[OptionRowEvidence] = []
    rejection: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejection[reason] = rejection.get(reason, 0) + 1

    for supplied in chain.rows:
        quote = supplied.quote
        if (quote.metadata.available_time > evaluated
                or quote.underlying_id != candidate.metadata.instrument_id
                or quote.metadata.session != candidate.metadata.session
                or quote.metadata.instrument_type != "OPTION"):
            fatal.append("OPTION_IDENTITY_OR_AVAILABILITY_UNAVAILABLE")
            continue
        if quote.option_type != wanted_right:
            continue
        dte = (quote.expiry - current_date).days
        if dte == 0 and candidate.strategy_id != "CRVOL_ORB5":
            reject("NOT_SELECTED_BY_THIS_RESEARCH_POLICY")
            continue
        if dte < (0 if candidate.strategy_id == "CRVOL_ORB5" else 1) or dte > 5:
            continue
        if quote.delta is None:
            fatal.append("POSSIBLY_ELIGIBLE_DELTA_MISSING")
            continue
        absolute_delta = abs(_decimal(quote.delta, "delta"))
        if not Decimal("0.50") <= absolute_delta <= Decimal("0.70"):
            continue
        if quote.non_standard is True:
            reject("NONSTANDARD_CONTRACT")
            continue
        expected_deliverable = f"100 SHARES {quote.underlying_id}"
        if (quote.multiplier != 100 or not supplied.standard_deliverable_proved
                or quote.deliverable != expected_deliverable):
            fatal.append("STANDARD_CONTRACT_PROOF_UNAVAILABLE")
            continue
        if (quote.implied_volatility is None
                or not isfinite(float(quote.implied_volatility))
                or quote.implied_volatility <= 0):
            fatal.append("MEDIAN_IV_REFERENCE_UNAVAILABLE")
            continue
        references.setdefault((quote.option_type, quote.expiry), []).append(_decimal(quote.implied_volatility, "IV"))
        required = (quote.bid, quote.ask, quote.bid_size, quote.ask_size, quote.open_interest,
                    quote.volume, quote.gamma, quote.theta)
        if any(value is None for value in required) or not all((
                supplied.units_proved, supplied.greek_snapshot_proved)):
            fatal.append("MANDATORY_IN_BAND_FIELD_OR_PROOF_MISSING")
            continue
        if (quote.status == "MISSING" or quote.delayed is None
                or quote.metadata.quality in ("UNAVAILABLE", "UNKNOWN")):
            fatal.append("OPTION_QUOTE_STATUS_UNAVAILABLE")
            continue
        if (quote.status != "VALID" or quote.delayed is True
                or quote.metadata.quality != "VALID"):
            reject("NONSTANDARD_OR_INVALID_QUOTE")
            continue
        bid, ask = _decimal(quote.bid, "bid"), _decimal(quote.ask, "ask")
        midpoint = (bid + ask) / 2
        quote_age = _effective_age(evaluated, quote.quote_time, supplied.reported_age_seconds)
        separation = (None if quote.quote_time is None or underlying_time is None else
                      Decimal(str(abs((quote.quote_time - underlying_time).total_seconds()))))
        same_day = dte == 0
        age_limit = Decimal(1) if same_day else Decimal(3)
        spread_limit = Decimal("0.05") if same_day else Decimal("0.10")
        oi_limit = 1000 if same_day else 100
        volume_limit = 1000 if same_day else 0
        size_limit = 10 if same_day else 2
        signed_delta_ok = quote.delta >= 0 if wanted_right == "CALL" else quote.delta <= 0
        if quote_age is None or separation is None:
            fatal.append("OPTION_QUOTE_TIME_UNAVAILABLE")
        elif max(quote_age, underlying_age) > age_limit or separation > age_limit:
            reject("STALE_OPTION_QUOTE")
        elif bid <= 0 or ask <= 0 or ask < bid or midpoint < Decimal("0.20"):
            reject("PRICE_FILTER")
        elif (ask - bid) / midpoint > spread_limit:
            reject("SPREAD_FILTER")
        elif quote.open_interest < oi_limit or quote.volume < volume_limit:
            reject("LIQUIDITY_FILTER")
        elif min(quote.bid_size, quote.ask_size) < size_limit:
            reject("SIZE_FILTER")
        elif quote.gamma < 0 or quote.theta > 0 or not signed_delta_ok:
            reject("GREEK_FILTER")
        elif same_day and chain.same_day_membership is not True:
            if chain.same_day_membership is None:
                reject("SAME_DAY_MEMBERSHIP_UNAVAILABLE")
            else:
                reject("SAME_DAY_NOT_PERMITTED")
        else:
            eligible.append(supplied)
    if fatal:
        return _unavailable(chain, policy, *fatal)
    scores: list[OptionScore] = []
    by_id = {row.quote.record_id: row for row in eligible}
    for supplied in eligible:
        values = sorted(references[(supplied.quote.option_type, supplied.quote.expiry)])
        middle = len(values) // 2
        median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        score = _score(supplied, underlying_mid, median, current_date)
        threshold = Decimal(75) if (supplied.quote.expiry - current_date).days == 0 else Decimal(65)
        if score.score >= threshold:
            scores.append(score)
        else:
            reject("OPTION_SCORE_FILTER")
    scores.sort(key=lambda value: (-value.score, value.delta_distance, value.spread_ratio,
                -value.minimum_size, -value.volume, -value.open_interest, not value.same_week,
                by_id[value.option_quote_id].quote.expiry, value.contract_id))
    counts = tuple(sorted(rejection.items()))
    if not scores:
        reasons = tuple(f"{name}:{count}" for name, count in counts) or ("NO_LISTED_POLICY_EXPIRATION",)
        return OptionSelection(OptionRecommendation(
            record_id=f"m47:options:{candidate.record_id}", candidate_id=candidate.record_id,
            status="POOR", ranked_at=evaluated, reasons=reasons, policy_version=policy,
        ), (), counts)
    best = by_id[scores[0].option_quote_id].quote
    deliverable = best.deliverable or f"STANDARD_100_SHARES:{best.underlying_id}"
    reasons = ("FROZEN_POLICY_TOP_RANKED",)
    if candidate.strategy_id == "CRVOL_ORB5" and chain.same_day_membership is None:
        reasons += ("ORDINARY_DTE_ONLY / SAME_DAY_MEMBERSHIP_UNAVAILABLE",)
    recommendation = OptionRecommendation(
        record_id=f"m47:options:{candidate.record_id}", candidate_id=candidate.record_id,
        status="RECOMMENDED", ranked_at=evaluated, reasons=reasons, policy_version=policy,
        option_quote_id=best.record_id, contract_id=best.contract_id, expiry=best.expiry,
        strike=best.strike, option_type=best.option_type, multiplier=best.multiplier,
        deliverable=deliverable, rank=1, score=float(scores[0].score),
    )
    return OptionSelection(recommendation, tuple(scores), counts)


@dataclass(frozen=True)
class PortfolioCandidate:
    candidate: AlertCandidate
    research_arm_id: str
    source_mode: str
    portfolio_experiment_id: str
    frozen_daily_atr: float
    mechanical_event_available_at: datetime
    priority_tier: int = 0
    recovery: "ProducerRecovery | None" = None
    session_close: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, AlertCandidate):
            raise RecordError("portfolio input requires an AlertCandidate")
        for name in ("research_arm_id", "source_mode", "portfolio_experiment_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise RecordError(f"{name} must be explicit")
        if _decimal(self.frozen_daily_atr, "frozen daily ATR") <= 0:
            raise RecordError("frozen daily ATR must be positive")
        object.__setattr__(self, "mechanical_event_available_at",
                           as_utc(self.mechanical_event_available_at))
        if self.mechanical_event_available_at > self.candidate.created_at:
            raise RecordError("mechanical event cannot follow candidate creation")
        if self.priority_tier not in (0, 1):
            raise RecordError("priority tier must be zero or one")
        if self.recovery is not None and not isinstance(self.recovery, ProducerRecovery):
            raise RecordError("producer recovery must be ProducerRecovery or null")
        if self.session_close is not None:
            object.__setattr__(self, "session_close", as_utc(self.session_close))


@dataclass(frozen=True)
class ProducerRecovery:
    """The finite producer facts needed to resume one frozen M4.7 wrapper."""

    producer_state: str
    frozen_reference: str
    reserved_number: int
    started_count: int
    reset_satisfied: bool
    previous_mechanical_event: datetime
    last_action_time: datetime

    def __post_init__(self) -> None:
        if not self.producer_state or not self.frozen_reference:
            raise RecordError("producer recovery identity must be explicit")
        if type(self.reserved_number) is not int or self.reserved_number < 1:
            raise RecordError("reserved number must be a positive integer")
        if type(self.started_count) is not int or self.started_count < 0:
            raise RecordError("started count must be a nonnegative integer")
        if type(self.reset_satisfied) is not bool:
            raise RecordError("reset fact must be true or false")
        object.__setattr__(self, "previous_mechanical_event",
                           as_utc(self.previous_mechanical_event))
        object.__setattr__(self, "last_action_time", as_utc(self.last_action_time))

    def as_dict(self) -> dict[str, object]:
        return {
            "producer_state": self.producer_state,
            "frozen_reference": self.frozen_reference,
            "reserved_number": self.reserved_number,
            "started_count": self.started_count,
            "reset_satisfied": self.reset_satisfied,
            "previous_mechanical_event": _time_text(self.previous_mechanical_event),
            "last_action_time": _time_text(self.last_action_time),
        }


@dataclass(frozen=True)
class ReversalReleaseEvidence:
    """Original producer requests and canonical records for one ownership claim."""

    record_id: str
    from_candidate_id: str
    to_candidate_id: str
    trigger_request: TriggerRequest
    handoff_request: HandoffRequest
    reversal_request: ReversalRequest
    session: SessionRecord
    supporting_records: tuple[Bar | Quote | FeatureSnapshot, ...]

    def __post_init__(self) -> None:
        if not self.record_id or not self.from_candidate_id or not self.to_candidate_id:
            raise RecordError("release identity must be explicit")
        if self.from_candidate_id == self.to_candidate_id:
            raise RecordError("release must link different candidates")
        if not isinstance(self.trigger_request, TriggerRequest):
            raise RecordError("release requires the original ORB trigger request")
        if not isinstance(self.handoff_request, HandoffRequest):
            raise RecordError("release requires the original handoff request")
        if not isinstance(self.reversal_request, ReversalRequest):
            raise RecordError("release requires the original reversal request")
        if not isinstance(self.session, SessionRecord):
            raise RecordError("release requires the original session")
        if (not isinstance(self.supporting_records, tuple)
                or any(not isinstance(row, (Bar, Quote, FeatureSnapshot))
                       for row in self.supporting_records)):
            raise RecordError("release supporting records must be canonical records")
        ids = [row.record_id for row in self.supporting_records]
        if len(ids) != len(set(ids)):
            raise RecordError("release supporting record IDs must be unique")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "from_candidate_id": self.from_candidate_id,
            "to_candidate_id": self.to_candidate_id,
            "trigger_request": _canonical_value(self.trigger_request),
            "handoff_request": _canonical_value(self.handoff_request),
            "reversal_request": _canonical_value(self.reversal_request),
            "session": self.session.as_dict(),
            "supporting_records": [row.as_dict() for row in sorted(
                self.supporting_records, key=lambda item: item.record_id)],
        }


def candidate_key(row: PortfolioCandidate) -> dict[str, object]:
    candidate = row.candidate
    epoch = datetime(1970, 1, 1, tzinfo=row.mechanical_event_available_at.tzinfo)
    elapsed = row.mechanical_event_available_at - epoch
    available_ns = ((elapsed.days * 86400 + elapsed.seconds) * 1_000_000
                    + elapsed.microseconds) * 1000
    return {
        "alert_type": candidate.alert_type, "config_hash": candidate.config_hash,
        "frozen_input_ids": sorted(set(candidate.input_record_ids)),
        "instrument_id": candidate.metadata.instrument_id,
        "mechanical_event_available_ns": available_ns,
        "research_arm_id": row.research_arm_id,
        "session_id": candidate.metadata.session, "source_mode": row.source_mode,
        "strategy_id": candidate.strategy_id, "strategy_version": candidate.strategy_version,
        "structure_id": candidate.structure_id,
    }


def candidate_fingerprint(row: PortfolioCandidate) -> str:
    try:
        payload = json.dumps(candidate_key(row), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeEncodeError, ValueError) as exc:
        raise RecordError("candidate key is not valid canonical UTF-8 JSON") from exc
    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class PortfolioManifest:
    portfolio_experiment_id: str
    data_mode: str
    price_source_basis: str
    global_config_hash: str
    observation_cutoff: datetime
    candidates: tuple[PortfolioCandidate, ...]
    complete: bool
    required_records_complete: bool
    reversal_releases: tuple[ReversalReleaseEvidence, ...] = ()

    def __post_init__(self) -> None:
        for name in ("portfolio_experiment_id", "data_mode", "price_source_basis", "global_config_hash"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise RecordError(f"{name} must be explicit")
        object.__setattr__(self, "observation_cutoff", as_utc(self.observation_cutoff))
        if (not isinstance(self.candidates, tuple)
                or any(not isinstance(row, PortfolioCandidate)
                       for row in self.candidates)):
            raise RecordError("manifest candidates must be supplied portfolio candidates")
        if type(self.complete) is not bool or type(self.required_records_complete) is not bool:
            raise RecordError("manifest completeness flags must be true or false")
        if (not isinstance(self.reversal_releases, tuple)
                or any(not isinstance(row, ReversalReleaseEvidence)
                       for row in self.reversal_releases)):
            raise RecordError("reversal releases must contain original producer evidence")
        release_ids = [row.record_id for row in self.reversal_releases]
        release_pairs = [(row.from_candidate_id, row.to_candidate_id)
                         for row in self.reversal_releases]
        if len(release_ids) != len(set(release_ids)) or len(release_pairs) != len(set(release_pairs)):
            raise RecordError("reversal release identities must be unique")


@dataclass(frozen=True)
class PortfolioGroup:
    anchor_fingerprint: str
    primary_fingerprint: str
    member_fingerprints: tuple[str, ...]
    confluence_fingerprints: tuple[str, ...]
    conflicts: tuple[str, ...]
    released_from_fingerprint: str | None = None
    release_record_id: str | None = None


@dataclass(frozen=True)
class PortfolioProjection:
    status: str
    policy_version: str
    manifest_hash: str
    groups: tuple[PortfolioGroup, ...]
    retained_candidate_ids: tuple[str, ...]
    unavailable_reasons: tuple[str, ...] = ()
    recovery: tuple[dict[str, object], ...] = ()
    releases: tuple[dict[str, object], ...] = ()

    def to_json(self) -> str:
        return json.dumps({
            "status": self.status, "policy_version": self.policy_version,
            "manifest_hash": self.manifest_hash,
            "groups": [group.__dict__ for group in self.groups],
            "retained_candidate_ids": self.retained_candidate_ids,
            "unavailable_reasons": self.unavailable_reasons,
            "recovery": self.recovery, "releases": self.releases,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _time_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        return _time_text(value)
    if hasattr(value, "as_dict"):
        return _canonical_value(value.as_dict())
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _canonical_value(asdict(value))
    return value


def _semantic_bytes(row: PortfolioCandidate) -> str:
    return row.candidate.to_json()


def _recovery_payload(row: PortfolioCandidate) -> dict[str, object] | None:
    if row.recovery is None or row.session_close is None:
        return None
    deadline = intent_expiry(row)
    return {
        "candidate_key": candidate_key(row),
        "fingerprint": candidate_fingerprint(row),
        "semantic_candidate_json": _semantic_bytes(row),
        "mechanical_event_available_at": _time_text(row.mechanical_event_available_at),
        "producer_namespace": row.candidate.strategy_id,
        "research_arm_id": row.research_arm_id,
        "intent_expires_at": _time_text(deadline),
        "session_close": _time_text(row.session_close),
        "producer": row.recovery.as_dict(),
    }


def _manifest_hash(manifest: PortfolioManifest) -> str:
    payload = {
        "namespace": [manifest.portfolio_experiment_id, manifest.data_mode,
                      manifest.price_source_basis, manifest.global_config_hash],
        "observation_cutoff": manifest.observation_cutoff.isoformat(),
        "candidate_fingerprints": sorted(candidate_fingerprint(row) for row in manifest.candidates),
        "candidate_semantics": sorted(
            (candidate_fingerprint(row), _semantic_bytes(row)) for row in manifest.candidates),
        "reversal_releases": [row.as_dict() for row in sorted(
            manifest.reversal_releases, key=lambda item: (
                item.record_id, item.from_candidate_id, item.to_candidate_id))],
        "policy_version": GROUP_POLICY_VERSION,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def _record_matches(record: object, sources: dict[str, Bar | Quote | FeatureSnapshot]) -> bool:
    """Bind reduced producer facts to their canonical source values and times."""
    ident = getattr(record, "record_id", None)
    source = sources.get(ident)
    if source is None:
        return False
    if hasattr(record, "price"):
        return (isinstance(source, Quote) and record.price == source.last
                and record.observed_at == source.trade_time
                and record.available_at == source.metadata.available_time)
    if hasattr(record, "close"):
        return (isinstance(source, Bar) and record.close == source.close
                and record.bar_end == source.end_time
                and record.available_at == source.metadata.available_time)
    return True


def _checked_release(evidence: ReversalReleaseEvidence,
                     source: AlertCandidate, target: AlertCandidate):
    """Recompute the full ORB -> failed break -> reversal chain from originals."""
    sources = {row.record_id: row for row in evidence.supporting_records}
    trigger_request = evidence.trigger_request
    reduced = [*trigger_request.observations]
    if trigger_request.last_trade is not None:
        reduced.append(trigger_request.last_trade)
    if trigger_request.minute_close is not None:
        reduced.append(trigger_request.minute_close)
    handoff_request = evidence.handoff_request
    if handoff_request.breakout_extreme is not None:
        reduced.append(handoff_request.breakout_extreme)
    if handoff_request.minute_close is not None:
        reduced.append(handoff_request.minute_close)
    reversal_request = evidence.reversal_request
    for item in (reversal_request.last_trade, reversal_request.confirmation_close):
        if item is not None:
            reduced.append(item)
    if any(not _record_matches(item, sources) for item in reduced):
        return None
    frozen = trigger_request.candidate
    required = {frozen.anchor_bar_id, *frozen.input_record_ids}
    if not required <= sources.keys():
        return None
    trigger = evaluate_orb5_trigger(trigger_request)
    handoff = evaluate_or_failure_handoff(replace(handoff_request, attempt=trigger))
    if not (handoff.state.state == "SETUP_FORMING"
            and handoff.state.substate == FAILURE_FORMING):
        return None
    reversal = evaluate_or_failure_rev(replace(reversal_request, handoff=handoff))
    handoff_gate = next((gate for gate in reversal.gates if gate.name == HANDOFF_GATE), None)
    if not (handoff_gate is not None and handoff_gate.status == PASS
            and reversal.state.state == "ALERT_TRIGGERED"):
        return None
    declared = DeclaredTransition(
        evidence.record_id, evidence.from_candidate_id, evidence.to_candidate_id,
        reversal, evidence.session, evidence.supporting_records)
    report = report_cross_strategy_interaction(InteractionRequest(
        evaluated_at=max(source.created_at, target.created_at, reversal.evaluated_at),
        policy=InteractionPolicy("M47_RELEASE_CHECK_V1", "M47_FIRST4_RESEARCH_V1",
                                 180, 0.25, BOTH_REGIONS),
        candidates=(source, target), transitions=(declared,)))
    finding = report.transitions[0]
    return finding if finding.status == ACCEPTED else None


def project_portfolio(manifest: PortfolioManifest) -> PortfolioProjection:
    """Create one deterministic complete-batch recording projection."""
    retained = tuple(sorted(row.candidate.record_id for row in manifest.candidates))
    digest = _manifest_hash(manifest)
    recovery = tuple(_recovery_payload(row) for row in sorted(
        manifest.candidates, key=candidate_fingerprint))
    if not manifest.complete or not manifest.required_records_complete:
        return PortfolioProjection("GROUPING_UNAVAILABLE", GROUP_POLICY_VERSION, digest, (), retained,
                                   ("COMPLETE_OFFLINE_BATCH_NOT_CERTIFIED",))
    if any(row.portfolio_experiment_id != manifest.portfolio_experiment_id
           for row in manifest.candidates):
        return PortfolioProjection("GROUPING_UNAVAILABLE", GROUP_POLICY_VERSION, digest, (), retained,
                                   ("PORTFOLIO_EXPERIMENT_ROSTER_MISMATCH",))
    if any(item is None for item in recovery):
        return PortfolioProjection("GROUPING_UNAVAILABLE", GROUP_POLICY_VERSION, digest, (), retained,
                                   ("RECOVERY_FACTS_UNAVAILABLE",))
    rows = sorted(manifest.candidates, key=lambda row: (
        row.mechanical_event_available_at, row.priority_tier, candidate_fingerprint(row)))
    semantic: dict[str, str] = {}
    groups: list[dict[str, object]] = []
    candidate_by_id = {row.candidate.record_id: row.candidate for row in rows}
    releases = {}
    checked_release_payloads = []
    for release in manifest.reversal_releases:
        source = candidate_by_id.get(release.from_candidate_id)
        target = candidate_by_id.get(release.to_candidate_id)
        finding = None if source is None or target is None else _checked_release(release, source, target)
        if finding is not None:
            releases[(release.from_candidate_id, release.to_candidate_id)] = (release, finding)
            checked_release_payloads.append(release.as_dict())
    for row in rows:
        fingerprint = candidate_fingerprint(row)
        encoded = row.candidate.to_json()
        if fingerprint in semantic and semantic[fingerprint] != encoded:
            return PortfolioProjection("GROUPING_UNAVAILABLE", GROUP_POLICY_VERSION, digest, (), retained,
                                       ("IDENTITY_COLLISION_UNAVAILABLE",))
        semantic[fingerprint] = encoded
        candidate = row.candidate
        qualifiers: list[tuple[object, ...]] = []
        for index, group in enumerate(groups):
            anchor = group["anchor"]
            owner = group["owner"]
            anchor_candidate = anchor.candidate
            owner_candidate = owner.candidate
            if (candidate.metadata.instrument_id != anchor_candidate.metadata.instrument_id
                    or candidate.metadata.session != anchor_candidate.metadata.session
                    or row.source_mode != anchor.source_mode):
                continue
            if candidate.direction != owner_candidate.direction:
                release = releases.get((owner_candidate.record_id, candidate.record_id))
                if release is not None:
                    group["members"].append(fingerprint)
                    group["owner"] = row
                    group["released_from"] = candidate_fingerprint(owner)
                    group["release_record_id"] = release[0].record_id
                    qualifiers = []
                    break
                if candidate.created_at < owner_candidate.expires_at:
                    group["conflicts"].append(fingerprint)
                continue
            seconds = abs((row.mechanical_event_available_at
                           - anchor.mechanical_event_available_at).total_seconds())
            trigger_distance = abs(candidate.trigger_price - anchor_candidate.trigger_price)
            stop_distance = abs(candidate.risk.hard_stop - anchor_candidate.risk.hard_stop)
            limit = Decimal("0.25") * _decimal(anchor.frozen_daily_atr, "anchor ATR")
            maximum = max(_decimal(trigger_distance, "trigger distance"),
                          _decimal(stop_distance, "stop distance"))
            if seconds <= 180 and maximum <= limit:
                qualifiers.append((Decimal(str(seconds)), maximum / _decimal(anchor.frozen_daily_atr, "anchor ATR"),
                                   anchor.mechanical_event_available_at,
                                   candidate_fingerprint(anchor), index))
        if any(group.get("owner") is row for group in groups):
            continue
        if qualifiers:
            index = min(qualifiers)[-1]
            groups[index]["members"].append(fingerprint)
            groups[index]["confluence"].append(fingerprint)
        else:
            groups.append({"anchor": row, "owner": row, "members": [fingerprint],
                           "confluence": [], "conflicts": [], "released_from": None,
                           "release_record_id": None})
    output = tuple(PortfolioGroup(candidate_fingerprint(group["anchor"]),
                                  candidate_fingerprint(group["owner"]),
                                  tuple(group["members"]), tuple(group["confluence"]),
                                  tuple(group["conflicts"]), group["released_from"],
                                  group["release_record_id"]) for group in groups)
    return PortfolioProjection("RECORDED", GROUP_POLICY_VERSION, digest, output, retained,
                               (), recovery, tuple(checked_release_payloads))


def intent_expiry(candidate: PortfolioCandidate, *, session_close: datetime | None = None) -> datetime:
    """Return the fixed delivery-intent deadline; equality is expired."""
    if not isinstance(candidate, PortfolioCandidate):
        raise RecordError("intent expiry requires the original portfolio candidate")
    close_value = session_close if session_close is not None else candidate.session_close
    if close_value is None:
        raise RecordError("intent expiry requires the original session close")
    close = as_utc(close_value)
    alert = candidate.candidate
    seconds = 30 if alert.alert_type == "HEADS_UP" else 120
    outer = alert.expires_at if alert.alert_type == "HEADS_UP" else close
    return min(outer, candidate.mechanical_event_available_at + timedelta(seconds=seconds))


def intent_is_expired(expires_at: datetime, at: datetime) -> bool:
    return as_utc(at) >= as_utc(expires_at)


def cooldown_allows(strategy_id: str, previous_mechanical_event: datetime,
                    new_structure_or_attempt: datetime) -> bool:
    if strategy_id not in ("CRVOL_ORB5", "HOD_COMP_RS"):
        raise RecordError("cooldown policy is not defined for this strategy")
    return as_utc(new_structure_or_attempt) - as_utc(previous_mechanical_event) >= timedelta(seconds=600)
