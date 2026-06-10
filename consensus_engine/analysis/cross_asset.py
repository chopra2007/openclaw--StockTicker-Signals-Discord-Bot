"""E2 — cross-asset regime confirm/veto multiplier (VIX term-structure leg).

Purpose: Apply a bounded confidence multiplier to already-triggered BULLISH
alerts. A calm VIX term-structure (steep contango) provides mild confirmation;
a stressed structure (backwardation) is a caution flag that widens the effective
STRONG cutoff. This is a REGIME FLAG, not a directional predictor.

CRITICAL design principle (verified Pass-3 trap):
  VIX backwardation often precedes a bounce. Backwardation does NOT mean the
  market will fall. The multiplier therefore NEVER generates a "market will
  fall" signal. It only modulates the confirmation threshold for bullish alerts:
  backwardation -> raise the bar a bit (veto direction, multiplier toward 0.85);
  steep contango (calm) -> modest confirmation (multiplier toward 1.15).

VIX term ratio = spot_VIX / VIX3M_spot (both from yfinance ^VIX / ^VIX3M).
  ratio > 1.0  (backwardation, stressed)  -> multiplier drifts toward veto_floor
  ratio < 1.0  (contango, calm)           -> multiplier drifts toward confirm_ceiling
  ratio ~ 1.0  (neutral band)             -> multiplier stays near 1.0

Multiplier bounds (from config/consensus.yaml features.cross_asset):
  veto_floor:      0.85  (minimum — backwardation can never exceed this penalty)
  confirm_ceiling: 1.15  (maximum — contango can never exceed this boost)

Caching: fetched once per TTL_MINUTES (15 min). A stale cache (recency_window
`is_fresh("vix", ...)` returns False — cap 1440 min) degrades to 1.0 (no-op).
On any fetch error: return 1.0 and log once.

Flag: features.cross_asset.enabled (False by default, force-off in conftest).
Flag OFF -> get_multiplier() returns 1.0 unconditionally (byte-identical path).

FRED/HY-credit leg: NOT BUILT in this version.
  The plan reserves `features.cross_asset.fred_leg_enabled` as a future key.
  There is NO code behind it here. Reason: no FRED API key exists in this
  environment (as of signal-features-2026-06-09 build), and the plan explicitly
  forbids shipping dead data paths before access is verified. The key is a
  config placeholder only. When a FRED key is obtained, build a second leg
  following the same TTL-cache + recency_window + failure=1.0 pattern.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine.analysis.recency_window import is_fresh

log = logging.getLogger("consensus_engine.analysis.cross_asset")

# ---------------------------------------------------------------------------
# Module-level cache (shared across one process lifetime; TTL prevents staleness)
# ---------------------------------------------------------------------------

_TTL_MINUTES: float = 15.0

_cache: dict = {
    "ratio": None,          # float | None
    "multiplier": None,     # float | None
    "fetched_at": None,     # datetime (UTC) | None
}

# Suppress repeated fetch-error logs within a TTL window
_last_error_logged_at: Optional[datetime] = None
_ERROR_SUPPRESS_MIN: float = 15.0


def _log_fetch_error_once(msg: str, *args) -> None:
    global _last_error_logged_at
    now = datetime.now(timezone.utc)
    if _last_error_logged_at is not None:
        age_min = (now - _last_error_logged_at).total_seconds() / 60.0
        if age_min < _ERROR_SUPPRESS_MIN:
            return
    _last_error_logged_at = now
    log.warning(msg, *args)


# ---------------------------------------------------------------------------
# VIX fetch (synchronous, runs in executor)
# ---------------------------------------------------------------------------

def _fetch_vix_ratio() -> Optional[float]:
    """Blocking yfinance fetch for ^VIX and ^VIX3M. Returns ratio or None on error.

    Imported and called only from the async path via run_in_executor so it never
    blocks the event loop — matching the options.py pattern.
    """
    try:
        import yfinance as yf
        vix_hist = yf.Ticker("^VIX").history(period="2d")
        vix3m_hist = yf.Ticker("^VIX3M").history(period="2d")

        if vix_hist.empty or vix3m_hist.empty:
            return None

        vix_spot = float(vix_hist["Close"].iloc[-1])
        vix3m_spot = float(vix3m_hist["Close"].iloc[-1])

        if vix3m_spot <= 0:
            return None

        return vix_spot / vix3m_spot
    except Exception as exc:
        # Bubble None; caller handles error logging and fallback
        log.debug("[E2] _fetch_vix_ratio error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Multiplier math
# ---------------------------------------------------------------------------

def _ratio_to_multiplier(ratio: float) -> float:
    """Map VIX/VIX3M ratio to a bounded confidence multiplier.

    Design (from plan §2 Wave 4 E2):
    - ratio > 1.0 (backwardation) -> multiplier < 1.0, floor = veto_floor (0.85)
    - ratio < 1.0 (contango)      -> multiplier > 1.0, ceil = confirm_ceiling (1.15)
    - ratio == 1.0                -> 1.0

    The mapping is linear, symmetric around 1.0, clamped:
      raw = 1.0 + (1.0 - ratio) * scale
      multiplier = clamp(raw, veto_floor, confirm_ceiling)

    where scale is derived from the config bounds so the extremes of each
    configured bound are reached at a "natural" ratio swing.  A swing of +/-0.15
    in ratio (e.g. 1.0 -> 1.15 or 1.0 -> 0.85) produces the full bound:
      scale = (confirm_ceiling - 1.0) / 0.15  (default: 0.15/0.15 = 1.0)
    This gives a simple 1:1 linear mapping with the default config, and scales
    with custom veto_floor/confirm_ceiling values.

    The scale parameter keeps the math self-consistent when users change the
    floor/ceiling in config.
    """
    veto_floor = float(cfg.get("features.cross_asset.veto_floor", 0.85))
    confirm_ceiling = float(cfg.get("features.cross_asset.confirm_ceiling", 1.15))

    # Derive the linear scale so the full range is hit at ratio +/-0.15 swing.
    # confirm_ceiling - 1.0 is the "upside" travel; veto side mirrors it.
    upside = confirm_ceiling - 1.0    # e.g. 0.15
    downside = 1.0 - veto_floor       # e.g. 0.15
    reference_swing = 0.15            # ratio swing that produces the full bound

    # ratio < 1 (calm/contango) -> 1-ratio > 0 -> raw > 1 -> toward ceiling
    # ratio > 1 (stressed/backwardation) -> 1-ratio < 0 -> raw < 1 -> toward floor
    delta = 1.0 - ratio

    if delta >= 0:
        # contango side — scale by upside
        scale = upside / reference_swing
    else:
        # backwardation side — scale by downside (may differ from upside if asymmetric config)
        scale = downside / reference_swing

    raw = 1.0 + delta * scale
    return max(veto_floor, min(confirm_ceiling, raw))


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def get_multiplier(executor=None) -> float:
    """Return the current cross-asset confidence multiplier.

    Returns 1.0 (no-op) when:
    - features.cross_asset.enabled is False
    - fetch fails
    - cached value is stale per recency_window.is_fresh("vix", ...)
    """
    if not cfg.get("features.cross_asset.enabled", False):
        return 1.0

    now = datetime.now(timezone.utc)

    # Check cache validity
    cached_ratio = _cache["ratio"]
    cached_mul = _cache["multiplier"]
    fetched_at = _cache["fetched_at"]

    cache_hit = (
        cached_ratio is not None
        and cached_mul is not None
        and fetched_at is not None
        and (now - fetched_at).total_seconds() / 60.0 <= _TTL_MINUTES
    )

    if not cache_hit:
        # Fetch fresh ratio in executor (blocking yfinance call)
        loop = asyncio.get_running_loop()
        try:
            if executor is not None:
                ratio = await loop.run_in_executor(executor, _fetch_vix_ratio)
            else:
                ratio = await loop.run_in_executor(None, _fetch_vix_ratio)
        except Exception as exc:
            _log_fetch_error_once("[E2] VIX fetch error — returning multiplier 1.0 (no-op): %s", exc)
            return 1.0

        if ratio is None:
            _log_fetch_error_once("[E2] VIX data unavailable — returning multiplier 1.0 (no-op)")
            return 1.0

        multiplier = _ratio_to_multiplier(ratio)
        _cache["ratio"] = ratio
        _cache["multiplier"] = multiplier
        _cache["fetched_at"] = now

        log.info("[E2 shadow] vix_term ratio=%.3f multiplier=%.3f", ratio, multiplier)
        return multiplier

    # Cache hit — check recency_window freshness (cap 1440 min for VIX source)
    if not is_fresh("vix", fetched_at):
        log.debug("[E2] cached VIX value is stale per recency_window — returning 1.0")
        return 1.0

    # Cache is fresh — emit shadow log on each use
    log.info("[E2 shadow] vix_term ratio=%.3f multiplier=%.3f (cached)", cached_ratio, cached_mul)
    return cached_mul


def clear_cache() -> None:
    """Clear the module-level cache. Used in tests to reset state between cases."""
    _cache["ratio"] = None
    _cache["multiplier"] = None
    _cache["fetched_at"] = None
