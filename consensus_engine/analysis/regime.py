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


_COLD_START = RegimeContext(label="normal", z_score=0.0, threshold_shift=0, cold_start=True, as_of_date="")


async def lookup_regime(now_utc: Optional[datetime] = None) -> RegimeContext:
    """Read most recent regime_daily row.

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
    log.info("[A5] regime=%s z=%.2f shift=%d cold_start=False", label, z, shift)
    return RegimeContext(label=label, z_score=z, threshold_shift=shift, cold_start=False, as_of_date=row["date_utc"])


async def _fetch_spy_closes(n: int = 260) -> list[float]:
    """Fetch last n daily SPY closes from Yahoo Finance API."""
    import aiohttp
    url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
    params = {"interval": "1d", "range": "1y"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession() as session:
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
    log.info("[A5] persisted regime=%s z_raw=%.3f z_smooth=%.3f shift=%d for %s",
             result["regime_label"], result["z_score_raw"], result["z_score_smoothed"], shift, date_str)
    return RegimeContext(
        label=result["regime_label"],
        z_score=result["z_score_smoothed"],
        threshold_shift=shift,
        cold_start=False,
        as_of_date=date_str,
    )


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
