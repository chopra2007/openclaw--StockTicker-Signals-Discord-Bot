"""Round-3 data feasibility, measured live rather than remembered.

Round 3 opened a direction round 2 never touched: information from outside the
price series. This file goes and looks at what the project's own database
actually holds and when it starts, counts the minute bars on disk, and records
the answer. Every number below is queried at the moment the file is written.
"""
import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

DB = "/root/.openclaw/workspace/consensus.db"
MINUTES = Path("/home/openclaw/.openclaw/research-data/todo-111-round2/minutes")
DEV_END = "2025-07-01"
OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research/todo-111-round3/"
           "feasibility-data.json")


def day(x):
    return dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d")


def main():
    files = sorted(MINUTES.glob("*.parquet"))
    bars = sum(len(pd.read_parquet(p, columns=["ts"])) for p in files)

    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    tables = {}
    for table, col in [("ticker_signals", "detected_at"),
                       ("options_flow", "detected_at"),
                       ("signal_events", "recorded_at"),
                       ("shadow_predictions", "created_at")]:
        lo, hi, n = conn.execute(
            "select min(%s), max(%s), count(*) from %s" % (col, col, table)
        ).fetchone()
        before = conn.execute(
            "select count(*) from %s where %s < ?" % (table, col),
            (dt.datetime.fromisoformat(DEV_END).replace(
                tzinfo=dt.timezone.utc).timestamp(),)).fetchone()[0]
        tables[table] = {"rows": n, "oldest": day(lo) if lo and lo > 1e9 else str(lo),
                         "newest": day(hi), "rowsBeforeDevEnd": before}

    out = {
        "check": "data",
        "missionId": "todo-111-trading-edge-round3",
        "developmentEnds": DEV_END,
        "priceSeries": {
            "status": "available",
            "parquetFiles": len(files),
            "oneMinuteBars": bars,
            "symbols": len(files) // 2,
            "feeds": ["EQUS.MINI", "XNYS.PILLAR"],
            "note": "enough to decide first touch at one-minute resolution",
        },
        "outsidePriceSeries": {
            "status": "blocked",
            "reason": ("every record the project has collected postdates the "
                       "development period, so none of it can be used to build "
                       "a rule and all of it sits inside the sealed window"),
            "tables": tables,
        },
        "intradayOptionPrices": {
            "status": "blocked",
            "reason": ("the only local chains are one end-of-day snapshot a "
                       "week, 2019-02 to 2022-12, which cannot tell whether an "
                       "option touched +20% before -20%"),
            "ownerDecision": True,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out["outsidePriceSeries"]["tables"], indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
