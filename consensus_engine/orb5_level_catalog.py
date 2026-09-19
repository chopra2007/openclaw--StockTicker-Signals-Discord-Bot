"""M9.1AH: the D-090 structural level catalog for one ORB5 trade, from supplied features.

`select_orb5_structure_targets` (`orb5_trade_walk.py`) needs a level list and a
flag saying whether that list is complete. This module builds both from what
the supplied bars can honestly give:

- `PDH`/`PDL` and `PMH`/`PML`: read from a `FeatureSnapshot` built by
  `build_core_price_snapshot`. A missing feature makes that family UNKNOWN.
- `OR_MEASURED_MOVE`: long `ORH + width`, short `ORL - width`, from an available
  bar-native opening range.
- `ATR_PROJECTION` (`PRIOR_CLOSE_DAILY_ATR_LEVELS_V1`): prior regular close
  plus and minus `DAILY_ATR_14_SMA_V1`, both read from the snapshot. Either one
  missing makes the family UNKNOWN. A level behind entry is left to the D-090
  selector, never moved forward.
- `DAILY_SWING` (`DAILY_SWING_PLATEAU_2X2_V1`): confirmed 2x2 plateau highs and
  lows over the 63 preceding completed daily sessions, when a daily history and
  evaluation time are supplied. A missing session or basis makes it `UNKNOWN`;
  a complete window with no swing is `KNOWN_EMPTY`.
- `PRIOR_SESSION_BAR_PROFILE` (`PRIOR_SESSION_BAR_PROFILE_V1`): POC, VAL and VAH
  of the prior session's one-minute bars, when minute and daily history, a valid
  tick and an evaluation time are supplied. Any missing input or unexplained
  minute makes it `UNKNOWN` and the catalog incomplete (D-104). No proxy or
  filler level is ever added, and nothing is treated as "no obstacle".

Each family reports one state: `PRESENT`, `KNOWN_EMPTY` (not used yet, since no
complete-empty proof exists for these inputs) or `UNKNOWN`. No data is fetched,
no parameter is searched, and no order, alert or delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from datetime import datetime
from decimal import Decimal

from .core_price_features import build_daily_swings, build_prior_session_profile
from .historical_bars import HistoryBatch
from .orb5_research_adapter import Orb5OpeningRange
from .trade_alerts_models import FeatureSnapshot, RecordError

CATALOG_VERSION = "ORB5_STRUCTURE_BAR_V1_PARTIAL_M9_1AK"
PRESENT = "PRESENT"
UNKNOWN = "UNKNOWN"

_FEATURE_FAMILIES = (
    ("PDH", "PDH_V1"), ("PDL", "PDL_V1"), ("PMH", "PMH_V1"), ("PML", "PML_V1"),
)


@dataclass(frozen=True)
class Orb5LevelCatalog:
    direction: str
    levels: tuple[tuple[str, float], ...]
    family_states: dict[str, str]
    unknown_reasons: dict[str, str]
    version: str = CATALOG_VERSION

    @property
    def complete(self) -> bool:
        return all(state != UNKNOWN for state in self.family_states.values())


def build_orb5_level_catalog(
    snapshot: FeatureSnapshot, opening_range: Orb5OpeningRange, *, direction: str,
    daily_history: HistoryBatch | None = None, evaluated_at: datetime | None = None,
    minute_history: HistoryBatch | None = None, tick: Decimal | float | None = None,
) -> Orb5LevelCatalog:
    """One catalog per direction; a family the inputs cannot prove is UNKNOWN."""
    if not isinstance(snapshot, FeatureSnapshot):
        raise RecordError("a FeatureSnapshot is required")
    if not isinstance(opening_range, Orb5OpeningRange):
        raise RecordError("an Orb5OpeningRange is required")
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    by_name = {item.name: item for item in snapshot.features}
    levels: list[tuple[str, float]] = []
    states: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for family, feature in _FEATURE_FAMILIES:
        item = by_name.get(feature)
        if item is None:
            states[family], reasons[family] = UNKNOWN, "FEATURE_ABSENT"
        elif item.value is None:
            states[family], reasons[family] = UNKNOWN, item.missing_reason or "MISSING"
        else:
            states[family] = PRESENT
            levels.append((family, item.value))
    if opening_range.available:
        width = Fraction(str(opening_range.high)) - Fraction(str(opening_range.low))
        base = Fraction(str(opening_range.high if direction == "LONG" else opening_range.low))
        target = base + width if direction == "LONG" else base - width
        states["OR_MEASURED_MOVE"] = PRESENT
        levels.append(("OR_MEASURED_MOVE", float(target)))
    else:
        states["OR_MEASURED_MOVE"] = UNKNOWN
        reasons["OR_MEASURED_MOVE"] = opening_range.missing_reason or "OPENING_RANGE_UNAVAILABLE"
    close, atr = by_name.get("PRIOR_REGULAR_CLOSE_V1"), by_name.get("DAILY_ATR_14_SMA_V1")
    missing = [item for item in (close, atr) if item is None or item.value is None]
    if missing:
        first = missing[0]
        states["ATR_PROJECTION"] = UNKNOWN
        reasons["ATR_PROJECTION"] = ("FEATURE_ABSENT" if first is None
                                     else first.missing_reason or "MISSING")
    else:
        states["ATR_PROJECTION"] = PRESENT
        base, width = Fraction(str(close.value)), Fraction(str(atr.value))
        levels.append(("ATR_PROJECTION_UP", float(base + width)))
        levels.append(("ATR_PROJECTION_DOWN", float(base - width)))
    if daily_history is None or evaluated_at is None:
        states["DAILY_SWING"], reasons["DAILY_SWING"] = UNKNOWN, "MISSING_DAILY_HISTORY"
    else:
        swings = build_daily_swings(daily_history, evaluated_at)
        states["DAILY_SWING"] = swings.state
        if swings.state == UNKNOWN:
            reasons["DAILY_SWING"] = swings.reason or "MISSING"
        levels.extend(("DAILY_SWING_HIGH", price) for price in swings.highs)
        levels.extend(("DAILY_SWING_LOW", price) for price in swings.lows)
    if evaluated_at is None:
        states["PRIOR_SESSION_BAR_PROFILE"] = UNKNOWN
        reasons["PRIOR_SESSION_BAR_PROFILE"] = "MISSING_EVALUATION_TIME"
    else:
        profile = build_prior_session_profile(
            minute_history, daily_history,
            prior_close=close.value if close is not None else None,
            daily_atr=atr.value if atr is not None else None,
            tick=tick, evaluated_at=evaluated_at)
        states["PRIOR_SESSION_BAR_PROFILE"] = profile.state
        if profile.state == UNKNOWN:
            reasons["PRIOR_SESSION_BAR_PROFILE"] = profile.reason or "MISSING"
        else:
            levels.extend((("PROFILE_POC", profile.poc), ("PROFILE_VAL", profile.val),
                           ("PROFILE_VAH", profile.vah)))
    return Orb5LevelCatalog(direction, tuple(levels), states, reasons)


__all__ = ["CATALOG_VERSION", "Orb5LevelCatalog", "build_orb5_level_catalog"]
