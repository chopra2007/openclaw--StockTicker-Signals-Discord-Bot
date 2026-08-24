#!/usr/bin/env python3
"""Shared constants and readers for the TODO #93 auction pressure/response research.

Local files only. No online Databento client, no API key, no network.
Every clock decision uses genuine UTC timestamps (`ts_recv` / `ts_event`)
converted to US Eastern; owner-facing text uses Pacific.
"""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import databento as db

SEED = 20260824

DATA_DIR = Path(
    "/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08"
)
PRIOR_DIR = Path(
    "/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance"
)
GATE_DIR = Path(
    "/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-pressure-response"
)

IMBALANCE_FILE = DATA_DIR / "xnys-pillar_imbalance_60-symbols_2023-01-01_2026-08-22.dbn.zst"
EQUS_FILE = DATA_DIR / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"
EQUS_BRK_FILE = DATA_DIR / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

# ---- frozen clock (Eastern seconds-of-day; Pacific label in the comment) ----
SNAPSHOT_CUTOFFS_ET = {           # Pacific:
    "0915": 9 * 3600 + 15 * 60,   # 6:15 a.m.
    "0920": 9 * 3600 + 20 * 60,   # 6:20 a.m.
    "0925": 9 * 3600 + 25 * 60,   # 6:25 a.m.
    "0929_30": 9 * 3600 + 29 * 60 + 30,  # 6:29:30 a.m.
    "0930": 9 * 3600 + 30 * 60,   # 6:30 a.m.
}
SNAPSHOT_ORDER = ["0915", "0920", "0925", "0929_30", "0930"]

# One-minute bars are stamped at the START of the bar, so "the bar ending at
# 9:40 a.m. Eastern" is the record stamped 09:39.
MIN_OPEN = 9 * 60 + 30        # 09:30 bar -> its `open` is the opening price
MIN_FIRST_FIVE = 9 * 60 + 34  # bar ending 09:35 -> first-five-minute return
MIN_ENTRY_B = 9 * 60 + 35     # bar ending 09:36 -> lane B entry
MIN_ENTRY_A = 9 * 60 + 39     # bar ending 09:40 -> lane A entry
MIN_EXIT30_B = 10 * 60 + 5    # 30 minutes after lane B entry
MIN_EXIT30_A = 10 * 60 + 9    # 30 minutes after lane A entry
MIN_EXIT_B = 10 * 60 + 35     # 60 minutes after lane B entry
MIN_EXIT_A = 10 * 60 + 39     # 60 minutes after lane A entry
MIN_PRIOR_CLOSE = 15 * 60 + 59  # bar ending 16:00 -> prior session close
MIN_RANGE_LO = MIN_OPEN
MIN_RANGE_HI = MIN_EXIT_A
NEEDED_MINUTES = set(range(MIN_RANGE_LO, MIN_RANGE_HI + 1)) | {MIN_PRIOR_CLOSE}

# ---- frozen trade definitions ----
MIN_ENTRY_VOLUME = 500          # strictly more than 500 shares in the entry minute
BASE_COST = 0.0015              # 15 basis points round trip
COST_SENSITIVITY = (0.0010, 0.0015, 0.0025)
STRESS_COST = 0.0025
TRAILING_WINDOW = 60            # valid trading sessions
TRAILING_MIN = 20
MIN_BASKET_BREADTH = 10
EXTREME_PCTL = 0.90
LARGE_GAP_PCTL = 0.75
PERSISTENCE_MIN = 0.80
CANCELLATION_MIN = 0.50
MAX_TRADES_PER_DAY = 4
PRECISION_MIN = 0.60
PRECISION_MIN_SUPPORT = 50

# ---- frozen split ----
DEV_FRACTION = 0.8
FOLDS = [(0, 250, 250, 370), (0, 370, 370, 490), (0, 490, 490, 610), (0, 610, 610, 730)]

PRICE_SCALE = 1e-9  # DBN fixed-point prices


class EtClock:
    """Fast UTC-nanosecond -> Eastern conversion, cached per UTC day.

    Safe because every record this research reads falls between 08:00 and
    16:00 Eastern, far from the 02:00 daylight-saving switch.
    """

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


def side_sign(side) -> float:
    s = str(side)
    if s in ("B", "Side.BID"):
        return 1.0
    if s in ("A", "Side.ASK"):
        return -1.0
    return 0.0
