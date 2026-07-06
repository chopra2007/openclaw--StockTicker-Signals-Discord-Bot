"""CLI: `python -m consensus_engine.eval [--db PATH] [--out PATH]`.

Read-only. Runs every eval section, writes a markdown report, and prints a
one-screen summary of the decision-relevant numbers.
"""

from __future__ import annotations

import argparse
import os

from consensus_engine.eval import loaders, report


def _f(x, nd=3):
    try:
        if x != x:
            return "nan"
        return f"{x:.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def main() -> None:
    default_out = os.path.join(
        os.path.dirname(loaders.DEFAULT_DB),
        ".omc", "plans", "bot-research-build", "eval-report.md",
    )
    ap = argparse.ArgumentParser(prog="python -m consensus_engine.eval")
    ap.add_argument("--db", default=loaders.DEFAULT_DB, help="path to consensus.db (read-only)")
    ap.add_argument("--out", default=default_out, help="markdown report output path")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    res = report.run(args.db, args.out)
    s = res["sections"]

    print("=" * 72)
    print("EVAL SUMMARY (read-only)")
    print("=" * 72)

    print("\n[1] Label audit — correct (resolved-only) vs naive rate:")
    for t in s["label_audit"]["tables"]:
        for r in t["per_horizon"]:
            print(f"    {t['name']:20s} {r['horizon']:>3s}: correct={_f(r['correct_rate'])} "
                  f"naive={_f(r['naive_rate'])} (resolved {r['resolved']}, NULL {r['null']})")

    print("\n[2] Calibration held-out Brier (lower=better):")
    for h, d in s["calibration"]["horizons"].items():
        if "raw" not in d:
            continue
        print(f"    {h}: incumbent={_f(d['raw']['brier'])} base-rate={_f(d['raw']['base_rate_brier'])} "
              f"isotonic={_f(d['isotonic_test_brier'])} beta={_f(d['beta_test_brier'])}")

    print("\n[3] Discrimination (final_score AUC):")
    for h, d in s["discrimination"]["horizons"].items():
        if "auc" in d:
            print(f"    {h}: AUC={_f(d['auc'])} top-decile-lift={_f(d['top_decile_lift'])} "
                  f"base={_f(d['base_rate'])} n={d['n']}")

    print("\n[3b] Edge pockets (Wilson-LB > 0.50, n >= min):")
    found = False
    for h, d in s["edge_pockets"]["horizons"].items():
        for r in d["edge_found"]:
            found = True
            print(f"    {h}: {r['slice']} hit={_f(r['hit_rate'])} WLB={_f(r['wilson_lb'])} n={r['n']}")
    if not found:
        print("    NONE — no subgroup beats a coin flip with confidence.")

    print("\n[4] Logistic challenger vs incumbent:")
    lc = s["logistic"]
    for h, d in lc.get("horizons", {}).items():
        if "verdict" in d:
            print(f"    {h}: {d['verdict']} "
                  f"(inc Brier {_f(d['incumbent']['brier'])} / chal {_f(d['challenger']['brier'])}; "
                  f"inc AUC {_f(d['incumbent']['auc'])} / chal {_f(d['challenger']['auc'])})")
        else:
            print(f"    {h}: {d.get('note')}")

    print("\n[5] Top univariate ICs (24h):")
    ps = s["per_signal"]
    if "ics" in ps:
        for r in ps["ics"][:6]:
            print(f"    {r['feature']:24s} IC={_f(r['spearman_ic'])}")

    print("\n[6a] Display signals logged? " + s["data_availability"]["6a_display_signals"]["verdict"])
    print("[6b] " + s["data_availability"]["6b_source_performance"]["verdict"])

    print(f"\nFull report written to: {args.out}")


if __name__ == "__main__":
    main()
