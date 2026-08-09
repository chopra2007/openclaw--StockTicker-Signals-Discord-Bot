"""options-flow-buyresell-sweeps: does the buy/sell-side tag call direction
BETTER than the old call/put-only guess, or worse?

`side_labels_live` shipped 2026-08-09 without the grading step normally required
first (memory `feedback_thin_sample_rates`, repo Regression Gate) — this script
is that check, deferred. Reuses grade_options_flow.py's price data and helpers
(same options_flow_outcomes table, same market-adjusted-return methodology,
same "cluster to 1 event, drop thin samples" rules) — run
`grade_options_flow.py --backfill` first so outcomes exist to grade against.

The sharp question: on events where the two methods DISAGREE (old call/put-only
says one direction, new side-aware says the other — the only cases where the
side tag actually changes anything), which one was more often right? Exactly
one of them is correct per disagreement event, so this is a coin-flip test
against 50%, not a two-proportion comparison.

    python3 scripts/grade_options_flow_side.py --report
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grade_options_flow import MIN_N, excess_move  # noqa: E402
from consensus_engine import db  # noqa: E402


def _new_bullish(side: str, flow_side: str) -> bool:
    """Same formula as format_flow_alert: BUY call / SELL put = bullish."""
    return (side.upper() == "CALL") == (flow_side == "BUY")


def _cluster_by_flow_side(rows: list[dict]) -> list[dict]:
    """One row per (ticker, market_date, flow_side), keeping the highest
    vol/OI contract — same rationale as grade_options_flow.cluster_events,
    just keyed on the buy/sell tag instead of call/put."""
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["ticker"], r["market_date"], r["flow_side"])
        if k not in best or (r.get("vol_oi_ratio") or 0) > (best[k].get("vol_oi_ratio") or 0):
            best[k] = r
    return list(best.values())


async def report() -> str:
    await db.init_db()
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT o.*, f.vol_oi_ratio, f.flow_side
               FROM options_flow_outcomes o JOIN options_flow f ON f.id = o.flow_id
               WHERE f.flow_side IN ('BUY', 'SELL')"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close_db()

    if not rows:
        return ("No graded events with a side tag yet. Either `side_collect` hasn't "
                "been live long enough, or run `grade_options_flow.py --backfill` first.")

    for r in rows:
        r["adj_5d"] = excess_move(r, 5)
    rows = [r for r in rows if r["adj_5d"] is not None and r["adj_5d"] != 0]

    clustered = _cluster_by_flow_side(rows)
    disagree = [r for r in clustered
                if _new_bullish(r["side"], r["flow_side"]) != (r["side"].upper() == "CALL")]

    lines = [
        "# Options-flow side-tag grading (options-flow-buyresell-sweeps)",
        "",
        f"{len(clustered)} clustered BUY/SELL events (1 per ticker-day-side) with a "
        f"measurable 5-day outcome. Of those, **{len(disagree)}** are cases where the "
        f"side tag actually changes the call vs. the old call/put-only guess — those "
        f"are the only ones that matter for this decision.",
        "",
    ]

    if len(disagree) < MIN_N:
        lines.append(
            f"**Too thin to call ({len(disagree)} disagreement events, need {MIN_N}+).** "
            f"Keep `side_labels_live` on and re-run this later, or fall back to "
            f"call/put-only until there's enough data."
        )
        return "\n".join(lines)

    new_wins = sum(1 for r in disagree if _new_bullish(r["side"], r["flow_side"]) == (r["adj_5d"] > 0))
    n = len(disagree)
    win_rate = new_wins / n
    z = (win_rate - 0.5) / (0.25 / n) ** 0.5

    verdict = (
        "**side tag is doing real work — keep it live**" if z >= 1.96 else
        "**side tag is making things WORSE — consider reverting to call/put-only**" if z <= -1.96 else
        "**no significant difference yet (could be luck either way)**"
    )
    lines += [
        f"On those {n} disagreement events, the side-aware call was right "
        f"**{100 * win_rate:.1f}%** of the time (vs. 50% if the tag knew nothing; "
        f"z={z:+.2f}).",
        "",
        verdict,
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Grade the options-flow side tag (options-flow-buyresell-sweeps).")
    p.add_argument("--report", action="store_true", help="print the verdict")
    args = p.parse_args()
    if args.report:
        print(asyncio.run(report()))
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
