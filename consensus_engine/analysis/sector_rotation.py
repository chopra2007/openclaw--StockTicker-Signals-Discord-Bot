"""F1: sector-rotation RRG-Lite engine (trade-edge market-context layer).

Ranks the 13 sector ETFs *against SPY* and against each other, persisting a
multi-day RS-Ratio / RS-Momentum series plus a lagging->improving inflection
flag into ``sector_rs_daily``. This is the cross-sectional read that A4 (single
same-day ETF gate), #6 / Wolf (per-ticker RS) do NOT produce.

Definition (RRG-Lite, StockCharts JdK style; frozen mapping to the
preregistered params so the formula is unambiguous):

    rs[t]          = 100 * etf_close[t] / spy_close[t]          (relative strength)
    rs_ratio[t]    = 100 + zscore over the trailing N (=n_window) of rs
    roc[t]         = rs_ratio[t] - rs_ratio[t-1]                (1-day ROC of the ratio)
    rs_momentum[t] = 100 + zscore over the trailing k (=k_window) of roc

    N = n_window  -> the RS-Ratio normalisation window (smoothed RS level)
    k = k_window  -> the RS-Momentum normalisation window
    ROC lag       -> 1 trading day (the day-over-day change of rs_ratio)

``zscore`` is the population z-score of the last value in the window:
``(x[-1] - mean(window)) / std(window)``; a zero-variance window yields 0
(so rs_ratio / rs_momentum collapse to the 100 mid-line).

Quadrant from the 100/100 split:
    rs_ratio >= 100 & rs_momentum >= 100 -> leading     (strong + accelerating)
    rs_ratio >= 100 & rs_momentum <  100 -> weakening    (strong but rolling over)
    rs_ratio <  100 & rs_momentum <  100 -> lagging      (weak + decelerating)
    rs_ratio <  100 & rs_momentum >= 100 -> improving    (weak but turning up = early)

Inflection (the actionable event) = a lagging->improving transition that is
confirmed: the ETF is currently ``improving``, has been improving for at least
``persistence`` (P) consecutive days, the quadrant immediately before that run
was ``lagging``, and the momentum distance above the mid-line
(rs_momentum - 100) exceeds ``distance`` (D).

Point-in-time: every value at date t uses ONLY closes up to and including t
(trailing windows + the PRIOR close — never the same-day look-ahead). So the
value computed on the full series equals the value computed on the prefix to t.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# The 13-ETF universe (db.py sector_rs_daily comment / final-plan §4).
SECTOR_ETFS: tuple[str, ...] = (
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC",
    "SMH", "XBI",
)
BENCHMARK = "SPY"

_QUADRANTS = ("leading", "weakening", "lagging", "improving")


@dataclass
class RotationContext:
    etf: str
    rs_ratio: float
    rs_momentum: float
    quadrant: str        # one of _QUADRANTS, or "" on cold start
    inflection: bool     # True = lagging->improving fired on as_of_date
    cold_start: bool     # True until a fresh sector_rs_daily row exists
    as_of_date: str      # YYYY-MM-DD


_COLD_START = RotationContext(
    etf="", rs_ratio=100.0, rs_momentum=100.0, quadrant="", inflection=False,
    cold_start=True, as_of_date="",
)


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------

def _params(n_window, k_window, distance, persistence) -> tuple[int, int, float, int]:
    n = int(n_window if n_window is not None
            else cfg.get("features.sector_rotation.n_window", 10))
    k = int(k_window if k_window is not None
            else cfg.get("features.sector_rotation.k_window", 5))
    d = float(distance if distance is not None
              else cfg.get("features.sector_rotation.distance", 2))
    p = int(persistence if persistence is not None
            else cfg.get("features.sector_rotation.persistence", 2))
    return n, k, d, p


# ---------------------------------------------------------------------------
# Core math (pure python on trailing windows — point-in-time by construction)
# ---------------------------------------------------------------------------

def _zscore_last(window: list[float]) -> float:
    """Population z-score of the last value within ``window``; 0 if no variance."""
    n = len(window)
    mean = sum(window) / n
    var = sum((x - mean) ** 2 for x in window) / n
    std = math.sqrt(var)
    if std <= 0:
        return 0.0
    return (window[-1] - mean) / std


def _quadrant(rs_ratio: float, rs_momentum: float) -> str:
    strong = rs_ratio >= 100.0
    accel = rs_momentum >= 100.0
    if strong and accel:
        return "leading"
    if strong and not accel:
        return "weakening"
    if not strong and not accel:
        return "lagging"
    return "improving"


def _compute_etf_series(rs: list[float], n: int, k: int) -> list[Optional[dict]]:
    """Per-date rs_ratio / rs_momentum / quadrant for one ETF's rs series.

    Returns a list aligned with ``rs``; entries are None until enough trailing
    history exists (rs_ratio needs N closes; rs_momentum needs N + k closes for
    the k trailing 1-day ROCs of the ratio).
    """
    m = len(rs)
    rs_ratio: list[Optional[float]] = [None] * m
    for t in range(m):
        if t >= n - 1:
            rs_ratio[t] = 100.0 + _zscore_last(rs[t - n + 1: t + 1])

    roc: list[Optional[float]] = [None] * m
    for t in range(1, m):
        if rs_ratio[t] is not None and rs_ratio[t - 1] is not None:
            roc[t] = rs_ratio[t] - rs_ratio[t - 1]

    out: list[Optional[dict]] = [None] * m
    for t in range(m):
        if rs_ratio[t] is None or t - k + 1 < 0:
            continue
        win = roc[t - k + 1: t + 1]
        if any(v is None for v in win):
            continue
        rm = 100.0 + _zscore_last(win)  # type: ignore[arg-type]
        rr = rs_ratio[t]
        out[t] = {
            "rs_ratio": rr,
            "rs_momentum": rm,
            "quadrant": _quadrant(rr, rm),
        }
    return out


def _mark_inflections(series: list[Optional[dict]], distance: float,
                      persistence: int) -> None:
    """Set series[t]['inflection'] in-place: lagging->improving, persisted + far.

    Looks only backward, so it stays point-in-time. Fires on date t when the
    current quadrant is 'improving', the consecutive improving run ending at t is
    >= persistence days, the quadrant just before that run was 'lagging', and
    (rs_momentum - 100) > distance.
    """
    for t, cell in enumerate(series):
        if cell is None:
            continue
        cell["inflection"] = False
        if cell["quadrant"] != "improving":
            continue
        # length of the consecutive 'improving' run ending at t
        run = 0
        i = t
        while i >= 0 and series[i] is not None and series[i]["quadrant"] == "improving":
            run += 1
            i -= 1
        prior = series[i] if i >= 0 else None
        prior_is_lagging = prior is not None and prior["quadrant"] == "lagging"
        far_enough = (cell["rs_momentum"] - 100.0) > distance
        if run >= persistence and prior_is_lagging and far_enough:
            cell["inflection"] = True


def compute_series(closes_df, n_window=None, k_window=None, distance=None,
                   persistence=None) -> dict[str, list[Optional[dict]]]:
    """Full per-ETF rotation series (every date, point-in-time).

    ``closes_df`` is a date-indexed DataFrame whose columns include the ETF
    symbols and ``SPY``. Returns {etf: [per-date dict | None]} aligned with the
    DataFrame's row order. Exposed (used by the backfill/cron + tests).
    """
    n, k, d, p = _params(n_window, k_window, distance, persistence)
    if BENCHMARK not in closes_df.columns:
        raise ValueError(f"sector_rotation: closes_df missing {BENCHMARK!r} column")

    spy = [float(x) for x in closes_df[BENCHMARK].tolist()]
    result: dict[str, list[Optional[dict]]] = {}
    for etf in SECTOR_ETFS:
        if etf not in closes_df.columns:
            continue
        closes = [float(x) for x in closes_df[etf].tolist()]
        rs = [100.0 * c / s if s else float("nan") for c, s in zip(closes, spy)]
        series = _compute_etf_series(rs, n, k)
        _mark_inflections(series, d, p)
        result[etf] = series
    return result


def compute_rotation(closes_df, n_window=None, k_window=None, distance=None,
                     persistence=None) -> list[dict]:
    """Compute the latest-date rotation rows ready for ``sector_rs_daily`` insert.

    Returns one dict per ETF (those with enough history on the last date):
    {date_utc, etf, rs_ratio, rs_momentum, quadrant, inflection, n_window,
    k_window}. Uses the PRIOR close only (the last row of ``closes_df`` should be
    the most recent known close).
    """
    n, k, d, p = _params(n_window, k_window, distance, persistence)
    series = compute_series(closes_df, n, k, d, p)
    if len(closes_df.index) == 0:
        return []
    last_i = len(closes_df.index) - 1
    date_utc = str(closes_df.index[last_i])[:10]

    rows: list[dict] = []
    for etf, cells in series.items():
        cell = cells[last_i]
        if cell is None:
            continue
        rows.append({
            "date_utc": date_utc,
            "etf": etf,
            "rs_ratio": cell["rs_ratio"],
            "rs_momentum": cell["rs_momentum"],
            "quadrant": cell["quadrant"],
            "inflection": 1 if cell["inflection"] else 0,
            "n_window": n,
            "k_window": k,
        })
    return rows


# ---------------------------------------------------------------------------
# Live read path (engine / command) — reads the persisted table, no fetch
# ---------------------------------------------------------------------------

async def lookup_rotation(sector_etf: str) -> RotationContext:
    """Read the newest ``sector_rs_daily`` row for ``sector_etf``.

    Cold start (flag OFF / no row / stale row) -> ``_COLD_START``. Mirrors
    regime.lookup_regime: the daily cron writes the table; this only reads it.
    """
    if not cfg.get("features.sector_rotation.enabled", False):
        return _COLD_START

    from consensus_engine.analysis import market_panel

    etf = sector_etf.upper()
    row = await market_panel.get_latest_row("sector_rs_daily", {"etf": etf})
    if not row:
        return _COLD_START

    if market_panel.is_stale(row["computed_at"]):
        age = market_panel.row_age_days(row["computed_at"])
        log.warning("[F1] sector_rs_daily for %s is %.1f days old — cold start", etf, age)
        return _COLD_START

    return RotationContext(
        etf=etf,
        rs_ratio=row["rs_ratio"],
        rs_momentum=row["rs_momentum"],
        quadrant=row["quadrant"],
        inflection=bool(row["inflection"]),
        cold_start=False,
        as_of_date=row["date_utc"],
    )
