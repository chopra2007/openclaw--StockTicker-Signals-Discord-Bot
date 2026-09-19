"""D-090 B-entry geometry over supplied facts; no source or strategy activation.

The caller supplies the frozen crossing values, complete anchor path and an
externally defined catalog. READY means supplied geometry only, never approved
catalog producers, current source coverage, strategy validity or permission to act.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from fractions import Fraction
import json

from .trade_alerts_models import FeatureSnapshot, RecordError, RiskLevel, SourceMetadata, TargetLevel
from .utils.time_context import as_utc, session_date_at


SELECTOR_VERSION = "D090_B_RISK_TARGETS_V1"
VARIANTS = ("CRVOL_ORB5_B_TAPE_V1", "CRVOL_ORB5_B_QUOTE_PROJECTED_V1")
REQUIRED_FAMILIES = (
    "PREMARKET", "PRIOR_DAY", "OR_MEASURED_MOVE", "ATR", "AVWAP", "PROFILE",
    "OTHER_STRUCTURE",
)


def _known(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().upper() not in ("UNKNOWN", "UNSPECIFIED"))


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError("a timestamp is required")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError("timestamps require a timezone") from exc


@dataclass(frozen=True)
class PriceInput:
    """Bind one canonical feature to an explicit common price/venue basis.

    The basis and feature definition identify supplied contracts, not source proof.
    Null values and unknown labels remain inputs so the selector can report them.
    """

    snapshot: FeatureSnapshot
    feature_name: str
    price_basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, FeatureSnapshot):
            raise RecordError("price input requires FeatureSnapshot")
        if not _known(self.feature_name):
            raise RecordError("feature name must be explicit")
        if not isinstance(self.price_basis, str):
            raise RecordError("price basis must be a string")


@dataclass(frozen=True)
class FamilyCoverage:
    family: str
    status: str
    available_at: datetime
    covered_through: datetime
    evidence_reference: str

    def __post_init__(self) -> None:
        if self.family not in REQUIRED_FAMILIES:
            raise RecordError("unsupported structural family")
        if self.status not in ("COMPLETE", "UNKNOWN", "UNAVAILABLE"):
            raise RecordError("unsupported structural coverage status")
        for name in ("available_at", "covered_through"):
            object.__setattr__(self, name, _instant(getattr(self, name)))
        if self.covered_through > self.available_at:
            raise RecordError("coverage cannot precede its observed-through time")
        if not isinstance(self.evidence_reference, str):
            raise RecordError("coverage reference must be a string")


@dataclass(frozen=True)
class StructuralLevel:
    price: PriceInput
    family: str
    kind: str
    admitted_target: bool
    blocking_obstacle: bool

    def __post_init__(self) -> None:
        if not isinstance(self.price, PriceInput):
            raise RecordError("level requires a price input")
        if self.family not in REQUIRED_FAMILIES or not _known(self.kind):
            raise RecordError("level family and kind must be explicit")
        if type(self.admitted_target) is not bool or type(self.blocking_obstacle) is not bool:
            raise RecordError("level roles must be booleans")
        if not self.admitted_target and not self.blocking_obstacle:
            raise RecordError("level must have a target or obstacle role")


@dataclass(frozen=True)
class StructuralCatalog:
    version: str
    metadata: SourceMetadata
    price_basis: str
    coverage: tuple[FamilyCoverage, ...]
    levels: tuple[StructuralLevel, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not isinstance(self.price_basis, str):
            raise RecordError("catalog version and price basis must be strings")
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("catalog requires SourceMetadata")
        for name, kind in (("coverage", FamilyCoverage), ("levels", StructuralLevel)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(row, kind) for row in values):
                raise RecordError(f"{name} must be a tuple of typed rows")
        families = [row.family for row in self.coverage]
        if len(families) != len(set(families)):
            raise RecordError("coverage families must be unique")


@dataclass(frozen=True)
class RiskTargetRequest:
    variant: str
    direction: str
    crossed_at: datetime
    evaluated_at: datetime
    anchor: PriceInput
    frozen_atr: PriceInput
    price_increment: PriceInput
    boundary: PriceInput
    entry: PriceInput
    path_complete: bool
    path_evidence_reference: str
    catalog: StructuralCatalog

    def __post_init__(self) -> None:
        if self.variant not in VARIANTS or self.direction not in ("LONG", "SHORT"):
            raise RecordError("only the two D-090 B variants and LONG/SHORT are supported")
        for name in ("crossed_at", "evaluated_at"):
            object.__setattr__(self, name, _instant(getattr(self, name)))
        if self.crossed_at > self.evaluated_at:
            raise RecordError("evaluation cannot precede crossing")
        if session_date_at(self.crossed_at) != session_date_at(self.evaluated_at):
            raise RecordError("crossing and trigger must belong to one session")
        for name in ("anchor", "frozen_atr", "price_increment", "boundary", "entry"):
            if not isinstance(getattr(self, name), PriceInput):
                raise RecordError(f"{name} requires PriceInput")
        if type(self.path_complete) is not bool or not isinstance(self.path_evidence_reference, str):
            raise RecordError("path coverage must be explicit")
        if not isinstance(self.catalog, StructuralCatalog):
            raise RecordError("catalog is required")


@dataclass(frozen=True)
class RiskTargetResult:
    request: RiskTargetRequest
    status: str
    reasons: tuple[str, ...]
    raw_stop: float | None = None
    risk: RiskLevel | None = None
    extension_r: float | None = None
    targets: tuple[TargetLevel, ...] = ()
    # A tuple per target preserves every equal-price label and its input link.
    target_labels: tuple[tuple[str, ...], ...] = ()
    target_input_ids: tuple[tuple[str, ...], ...] = ()
    unavailable: tuple[str, ...] = ("SOFT_INVALIDATION_UNDEFINED", "RUNNER_UNDEFINED")

    def as_dict(self) -> dict[str, object]:
        # Convert only instants; canonical numeric facts retain their own values.
        return json.loads(self.to_json())

    def to_json(self) -> str:
        def instant(value: datetime) -> str:
            return as_utc(value).isoformat().replace("+00:00", "Z")
        return json.dumps({"selector_version": SELECTOR_VERSION, **asdict(self)},
                          default=instant, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _metadata_reason(meta: SourceMetadata, request: RiskTargetRequest, at: datetime) -> str | None:
    scope = request.boundary.snapshot.metadata
    if (meta.instrument_type not in ("EQUITY", "ETF")
            or meta.instrument_id != scope.instrument_id
            or meta.instrument_type != scope.instrument_type
            or meta.session != session_date_at(request.evaluated_at).isoformat()):
        return "IDENTITY_MISMATCH"
    # Derived features legitimately have different producer names. Compatibility
    # uses the explicitly supplied source/venue/adjustment price_basis instead.
    if not _known(meta.source):
        return "SOURCE_UNAVAILABLE"
    if not _known(meta.data_mode) or meta.quality not in ("VALID", "DEGRADED_PROXY"):
        return "QUALITY_UNAVAILABLE"
    if meta.source_time is None or meta.source_time > meta.available_time:
        return "INVALID_SOURCE_TIME"
    if meta.available_time > at:
        return "NOT_YET_AVAILABLE"
    return None


def _price(value: PriceInput, request: RiskTargetRequest, at: datetime,
           *, allow_zero: bool = False) -> tuple[Fraction | None, str | None]:
    snapshot = value.snapshot
    reason = _metadata_reason(snapshot.metadata, request, at)
    if reason:
        return None, reason
    if snapshot.evaluated_at > at:
        return None, "NOT_YET_EVALUATED"
    if not _known(snapshot.feature_version):
        return None, "DEFINITION_UNAVAILABLE"
    if not _known(value.price_basis) or value.price_basis != request.catalog.price_basis:
        return None, "PRICE_BASIS_MISMATCH"
    feature = next((f for f in snapshot.features if f.name == value.feature_name), None)
    if feature is None or feature.value is None:
        return None, "VALUE_UNAVAILABLE" if feature is None else feature.missing_reason
    if feature.unit != "USD_PER_SHARE":
        return None, "WRONG_UNIT"
    if feature.value < 0 or (feature.value == 0 and not allow_zero):
        return None, "NONPOSITIVE_VALUE"
    # Decimal text is the authoritative input. Exact rational arithmetic avoids
    # binary rounding at the tick, .35, 1, 1.5 and 2.5 boundaries.
    return Fraction(str(feature.value)), None


def select_b_risk_targets(request: RiskTargetRequest) -> RiskTargetResult:
    """Freeze stop/R and select only supplied admitted levels under D-090 §6.

    No anchor-path, ATR, AVWAP, profile, soft-invalidation or runner producer lives
    here. Catalog roles/coverage are supplied evidence, not inferred applicability.
    """
    if not isinstance(request, RiskTargetRequest):
        raise RecordError("RiskTargetRequest is required")
    reasons = []
    values = {}
    for name in ("anchor", "frozen_atr", "price_increment", "boundary", "entry"):
        at = request.crossed_at if name in ("frozen_atr", "boundary", "price_increment") else request.evaluated_at
        values[name], reason = _price(getattr(request, name), request, at, allow_zero=name == "frozen_atr")
        if reason:
            reasons.append(name.upper() + ":" + reason)
    if not request.path_complete or not _known(request.path_evidence_reference):
        reasons.append("ANCHOR_PATH_INCOMPLETE")
    if request.frozen_atr.feature_name != "ATR_1M_20_SMA_V1":
        reasons.append("FROZEN_ATR_WRONG_DEFINITION")
    path_mode = ("ELIGIBLE_TRADE_PATH" if request.variant == VARIANTS[0]
                 else "QUOTE_LAST_TRADE_PATH_ESTIMATE")
    if any(row.snapshot.metadata.data_mode != path_mode for row in (request.anchor, request.entry)):
        reasons.append("PATH_MODE_MISMATCH")
    seen = {}
    for row in (request.anchor, request.frozen_atr, request.price_increment, request.boundary,
                request.entry, *(level.price for level in request.catalog.levels)):
        snapshot = row.snapshot
        if snapshot.record_id in seen and seen[snapshot.record_id] != snapshot:
            reasons.append("CONFLICTING_INPUT_ID")
        seen[snapshot.record_id] = snapshot
    # The anchor and eligible latest trade describe this trigger, not a stale
    # earlier evaluation re-labeled by the caller's current request time.
    if any(row.snapshot.evaluated_at != request.evaluated_at for row in (request.anchor, request.entry)):
        reasons.append("TRIGGER_INPUT_NOT_CURRENT")
    if reasons:
        return RiskTargetResult(request, "UNAVAILABLE", tuple(reasons))

    sign = 1 if request.direction == "LONG" else -1
    anchor, atr, tick, boundary, entry = (values[n] for n in (
        "anchor", "frozen_atr", "price_increment", "boundary", "entry"))
    if sign * (entry - anchor) < 0:
        return RiskTargetResult(request, "UNAVAILABLE", ("ANCHOR_EXCLUDES_ENTRY",))
    raw = anchor - sign * Fraction("0.05") * atr
    ticks = raw / tick
    count = ticks.numerator // ticks.denominator if sign == 1 else -(-ticks.numerator // ticks.denominator)
    stop = count * tick
    risk = sign * (entry - stop)
    if stop <= 0 or risk <= 0:
        return RiskTargetResult(request, "REJECTED", ("INVALID_STOP_GEOMETRY",), float(raw))
    canonical_risk = RiskLevel(float(entry), float(stop), float(risk),
                               "D-090 supplied anchor minus/plus 0.05 frozen ATR; outward tick rounding",
                               request.anchor.snapshot.record_id)
    extension = sign * (entry - boundary)
    common = dict(raw_stop=float(raw), risk=canonical_risk, extension_r=float(extension / risk))
    if extension < 0:
        return RiskTargetResult(request, "REJECTED", ("ENTRY_BEFORE_BOUNDARY",), **common)
    if extension > Fraction("0.35") * risk:
        return RiskTargetResult(request, "REJECTED", ("STALE_EXTENSION",), **common)

    catalog = request.catalog
    if not _known(catalog.version) or not _known(catalog.price_basis):
        reasons.append("CATALOG_DEFINITION_UNAVAILABLE")
    reason = _metadata_reason(catalog.metadata, request, request.evaluated_at)
    if reason:
        reasons.append("CATALOG:" + reason)
    coverage = {row.family: row for row in catalog.coverage}
    for family in REQUIRED_FAMILIES:
        row = coverage.get(family)
        if (row is None or row.status != "COMPLETE" or not _known(row.evidence_reference)
                or row.available_at > request.evaluated_at
                or row.covered_through < request.evaluated_at):
            reasons.append("CATALOG_INCOMPLETE:" + family)

    grouped = {}
    for level in catalog.levels:
        price, reason = _price(level.price, request, request.evaluated_at)
        if reason:
            reasons.append("LEVEL:" + level.family + ":" + reason)
        elif sign * (price - entry) > 0:
            grouped.setdefault(price, []).append(level)
    if reasons:
        return RiskTargetResult(request, "UNAVAILABLE", tuple(sorted(set(reasons))), **common)

    ordered = sorted(grouped, key=lambda price: sign * (price - entry))
    obstacles = [price for price in ordered if any(l.blocking_obstacle for l in grouped[price])]
    admitted = [price for price in ordered if any(l.admitted_target for l in grouped[price])]
    if obstacles and sign * (obstacles[0] - entry) < risk:
        return RiskTargetResult(request, "REJECTED", ("OBSTACLE_BELOW_1R",), **common)
    first = next((p for p in admitted if sign * (p - entry) >= Fraction("1.5") * risk), None)
    if first is None or any(sign * (p - entry) < sign * (first - entry) for p in obstacles):
        return RiskTargetResult(request, "REJECTED", ("INSUFFICIENT_RR",), **common)
    second = next((p for p in admitted if sign * (p - first) > 0
                   and sign * (p - entry) >= Fraction("2.5") * risk), None)
    prices = (first,) if second is None else (first, second)
    targets, labels, references = [], [], []
    for number, price in enumerate(prices, 1):
        rows = grouped[price]
        target_labels = tuple(sorted({row.kind for row in rows}))
        input_ids = tuple(sorted({row.price.snapshot.record_id for row in rows}))
        targets.append(TargetLevel("T" + str(number), float(price), float(sign * (price - entry) / risk),
                                   catalog.version))
        labels.append(target_labels)
        references.append(input_ids)
    unavailable = ("SOFT_INVALIDATION_UNDEFINED", "RUNNER_UNDEFINED")
    if second is None:
        unavailable += ("T2_UNAVAILABLE",)
    return RiskTargetResult(request, "READY", (), targets=tuple(targets),
                            target_labels=tuple(labels), target_input_ids=tuple(references),
                            unavailable=unavailable, **common)
