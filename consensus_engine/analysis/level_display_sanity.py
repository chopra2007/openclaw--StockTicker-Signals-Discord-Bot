"""Shared display-time level sanity gate (item C, deep-dive-2026-06-08).

One place that answers "is this stored price level sane vs today's price?" right before a
level is shown to a user (#brief, #news confluence) or saved (Wolf thesis merge). It exists
because fabricated/transposed levels (NVDA 850 on a $208 stock, SMH 12,616 on a ~$280 ETF)
reached users. Separate from price_sanity.py — that module's split-factor forgiveness is the
exact loophole here, and the YouTube save path depends on it, so we don't touch it.

Gate (USER 2026-06-08): DROP if the level is >= 2.0x or <= 0.5x the live price. Keep the
<$5 penny exemption (!all uses it — penny names have real 2-4x targets). Index/commodity
scopes have no Finnhub quote, so a wide per-scope magnitude band (_INDEX_RANGE) fail-CLOSES
the order-of-magnitude class without gating real levels. Equities with no quote fail-OPEN.
"""
from __future__ import annotations

import enum
import logging
import time

from consensus_engine.api_adapters import get_live_quote_price

log = logging.getLogger(__name__)


class LevelVerdict(enum.Enum):
    KEEP = "keep"        # plausible vs live price, or penny-exempt, or no anchor + in-band
    DROP = "drop"        # >= _MAX_RATIO or <= 1/_MAX_RATIO off live, OR index-range fail
    SUSPECT = "suspect"  # equity with no live anchor — kept but logged


_MAX_RATIO = 2.0            # USER 2026-06-08: drop if level/live >= 2.0 or <= 0.5
_PENNY_SKIP_PRICE = 5.0     # mirror all_command levels._SCORE_V2_PENNY_SKIP_PRICE

# Known non-equity / index / commodity scopes -> a WIDE plausible RANGE for the value
# itself. These either have NO Finnhub /quote (true indices: SOX/SPX/NDX/RUT/DJIA/VIX/OIL/
# GOLD/BONDS/YIELDS/DXY) or are ETFs whose quote may be momentarily None (SMH/IGV/XL*/
# SPY/QQQ/IWM/URA). Ranges are deliberately an order of magnitude wide — they only ever
# catch the magnitude-mistake class (SMH 12,616, GOLD 21,000), never a real level.
# MUST cover every index/commodity key in wolf_news._SCOPE_DISPLAY (asserted by a unit test).
_INDEX_RANGE = {
    "SMH": (150, 400), "SOX": (3000, 8000), "NDX": (12000, 30000), "SPX": (3000, 8000),
    "RUT": (1500, 4000), "DJIA": (25000, 55000), "VIX": (8, 95), "OIL": (20, 160),
    "GOLD": (1000, 5000), "BONDS": (5, 200), "YIELDS": (0.5, 20), "DXY": (80, 130),
    "BTC": (10000, 250000), "IGV": (40, 250), "XLE": (40, 200), "XLF": (20, 120),
    "XLK": (100, 400), "XLV": (60, 250),
    # Extra liquid ETFs that show up as Wolf scopes (have quotes; band is belt-and-suspenders).
    "SPY": (300, 800), "QQQ": (250, 800), "IWM": (120, 400), "URA": (15, 80),
}
# Scopes with genuinely unbounded upside — fail-OPEN above the band (drop only below floor).
_UNBOUNDED_UP = {"BTC"}

# tiny shared (ticker -> (price, ts)) quote cache so C's surfaces + A's guard don't fan out
# Finnhub calls; ~60s TTL.
_quote_cache: dict[str, tuple[float | None, float]] = {}
_QUOTE_TTL = 60.0


async def _cached_quote(ticker: str) -> float | None:
    now = time.time()
    hit = _quote_cache.get(ticker)
    if hit is not None and (now - hit[1]) < _QUOTE_TTL:
        return hit[0]
    price = await get_live_quote_price(ticker)
    _quote_cache[ticker] = (price, now)
    return price


async def classify_level(ticker: str, level_price: float,
                         live_price: float | None = None) -> LevelVerdict:
    """Tri-state plausibility of one stored level for `ticker` at today's price."""
    try:
        lp = float(level_price)
    except (TypeError, ValueError):
        return LevelVerdict.DROP
    if lp <= 0:
        return LevelVerdict.DROP

    tk = (ticker or "").upper()

    if live_price is None:
        live_price = await _cached_quote(tk)

    if live_price and live_price > 0:
        # Penny exemption: <$5 names have real multi-bagger targets (!all exempts them).
        if live_price < _PENNY_SKIP_PRICE:
            return LevelVerdict.KEEP
        ratio = lp / live_price
        if ratio >= _MAX_RATIO or ratio <= 1.0 / _MAX_RATIO:
            return LevelVerdict.DROP
        return LevelVerdict.KEEP

    # No live anchor (Finnhub miss OR a true non-tradeable index/commodity scope).
    rng = _INDEX_RANGE.get(tk)
    if rng is not None:
        lo, hi = rng
        if lp < lo:
            return LevelVerdict.DROP
        if lp > hi:
            # unbounded-upside scopes (BTC): fail-open above the band; drop only if absurd (>10x ceiling)
            if tk in _UNBOUNDED_UP:
                return LevelVerdict.DROP if lp > hi * 10 else LevelVerdict.KEEP
            return LevelVerdict.DROP
        return LevelVerdict.KEEP
    # Unknown ticker, no quote -> fail-open but flag (matches the YouTube path's fail-open).
    return LevelVerdict.SUSPECT


async def filter_levels_for_display(ticker: str, levels, live_price: float | None = None):
    """Return (kept_levels, dropped_count). One quote fetch per ticker (shared cache)."""
    tk = (ticker or "").upper()
    if live_price is None:
        live_price = await _cached_quote(tk)
    kept, dropped = [], 0
    fail_open_logged = False
    for lv in levels:
        price = lv["price"] if isinstance(lv, dict) else lv
        v = await classify_level(tk, price, live_price=live_price)
        if v is LevelVerdict.DROP:
            dropped += 1
            log.warning("level_display_sanity: dropped %s level %s (live=%s)", tk, price, live_price)
        else:
            if v is LevelVerdict.SUSPECT and not fail_open_logged:
                log.warning("level_display_sanity: fail-open kept %s level (no live anchor)", tk)
                fail_open_logged = True
            kept.append(lv)
    return kept, dropped
