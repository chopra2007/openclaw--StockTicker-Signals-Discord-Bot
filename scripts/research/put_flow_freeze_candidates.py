"""Freeze the extreme-PUT-flow morning shortlist candidates from stored rows.

One job only: apply the frozen selection rule to `options_flow` +
`options_flow_outcomes` and write the candidate list plus a fingerprint of it,
BEFORE any exact-entry price is fetched. Nothing here looks at future prices.

The frozen rule (see .omc/plans/extreme-put-flow-morning-shortlist-build-prompt.md):
  1. side = PUT
  2. single stocks only (project fund list in scripts/grade_options_flow.py)
  3. vol_oi_ratio >= 50
  4. keep the live size gates: volume >= 500, premium >= $250,000
  5. one event per (ticker, market_date): highest vol_oi_ratio, stable tie-break
  6. rank by vol_oi_ratio, keep at most 4 per date
  7. the BUY/SELL side tag is NOT used as a gate
  8. zero selections on a date is allowed

    python3 scripts/research/put_flow_freeze_candidates.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from grade_options_flow import ETF_TICKERS, excess_move  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
OUT_DIR = ROOT / ".omc" / "research" / "extreme-put-flow-morning-shortlist"

MIN_VOL_OI = 50.0
MIN_VOLUME = 500
MIN_PREMIUM_USD = 250_000.0
MAX_PER_DATE = 4

FIELDS = [
    "market_date", "rank", "ticker", "contract_symbol", "side",
    "vol_oi_ratio", "volume", "premium_usd", "flow_id", "detected_at",
    "entry_spot", "close_0d", "close_1d", "close_5d",
    "bench_close_0d", "bench_close_1d", "bench_close_5d",
]


def sort_key(row: dict) -> tuple:
    """Rank highest vol/OI first. Ticker then contract symbol break ties, so the
    same stored rows always produce the same list."""
    return (-(row.get("vol_oi_ratio") or 0.0),
            row.get("ticker") or "",
            row.get("contract_symbol") or "",
            row.get("flow_id") or 0)


def select_candidates(rows: list[dict]) -> list[dict]:
    """Apply the frozen rule to already-joined flow+outcome rows."""
    pool = [
        r for r in rows
        if (r.get("side") or "").upper() == "PUT"
        and r["ticker"] not in ETF_TICKERS
        and (r.get("vol_oi_ratio") or 0.0) >= MIN_VOL_OI
        and (r.get("volume") or 0) >= MIN_VOLUME
        and (r.get("premium_usd") or 0.0) >= MIN_PREMIUM_USD
    ]

    # Step 5: one event per ticker per market date, highest vol/OI wins.
    best: dict[tuple, dict] = {}
    for r in pool:
        k = (r["ticker"], r["market_date"])
        if k not in best or sort_key(r) < sort_key(best[k]):
            best[k] = r

    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in best.values():
        by_date[r["market_date"]].append(r)

    out: list[dict] = []
    for market_date in sorted(by_date):
        ranked = sorted(by_date[market_date], key=sort_key)[:MAX_PER_DATE]
        for i, r in enumerate(ranked, start=1):
            r = dict(r)
            r["rank"] = i
            out.append(r)
    return out


def load_rows(db_path: Path, require_graded: bool) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT o.*, f.vol_oi_ratio, f.volume, f.premium_usd
               FROM options_flow_outcomes o JOIN options_flow f ON f.id = o.flow_id"""
        )]
    finally:
        conn.close()
    if require_graded:
        # The reproduction sample is the events whose 5-day market-adjusted move
        # could be computed. Keeps this list identical to the stored evidence.
        rows = [r for r in rows if excess_move(r, 5) is not None]
    return rows


def fingerprint(cands: list[dict]) -> str:
    body = "\n".join(
        f"{c['market_date']}|{c['rank']}|{c['ticker']}|{c['contract_symbol']}|"
        f"{c['flow_id']}|{c['vol_oi_ratio']:.6f}"
        for c in cands
    )
    return hashlib.sha256(body.encode()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(ROOT / "consensus.db"))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(Path(args.db), require_graded=True)
    cands = select_candidates(rows)

    csv_path = out_dir / "frozen-candidates.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for c in cands:
            w.writerow(c)

    dates = sorted({c["market_date"] for c in cands})
    meta = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "rule": {
            "side": "PUT",
            "min_vol_oi": MIN_VOL_OI,
            "min_volume": MIN_VOLUME,
            "min_premium_usd": MIN_PREMIUM_USD,
            "max_per_date": MAX_PER_DATE,
            "fund_exclusion": sorted(ETF_TICKERS),
            "one_event_per": ["ticker", "market_date"],
            "tie_break": "vol_oi_ratio desc, ticker, contract_symbol, flow_id",
            "buy_sell_tag_used_as_gate": False,
        },
        "source_rows_graded": len(rows),
        "candidates": len(cands),
        "signal_dates": len(dates),
        "distinct_stocks": len({c["ticker"] for c in cands}),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "fingerprint_sha256": fingerprint(cands),
        "csv": str(csv_path.relative_to(ROOT)),
    }
    (out_dir / "frozen-candidates-meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print(json.dumps({k: v for k, v in meta.items() if k != "rule"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
