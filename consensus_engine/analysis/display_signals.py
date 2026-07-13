"""#62: log the five rich signals that the bot computes but never remembers.

Max-pain, analyst momentum, EPS revisions, peer relative-strength and chart
patterns are all computed today — but ONLY in the `!all` display path, to be
printed once and thrown away. They never touch the scoring path, so they are
recorded nowhere, so nobody can ever ask "would these have predicted anything?"
The honesty eval (#61) hit exactly this wall: of 3,134 stored decisions, only
`final_score` had any variance to learn from.

This module recomputes the five per decision and writes them into
`decision_snapshots.feature_vector_json`. It changes no alert and no score. Once
~90 resolved 24-hour outcomes accrue, the auto-flip engine tests each signal for
real predictive lift and, if one earns it, flips `scoring.fold_display_signals`
on by itself.

Latency: these fetches are slow (peer RS alone budgets 22s). So this never runs
on the alert path. `main.py` writes the snapshot row first and schedules this
afterwards, then merges the result into the already-written row. The alert goes
out at exactly the speed it did before.

Every signal is independently timed out and failure-safe: a hung yfinance call
costs that one key, not the other four.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# Per-signal budgets. Generous — this is off the hot path and a missing signal is
# a permanently missing training row, so waiting is cheaper than losing the data.
_MAX_PAIN_TIMEOUT_S = 20.0
_SNAPSHOT_SUB_TIMEOUT_S = 8.0
_PEER_TIMEOUT_S = 25.0
_CANDLES_TIMEOUT_S = 20.0

# Whole-collection ceiling, so a pathological run can't leak a task forever.
_TOTAL_TIMEOUT_S = 45.0


def _num(v: Any) -> Optional[float]:
    """Floats only; drop None/NaN/inf so a poisoned value never enters the vector."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


async def _max_pain(ticker: str) -> dict:
    """Strike where the most options expire worthless, plus the put/call OI balance.

    `compute_max_pain` returns {"spot", "weekly": {strike, expiry, total_oi}|None,
    "monthly": {...}|None, "pc_oi_ratio", "call_oi_sum", "put_oi_sum", ...}. When the
    nearest expiry IS the monthly, `weekly` is None and `monthly` carries it — so
    read weekly first and fall through, never assume both.
    """
    from consensus_engine.scanners import options

    mp = await asyncio.wait_for(options.compute_max_pain(ticker), timeout=_MAX_PAIN_TIMEOUT_S)
    if not mp:
        return {}
    spot = _num(mp.get("spot"))
    leg = mp.get("weekly") or mp.get("monthly")
    out: dict = {}

    strike = _num((leg or {}).get("strike"))
    if strike is not None:
        out["max_pain_strike"] = strike
        # The scale-free version: how far spot sits above/below max pain. A raw
        # strike is meaningless across names; the gap is what a model can learn.
        if spot and spot > 0:
            out["max_pain_spot_gap_pct"] = (spot - strike) / spot * 100.0
        if (leg or {}).get("expiry"):
            out["max_pain_expiry"] = str(leg["expiry"])

    pc = _num(mp.get("pc_oi_ratio"))
    if pc is not None:
        out["max_pain_pc_oi_ratio"] = pc
    return out


async def _analyst_momentum(ticker: str) -> dict:
    """Shift in the analyst rating mix over the last two months.

    Calls snapshot.py's private fetcher directly and on purpose: the public
    `fetch_ticker_snapshot` gates this behind a DISPLAY flag, and turning that on
    would change what `!all` prints. Logging must not move the UI.
    """
    from consensus_engine.scanners import snapshot

    loop = asyncio.get_running_loop()
    mom = await asyncio.wait_for(
        loop.run_in_executor(None, snapshot._fetch_analyst_momentum, ticker),
        timeout=_SNAPSHOT_SUB_TIMEOUT_S,
    )
    if not mom:
        return {}
    out = {}
    shift = _num(mom.get("shift"))
    if shift is not None:
        out["analyst_momentum_shift"] = shift
    now = _num(mom.get("now"))
    if now is not None:
        out["analyst_momentum_now"] = now
    return out


async def _eps_revisions(ticker: str) -> dict:
    """How many analysts raised vs cut this quarter's EPS estimate in the last 30 days."""
    from consensus_engine.scanners import snapshot

    loop = asyncio.get_running_loop()
    rev = await asyncio.wait_for(
        loop.run_in_executor(None, snapshot._fetch_eps_revisions, ticker),
        timeout=_SNAPSHOT_SUB_TIMEOUT_S,
    )
    if not rev:
        return {}
    up, down = _num(rev.get("up")), _num(rev.get("down"))
    if up is None and down is None:
        return {}
    up, down = up or 0.0, down or 0.0
    out = {"eps_revision_up": up, "eps_revision_down": down, "eps_revision_net": up - down}
    total = up + down
    if total > 0:
        out["eps_revision_breadth"] = (up - down) / total   # in [-1, 1]
    return out


async def _peer_relative_strength(ticker: str) -> dict:
    """How much the stock outran (or lagged) its peers / sector ETF."""
    from consensus_engine.analysis import peer_comparison

    rs = await asyncio.wait_for(
        peer_comparison.compute_relative_strength(ticker), timeout=_PEER_TIMEOUT_S,
    )
    if not rs:
        return {}
    out = {}
    delta = _num(rs.get("delta"))
    if delta is not None:
        out["peer_rs_delta"] = delta
    if rs.get("verdict"):
        out["peer_rs_verdict"] = str(rs["verdict"])
    if rs.get("mode"):
        out["peer_rs_mode"] = str(rs["mode"])
    return out


async def _chart_pattern(ticker: str) -> dict:
    """Breakout / bull-flag / double-bottom on the daily chart, if any."""
    from consensus_engine.analysis import patterns

    candles = await asyncio.wait_for(
        patterns.fetch_daily_candles(ticker, range_str="3mo"), timeout=_CANDLES_TIMEOUT_S,
    )
    if not candles:
        return {}
    hit = patterns.detect_all(candles)
    if not hit:
        # A clean chart is DATA, not a missing value: "no pattern" must be
        # distinguishable from "the fetch died", or the model learns from a
        # sample biased toward stocks that happened to have patterns.
        return {"chart_pattern": "none", "chart_pattern_confidence": 0.0}
    out: dict = {"chart_pattern": str(hit.get("pattern") or "none")}
    conf = _num(hit.get("confidence"))
    if conf is not None:
        out["chart_pattern_confidence"] = conf
    level = _num(hit.get("key_level"))
    if level is not None:
        out["chart_pattern_key_level"] = level
    return out


_COLLECTORS = (
    ("max_pain", _max_pain),
    ("analyst_momentum", _analyst_momentum),
    ("eps_revisions", _eps_revisions),
    ("peer_rs", _peer_relative_strength),
    ("chart_pattern", _chart_pattern),
)


async def collect_display_signals(ticker: str) -> dict:
    """Compute all five in parallel. Returns whatever succeeded, plus a coverage note.

    Never raises. A signal that times out or errors is simply absent from the
    result, and `_missing` names it, so a later reader can tell "this signal did
    not fire" apart from "this signal was never collected".
    """
    async def _one(name: str, fn) -> tuple[str, dict | None]:
        try:
            return name, await fn(ticker)
        except asyncio.TimeoutError:
            log.debug("display_signals: %s timed out for %s", name, ticker)
        except Exception as e:                       # noqa: BLE001 — logging must not raise
            log.debug("display_signals: %s failed for %s: %s", name, ticker, e)
        return name, None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_one(n, f) for n, f in _COLLECTORS]),
            timeout=_TOTAL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.warning("display_signals: whole collection timed out for %s", ticker)
        return {}

    out: dict = {}
    missing: list[str] = []
    for name, value in results:
        if value:
            out.update(value)
        else:
            missing.append(name)
    if missing:
        out["_missing"] = missing
    return out


# ---------------------------------------------------------------------------
# The scoring CONSUMER — built, tested, and OFF.
# ---------------------------------------------------------------------------
# `scoring.fold_display_signals.enabled` is the flag the auto-flip registry points
# at. It exists so that the day the data proves one of these signals predicts
# something, the engine has somewhere to put it. Until then this returns 0 and is
# never called with the flag on.
#
# Deliberately crude: each signal contributes a small, bounded, monotonic nudge in
# the direction the signal points, and the total is clamped. Nothing here is fitted
# to data — fitting is what the readiness check is for. A signal that has not
# earned its place contributes nothing because the flag is off, not because its
# coefficient is small.

_BULLISH_PATTERNS = frozenset({"breakout_above_n_day_high", "bull_flag", "double_bottom"})


def display_signal_adjustment(signals: dict | None) -> int:
    """Bounded score adjustment from the 5 logged display signals. 0 when OFF.

    Returns points to ADD to the score, clamped to +/- `scoring.fold_display_signals
    .max_points`. Absent signals contribute nothing, so a partial collection cannot
    push the score around by accident.
    """
    if not signals or not cfg.get("scoring.fold_display_signals.enabled", False):
        return 0

    points = 0.0

    # Analyst rating mix improving -> mild positive.
    shift = _num(signals.get("analyst_momentum_shift"))
    if shift:
        points += max(-2.0, min(2.0, shift * 4.0))

    # More analysts raising than cutting EPS -> positive, scaled by breadth [-1, 1].
    breadth = _num(signals.get("eps_revision_breadth"))
    if breadth is not None:
        points += 2.0 * breadth

    # Outrunning its peers -> positive, 1 point per 5% of outperformance, capped.
    delta = _num(signals.get("peer_rs_delta"))
    if delta is not None:
        points += max(-2.0, min(2.0, delta / 5.0))

    # A confirmed bullish chart pattern -> up to 2 points, scaled by confidence.
    pattern = signals.get("chart_pattern")
    conf = _num(signals.get("chart_pattern_confidence")) or 0.0
    if pattern in _BULLISH_PATTERNS:
        points += 2.0 * conf

    # Spot far ABOVE max pain means dealers are positioned to pull it back down.
    gap = _num(signals.get("max_pain_spot_gap_pct"))
    if gap is not None:
        points -= max(-2.0, min(2.0, gap / 5.0))

    cap = float(cfg.get("scoring.fold_display_signals.max_points", 8))
    return int(round(max(-cap, min(cap, points))))


# The exact top-level feature names the auto-flip readiness check reads, and the
# rich key each is distilled from. `auto_flip_check.py::check_display_signals_lift`
# does `obj[term]` on the TOP level of feature_vector_json and skips anything that
# is not a number — so a nested dict, or a string pattern label, would make the
# switch permanently un-testable while looking fine. One scale-free number each.
_CANONICAL = {
    "max_pain": "max_pain_spot_gap_pct",       # signed % of spot above/below max pain
    "analyst_momentum": "analyst_momentum_shift",
    "eps_revision": "eps_revision_breadth",    # (up - down) / (up + down), in [-1, 1]
    "peer_rs": "peer_rs_delta",                # signed % outperformance vs peers/ETF
}


def canonical_features(signals: dict) -> dict:
    """Flatten the five signals to one signed number each, named as the auto-flip
    readiness check expects. Absent signals are simply omitted."""
    out: dict = {}
    for name, source_key in _CANONICAL.items():
        v = _num(signals.get(source_key))
        if v is not None:
            out[name] = v

    # A pattern label is not a number. Encode it as a SIGNED confidence so the
    # checker can correlate it: bullish +conf, bearish -conf, no pattern 0.0.
    pattern = signals.get("chart_pattern")
    if pattern is not None:
        conf = _num(signals.get("chart_pattern_confidence")) or 0.0
        if pattern in _BULLISH_PATTERNS:
            out["chart_pattern"] = conf
        elif pattern == "none":
            out["chart_pattern"] = 0.0
        else:
            out["chart_pattern"] = -conf   # any bearish pattern added later
    return out


async def log_display_signals(snapshot_id: int, ticker: str) -> dict:
    """Collect the five and merge them into an ALREADY-WRITTEN snapshot row.

    Writes BOTH: the rich `display_signals` sub-dict (everything, for later
    analysis) and five flat numeric top-level keys (what the auto-flip readiness
    check actually reads). Runs off the alert path — see the module docstring.
    """
    if not cfg.get("features.forward_log_display_signals.enabled", True):
        return {}
    from consensus_engine import db

    signals = await collect_display_signals(ticker)
    if not signals:
        return {}
    payload: dict = {"display_signals": signals}
    payload.update(canonical_features(signals))
    await db.merge_snapshot_feature_vector(snapshot_id, payload)
    log.info("display_signals: logged %d fields (%d canonical) for $%s (snapshot %d)",
             len([k for k in signals if k != "_missing"]),
             len(payload) - 1, ticker, snapshot_id)
    return signals
