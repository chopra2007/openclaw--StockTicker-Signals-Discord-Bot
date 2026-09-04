"""TODO #111 mechanism 6 — feasibility check for the put-flow morning shortlist.

This lane's FIRST job is not a backtest. Frozen matrix section 6 gates tests
51-54 on one question:

    Can the exact morning shortlist be reconstructed for each historical date
    from records that existed that morning?

This script answers it, spends nothing, downloads nothing. It only reads:
  - consensus.db  (options_flow / options_flow_outcomes — the raw poll history)
  - .omc/research/extreme-put-flow-morning-shortlist/frozen-candidates.csv

It re-derives the 188 frozen candidates three ways and prints whether they agree:
  A. exactly as put_flow_freeze_candidates.py did (graded events only)
  B. the same, but WITHOUT the look-ahead "5-day outcome exists" filter
  C. straight from options_flow with NO outcomes join at all

If A == B == C == the frozen CSV, the selection depends on nothing that was
unknowable on the signal-day close, and the gate passes.

    python3 scripts/research/todo_111_tourney_putflow.py
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import sqlite3
import sys
import zoneinfo
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from grade_options_flow import ETF_TICKERS, excess_move  # noqa: E402

PT = zoneinfo.ZoneInfo("America/Los_Angeles")
FROZEN_CSV = ROOT / ".omc/research/extreme-put-flow-morning-shortlist/frozen-candidates.csv"
META_FINGERPRINT = "5b7cfcc12ec454113bb7b5bdb7713938d8f129f21977e252b175d2db9ab98427"

MIN_VOL_OI = 50.0
MIN_VOLUME = 500
MIN_PREMIUM_USD = 250_000.0
MAX_PER_DATE = 4


def sort_key(r: dict) -> tuple:
    return (-(r.get("vol_oi_ratio") or 0.0),
            r.get("ticker") or "",
            r.get("contract_symbol") or "",
            r.get("flow_id") or 0)


def select(rows: list[dict]) -> list[dict]:
    """The frozen rule, byte-identical to put_flow_freeze_candidates.select_candidates."""
    pool = [
        r for r in rows
        if (r.get("side") or "").upper() == "PUT"
        and r["ticker"] not in ETF_TICKERS
        and (r.get("vol_oi_ratio") or 0.0) >= MIN_VOL_OI
        and (r.get("volume") or 0) >= MIN_VOLUME
        and (r.get("premium_usd") or 0.0) >= MIN_PREMIUM_USD
    ]
    best: dict[tuple, dict] = {}
    for r in pool:
        k = (r["ticker"], r["market_date"])
        if k not in best or sort_key(r) < sort_key(best[k]):
            best[k] = r
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in best.values():
        by_date[r["market_date"]].append(r)
    out: list[dict] = []
    for md in sorted(by_date):
        for i, r in enumerate(sorted(by_date[md], key=sort_key)[:MAX_PER_DATE], 1):
            rr = dict(r)
            rr["rank"] = i
            out.append(rr)
    return out


def fingerprint(cands: list[dict]) -> str:
    body = "\n".join(
        f"{c['market_date']}|{c['rank']}|{c['ticker']}|{c['contract_symbol']}|"
        f"{c['flow_id']}|{float(c['vol_oi_ratio']):.6f}"
        for c in cands
    )
    return hashlib.sha256(body.encode()).hexdigest()


# earliest options_flow row per (contract_symbol, market_date) — mirrors _FLOW_EVENTS_SQL
_EVENTS_SQL = """
SELECT f.id AS flow_id, f.ticker, f.side, f.contract_symbol, f.volume,
       f.open_interest, f.vol_oi_ratio, f.premium_usd, f.spot, f.detected_at,
       date(f.detected_at, 'unixepoch', '-5 hours') AS market_date
FROM options_flow f
JOIN (SELECT contract_symbol,
             date(detected_at, 'unixepoch', '-5 hours') AS md,
             MIN(detected_at) AS first_ts
      FROM options_flow GROUP BY contract_symbol, md) fst
  ON f.contract_symbol = fst.contract_symbol AND f.detected_at = fst.first_ts
WHERE f.spot > 0
"""


def main() -> int:
    db_path = ROOT / "consensus.db"
    if not db_path.exists():
        print("consensus.db not found at", db_path)
        return 2

    frozen = list(csv.DictReader(FROZEN_CSV.open()))
    fdates = {r["market_date"] for r in frozen}
    frozen_rows = [(r["market_date"], int(r["rank"]), r["ticker"],
                    r["contract_symbol"], int(r["flow_id"])) for r in frozen]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    joined = [dict(r) for r in conn.execute(
        """SELECT o.*, f.vol_oi_ratio, f.volume, f.premium_usd
           FROM options_flow_outcomes o JOIN options_flow f ON f.id = o.flow_id""")]
    graded = [r for r in joined if excess_move(r, 5) is not None]

    A = [c for c in select(graded) if c["market_date"] in fdates]
    B = [c for c in select(joined) if c["market_date"] in fdates]

    events = [dict(r) for r in conn.execute(_EVENTS_SQL)]
    C = [c for c in select(events) if c["market_date"] in fdates]

    def rowset(cands):
        return [(c["market_date"], c["rank"], c["ticker"],
                 c["contract_symbol"], c["flow_id"]) for c in cands]

    checks = {
        "A graded-events reconstruction == frozen CSV": rowset(A) == frozen_rows,
        "A fingerprint == meta.json": fingerprint(A) == META_FINGERPRINT,
        "B no-lookahead-filter reconstruction == frozen CSV": rowset(B) == frozen_rows,
        "C raw options_flow (no outcomes join) == frozen CSV": rowset(C) == frozen_rows,
    }

    # entry-timing: every detected_at strictly before the D+1 morning entry.
    late = []
    for r in frozen:
        d = dt.datetime.fromtimestamp(float(r["detected_at"]), PT)
        y, m, dd = map(int, r["market_date"].split("-"))
        nextday = dt.date(y, m, dd) + dt.timedelta(days=1)
        # conservative lower bound for entry: 06:30 PT on the next calendar day
        entry_lb = dt.datetime(nextday.year, nextday.month, nextday.day, 6, 30, tzinfo=PT)
        if d >= entry_lb:
            late.append((r["market_date"], r["ticker"], d.isoformat()))
    checks["every detected_at is before the next-day entry"] = not late

    print(f"frozen candidates: {len(frozen)} rows, {len(fdates)} signal dates")
    print(f"graded outcome rows in db: {len(joined)}  "
          f"(dropped by 5-day-outcome filter: {len(joined) - len(graded)})")
    print()
    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok &= passed
    if late:
        print("\n  detections at/after next-day 06:30 PT:")
        for x in late:
            print("   ", x)
    print()
    print("VERDICT:", "RECONSTRUCTABLE — mechanism 6 gate PASSES" if ok
          else "NOT reconstructable — see failures above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
