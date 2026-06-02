"""Canonical scope mapping for the Wolf macro-brain (TODO #20).

Maps any ticker / index / asset name Wolf mentions to a (scope_type, scope_key)
pair so theses are stored and (later) compared at a consistent granularity:

    scope_type in {market, sector, stock, asset}
    scope_key  = canonical identifier (SPX, XLE, NVDA, OIL, GOLD, BONDS, YIELDS, BTC, DXY, ...)

Reuses consensus_engine/data/sector_map.yaml (stock -> sector ETF) for the stock
scope. Does NOT mutate that file (it is load-bearing for the A4 sector gate).
"""
from __future__ import annotations

import os
import yaml

# Whole-market instruments
_MARKET_IDS = {"SPY", "QQQ", "IWM", "SPX", "NDX", "RUT", "VIX", "DIA", "DJIA"}

# R7: index/leveraged-index ETFs proxy to their underlying index so the index and
# its tradable vehicles share ONE thread key. Applied in the market branch only.
_INDEX_PROXY = {
    "SPY": "SPX", "QQQ": "NDX", "IWM": "RUT", "DIA": "DJIA",
    "TQQQ": "NDX", "SQQQ": "NDX",
}

# R7: all semiconductor vehicles unify into the single ('sector','SMH') thread.
# Applied at step 4a (AFTER the market check so it can't steal market symbols).
_SEMIS_UNIFY = {"SMH", "SOX", "SOXX", "SOXL", "SOXS"}

# Inverse ETFs we unify into a base thread above: their WRITTEN direction is the
# OPPOSITE of the base instrument's (SOXS up = semis DOWN; SQQQ up = Nasdaq DOWN), so
# the parser flips it. Without this, an inverse ETF Wolf cites as EVIDENCE for his short
# becomes a phantom opposite-direction thesis that cancels the real one via the flip
# logic. Keep in sync with the inverse symbols in _SEMIS_UNIFY / _INDEX_PROXY.
_INVERSE_PROXY = {"SOXS", "SQQQ"}

# Sector / group ETFs (the 11 SPDR sectors + common industry ETFs Wolf cites)
_SECTOR_ETFS = {
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLC", "XLE", "XLI", "XLU", "XLRE", "XLB",
    "SMH", "SOX", "SOXX", "IGV", "ITA", "XBI", "XOP", "OIH", "KRE", "XRT",
}

# Asset-class instruments -> canonical asset key
_ASSET_MAP = {
    # Oil / energy commodity
    "USO": "OIL", "CL": "OIL", "CL=F": "OIL", "OIL": "OIL", "USOIL": "OIL", "WTI": "OIL", "BRENT": "OIL",
    # Gold
    "GLD": "GOLD", "GC": "GOLD", "GC=F": "GOLD", "GOLD": "GOLD", "XAUUSD": "GOLD", "IAU": "GOLD",
    # Bonds (price)
    "TLT": "BONDS", "IEF": "BONDS", "AGG": "BONDS", "ZN=F": "BONDS", "BONDS": "BONDS",
    # Yields / rates
    "TNX": "YIELDS", "^TNX": "YIELDS", "YIELDS": "YIELDS", "10Y": "YIELDS", "2Y": "YIELDS",
    "30Y": "YIELDS", "US10Y": "YIELDS",
    # Bitcoin
    "BTC": "BTC", "BTCUSD": "BTC", "BTC-USD": "BTC", "IBIT": "BTC", "GBTC": "BTC", "BITCOIN": "BTC",
    # Dollar
    "DXY": "DXY", "^DXY": "DXY", "UUP": "DXY", "DOLLAR": "DXY", "USD": "DXY",
}

# Broad-name aliases (Wolf writes "S&P", "Nasdaq", "the dollar", etc.)
_NAME_ALIASES = {
    "s&p": "SPX", "s&p 500": "SPX", "sp500": "SPX", "sp 500": "SPX", "spx": "SPX", "spooz": "SPX",
    "es": "SPX", "es=f": "SPX",
    "nasdaq": "NDX", "ndx": "NDX", "naz": "NDX", "nq": "NDX", "nq=f": "NDX",
    "nasdaq-100": "NDX", "nasdaq 100": "NDX", "nasdaq100": "NDX", "ndx100": "NDX",
    "russell": "RUT", "russell 2000": "RUT", "small caps": "RUT", "small-caps": "RUT",
    "dow": "DJIA", "dow jones": "DJIA", "djia": "DJIA",
    "semis": "SMH", "semiconductors": "SMH", "sox": "SMH",
    "software": "IGV", "tech": "XLK", "energy": "XLE", "financials": "XLF", "banks": "XLF",
    "oil": "OIL", "crude": "OIL", "gold": "GOLD", "bonds": "BONDS", "treasuries": "BONDS",
    "yields": "YIELDS", "rates": "YIELDS", "the dollar": "DXY", "dollar": "DXY", "dxy": "DXY",
    "bitcoin": "BTC", "btc": "BTC", "vix": "VIX", "volatility": "VIX",
}

_SECTOR_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sector_map.yaml")
_sector_map_cache: dict[str, str] | None = None


def _stock_sector_map() -> dict[str, str]:
    """Load (and cache) the stock->sector-ETF map, dropping the `*_comment` rows."""
    global _sector_map_cache
    if _sector_map_cache is None:
        try:
            with open(_SECTOR_MAP_PATH) as f:
                raw = yaml.safe_load(f).get("mappings", {})
            _sector_map_cache = {
                k.upper(): v for k, v in raw.items() if not k.endswith("_comment")
            }
        except Exception:
            _sector_map_cache = {}
    return _sector_map_cache


def resolve_scope(raw_identifier: str) -> tuple[str, str]:
    """Map a raw ticker/name to (scope_type, scope_key).

    Resolution order: name alias -> asset map -> market -> sector ETF -> known stock
    -> default to stock with the bare uppercased symbol.

    Examples:
        resolve_scope("SPY")  -> ("market", "SPX")   # index ETF proxies to its index
        resolve_scope("S&P")  -> ("market", "SPX")
        resolve_scope("XLE")  -> ("sector", "XLE")
        resolve_scope("SMH")  -> ("sector", "SMH")
        resolve_scope("USO")  -> ("asset", "OIL")
        resolve_scope("NVDA") -> ("stock", "NVDA")
    """
    if not raw_identifier:
        return ("stock", "")
    s = raw_identifier.strip()
    lower = s.lower()
    upper = s.upper()

    # 1. Name alias -> re-resolve the canonical symbol it points at.
    if lower in _NAME_ALIASES:
        canon = _NAME_ALIASES[lower]
        if canon != upper:  # avoid infinite recursion when alias == symbol
            return resolve_scope(canon)
        upper = canon

    # 2. Asset class.
    if upper in _ASSET_MAP:
        return ("asset", _ASSET_MAP[upper])

    # 3. Whole market (with index-ETF proxy: SPY->SPX, QQQ->NDX, TQQQ->NDX, ...).
    if upper in _INDEX_PROXY:
        return ("market", _INDEX_PROXY[upper])
    if upper in _MARKET_IDS:
        return ("market", upper)

    # 4a. Semis unify: all semiconductor vehicles -> ('sector','SMH'). After the
    #     market check so it can never steal a market symbol.
    if upper in _SEMIS_UNIFY:
        return ("sector", "SMH")

    # 4. Sector / group ETF.
    if upper in _SECTOR_ETFS:
        return ("sector", upper)

    # 5. Known individual stock.
    if upper in _stock_sector_map():
        return ("stock", upper)

    # 6. Unknown -> treat as a stock with its bare symbol.
    return ("stock", upper)


def stock_sector_etf(ticker: str) -> str | None:
    """Return the sector ETF for a stock ticker, or None if unknown."""
    return _stock_sector_map().get(ticker.upper())


def is_inverse_proxy(identifier: str) -> bool:
    """True if `identifier` is an inverse ETF that unifies into a base thread, so its
    written direction must be flipped to the base instrument's (SOXS bull = SMH bear)."""
    return (identifier or "").strip().upper() in _INVERSE_PROXY


# FORWARD map (Phase-3 outcomes): a canonical scope_key -> a liquid, yfinance-quotable
# symbol whose daily close proxies the thesis. The inverse of resolve_scope's INTO-canonical
# maps. Sector/stock scope_keys are already real symbols (XLE/SMH/IGV/NVDA) -> pass through.
_SCOPE_PROXY = {
    "SPX": "SPY", "NDX": "QQQ", "NAS100": "QQQ", "RUT": "IWM", "DJIA": "DIA", "VIX": "^VIX",
    "TRANSPORTS": "IYT",
    "OIL": "USO", "GOLD": "GLD", "BONDS": "TLT", "YIELDS": "^TNX", "DXY": "UUP", "BTC": "BTC-USD",
}


def proxy_symbol(scope_type: str, scope_key: str) -> str | None:
    """Return a liquid tradeable symbol for a thesis scope, or None if unmapped.

    None means the outcome scorer leaves the thesis 'inconclusive' (never a false
    win/loss). A known index/macro alias maps via _SCOPE_PROXY regardless of how the
    parser scoped it (NAS100/TRANSPORTS sometimes land as 'stock'); other sector/stock
    keys are already real symbols and pass through.
    """
    key = (scope_key or "").strip().upper()
    if not key:
        return None
    if key in _SCOPE_PROXY:
        return _SCOPE_PROXY[key]
    if scope_type in ("sector", "stock"):
        return key
    return None
