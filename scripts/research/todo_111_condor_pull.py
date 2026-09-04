"""TODO #111 iron condor — buy exactly the Databento minutes the frozen rule needs.

Two purchases per entry:
  1. one minute of the whole SPY option chain, to read the expected move and
     name the four legs (allowed once per signal date by the handoff);
  2. every regular-session minute of those four legs, entry through the 14th
     trading day.

Every request is cost-estimated first and appended to the spend ledger. The
script refuses to send a request that would push the running total past the
$20.00 ceiling.
"""
from __future__ import annotations
import json, os, re, sys, threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from concurrent.futures import ThreadPoolExecutor

import databento as db

RD = "/home/openclaw/.openclaw/research-data/todo-111-condor"
LEDGER = f"{RD}/spend_ledger.json"
DATASET = "OPRA.PILLAR"
CEILING = 20.00
LOCK = threading.Lock()          # the ledger is the shared spend record
WORKERS = 6
NY = ZoneInfo("America/New_York")
ENTRY_LOCAL = (10, 0)          # 10:00 exchange time = 7:00 a.m. Pacific
MAX_HOLD_TRADING_DAYS = 14
WING = 5.0
DTE_LO, DTE_HI, DTE_TARGET = 30, 45, 37


def key() -> str:
    for line in open("/root/.openclaw/.env"):
        m = re.match(r"^DATABENTO_API_KEY=(.*)$", line.strip())
        if m:
            return m.group(1).strip("\"'")
    raise SystemExit("DATABENTO_API_KEY not found")


def ledger() -> list:
    return json.load(open(LEDGER)) if os.path.exists(LEDGER) else []


def spent(led=None) -> float:
    return sum(x["cost_usd"] for x in (led if led is not None else ledger()))


def buy(client, label, path, **kw):
    """Estimate, check the ceiling, download, record. Returns the DBNStore."""
    if os.path.exists(path):                      # already bought, never pay twice
        return db.DBNStore.from_file(path)
    cost = client.metadata.get_cost(dataset=DATASET, **kw)
    with LOCK:                                    # one writer at a time on the ledger
        led = ledger()
        if spent(led) + cost > CEILING:
            raise SystemExit(f"STOP: {label} would take the total to "
                             f"${spent(led) + cost:.4f}, past the ${CEILING:.2f} ceiling")
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


OSI = re.compile(r"^(?P<root>.{6})(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_osi(sym: str):
    m = OSI.match(sym)
    if not m:
        return None
    return (f"20{m['y']}-{m['m']}-{m['d']}", m["cp"], int(m["strike"]) / 1000.0)


def snapshot_quotes(store):
    """raw symbol -> (bid, ask, bid_size, ask_size) for the one snapshot minute."""
    df = store.to_df()
    if df.empty:
        return {}
    first = df.index.min()
    df = df[df.index == first]
    out = {}
    for sym, b, a, bs, asz in zip(df["symbol"], df["bid_px_00"], df["ask_px_00"],
                                  df["bid_sz_00"], df["ask_sz_00"]):
        out[sym] = (float(b), float(a), int(bs), int(asz))
    return out


def choose_legs(quotes, entry_day: str):
    """The frozen selector. Returns a dict or a string saying why it skipped."""
    ed = datetime.fromisoformat(entry_day).date()
    chain = {}
    for sym, (b, a, bs, asz) in quotes.items():
        p = parse_osi(sym)
        if not p or a <= 0:          # ask > 0 is the quote test; a 0.00 bid is real
            continue
        exp, cp, k = p
        dte = (datetime.fromisoformat(exp).date() - ed).days
        if DTE_LO <= dte <= DTE_HI:
            chain.setdefault(exp, {}).setdefault(k, {})[cp] = (b, a, bs, asz)
    if not chain:
        return "no listed expiry 30-45 days out"
    # depth first: the thin weeklies in the window do not list a $5 wing
    exp = max(chain, key=lambda e: (len(chain[e]),
              -abs((datetime.fromisoformat(e).date() - ed).days - DTE_TARGET)))
    strikes = chain[exp]
    both = {k: v for k, v in strikes.items() if "C" in v and "P" in v}
    if not both:
        return "no strike with both a call and a put"
    mid = lambda q: (q[0] + q[1]) / 2.0
    k_par = min(both, key=lambda k: abs(mid(both[k]["C"]) - mid(both[k]["P"])))
    spot = k_par + mid(both[k_par]["C"]) - mid(both[k_par]["P"])
    k_atm = min(both, key=lambda k: abs(k - spot))
    em = mid(both[k_atm]["C"]) + mid(both[k_atm]["P"])
    listed = sorted(strikes)
    below = [k for k in listed if k <= spot - em and "P" in strikes[k]]
    above = [k for k in listed if k >= spot + em and "C" in strikes[k]]
    if not below or not above:
        return "expected-move boundary is outside the listed strikes"
    sp, sc = max(below), min(above)
    lp, lc = sp - WING, sc + WING
    if lp not in strikes or "P" not in strikes.get(lp, {}):
        return f"long put {lp} not listed"
    if lc not in strikes or "C" not in strikes.get(lc, {}):
        return f"long call {lc} not listed"
    root = next(s for s in quotes if parse_osi(s) and parse_osi(s)[0] == exp)[:6]
    y, m, d = exp.split("-")
    osi = lambda k, cp: f"{root}{y[2:]}{m}{d}{cp}{int(round(k * 1000)):08d}"
    return dict(expiration=exp, dte=(datetime.fromisoformat(exp).date() - ed).days,
                spot=spot, atm_strike=k_atm, expected_move=em,
                lower=spot - em, upper=spot + em,
                short_put=sp, long_put=lp, short_call=sc, long_call=lc,
                symbols={"short_put": osi(sp, "P"), "long_put": osi(lp, "P"),
                         "short_call": osi(sc, "C"), "long_call": osi(lc, "C")})


def entry_ts(day: str) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, *ENTRY_LOCAL, tzinfo=NY)


def utc(ts: datetime) -> str:
    return ts.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")


def run(period: str, limit: int | None = None, estimate_only: bool = False):
    sd = json.load(open(f"{RD}/signal_dates.json"))[period]
    spy = json.load(open("/home/openclaw/.openclaw/workspace/data/mmhl_daily/SPY.json"))
    days = sorted(spy)
    idx = {d: i for i, d in enumerate(days)}
    client = db.Historical(key=key())
    os.makedirs(f"{RD}/{period}", exist_ok=True)
    def one(sig):
        if sig not in idx or idx[sig] + 1 >= len(days):
            return None
        entry_day = days[idx[sig] + 1]
        last_day = days[min(idx[entry_day] + MAX_HOLD_TRADING_DAYS, len(days) - 1)]
        t0 = entry_ts(entry_day)
        rec = dict(signal_date=sig, entry_day=entry_day, last_day=last_day)
        kw = dict(schema="cbbo-1m", symbols=["SPY.OPT"], stype_in="parent",
                  start=utc(t0), end=utc(t0 + timedelta(seconds=1)))
        if estimate_only:
            rec["chain_cost"] = client.metadata.get_cost(dataset=DATASET, **kw)
            return rec
        store = buy(client, f"chain {entry_day}", f"{RD}/{period}/chain_{entry_day}.dbn.zst", **kw)
        legs = choose_legs(snapshot_quotes(store), entry_day)
        if isinstance(legs, str):
            rec["skipped"] = legs
            print(f"{sig} -> {entry_day}: SKIP ({legs})", flush=True)
            return rec
        rec["legs"] = legs
        end = entry_ts(last_day).replace(hour=16, minute=5)
        leg_path = f"{RD}/{period}/legs_{entry_day}.dbn.zst"
        buy(client, f"legs {entry_day}", leg_path,
            schema="cbbo-1m", symbols=sorted(legs["symbols"].values()),
            stype_in="raw_symbol", start=utc(t0), end=utc(end))
        rec["legs_file"] = leg_path
        print(f"{sig} -> {entry_day}: {legs['expiration']} "
              f"{legs['long_put']}/{legs['short_put']} - "
              f"{legs['short_call']}/{legs['long_call']}  spot {legs['spot']:.2f} "
              f"EM {legs['expected_move']:.2f}  spent ${spent():.4f}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        out = [r for r in ex.map(one, sd["dates"][:limit]) if r]
    json.dump(out, open(f"{RD}/{period}_trades.json", "w"), indent=1)
    print(f"\n{period}: {len(out)} entries, total spent ${spent():.4f}")


if __name__ == "__main__":
    period = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    run(period, limit, estimate_only="--estimate" in sys.argv)
