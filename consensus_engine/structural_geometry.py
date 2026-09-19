"""Pure supplied-input structural geometry for M3.5.

The caller selects the anchors, windows, target and buffer rule.  This module
only checks their point-in-time identity and performs the shared arithmetic.  It
does no fetching, clock reading, storage, strategy selection or live work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math

from .trade_alerts_models import Bar, FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_date_at


FEATURE_VERSION = "M35_STRUCTURAL_GEOMETRY_V1"
DATA_MODE = "SUPPLIED_STRUCTURAL_GEOMETRY"
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or value.strip().upper() in _UNKNOWN:
        raise RecordError(f"{name} must be explicit")
    return value


def _number(value: object, name: str, *, zero: bool = False) -> Decimal:
    if (isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
            or not math.isfinite(float(value))):
        raise RecordError(f"{name} must be finite")
    result = Decimal(str(value))
    if result < 0 or (result == 0 and not zero):
        raise RecordError(f"{name} must be {'nonnegative' if zero else 'positive'}")
    return result


@dataclass(frozen=True)
class GeometryPrice:
    """One caller-supplied price with the facts needed for point-in-time checks."""

    record_id: str
    symbol: str
    instrument_type: str
    session: str
    observed_at: datetime
    available_at: datetime
    source: str
    adjustment_basis: str
    coverage_basis: str
    value: float | None
    missing_reason: str | None = None
    price_convention: str = "USD_PER_SHARE"

    def __post_init__(self) -> None:
        for name in ("record_id", "symbol", "session", "source", "adjustment_basis",
                     "coverage_basis", "price_convention"):
            _text(getattr(self, name), name)
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("geometry price instrument type must be EQUITY or ETF")
        observed = _instant(self.observed_at, "observed_at")
        available = _instant(self.available_at, "available_at")
        if available < observed:
            raise RecordError("geometry price cannot be available before observation")
        if self.value is None:
            _text(self.missing_reason, "missing_reason")
        else:
            _number(self.value, "geometry price")
            if self.missing_reason is not None:
                raise RecordError("an available geometry price cannot have a missing reason")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)


@dataclass(frozen=True)
class StructuralGeometryInputs:
    """Caller-selected inputs; selection and strategy thresholds stay outside M3.5."""

    direction: str
    impulse_start: GeometryPrice | None = None
    impulse_extreme: GeometryPrice | None = None
    adverse_extreme: GeometryPrice | None = None
    recent_high: GeometryPrice | None = None
    recent_low: GeometryPrice | None = None
    prior_high: GeometryPrice | None = None
    prior_low: GeometryPrice | None = None
    drive_path: tuple[GeometryPrice, ...] = ()
    current_price: GeometryPrice | None = None
    structural_level: GeometryPrice | None = None
    entry: GeometryPrice | None = None
    stop: GeometryPrice | None = None
    target: GeometryPrice | None = None
    atr: GeometryPrice | None = None
    buffer_floor: float = 0.01
    buffer_atr_multiple: float = 0.0
    swing_bars: tuple[Bar, ...] = ()

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("geometry direction must be LONG or SHORT")
        names = (
            "impulse_start", "impulse_extreme", "adverse_extreme", "recent_high",
            "recent_low", "prior_high", "prior_low", "current_price",
            "structural_level", "entry", "stop", "target", "atr",
        )
        if any(getattr(self, name) is not None
               and not isinstance(getattr(self, name), GeometryPrice) for name in names):
            raise RecordError("geometry prices must use GeometryPrice or null")
        if (not isinstance(self.drive_path, tuple)
                or any(not isinstance(item, GeometryPrice) for item in self.drive_path)):
            raise RecordError("drive_path must be a tuple of GeometryPrice")
        if (not isinstance(self.swing_bars, tuple)
                or any(not isinstance(item, Bar) for item in self.swing_bars)):
            raise RecordError("swing_bars must be a tuple of canonical Bar records")
        _number(self.buffer_floor, "buffer_floor", zero=True)
        _number(self.buffer_atr_multiple, "buffer_atr_multiple", zero=True)


def _feature(name: str, value: Decimal | int | None, unit: str, reason: str | None,
             ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason,
                        tuple(sorted(set(ids))))


def _price_value(row: GeometryPrice | None, *, moment: datetime, symbol: str,
                 instrument_type: str, session: str,
                 ) -> tuple[Decimal | None, str | None, tuple[str, ...]]:
    if row is None:
        return None, "MISSING_INPUT", ()
    ids = (row.record_id,)
    if row.symbol != symbol:
        return None, "INCOMPATIBLE_SYMBOL", ids
    if row.instrument_type != instrument_type:
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    if row.session != session:
        return None, "INCOMPATIBLE_SESSION", ids
    if row.price_convention != "USD_PER_SHARE":
        return None, "INCOMPATIBLE_PRICE_UNIT", ids
    if row.available_at > moment:
        return None, "NOT_YET_AVAILABLE", ids
    if row.observed_at > moment:
        return None, "FUTURE_OBSERVATION", ids
    if row.value is None:
        return None, row.missing_reason, ids
    return Decimal(str(row.value)), None, ids


def _compatible(rows: tuple[GeometryPrice | None, ...], *, moment: datetime, symbol: str,
                instrument_type: str, session: str):
    values = [_price_value(row, moment=moment, symbol=symbol,
                           instrument_type=instrument_type, session=session) for row in rows]
    ids = tuple(i for _, _, item_ids in values for i in item_ids)
    reason = next((reason for _, reason, _ in values if reason), None)
    supplied = tuple(row for row in rows if row is not None)
    if reason is None and supplied:
        bases = {(row.source, row.adjustment_basis, row.coverage_basis) for row in supplied}
        if len(bases) != 1:
            reason = "INCOMPATIBLE_SOURCE_OR_PRICE_BASIS"
    return tuple(value for value, _, _ in values), reason, ids


def _ratio_features(inputs: StructuralGeometryInputs, *, moment: datetime, symbol: str,
                    instrument_type: str, session: str) -> list[FeatureValue]:
    sign = Decimal(1 if inputs.direction == "LONG" else -1)
    values, reason, ids = _compatible(
        (inputs.impulse_start, inputs.impulse_extreme, inputs.adverse_extreme),
        moment=moment, symbol=symbol, instrument_type=instrument_type, session=session)
    retracement = None
    if reason is None:
        start, extreme, adverse = values
        impulse = sign * (extreme - start)
        if impulse <= 0:
            reason = "NONPOSITIVE_IMPULSE_DISTANCE"
        else:
            retracement = max(Decimal(0), sign * (extreme - adverse) / impulse)
    features = [_feature("RETRACEMENT_RATIO_V1", retracement, "RATIO", reason, ids)]

    values, reason, ids = _compatible(
        (inputs.recent_high, inputs.recent_low, inputs.prior_high, inputs.prior_low),
        moment=moment, symbol=symbol, instrument_type=instrument_type, session=session)
    compression = None
    if reason is None:
        recent_high, recent_low, prior_high, prior_low = values
        if recent_high < recent_low or prior_high < prior_low:
            reason = "INVALID_RANGE_GEOMETRY"
        elif prior_high == prior_low:
            reason = "ZERO_PRIOR_RANGE"
        else:
            compression = (recent_high - recent_low) / (prior_high - prior_low)
    features.append(_feature("COMPRESSION_RANGE_RATIO_V1", compression, "RATIO", reason, ids))
    return features


def _drive_feature(inputs: StructuralGeometryInputs, *, moment: datetime, symbol: str,
                   instrument_type: str, session: str) -> FeatureValue:
    if len(inputs.drive_path) < 2:
        return _feature("DRIVE_EFFICIENCY_V1", None, "RATIO", "INSUFFICIENT_PATH", ())
    values, reason, ids = _compatible(inputs.drive_path, moment=moment, symbol=symbol,
                                      instrument_type=instrument_type, session=session)
    if reason:
        return _feature("DRIVE_EFFICIENCY_V1", None, "RATIO", reason, ids)
    if any(left.observed_at >= right.observed_at
           for left, right in zip(inputs.drive_path, inputs.drive_path[1:])):
        return _feature("DRIVE_EFFICIENCY_V1", None, "RATIO", "NONCHRONOLOGICAL_PATH", ids)
    denominator = sum(abs(right - left) for left, right in zip(values, values[1:]))
    if denominator == 0:
        return _feature("DRIVE_EFFICIENCY_V1", None, "RATIO", "ZERO_PATH_DISTANCE", ids)
    return _feature("DRIVE_EFFICIENCY_V1", abs(values[-1] - values[0]) / denominator,
                    "RATIO", None, ids)


def _distance_features(inputs: StructuralGeometryInputs, *, moment: datetime, symbol: str,
                       instrument_type: str, session: str) -> list[FeatureValue]:
    sign = Decimal(1 if inputs.direction == "LONG" else -1)
    values, reason, ids = _compatible((inputs.current_price, inputs.structural_level),
                                      moment=moment, symbol=symbol,
                                      instrument_type=instrument_type, session=session)
    distance = None if reason else sign * (values[1] - values[0])
    features = [_feature("DIRECTIONAL_DISTANCE_TO_LEVEL_V1", distance,
                         "USD_PER_SHARE", reason, ids)]
    atr_values, atr_reason, atr_ids = _compatible((inputs.atr,), moment=moment, symbol=symbol,
                                                  instrument_type=instrument_type,
                                                  session=session)
    normalized = None
    combined_reason = reason or atr_reason
    if combined_reason is None:
        if atr_values[0] <= 0:
            combined_reason = "NONPOSITIVE_ATR"
        else:
            normalized = distance / atr_values[0]
    features.append(_feature("DIRECTIONAL_DISTANCE_TO_LEVEL_ATR_V1", normalized, "ATR",
                             combined_reason, ids + atr_ids))
    return features


def _risk_and_buffer_features(inputs: StructuralGeometryInputs, *, moment: datetime, symbol: str,
                              instrument_type: str, session: str) -> list[FeatureValue]:
    sign = Decimal(1 if inputs.direction == "LONG" else -1)
    values, reason, ids = _compatible((inputs.entry, inputs.stop, inputs.target),
                                      moment=moment, symbol=symbol,
                                      instrument_type=instrument_type, session=session)
    ratio = None
    if reason is None:
        entry, stop, target = values
        risk = sign * (entry - stop)
        reward = sign * (target - entry)
        if risk <= 0:
            reason = "NONPOSITIVE_RISK"
        elif reward < 0:
            reason = "NEGATIVE_REWARD"
        else:
            ratio = reward / risk
    features = [_feature("RISK_REWARD_RATIO_V1", ratio, "R_MULTIPLE", reason, ids)]

    values, reason, ids = _compatible((inputs.atr,), moment=moment, symbol=symbol,
                                      instrument_type=instrument_type, session=session)
    buffer = None
    if reason is None:
        if values[0] <= 0:
            reason = "NONPOSITIVE_ATR"
        else:
            buffer = max(Decimal(str(inputs.buffer_floor)),
                         Decimal(str(inputs.buffer_atr_multiple)) * values[0])
    features.append(_feature("ATR_BUFFER_V1", buffer, "USD_PER_SHARE", reason, ids))
    return features


def _swing_features(inputs: StructuralGeometryInputs, *, moment: datetime, symbol: str,
                    instrument_type: str, session: str) -> list[FeatureValue]:
    bars = inputs.swing_bars
    names = (("SWING_HIGH_PLATEAU_2X2_V1", "high", max, lambda x, y: x < y),
             ("SWING_LOW_PLATEAU_2X2_V1", "low", min, lambda x, y: x > y))
    if not bars:
        return [_feature(name, None, "USD_PER_SHARE", "MISSING_SWING_WINDOW", ())
                for name, *_ in names]
    ids = tuple(bar.record_id for bar in bars)
    reason = None
    for bar in bars:
        if (bar.metadata.instrument_id != symbol or bar.metadata.instrument_type != instrument_type
                or bar.metadata.session != session):
            reason = "INCOMPATIBLE_SWING_IDENTITY"
            break
        if (bar.price_convention != "USD_PER_SHARE" or not bar.is_final
                or bar.metadata.available_time > moment or bar.certified_no_trade
                or bar.metadata.quality != "VALID"):
            reason = "INCOMPLETE_SWING_WINDOW"
            break
    if reason is None and any(left.end_time != right.start_time
                              for left, right in zip(bars, bars[1:])):
        reason = "NONCONTIGUOUS_SWING_WINDOW"
    if reason is None and len({(bar.metadata.source, bar.metadata.data_mode,
                                bar.adjustment_basis, bar.price_convention)
                               for bar in bars}) != 1:
        reason = "INCOMPATIBLE_SWING_SOURCE_OR_PRICE_BASIS"
    if reason:
        return [_feature(name, None, "USD_PER_SHARE", reason, ids) for name, *_ in names]

    output = []
    for name, field, _choose, outside in names:
        values = [Decimal(str(getattr(bar, field))) for bar in bars]
        matches: list[tuple[int, int, Decimal]] = []
        i = 0
        while i < len(values):
            j = i
            while j + 1 < len(values) and values[j + 1] == values[i]:
                j += 1
            if i >= 2 and j + 2 < len(values) and all(
                    outside(values[k], values[i]) for k in (i - 2, i - 1, j + 1, j + 2)):
                matches.append((i, j, values[i]))
            i = j + 1
        if not matches:
            output.append(_feature(name, None, "USD_PER_SHARE", "KNOWN_EMPTY", ids))
            continue
        i, j, value = matches[-1]
        used = tuple(bar.record_id for bar in bars[i - 2:j + 3])
        output.append(_feature(name, value, "USD_PER_SHARE", None, used))
    return output


def build_structural_geometry_snapshot(
    *, record_id: str, evaluated_at: datetime, symbol: str, instrument_type: str,
    inputs: StructuralGeometryInputs,
) -> FeatureSnapshot:
    """Calculate shared geometry from one caller-selected, supplied-input set."""
    _text(record_id, "record_id")
    _text(symbol, "symbol")
    if instrument_type not in ("EQUITY", "ETF"):
        raise RecordError("geometry instrument type must be EQUITY or ETF")
    if not isinstance(inputs, StructuralGeometryInputs):
        raise RecordError("inputs must be StructuralGeometryInputs")
    moment = _instant(evaluated_at, "evaluated_at")
    session = session_date_at(moment).isoformat()
    features = _ratio_features(inputs, moment=moment, symbol=symbol,
                               instrument_type=instrument_type, session=session)
    features.append(_drive_feature(inputs, moment=moment, symbol=symbol,
                                   instrument_type=instrument_type, session=session))
    features.extend(_distance_features(inputs, moment=moment, symbol=symbol,
                                       instrument_type=instrument_type, session=session))
    features.extend(_swing_features(inputs, moment=moment, symbol=symbol,
                                    instrument_type=instrument_type, session=session))
    features.extend(_risk_and_buffer_features(inputs, moment=moment, symbol=symbol,
                                              instrument_type=instrument_type, session=session))
    all_ids = tuple(sorted({item for feature in features for item in feature.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_RESEARCH",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session, data_mode=DATA_MODE, quality="VALID",
    )
    return FeatureSnapshot(record_id=record_id, metadata=metadata, evaluated_at=moment,
                           feature_version=FEATURE_VERSION, features=tuple(features),
                           input_record_ids=all_ids)
