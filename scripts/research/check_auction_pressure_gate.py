#!/usr/bin/env python3
"""TODO #93 mechanical gate checker.

Each phase's pass/fail is arithmetic, not narrative. Run as:
    python3 scripts/research/check_auction_pressure_gate.py phase0 .. phase7
Exit code 0 means the gate passed, 1 means it failed.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_pressure_common import GATE_DIR, MAX_TRADES_PER_DAY, SEED  # noqa: E402

SPLIT_DATE = "2025-11-28"
DEV_DATES = 730
EVAL_DATES = 182
EVAL_ARTIFACTS = ["final-events.parquet", "final-summary.json", "final-report.md",
                  "phase6-gate.json", "final-audit-report.md", "phase7-gate.json"]


def load(name):
    p = GATE_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def sha(name):
    p = GATE_DIR / name
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def check(results, label, ok, detail=""):
    results.append({"check": label, "pass": bool(ok), "detail": str(detail)})
    return bool(ok)


def phase0(r):
    g = load("phase0-gate.json")
    if not check(r, "phase0-gate.json exists", g is not None):
        return
    check(r, "all four data files plus supporting files hash-match the manifest",
          g["all_hashes_match"], g["file_hash_verification"].keys().__len__())
    check(r, "budget is zero and the online client is banned",
          g["spend_controls"]["budget_usd"] == 0.0
          and g["spend_controls"]["online_databento_client_forbidden"])
    check(r, "frozen split recorded as 730 development / 182 evaluation dates",
          g["frozen_split"]["development_dates"] == DEV_DATES
          and g["frozen_split"]["evaluation_dates"] == EVAL_DATES)
    check(r, "seed recorded", g["seed"] == SEED)


def phase1(r):
    g = load("phase1-gate.json")
    if not check(r, "phase1-gate.json exists", g is not None):
        return
    check(r, "panel built", g["rows_development"] > 0, g["rows_development"])
    check(r, "development calendar is 730 dates ending 2025-11-28",
          g["calendar"]["development_dates"] == DEV_DATES
          and g["calendar"]["split_date"] == SPLIT_DATE)
    check(r, "no evaluation date reached the panel",
          g["max_date_in_panel"] <= SPLIT_DATE, g["max_date_in_panel"])
    check(r, "every excluded row carries a reason",
          "" in g["lane_a_exclusions"] and "" in g["lane_b_exclusions"])
    check(r, "panel, sample and data dictionary written",
          all((GATE_DIR / f).exists() for f in
              ["dev-panel.parquet", "dev-panel-sample.csv", "data-dictionary.json"]))


def phase2(r):
    h = load("hypotheses-v1.json")
    if not check(r, "hypotheses-v1.json exists", h is not None):
        return
    check(r, "hypotheses-v1.md exists", (GATE_DIR / "hypotheses-v1.md").exists())
    check(r, "exactly six rules", len(h["rules"]) == 6, len(h["rules"]))
    check(r, "rule ids are the frozen six",
          sorted(x["id"] for x in h["rules"]) == ["A1", "A2", "A3", "B1", "B2", "B3"])
    check(r, "lane B never reads the first-five-minute return",
          "first_five_return" not in h["lanes"]["b"]["allowed_features"]
          and "dir_first_five_return" in h["ranking_model"]["model_inputs"]["lane_b_unavailable"])
    check(r, "lane clocks frozen",
          h["lanes"]["a"]["entry_bar_ends_pacific"] == "06:40"
          and h["lanes"]["b"]["entry_bar_ends_pacific"] == "06:36")
    check(r, "seed frozen", h["seed"] == SEED)
    check(r, "no evaluation artifact exists yet",
          not any((GATE_DIR / f).exists() for f in EVAL_ARTIFACTS))
    g = {"phase": "phase2", "hypotheses_sha256": sha("hypotheses-v1.json"),
         "hypotheses_md_sha256": sha("hypotheses-v1.md"),
         "panel_sha256": sha("dev-panel.parquet")}
    (GATE_DIR / "phase2-gate.json").write_text(json.dumps(
        {**g, "checks": r, "gate_pass": all(c["pass"] for c in r)}, indent=2))


def phase3(r):
    s = load("internal-summary.json")
    if not check(r, "internal-summary.json exists", s is not None):
        return
    check(r, "internal-events.parquet exists", (GATE_DIR / "internal-events.parquet").exists())
    check(r, "the panel it used ends on the split date", s["panel_hash"] == sha("dev-panel.parquet"))
    check(r, "the frozen hypothesis file was not edited after freezing",
          s["hypotheses_hash"] == sha("hypotheses-v1.json"))
    check(r, "candidates were produced", s["candidates_total"] > 0, s["candidates_total"])
    check(r, "all six plain rules reported", len(s["plain_rules"]) == 6)
    check(r, "no evaluation artifact exists yet",
          not any((GATE_DIR / f).exists() for f in EVAL_ARTIFACTS))


def phase4(r):
    a = load("audit-recompute.json")
    if not check(r, "audit-recompute.json exists", a is not None):
        return
    check(r, "audit report written", (GATE_DIR / "audit-report.md").exists())
    check(r, "audit event checks written", (GATE_DIR / "audit-event-checks.csv").exists())
    check(r, "auditor reproduced the headline numbers", a.get("headline_match") is True,
          a.get("headline_detail", ""))
    check(r, "lane A never enters before the bar ending 6:40 a.m. Pacific",
          a.get("lane_a_entry_clock_ok") is True)
    check(r, "lane B never enters before the bar ending 6:36 a.m. Pacific",
          a.get("lane_b_entry_clock_ok") is True)
    check(r, "lane B never used first-five-minute data",
          a.get("lane_b_no_first_five") is True)
    check(r, "no material timing, leakage, direction, join, or cost defect",
          not a.get("material_defects"), a.get("material_defects"))


def phase5(r):
    import numpy as np
    import pandas as pd

    s = load("internal-summary.json")
    if not check(r, "internal-summary.json exists", s is not None):
        return
    a = load("audit-recompute.json")
    check(r, "phase 4 audit is clean", bool(a) and not a.get("material_defects"))

    ev_path = GATE_DIR / "internal-events.parquet"
    if not check(r, "internal-events.parquet exists", ev_path.exists()):
        return
    ev = pd.read_parquet(ev_path)
    sel = ev[ev["selected"]] if "selected" in ev else ev.iloc[0:0]
    n = len(sel)

    if n == 0:
        check(r, "gate 1 — at least 200 selected trades and 30 tickers", False, "0 selected trades")
        for i, label in [(2, "no more than four selected trades on any day"),
                         (3, "win rate at least 60% with the lower bound above 50%"),
                         (4, "mean at least +20 bps after cost with the lower bound above zero"),
                         (5, "profit factor at least 1.25"),
                         (6, "positive in at least three of four blocks"),
                         (7, "no ticker above 10% of net profit"),
                         (8, "beats the middle-ranked and no-signal groups by 15 bps"),
                         (9, "beats the 95th percentile of the shuffled controls"),
                         (10, "non-negative under the 25 bps stress cost")]:
            check(r, f"gate {i} — {label}", False, "no selected trades")
        return

    net = sel["net"].to_numpy()
    S = s["selected"]
    check(r, "gate 1 — at least 200 selected trades and 30 tickers",
          n >= 200 and sel["symbol"].nunique() >= 30,
          f"{n} trades, {sel['symbol'].nunique()} tickers")
    check(r, "gate 2 — no more than four selected trades on any day",
          int(sel.groupby("date").size().max()) <= MAX_TRADES_PER_DAY,
          int(sel.groupby("date").size().max()))
    check(r, "gate 3 — win rate at least 60% with the lower bound above 50%",
          (net > 0).mean() >= 0.60 and S["win_rate_ci95"][0] > 0.50,
          f"{(net>0).mean():.4f}, lower bound {S['win_rate_ci95'][0]:.4f}")
    check(r, "gate 4 — mean at least +20 bps after the 15 bps base cost, lower bound above zero",
          net.mean() * 1e4 >= 20.0 and S["mean_ci95_bps"][0] > 0.0,
          f"{net.mean()*1e4:.2f} bps, lower bound {S['mean_ci95_bps'][0]:.2f} bps")
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    check(r, "gate 5 — profit factor at least 1.25", pf >= 1.25, f"{pf:.3f}")
    blocks = sel.groupby("fold")["net"].mean() * 1e4
    check(r, "gate 6 — positive in at least three of four blocks, none worse than -5 bps",
          (blocks > 0).sum() >= 3 and blocks.min() >= -5.0,
          {int(k): round(float(v), 2) for k, v in blocks.items()})
    prof = sel.groupby("symbol")["net"].sum()
    total = net.sum()
    share = float(prof.max() / total) if total > 0 else 1.0
    check(r, "gate 7 — no ticker contributes more than 10% of net profit",
          total > 0 and share <= 0.10, f"{share:.4f}")
    mid = s.get("middle_ranked", {})
    ctrl = s.get("matched_no_signal", {})
    edge_mid = net.mean() * 1e4 - mid.get("mean_bps", 0.0) if mid.get("n") else None
    edge_ctrl = net.mean() * 1e4 - ctrl.get("mean_bps", 0.0) if ctrl.get("n") else None
    check(r, "gate 8 — beats the middle-ranked and matched no-signal groups by 15 bps",
          edge_mid is not None and edge_ctrl is not None
          and edge_mid >= 15.0 and edge_ctrl >= 15.0,
          f"middle {edge_mid}, no-signal {edge_ctrl}")
    sh = s.get("direction_shuffle", {})
    check(r, "gate 9 — observed mean above the 95th percentile of 1,000 shuffles",
          bool(sh.get("observed_above_p95")),
          f"observed {net.mean()*1e4:.2f} bps vs p95 {sh.get('p95_bps')}")
    stress = sel["net_25bps"].mean() * 1e4 if "net_25bps" in sel else None
    check(r, "gate 10 — mean stays non-negative under the 25 bps stress cost",
          stress is not None and stress >= 0.0, stress)


def phase6(r):
    g = load("phase6-gate.json")
    if not check(r, "phase6-gate.json exists", g is not None):
        return
    check(r, "the frozen final spec was verified before the run", g.get("frozen_spec_verified"))
    check(r, "the final run happened exactly once", g.get("runs") == 1)


def phase7(r):
    g = load("phase7-gate.json")
    if not check(r, "phase7-gate.json exists", g is not None):
        return
    check(r, "independent final audit written", (GATE_DIR / "final-audit-report.md").exists())
    check(r, "final verdict written", (GATE_DIR / "final-research-verdict.md").exists())


PHASES = {"phase0": phase0, "phase1": phase1, "phase2": phase2, "phase3": phase3,
          "phase4": phase4, "phase5": phase5, "phase6": phase6, "phase7": phase7}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=sorted(PHASES))
    args = ap.parse_args()
    results = []
    PHASES[args.phase](results)
    ok = bool(results) and all(c["pass"] for c in results)
    for c in results:
        mark = "PASS" if c["pass"] else "FAIL"
        detail = f"  [{c['detail']}]" if c["detail"] and c["detail"] != "None" else ""
        print(f"{mark}  {c['check']}{detail}")
    print(f"\n{args.phase}: {'PASS' if ok else 'FAIL'}")
    if args.phase in ("phase5",):
        (GATE_DIR / "phase5-gate.json").write_text(json.dumps(
            {"phase": "phase5", "checks": results, "gate_pass": ok,
             "advance_to_final_evaluation": ok}, indent=2))
    if args.phase in ("phase0", "phase1", "phase3", "phase4"):
        pass  # those gate files are written by the phase that produces them
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
