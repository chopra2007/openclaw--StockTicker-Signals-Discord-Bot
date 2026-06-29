"""F5: internal signal-stream breadth oscillator (trade-edge market-context layer).

ONE oscillator built from the bot's OWN directional stream: the net of distinct
*bullish* minus distinct *bearish* tickers, counted from INFORMED sources over a
rolling window of calendar days, EMA-smoothed, then turned into an expanding-window
z-score (``osc_z``). Persisted once per day into ``internal_breadth_daily``.

IMPORTANT — this is DESCRIPTIVE MARKET CONTEXT, a *view*, not a buy/sell signal.
It has NO gate and changes NO alert. The back-tests showed no tradeable edge; this
read only forward-collects so a human can eyeball whether the bot's own crowd is
leaning more long or more short than usual. See ``LONG_BIAS_NOTE``.

What counts (informed directional stream):
  * ``signal_events`` rows whose ``source_type`` is NOT in ``EXCLUDED_SOURCES``
    and whose ``direction`` is bullish (``long``) or bearish (``short``).
Explicitly EXCLUDED:
  * raw ApeWisdom (mostly neutral crowd noise, ``source_type='apewisdom'``);
  * Form-4 insider rows (``source_type='form4'`` / ``'sec_form4'``);
  * ``neutral`` / NULL directions (no lean);
  * epoch-1970 garbage rows (``recorded_at`` below ``_EPOCH_FLOOR``).

Structural long-bias: the bot's history is far more bullish than bearish
(~2448 long vs ~784 short twitter calls), so a positive net is the resting state.
Read the *change* (the z-score), not the raw level. This caveat ships in every
output via ``LONG_BIAS_NOTE``.

Point-in-time by construction: each date's net uses only signals dated on or before
that date (a backward rolling window); the EMA and the z-score expand over prior
dates only — never look ahead. So the value computed on the full stream equals the
value computed on the prefix-to-date (truncation test).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# Sources that are NOT the informed directional stream (lower-cased match).
EXCLUDED_SOURCES = frozenset({"apewisdom", "form4", "sec_form4", "sec"})
# Direction labels mapped to a lean.
BULLISH = frozenset({"long", "bull", "bullish"})
BEARISH = frozenset({"short", "bear", "bearish"})

# Anything below this unix timestamp (~2001-09) is treated as garbage / epoch-1970
# (the signal_events tripwire: a few rows carry tiny floats like 100.0).
_EPOCH_FLOOR = 1_000_000_000.0

# The structural long-bias caveat that ships with every output.
LONG_BIAS_NOTE = (
    "Market context only (a view, not a buy/sell signal). The bot's directional "
    "stream is structurally long-biased — far more bullish than bearish calls — so "
    "a positive net is the normal resting state. Read the change (z-score), not the level."
)


@dataclass
class BreadthContext:
    net_bull_bear: int          # distinct bullish - distinct bearish tickers (rolling window)
    n_bullish: int              # distinct bullish tickers in the window
    n_bearish: int              # distinct bearish tickers in the window
    osc_z: float                # EMA-smoothed, expanding-window z-score
    n_signals: int              # raw informed directional signal count (thin-day guard)
    cold_start: bool            # True until a fresh internal_breadth_daily row exists
    as_of_date: str             # YYYY-MM-DD, "" on cold start
    long_bias_note: str         # the structural long-bias caveat (always set)


_COLD_START = BreadthContext(
    net_bull_bear=0, n_bullish=0, n_bearish=0, osc_z=0.0, n_signals=0,
    cold_start=True, as_of_date="", long_bias_note=LONG_BIAS_NOTE,
)


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------

def _params(window, ema_alpha) -> tuple[int, float]:
    w = int(window if window is not None
            else cfg.get("features.internal_breadth.window", 5))
    a = float(ema_alpha if ema_alpha is not None
              else cfg.get("features.internal_breadth.ema_alpha", 0.4))
    return w, a


def _get(row, key, default=None):
    """Read a column from a dict OR a sqlite3.Row uniformly."""
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None else val


def _lean(direction) -> Optional[str]:
    """Map a raw direction label to 'bull' / 'bear' / None (neutral / unknown)."""
    if not direction:
        return None
    d = str(direction).strip().lower()
    if d in BULLISH:
        return "bull"
    if d in BEARISH:
        return "bear"
    return None


def _epoch_to_date(epoch: float) -> Optional[str]:
    """UTC YYYY-MM-DD for a unix epoch, or None for garbage / epoch-1970 rows."""
    if epoch is None or float(epoch) < _EPOCH_FLOOR:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Core math (pure — point-in-time by construction)
# ---------------------------------------------------------------------------

def _expanding_z(values: list[float]) -> list[float]:
    """Expanding-window population z-score of each value vs all values up to it.

    z[i] = (v[i] - mean(v[0..i])) / std(v[0..i]); 0 when the window has zero
    variance or only one point. Backward-only, so it stays point-in-time.
    """
    out: list[float] = []
    for i in range(len(values)):
        window = values[: i + 1]
        n = len(window)
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n
        std = math.sqrt(var)
        out.append((window[-1] - mean) / std if std > 0 else 0.0)
    return out


def compute_internal_breadth(rows_or_conn: Iterable, window=None,
                             ema_alpha=None) -> list[dict]:
    """Build the per-date internal-breadth series (pure, testable).

    ``rows_or_conn`` is an iterable of signal_events-shaped row mappings (dict or
    sqlite3.Row) with keys ``ticker``, ``direction``, ``source_type``,
    ``recorded_at``. Returns one dict per date that has at least one informed
    directional signal, ordered OLDEST -> NEWEST:
        {date_utc, net_bull_bear, n_bullish, n_bearish, osc_z, n_signals}
    The daily cron persists the last entry; backtests can use the whole series.

    Excludes neutral/NULL directions, ApeWisdom, Form-4, and epoch-1970 garbage.
    Each date's window covers ``window`` calendar days ending on that date; the
    same ticker appearing on several days inside the window counts ONCE (distinct).
    """
    w, alpha = _params(window, ema_alpha)

    # 1. Filter to the informed directional stream, bucket by UTC date.
    #    per_date[date] = {"bull": set(tickers), "bear": set(tickers), "raw": int}
    per_date: dict[str, dict] = {}
    for row in rows_or_conn:
        src = str(_get(row, "source_type", "") or "").strip().lower()
        if src in EXCLUDED_SOURCES:
            continue
        lean = _lean(_get(row, "direction"))
        if lean is None:
            continue
        date_str = _epoch_to_date(_get(row, "recorded_at"))
        if date_str is None:
            continue
        ticker = _get(row, "ticker")
        if not ticker:
            continue
        bucket = per_date.setdefault(date_str, {"bull": set(), "bear": set(), "raw": 0})
        bucket["raw"] += 1
        bucket["bull" if lean == "bull" else "bear"].add(str(ticker).upper())

    if not per_date:
        return []

    dates = sorted(per_date)

    # 2. Rolling-window distinct counts (window calendar days, backward-only).
    series: list[dict] = []
    nets: list[float] = []
    for d in dates:
        d_dt = datetime.strptime(d, "%Y-%m-%d").date()
        start = d_dt - timedelta(days=w - 1)
        bull: set[str] = set()
        bear: set[str] = set()
        raw = 0
        for od in dates:
            od_dt = datetime.strptime(od, "%Y-%m-%d").date()
            if start <= od_dt <= d_dt:
                bull |= per_date[od]["bull"]
                bear |= per_date[od]["bear"]
                raw += per_date[od]["raw"]
        net = len(bull) - len(bear)
        nets.append(float(net))
        series.append({
            "date_utc": d,
            "net_bull_bear": net,
            "n_bullish": len(bull),
            "n_bearish": len(bear),
            "n_signals": raw,
        })

    # 3. EMA-smooth the net series, then expanding z-score (both backward-only).
    ema: list[float] = []
    for i, net in enumerate(nets):
        ema.append(net if i == 0 else alpha * net + (1 - alpha) * ema[i - 1])
    z = _expanding_z(ema)
    for cell, zval in zip(series, z):
        cell["osc_z"] = zval

    return series


# ---------------------------------------------------------------------------
# Cron entry point (forward-collect; runs regardless of the enabled flag)
# ---------------------------------------------------------------------------

async def compute_and_persist(date_utc: Optional[str] = None) -> Optional[dict]:
    """Fetch the recent informed stream, compute the series, persist the latest row.

    Forward-collect: this runs whether or not ``features.internal_breadth.enabled``
    is set — the table accumulates so a human can read it once the flag is flipped.
    Returns the persisted row dict (or None when there is nothing to persist).
    """
    import time
    from consensus_engine import db

    window = cfg.get("features.internal_breadth.window", 5)
    ema_alpha = cfg.get("features.internal_breadth.ema_alpha", 0.4)
    history_days = cfg.get("features.internal_breadth.history_days", 180)
    min_signals = cfg.get("features.internal_breadth.min_signals", 8)

    target = (date_utc if date_utc is not None
              else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    target_dt = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = (target_dt - timedelta(days=history_days)).timestamp()
    upper = (target_dt + timedelta(days=1)).timestamp()  # include all of target day

    conn = await db.get_db()
    cur = await conn.execute(
        """SELECT ticker, direction, source_type, recorded_at
           FROM signal_events
           WHERE recorded_at >= ? AND recorded_at < ?""",
        (cutoff, upper),
    )
    rows = await cur.fetchall()
    series = compute_internal_breadth(rows, window, ema_alpha)
    if not series:
        log.info("[F5] no informed directional signals in window — nothing to persist")
        return None

    # Persist the row matching the target date if present, else the most recent.
    last = next((c for c in reversed(series) if c["date_utc"] == target), series[-1])
    if last["n_signals"] < min_signals:
        log.warning("[F5] thin day: only %d informed signals for %s (min %d) — "
                    "persisting but treat osc_z as low-confidence",
                    last["n_signals"], last["date_utc"], min_signals)

    await conn.execute(
        """INSERT OR REPLACE INTO internal_breadth_daily
           (date_utc, net_bull_bear, n_bullish, n_bearish, osc_z, n_signals, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (last["date_utc"], last["net_bull_bear"], last["n_bullish"], last["n_bearish"],
         last["osc_z"], last["n_signals"], time.time()),
    )
    await conn.commit()
    log.info("[F5] persisted internal breadth net=%d (bull=%d bear=%d) z=%.3f n=%d for %s",
             last["net_bull_bear"], last["n_bullish"], last["n_bearish"],
             last["osc_z"], last["n_signals"], last["date_utc"])
    return last


# ---------------------------------------------------------------------------
# Live read path (engine / command) — reads the persisted table, no fetch
# ---------------------------------------------------------------------------

async def lookup_internal_breadth() -> BreadthContext:
    """Read the newest ``internal_breadth_daily`` row into a BreadthContext.

    Cold start (flag OFF / no row / stale row) -> ``_COLD_START``. Mirrors
    sector_rotation.lookup_rotation: the daily cron writes the table; this only
    reads it. The structural long-bias note is attached to every return value.
    """
    if not cfg.get("features.internal_breadth.enabled", False):
        return _COLD_START

    from consensus_engine.analysis import market_panel

    row = await market_panel.get_latest_row("internal_breadth_daily")
    if not row:
        return _COLD_START

    if market_panel.is_stale(row["computed_at"]):
        age = market_panel.row_age_days(row["computed_at"])
        log.warning("[F5] internal_breadth_daily is %.1f days old — cold start", age)
        return _COLD_START

    return BreadthContext(
        net_bull_bear=int(row["net_bull_bear"]),
        n_bullish=int(row["n_bullish"]),
        n_bearish=int(row["n_bearish"]),
        osc_z=float(row["osc_z"]),
        n_signals=int(row["n_signals"]),
        cold_start=False,
        as_of_date=row["date_utc"],
        long_bias_note=LONG_BIAS_NOTE,
    )


if __name__ == "__main__":
    """CLI: python3 -m consensus_engine.analysis.internal_breadth [YYYY-MM-DD]"""
    import sys
    import asyncio as _asyncio
    from consensus_engine import db as _db

    async def _main():
        await _db.init_db()
        target = sys.argv[1] if len(sys.argv) > 1 else None
        last = await compute_and_persist(target)
        if last:
            print(f"Internal breadth for {last['date_utc']}: net={last['net_bull_bear']} "
                  f"(bull={last['n_bullish']} bear={last['n_bearish']}) "
                  f"z={last['osc_z']:.3f} n={last['n_signals']}")
        else:
            print("No informed directional signals to persist.")
        await _db.close_db()

    _asyncio.run(_main())
