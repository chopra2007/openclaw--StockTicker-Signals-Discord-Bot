#!/usr/bin/env python3
"""Shared constants and readers for the TODO #103 intraday-dislocation research.

Local files only. No online Databento client, no API key, no network, no spend.

Clock note: the DBN one-minute bars are stamped at the START of the bar, so the
bar stamped 09:30 Eastern covers 09:30:00-09:30:59. All internal market maths
uses Eastern because that is what the exchange runs on; every number the owner
sees is labelled Pacific.
"""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import databento as db

SEED = 20260828

DATA_DIR = Path(
    "/home/openclaw/.openclaw/research-data/databento/opening-auctions/"
    "selected60_2023-01_to_2026-08"
)
RES_DIR = Path(
    "/home/openclaw/.openclaw/workspace/.omc/research/intraday-dislocation"
)

EQUS_FILE = DATA_DIR / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"
EQUS_BRK_FILE = DATA_DIR / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"
PILLAR_FILE = DATA_DIR / "xnys-pillar_ohlcv-1m_60-symbols_2023-01-01_2026-08-22.dbn.zst"

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

PRICE_SCALE = 1e-9  # DBN fixed-point prices

# ---- minute indices (minute-of-day in Eastern, bar stamped at its start) ----
MIN_OPEN = 9 * 60 + 30        # 09:30 ET = 6:30 a.m. Pacific
MIN_WINDOW_LAST = 9 * 60 + 59  # last bar fully inside the 09:30-10:00 window
MIN_STAB_1 = 10 * 60          # 10:00 bar - first stabilisation minute
MIN_STAB_2 = 10 * 60 + 1      # 10:01 bar - second stabilisation minute
MIN_ENTRY_DIRECT = 10 * 60 + 1     # direct entry: open of the 10:01 bar
MIN_ENTRY_CONFIRMED = 10 * 60 + 2  # confirmed entry: open of the 10:02 bar
MIN_HOLD_PRIMARY = 30         # primary maximum holding time, minutes
MIN_HOLD_STRESS = 60          # frozen stress check only, never a tie-breaker
MIN_LAST_NEEDED = 11 * 60 + 10
MIN_RTH_LAST = 15 * 60 + 59   # 15:59 bar closes the regular session

KEEP_MINUTES = set(range(MIN_OPEN, MIN_LAST_NEEDED + 1)) | {MIN_RTH_LAST}


class EtClock:
    """Fast UTC-nanosecond -> Eastern conversion, cached per UTC day."""

    def __init__(self):
        self._offset = {}

    def offset_ns(self, ts_ns: int) -> int:
        day = ts_ns // 86_400_000_000_000
        off = self._offset.get(day)
        if off is None:
            dt = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC).astimezone(ET)
            off = int(dt.utcoffset().total_seconds()) * 1_000_000_000
            self._offset[day] = off
        return off

    def date_and_sec(self, ts_ns: int):
        local = ts_ns + self.offset_ns(ts_ns)
        day = local // 86_400_000_000_000
        sec = (local % 86_400_000_000_000) / 1e9
        return day, sec


def day_to_date_str(day: int) -> str:
    return datetime.utcfromtimestamp(day * 86_400).strftime("%Y-%m-%d")


def open_store(path: Path):
    return db.DBNStore.from_file(str(path))


def symbol_map(path: Path):
    """instrument_id -> raw symbol, from the file's own metadata mappings."""
    store = open_store(path)
    out = {}
    for symbol, intervals in store.metadata.mappings.items():
        for iv in intervals:
            out[int(iv["symbol"])] = symbol
    return out


def canonical(symbol: str) -> str:
    """XNYS writes 'BRK B'; EQUS writes 'BRK.B'. One name for both."""
    return symbol.replace(" ", ".").upper()
