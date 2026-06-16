#!/usr/bin/env python3
"""Read-only I10 backtest: classify every STRONG_ALERT snapshot by hard-evidence status.

Per the plan (section 3 + section-9 Codex correction):
  (a) PROVABLY SAFE   — sources_json has news_catalyst>0 OR sec_filing>0 OR options_flow>0
  (b) TECHNICAL/ANALYST-ONLY — none of (a); demotion depends on the unstored
      technical_filter_count / analyst_lb → "not provable from stored data"
  (c) NO HARD EVIDENCE — would demote under I10 if flag were ON

NOTE: sources_json.technical is capped/aggregated points, NOT a filter count.
We do NOT use it as a proxy for technical_filter_count (Codex correction).
"""

import asyncio
import json
import sys

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")
from consensus_engine import config as cfg, db


async def main() -> None:
    cfg.load_config()
    await db.init_db()

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT id, ticker, decision, sources_json, recorded_at "
        "FROM decision_snapshots "
        "WHERE decision = 'STRONG_ALERT' "
        "ORDER BY recorded_at"
    )
    rows = [dict(r) for r in await cur.fetchall()]

    print(f"\n=== I10 hard-evidence backtest ===")
    print(f"Input rows: decision='STRONG_ALERT' from decision_snapshots")
    print(f"Fields used: news_catalyst, sec_filing, options_flow (from sources_json)")
    print(f"Fields NOT usable: technical_filter_count, analyst_lb (not stored in snapshot)")
    print(f"Row count: {len(rows)}\n")

    provably_safe = []      # (a)
    technical_only = []     # (b)
    no_hard_evidence = []   # (c)

    for r in rows:
        try:
            sj = json.loads(r["sources_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            sj = {}

        news_catalyst = int(sj.get("news_catalyst", 0) or 0)
        sec_filing    = int(sj.get("sec_filing", 0) or 0)
        options_flow  = int(sj.get("options_flow", 0) or 0)
        technical_pts = int(sj.get("technical", 0) or 0)   # logged but NOT used as proof

        # (a) Provably safe: at least one hard-evidence signal stored
        if news_catalyst > 0 or sec_filing > 0 or options_flow > 0:
            provably_safe.append({
                "id": r["id"], "ticker": r["ticker"],
                "news_catalyst": news_catalyst,
                "sec_filing": sec_filing,
                "options_flow": options_flow,
                "technical_pts_stored": technical_pts,
            })
        elif technical_pts > 0:
            # (b) Has technical points but we can't prove filter count from stored data
            technical_only.append({
                "id": r["id"], "ticker": r["ticker"],
                "news_catalyst": news_catalyst,
                "sec_filing": sec_filing,
                "options_flow": options_flow,
                "technical_pts_stored": technical_pts,
                "note": "not provable from stored data (technical_filter_count/analyst_lb unstored)",
            })
        else:
            # (c) No hard evidence of any kind in stored data
            no_hard_evidence.append({
                "id": r["id"], "ticker": r["ticker"],
                "news_catalyst": news_catalyst,
                "sec_filing": sec_filing,
                "options_flow": options_flow,
                "technical_pts_stored": technical_pts,
                "note": "would demote under I10",
            })

    # --- Results ---
    print(f"=== Classification results (n={len(rows)}) ===")
    print(f"  (a) PROVABLY SAFE (news/sec/options > 0):      {len(provably_safe)}")
    print(f"  (b) TECHNICAL/ANALYST-ONLY (not provable):     {len(technical_only)}")
    print(f"  (c) NO HARD EVIDENCE (would demote):           {len(no_hard_evidence)}")
    print()

    if technical_only:
        print("--- Category (b): TECHNICAL/ANALYST-ONLY rows ---")
        for row in technical_only:
            print(
                f"  id={row['id']} ticker={row['ticker']}"
                f"  news={row['news_catalyst']} sec={row['sec_filing']}"
                f"  options={row['options_flow']} tech_pts={row['technical_pts_stored']}"
                f"  | {row['note']}"
            )
        print()

    if no_hard_evidence:
        print("--- Category (c): NO HARD EVIDENCE rows ---")
        for row in no_hard_evidence:
            print(
                f"  id={row['id']} ticker={row['ticker']}"
                f"  news={row['news_catalyst']} sec={row['sec_filing']}"
                f"  options={row['options_flow']} tech_pts={row['technical_pts_stored']}"
                f"  | {row['note']}"
            )
        print()

    if not no_hard_evidence:
        print("Category (c) is EMPTY — no row would demote under I10 from stored data alone.")
        print()

    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
