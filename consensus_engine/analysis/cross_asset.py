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

FRED/HY-credit leg (built 2026-06-15, gated by features.cross_asset.fred_leg_enabled):
  A second regime leg from the ICE BofA US High-Yield Option-Adjusted Spread
  (FRED series BAMLH0A0HYM2 — the standard credit-stress gauge, daily, % pts).
  credit ratio = latest_spread / trailing-60d baseline (excl. latest).
    ratio > 1.0  (spreads WIDER than recent normal, credit stress) -> veto side
    ratio < 1.0  (spreads TIGHTER, calm)                           -> confirm side
  Same TTL-cache + recency_window + failure=no-op pattern as the VIX leg. Reads
  FRED_API_KEY from the environment (set in .env.service). Missing key, fetch
  error, insufficient history, or a stale latest observation -> leg is a no-op
  (None), and get_multiplier falls back to the VIX leg alone (never dilutes a
  live leg with a neutral placeholder).

Combining the two legs (when fred_leg_enabled): average the available legs, then
  clamp to [veto_floor, confirm_ceiling]. An unavailable leg (None) is dropped,
  not averaged in as 1.0 — so missing credit data can never weaken a real VIX
  veto, and vice-versa.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine.analysis.recency_window import is_fresh

log = logging.getLogger("consensus_engine.analysis.cross_asset")

# --- FRED credit-spread leg constants ---
_FRED_SERIES = "BAMLH0A0HYM2"   # ICE BofA US High-Yield Index Option-Adjusted Spread (daily, % pts)
_FRED_BASELINE_DAYS = 60        # trailing obs (excl. latest) defining the "recent normal" baseline
_FRED_MIN_DAYS = 20             # need at least this many obs to form a baseline, else no-op
_FRED_MAX_OBS_AGE_DAYS = 8      # latest FRED obs older than this -> no-op (tolerates the ~1-2 business-day publish lag)

# ---------------------------------------------------------------------------
# Module-level cache (shared across one process lifetime; TTL prevents staleness)
# ---------------------------------------------------------------------------

_TTL_MINUTES: float = 15.0

_cache: dict = {
    "ratio": None,          # float | None
    "multiplier": None,     # float | None
    "fetched_at": None,     # datetime (UTC) | None
}

# Separate cache for the FRED credit-spread leg (same shape/TTL as the VIX cache).
_credit_cache: dict = {
    "ratio": None,
    "multiplier": None,
    "fetched_at": None,
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
        from consensus_engine.utils import prices  # #57 Schwab ($VIX) primary, yfinance fallback
        vix_hist = prices.fetch_history("^VIX", period="2d")
        vix3m_hist = prices.fetch_history("^VIX3M", period="2d")

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


def _obs_recent_enough(date_str: str) -> bool:
    """True if a FRED observation date (YYYY-MM-DD) is within the publish-lag tolerance.

    FRED daily macro series lag ~1-2 business days, so on a Monday the latest obs is
    typically the prior Friday — that is fine. A gap larger than _FRED_MAX_OBS_AGE_DAYS
    means the series stopped updating; treat the leg as unavailable.
    """
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        return (date.today() - date(y, m, d)).days <= _FRED_MAX_OBS_AGE_DAYS
    except Exception:
        return False


def _fetch_credit_ratio() -> Optional[float]:
    """Blocking FRED fetch for HY credit-spread OAS. Returns current/baseline ratio or None.

    ratio > 1.0 -> spreads WIDER than the trailing baseline (credit stress) -> veto side
    ratio < 1.0 -> spreads TIGHTER than baseline (calm)                     -> confirm side
    Mirrors _fetch_vix_ratio: runs in an executor, returns None on any problem
    (missing key, HTTP error, too little history, stale series). Caller defaults
    a None to a no-op leg.
    """
    key = os.environ.get("FRED_API_KEY")
    if not key:
        log.debug("[E2 fred] FRED_API_KEY not set — credit leg unavailable")
        return None
    try:
        q = urllib.parse.urlencode({
            "series_id": _FRED_SERIES,
            "api_key": key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(_FRED_BASELINE_DAYS + 30),
        })
        url = f"https://api.stlouisfed.org/fred/series/observations?{q}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.load(resp)
        obs = [o for o in data.get("observations", []) if o.get("value") not in (".", "", None)]
        if len(obs) < _FRED_MIN_DAYS + 1:
            return None
        if not _obs_recent_enough(obs[0].get("date", "")):
            log.debug("[E2 fred] latest FRED obs %s too old — credit leg no-op", obs[0].get("date"))
            return None
        vals = [float(o["value"]) for o in obs]
        current = vals[0]
        window = vals[1:1 + _FRED_BASELINE_DAYS]
        if len(window) < _FRED_MIN_DAYS:
            return None
        baseline = sum(window) / len(window)
        if baseline <= 0:
            return None
        return current / baseline
    except Exception as exc:
        log.debug("[E2 fred] _fetch_credit_ratio error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Multiplier math
# ---------------------------------------------------------------------------

def _ratio_to_multiplier(ratio: float, reference_swing: float = 0.15) -> float:
    """Map a stress ratio to a bounded confidence multiplier.

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
    # reference_swing = ratio swing that produces the full bound. Caller passes the
    # source-appropriate value: 0.15 for VIX (rarely moves >15%), wider for credit
    # (HY spreads routinely swing further off their own baseline).

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

async def _get_vix_multiplier(executor=None) -> Optional[float]:
    """VIX-term-structure leg. Returns the multiplier, or None when unavailable
    (fetch error / no data / stale cache). The caller decides how a None is handled."""
    now = datetime.now(timezone.utc)

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
        loop = asyncio.get_running_loop()
        try:
            ratio = await loop.run_in_executor(executor, _fetch_vix_ratio)
        except Exception as exc:
            _log_fetch_error_once("[E2] VIX fetch error — leg no-op: %s", exc)
            return None
        if ratio is None:
            _log_fetch_error_once("[E2] VIX data unavailable — leg no-op")
            return None
        multiplier = _ratio_to_multiplier(ratio)
        _cache["ratio"] = ratio
        _cache["multiplier"] = multiplier
        _cache["fetched_at"] = now
        log.info("[E2 shadow] vix_term ratio=%.3f multiplier=%.3f", ratio, multiplier)
        return multiplier

    if not is_fresh("vix", fetched_at):
        log.debug("[E2] cached VIX value is stale per recency_window — leg no-op")
        return None

    log.info("[E2 shadow] vix_term ratio=%.3f multiplier=%.3f (cached)", cached_ratio, cached_mul)
    return cached_mul


async def _get_credit_multiplier(executor=None) -> Optional[float]:
    """FRED HY credit-spread leg. Returns the multiplier, or None when unavailable
    (missing key / fetch error / too little history / stale series / stale cache)."""
    swing = float(cfg.get("features.cross_asset.fred_reference_swing", 0.40))
    now = datetime.now(timezone.utc)

    cached_ratio = _credit_cache["ratio"]
    cached_mul = _credit_cache["multiplier"]
    fetched_at = _credit_cache["fetched_at"]

    cache_hit = (
        cached_ratio is not None
        and cached_mul is not None
        and fetched_at is not None
        and (now - fetched_at).total_seconds() / 60.0 <= _TTL_MINUTES
    )

    if not cache_hit:
        loop = asyncio.get_running_loop()
        try:
            ratio = await loop.run_in_executor(executor, _fetch_credit_ratio)
        except Exception as exc:
            _log_fetch_error_once("[E2 fred] credit fetch error — leg no-op: %s", exc)
            return None
        if ratio is None:
            return None
        multiplier = _ratio_to_multiplier(ratio, reference_swing=swing)
        _credit_cache["ratio"] = ratio
        _credit_cache["multiplier"] = multiplier
        _credit_cache["fetched_at"] = now
        log.info("[E2 shadow] credit_oas ratio=%.3f multiplier=%.3f", ratio, multiplier)
        return multiplier

    if not is_fresh("fred", fetched_at):
        log.debug("[E2 fred] cached credit value is stale per recency_window — leg no-op")
        return None

    log.info("[E2 shadow] credit_oas ratio=%.3f multiplier=%.3f (cached)", cached_ratio, cached_mul)
    return cached_mul


async def get_multiplier(executor=None) -> float:
    """Return the current cross-asset confidence multiplier (clamped to the bounds).

    Modes controlled by features.cross_asset.{enabled, shadow}:
      enabled=True,  shadow=any  -> apply multiplier to live score (existing behaviour)
      enabled=False, shadow=True -> SHADOW-ONLY: compute VIX+credit, log a
                                    '[E2 shadow]' line with ratio/multiplier/would-cross,
                                    return 1.0 so the live score is NOT affected
      enabled=False, shadow=False -> do nothing; return 1.0 with no compute

    With fred_leg_enabled, the VIX and credit legs are averaged and re-clamped;
    an unavailable leg is dropped (never averaged in as a neutral 1.0), so missing
    data on one leg can't weaken a live signal on the other.
    """
    enabled = cfg.get("features.cross_asset.enabled", False)
    shadow = cfg.get("features.cross_asset.shadow", True)

    if not enabled and not shadow:
        return 1.0

    vix_mult = await _get_vix_multiplier(executor)

    fred_enabled = cfg.get("features.cross_asset.fred_leg_enabled", False)
    if fred_enabled:
        credit_mult = await _get_credit_multiplier(executor)
        legs = [m for m in (vix_mult, credit_mult) if m is not None]
    else:
        credit_mult = None
        legs = [vix_mult] if vix_mult is not None else []

    if not legs:
        combined = 1.0
    elif len(legs) == 1:
        combined = legs[0]
    else:
        veto_floor = float(cfg.get("features.cross_asset.veto_floor", 0.85))
        confirm_ceiling = float(cfg.get("features.cross_asset.confirm_ceiling", 1.15))
        combined = max(veto_floor, min(confirm_ceiling, sum(legs) / len(legs)))
        log.info("[E2 shadow] combined vix=%.3f credit=%.3f -> %.3f", vix_mult, credit_mult, combined)

    # #55 Build A: persist the daily cross-asset ratios/multipliers (the SAME values
    # the [E2 shadow] lines show) — once per UTC day, in BOTH live (enabled) and
    # shadow modes. The FRED HY-credit ratio is point-in-time and CANNOT be
    # backfilled (FRED serves only a rolling ~3yr window), so every unlogged day is
    # gone. The DB helper is idempotent per UTC day, so this per-alert hot path
    # writes at most one row/day. Wrapped so a DB problem can NEVER raise into the
    # engine path. Skip when both legs are unavailable (no real data → no null row).
    if vix_mult is not None or credit_mult is not None:
        try:
            from consensus_engine import db as _db
            await _db.insert_cross_asset_shadow(
                vix_term_ratio=_cache["ratio"],
                vix_term_multiplier=vix_mult,
                credit_oas_ratio=_credit_cache["ratio"],
                credit_oas_multiplier=credit_mult,
                combined_multiplier=combined,
            )
        except Exception as exc:  # never propagate into the live engine loop
            log.debug("[E2] cross_asset_shadow persist failed: %s", exc)

    if not enabled:
        # Shadow-only: log the would-have-applied verdict but return 1.0
        high = float(cfg.get("precision_engine.thresholds.high_confidence", 80))
        # "would-cross" means the multiplier meaningfully changes classification odds;
        # flag when it would push a score from below to above the STRONG threshold.
        # We can't know the caller's score here, so log the threshold context only.
        log.info(
            "[E2 shadow-only] vix_mult=%s credit_mult=%s combined=%.3f "
            "(would_apply=False; strong_threshold=%.0f)",
            f"{vix_mult:.3f}" if vix_mult is not None else "N/A",
            f"{credit_mult:.3f}" if credit_mult is not None else "N/A",
            combined,
            high,
        )
        return 1.0

    return combined


def clear_cache() -> None:
    """Clear both module-level caches. Used in tests to reset state between cases."""
    for c in (_cache, _credit_cache):
        c["ratio"] = None
        c["multiplier"] = None
        c["fetched_at"] = None
