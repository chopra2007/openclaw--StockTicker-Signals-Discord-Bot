#!/usr/bin/env python3
"""Lane A INDEPENDENT AUDIT recompute -- written by the auditor, not the
builder. Derives every headline number from the raw artifacts on its own
terms (own Wilson CI, own bootstrap, own clustering) rather than re-running
the builder's lane_a_analyze.py. Read-only; writes nothing."""
import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

R = Path(".omc/research/event-reaction-short-duration")
PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")

cat = json.loads((R / "lane_a_catalyst_outcomes.json").read_text())
ctrl = json.loads((R / "lane_a_control_outcomes.json").read_text())
rows = list(csv.DictReader((R / "events_lane_a.csv").open()))
manifest = json.loads((R / "events_lane_a_raw_manifest.json").read_text())


def signed(r, key="mkt_adj_ret_60m_pct"):
    v = r.get(key)
    if v is None:
        return None
    return v if r["trade_direction"] == "up" else -v


def wilson(w, n, z=1.96):
    if n == 0:
        return (None, None)
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - m) * 100, 1), round(min(1, c + m) * 100, 1))


def boot_mean_ci(vals, iters=10000, seed=7):
    if not vals:
        return (None, None)
    rnd = random.Random(seed)
    n = len(vals)
    means = sorted(statistics.mean(rnd.choices(vals, k=n)) for _ in range(iters))
    return (round(means[int(0.025 * iters)], 3), round(means[int(0.975 * iters)], 3))


def cluster_boot_mean_ci(pairs, iters=10000, seed=11):
    """Bootstrap resampling whole TICKERS, not rows -- respects the fact that
    repeated events on one ticker are not independent."""
    by = defaultdict(list)
    for tk, v in pairs:
        by[tk].append(v)
    keys = list(by)
    if not keys:
        return (None, None)
    rnd = random.Random(seed)
    means = []
    for _ in range(iters):
        s = [v for k in rnd.choices(keys, k=len(keys)) for v in by[k]]
        means.append(statistics.mean(s))
    means.sort()
    return (round(means[int(0.025 * iters)], 3), round(means[int(0.975 * iters)], 3))


def z_two_prop(w1, n1, w2, n2):
    if not n1 or not n2:
        return None
    p1, p2 = w1 / n1, w2 / n2
    pp = (w1 + w2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return round(z, 3), round(p, 4)


def arm(rowset, label):
    n = len(rowset)
    have = [r for r in rowset if signed(r) is not None]
    wins = [r for r in have if signed(r) > 0]
    vals = [signed(r) for r in have]
    pnl = [r["pnl_per_100_risk_dollars"] for r in rowset if r.get("pnl_per_100_risk_dollars") is not None]
    raw = [r["ticker_ret_60m_pct"] if r["trade_direction"] == "up" else -r["ticker_ret_60m_pct"]
           for r in rowset if r.get("ticker_ret_60m_pct") is not None]
    print(f"\n  [{label}] n={n}  (rows with mkt-adj 60m = {len(have)}; {n-len(have)} dropped)")
    if have:
        print(f"    directional success 60m (mkt-adj) : {len(wins)}/{len(have)} = "
              f"{len(wins)/len(have)*100:.1f}%  Wilson95 {wilson(len(wins), len(have))}")
        print(f"    mean mkt-adj 60m ret  : {statistics.mean(vals):+.3f}%  median {statistics.median(vals):+.3f}%"
              f"  boot95 {boot_mean_ci(vals)}")
        print(f"    ticker-clustered boot95 on that mean: "
              f"{cluster_boot_mean_ci([(r['ticker'], signed(r)) for r in have])}")
    if raw:
        print(f"    mean RAW (unadjusted) 60m ret: {statistics.mean(raw):+.3f}%")
    if pnl:
        print(f"    $ per $100 risk       : mean ${statistics.mean(pnl):+.2f} median ${statistics.median(pnl):+.2f}"
              f" total ${sum(pnl):+.2f}  boot95 {boot_mean_ci(pnl)}")
        print(f"    target/stop           : {dict(Counter(r['target_stop_outcome'] for r in rowset))}")
    tk = Counter(r["ticker"] for r in rowset)
    print(f"    distinct tickers={len(tk)}  top5 {tk.most_common(5)}")
    return {"have": have, "wins": len(wins), "nhave": len(have), "vals": vals, "pnl": pnl, "rows": rowset}


print("=" * 74)
print("LANE A -- INDEPENDENT AUDIT RECOMPUTE")
print("=" * 74)

# ---------- 1. event-table counts ----------
usable = [r for r in rows if not r["missing_data_exclusion_reason"]]
qual = [r for r in usable if r["qualifies"] == "True"]
print(f"\n1. EVENT TABLE  ({len(rows)} rows in events_lane_a.csv)")
print(f"   raw yfinance manifest rows : {len(manifest)}")
print(f"   excluded rows              : {len(rows)-len(usable)}")
print("   exclusion reasons          :")
for k, v in Counter(r["missing_data_exclusion_reason"] for r in rows if r["missing_data_exclusion_reason"]).most_common():
    print(f"       {k}: {v}")
print(f"   usable candidates          : {len(usable)}")
print(f"   qualifying (frozen filter) : {len(qual)}  = {len(qual)/len(usable)*100:.1f}% of usable")
for p in ("dev", "eval"):
    u = [r for r in usable if r["dev_or_eval"] == p]
    q = [r for r in u if r["qualifies"] == "True"]
    print(f"     {p:4s}: usable={len(u):4d}  qualifying={len(q):3d}  ({len(q)/len(u)*100:.1f}%)")
split = max(r["entry_day"] for r in usable if r["dev_or_eval"] == "dev")
emin = min(r["entry_day"] for r in usable if r["dev_or_eval"] == "eval")
print(f"   chronological split: dev ends {split}, eval starts {emin} -> "
      f"{'CHRONOLOGICAL, no overlap' if emin > split else 'OVERLAP -- DEFECT'}")

# ---------- 2. duplicates ----------
print("\n2. DUPLICATE CHECK")
for nm, rs in (("catalyst", cat), ("control", ctrl)):
    keys = Counter((r["ticker"], r["entry_day"]) for r in rs)
    dups = {k: v for k, v in keys.items() if v > 1}
    print(f"   {nm}: {len(rs)} rows, {len(keys)} distinct ticker+entry_day -> "
          f"{'CLEAN' if not dups else f'DUPLICATES {dups}'}")
qk = Counter((r["ticker"], r["entry_day"]) for r in qual)
print(f"   event table qualifying: {len(qual)} rows, {len(qk)} distinct ticker+entry_day -> "
      f"{'CLEAN' if all(v==1 for v in qk.values()) else 'DUPES ' + str({k:v for k,v in qk.items() if v>1})}")
overlap = {(r["ticker"], r["entry_day"]) for r in cat} & {(r["ticker"], r["entry_day"]) for r in ctrl}
print(f"   ticker+day appearing in BOTH arms: {len(overlap)} {sorted(overlap)[:5]}")

# ---------- 3. control-arm contamination ----------
print("\n3. CONTROL-ARM CONTAMINATION (is a 'no-catalyst' day actually an earnings day?)")
earn_days = defaultdict(set)      # every earnings entry_day in the table, qualifying or not
for r in usable:
    earn_days[r["ticker"]].add(r["entry_day"])
hits = [(r["ticker"], r["entry_day"]) for r in ctrl if r["entry_day"] in earn_days[r["ticker"]]]
print(f"   control days that ARE a Lane A earnings entry_day: {len(hits)}/{len(ctrl)}")
for h in hits[:15]:
    print(f"       {h[0]} {h[1]}")
# within +/-1 trading day of any earnings day (not just qualifying ones)
near = 0
for r in ctrl:
    d = date.fromisoformat(r["entry_day"])
    for off in (-3, -2, -1, 1, 2, 3):
        if str(d + timedelta(days=off)) in earn_days[r["ticker"]]:
            near += 1
            break
print(f"   control days within +/-3 calendar days of ANY earnings entry_day: {near}/{len(ctrl)}")

# ---------- 4. sector adjustment coverage ----------
print("\n4. SECTOR-ADJUSTMENT COVERAGE (primary outcome is 'market- AND sector-adjusted')")
priced = [r for r in qual if r["entry_price"]]
sec_ok = [r for r in priced if r["sector_adj_ret_60m_pct"]]
etf_ok = [r for r in priced if r["sector_etf_used"]]
print(f"   priced qualifying rows: {len(priced)}")
print(f"   with a mapped sector ETF          : {len(etf_ok)} ({len(etf_ok)/len(priced)*100:.1f}%)")
print(f"   with a sector-adjusted 60m return : {len(sec_ok)} ({len(sec_ok)/len(priced)*100:.1f}%)")
print(f"   -> the other {len(priced)-len(sec_ok)} are MARKET-ONLY adjusted")
print(f"   control rows carrying any sector_adj field: {sum('sector_adj_ret_60m_pct' in r for r in ctrl)}/{len(ctrl)}")

# ---------- 5. look-ahead / trigger-completion ----------
print("\n5. TRIGGER-COMPLETION vs ENTRY TIME  (plan s10: no entry before the trigger finished)")
print("   Trigger inputs (rvol_30m volume, initial_reaction_pct close) come from the")
print("   09:00-09:30 ET 30-minute bar -> not knowable until 09:30:00 ET.")
for nm, rs in (("catalyst", cat), ("control", ctrl)):
    et = Counter(r["entry_ts_et"][11:16] for r in rs)
    early = sum(v for k, v in et.items() if k < "09:30")
    print(f"   {nm}: entries before 09:30 ET = {early}/{len(rs)} ({early/len(rs)*100:.1f}%)  times {dict(sorted(et.items()))}")

# ---------- 6. geometry / balance ----------
print("\n6. BALANCE & GEOMETRY BIAS")
for p in ("dev", "eval"):
    c = [r for r in cat if r["period"] == p]
    k = [r for r in ctrl if r["period"] == p]
    if not c or not k:
        continue
    print(f"   {p}: N cat={len(c)} ctrl={len(k)}")
    for fld, f in (("rvol_30m", lambda r: r["rvol_30m"]),
                   ("|init move|%", lambda r: abs(r["initial_reaction_pct"]))):
        cv, kv = sorted(map(f, c)), sorted(map(f, k))
        print(f"     {fld:14s} cat med={statistics.median(cv):7.2f} (IQR {cv[len(cv)//4]:.2f}-{cv[3*len(cv)//4]:.2f})"
              f"   ctrl med={statistics.median(kv):7.2f} (IQR {kv[len(kv)//4]:.2f}-{kv[3*len(kv)//4]:.2f})"
              f"   ratio={statistics.median(cv)/statistics.median(kv):.2f}x")
    print(f"     direction split cat={dict(Counter(r['trade_direction'] for r in c))} "
          f"ctrl={dict(Counter(r['trade_direction'] for r in k))}")
    print(f"     date range  cat {min(r['entry_day'] for r in c)}..{max(r['entry_day'] for r in c)}"
          f"   ctrl {min(r['entry_day'] for r in k)}..{max(r['entry_day'] for r in k)}")

# ---------- 7. headline outcome recompute ----------
print("\n7. PRIMARY-OUTCOME RECOMPUTE")
res = {}
for p in ("dev", "eval"):
    print(f"\n  ===== {p.upper()} =====")
    a = arm([r for r in cat if r["period"] == p], f"{p} CATALYST")
    b = arm([r for r in ctrl if r["period"] == p], f"{p} CONTROL")
    res[p] = (a, b)
    zz = z_two_prop(a["wins"], a["nhave"], b["wins"], b["nhave"])
    print(f"    two-proportion z (cat vs ctrl, 60m directional): z={zz[0]} p={zz[1]}")
    if a["vals"] and b["vals"]:
        diff = statistics.mean(a["vals"]) - statistics.mean(b["vals"])
        print(f"    mean mkt-adj 60m difference (cat - ctrl): {diff:+.3f} pp")
        print(f"    mean $/100-risk difference: ${statistics.mean(a['pnl'])-statistics.mean(b['pnl']):+.2f}")

# ---------- 8. drift / concentration / extreme ----------
print("\n8. DRIFT, CONCENTRATION, EXTREME EVENT")
for p in ("dev", "eval"):
    k = [r for r in ctrl if r["period"] == p]
    # unsigned market-adjusted drift of the control arm = the period's own baseline
    uv = [r["mkt_adj_ret_60m_pct"] for r in k if r.get("mkt_adj_ret_60m_pct") is not None]
    up = [r for r in k if r["trade_direction"] == "up"]
    print(f"   {p}: control UNSIGNED mean mkt-adj 60m = {statistics.mean(uv):+.3f}%  "
          f"(a pure drift proxy; {len(up)}/{len(k)} control days were 'up')")
for p in ("dev", "eval"):
    a, b = res[p]
    rs = a["have"]
    if not rs:
        continue
    big = max(rs, key=lambda r: abs(signed(r)))
    rest = [signed(r) for r in rs if r is not big]
    print(f"   {p} catalyst largest |effect|: {big['ticker']} {big['entry_day']} "
          f"signed_mkt_adj_60m={signed(big):+.2f}%  pnl=${big['pnl_per_100_risk_dollars']}")
    print(f"      mean without it: {statistics.mean(rest):+.3f}% (with it {statistics.mean(a['vals']):+.3f}%)")
    bt = Counter(r["ticker"] for r in a["rows"])
    top = bt.most_common(1)[0]
    without = [signed(r) for r in rs if r["ticker"] != top[0]]
    print(f"      top ticker {top[0]} contributes {top[1]}/{len(a['rows'])} rows; "
          f"mean without that ticker: {statistics.mean(without):+.3f}%")
    bd = Counter(r["entry_day"] for r in a["rows"])
    topd = bd.most_common(3)
    print(f"      top days: {topd}")
    pnl_sorted = sorted(a["rows"], key=lambda r: -(r["pnl_per_100_risk_dollars"] or 0))
    print(f"      top3 PnL rows: " + ", ".join(f"{r['ticker']} {r['entry_day']} ${r['pnl_per_100_risk_dollars']}" for r in pnl_sorted[:3]))

# ---------- 9. EPS-sign vs reaction disagreement ----------
print("\n9. DIRECTION BASIS (EPS surprise sign vs observed premarket reaction)")
for p in ("dev", "eval"):
    u = [r for r in usable if r["dev_or_eval"] == p]
    ag = sum(1 for r in u if r["direction_agrees"] == "True")
    print(f"   {p}: agree {ag}/{len(u)} = {ag/len(u)*100:.1f}%  -> disagree {100-ag/len(u)*100:.1f}%")
    m = [r for r in u if r["rvol_30m"] and float(r["rvol_30m"]) >= 5.0 and abs(float(r["initial_reaction_pct"])) >= 3.0]
    ag2 = sum(1 for r in m if r["direction_agrees"] == "True")
    print(f"        among rows already passing rvol>=5 & |move|>=3: {ag2}/{len(m)} agree "
          f"({ag2/len(m)*100:.1f}%) -> the EPS-sign test rejects {len(m)-ag2} of {len(m)}")

# ---------- 10. power ----------
print("\n10. POWER vs plan s12 (~93 per group to separate 70% from 50%)")
for p in ("dev", "eval"):
    a, b = res[p]
    print(f"   {p}: catalyst n={a['nhave']} ({a['nhave']/93*100:.0f}% of the 93 floor), "
          f"control n={b['nhave']}; distinct catalyst tickers={len({r['ticker'] for r in a['rows']})}")
