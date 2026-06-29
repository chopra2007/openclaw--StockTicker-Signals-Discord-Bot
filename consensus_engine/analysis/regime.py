"""A5: daily realized-volatility z-score regime tagger.

Classifies the current volatility regime as calm/normal/elevated/panic.
Used by engine._classify to shift the high_confidence threshold.

Cold start: returns label='normal', threshold_shift=0 until regime_daily
has at least cold_start_min_days rows.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)


@dataclass
class RegimeContext:
    label: str           # "calm" | "normal" | "elevated" | "panic"
    z_score: float       # EMA(5)-smoothed z-score
    threshold_shift: int # int to add to high_confidence threshold
    cold_start: bool     # True until regime_daily has >=30 rows
    as_of_date: str      # YYYY-MM-DD
    # --- F3 price-trend leg (final-plan.md §2.3). All default to None so the
    # A5 vol-regime behaviour is byte-identical when features.trend_regime is OFF.
    trend_state: Optional[str] = None        # "green" | "yellow" | "red"
    trend_close: Optional[float] = None      # latest index close
    sma_200: Optional[float] = None
    sma_50: Optional[float] = None
    sma_50_slope: Optional[float] = None     # fractional 50DMA slope over slope_window
    tsmom_3m: Optional[float] = None         # 63-trading-day total return
    dist_200_z: Optional[float] = None       # distance-to-200DMA z-score
    trend_as_of_date: Optional[str] = None   # YYYY-MM-DD of the trend_daily row
    trend_cold_start: bool = True            # True until a fresh trend_daily row exists


_COLD_START = RegimeContext(label="normal", z_score=0.0, threshold_shift=0, cold_start=True, as_of_date="")


def _apply_graduated_widening(label: str, z_smooth: float, base_shift: int) -> int:
    """I14-widening: for panic regime, scale shift with z_smooth above panic_z.

    Flag features.regime_widening_graduated.enabled must be True; otherwise
    returns base_shift unchanged (byte-identical to legacy behaviour).

    Formula: shift = base_panic_shift + slope * (z_smooth - panic_z)
    Clamped to min(max_shift, cutoff_ceiling - base_high).
    Non-panic labels always return base_shift.
    """
    if not cfg.get("features.regime_widening_graduated.enabled", False):
        return base_shift
    if label != "panic":
        return base_shift

    panic_z = cfg.get("features.regime_classifier.panic_z", 1.5)
    shifts = cfg.get("features.regime_classifier.regime_shifts", {"calm": -5, "elevated": 5, "panic": 10})
    base_panic_shift = shifts.get("panic", 10)
    slope = cfg.get("features.regime_widening_graduated.slope", 2.5)
    max_shift = cfg.get("features.regime_widening_graduated.max_shift", 15)
    cutoff_ceiling = cfg.get("features.regime_widening_graduated.cutoff_ceiling", 90)
    base_high = cfg.get("precision_engine.thresholds.high_confidence", 80)

    raw = base_panic_shift + slope * (z_smooth - panic_z)
    # Cap 1: absolute shift ceiling
    clamped = min(raw, max_shift)
    # Cap 2: base_high + shift must not exceed cutoff_ceiling
    ceiling_cap = cutoff_ceiling - base_high
    shift = int(min(clamped, ceiling_cap))
    return shift


async def lookup_regime(now_utc: Optional[datetime] = None) -> RegimeContext:
    """Read most recent regime_daily row, then attach the F3 trend leg.

    The vol-regime portion is unchanged from A5. When features.trend_regime is
    OFF the returned context is the exact same object the vol path produced, so
    A5 behaviour is byte-identical. When ON, the trend fields from trend_daily
    are layered on without touching any vol field.
    """
    ctx = await _lookup_vol_regime(now_utc)
    if not cfg.get("features.trend_regime.enabled", False):
        return ctx
    return await _attach_trend(ctx)


async def _lookup_vol_regime(now_utc: Optional[datetime] = None) -> RegimeContext:
    """Read most recent regime_daily row (A5 vol regime).

    Cold-start (count < cold_start_min_days) -> returns _COLD_START.
    Row older than 7 days -> log WARNING, return _COLD_START.
    """
    from consensus_engine import db
    if not cfg.get("features.regime_classifier.enabled", False):
        return _COLD_START

    conn = await db.get_db()
    min_days = cfg.get("features.regime_classifier.cold_start_min_days", 30)

    cur = await conn.execute("SELECT COUNT(*) as cnt FROM regime_daily")
    row = await cur.fetchone()
    count = row["cnt"] if row else 0
    if count < min_days:
        return _COLD_START

    cur = await conn.execute(
        "SELECT * FROM regime_daily ORDER BY date_utc DESC LIMIT 1"
    )
    row = await cur.fetchone()
    if not row:
        return _COLD_START

    import time
    age_days = (time.time() - row["computed_at"]) / 86400
    if age_days > 7:
        log.warning("[A5] regime_daily most recent row is %.1f days old — falling back to normal", age_days)
        return _COLD_START

    label = row["regime_label"]
    z = row["z_score_smoothed"]
    shifts = cfg.get("features.regime_classifier.regime_shifts", {"calm": -5, "elevated": 5, "panic": 10})
    shift = shifts.get(label, 0)
    shift = _apply_graduated_widening(label, z, shift)
    log.info("[A5] regime=%s z=%.2f shift=%d cold_start=False", label, z, shift)
    return RegimeContext(label=label, z_score=z, threshold_shift=shift, cold_start=False, as_of_date=row["date_utc"])


async def _fetch_spy_closes(n: int = 260) -> list[float]:
    """Fetch last n daily SPY closes from Yahoo Finance API."""
    import aiohttp
    from consensus_engine.utils.http import get_session
    url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
    params = {"interval": "1d", "range": "1y"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        session = await get_session()
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                log.warning("[A5] Yahoo Finance returned %d for SPY", resp.status)
                return []
            data = await resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return []
            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            return closes[-n:] if len(closes) >= n else closes
    except Exception as e:
        log.warning("[A5] SPY fetch error: %s", e)
        return []


def _compute_regime(closes: list[float], date_str: str) -> Optional[dict]:
    """Compute regime from a list of close prices. Returns dict for DB insert or None."""
    if len(closes) < 22:
        log.warning("[A5] Not enough SPY closes to compute regime (got %d)", len(closes))
        return None

    # 20-day realized vol (std of daily log returns, annualized)
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(returns) < 20:
        return None
    recent_20 = returns[-20:]
    mean_ret = sum(recent_20) / len(recent_20)
    var_20 = sum((r - mean_ret) ** 2 for r in recent_20) / len(recent_20)
    realized_vol_20d = math.sqrt(var_20 * 252)  # annualized

    # 252-day mean and std of daily log-return
    if len(returns) < 50:
        returns_252 = returns
    else:
        returns_252 = returns[-252:]
    mean_252 = sum(returns_252) / len(returns_252)
    if len(returns_252) < 2:
        return None
    var_252 = sum((r - mean_252) ** 2 for r in returns_252) / len(returns_252)
    std_252 = math.sqrt(var_252) if var_252 > 0 else 1e-9

    # z-score
    z_raw = (realized_vol_20d - math.sqrt(var_252 * 252)) / (std_252 * math.sqrt(252))

    # EMA(5) smoothing -- use z_raw as first value (cold start treated as itself)
    alpha = cfg.get("features.regime_classifier.ema_alpha", 0.4)
    z_smooth = z_raw  # bootstrap; production: use prev DB row for EMA chain

    # Label
    panic_z = cfg.get("features.regime_classifier.panic_z", 1.5)
    elevated_z = cfg.get("features.regime_classifier.elevated_z", 0.5)
    calm_z = cfg.get("features.regime_classifier.calm_z", -1.0)
    if z_smooth >= panic_z:
        label = "panic"
    elif z_smooth >= elevated_z:
        label = "elevated"
    elif z_smooth <= calm_z:
        label = "calm"
    else:
        label = "normal"

    return {
        "date_utc": date_str,
        "realized_vol_20d": realized_vol_20d,
        "mean_252d": mean_252,
        "std_252d": std_252,
        "z_score_raw": z_raw,
        "z_score_smoothed": z_smooth,
        "regime_label": label,
    }


async def compute_and_persist_regime(date_utc: date) -> RegimeContext:
    """Cron-only entry point. Fetch SPY closes, compute regime, INSERT OR REPLACE into regime_daily."""
    import time
    from consensus_engine import db

    closes = await _fetch_spy_closes(260)
    if not closes:
        log.error("[A5] Failed to fetch SPY closes for regime computation")
        return _COLD_START

    date_str = date_utc.strftime("%Y-%m-%d")
    result = _compute_regime(closes, date_str)
    if result is None:
        return _COLD_START

    # EMA chaining: load previous z_score_smoothed if available
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT z_score_smoothed FROM regime_daily ORDER BY date_utc DESC LIMIT 1"
    )
    prev_row = await cur.fetchone()
    if prev_row:
        alpha = cfg.get("features.regime_classifier.ema_alpha", 0.4)
        result["z_score_smoothed"] = alpha * result["z_score_raw"] + (1 - alpha) * prev_row["z_score_smoothed"]
        # Re-label with smoothed z
        panic_z = cfg.get("features.regime_classifier.panic_z", 1.5)
        elevated_z = cfg.get("features.regime_classifier.elevated_z", 0.5)
        calm_z = cfg.get("features.regime_classifier.calm_z", -1.0)
        z_s = result["z_score_smoothed"]
        if z_s >= panic_z:
            result["regime_label"] = "panic"
        elif z_s >= elevated_z:
            result["regime_label"] = "elevated"
        elif z_s <= calm_z:
            result["regime_label"] = "calm"
        else:
            result["regime_label"] = "normal"

    await conn.execute(
        """INSERT OR REPLACE INTO regime_daily
           (date_utc, realized_vol_20d, mean_252d, std_252d, z_score_raw, z_score_smoothed, regime_label, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (result["date_utc"], result["realized_vol_20d"], result["mean_252d"], result["std_252d"],
         result["z_score_raw"], result["z_score_smoothed"], result["regime_label"], time.time()),
    )
    await conn.commit()

    shifts = cfg.get("features.regime_classifier.regime_shifts", {"calm": -5, "elevated": 5, "panic": 10})
    shift = shifts.get(result["regime_label"], 0)
    shift = _apply_graduated_widening(result["regime_label"], result["z_score_smoothed"], shift)
    log.info("[A5] persisted regime=%s z_raw=%.3f z_smooth=%.3f shift=%d for %s",
             result["regime_label"], result["z_score_raw"], result["z_score_smoothed"], shift, date_str)
    return RegimeContext(
        label=result["regime_label"],
        z_score=result["z_score_smoothed"],
        threshold_shift=shift,
        cold_start=False,
        as_of_date=date_str,
    )


# ===========================================================================
# F3 — price-trend / direction regime leg (final-plan.md §2.3)
# Lives BESIDE the A5 vol z-score. Computed once/day by the market_daily cron,
# persisted to trend_daily, and surfaced through RegimeContext's trend fields.
# Frozen params (preregistration_trade_edge.yaml f3_trend_regime): sma_fast=50,
# sma_slow=200, tsmom_lookback_days=63. All read via config with those defaults.
# ===========================================================================

# Need 200 closes for the 200DMA plus a window of distance points for the
# distance-to-200DMA z-score; require enough history for a stable read.
_TREND_MIN_CLOSES = 220
_DIST_Z_MAX_POINTS = 252  # cap the distance-z window at ~1 trading year


async def _attach_trend(ctx: RegimeContext) -> RegimeContext:
    """Layer the latest trend_daily row onto a vol RegimeContext.

    Returns a NEW context with trend fields populated; the vol fields are copied
    unchanged. If there is no fresh trend_daily row (cold-start or stale >7d),
    the trend fields stay at their None/cold-start defaults.
    """
    import dataclasses
    import time
    from consensus_engine import db

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM trend_daily ORDER BY date_utc DESC LIMIT 1"
    )
    row = await cur.fetchone()
    if not row:
        return ctx  # no trend data yet -> defaults (trend_cold_start=True)

    age_days = (time.time() - row["computed_at"]) / 86400
    if age_days > 7:
        log.warning("[F3] trend_daily most recent row is %.1f days old — trend cold-start", age_days)
        return ctx

    log.info("[F3] trend_state=%s close=%.2f sma200=%.2f tsmom=%.4f for %s",
             row["trend_state"], row["close"], row["sma_200"], row["tsmom_3m"], row["date_utc"])
    return dataclasses.replace(
        ctx,
        trend_state=row["trend_state"],
        trend_close=row["close"],
        sma_200=row["sma_200"],
        sma_50=row["sma_50"],
        sma_50_slope=row["sma_50_slope"],
        tsmom_3m=row["tsmom_3m"],
        dist_200_z=row["dist_200_z"],
        trend_as_of_date=row["date_utc"],
        trend_cold_start=False,
    )


async def _fetch_trend_closes(symbol: str = "SPY", n: int = 520) -> list[float]:
    """Fetch last n daily closes for a trend index from Yahoo Finance (2y range).

    Separate from _fetch_spy_closes (which fetches 1y for the vol z-score) so the
    A5 fetch path is untouched; trend needs a longer history for a 200DMA + a
    distance-to-200DMA z-score window.
    """
    import aiohttp
    from consensus_engine.utils.http import get_session
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d", "range": "2y"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        session = await get_session()
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                log.warning("[F3] Yahoo Finance returned %d for %s", resp.status, symbol)
                return []
            data = await resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return []
            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            return closes[-n:] if len(closes) >= n else closes
    except Exception as e:
        log.warning("[F3] %s fetch error: %s", symbol, e)
        return []


def _classify_trend_state(above_200: bool, slope_up: bool, tsmom_up: bool) -> str:
    """Three sign votes -> trend_state. All bullish = green, none = red, mixed = yellow."""
    bull_votes = int(above_200) + int(slope_up) + int(tsmom_up)
    if bull_votes == 3:
        return "green"
    if bull_votes == 0:
        return "red"
    return "yellow"


def _compute_trend(closes: list[float], date_str: str, index_symbol: str = "SPY") -> Optional[dict]:
    """Compute the trend leg from a list of closes. Returns a dict for DB insert or None.

    Components (all from PRIOR closes; the cron uses the prior daily close):
      * close vs 200DMA            -> directional vote
      * 50DMA slope over slope_window -> directional vote
      * 63td (3-month) momentum    -> directional vote
      * distance-to-200DMA z-score -> persisted extension measure
    trend_state = green (all 3 bullish) / red (all 3 bearish) / yellow (mixed).
    """
    sma_slow = cfg.get("features.trend_regime.sma_slow", 200)
    sma_fast = cfg.get("features.trend_regime.sma_fast", 50)
    tsmom_lb = cfg.get("features.trend_regime.tsmom_lookback_days", 63)
    slope_window = cfg.get("features.trend_regime.slope_window", 10)

    need = max(_TREND_MIN_CLOSES, sma_slow + 20, sma_fast + slope_window, tsmom_lb + 1)
    if len(closes) < need:
        log.warning("[F3] Not enough closes to compute trend (got %d, need %d)", len(closes), need)
        return None

    close = closes[-1]
    sma_200 = sum(closes[-sma_slow:]) / sma_slow
    sma_50 = sum(closes[-sma_fast:]) / sma_fast
    sma_50_prev = sum(closes[-sma_fast - slope_window:-slope_window]) / sma_fast
    sma_50_slope = (sma_50 - sma_50_prev) / sma_50_prev if sma_50_prev else 0.0
    tsmom_3m = close / closes[-1 - tsmom_lb] - 1.0

    # distance-to-200DMA z-score over the available history (each day that has
    # sma_slow priors), capped at _DIST_Z_MAX_POINTS most-recent points.
    dist_series = []
    for i in range(sma_slow, len(closes) + 1):
        window = closes[i - sma_slow:i]
        s200 = sum(window) / sma_slow
        dist_series.append((closes[i - 1] - s200) / s200)
    dist_series = dist_series[-_DIST_Z_MAX_POINTS:]
    cur_dist = dist_series[-1]
    mean_d = sum(dist_series) / len(dist_series)
    if len(dist_series) >= 2:
        var_d = sum((x - mean_d) ** 2 for x in dist_series) / len(dist_series)
        std_d = math.sqrt(var_d) if var_d > 0 else 1e-9
    else:
        std_d = 1e-9
    dist_200_z = (cur_dist - mean_d) / std_d

    trend_state = _classify_trend_state(close > sma_200, sma_50_slope > 0, tsmom_3m > 0)

    return {
        "date_utc": date_str,
        "index_symbol": index_symbol,
        "close": close,
        "sma_200": sma_200,
        "sma_50": sma_50,
        "sma_50_slope": sma_50_slope,
        "tsmom_3m": tsmom_3m,
        "dist_200_z": dist_200_z,
        "trend_state": trend_state,
    }


async def compute_and_persist_trend(date_utc: date, index_symbol: str = "SPY") -> Optional[dict]:
    """Cron-only entry point. Fetch closes, compute the trend leg, INSERT OR REPLACE
    into trend_daily. Returns the computed dict (or None on failure).

    Note: trend_daily PK is date_utc only, so one index per date — SPY by default.
    """
    import time
    from consensus_engine import db

    closes = await _fetch_trend_closes(index_symbol, 520)
    if not closes:
        log.error("[F3] Failed to fetch %s closes for trend computation", index_symbol)
        return None

    date_str = date_utc.strftime("%Y-%m-%d")
    result = _compute_trend(closes, date_str, index_symbol)
    if result is None:
        return None

    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO trend_daily
           (date_utc, index_symbol, close, sma_200, sma_50, sma_50_slope,
            tsmom_3m, dist_200_z, trend_state, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (result["date_utc"], result["index_symbol"], result["close"], result["sma_200"],
         result["sma_50"], result["sma_50_slope"], result["tsmom_3m"], result["dist_200_z"],
         result["trend_state"], time.time()),
    )
    await conn.commit()
    log.info("[F3] persisted trend_state=%s close=%.2f sma200=%.2f tsmom=%.4f dist_z=%.3f for %s",
             result["trend_state"], result["close"], result["sma_200"],
             result["tsmom_3m"], result["dist_200_z"], date_str)
    return result


if __name__ == "__main__":
    """CLI: python3 -m consensus_engine.analysis.regime --compute-today"""
    import sys
    import asyncio as _asyncio
    from consensus_engine import db as _db

    async def _main():
        await _db.init_db()
        today = date.today()
        regime = await compute_and_persist_regime(today)
        print(f"Regime for {today}: label={regime.label} z={regime.z_score:.3f} shift={regime.threshold_shift}")
        await _db.close_db()

    _asyncio.run(_main())
