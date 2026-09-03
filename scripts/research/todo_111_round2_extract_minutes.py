"""One-time extraction of the local Databento one-minute bars into per-symbol
parquet so every later candidate test is cheap.

Writes to /home/openclaw/.openclaw/research-data/todo-111-round2/minutes/.
Safe to re-run: a symbol file that already exists is left alone.

Bars are stamped at the START of the minute (a bar stamped 09:30 Eastern covers
09:30:00-09:30:59). Prices are kept in float dollars.
"""
import json
import sys
import time
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from intraday_dislocation_common import canonical, open_store, symbol_map

SRC = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions/"
           "selected60_2023-01_to_2026-08")
OUT = Path("/home/openclaw/.openclaw/research-data/todo-111-round2/minutes")
SCALE = 1e-9

FILES = [
    ("equs", SRC / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"),
    ("equs", SRC / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"),
    ("xnys", SRC / "xnys-pillar_ohlcv-1m_60-symbols_2023-01-01_2026-08-22.dbn.zst"),
]


def extract(tag, path):
    t0 = time.time()
    inst2sym = {i: canonical(s) for i, s in symbol_map(path).items()}
    names = sorted(set(inst2sym.values()))
    code = {n: i for i, n in enumerate(names)}
    unknown = 0

    ts = array("q")
    sym = array("i")
    op = array("q")
    hi = array("q")
    lo = array("q")
    cl = array("q")
    vol = array("q")

    for rec in open_store(path):
        name = inst2sym.get(rec.instrument_id)
        if name is None:
            unknown += 1
            continue
        ts.append(rec.ts_event)
        sym.append(code[name])
        op.append(rec.open)
        hi.append(rec.high)
        lo.append(rec.low)
        cl.append(rec.close)
        vol.append(rec.volume)

    df = pd.DataFrame({
        "ts": pd.to_datetime(np.frombuffer(ts, dtype=np.int64), utc=True),
        "symbol": np.frombuffer(sym, dtype=np.int32),
        "open": np.frombuffer(op, dtype=np.int64) * SCALE,
        "high": np.frombuffer(hi, dtype=np.int64) * SCALE,
        "low": np.frombuffer(lo, dtype=np.int64) * SCALE,
        "close": np.frombuffer(cl, dtype=np.int64) * SCALE,
        "volume": np.frombuffer(vol, dtype=np.int64),
    })
    written = []
    for scode, part in df.groupby("symbol"):
        name = names[int(scode)]
        out = OUT / ("%s__%s.parquet" % (tag, name))
        part = part.drop(columns=["symbol"]).sort_values("ts")
        if out.exists():
            part = (pd.concat([pd.read_parquet(out), part])
                      .sort_values("ts").drop_duplicates("ts"))
        part.to_parquet(out, index=False)
        written.append({"symbol": name, "rows": int(len(part)),
                        "first": str(part["ts"].iloc[0]), "last": str(part["ts"].iloc[-1])})
    print("%s %s: %d records, %d symbols, %d unknown, %.1fs"
          % (tag, path.name[:44], len(df), len(written), unknown, time.time() - t0),
          flush=True)
    return written


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for tag, path in FILES:
        report.setdefault(tag, []).extend(extract(tag, path))
    (OUT / "extraction-report.json").write_text(json.dumps(report, indent=2))
    print("files written:", len(list(OUT.glob("*.parquet"))))


if __name__ == "__main__":
    main()
