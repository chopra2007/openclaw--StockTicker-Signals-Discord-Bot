"""A4: sector ETF peer-confirmation gate.

check_sector_alignment is called before _classify to verify that the sector
ETF is moving in the same direction as the alert direction. If the sector
ETF is NOT moving in the same direction (and no bypass applies), the signal
should NOT bypass the market gate.

Bypass conditions (any True → pass regardless of ETF movement):
  - catalyst_type in A4_BYPASS_CATALYSTS
  - catalyst_type is empty / unknown / "Market Movement"
  - premarket or after-hours (before 09:35 ET or after 16:00 ET, or weekend)
  - ticker not in sector_map

Shadow-mode: always returns a SectorVerdict; only blocks when feature is
enabled AND all bypass flags are False AND ETF moved in opposite direction.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bypass catalyst set
# ---------------------------------------------------------------------------

A4_BYPASS_CATALYSTS: frozenset[str] = frozenset({
    "M&A", "FDA Approval", "Earnings Beat",
    "Government Contract", "Short Squeeze",
    "Analyst Upgrade", "SEC Filing", "Insider Buying",
    "Guidance Update", "Breaking News",
})

# ---------------------------------------------------------------------------
# YAML sector map loader
# ---------------------------------------------------------------------------

_MAP_PATH = Path(__file__).parent.parent / "data" / "sector_map.yaml"
_sector_map: dict[str, str] | None = None


def _load_sector_map() -> dict[str, str]:
    global _sector_map
    if _sector_map is not None:
        return _sector_map
    if not _MAP_PATH.exists():
        log.warning("[A4] sector_map.yaml not found at %s — all tickers unmapped", _MAP_PATH)
        _sector_map = {}
        return _sector_map
    try:
        import yaml
        with open(_MAP_PATH) as f:
            data = yaml.safe_load(f) or {}
        _sector_map = data.get("mappings", {}) or {}
        return _sector_map
    except Exception as e:
        log.warning("[A4] Failed to load sector_map.yaml: %s — all tickers unmapped", e)
        _sector_map = {}
        return _sector_map


# ---------------------------------------------------------------------------
# ETF quote cache (5-min TTL)
# ---------------------------------------------------------------------------

_etf_cache: dict[str, tuple[float, float]] = {}  # symbol -> (change_pct, expires_at)
_CACHE_TTL = 300.0  # 5 minutes


async def _fetch_etf_change_pct(etf: str) -> float | None:
    """Fetch day change percent for ETF via Finnhub quote.

    Returns None on error. Caches result for 5 minutes.
    """
    now = time.monotonic()
    if etf in _etf_cache:
        change_pct, expires_at = _etf_cache[etf]
        if now < expires_at:
            return change_pct

    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        log.warning("[A4] Finnhub API key missing — cannot fetch ETF quote")
        return None

    url = f"https://finnhub.io/api/v1/quote?symbol={etf}&token={api_key}"
    try:
        from consensus_engine.utils.http import get_session
        session = await get_session()
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                log.warning("[A4] Finnhub quote for %s returned HTTP %s", etf, resp.status)
                return None
            data = await resp.json()
            # Finnhub quote: dp = percent change
            dp = data.get("dp")
            if dp is None:
                log.warning("[A4] Finnhub quote for %s missing 'dp' field: %s", etf, data)
                return None
            change_pct = float(dp)
            _etf_cache[etf] = (change_pct, now + _CACHE_TTL)
            return change_pct
    except Exception as e:
        log.warning("[A4] Failed to fetch ETF quote for %s: %s", etf, e)
        return None


# ---------------------------------------------------------------------------
# Pre-market / after-hours detection
# ---------------------------------------------------------------------------

def _is_off_hours(now_utc: datetime) -> bool:
    """True if now_utc is before 09:35 ET or after 16:00 ET, or a weekend."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore

    et = ZoneInfo("America/New_York")
    now_aware = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    now_et = now_aware.astimezone(et)

    # Weekend
    if now_et.weekday() >= 5:
        return True

    # Before 09:35
    open_time = now_et.replace(hour=9, minute=35, second=0, microsecond=0)
    close_time = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    return now_et < open_time or now_et >= close_time


# ---------------------------------------------------------------------------
# Main verdict dataclass and check function
# ---------------------------------------------------------------------------

@dataclass
class SectorVerdict:
    aligned: bool
    bypass_due_to_catalyst: bool    # True if catalyst_type is in bypass list
    bypass_due_to_unknown: bool     # True if catalyst_type is empty/unknown/Market Movement
    bypass_due_to_premarket: bool   # True if before 09:35 ET / after 16:00 ET
    bypass_due_to_unmapped: bool    # True if ticker not in sector_map
    sector_etf: Optional[str]
    sector_change_pct: Optional[float]
    reason: str  # "aligned" | "blocked" | "bypass_catalyst" | "bypass_unknown" | "bypass_premarket" | "bypass_unmapped" | "disabled"


_DISABLED_VERDICT = SectorVerdict(
    aligned=True,
    bypass_due_to_catalyst=False,
    bypass_due_to_unknown=False,
    bypass_due_to_premarket=False,
    bypass_due_to_unmapped=False,
    sector_etf=None,
    sector_change_pct=None,
    reason="disabled",
)

_UNKNOWN_CATALYSTS = {"", "unknown", "market movement"}


async def check_sector_alignment(
    ticker: str,
    direction: str,      # "long" | "short"
    catalyst_type: str,
    now_utc: datetime,
) -> SectorVerdict:
    """Check if sector ETF moves in same direction as alert direction.

    Returns SectorVerdict. If any bypass flag True → treat as passing.
    On 'blocked': caller should NOT pass A4 into the bypass OR-clause.
    """
    if not cfg.get("features.sector_confirmation.enabled", False):
        return _DISABLED_VERDICT

    # Check catalyst bypass
    bypass_catalyst = catalyst_type in A4_BYPASS_CATALYSTS
    if bypass_catalyst:
        return SectorVerdict(
            aligned=False,
            bypass_due_to_catalyst=True,
            bypass_due_to_unknown=False,
            bypass_due_to_premarket=False,
            bypass_due_to_unmapped=False,
            sector_etf=None,
            sector_change_pct=None,
            reason="bypass_catalyst",
        )

    # Check unknown catalyst bypass
    bypass_unknown = catalyst_type.strip().lower() in _UNKNOWN_CATALYSTS
    if bypass_unknown:
        return SectorVerdict(
            aligned=False,
            bypass_due_to_catalyst=False,
            bypass_due_to_unknown=True,
            bypass_due_to_premarket=False,
            bypass_due_to_unmapped=False,
            sector_etf=None,
            sector_change_pct=None,
            reason="bypass_unknown",
        )

    # Check pre-market / after-hours bypass
    bypass_premarket = _is_off_hours(now_utc)
    if bypass_premarket:
        return SectorVerdict(
            aligned=False,
            bypass_due_to_catalyst=False,
            bypass_due_to_unknown=False,
            bypass_due_to_premarket=True,
            bypass_due_to_unmapped=False,
            sector_etf=None,
            sector_change_pct=None,
            reason="bypass_premarket",
        )

    # Check sector map
    sector_map = _load_sector_map()
    etf = sector_map.get(ticker.upper())
    if etf is None:
        return SectorVerdict(
            aligned=False,
            bypass_due_to_catalyst=False,
            bypass_due_to_unknown=False,
            bypass_due_to_premarket=False,
            bypass_due_to_unmapped=True,
            sector_etf=None,
            sector_change_pct=None,
            reason="bypass_unmapped",
        )

    # Fetch ETF change
    threshold = cfg.get("features.sector_confirmation.sector_change_threshold_pct", 0.3)
    change_pct = await _fetch_etf_change_pct(etf)

    if change_pct is None:
        # Can't fetch ETF — treat as unmapped bypass
        return SectorVerdict(
            aligned=False,
            bypass_due_to_catalyst=False,
            bypass_due_to_unknown=False,
            bypass_due_to_premarket=False,
            bypass_due_to_unmapped=True,
            sector_etf=etf,
            sector_change_pct=None,
            reason="bypass_unmapped",
        )

    # Determine alignment
    direction_lower = direction.lower()
    if direction_lower == "long":
        aligned = change_pct > threshold
    elif direction_lower == "short":
        aligned = change_pct < -threshold
    else:
        # neutral — bypass
        return SectorVerdict(
            aligned=True,
            bypass_due_to_catalyst=False,
            bypass_due_to_unknown=True,
            bypass_due_to_premarket=False,
            bypass_due_to_unmapped=False,
            sector_etf=etf,
            sector_change_pct=change_pct,
            reason="bypass_unknown",
        )

    reason = "aligned" if aligned else "blocked"
    log.info(
        "[A4] $%s direction=%s etf=%s change=%.2f%% threshold=%.2f%% → %s",
        ticker, direction, etf, change_pct, threshold, reason,
    )

    return SectorVerdict(
        aligned=aligned,
        bypass_due_to_catalyst=False,
        bypass_due_to_unknown=False,
        bypass_due_to_premarket=False,
        bypass_due_to_unmapped=False,
        sector_etf=etf,
        sector_change_pct=change_pct,
        reason=reason,
    )
