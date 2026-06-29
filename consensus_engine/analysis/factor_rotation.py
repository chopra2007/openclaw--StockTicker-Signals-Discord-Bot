"""F2: factor / style RS-leadership engine (trade-edge market-context layer).

For each factor/style ETF (MTUM QUAL IWF IWD VLUE USMV SPLV SPHB SIZE IWM RSP)
this measures relative strength *against SPY* and the speed at which that relative
strength is changing, persisting a daily row into ``factor_rs_daily``. This is the
equity-STYLE axis that neither A5 (volatility regime) nor E2 (VIX / credit) touch.

Definition (returns-based, frozen to the preregistered windows so the formula is
unambiguous; mirrors ``sector_rotation.py``'s module structure):

    rs[t]          = 100 * etf_close[t] / spy_close[t]            (relative strength line)
    rs_vs_spy[t]   = 100 * (rs[t] / rs[t - rs_window]  - 1)       (short RS return vs SPY)
    rs_momentum[t] = 100 * (rs[t] / rs[t - mom_window] - 1)       (long  RS return vs SPY)

    rs_window  -> the short relative-strength lookback (default 21 trading days)
    mom_window -> the long  relative-strength lookback (default 63 trading days)

    leading      = rs_vs_spy > 0        (the factor is out-performing SPY over rs_window)
    accelerating = (rs_vs_spy / rs_window) > (rs_momentum / mom_window)  -> True  (speeding up)
                                          <                              -> False (fading)
                                          ==                             -> None  (flat)

``accelerating`` compares the per-day RS gain over the short window with the per-day
RS gain over the long window, so the two horizons are put on the same footing before
they are compared.

Point-in-time: every value at date t uses ONLY closes up to and including t (the
trailing lookbacks rs[t-rs_window] / rs[t-mom_window]). So the value computed on the
full series equals the value computed on the prefix to t (truncation test).

Live read path: ``lookup_factor_leadership`` reads the persisted table only (the daily
cron writes it); it returns a cold start when the flag is OFF, there is no row, or the
freshest row is stale — mirroring ``sector_rotation.lookup_rotation``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# The 11-factor/style universe (db.py factor_rs_daily comment / final-plan §4).
FACTOR_ETFS: tuple[str, ...] = (
    "MTUM", "QUAL", "IWF", "IWD", "VLUE", "USMV", "SPLV", "SPHB", "SIZE", "IWM", "RSP",
)
BENCHMARK = "SPY"


@dataclass
class FactorContext:
    factor_etf: str
    rs_vs_spy: float
    rs_momentum: float
    leading: bool
    accelerating: Optional[bool]   # True = speeding up, False = fading, None = flat
    as_of_date: str                # YYYY-MM-DD


@dataclass
class FactorLeadership:
    """Cross-sectional read on the latest persisted date."""
    as_of_date: str                       # YYYY-MM-DD, "" on cold start
    leaders: list[FactorContext]          # leading factors, rs_vs_spy high -> low
    accelerating: list[str]               # factor_etfs with accelerating True, rs_vs_spy desc
    fading: list[str]                     # factor_etfs with accelerating False, rs_vs_spy desc
    cold_start: bool                      # True until a fresh factor_rs_daily row exists


_COLD_LEADERSHIP = FactorLeadership(
    as_of_date="", leaders=[], accelerating=[], fading=[], cold_start=True,
)


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------

def _params(rs_window, mom_window) -> tuple[int, int]:
    rw = int(rs_window if rs_window is not None
             else cfg.get("features.factor_rotation.rs_window", 21))
    mw = int(mom_window if mom_window is not None
             else cfg.get("features.factor_rotation.mom_window", 63))
    return rw, mw


def _accel_bool(value) -> Optional[bool]:
    """Normalise an accelerating flag (1/0/None or True/False/None) to bool|None."""
    if value is None:
        return None
    return bool(value)


# ---------------------------------------------------------------------------
# Core math (pure python on trailing lookbacks — point-in-time by construction)
# ---------------------------------------------------------------------------

def _compute_one(rs: list[float], rw: int, mw: int) -> list[Optional[dict]]:
    """Per-date rs_vs_spy / rs_momentum / leading / accelerating for one rs series.

    Returns a list aligned with ``rs``; entries are None until enough trailing
    history exists (both rs[t-rw] and rs[t-mw] must be available, i.e. t >= max(rw, mw)).
    """
    m = len(rs)
    lookback = max(rw, mw)
    out: list[Optional[dict]] = [None] * m
    for t in range(m):
        if t < lookback:
            continue
        base_s = rs[t - rw]
        base_l = rs[t - mw]
        if not base_s or not base_l:        # 0 / nan guard
            continue
        rsv = 100.0 * (rs[t] / base_s - 1.0)
        rmo = 100.0 * (rs[t] / base_l - 1.0)
        short_rate = rsv / rw
        long_rate = rmo / mw
        if short_rate > long_rate:
            accel: Optional[bool] = True
        elif short_rate < long_rate:
            accel = False
        else:
            accel = None
        out[t] = {
            "rs_vs_spy": rsv,
            "rs_momentum": rmo,
            "leading": rsv > 0.0,
            "accelerating": accel,
        }
    return out


def compute_factor_series(closes_df, rs_window=None, mom_window=None,
                          ) -> dict[str, list[Optional[dict]]]:
    """Full per-factor RS series (every date, point-in-time).

    ``closes_df`` is a date-indexed DataFrame whose columns include the factor ETF
    symbols and ``SPY``. Returns {factor_etf: [per-date dict | None]} aligned with
    the DataFrame's row order. Exposed (used by the backfill/cron + tests).
    """
    rw, mw = _params(rs_window, mom_window)
    if BENCHMARK not in closes_df.columns:
        raise ValueError(f"factor_rotation: closes_df missing {BENCHMARK!r} column")

    spy = [float(x) for x in closes_df[BENCHMARK].tolist()]
    result: dict[str, list[Optional[dict]]] = {}
    for etf in FACTOR_ETFS:
        if etf not in closes_df.columns:
            continue
        closes = [float(x) for x in closes_df[etf].tolist()]
        rs = [100.0 * c / s if s else float("nan") for c, s in zip(closes, spy)]
        result[etf] = _compute_one(rs, rw, mw)
    return result


def compute_factor_rows(closes_df, rs_window=None, mom_window=None) -> list[dict]:
    """Compute the latest-date factor rows ready for ``factor_rs_daily`` insert.

    Returns one dict per factor (those with enough history on the last date):
    {date_utc, factor_etf, rs_vs_spy, rs_momentum, leading, accelerating}. The
    daily cron adds ``computed_at``. Uses the PRIOR close only (the last row of
    ``closes_df`` should be the most recent known close).
    """
    rw, mw = _params(rs_window, mom_window)
    series = compute_factor_series(closes_df, rw, mw)
    if len(closes_df.index) == 0:
        return []
    last_i = len(closes_df.index) - 1
    date_utc = str(closes_df.index[last_i])[:10]

    rows: list[dict] = []
    for etf, cells in series.items():
        cell = cells[last_i]
        if cell is None:
            continue
        accel = cell["accelerating"]
        rows.append({
            "date_utc": date_utc,
            "factor_etf": etf,
            "rs_vs_spy": cell["rs_vs_spy"],
            "rs_momentum": cell["rs_momentum"],
            "leading": 1 if cell["leading"] else 0,
            "accelerating": None if accel is None else (1 if accel else 0),
        })
    return rows


# ---------------------------------------------------------------------------
# Leadership builder (pure; shared by the live read path and the compute tests)
# ---------------------------------------------------------------------------

def build_leadership(rows: list[dict], as_of_date: str,
                     cold_start: bool) -> FactorLeadership:
    """Roll up factor rows into leaders + accelerating/fading lists.

    ``rows`` are factor_rs_daily-shaped dicts (from ``compute_factor_rows`` or the
    DB). ``leaders`` = leading factors ranked rs_vs_spy high->low; ``accelerating``
    / ``fading`` are factor_etf name lists (also rs_vs_spy desc) split on the
    accelerating flag (flat / None factors fall in neither list).
    """
    if cold_start:
        return _COLD_LEADERSHIP
    ordered = sorted(rows, key=lambda r: r["rs_vs_spy"], reverse=True)
    leaders = [
        FactorContext(
            factor_etf=r["factor_etf"],
            rs_vs_spy=r["rs_vs_spy"],
            rs_momentum=r["rs_momentum"],
            leading=bool(r["leading"]),
            accelerating=_accel_bool(r["accelerating"]),
            as_of_date=as_of_date,
        )
        for r in ordered if r["leading"]
    ]
    accelerating = [r["factor_etf"] for r in ordered if _accel_bool(r["accelerating"]) is True]
    fading = [r["factor_etf"] for r in ordered if _accel_bool(r["accelerating"]) is False]
    return FactorLeadership(
        as_of_date=as_of_date,
        leaders=leaders,
        accelerating=accelerating,
        fading=fading,
        cold_start=False,
    )


# ---------------------------------------------------------------------------
# Live read path (engine / command) — reads the persisted table, no fetch
# ---------------------------------------------------------------------------

async def lookup_factor_leadership() -> FactorLeadership:
    """Read the newest ``factor_rs_daily`` date and roll it up into a leadership read.

    Cold start (flag OFF / no row / stale row) -> ``_COLD_LEADERSHIP``. Mirrors
    sector_rotation.lookup_rotation: the daily cron writes the table; this only reads it.
    """
    if not cfg.get("features.factor_rotation.enabled", False):
        return _COLD_LEADERSHIP

    from consensus_engine.analysis import market_panel

    latest = await market_panel.get_latest_row("factor_rs_daily")
    if not latest:
        return _COLD_LEADERSHIP

    if market_panel.is_stale(latest["computed_at"]):
        age = market_panel.row_age_days(latest["computed_at"])
        log.warning("[F2] factor_rs_daily is %.1f days old — cold start", age)
        return _COLD_LEADERSHIP

    date_utc = latest["date_utc"]
    rows = await market_panel.get_recent_rows(
        "factor_rs_daily", limit=len(FACTOR_ETFS), filters={"date_utc": date_utc}
    )
    return build_leadership(rows, date_utc, cold_start=False)
