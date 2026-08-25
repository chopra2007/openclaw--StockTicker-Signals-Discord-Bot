"""Download the 5-minute and daily bars the exact-entry test needs, and cache them.

Source is Schwab `/pricehistory`, which reaches back about six months for
5-minute bars — enough for the whole 2026-06-01 → 2026-08-21 window. Nothing is
bought: no Databento call is made and no paid credit is spent.

The 6:35 a.m. Pacific price is the OPEN of the 9:35 a.m. Eastern 5-minute bar,
which is the first trade at or after that moment.

    python3 scripts/research/put_flow_fetch_bars.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")

CACHE_DIR = ROOT / "data" / "put_flow_bars"
BENCHMARK = "SPY"
START = datetime(2026, 5, 26, tzinfo=ET)
END = datetime(2026, 8, 23, tzinfo=ET)


def _frame_to_5m(df) -> dict[str, dict[str, float]]:
    """{'YYYY-MM-DD': {'HH:MM': open}} in Eastern clock time, regular session."""
    out: dict[str, dict[str, float]] = {}
    for ts, row in df.iterrows():
        ts = ts.tz_convert(ET)
        out.setdefault(ts.strftime("%Y-%m-%d"), {})[ts.strftime("%H:%M")] = float(row["Open"])
    return out


def _frame_to_daily(df) -> dict[str, list[float]]:
    """{'YYYY-MM-DD': [close, volume]}."""
    out: dict[str, list[float]] = {}
    for ts, row in df.iterrows():
        ts = ts.tz_convert(ET)
        out[ts.strftime("%Y-%m-%d")] = [float(row["Close"]), float(row["Volume"])]
    return out


def fetch(ticker: str, kind: str, force: bool = False) -> dict | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{ticker.replace('/', '_')}.{kind}.json"
    if path.exists() and not force:
        return json.loads(path.read_text())

    interval = "5m" if kind == "bars5m" else "1d"
    for attempt in range(3):
        try:
            df = schwab_client.get_price_history(
                ticker, interval=interval, start=START, end=END, extended_hours=False)
            break
        except Exception as e:  # network / auth / rate limit
            print(f"  {ticker} {kind} attempt {attempt + 1} failed: {e}", file=sys.stderr)
            df = None
            time.sleep(2 ** attempt)
    if df is None or df.empty:
        return None
    data = _frame_to_5m(df) if kind == "bars5m" else _frame_to_daily(df)
    path.write_text(json.dumps(data))
    return data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickers", default=None,
                   help="comma list; default = every ticker in frozen-candidates.csv")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        import csv
        csv_path = (ROOT / ".omc" / "research" / "extreme-put-flow-morning-shortlist"
                    / "frozen-candidates.csv")
        with csv_path.open() as fh:
            tickers = sorted({r["ticker"] for r in csv.DictReader(fh)})
    if BENCHMARK not in tickers:
        tickers.append(BENCHMARK)

    missing = []
    for i, tk in enumerate(tickers, 1):
        ok5 = fetch(tk, "bars5m", force=args.force) is not None
        okd = fetch(tk, "daily", force=args.force) is not None
        if not (ok5 and okd):
            missing.append(tk)
        print(f"[{i}/{len(tickers)}] {tk} 5m={'ok' if ok5 else 'MISSING'} "
              f"daily={'ok' if okd else 'MISSING'}", file=sys.stderr)
        time.sleep(0.35)

    print(json.dumps({
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "tickers": len(tickers),
        "missing": missing,
        "cache_dir": str(CACHE_DIR.relative_to(ROOT)),
        "paid_data_spend_usd": 0.0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
