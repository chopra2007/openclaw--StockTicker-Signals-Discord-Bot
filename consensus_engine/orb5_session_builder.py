"""M9.1AL: one `Orb5Session` from supplied bars, so the grid run needs no hand-made levels.

`build_orb5_session` builds a `FeatureSnapshot` (`build_core_price_snapshot`) and,
for each direction and each opening range (5 and 15 minutes), an
`Orb5LevelCatalog` (`build_orb5_level_catalog`). The catalogs are stored on the
session by `(direction, opening-range minutes)`, because the measured-move level
depends on both. A catalog that cannot prove a family stays incomplete and the
D-090 exit leaves that trade unresolved (D-104); nothing is filled in.

An opening range that had not finished at `evaluated_at` is treated as
unavailable, so a 15-minute catalog never reads bars after the evaluation time.
ATR, tick and the entry fill stay caller-supplied (the D-106 quote fill still
does not exist, see `orb5_grid_run.RANKING_BLOCKERS`). No data is fetched and no
alert or order occurs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from .core_price_features import build_core_price_snapshot
from .historical_bars import HistoryBatch
from .orb5_grid_run import DIRECTIONS, Orb5Session
from .orb5_level_catalog import build_orb5_level_catalog
from .orb5_research_adapter import Orb5OpeningRange, opening_range_from_bars
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_date_at

OPENING_RANGE_MINUTES = (5, 15)
NOT_YET_COMPLETE = "OPENING_RANGE_NOT_COMPLETE_AT_EVALUATION"


def build_orb5_session(
    *, ticker: str, instrument_type: str, evaluated_at: datetime,
    minute_history: HistoryBatch | None, daily_history: HistoryBatch | None,
    prior_minute_history: HistoryBatch | None = None,
    premarket_history: HistoryBatch | None = None,
    latest_atr: float | None, tick: float | None,
    entry_price: dict[str, float | None], entry_time: dict[str, datetime | None],
    entry_source: str,
) -> Orb5Session:
    """The session record for one ticker-day; unproven catalog families stay UNKNOWN."""
    if minute_history is None:
        raise RecordError("the session's minute history is required")
    if minute_history.request.symbol != ticker:
        raise RecordError("minute history symbol must match the ticker")
    moment = as_utc(evaluated_at)
    opened = as_utc(minute_history.request.start)
    snapshot = build_core_price_snapshot(
        record_id=f"orb5-session:{ticker}:{moment.isoformat()}", evaluated_at=moment,
        minute_history=minute_history, daily_history=daily_history,
        premarket_history=premarket_history)
    catalogs: dict[tuple[str, int], tuple[tuple[tuple[str, float], ...], bool]] = {}
    for minutes in OPENING_RANGE_MINUTES:
        if opened + timedelta(minutes=minutes) > moment:
            opening_range = Orb5OpeningRange(None, None, minutes, (), NOT_YET_COMPLETE, None)
        else:
            opening_range = opening_range_from_bars(
                symbol=ticker, instrument_type=instrument_type, minutes=minutes,
                minute_history=minute_history)
        for direction in DIRECTIONS:
            catalog = build_orb5_level_catalog(
                snapshot, opening_range, direction=direction, daily_history=daily_history,
                evaluated_at=moment, minute_history=prior_minute_history,
                tick=Decimal(str(tick)) if tick is not None else None)
            catalogs[(direction, minutes)] = (catalog.levels, catalog.complete)
    session_date: date = session_date_at(opened)
    return Orb5Session(
        ticker, session_date, instrument_type, latest_atr, tick, dict(entry_price),
        dict(entry_time), entry_source, minute_history, catalogs=catalogs)


__all__ = ["OPENING_RANGE_MINUTES", "NOT_YET_COMPLETE", "build_orb5_session"]
