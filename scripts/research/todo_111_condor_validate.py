"""TODO #111 iron condor — check every downloaded file before it is trusted."""
from __future__ import annotations
import json, sys
from collections import Counter
from datetime import time as dtime
from zoneinfo import ZoneInfo

import databento as db

RD = "/home/openclaw/.openclaw/research-data/todo-111-condor"
NY = ZoneInfo("America/New_York")

period = sys.argv[1]
trades = json.load(open(f"{RD}/{period}_trades.json"))
problems, checked = [], 0
minute_counts, coverage = [], []
for t in trades:
    if "legs_file" not in t:
        continue
    checked += 1
    store = db.DBNStore.from_file(t["legs_file"])
    meta = store.metadata
    if meta.dataset != "OPRA.PILLAR" or meta.schema.value != "cbbo-1m":
        problems.append((t["entry_day"], f"wrong dataset/schema {meta.dataset}/{meta.schema}"))
        continue
    df = store.to_df()
    want = set(t["legs"]["symbols"].values())
    got = set(df["symbol"].unique())
    if got != want:
        problems.append((t["entry_day"], f"contracts differ: missing {sorted(want - got)}"))
    if df.reset_index().duplicated(subset=["ts_recv", "symbol"]).any():
        problems.append((t["entry_day"], "duplicate timestamp for a contract"))
    if (df["ask_px_00"] < 0).any() or (df["bid_px_00"] < 0).any():
        problems.append((t["entry_day"], "negative bid or ask"))
    per = Counter(df["symbol"])
    minute_counts.append(min(per.values()) if per else 0)
    local = df.index.tz_convert(NY)
    session = df[(local.time >= dtime(9, 30)) & (local.time <= dtime(16, 0))]
    if session.empty:
        problems.append((t["entry_day"], "no regular-session minutes at all"))
        continue
    per_stamp = session.groupby(level=0)["symbol"].nunique()
    coverage.append((per_stamp == 4).sum() / len(per_stamp))

out = {"period": period, "files_checked": checked,
       "problem_count": len(problems), "problems": problems[:25],
       "min_minutes_per_leg": {"min": min(minute_counts), "median": sorted(minute_counts)[len(minute_counts) // 2],
                               "max": max(minute_counts)} if minute_counts else None,
       "all_four_legs_quoted_share": {"min": min(coverage), "mean": sum(coverage) / len(coverage),
                                      "max": max(coverage)} if coverage else None}
json.dump(out, open(f"{RD}/{period}_validation.json", "w"), indent=1)
print(json.dumps(out, indent=1)[:2500])
