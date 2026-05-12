"""A-T0 calendar-context filter for price-level anchors.

A YouTube transcript line like "our number one draft pick for Q2 of 2024 is
Microsoft" has Gemini extracting `price=2024.0, level_type=target` for $MSFT
because the year happens to be in valid integer range. This filter rejects
that class of leak by treating 4-digit integers in the calendar window
(1900–2100) as suspicious when the surrounding snippet contains explicit
date markers (Q1/Q2/Q3/Q4, fiscal/FY, month names, "in", "by").

Carve-outs:
  * Stock tickers whose live price legitimately sits in (1500, 2300) get
    a per-ticker pass (BRK.A, NVR, AZO, BKNG, MKL, BOOK, SEB).
  * Asset-aware backstop: if `abs(price - current_price) / current_price`
    is under 5%, we assume Gemini got it right regardless of context.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("consensus_engine.analysis.calendar_filter")

# Tickers whose live prices legitimately land in (1500, 2300). If you add
# more, keep the list short and conservative — every entry weakens the
# year-range filter for that ticker.
_HIGH_PRICED_TICKERS: frozenset[str] = frozenset({
    "BRK.A", "BRK-A", "BRKA",
    "NVR", "AZO", "BKNG", "MKL", "BOOK", "SEB",
})

_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
)

_CALENDAR_MARKERS = re.compile(
    r"\bQ[1-4]\b"
    r"|\bfiscal\b"
    r"|\bFY\b"
    r"|\bby\b"
    r"|\bin\b"
    r"|\b(?:" + "|".join(_MONTHS) + r")\b",
    re.IGNORECASE,
)

_ASSET_PROXIMITY_PCT = 0.05  # within 5% of spot → allow regardless of context


def is_calendar_year_in_context(
    price: float,
    snippet: str | None,
    ticker: str,
    current_price: float | None = None,
) -> bool:
    """True iff `price` looks like a calendar year mis-extracted as a price.

    Rejection conditions (all must hold):
      1. `price` is an integer (no fractional cents) in [1900, 2100].
      2. `snippet` contains a calendar marker (Q1-Q4, fiscal, FY, by, in, month name).
      3. Ticker is not in `_HIGH_PRICED_TICKERS`.
      4. If `current_price` is provided, the price is NOT within ±5% of spot.

    Returns False (allow the level) when any of the above fails.
    """
    if not isinstance(price, (int, float)):
        return False
    if not (1900 <= price <= 2100):
        return False
    if abs(price - round(price)) > 1e-6:
        return False  # fractional like 1999.50 is a real price, not a year

    ticker_norm = (ticker or "").upper()
    if ticker_norm in _HIGH_PRICED_TICKERS:
        return False

    if current_price and current_price > 0:
        if abs(price - current_price) / current_price < _ASSET_PROXIMITY_PCT:
            return False  # asset-aware backstop

    if not snippet:
        return False

    return bool(_CALENDAR_MARKERS.search(snippet))
