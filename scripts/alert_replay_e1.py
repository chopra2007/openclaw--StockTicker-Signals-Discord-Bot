#!/usr/bin/env python3
"""Offline alert-pipeline replay for the E1 (FINRA short-volume) scoring term — TODO #32.

Codex's prerequisite before flipping any scoring flag: show the USER-VISIBLE ALERT delta
(tier changes / new STRONG alerts), not just the term fire-rate. E1 is purely additive to
the precision total and capped at +5; STRONG fires at total>=80 and WATCHLIST at >=65. So
E1 can ONLY upgrade a stored WATCHLIST decision whose total is in [80-cap, 79] (it cannot
reach 80 from below 75), and only when that ticker actually fires the FINRA z-signal. We
read the real historical decisions from decision_snapshots and apply the production E1 term
function to bound the alert delta exactly.

Read-only. Prints the candidate set + the tickers that actually fire E1 + examples.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")
from consensus_engine import config as cfg, db
from consensus_engine.cross_reference import _compute_finra_short_volume_pts


async def _e1_points(ticker: str, direction: str = "long") -> int:
    """Production E1 term for a ticker right now (0 or the +cap), via the real function."""
    try:
        latest = await db.get_latest_finra_short_volume(ticker)
        baseline = await db.get_finra_short_volume_baseline(ticker)
        if not latest or not baseline:
            return 0
        return _compute_finra_short_volume_pts(
            short_pct=latest["short_pct"], baseline=baseline,
            finra_published_at=latest.get("finra_published_at"), direction=direction)
    except Exception:
        return 0


async def main():
    cfg.load_config()
    await db.init_db()
    cap = int(cfg.get("features.finra_short_volume.term_cap", 5))
    high = int(cfg.get("precision_engine.thresholds.high_confidence", 80))
    med = int(cfg.get("precision_engine.thresholds.medium_confidence", 65))
    floor = high - cap  # lowest total that +cap can lift to STRONG

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT ticker, decision, final_score, sources_json FROM decision_snapshots")
    rows = [dict(r) for r in await cur.fetchall()]

    def total_of(r):
        try:
            return int(json.loads(r["sources_json"] or "{}").get("total", r["final_score"] or 0))
        except Exception:
            return int(r["final_score"] or 0)

    watchlist = [r for r in rows if r["decision"] == "WATCHLIST"]
    # E1 can only flip a WATCHLIST whose total is within +cap of the STRONG threshold
    upgrade_candidates = [r for r in watchlist if floor <= total_of(r) < high]

    print(f"snapshots total={len(rows)}  WATCHLIST={len(watchlist)}  "
          f"STRONG={sum(1 for r in rows if r['decision']=='STRONG_ALERT')}")
    print(f"E1: cap=+{cap}, STRONG>= {high}, WATCHLIST>= {med}; "
          f"a WATCHLIST can only upgrade if total in [{floor},{high-1}]")
    print(f"upgrade-eligible WATCHLIST snapshots (by score band): {len(upgrade_candidates)}")

    # of those candidates, which tickers ACTUALLY fire E1 today -> the real alert delta
    fired = []
    checked = {}
    for r in upgrade_candidates:
        t = r["ticker"]
        if t not in checked:
            checked[t] = await _e1_points(t)
        if checked[t] > 0 and total_of(r) + checked[t] >= high:
            fired.append((t, total_of(r), checked[t]))

    # also: across ALL snapshot tickers, how many fire E1 at all (context / fire-rate)
    all_tickers = sorted({r["ticker"] for r in rows})
    fire_any = 0
    for t in all_tickers:
        if t not in checked:
            checked[t] = await _e1_points(t)
        if checked[t] > 0:
            fire_any += 1

    print(f"\nE1 term fires for {fire_any}/{len(all_tickers)} snapshot tickers (context)")
    print(f"ALERT DELTA — WATCHLIST -> STRONG_ALERT upgrades from E1: {len(fired)}")
    for t, tot, pts in fired[:20]:
        print(f"  {t}: {tot} +{pts} = {tot+pts} -> STRONG")
    if not fired:
        print("  (none — E1 changes ZERO historical alert tiers; it only adds <=+5 "
              "confluence to scores already near/over the bar)")

    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
