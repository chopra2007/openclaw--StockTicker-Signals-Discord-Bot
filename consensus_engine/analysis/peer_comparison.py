"""Relative-strength peer comparison for the !all command (#6 lever / item 3).

Answers "is this stock beating or lagging its true peers?" — a directional
signal (outperform = bullish, underperform = bearish). Computes the stock's
N-day % move minus the average of its peers' N-day moves.

FREE data only: yfinance daily closes (already used elsewhere in the engine).

Design (regression-safe + latency-bounded — see the Pass-3 critic review):
  * Peers come from data/peer_groups.yaml (curated, keyed by yfinance
    .info['industry']). A ticker NOT listed there is resolved at runtime from
    its yfinance .info industry/sector, cached in the ticker_sector_cache DB
    table (db.get/set_ticker_sector). Curated industry match → that group's
    peers; else broad sector → a single sector ETF benchmark.
  * This module owns a SMALL bounded ThreadPoolExecutor so the (up to
    max_peers) blocking yfinance calls cannot starve the shared 8-worker pool
    that the rest of !all already saturates.
  * compute_relative_strength bounds its own fetches with asyncio.wait_for.
  * The sub-industry ETF (e.g. SMH) *includes* the stock, so an ETF-fallback
    benchmark is biased toward "in-line" for mega-caps — it is labelled with
    the ETF symbol (e.g. "vs SMH") so the embed is honest, and the ETF-mode
    verdict is NOT fed to the narrator as a clean directional fact (only the
    curated-peer-mean mode is).
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine.utils.yahoo_limit import get_yahoo_semaphore  # C20

log = logging.getLogger(__name__)

_PEER_PATH = Path(__file__).parent.parent / "data" / "peer_groups.yaml"

# Bounded pool dedicated to peer fetches (keeps blocking yfinance calls off the
# shared default executor that the rest of !all uses).
_PEER_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="peer-rs")

# Loaded lazily; (groups_by_industry, ticker_index, sector_etf_fallback).
_peer_data: Optional[tuple] = None


def _load_peer_groups() -> tuple:
    """Load peer_groups.yaml once. Returns (groups, ticker_index, sector_fallback).

    groups: {industry: {"benchmark_etf": str, "members": [..]}}
    ticker_index: {TICKER: industry}
    sector_fallback: {sector: etf}
    """
    global _peer_data
    if _peer_data is not None:
        return _peer_data
    groups: dict = {}
    ticker_index: dict = {}
    sector_fallback: dict = {}
    try:
        import yaml
        with open(_PEER_PATH) as f:
            data = yaml.safe_load(f) or {}
        groups = data.get("groups", {}) or {}
        sector_fallback = data.get("sector_etf_fallback", {}) or {}
        for industry, spec in groups.items():
            for m in (spec.get("members") or []):
                # Defensive: a bare ticker like ON/NO/YES parses as a YAML bool.
                # They should be quoted in the YAML; skip any that slipped through
                # so one bad token can't nuke the whole peer map.
                if not isinstance(m, str):
                    log.warning("peer_comparison: non-string member %r in %s (quote it in YAML)", m, industry)
                    continue
                ticker_index[m.upper()] = industry
    except Exception as e:  # noqa: BLE001
        log.warning("peer_comparison: failed to load peer_groups.yaml: %s", e)
    _peer_data = (groups, ticker_index, sector_fallback)
    return _peer_data


def _fetch_info_sector(ticker: str) -> tuple:
    """Blocking yfinance .info sector/industry fetch. Returns (sector, industry)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("sector"), info.get("industry")
    except Exception as e:  # noqa: BLE001
        log.debug("peer_comparison: .info fetch failed for %s: %s", ticker, e)
        return None, None


async def resolve_peers(ticker: str) -> dict:
    """Resolve a ticker's peer set + benchmark ETF.

    Returns {"group": str|None, "peers": [TICKER...], "benchmark_etf": str|None,
             "source": "curated"|"dynamic_curated"|"dynamic_etf"|"none"}.
    `peers` always excludes the ticker itself.
    """
    tk = ticker.upper()
    groups, ticker_index, sector_fallback = _load_peer_groups()

    industry = ticker_index.get(tk)
    if industry:  # curated hit
        spec = groups.get(industry, {})
        peers = [m for m in (spec.get("members") or []) if isinstance(m, str) and m.upper() != tk]
        return {"group": industry, "peers": peers,
                "benchmark_etf": spec.get("benchmark_etf"), "source": "curated"}

    # dynamic fallback: DB cache → yfinance .info
    sector = ind = None
    try:
        from consensus_engine import db
        cached = await db.get_ticker_sector(tk)
        if cached:
            sector, ind = cached.get("sector"), cached.get("industry")
    except Exception as e:  # noqa: BLE001
        log.debug("peer_comparison: sector cache read failed for %s: %s", tk, e)

    if sector is None and ind is None:
        loop = asyncio.get_running_loop()
        async with get_yahoo_semaphore():  # C20
            sector, ind = await loop.run_in_executor(_PEER_EXECUTOR, _fetch_info_sector, tk)
        try:
            from consensus_engine import db
            await db.set_ticker_sector(tk, sector, ind)
        except Exception as e:  # noqa: BLE001
            log.debug("peer_comparison: sector cache write failed for %s: %s", tk, e)

    # dynamic industry matches a curated group → use those peers
    if ind and ind in groups:
        spec = groups[ind]
        peers = [m for m in (spec.get("members") or []) if isinstance(m, str) and m.upper() != tk]
        return {"group": ind, "peers": peers,
                "benchmark_etf": spec.get("benchmark_etf"), "source": "dynamic_curated"}

    # else broad sector → sector ETF benchmark, no curated peers
    if sector and sector in sector_fallback:
        return {"group": sector, "peers": [], "benchmark_etf": sector_fallback[sector],
                "source": "dynamic_etf"}

    return {"group": None, "peers": [], "benchmark_etf": None, "source": "none"}


def _pct_change(ticker: str, window_days: int) -> Optional[float]:
    """N-trading-day % change from yfinance daily closes. None on short/no data.

    Guards len(closes) < window_days+1 BEFORE indexing (a fresh listing or a
    halted/illiquid ticker can return sparse rows → IndexError otherwise).
    """
    try:
        from consensus_engine.utils import prices  # #57 Schwab primary, yfinance fallback
        # period covers comfortably more than window_days trading days.
        period = f"{max(window_days * 3, 10)}d"
        h = prices.fetch_history(ticker, period=period, interval="1d")
        if h is None or h.empty:
            return None
        closes = h["Close"].dropna()
        if len(closes) < window_days + 1:
            return None
        last = float(closes.iloc[-1])
        prior = float(closes.iloc[-(window_days + 1)])
        if prior <= 0:
            return None
        return round((last / prior - 1.0) * 100.0, 2)
    except Exception as e:  # noqa: BLE001
        log.debug("peer_comparison: pct_change failed for %s: %s", ticker, e)
        return None


async def _gather_pct(tickers: list[str], window_days: int) -> dict:
    """Fetch _pct_change for many tickers on the bounded pool. {ticker: pct|None}."""
    loop = asyncio.get_running_loop()

    async def _one(t):
        # C20: bound peer yfinance fetches with the rest of the engine's Yahoo
        # traffic (released the instant the fetch returns).
        async with get_yahoo_semaphore():
            return await loop.run_in_executor(_PEER_EXECUTOR, _pct_change, t, window_days)

    results = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
    out = {}
    for t, r in zip(tickers, results):
        out[t] = r if isinstance(r, (int, float)) else None
    return out


async def compute_relative_strength(
    ticker: str, window_days: Optional[int] = None, executor=None,
) -> Optional[dict]:
    """Stock's N-day move vs its peers' average. Returns a dict or None.

    Return dict:
      {stock_pct, benchmark_pct, delta, verdict, benchmark_label, mode,
       source, peers_used, window_days, narrator_ok}
    verdict ∈ {"outperforming","underperforming","in-line"}.
    mode ∈ {"peers","etf"}; narrator_ok True only for the clean curated-peer mean.
    """
    if not cfg.get("features.peer_comparison.enabled", False):
        return None
    if window_days is None:
        window_days = int(cfg.get("features.peer_comparison.window_days", 5))
    max_peers = int(cfg.get("features.peer_comparison.max_peers", 5))
    thr = float(cfg.get("features.peer_comparison.outperform_threshold_pct", 1.0))

    # C10: the old hard-coded 12s ceiling silently dropped the field under
    # throttle. Raise it (default 22s) so a slow-but-valid peer fetch survives.
    timeout_s = float(cfg.get("features.peer_comparison.timeout_s", 22))
    try:
        return await asyncio.wait_for(
            _compute(ticker.upper(), window_days, max_peers, thr), timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning("peer_comparison: timed out (>%.0fs) for %s", timeout_s, ticker)
        return None
    except Exception as e:  # noqa: BLE001
        log.debug("peer_comparison: compute failed for %s: %s", ticker, e)
        return None


async def _compute(tk: str, window_days: int, max_peers: int, thr: float) -> Optional[dict]:
    resolved = await resolve_peers(tk)
    peers = resolved["peers"][:max_peers]
    etf = resolved["benchmark_etf"]

    # One bounded batch: the stock, its capped peers, and the ETF (cheap; may be
    # needed as fallback). At most 1 + max_peers + 1 calls on a 4-worker pool.
    fetch_list = [tk] + peers + ([etf] if etf else [])
    pcts = await _gather_pct(fetch_list, window_days)

    stock_pct = pcts.get(tk)
    if stock_pct is None:
        return None  # can't compare without the stock's own move

    peer_vals = [pcts[p] for p in peers if pcts.get(p) is not None]
    if len(peer_vals) >= 2:
        benchmark_pct = round(sum(peer_vals) / len(peer_vals), 2)
        label = resolved["group"] or "peers"
        mode = "peers"
        narrator_ok = True
        peers_used = len(peer_vals)
    elif etf and pcts.get(etf) is not None:
        benchmark_pct = pcts[etf]
        label = etf  # honest: name the ETF, which includes the stock itself
        mode = "etf"
        narrator_ok = False  # contaminated benchmark — embed only
        peers_used = 0
    else:
        return None

    delta = round(stock_pct - benchmark_pct, 2)
    if delta > thr:
        verdict = "outperforming"
    elif delta < -thr:
        verdict = "underperforming"
    else:
        verdict = "in-line"

    return {
        "stock_pct": stock_pct,
        "benchmark_pct": benchmark_pct,
        "delta": delta,
        "verdict": verdict,
        "benchmark_label": label,
        "mode": mode,
        "source": resolved["source"],
        "peers_used": peers_used,
        "window_days": window_days,
        "narrator_ok": narrator_ok,
    }
