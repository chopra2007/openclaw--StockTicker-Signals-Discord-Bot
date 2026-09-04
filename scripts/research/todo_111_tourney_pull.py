"""TODO #111 tournament — the only place that spends Databento money.

Manifest driven. A lane never downloads anything itself: it writes a manifest
saying which entry days it needs a whole-chain snapshot for, and which option
contracts it needs minute quotes for, and this script

  1. subtracts everything already on disk (including the files the earlier
     iron-condor study already paid for),
  2. cost-estimates every remaining request with the official estimator,
  3. refuses to send anything that could push the ALL-RUN total past the
     ceiling,
  4. downloads, and appends the exact request and its cost to the ledger.

Run with --estimate first. It sends no data request and spends nothing; it
prints what the manifest would cost.

Manifest shape:

  {"label": "lane-1-premium-selling",
   "chain_days": ["2014-01-08", ...],            # entry days needing a snapshot
   "legs": {"2014-01-08": {"symbols": ["SPY   140207P00173000", ...],
                           "end_day": "2014-01-29"}, ...}}

`end_day` is the last trading day the exit walk may use (the 14- or 7-day cap).
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import databento as db

TOURNEY = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
CONDOR = "/home/openclaw/.openclaw/research-data/todo-111-condor"
LEDGER = f"{TOURNEY}/spend_ledger.json"
CONDOR_LEDGER = f"{CONDOR}/spend_ledger.json"
DATASET = "OPRA.PILLAR"
CEILING = 20.00                 # hard, across the whole run, both ledgers
NY = ZoneInfo("America/New_York")
ENTRY_LOCAL = (10, 0)           # 10:00 exchange time = 7:00 a.m. Pacific
LOCK = threading.Lock()
# Six parallel requests were fine for the first few hundred files and then the
# provider started throttling them to roughly one a minute. Keep it low and let
# the environment raise it if a future run needs to.
WORKERS = int(os.environ.get("TOURNEY_WORKERS", "2"))


# ---------------------------------------------------------------- money

def key() -> str:
    for line in open("/root/.openclaw/.env"):
        m = re.match(r"^DATABENTO_API_KEY=(.*)$", line.strip())
        if m:
            return m.group(1).strip("\"'")
    raise SystemExit("DATABENTO_API_KEY not found")


def ledger(path=LEDGER) -> list:
    return json.load(open(path)) if os.path.exists(path) else []


def spent_all() -> float:
    """Everything this whole TODO #111 run has spent, both study folders."""
    return sum(x["cost_usd"] for x in ledger(CONDOR_LEDGER) + ledger(LEDGER))


def buy(client, label, path, **kw):
    """Estimate, check the ceiling, download, record. Never pays twice."""
    if os.path.exists(path):
        return db.DBNStore.from_file(path)
    cost = client.metadata.get_cost(dataset=DATASET, **kw)
    with LOCK:
        if spent_all() + cost > CEILING:
            raise SystemExit(f"STOP: {label} would take the run total to "
                             f"${spent_all() + cost:.4f}, past ${CEILING:.2f}")
    size = client.metadata.get_billable_size(dataset=DATASET, **kw)
    data = client.timeseries.get_range(dataset=DATASET, **kw)
    tmp = path + ".part"
    data.to_file(tmp)
    os.replace(tmp, path)
    with LOCK:
        led = ledger()
        led.append(dict(label=label, cost_usd=cost, billable_bytes=size, file=path,
                        request={k: (list(v) if isinstance(v, (list, tuple)) else str(v))
                                 for k, v in kw.items()}))
        json.dump(led, open(LEDGER, "w"), indent=1)
    return data


# ------------------------------------------------------- what is already owned

def chain_path(day: str, root: str = "SPY") -> str:
    """A whole-chain entry-minute snapshot, wherever it already lives.

    `root` is the underlying's option root. SPY keeps the original unprefixed
    file names so the 279 snapshots the condor study already paid for are still
    found; every other underlying gets its own file.
    """
    if root == "SPY":
        old = f"{CONDOR}/development/chain_{day}.dbn.zst"
        if os.path.exists(old):
            return old
        return f"{TOURNEY}/chains/chain_{day}.dbn.zst"
    return f"{TOURNEY}/chains/chain_{root}_{day}.dbn.zst"


def owned_symbols(day: str) -> dict:
    """symbol -> file, for every contract whose minutes are already on disk."""
    idx_path = f"{TOURNEY}/owned_index.json"
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    return idx.get(day, {})


def rebuild_owned_index():
    """Scan every leg file we own and record which contracts are inside it.

    Reads the request recorded in each ledger entry rather than opening the
    data, so this is fast and cannot be fooled by a partial download.
    """
    idx = {}
    for led_path, root in ((CONDOR_LEDGER, CONDOR), (LEDGER, TOURNEY)):
        for e in ledger(led_path):
            req = e.get("request", {})
            if req.get("schema") != "cbbo-1m" or req.get("stype_in") != "raw_symbol":
                continue
            f = e["file"]
            if not os.path.exists(f):
                continue
            m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
            if not m:
                continue
            day = m.group(1)
            end = str(req.get("end", ""))[:10]
            for s in req.get("symbols", []):
                idx.setdefault(day, {})[s] = {"file": f, "covers_to": end}
    os.makedirs(TOURNEY, exist_ok=True)
    json.dump(idx, open(f"{TOURNEY}/owned_index.json", "w"), indent=1)
    n = sum(len(v) for v in idx.values())
    print(f"owned index: {len(idx)} days, {n} contract-days already paid for")
    return idx


# ---------------------------------------------------------------- requests

def entry_ts(day: str) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, *ENTRY_LOCAL, tzinfo=NY)


def utc(ts: datetime) -> str:
    return ts.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")


def plan(manifest: dict, idx: dict) -> list:
    """Every request the manifest still needs, smallest set possible."""
    jobs = []
    # A chain day is either a bare date string (SPY, the default underlying) or
    # {"day": ..., "root": ...} when the lane trades some other stock.
    want = set()
    for item in manifest.get("chain_days", []):
        want.add((item, "SPY") if isinstance(item, str)
                 else (item["day"], item.get("root", "SPY")))
    for day, root in sorted(want):
        p = chain_path(day, root)
        if os.path.exists(p):
            continue
        t0 = entry_ts(day)
        jobs.append(dict(kind="chain", day=day, root=root, path=p,
                         label=f"chain {root} {day}",
                         kw=dict(schema="cbbo-1m", symbols=[f"{root}.OPT"],
                                 stype_in="parent",
                                 start=utc(t0), end=utc(t0 + timedelta(seconds=1)))))
    for day, spec in sorted(manifest.get("legs", {}).items()):
        end_day = spec["end_day"]
        have = idx.get(day, {})
        need = sorted(s for s in spec["symbols"]
                      if not (s in have and have[s]["covers_to"] >= end_day))
        if not need:
            continue
        h = hashlib.sha1(("|".join(need) + end_day).encode()).hexdigest()[:10]
        p = f"{TOURNEY}/legs/legs_{day}_{h}.dbn.zst"
        if os.path.exists(p):
            continue
        t0 = entry_ts(day)
        end = entry_ts(end_day).replace(hour=16, minute=5)
        jobs.append(dict(kind="legs", day=day, path=p, symbols=need,
                         label=f"legs {day} x{len(need)}",
                         kw=dict(schema="cbbo-1m", symbols=need,
                                 stype_in="raw_symbol",
                                 start=utc(t0), end=utc(end))))
    return jobs


def estimate(client, jobs) -> float:
    total = 0.0
    per_kind = {}
    def one(j):
        return j, client.metadata.get_cost(dataset=DATASET, **j["kw"])
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for j, c in ex.map(one, jobs):
            j["estimate"] = c
    for j in jobs:
        total += j["estimate"]
        per_kind[j["kind"]] = per_kind.get(j["kind"], 0.0) + j["estimate"]
    print(f"already spent on this run: ${spent_all():.4f}")
    for k, v in sorted(per_kind.items()):
        n = sum(1 for j in jobs if j["kind"] == k)
        print(f"  {k:6s} {n:5d} requests   ${v:.4f}")
    print(f"manifest estimate:          ${total:.4f}")
    print(f"run total if sent:          ${spent_all() + total:.4f} of ${CEILING:.2f}")
    return total


def download(client, jobs, allowance: float):
    est = sum(j["estimate"] for j in jobs)
    if est > allowance:
        raise SystemExit(f"STOP: estimate ${est:.4f} is over the ${allowance:.2f} "
                         "allowance given on the command line")
    os.makedirs(f"{TOURNEY}/chains", exist_ok=True)
    os.makedirs(f"{TOURNEY}/legs", exist_ok=True)
    done = [0]
    def one(j):
        buy(client, j["label"], j["path"], **j["kw"])
        done[0] += 1
        if done[0] % 25 == 0:
            print(f"  {done[0]}/{len(jobs)}  spent ${spent_all():.4f}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(one, jobs))
    print(f"done: {len(jobs)} requests, run total ${spent_all():.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("--estimate", action="store_true",
                    help="price the manifest and send no data request")
    ap.add_argument("--allowance", type=float, default=0.0,
                    help="the most this single run may spend; required to download")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild the index of contracts already on disk and stop")
    a = ap.parse_args()
    idx = rebuild_owned_index()
    if a.reindex:
        sys.exit(0)
    if not a.manifest:
        ap.error("a manifest path is required unless --reindex is given")
    man = json.load(open(a.manifest))
    jobs = plan(man, idx)
    print(f"manifest {man.get('label', a.manifest)}: {len(jobs)} requests still needed")
    if not jobs:
        sys.exit(0)
    client = db.Historical(key=key())
    estimate(client, jobs)
    if not a.estimate:
        if a.allowance <= 0:
            raise SystemExit("refusing to spend without an explicit --allowance")
        download(client, jobs, a.allowance)
