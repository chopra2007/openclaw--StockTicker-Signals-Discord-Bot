"""Shared benchmark-relative grading spine (TODO #55 + #20).

One place for "how did this stock do MINUS how its benchmark did over the same
sessions". Three consumers import from here:

  * scripts/grade_analyst_catalysts.py  — #55 short-term (BHAR) + long-term checkpoints
  * scripts/wolf_timing_backtest.py     — #20 raw-Wolf vs confluence-gated entry
  * (scripts/grade_options_flow.py keeps its own excess_move — the shipped #57 grader
     is deliberately NOT edited; this module generalises the same formula.)

Benchmark resolution order: peer_groups.yaml `benchmark_etf` (sub-industry, e.g.
NVDA -> SMH) then sector_map.yaml `mappings` (broad SPDR, e.g. AAPL -> XLK) then
None. A None means "no benchmark" -> the caller SKIPS the row; it never guesses.

Scope rule (structural, not convention): BHAR is a SHORT-TERM statistic only. The
long-term checkpoint function raises if handed a BHAR-scale window, so a future
edit that wires daily-compounded BHAR into the multi-month path fails a test
instead of silently shipping.
"""

from __future__ import annotations

import logging
import os
from bisect import bisect_left

import yaml

log = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_PEER_GROUPS_PATH = os.path.join(_DATA_DIR, "peer_groups.yaml")
_SECTOR_MAP_PATH = os.path.join(_DATA_DIR, "sector_map.yaml")

# The short-term catalyst window: 30 calendar days ~= 21 trading sessions.
BHAR_WINDOW_DAYS = 21
# Weekly checkpoints inside that window (plus the terminal bar).
BHAR_CHECKPOINTS = (5, 10, 15, 20, 21)
# A long-term bet is graded at these sparse checkpoints — never daily.
LONG_TERM_CHECKPOINTS = (30, 60, 90)

_benchmark_cache: dict[str, str] | None = None


def _load_benchmarks() -> dict[str, str]:
    """{TICKER: benchmark ETF} — peer group wins, sector map fills the rest."""
    global _benchmark_cache
    if _benchmark_cache is not None:
        return _benchmark_cache

    table: dict[str, str] = {}
    with open(_SECTOR_MAP_PATH) as fh:
        sector_map = yaml.safe_load(fh) or {}
    for ticker, etf in (sector_map.get("mappings") or {}).items():
        if etf:
            table[str(ticker).upper()] = str(etf).upper()

    with open(_PEER_GROUPS_PATH) as fh:
        peer_groups = yaml.safe_load(fh) or {}
    for group in (peer_groups.get("groups") or {}).values():
        etf = group.get("benchmark_etf")
        if not etf:
            continue
        for member in group.get("members") or []:
            table[str(member).upper()] = str(etf).upper()  # peer group overrides sector

    _benchmark_cache = table
    return table


def resolve_benchmark(ticker: str) -> str | None:
    """The ETF this ticker should be graded against, or None -> caller skips the row.

    Returning None (rather than defaulting to SPY) is deliberate: grading a long-tail
    name against SPY would silently measure sector beta, not analyst skill.
    """
    if not ticker:
        return None
    return _load_benchmarks().get(ticker.strip().upper())


async def resolve_benchmark_dynamic(ticker: str) -> str | None:
    """resolve_benchmark() plus a dynamic tail for long-tail tickers (RKLB, HIMS...).

    Ladder: curated tables (peer_groups -> sector_map, via resolve_benchmark) ->
    peer_comparison.resolve_peers(), which already owns the rest: 30-day DB sector
    cache -> ONE yfinance .info lookup (bounded executor + Yahoo semaphore) ->
    curated group matched by industry (sub-industry ETF, e.g. SMH) -> sector-name
    ETF from peer_groups.yaml `sector_etf_fallback` (e.g. Industrials -> XLI).

    Still returns None rather than guessing SPY when even Yahoo has no sector for
    the ticker — the caller keeps skipping those rows. Async because a cache miss
    may fetch over the network; sync callers keep using resolve_benchmark().
    """
    static = resolve_benchmark(ticker)
    if static:
        return static
    if not ticker:
        return None
    try:
        from consensus_engine.analysis.peer_comparison import resolve_peers
        resolved = await resolve_peers(ticker.strip().upper())
    except Exception as e:  # noqa: BLE001 — a broken fallback must degrade to "skip", never crash a grading run
        log.warning("benchmark_grading: dynamic resolve failed for %s: %s", ticker, e)
        return None
    etf = resolved.get("benchmark_etf")
    return str(etf).upper() if etf else None


def close_n_trading_days_later(bars: dict[str, float], entry_date: str,
                               n: int) -> float | None:
    """The close n trading sessions after `entry_date` (bar 0 = that session).

    The ticker's own bar dates ARE the trading calendar, so weekends/holidays are
    skipped for free. Returns None when the window has not elapsed yet — the caller
    leaves that row ungraded and a later --backfill fills it in.
    """
    if not bars:
        return None
    days = sorted(bars)
    idx = bisect_left(days, entry_date)
    if idx >= len(days):
        return None
    target = idx + n
    if target >= len(days):
        return None
    return bars[days[target]]


def _leg_return(bars: dict[str, float], entry_date: str, n: int) -> float | None:
    """Simple close-to-close return from bar 0 to bar n, or None if unavailable."""
    start = close_n_trading_days_later(bars, entry_date, 0)
    end = close_n_trading_days_later(bars, entry_date, n)
    if not start or not end or start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def buy_and_hold_abnormal_return(stock_bars: dict[str, float],
                                 bench_bars: dict[str, float],
                                 entry_date: str,
                                 n_trading_days: int) -> float | None:
    """Stock's move minus its benchmark's move over the SAME trading window.

    Both legs run bar 0 -> bar n, so whatever the market did over exactly those
    sessions cancels out. This is the number that says whether the call had an edge;
    a raw % change does not. Returns None when either leg is missing.

    SHORT-TERM ONLY (<= BHAR_WINDOW_DAYS). Raises on a long-horizon window so the
    30-day scope is enforced in code.
    """
    if n_trading_days > BHAR_WINDOW_DAYS:
        raise ValueError(
            f"BHAR is a short-term statistic: n_trading_days={n_trading_days} exceeds "
            f"the {BHAR_WINDOW_DAYS}-session window. Long-horizon bets are graded with "
            f"checkpoint_excess_return()."
        )
    stock = _leg_return(stock_bars, entry_date, n_trading_days)
    bench = _leg_return(bench_bars, entry_date, n_trading_days)
    if stock is None or bench is None:
        return None
    return stock - bench


def weekly_checkpoints(stock_bars: dict[str, float], bench_bars: dict[str, float],
                       entry_date: str) -> dict[int, float | None]:
    """{5: bhar, 10: .., 15: .., 20: .., 21: ..} — the short-term BHAR path."""
    return {
        n: buy_and_hold_abnormal_return(stock_bars, bench_bars, entry_date, n)
        for n in BHAR_CHECKPOINTS
    }


def checkpoint_excess_return(stock_bars: dict[str, float], bench_bars: dict[str, float],
                             entry_date: str, n_trading_days: int) -> float | None:
    """Excess return at ONE sparse long-horizon checkpoint (30/60/90 sessions).

    Same arithmetic as BHAR but deliberately a SEPARATE function: it refuses a
    BHAR-scale window. A long-term thesis ("the moat widens") is checked a few
    times, not compounded daily — daily stats on a 90-day bet are noise.
    """
    if n_trading_days <= BHAR_WINDOW_DAYS:
        raise ValueError(
            f"checkpoint_excess_return is the LONG-horizon path: n_trading_days="
            f"{n_trading_days} is a BHAR-scale (<= {BHAR_WINDOW_DAYS}) window. Use "
            f"buy_and_hold_abnormal_return() for short-term catalysts."
        )
    stock = _leg_return(stock_bars, entry_date, n_trading_days)
    bench = _leg_return(bench_bars, entry_date, n_trading_days)
    if stock is None or bench is None:
        return None
    return stock - bench


def directional_win(bhar: float | None, direction: str) -> int | None:
    """WIN = the call beat its benchmark in the direction the analyst called.

    long  -> BHAR > 0 (stock outran its sector)
    short -> BHAR < 0 (stock lagged its sector)
    Returns None when the window has not elapsed (ungraded, not a loss).
    """
    if bhar is None:
        return None
    d = (direction or "").strip().lower()
    if d in ("long", "bullish", "bull"):
        return int(bhar > 0)
    if d in ("short", "bearish", "bear"):
        return int(bhar < 0)
    return None
