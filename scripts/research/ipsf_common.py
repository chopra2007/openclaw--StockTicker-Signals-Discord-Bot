#!/usr/bin/env python3
"""Shared constants and readers for the immediate-profitable-share-feature work.

Local files only. No network, no API key, no spend.

Clock note: the DBN one-minute bars are stamped at the START of the bar, so the
bar stamped 09:30 Eastern covers 09:30:00-09:30:59. Market maths uses Eastern
because that is what the exchange runs on; every number the owner sees is
labelled Pacific.
"""

from pathlib import Path

RES_DIR = Path(
    "/home/openclaw/.openclaw/workspace/.omc/research/immediate-profitable-share-feature"
)

SEED = 20260828

# Regular trading hours, minute-of-day Eastern, bar stamped at its start.
MIN_OPEN = 9 * 60 + 30      # 09:30
MIN_RTH_LAST = 15 * 60 + 59  # 15:59 bar closes the session

# Thirty-minute blocks of the regular session, by their first minute.
BLOCK_STARTS = [MIN_OPEN + 30 * i for i in range(13)]  # 09:30 .. 15:30
# Method 1 excludes the first and the final block.
METHOD1_BLOCKS = BLOCK_STARTS[1:-1]  # 10:00 .. 15:00 -> eleven blocks

CHRONO_SPLIT_DEV_DATES = 672  # first 672 dates develop; last 182 stay sealed
SEALED_DATES = 182
