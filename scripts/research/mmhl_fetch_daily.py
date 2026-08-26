"""Fetch and cache long-history DAILY bars for the multi-method research run.

Research-only. Writes nothing into production paths and is imported by no
production code. Cache lives under data/mmhl_daily/.

Universe = the tickers this project actually tracks (those that appear in
options_flow_outcomes), minus funds/ETFs, since the research question is about
single stocks. This is a disclosed selection: the list is today's list, so
delisted names are absent (survivorship bias), and it was selected on 2026
options activity.

    python3 scripts/research/mmhl_fetch_daily.py
"""

from __future__ import annotations

import json
import sqlite3
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

CACHE_DIR = ROOT / "data" / "mmhl_daily"
DB = ROOT / "consensus.db"

# Start well after the earliest available date: a start before ~1985 makes the
# vendor silently return garbage instead of erroring (measured in the data
# inventory), so we never request one.
START = datetime(2005, 1, 1, tzinfo=ET)
END = datetime(2026, 8, 24, tzinfo=ET)

# Funds, index products and leveraged/commodity vehicles. The research question
# is about single stocks; a fund's "gap" is a different animal.
NOT_A_STOCK = {
    "SPY", "QQQ", "IWM", "DIA", "SOXX", "SMH", "SOXL", "SOXS", "TQQQ", "SQQQ",
    "USO", "GLD", "SLV", "UNG", "TLT", "HYG", "LQD", "XLF", "XLE", "XLK", "XLV",
    "XLI", "XLP", "XLU", "XLB", "XLY", "XLC", "XLRE", "XBI", "IBIT", "ARKK",
    "VXX", "UVXY", "SVXY", "EEM", "EFA", "FXI", "KWEB", "GDX", "GDXJ", "TNA",
    "TZA", "SPXU", "UPRO", "SSO", "SDS", "QLD", "PSQ", "SH", "VOO", "VTI",
    "RSP", "MTUM", "QUAL", "SIZE", "SPHB", "SPLV", "USMV", "VLUE", "IWD", "IWF",
    "LABU", "LABD", "NUGT", "DUST", "JNUG", "ERX", "FAS", "FAZ", "YINN", "MSTX",
    "BITO", "ETHU", "SPXL", "TMF", "TMV", "BOIL", "KOLD", "UCO", "SCO", "AGQ",
}


def universe() -> list[str]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT DISTINCT ticker FROM options_flow_outcomes ORDER BY ticker").fetchall()
    con.close()
    out = []
    for (t,) in rows:
        t = t.strip().upper()
        if not t or t in NOT_A_STOCK:
            continue
        if not t.isalpha() or len(t) > 5:      # drop odd symbols/options artefacts
            continue
        out.append(t)
    return out


def fetch(ticker: str, force: bool = False) -> dict | None:
    """{'YYYY-MM-DD': [open, high, low, close, volume]} in Eastern dates."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{ticker}.json"
    if path.exists() and not force:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    df = None
    for attempt in range(3):
        try:
            df = schwab_client.get_price_history(
                ticker, interval="1d", start=START, end=END, extended_hours=False)
            break
        except Exception as e:
            print(f"  {ticker} attempt {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    if df is None or df.empty:
        return None
    out: dict[str, list[float]] = {}
    for ts, row in df.iterrows():
        d = ts.tz_convert(ET).strftime("%Y-%m-%d")
        out[d] = [float(row["Open"]), float(row["High"]), float(row["Low"]),
                  float(row["Close"]), float(row["Volume"])]
    if not out:
        return None
    path.write_text(json.dumps(out))
    return out


def main() -> int:
    tickers = universe()
    print(f"universe: {len(tickers)} single stocks", file=sys.stderr)
    ok, missing, spans = 0, [], {}
    for i, tk in enumerate(tickers, 1):
        data = fetch(tk)
        if data:
            ok += 1
            ds = sorted(data)
            spans[tk] = [ds[0], ds[-1], len(ds)]
        else:
            missing.append(tk)
        if i % 25 == 0 or i == len(tickers):
            print(f"[{i}/{len(tickers)}] ok={ok} missing={len(missing)}", file=sys.stderr)
        time.sleep(0.3)

    meta = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "requested_start": START.strftime("%Y-%m-%d"),
        "tickers_requested": len(tickers),
        "tickers_ok": ok,
        "missing": missing,
        "paid_data_spend_usd": 0.0,
        "spans": spans,
    }
    (CACHE_DIR / "_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "spans"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
