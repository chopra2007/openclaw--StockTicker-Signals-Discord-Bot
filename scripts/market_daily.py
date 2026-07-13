"""Daily market-context orchestrator (trade-edge layer).

ONE cron entrypoint that computes and persists the daily market-context rows by
calling the FROZEN analysis modules — it does not re-implement any of the math:

    sector_rotation.compute_series        -> sector_rs_daily        (F1)
    factor_rotation.compute_factor_series -> factor_rs_daily        (F2)
    regime._compute_trend                 -> trend_daily            (F3)
    internal_breadth.compute_internal_breadth -> internal_breadth_daily (F5)

These are DESCRIPTIVE market-context reads (a view, not a buy/sell signal). The
back-tests found NO tradeable edge, so nothing here gates a live alert; the rows
are surfaced read-only and shadow-logged. Rotation labels honestly distinguish
'improving (early)' from 'leading (already moved)' so a finished move is never
read as a fresh entry.

Data source: the Parquet store (``data/market_store``). By default the run first
REFRESHES that store with the latest daily closes from yfinance (raw,
auto_adjust=False) and MERGES them in — recent rows overwritten, the long history
kept — so a daily cron self-updates instead of computing off frozen closes
forever. ``--no-download`` skips the fetch and computes from the cached store only
(offline / tests). The refresh is best-effort: a yfinance failure logs a warning
and the run proceeds on whatever the store already has (history is never wiped).
Every value at date t uses ONLY closes up to and including t (trailing windows +
the prior close), so the value computed on the full series equals the value
computed on the prefix to t.

Usage:
    python3 scripts/market_daily.py --dry-run                  # refresh + compute + gate, NO write
    python3 scripts/market_daily.py                            # refresh + seed (full window)
    python3 scripts/market_daily.py --days 3                   # refresh + self-heal last 3 days
    python3 scripts/market_daily.py --no-download --days 3     # cached store only (no fetch)
    python3 scripts/market_daily.py --db /tmp/x.db --days 3    # target a NON-live db
    python3 scripts/market_daily.py --days 3 --dry-run

``--db PATH`` targets a specific SQLite db (tests pass a tmp_path; the daily cron
omits it and falls back to ``database.path`` from config). The needed tables are
created on first write via the shared ``db.SCHEMA`` (CREATE TABLE IF NOT EXISTS),
so a fresh temp db works without a separate migration step. INSERT OR REPLACE on
the table primary keys makes every run idempotent.

DO NOT run against the live consensus.db while the consensus-engine service /
market_daily.timer is also writing — SQLite serialises, but a one-time seed should
stop the timer or use --dry-run first.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Project root on sys.path so consensus_engine imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import config as cfg
from consensus_engine.analysis import sector_rotation as sr
from consensus_engine.analysis import factor_rotation as fr
from consensus_engine.analysis import regime
from consensus_engine.analysis import internal_breadth as ib

log = logging.getLogger("market_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Union of every symbol the three reads need (sector ETFs + factor ETFs + SPY).
_SYMBOLS: tuple[str, ...] = (sr.BENCHMARK,) + sr.SECTOR_ETFS + fr.FACTOR_ETFS

# Universe the daily refresh keeps fresh: the compute universe (SPY + sector +
# factor ETFs) plus QQQ (used by the back-test's QQQ-relative transfer). dict
# preserves order while de-duping any accidental overlap.
_REFRESH_SYMBOLS: tuple[str, ...] = tuple(
    dict.fromkeys((sr.BENCHMARK, "QQQ") + sr.SECTOR_ETFS + fr.FACTOR_ETFS))

# yfinance window pulled each refresh. ~1 month (>10 trading days) so a cron that
# misses a few days (weekend pause, holidays) still overlaps the stored tail and
# self-heals — the merge keeps everything older than this window untouched.
_REFRESH_PERIOD = "1mo"


# ---------------------------------------------------------------------------
# Parquet panel (point-in-time closes from the cached store)
# ---------------------------------------------------------------------------

def _resolve_store_dir(store_dir: str | None) -> Path:
    if store_dir is not None:
        return Path(store_dir)
    rel = cfg.get("features.market_data.store_dir", None) or cfg.get(
        "market_data.store_dir", "data/market_store")
    p = Path(rel)
    return p if p.is_absolute() else (_ROOT / p)


def _load_closes(store_dir: str | None = None) -> pd.DataFrame:
    """Wide date-indexed close panel (one column per symbol), aligned across all.

    Reads the same Parquet files the back-tests use (``data/market_store``); each
    file is a date-indexed OHLCV frame with a lowercase ``close`` column. Rows with
    any missing symbol are dropped so the panel is aligned (mirrors
    ``sector_rotation_daily._fetch_closes`` which does ``dropna(how='any')``).
    """
    sdir = _resolve_store_dir(store_dir)
    cols: dict[str, pd.Series] = {}
    for sym in _SYMBOLS:
        path = sdir / f"{sym}.parquet"
        if not path.exists():
            log.warning("[panel] missing series %s (%s) — skipping", sym, path)
            continue
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        cols[sym] = df["close"].astype(float)
    if sr.BENCHMARK not in cols:
        raise FileNotFoundError(
            f"benchmark {sr.BENCHMARK} not found in store {sdir}")
    panel = pd.DataFrame(cols).sort_index().dropna(how="any")
    return panel


# ---------------------------------------------------------------------------
# Daily refresh — merge the latest yfinance closes into the Parquet store
# ---------------------------------------------------------------------------

def _get_store(sdir):
    """Return the shared sandbox parquet store, redirected to ``sdir``.

    Mirrors ``backtest_sector_rotation._get_store``: patch the store's config
    getter so ``store_dir()`` resolves to our market store. An absolute path in
    ``data.store_dir`` overrides ``project_root()`` (``root / ABS == ABS``), so the
    store reads/writes exactly the files ``_load_closes`` reads.
    """
    sys.path.insert(0, str(_ROOT / "volatility_regime_reversal_indicator"))
    from src.data import store as _store  # type: ignore

    sdir = Path(sdir)
    sdir.mkdir(parents=True, exist_ok=True)
    _orig_get = _store.get

    def _patched_get(key, default=None):
        if key == "data.store_dir":
            return str(sdir)
        return _orig_get(key, default)

    _store.get = _patched_get
    return _store


def _download_recent(sym: str, period: str = _REFRESH_PERIOD):
    """Download a recent RAW (auto_adjust=False) daily OHLCV window for one symbol.

    Reuses the per-symbol fetch shape of ``backtest_sector_rotation.download_and_store``
    but returns only the recent window (the merge keeps the long history). Columns
    are lowercased and the index coerced to tz-naive dates so it concats cleanly
    onto the stored (lowercase, tz-naive) series. Returns ``None`` if yfinance
    yields nothing.
    """
    import yfinance as yf

    raw = yf.download(sym, period=period, interval="1d", auto_adjust=False,
                      progress=False, group_by="column", threads=False)
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in raw.columns]
    df = raw[cols].dropna(how="any")
    if df.empty:
        return None
    df.columns = [str(c).lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def _merge_series(store, name: str, fresh: pd.DataFrame) -> None:
    """Merge a recent OHLCV window into the stored series, keeping the long history.

    Fresh rows OVERWRITE stored rows on duplicate dates (``keep='last'``); every
    older stored row is retained. Written back via the shared store's
    ``write_series`` — no new data layer.
    """
    if store.series_exists(name):
        old = store.read_series(name)
        combined = pd.concat([old, fresh])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = fresh.sort_index()
    store.write_series(name, combined, source="yfinance", adjusted=False)


def refresh_store(store_dir: str | None = None,
                  period: str = _REFRESH_PERIOD) -> int:
    """Refresh the Parquet store with recent closes for the full ETF universe.

    Best-effort and crash-proof: a per-symbol download/merge failure (or a symbol
    returning no data) logs a warning and is skipped — the existing series is left
    untouched, never wiped. Returns the count of symbols actually refreshed.
    """
    sdir = _resolve_store_dir(store_dir)
    try:
        store = _get_store(sdir)
    except Exception as e:  # noqa: BLE001 — never let the refresh crash the cron
        log.warning("[refresh] could not open store at %s (%s) — using cached data",
                    sdir, e)
        return 0
    n_ok = 0
    for sym in _REFRESH_SYMBOLS:
        try:
            fresh = _download_recent(sym, period)
        except Exception as e:  # noqa: BLE001
            log.warning("[refresh] %s download failed (%s) — keeping cached series",
                        sym, e)
            continue
        if fresh is None or fresh.empty:
            log.warning("[refresh] %s returned no data — keeping cached series", sym)
            continue
        try:
            _merge_series(store, sym, fresh)
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            log.warning("[refresh] %s merge failed (%s) — keeping cached series",
                        sym, e)
    log.info("[refresh] updated %d/%d series in %s",
             n_ok, len(_REFRESH_SYMBOLS), sdir)
    return n_ok


def _cutoff(days_limit: int | None) -> str | None:
    if days_limit is None:
        return None
    return str((date.today() - timedelta(days=days_limit)).isoformat())


# ---------------------------------------------------------------------------
# Row building (delegates the math to the frozen modules)
# ---------------------------------------------------------------------------

def build_sector_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    n = int(cfg.get("features.sector_rotation.n_window", 10))
    k = int(cfg.get("features.sector_rotation.k_window", 5))
    d = float(cfg.get("features.sector_rotation.distance", 2))
    p = int(cfg.get("features.sector_rotation.persistence", 2))
    series = sr.compute_series(panel, n, k, d, p)
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for etf, cells in series.items():
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            if cutoff is not None and dates[i] < cutoff:
                continue
            rows.append({
                "date_utc": dates[i], "etf": etf,
                "rs_ratio": cell["rs_ratio"], "rs_momentum": cell["rs_momentum"],
                "quadrant": cell["quadrant"],
                "inflection": 1 if cell["inflection"] else 0,
                "n_window": n, "k_window": k,
            })
    return rows


def build_factor_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    rw = int(cfg.get("features.factor_rotation.rs_window", 21))
    mw = int(cfg.get("features.factor_rotation.mom_window", 63))
    series = fr.compute_factor_series(panel, rw, mw)
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for etf, cells in series.items():
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            if cutoff is not None and dates[i] < cutoff:
                continue
            accel = cell["accelerating"]
            rows.append({
                "date_utc": dates[i], "factor_etf": etf,
                "rs_vs_spy": cell["rs_vs_spy"], "rs_momentum": cell["rs_momentum"],
                "leading": 1 if cell["leading"] else 0,
                "accelerating": None if accel is None else (1 if accel else 0),
            })
    return rows


def build_trend_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    """Compute the SPY trend leg per date via the FROZEN ``regime._compute_trend``.

    Point-in-time: each date is computed from the prefix of closes ending at it.
    trend_daily PK is date_utc only (one index/date) -> SPY.
    """
    spy = [float(x) for x in panel[sr.BENCHMARK].tolist()]
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for i in range(len(spy)):
        d = dates[i]
        if cutoff is not None and d < cutoff:
            continue
        res = regime._compute_trend(spy[: i + 1], d, "SPY")
        if res is None:
            continue
        rows.append(res)
    return rows


def build_breadth_rows(db_path: str | None, days_limit: int | None) -> list[dict]:
    """Internal-breadth series via the FROZEN ``internal_breadth.compute_internal_breadth``.

    Reads the bot's OWN directional stream (``signal_events``) from ``db_path`` —
    the same db we seed, which in production is the live consensus.db that holds
    signal_events. Returns one row per date that has informed directional signals,
    shaped for ``internal_breadth_daily``; empty when the db / table is absent
    (a brand-new temp db with no signals yet). This is DESCRIPTIVE breadth (F5),
    point-in-time by construction (the expanding z-score uses only prior dates).
    """
    if not db_path:
        return []
    if not Path(db_path).exists():
        return []
    window = int(cfg.get("features.internal_breadth.window", 5))
    alpha = float(cfg.get("features.internal_breadth.ema_alpha", 0.4))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_events'"
        ).fetchone()
        if not has:
            return []
        rows = conn.execute(
            "SELECT ticker, direction, source_type, recorded_at FROM signal_events"
        ).fetchall()
    finally:
        conn.close()
    series = ib.compute_internal_breadth(rows, window, alpha)
    cutoff = _cutoff(days_limit)
    return [c for c in series if cutoff is None or c["date_utc"] >= cutoff]


# ---------------------------------------------------------------------------
# r20 (standalone-scanners): RSP/SPY(+IWM) participation-proxy — one shadow row.
# Runs when features.market_breadth is enabled OR shadow (shadow:true in prod ->
# collect forward data without touching the !market panel, which stays gated on
# .enabled). DESCRIPTIVE-ONLY: the row accrues in market_breadth_daily and is
# NEVER read by cross_reference.score_ticker.
# ---------------------------------------------------------------------------

def build_market_breadth_rows(days_limit: int | None = None) -> list[dict]:
    """Build the r20 breadth snapshot row by REUSING the frozen market_breadth compute.

    Calls ``market_breadth.compute_market_breadth`` (same ``_ratio_trend`` math + the
    same ``prices.fetch_history`` RSP/SPY/IWM fetch) via ``asyncio.run`` — no ratio
    math is re-implemented here. Returns a single-element list (today's UTC snapshot,
    keyed like the forward-log) or [] when RSP/SPY is unavailable or the fetch fails.
    ``days_limit`` is accepted for call-site symmetry but does not window a
    point-in-time snapshot. Best-effort: a fetch failure logs and yields no row.
    """
    del days_limit  # snapshot is point-in-time; no windowing
    from consensus_engine.analysis import market_breadth as mb
    window_days = int(cfg.get("features.market_breadth.window_days", 20))
    trend_threshold_pct = float(cfg.get("features.market_breadth.trend_threshold_pct", 0.5))
    try:
        read = asyncio.run(mb.compute_market_breadth(
            window_days=window_days, trend_threshold_pct=trend_threshold_pct))
    except Exception as e:  # noqa: BLE001 — a breadth-fetch failure must not crash the cron
        log.warning("[breadth] compute failed (%s) — skipping market_breadth_daily row", e)
        return []
    if read is None:
        log.warning("[breadth] RSP/SPY unavailable — skipping market_breadth_daily row")
        return []
    row = dict(read)
    row["date_utc"] = datetime.now(timezone.utc).date().isoformat()
    return [row]


# ---------------------------------------------------------------------------
# r22 (macro-fred): FRED macro-leg producer — fills the descriptive F4 shell
# (macro_legs_daily). DESCRIPTIVE/shadow ONLY — never wired into cross_asset
# (E2). Honors the pre-existing '# F4 (NEVER averaged into cross_asset)' decision.
# ---------------------------------------------------------------------------

# FRED series -> role. T10Y2Y/T10Y3M curves are display-only (schema comment); the
# broad-dollar and real-yield legs drive the descriptive macro_multiplier as
# rate-of-change momentum signals (a rising dollar / rising real yields = tighter
# conditions = veto side; falling = confirm side). ICE DXY is proprietary and not on
# FRED, so DTWEXBGS (trade-weighted broad USD) is the dollar proxy — labelled as the
# FRED broad-dollar index, NOT "DXY".
_MACRO_ROC_WINDOW = 21          # trading-day-ish lookback (valid obs) for the ROC legs
_MACRO_FLOOR = 0.85             # bounded like E2; descriptive only, gates nothing
_MACRO_CEIL = 1.15
_MACRO_DXY_K = 1.0              # dxy_roc (fractional) -> multiplier travel; 0.05 ROC -> ~0.05
_MACRO_RY_K = 0.05             # real-yield ROC (fractional) -> multiplier travel


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _fetch_fred_obs(series_id: str, limit: int) -> list[tuple[str, float]]:
    """Return recent valid FRED observations (date, value) NEWEST-first (desc order).

    Empty list on any problem (missing FRED_API_KEY, HTTP error, no valid obs) — the
    caller treats an empty result as an unavailable leg (drop-None discipline). Mirrors
    cross_asset._fetch_credit_ratio's urllib call + FRED_API_KEY env read.
    """
    key = os.environ.get("FRED_API_KEY")
    if not key:
        log.debug("[macro] FRED_API_KEY not set — %s leg unavailable", series_id)
        return []
    try:
        q = urllib.parse.urlencode({
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(limit),
        })
        url = f"https://api.stlouisfed.org/fred/series/observations?{q}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.load(resp)
        obs = [o for o in data.get("observations", []) if o.get("value") not in (".", "", None)]
        return [(o.get("date", ""), float(o["value"])) for o in obs]
    except Exception as e:  # noqa: BLE001 — a FRED outage must not crash the cron
        log.warning("[macro] FRED fetch failed for %s (%s) — leg unavailable", series_id, e)
        return []


def _roc(obs: list[tuple[str, float]], window: int) -> float | None:
    """Rate-of-change of the newest value vs `window` valid obs ago (fractional).

    obs is NEWEST-first. None when there is not enough history or the prior value is
    non-positive (can't form a ratio).
    """
    if len(obs) <= window:
        return None
    latest = obs[0][1]
    prior = obs[window][1]
    if prior == 0:
        return None
    return latest / prior - 1.0


def build_macro_rows(days_limit: int | None = None) -> list[dict]:
    """Build the descriptive F4 macro row from FRED daily series (r22).

    Fetches T10Y2Y / T10Y3M (yield-curve slopes, display), DTWEXBGS (broad-dollar ROC),
    and DFII10 (10Y TIPS real yield level + its ROC). Computes a shadow ``macro_multiplier``
    from the AVAILABLE directional legs (dxy_roc, real_yield_roc) with the same
    drop-None-then-clamp discipline cross_asset.get_multiplier uses, and records the
    survivors in ``legs_used_json``. Returns a single-element list (the latest snapshot)
    or [] when no FRED data is available. ``days_limit`` is accepted for call-site
    symmetry but does not window a point-in-time snapshot.

    DESCRIPTIVE/shadow only: this NEVER feeds cross_asset (E2). The yfinance-ETF-derived
    columns (copper_gold_roc, semis_rs, cyc_def_div) are out of r22's FRED scope and left
    NULL (schema allows; only macro_multiplier is NOT NULL).
    """
    del days_limit  # snapshot is point-in-time; no windowing
    t10y2y_obs = _fetch_fred_obs("T10Y2Y", 5)
    t10y3m_obs = _fetch_fred_obs("T10Y3M", 5)
    dxy_obs = _fetch_fred_obs("DTWEXBGS", _MACRO_ROC_WINDOW + 20)
    ry_obs = _fetch_fred_obs("DFII10", _MACRO_ROC_WINDOW + 20)

    curve_t10y2y = t10y2y_obs[0][1] if t10y2y_obs else None
    curve_t10y3m = t10y3m_obs[0][1] if t10y3m_obs else None
    real_yield_10y = ry_obs[0][1] if ry_obs else None
    dxy_roc = _roc(dxy_obs, _MACRO_ROC_WINDOW)
    real_yield_roc = _roc(ry_obs, _MACRO_ROC_WINDOW)

    # Directional sub-multipliers (bounded); a rising dollar / rising real yields tightens
    # conditions -> veto side (<1.0); falling -> confirm side (>1.0).
    subs: dict[str, float] = {}
    if dxy_roc is not None:
        subs["dxy_roc"] = _clamp(1.0 - dxy_roc * _MACRO_DXY_K, _MACRO_FLOOR, _MACRO_CEIL)
    if real_yield_roc is not None:
        subs["real_yield_roc"] = _clamp(1.0 - real_yield_roc * _MACRO_RY_K, _MACRO_FLOOR, _MACRO_CEIL)

    # Drop-None then clamp the average (mirrors get_multiplier: an unavailable leg is
    # dropped, never averaged in as a neutral 1.0). No survivors -> neutral 1.0.
    if subs:
        macro_multiplier = _clamp(sum(subs.values()) / len(subs), _MACRO_FLOOR, _MACRO_CEIL)
    else:
        macro_multiplier = 1.0

    # Nothing usable at all (no curve, no level, no directional leg) -> no row.
    if (curve_t10y2y is None and curve_t10y3m is None
            and real_yield_10y is None and not subs):
        log.warning("[macro] no FRED macro data available — skipping macro_legs_daily row")
        return []

    # Key by the freshest FRED observation date among the fetched series (fallback: today).
    dates = [o[0][0] for o in (t10y2y_obs, t10y3m_obs, dxy_obs, ry_obs) if o]
    date_utc = max(dates) if dates else date.today().isoformat()

    return [{
        "date_utc": date_utc,
        "copper_gold_roc": None,   # yfinance-ETF leg — out of r22 FRED scope
        "dxy_roc": dxy_roc,
        "semis_rs": None,          # yfinance-ETF leg — out of r22 FRED scope
        "cyc_def_div": None,       # yfinance-ETF leg — out of r22 FRED scope
        "curve_t10y2y": curve_t10y2y,
        "curve_t10y3m": curve_t10y3m,
        "macro_multiplier": macro_multiplier,
        "legs_used_json": json.dumps(sorted(subs.keys())),
        "real_yield_10y": real_yield_10y,
    }]


# ---------------------------------------------------------------------------
# Correctness gate — independent pandas recompute on >=3 sampled rows per table
# ---------------------------------------------------------------------------

def _pop_zscore_last(arr) -> float:
    # Drop NaN so an early-history rolling window (fewer than the cap of valid
    # distance points, with leading NaN from the 200-day SMA warm-up) computes
    # the z over the VALID points only — mirroring regime._compute_trend, which
    # builds its dist_series from valid distances exclusively. Without this the
    # NaN poison std -> NaN -> 0.0 and the gate spuriously fails early dates.
    arr = arr[~pd.isna(arr)]
    if len(arr) == 0:
        return 0.0
    m = arr.mean()
    s = arr.std(ddof=0)
    return float((arr[-1] - m) / s) if s > 0 else 0.0


def _gate_sector(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-9) -> int:
    if not rows:
        return 0
    n = rows[0]["n_window"]
    k = rows[0]["k_window"]
    spy = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}

    def pop_z(s: pd.Series, w: int) -> pd.Series:
        mean = s.rolling(w).mean()
        std = s.rolling(w).std(ddof=0)
        z = (s - mean) / std
        return z.where(std > 0, 0.0)

    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        etf = row["etf"]
        rs = 100.0 * panel[etf].astype(float) / spy
        rs_ratio = 100.0 + pop_z(rs, n)
        roc = rs_ratio.diff(1)
        rs_mom = 100.0 + pop_z(roc, k)
        i = pos[row["date_utc"]]
        exp_rr, exp_rm = float(rs_ratio.iloc[i]), float(rs_mom.iloc[i])
        if abs(exp_rr - row["rs_ratio"]) > tol or abs(exp_rm - row["rs_momentum"]) > tol:
            fails.append(f"  sector {row['date_utc']} {etf}: rr {exp_rr} vs {row['rs_ratio']} "
                         f"rm {exp_rm} vs {row['rs_momentum']}")
    if fails:
        raise AssertionError("sector gate FAILED:\n" + "\n".join(fails))
    return len(sample)


def _gate_factor(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-9) -> int:
    if not rows:
        return 0
    rw = int(cfg.get("features.factor_rotation.rs_window", 21))
    mw = int(cfg.get("features.factor_rotation.mom_window", 63))
    spy = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}
    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        etf = row["factor_etf"]
        rs = 100.0 * panel[etf].astype(float) / spy
        rsv = 100.0 * (rs / rs.shift(rw) - 1.0)
        rmo = 100.0 * (rs / rs.shift(mw) - 1.0)
        i = pos[row["date_utc"]]
        exp_v, exp_m = float(rsv.iloc[i]), float(rmo.iloc[i])
        if abs(exp_v - row["rs_vs_spy"]) > tol or abs(exp_m - row["rs_momentum"]) > tol:
            fails.append(f"  factor {row['date_utc']} {etf}: v {exp_v} vs {row['rs_vs_spy']} "
                         f"m {exp_m} vs {row['rs_momentum']}")
    if fails:
        raise AssertionError("factor gate FAILED:\n" + "\n".join(fails))
    return len(sample)


def _gate_trend(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-6) -> int:
    if not rows:
        return 0
    sma_slow = cfg.get("features.trend_regime.sma_slow", 200)
    sma_fast = cfg.get("features.trend_regime.sma_fast", 50)
    tsmom_lb = cfg.get("features.trend_regime.tsmom_lookback_days", 63)
    slope_window = cfg.get("features.trend_regime.slope_window", 10)
    dist_cap = regime._DIST_Z_MAX_POINTS

    closes = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}
    sma200 = closes.rolling(sma_slow).mean()
    sma50 = closes.rolling(sma_fast).mean()
    slope = (sma50 - sma50.shift(slope_window)) / sma50.shift(slope_window)
    tsmom = closes / closes.shift(tsmom_lb) - 1.0
    dist = closes / sma200 - 1.0
    distz = dist.rolling(dist_cap, min_periods=1).apply(_pop_zscore_last, raw=True)

    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        i = pos[row["date_utc"]]
        checks = {
            "sma_200": (float(sma200.iloc[i]), row["sma_200"]),
            "sma_50": (float(sma50.iloc[i]), row["sma_50"]),
            "sma_50_slope": (float(slope.iloc[i]), row["sma_50_slope"]),
            "tsmom_3m": (float(tsmom.iloc[i]), row["tsmom_3m"]),
            "dist_200_z": (float(distz.iloc[i]), row["dist_200_z"]),
        }
        for name, (exp, got) in checks.items():
            if abs(exp - got) > tol:
                fails.append(f"  trend {row['date_utc']} {name}: {exp} vs {got}")
    if fails:
        raise AssertionError("trend gate FAILED:\n" + "\n".join(fails))
    return len(sample)


# ---------------------------------------------------------------------------
# Persistence (idempotent INSERT OR REPLACE into the target db)
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.create_function("unixepoch", 0, lambda: int(time.time()))  # 3.38 shim, mirror db.py
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the market tables if absent (CREATE TABLE IF NOT EXISTS, shared DDL)."""
    from consensus_engine.db import SCHEMA
    conn.executescript(SCHEMA)
    # r22: the live consensus.db created macro_legs_daily at schema v21 WITHOUT
    # real_yield_10y; CREATE TABLE IF NOT EXISTS is a no-op there, so add the column
    # defensively (idempotent, matches db._run_column_migrations) — this producer connects
    # with plain sqlite3 and does NOT run the async migration path.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(macro_legs_daily)").fetchall()}
    if "real_yield_10y" not in cols:
        conn.execute("ALTER TABLE macro_legs_daily ADD COLUMN real_yield_10y REAL")


def seed(conn: sqlite3.Connection, sector_rows: list[dict],
         factor_rows: list[dict], trend_rows: list[dict],
         breadth_rows: list[dict] | None = None,
         macro_rows: list[dict] | None = None,
         market_breadth_rows: list[dict] | None = None) -> None:
    now_ts = time.time()
    for r in sector_rows:
        conn.execute(
            """INSERT OR REPLACE INTO sector_rs_daily
               (date_utc, etf, rs_ratio, rs_momentum, quadrant, inflection,
                n_window, k_window, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["etf"], r["rs_ratio"], r["rs_momentum"], r["quadrant"],
             r["inflection"], r["n_window"], r["k_window"], now_ts),
        )
    for r in factor_rows:
        conn.execute(
            """INSERT OR REPLACE INTO factor_rs_daily
               (date_utc, factor_etf, rs_vs_spy, rs_momentum, leading,
                accelerating, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["factor_etf"], r["rs_vs_spy"], r["rs_momentum"],
             r["leading"], r["accelerating"], now_ts),
        )
    for r in trend_rows:
        conn.execute(
            """INSERT OR REPLACE INTO trend_daily
               (date_utc, index_symbol, close, sma_200, sma_50, sma_50_slope,
                tsmom_3m, dist_200_z, trend_state, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["index_symbol"], r["close"], r["sma_200"], r["sma_50"],
             r["sma_50_slope"], r["tsmom_3m"], r["dist_200_z"], r["trend_state"], now_ts),
        )
    for r in (breadth_rows or []):
        conn.execute(
            """INSERT OR REPLACE INTO internal_breadth_daily
               (date_utc, net_bull_bear, n_bullish, n_bearish, osc_z, n_signals,
                computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["net_bull_bear"], r["n_bullish"], r["n_bearish"],
             r["osc_z"], r["n_signals"], now_ts),
        )
    for r in (macro_rows or []):
        conn.execute(
            """INSERT OR REPLACE INTO macro_legs_daily
               (date_utc, copper_gold_roc, dxy_roc, semis_rs, cyc_def_div,
                curve_t10y2y, curve_t10y3m, macro_multiplier, legs_used_json,
                real_yield_10y, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["copper_gold_roc"], r["dxy_roc"], r["semis_rs"],
             r["cyc_def_div"], r["curve_t10y2y"], r["curve_t10y3m"],
             r["macro_multiplier"], r["legs_used_json"], r["real_yield_10y"], now_ts),
        )
    for r in (market_breadth_rows or []):
        conn.execute(
            """INSERT OR REPLACE INTO market_breadth_daily
               (date_utc, rsp_spy_ratio, rsp_spy_trend, iwm_spy_ratio,
                iwm_spy_trend, breadth_state, window_days, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["rsp_spy_ratio"], r["rsp_spy_trend"],
             r["iwm_spy_ratio"], r["iwm_spy_trend"], r["breadth_state"],
             r["window_days"], now_ts),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(db_path: str, days: int | None, dry_run: bool,
        store_dir: str | None = None, download: bool = True) -> dict[str, int]:
    """Compute + gate + persist the daily market-context rows; return write counts.

    ``db_path``    target SQLite db (NON-live in tests). Ignored on dry-run.
    ``days``       self-heal window (last N calendar days); None = full backfill.
    ``dry_run``    compute + run the correctness gate but write nothing.
    ``store_dir``  override the Parquet store dir (tests point at data/market_store).
    ``download``   True (default) refreshes the store with the latest yfinance
                   closes BEFORE computing, so the live cron self-updates; False
                   skips the fetch and computes from the cached store (offline /
                   tests). A refresh failure is non-fatal — see ``refresh_store``.
    """
    if download:
        refresh_store(store_dir)
    else:
        log.info("[market_daily] --no-download: computing from the cached store only.")
    panel = _load_closes(store_dir)
    if panel.empty:
        log.error("[market_daily] empty close panel — check the store at %s",
                  _resolve_store_dir(store_dir))
        return {"sector_rs_daily": 0, "factor_rs_daily": 0, "trend_daily": 0,
                "internal_breadth_daily": 0, "macro_legs_daily": 0,
                "market_breadth_daily": 0}
    log.info("[market_daily] panel %d rows, %s -> %s (%d symbols)",
             len(panel), str(panel.index[0])[:10], str(panel.index[-1])[:10],
             panel.shape[1])

    sector_rows = build_sector_rows(panel, days)
    factor_rows = build_factor_rows(panel, days)
    trend_rows = build_trend_rows(panel, days)
    # F5 breadth reads the bot's OWN directional stream (signal_events) from the
    # target db, not the parquet panel — empty on a fresh db with no signals.
    breadth_rows = build_breadth_rows(db_path, days)
    # r22 (macro-fred): descriptive F4 macro leg from FRED. Runs when the macro_legs
    # feature is enabled OR shadow (shadow:true in prod → collect forward data); the
    # baseline test suite forces both OFF (conftest) so it never hits FRED. Best-effort:
    # build_macro_rows returns [] on any FRED problem.
    macro_on = bool(cfg.get("features.macro_legs.enabled", False)
                    or cfg.get("features.macro_legs.shadow", False))
    macro_rows = build_macro_rows(days) if macro_on else []
    # r20 (standalone-scanners): RSP/SPY participation proxy. Runs when market_breadth
    # is enabled OR shadow (shadow:true in prod -> collect forward data without touching
    # the !market panel); the baseline test suite forces both OFF (conftest) so it never
    # fetches. Descriptive-only — the row is NEVER read by cross_reference.score_ticker.
    breadth_on = bool(cfg.get("features.market_breadth.enabled", False)
                      or cfg.get("features.market_breadth.shadow", False))
    market_breadth_rows = build_market_breadth_rows(days) if breadth_on else []

    # Correctness gate BEFORE any write (independent pandas recompute).
    checked = (_gate_sector(sector_rows, panel)
               + _gate_factor(factor_rows, panel)
               + _gate_trend(trend_rows, panel))
    log.info("[gate] correctness check PASSED on %d sampled rows "
             "(sector+factor+trend, independent pandas recompute)", checked)

    summary = {
        "sector_rs_daily": len(sector_rows),
        "factor_rs_daily": len(factor_rows),
        "trend_daily": len(trend_rows),
        "internal_breadth_daily": len(breadth_rows),
        "macro_legs_daily": len(macro_rows),
        "market_breadth_daily": len(market_breadth_rows),
    }
    if dry_run:
        log.info("[dry-run] computed %s — NO writes performed.", summary)
        return summary

    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        seed(conn, sector_rows, factor_rows, trend_rows, breadth_rows, macro_rows,
             market_breadth_rows)
    finally:
        conn.close()
    log.info("[market_daily] seeded %s into %s", summary, db_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily market-context orchestrator: seed sector_rs_daily / "
                    "factor_rs_daily / trend_daily from the cached Parquet store.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + run the correctness gate; do NOT write.")
    parser.add_argument("--days", type=int, default=None, metavar="N",
                        help="Self-heal: re-seed only the last N calendar days.")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config). "
                             "Pass a NON-live path for backfills/tests.")
    parser.add_argument("--store-dir", type=str, default=None, metavar="DIR",
                        help="Override the Parquet store dir "
                             "(default: features.market_data.store_dir).")
    parser.add_argument("--no-download", action="store_true",
                        help="Skip the yfinance refresh; compute from the cached "
                             "Parquet store only (offline / tests).")
    args = parser.parse_args()

    db_path = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")

    summary = run(db_path=db_path, days=args.days, dry_run=args.dry_run,
                  store_dir=args.store_dir, download=not args.no_download)
    total = sum(summary.values())
    if total == 0 and args.days is not None:
        log.info("Self-heal: no new trading days in last %d days — already current.",
                 args.days)
        return 0
    if total == 0:
        log.error("No rows computed — check the Parquet store coverage.")
        return 1
    print()
    print(f"Rows {'computed (dry-run)' if args.dry_run else 'seeded'}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
