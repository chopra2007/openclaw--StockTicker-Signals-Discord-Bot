"""Ticker fundamentals/analyst snapshot for the !all command (#6 lever).

Surfaces the single most-ubiquitous thing competitor ticker pages show that
`!all` lacked: the Wall-Street analyst price target + rating, plus forward P/E
and short interest. All from ONE yfinance `.info` fetch (free; pre-flight
GREEN on NVDA/AMD/SOFI 2026-05-31).

Design (regression-safe + latency-bounded — mirrors peer_comparison.py):
  * Own SMALL bounded ThreadPoolExecutor so the single blocking `.info` call
    can't starve the shared default pool the rest of !all uses (Pass-3 critic
    M1). `.info` measured at 0.4-0.7s.
  * asyncio.wait_for bounds the fetch; an empty/throttled `.info` (yfinance
    returns {} indistinguishably from a delisted ticker) logs a warning so the
    throttle rate is observable, and returns None -> the embed field is omitted.
  * Every key is .get()-guarded and NaN-filtered; returns None when neither the
    analyst block nor the fundamentals block has any data, so the field never
    renders empty.
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger(__name__)

# Dedicated bounded pool — keeps the blocking .info call off the shared executor.
_SNAPSHOT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot")

_FETCH_TIMEOUT_S = 8.0
# #6 Lever 1: eps_revisions is a SEPARATE lazy yfinance endpoint (its own quoteSummary
# network call — it does NOT ride .info). Fetched under its own short timeout so a slow
# analyst-revisions call nulls only that field and never delays/fails the main snapshot.
_EPS_REV_TIMEOUT_S = 4.0

_RATING_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
}

# #6 analyst-consensus momentum: weight each .recommendations bucket so a higher
# score = more bullish (StrongBuy=5 … StrongSell=1). This is the INTUITIVE direction;
# note yfinance's own recommendationMean uses the inverse (1=StrongBuy), which we
# deliberately do NOT use here. Pre-flight (2026-06-13): AMD 0m 5SB/37B/9H → 3.92.
_RATING_WEIGHTS = {"strongBuy": 5, "buy": 4, "hold": 3, "sell": 2, "strongSell": 1}


def _num(val) -> Optional[float]:
    """Coerce to float, dropping None / NaN / non-numeric."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _fetch_info(ticker: str) -> dict:
    """Blocking yfinance fetch: ``.info`` plus the current-fiscal-year EPS estimate.

    Returns {} on any error. The current-FY consensus EPS is stashed under the
    synthetic key ``_eps_cfy`` so the caller can build a forward P/E from
    price ÷ current-FY EPS. yfinance's own ``forwardPE`` divides price by the
    NEXT full fiscal year's EPS estimate, which for a Jan-fiscal-year name like
    NVDA reads ~a year too far out (e.g. ~16 when the rolling figure is ~24).
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        try:
            est = t.earnings_estimate  # separate yfinance endpoint
            if est is not None and "0y" in est.index and "avg" in est.columns:
                eps_cfy = _num(est.loc["0y", "avg"])
                if eps_cfy is not None:
                    info["_eps_cfy"] = eps_cfy
        except Exception:  # noqa: BLE001 — sparse/missing estimate table is normal
            pass
        return info
    except Exception as e:  # noqa: BLE001
        log.warning("snapshot: .info fetch failed for %s: %s", ticker, e)
        return {}


def _fetch_eps_revisions(ticker: str) -> Optional[dict]:
    """Blocking yfinance ``eps_revisions`` read for the CURRENT quarter ('0q').

    Returns {"up": int, "down": int} (analysts who raised/cut their current-quarter EPS
    estimate in the last 30 days) or None. yfinance column casing is inconsistent
    (upLast7days / upLast30days / downLast30days / downLast7Days) — we read the two
    *Last30days columns (both lowercase 'days') and guard for the row + columns being
    present, since the schema drifts and sparse tickers return an empty table."""
    try:
        import yfinance as yf
        rev = yf.Ticker(ticker).eps_revisions  # lazy network fetch (quoteSummary)
        if rev is None or getattr(rev, "empty", True) or "0q" not in rev.index:
            return None
        cols = rev.columns
        up = _num(rev.loc["0q", "upLast30days"]) if "upLast30days" in cols else None
        down = _num(rev.loc["0q", "downLast30days"]) if "downLast30days" in cols else None
        up_i = int(up) if up is not None else 0
        down_i = int(down) if down is not None else 0
        if up_i <= 0 and down_i <= 0:
            return None
        return {"up": up_i, "down": down_i}
    except Exception as e:  # noqa: BLE001 — sparse/missing/renamed table is normal
        log.debug("snapshot: eps_revisions fetch failed for %s: %s", ticker, e)
        return None


def _reco_score(row) -> tuple[Optional[float], int]:
    """Weighted mean rating (StrongBuy=5 … StrongSell=1) for one .recommendations
    row, plus the analyst count. Returns (None, 0) when the row has no analysts."""
    total = 0
    weighted = 0.0
    for col, w in _RATING_WEIGHTS.items():
        c = _num(row.get(col))
        n = int(c) if c is not None and c > 0 else 0
        total += n
        weighted += n * w
    if total <= 0:
        return None, 0
    return weighted / total, total


def _fetch_analyst_momentum(ticker: str) -> Optional[dict]:
    """Blocking yfinance ``.recommendations`` read → analyst-consensus momentum:
    the weighted rating NOW ('0m') vs. the oldest available prior period.

    Returns {"now","prior","shift","n_now","window"} or None. ``.recommendations``
    is a rolling window yfinance returns with only 1–4 rows, so a '-3m' baseline is
    NOT guaranteed (AMD often has just 0m/-1m/-2m); we take the oldest row present as
    the baseline and report the real window ('2mo'/'3mo') so the label never lies."""
    try:
        import yfinance as yf
        rec = yf.Ticker(ticker).recommendations  # lazy network fetch (quoteSummary)
        if rec is None or getattr(rec, "empty", True) or "period" not in getattr(rec, "columns", []):
            return None

        def _months(p: str) -> int:
            try:
                return int(str(p).rstrip("m"))  # '-3m' -> -3, '0m' -> 0
            except ValueError:
                return 0

        periods = {str(p): i for i, p in zip(rec.index, rec["period"])}
        if "0m" not in periods:
            return None
        oldest = min(periods, key=_months)  # most-negative month offset present
        if oldest == "0m":
            return None  # only the current month is present — no trend to show

        now_score, n_now = _reco_score(rec.loc[periods["0m"]])
        prior_score, _ = _reco_score(rec.loc[periods[oldest]])
        if now_score is None or prior_score is None:
            return None
        return {
            "now": round(now_score, 2),
            "prior": round(prior_score, 2),
            "shift": round(now_score - prior_score, 2),
            "n_now": n_now,
            "window": f"{abs(_months(oldest))}mo",
        }
    except Exception as e:  # noqa: BLE001 — sparse/missing/renamed table is normal
        log.debug("snapshot: analyst_momentum fetch failed for %s: %s", ticker, e)
        return None


async def fetch_ticker_snapshot(ticker: str) -> Optional[dict]:
    """Return an analyst+fundamentals snapshot dict, or None when unavailable.

    Keys (all optional): target_mean/high/low, n_analysts, rating, fwd_pe,
    short_pct (fraction, e.g. 0.0092), short_days (days-to-cover).
    """
    from consensus_engine import config as cfg
    if not cfg.get("features.snapshot.enabled", True):
        return None

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(_SNAPSHOT_EXECUTOR, _fetch_info, ticker),
            timeout=_FETCH_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        log.warning("snapshot: fetch timed out/failed for %s: %s", ticker, e)
        return None

    if not info:
        # Empty .info == throttled or delisted; indistinguishable. Logged so the
        # throttle rate is visible; field omits cleanly.
        log.warning("snapshot: empty .info for %s (throttled or no data)", ticker)
        return None

    rating_key = (info.get("recommendationKey") or "").strip().lower()
    rating = _RATING_LABELS.get(rating_key) if rating_key and rating_key != "none" else None

    snap = {
        "target_mean": _num(info.get("targetMeanPrice")),
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
        "n_analysts": int(info["numberOfAnalystOpinions"]) if _num(info.get("numberOfAnalystOpinions")) else None,
        "rating": rating,
        "fwd_pe": None,  # set below from current-FY EPS once price is known
        "short_pct": _num(info.get("shortPercentOfFloat")),
        "short_days": _num(info.get("shortRatio")),
    }

    # #6 lever — 52-week high/low distance, from the SAME .info call.
    # wk52_high_pct negative = below the high; wk52_low_pct positive = above the low.
    wk52_high = _num(info.get("fiftyTwoWeekHigh"))
    wk52_low = _num(info.get("fiftyTwoWeekLow"))
    price = (_num(info.get("currentPrice"))
             or _num(info.get("regularMarketPrice"))
             or _num(info.get("previousClose")))
    snap["wk52_high_pct"] = (price / wk52_high - 1) * 100 if price and wk52_high and wk52_high > 0 else None
    snap["wk52_low_pct"] = (price / wk52_low - 1) * 100 if price and wk52_low and wk52_low > 0 else None
    # full-audit smart-levels: expose RAW 52wk prices (not just % distances) for the
    # technical-levels engine; present whenever snap is returned (before the early None below).
    snap["wk52_high"] = wk52_high
    snap["wk52_low"] = wk52_low

    # Forward P/E on a rolling current-fiscal-year basis: price ÷ current-FY
    # consensus EPS (yfinance earnings_estimate '0y' avg). Honest "Fwd P/E"
    # that tracks the next ~12 months of earnings rather than the year-out
    # figure yfinance's forwardPE field reports. Omits when EPS is missing or
    # ≤ 0 (unprofitable → P/E meaningless).
    eps_cfy = _num(info.get("_eps_cfy"))
    snap["fwd_pe"] = (price / eps_cfy) if (price and eps_cfy and eps_cfy > 0) else None

    # #6 Lever 1: EPS-estimate-revision trend (analyst conviction). Flag-gated; fetched
    # in its OWN bounded call so a slow/hung eps_revisions endpoint nulls only this field.
    if cfg.get("features.snapshot.eps_revisions", False):
        try:
            rev = await asyncio.wait_for(
                loop.run_in_executor(_SNAPSHOT_EXECUTOR, _fetch_eps_revisions, ticker),
                timeout=_EPS_REV_TIMEOUT_S,
            )
            if rev:
                snap["eps_rev"] = rev
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
            log.debug("snapshot: eps_revisions skipped for %s: %s", ticker, e)

    # #6 lever — analyst-consensus momentum (rating now vs. ~3 months ago), from the
    # SEPARATE .recommendations endpoint. Its own bounded call so a slow/hung fetch nulls
    # only this field and never delays the main snapshot. Flag-gated.
    if cfg.get("features.snapshot.analyst_momentum", False):
        try:
            mom = await asyncio.wait_for(
                loop.run_in_executor(_SNAPSHOT_EXECUTOR, _fetch_analyst_momentum, ticker),
                timeout=_EPS_REV_TIMEOUT_S,
            )
            if mom:
                snap["analyst_momentum"] = mom
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
            log.debug("snapshot: analyst_momentum skipped for %s: %s", ticker, e)

    # #6 lever — fundamentals one-liner (PEG / revenue growth / profit margin / beta /
    # institutional %), all read from the SAME .info dict above (zero new network call).
    # Flag-gated; each field independent and omitted when missing/NaN so sparse microcaps
    # degrade gracefully. PEG guarded > 0 (a negative PEG is misleading); profit margin is
    # rendered even when negative (an unprofitable margin is honest signal).
    if cfg.get("features.fundamentals_oneliner.enabled", False):
        peg = _num(info.get("trailingPegRatio"))
        if peg is None:
            peg = _num(info.get("pegRatio"))
        rev_g = _num(info.get("revenueGrowth"))
        margin = _num(info.get("profitMargins"))
        beta = _num(info.get("beta"))
        inst = _num(info.get("heldPercentInstitutions"))
        fund = {
            "peg": peg if (peg is not None and peg > 0) else None,
            "rev_growth_pct": rev_g * 100 if rev_g is not None else None,
            "profit_margin_pct": margin * 100 if margin is not None else None,
            "beta": beta if (beta is not None and beta > 0) else None,
            "inst_pct": inst * 100 if inst is not None else None,
        }
        if any(v is not None for v in fund.values()):
            snap["fundamentals"] = fund

    has_analyst = snap["target_mean"] is not None or snap["rating"] is not None
    has_fundamentals = snap["fwd_pe"] is not None or snap["short_pct"] is not None
    if not has_analyst and not has_fundamentals:
        return None
    return snap
