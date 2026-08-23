#!/usr/bin/env python3
"""Lane B INDEPENDENT AUDIT — recompute headline numbers from raw files.

Written by the auditor (not the builder). Does not import or reuse the
builder's lane_b_build_events.py / lane_b_eval_test.py logic; derives every
number again from events_lane_b.csv, events_lane_b_raw_manifest.csv and
lane_b_eval_results.json.

Read-only. No provider calls. Usage: python3 scripts/research/lane_b_audit_recompute.py
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parents[2]
D = ROOT / ".omc" / "research" / "event-reaction-short-duration"

csv.field_size_limit(10_000_000)


def wilson(x: int, n: int, z: float = 1.96):
    if n == 0:
        return (None, None)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def mean_ci(v):
    n = len(v)
    if n < 2:
        return {"n": n, "mean": v[0] if n else None}
    m = statistics.mean(v)
    se = statistics.stdev(v) / math.sqrt(n)
    return {"n": n, "mean": round(m, 6), "ci95": [round(m - 1.96 * se, 6), round(m + 1.96 * se, 6)]}


def main():
    out = {}

    # ---------- 1. Event table ----------
    with open(D / "events_lane_b.csv", newline="") as f:
        events = list(csv.DictReader(f))
    out["event_rows_total"] = len(events)
    per = Counter((e["period"], e["ticker"]) for e in events)
    out["counts_by_period_ticker"] = {f"{p}/{t}": c for (p, t), c in sorted(per.items())}
    out["dev_events"] = sum(1 for e in events if e["period"] == "dev")
    out["eval_events"] = sum(1 for e in events if e["period"] == "eval")

    # ---------- 2. Duplicates / one-per-ticker-day ----------
    key = Counter((e["ticker"], e["trading_day_et"]) for e in events)
    out["ticker_day_collisions"] = {f"{k[0]} {k[1]}": v for k, v in key.items() if v > 1}
    out["duplicate_event_ids"] = [k for k, v in Counter(e["event_id"] for e in events).items() if v > 1]
    out["duplicate_urls"] = [k for k, v in Counter(e["url"] for e in events).items() if v > 1]
    out["duplicate_headlines"] = [k for k, v in Counter(e["headline"].strip().lower() for e in events).items() if v > 1]

    # ---------- 3. Chronological dev/eval separation ----------
    dev_days = sorted(e["trading_day_et"] for e in events if e["period"] == "dev")
    eval_days = sorted(e["trading_day_et"] for e in events if e["period"] == "eval")
    out["dev_day_range"] = [dev_days[0], dev_days[-1]]
    out["eval_day_range"] = [eval_days[0], eval_days[-1]]
    out["chronological_separation_clean"] = dev_days[-1] < eval_days[0]
    out["misfiled_period_rows"] = [
        e["event_id"] for e in events
        if (e["trading_day_et"] < "2026-07-01") != (e["period"] == "dev")
    ]

    # ---------- 4. Entry-timing arithmetic re-derived from first_public_ts ----------
    bad_delay, owner_window_flag_mismatch = [], []
    pt_in_window_dev = pt_in_window_eval = 0
    entry_hour_pt = Counter()
    for e in events:
        fp = datetime.fromisoformat(e["first_public_ts_et"])
        en = datetime.fromisoformat(e["entry_ts_et"])
        if (en - fp).total_seconds() != 20 * 60:
            bad_delay.append((e["event_id"], (en - fp).total_seconds() / 60))
        pt = datetime.fromisoformat(e["entry_ts_pt"])
        entry_hour_pt[pt.hour] += 1
        in_win = (pt.hour == 6 and 15 <= pt.minute <= 45)
        if in_win != (e["owner_actionable_window"] == "True"):
            owner_window_flag_mismatch.append(e["event_id"])
        if in_win:
            if e["period"] == "dev":
                pt_in_window_dev += 1
            else:
                pt_in_window_eval += 1
    out["entry_delay_not_exactly_20min"] = bad_delay
    out["owner_window_flag_mismatches"] = owner_window_flag_mismatch
    out["owner_actionable_window_dev"] = pt_in_window_dev
    out["owner_actionable_window_eval"] = pt_in_window_eval
    out["owner_actionable_pct_of_eval"] = round(100 * pt_in_window_eval / out["eval_events"], 2)
    out["entry_hour_pt_histogram_eval"] = dict(sorted(
        Counter(datetime.fromisoformat(e["entry_ts_pt"]).hour
                for e in events if e["period"] == "eval").items()))

    # ---------- 5. Retention rate off the CLASSIFIED candidate pool ----------
    with open(D / "events_lane_b_raw_manifest.csv", newline="") as f:
        man = list(csv.DictReader(f))
    out["manifest_rows"] = len(man)
    classified = [r for r in man if r["regex_chaff"] == "False"
                  and "not classified this run" not in (r.get("evidence_quote") or "")]
    passed = [r for r in classified if r["passes_frozen_retention_rule"] == "True"]
    out["manifest_regex_chaff_true"] = sum(1 for r in man if r["regex_chaff"] == "True")
    out["manifest_capped_out"] = sum(1 for r in man if "not classified this run" in (r.get("evidence_quote") or ""))
    out["classified_by_llm"] = len(classified)
    out["passed_frozen_rule"] = len(passed)
    out["retention_rate_of_classified_pct"] = round(100 * len(passed) / len(classified), 2)
    out["retention_rate_of_all_reps_pct"] = round(100 * len(passed) / len(man), 2)
    out["retention_by_ticker_pct"] = {
        t: round(100 * sum(1 for r in passed if r["ticker"] == t)
                 / max(1, sum(1 for r in classified if r["ticker"] == t)), 2)
        for t in ("AAPL", "MRNA", "ROKU", "GME")}

    # ---------- 6. Recompute eval-period outcome statistics ----------
    res = json.load(open(D / "lane_b_eval_results.json"))
    ev = res["event_level_detail"]
    ct = res["control_level_detail"]

    def usable(rs):
        return [r for r in rs if r.get("outcome") and "excluded_reason" not in r["outcome"]
                and r["outcome"].get("return_60min")]

    uev, uct = usable(ev), usable(ct)
    out["recomputed_usable_events"] = len(uev)
    out["recomputed_usable_controls"] = len(uct)
    out["recomputed_excluded_events"] = len(ev) - len(uev)
    out["excluded_pct_of_eval"] = round(100 * (len(ev) - len(uev)) / len(ev), 2)
    out["exclusion_reason_counts"] = dict(Counter(
        (r["outcome"] or {}).get("excluded_reason", "no_return_60min_computed") if r.get("outcome")
        else "no_outcome" for r in ev if r not in uev))

    e60 = [r["outcome"]["return_60min"]["signed_adjusted_return"] for r in uev]
    c60 = [r["outcome"]["return_60min"]["signed_adjusted_return"] for r in uct]
    es = sum(1 for v in e60 if v > 0)
    cs = sum(1 for v in c60 if v > 0)
    out["event_arm"] = {"n": len(e60), "successes": es, "rate": round(es / len(e60), 4),
                        "wilson95": wilson(es, len(e60)), "signed_return_60min": mean_ci(e60)}
    out["control_arm"] = {"n": len(c60), "successes": cs, "rate": round(cs / len(c60), 4),
                          "wilson95": wilson(cs, len(c60)), "signed_return_60min": mean_ci(c60)}

    p1, n1, p2, n2 = es / len(e60), len(e60), cs / len(c60), len(c60)
    pp = (es + cs) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se
    out["two_proportion_z"] = round(z, 3)
    out["two_proportion_p_two_sided"] = round(math.erfc(abs(z) / math.sqrt(2)), 4)

    # ---------- 7. Largest-event robustness ----------
    i_max = max(range(len(e60)), key=lambda i: abs(e60[i]))
    trimmed = e60[:i_max] + e60[i_max + 1:]
    out["largest_event"] = {
        "event_id": uev[i_max]["event_id"], "ticker": uev[i_max]["ticker"],
        "trading_day_et": uev[i_max]["trading_day_et"],
        "signed_return": e60[i_max], "headline": uev[i_max]["headline"][:110],
        "mean_with_all": round(statistics.mean(e60), 6),
        "mean_after_drop": round(statistics.mean(trimmed), 6),
        "success_rate_after_drop": round(sum(1 for v in trimmed if v > 0) / len(trimmed), 4),
    }

    # ---------- 8. Concentration ----------
    out["event_arm_by_ticker"] = {
        t: {"n": sum(1 for r in uev if r["ticker"] == t),
            "successes": sum(1 for r in uev if r["ticker"] == t
                             and r["outcome"]["return_60min"]["signed_adjusted_return"] > 0),
            "mean_signed": round(statistics.mean(
                [r["outcome"]["return_60min"]["signed_adjusted_return"] for r in uev if r["ticker"] == t]), 6)
            if any(r["ticker"] == t for r in uev) else None}
        for t in ("AAPL", "MRNA", "ROKU", "GME")}
    out["eval_direction_split"] = dict(Counter(r["direction_implied"] for r in uev))
    out["distinct_eval_trading_days"] = len({r["trading_day_et"] for r in uev})

    # ---------- 9. Control-arm entry-clock mismatch magnitude ----------
    med = res["median_entry_clock_et_by_ticker"]
    gaps = defaultdict(list)
    for r in uev:
        h, m = map(int, med[r["ticker"]].split(":"))
        et = datetime.fromisoformat(r["entry_ts_et"])
        gaps[r["ticker"]].append(abs((et.hour * 60 + et.minute) - (h * 60 + m)))
    out["control_clock_mismatch_minutes"] = {
        t: {"median": statistics.median(v), "max": max(v), "n": len(v)} for t, v in gaps.items()}

    # ---------- 10. Balance check verdict ----------
    out["balance_vol_ratio_event_over_control"] = {
        t: round(b["event_median_trailing5_vol"] / b["control_median_trailing5_vol"], 3)
        for t, b in res["balance_check"].items()
        if b.get("event_median_trailing5_vol") and b.get("control_median_trailing5_vol")}

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
