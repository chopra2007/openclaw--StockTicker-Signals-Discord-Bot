#!/usr/bin/env python3
"""F10 (#76 menu) — backtest-to-live decay tracker.

Warns when a signal that used to work starts failing live. For each signal_key
(decision tier, catalyst type, and options-flow side) it compares the trailing
`lookback_days` LIVE hit rate against a frozen baseline hit rate, using a Wilson
lower bound so a thin live sample can't trip a false alarm. When the live lower
bound falls below the baseline by more than `tolerance`, it posts ONE #errors
note via ops_alert (transition-only + flap guard, so it can't spam).

The tracker ONLY reports — it never un-flips a feature flag. Un-flipping is the
auto-flip engine's job (#67); decay detection is a heads-up, not an action.

Usage:
    # 1. Freeze baselines from all stored resolved outcomes (one-time / periodic)
    python3 scripts/signal_decay_check.py --freeze-baselines --db DB [--out BASELINES_DB]

    # 2. Compare live vs baseline and print the table (no alert)
    python3 scripts/signal_decay_check.py --dry-run --db DB [--baselines BASELINES_DB]

    # 3. Run for real (posts #errors notes for DECAY signals; needs the flag ON)
    python3 scripts/signal_decay_check.py --db DB [--baselines BASELINES_DB]

    # 4. Test the sink + flap guard
    python3 scripts/signal_decay_check.py --force-alert 'tier=ALERT' --db DB

Flag: features.decay_tracker.enabled (default false). When OFF the real run
computes the table but posts nothing. --dry-run always prints; --force-alert
always posts (it exists to test the sink).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time

_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

from consensus_engine import config as cfg
from consensus_engine.eval import loaders
from consensus_engine.eval.metrics import wilson_lower_bound

_BASELINES_DDL = """
CREATE TABLE IF NOT EXISTS signal_baselines (
    signal_key   TEXT PRIMARY KEY,
    baseline_rate REAL NOT NULL,
    baseline_n   INTEGER NOT NULL,
    horizon      TEXT NOT NULL,
    source       TEXT NOT NULL,
    frozen_at    REAL NOT NULL
);
"""

# A baseline is only trustworthy with enough rows behind it.
_MIN_FREEZE_N = 30


def collect(conn: sqlite3.Connection, *, horizon: str = "24h",
            since_ts: float | None = None) -> dict[str, list]:
    """Return {signal_key: [hits, n, horizon]} over decision_snapshots +
    options_flow_outcomes. `since_ts` restricts to recent rows (live window)."""
    acc: dict[str, list] = {}

    def add(key: str, hit: int, hz: str) -> None:
        a = acc.setdefault(key, [0, 0, hz])
        a[0] += int(hit)
        a[1] += 1

    for sn in loaders.load_snapshots(conn):
        if since_ts and sn.recorded_at < since_ts:
            continue
        h = sn.hit(horizon)
        if h is None:
            continue
        add(f"tier={sn.decision}", h, horizon)
        if sn.catalyst_type:
            add(f"catalyst={sn.catalyst_type}", h, horizon)

    try:
        q = ("SELECT side, win_1d, detected_at FROM options_flow_outcomes "
             "WHERE win_1d IS NOT NULL")
        for side, win, det in conn.execute(q):
            if since_ts and det and det < since_ts:
                continue
            add(f"flow:side={side}", win, "win_1d")
    except sqlite3.OperationalError:
        pass  # table absent in a stripped DB

    return acc


def freeze_baselines(src_db: str, out_db: str, *, horizon: str, source_label: str) -> list[dict]:
    conn = loaders.connect_ro(src_db)
    try:
        acc = collect(conn, horizon=horizon)
    finally:
        conn.close()

    out = sqlite3.connect(out_db)
    try:
        out.executescript(_BASELINES_DDL)
        now = time.time()
        written = []
        for key, (hits, n, hz) in sorted(acc.items()):
            if n < _MIN_FREEZE_N:
                continue
            rate = hits / n
            out.execute(
                "INSERT OR REPLACE INTO signal_baselines"
                "(signal_key, baseline_rate, baseline_n, horizon, source, frozen_at) "
                "VALUES (?,?,?,?,?,?)",
                (key, rate, n, hz, source_label, now))
            written.append({"signal_key": key, "rate": rate, "n": n, "horizon": hz})
        out.commit()
    finally:
        out.close()
    return written


def _load_baselines(baselines_db: str) -> dict[str, dict]:
    conn = sqlite3.connect(baselines_db)
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT signal_key, baseline_rate, baseline_n, horizon FROM signal_baselines"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()
    return {r["signal_key"]: dict(r) for r in rows}


def compare(src_db: str, baselines_db: str, *, lookback_days: int, tolerance: float,
            min_live_n: int) -> list[dict]:
    """For each baseline signal_key, compute the trailing live rate + Wilson LB
    and a verdict: DECAY / OK / INSUFFICIENT."""
    baselines = _load_baselines(baselines_db)
    if not baselines:
        return []
    since = time.time() - lookback_days * 86400

    conn = loaders.connect_ro(src_db)
    try:
        # collect per horizon actually present in the baselines (24h for snaps, win_1d for flow)
        horizons = {b["horizon"] for b in baselines.values()}
        live: dict[str, list] = {}
        for hz in horizons:
            live.update(collect(conn, horizon=hz, since_ts=since))
    finally:
        conn.close()

    results = []
    for key, b in sorted(baselines.items()):
        lh = live.get(key)
        live_hits = lh[0] if lh else 0
        live_n = lh[1] if lh else 0
        if live_n < min_live_n:
            results.append({
                "signal_key": key, "baseline_rate": b["baseline_rate"],
                "baseline_n": b["baseline_n"], "live_hits": live_hits, "live_n": live_n,
                "live_wlb": None, "verdict": "INSUFFICIENT",
            })
            continue
        wlb = wilson_lower_bound(live_hits, live_n)
        decayed = (b["baseline_rate"] - wlb) > tolerance
        results.append({
            "signal_key": key, "baseline_rate": b["baseline_rate"],
            "baseline_n": b["baseline_n"], "live_hits": live_hits, "live_n": live_n,
            "live_wlb": wlb, "verdict": "DECAY" if decayed else "OK",
        })
    return results


def format_table(results: list[dict]) -> str:
    if not results:
        return ("No baselines found — run --freeze-baselines first, or the baselines DB "
                "has no signal_baselines rows.")
    L = ["signal_key                 | baseline (n)   | live        | Wilson-LB | verdict",
         "-" * 78]
    for r in results:
        # raw ratio always (never a % on a thin sample), % only when live_n >= 10
        live_str = f"{r['live_hits']}/{r['live_n']}"
        if r["live_n"] >= 10:
            live_str += f" ({100*r['live_hits']/r['live_n']:.0f}%)"
        wlb = "n/a" if r["live_wlb"] is None else f"{r['live_wlb']:.3f}"
        L.append(f"{r['signal_key']:<26} | {r['baseline_rate']:.3f} ({r['baseline_n']:>4}) | "
                 f"{live_str:<11} | {wlb:>9} | {r['verdict']}")
    return "\n".join(L)


async def _alert(results: list[dict], *, tolerance: float) -> int:
    """Post a transition-only #errors note per DECAY signal; clear on recovery.
    Returns the number of messages actually sent."""
    from consensus_engine import db
    from consensus_engine.alerts.ops_alert import report_ops_state

    await db.init_db()
    sent = 0
    try:
        for r in results:
            if r["verdict"] == "INSUFFICIENT":
                continue
            key = f"signal_decay:{r['signal_key']}"
            down = r["verdict"] == "DECAY"
            title = f"📉 Signal decay: {r['signal_key']}"
            detail = (
                f"Live hit rate has decayed below its frozen baseline.\n"
                f"baseline {r['baseline_rate']:.1%} (n={r['baseline_n']}) → "
                f"live {r['live_hits']}/{r['live_n']} "
                f"(Wilson lower bound {r['live_wlb']:.3f}); "
                f"drop exceeds the {tolerance:.0%} tolerance."
            ) if down else "Live hit rate has recovered to its baseline."
            if await report_ops_state(key, down=down, title=title, detail=detail,
                                      failure_class="signal_decay"):
                sent += 1
    finally:
        await db.close_db()
    return sent


async def _force_alert(signal_key: str) -> None:
    from consensus_engine import db
    from consensus_engine.alerts.ops_alert import report_ops_state
    await db.init_db()
    try:
        await report_ops_state(
            f"signal_decay:{signal_key}", down=True,
            title=f"📉 Signal decay: {signal_key}",
            detail="Forced test alert (scripts/signal_decay_check.py --force-alert).",
            failure_class="signal_decay")
    finally:
        await db.close_db()


def main() -> int:
    ap = argparse.ArgumentParser(description="F10 backtest-to-live decay tracker")
    ap.add_argument("--db", default=loaders.DEFAULT_DB, help="source DB (snapshots + flow outcomes)")
    ap.add_argument("--baselines", default=None, help="DB holding signal_baselines (default: --db)")
    ap.add_argument("--out", default=None, help="freeze target DB (default: --db)")
    ap.add_argument("--freeze-baselines", action="store_true", help="freeze baselines and exit")
    ap.add_argument("--source-label", default="stored-history", help="baseline source label")
    ap.add_argument("--dry-run", action="store_true", help="print the table, never alert")
    ap.add_argument("--force-alert", default=None, metavar="SIGNAL_KEY",
                    help="post one forced #errors alert for SIGNAL_KEY (tests the sink/flap guard)")
    ap.add_argument("--horizon", default="24h", help="snapshot outcome horizon for freeze")
    args = ap.parse_args()

    lookback = int(cfg.get("features.decay_tracker.lookback_days", 60))
    tolerance = float(cfg.get("features.decay_tracker.tolerance", 0.10))
    min_live_n = int(cfg.get("features.decay_tracker.min_live_n", 30))

    if args.freeze_baselines:
        out_db = args.out or args.db
        written = freeze_baselines(args.db, out_db, horizon=args.horizon,
                                   source_label=args.source_label)
        print(f"Froze {len(written)} baseline(s) (>= {_MIN_FREEZE_N} rows) into {out_db}:")
        for w in written:
            print(f"  {w['signal_key']:<26} rate={w['rate']:.3f} n={w['n']} horizon={w['horizon']}")
        return 0

    if args.force_alert:
        asyncio.run(_force_alert(args.force_alert))
        print(f"Forced decay alert posted for {args.force_alert}")
        return 0

    baselines_db = args.baselines or args.db
    results = compare(args.db, baselines_db, lookback_days=lookback,
                      tolerance=tolerance, min_live_n=min_live_n)
    print(format_table(results))
    decayed = [r for r in results if r["verdict"] == "DECAY"]
    print(f"\n{len(decayed)} signal(s) decayed, "
          f"{sum(1 for r in results if r['verdict']=='OK')} OK, "
          f"{sum(1 for r in results if r['verdict']=='INSUFFICIENT')} insufficient.")

    if args.dry_run:
        return 0
    if not cfg.get("features.decay_tracker.enabled", False):
        print("features.decay_tracker.enabled is OFF — not alerting.")
        return 0
    sent = asyncio.run(_alert(results, tolerance=tolerance))
    print(f"Posted {sent} #errors transition note(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
