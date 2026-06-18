"""Phase-1 research run: ablation + kill-gate verdict on the populated store.

    python3 -m src.run_ablation --ticker SPY

Reads the FROZEN backtest/preregistration.yaml, runs the honest event-study
ablation, evaluates the 5-part kill-gate, and writes backtest/ABLATION-REPORT.md.
This is a research run — there is no flag to flip and nothing user-facing changes.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .backtest.ablation import evaluate_kill_gate, run_full_ablation
from .backtest.base_rate import edge_and_null
from .backtest.event_study import event_side, forward_atr_move
from .backtest.metrics import (concentration_regime, coverage_buckets,
                              coverage_pct, distribution_tails)
from .config import project_root
from .data import store

_ALL = ["SPY", "QQQ", "RSP", "QQQE", "HYG", "LQD", "TLT",
        "VIX", "VIX3M", "VVIX", "VXN", "SKEW", "BAA10Y"]
_KEY_INPUTS = ["SPY_close", "VIX_close", "VIX3M_close", "VVIX_close", "RSP_close",
               "BAA10Y_value", "TLT_close", "SKEW_close"]


def _load_pre() -> dict:
    return yaml.safe_load((project_root() / "backtest" / "preregistration.yaml").read_text())


def per_tier_hit_table(res: dict) -> pd.DataFrame:
    """For every condition, per-tier hit-rate (conditional) vs base rate + false-alarm."""
    pre_tiers = res["tiers"]
    hits, regime = res["hits"], res["regime"]
    rows = []
    for i, (name, pc) in enumerate(res["per_cond"].items()):
        ev = event_side(pc["side"])
        ep_pos = pc["ep_pos"]
        for tier in pre_tiers:
            h = hits[(ev, tier)].to_numpy()
            valid = np.isfinite(h)
            # same seed as the ablation grid hit-cells -> the two tables agree exactly
            r = edge_and_null(h, ep_pos, regime, 1.0, valid, seed_offset=1000 * (i + 1) + tier)
            cond = r["cond_mean"]
            rows.append({
                "name": name, "event_side": ev, "tier_pct": tier,
                "n_episodes": r["n_episodes"], "hit_rate": cond,
                "base_rate": r["uncond_mean"],
                "edge_pp": (r["edge"] * 100.0) if np.isfinite(r["edge"]) else np.nan,
                "false_alarm_rate": (1.0 - cond) if np.isfinite(cond) else np.nan,
                "null_p": r["null_p"],
            })
    return pd.DataFrame(rows)


def _fmt(x, nd=4):
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.ticker.upper() != "SPY":
        print(f"Phase 1 is SPY only; {args.ticker} is Phase 2 (not built). Exiting.")
        return
    if not store.series_exists("SPY"):
        print("store empty — run `python3 -m src.run_update` first.")
        return

    pre = _load_pre()
    panel = store.load_panel(_ALL, start=pre["meta"]["backtest_start"])
    print(f"panel: {panel.shape[0]} rows {panel.index.min().date()}..{panel.index.max().date()}")

    res = run_full_ablation(panel, pre)
    gate = evaluate_kill_gate(res, pre)
    tier_tbl = per_tier_hit_table(res)

    # coverage stratification note
    cov = coverage_pct(panel, _KEY_INPUTS)
    cov_dist = coverage_buckets(cov).value_counts().to_dict()

    t = res["table"].sort_values("edge", ascending=False)
    lines: list[str] = []
    lines.append("# Phase-1 Ablation & Kill-Gate Report — SPY\n")
    lines.append(f"- panel: {panel.shape[0]} rows, "
                 f"{panel.index.min().date()}..{panel.index.max().date()}")
    lines.append(f"- grid cells tested: {res['grid_cells']} "
                 f"(reality-check max-stat p = {_fmt(res['reality_p'],4)})")
    lines.append(f"- coverage buckets (days): {cov_dist}")
    lines.append(f"- primary horizon = {res['primary_h']}d; primary tier = {res['primary_tier']}%\n")

    lines.append("## Per-condition ablation (primary = 20d forward-return edge, sign-adjusted)\n")
    lines.append("| condition | family | side | N ep | edge(20d) | null_p | BH | stable(folds) | hit8 edge pp | hit8 p |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in t.iterrows():
        lines.append(
            f"| {r['name']} | {r['family']} | {r['side']} | {r['n_episodes']} | "
            f"{_fmt(r['edge'])} | {_fmt(r['null_p'],3)} | {'Y' if r['bh_survive'] else '·'} | "
            f"{'Y' if r['stable'] else '·'}({r['fold_pos']}+/{r['fold_neg']}-) | "
            f"{_fmt(r['hit_edge_pp'],1)} | {_fmt(r['hit_p'],3)} |")

    lines.append("\n## Per-tier hit-rate vs base-rate (false-alarm) — the user's target\n")
    lines.append("Top conditions ranked by 8% (primary) tier edge:\n")
    top8 = tier_tbl[(tier_tbl["tier_pct"] == res["primary_tier"])].sort_values("edge_pp", ascending=False)
    lines.append("| condition | event | N ep | tier | hit_rate | base_rate | edge pp | false-alarm | null_p |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in top8.head(12).iterrows():
        full = tier_tbl[(tier_tbl["name"] == r["name"])]
        for _, rr in full.iterrows():
            lines.append(
                f"| {rr['name']} | {rr['event_side']} | {rr['n_episodes']} | {rr['tier_pct']}% | "
                f"{_fmt(rr['hit_rate'],3)} | {_fmt(rr['base_rate'],3)} | {_fmt(rr['edge_pp'],1)} | "
                f"{_fmt(rr['false_alarm_rate'],3)} | {_fmt(rr['null_p'],3)} |")

    # forward-return distribution + tails + ATR-scaling (final-plan.md 6.1)
    fwd20 = res["fwd_arr"][res["primary_h"]]
    atr_move = forward_atr_move(panel, res["primary_h"]).to_numpy()
    lines.append(f"\n## Forward-return distribution, tails & ATR-scaling ({res['primary_h']}d)\n")
    ut = distribution_tails(fwd20)
    lines.append(f"- unconditional 20d fwd return: mean={_fmt(ut.get('mean'))}, "
                 f"median={_fmt(ut.get('median'))}, p05={_fmt(ut.get('p05'))}, "
                 f"p95={_fmt(ut.get('p95'))}, min={_fmt(ut.get('min'))}, max={_fmt(ut.get('max'))}")
    at = distribution_tails(atr_move)
    lines.append(f"- unconditional 20d move in ATR units: mean={_fmt(at.get('mean'),2)}, "
                 f"p05={_fmt(at.get('p05'),2)}, p95={_fmt(at.get('p95'),2)}")
    lines.append("- conditional tails for the 3 strongest-|edge| conditions:")
    top3 = res["table"].reindex(res["table"]["edge"].abs().sort_values(ascending=False).index).head(3)
    for _, r in top3.iterrows():
        ep = res["per_cond"][r["name"]]["ep_pos"]
        ct = distribution_tails(fwd20[ep])
        lines.append(f"  - {r['name']}: n={ct.get('n')}, mean={_fmt(ct.get('mean'))}, "
                     f"p05={_fmt(ct.get('p05'))}, p95={_fmt(ct.get('p95'))}")

    # concentration-regime stratification (final-plan.md 6.9) — the 2023-24 breadth trap
    conc = concentration_regime(panel).to_numpy()
    narrowing = conc < 0
    lines.append("\n## Concentration-regime check (breadth narrowing vs broadening)\n")
    for name in [n for n in res["per_cond"] if "breadth_break_top" in n]:
        pc = res["per_cond"][name]
        ep = pc["ep_pos"]
        h8 = res["hits"][(event_side(pc["side"]), res["primary_tier"])].to_numpy()
        ep_n = [p for p in ep if narrowing[p] and np.isfinite(h8[p])]
        ep_b = [p for p in ep if (not narrowing[p]) and np.isfinite(h8[p])]
        hn = float(np.mean([h8[p] for p in ep_n])) if ep_n else np.nan
        hb = float(np.mean([h8[p] for p in ep_b])) if ep_b else np.nan
        lines.append(f"- {name}: 8% hit-rate when breadth NARROWING={_fmt(hn,3)} "
                     f"(n={len(ep_n)}) vs BROADENING={_fmt(hb,3)} (n={len(ep_b)})")

    lines.append("\n## Collinearity / VIF (top 12)\n")
    lines.append("| condition | VIF |")
    lines.append("|---|---|")
    for name, row in res["vif"].head(12).iterrows():
        lines.append(f"| {name} | {_fmt(row['vif'],2)} |")

    lines.append("\n## KILL-GATE\n")
    g = gate
    lines.append(f"- **VERDICT: {g['verdict']}**")
    lines.append(f"- gate 1 (>=3 independent families): {g['gate1_families_ge3']} "
                 f"-> families={g['survivor_families']}")
    lines.append(f"- gate 2 (positive edge survives MTC): {g['gate2_edge_survives_mtc']} "
                 f"(reality_p={_fmt(g['reality_p'],4)}, BH+ survivors={g['n_bh_positive_survivors']})")
    lines.append(f"- gate 3 (directional fold-stability): {g['gate3_fold_stable']} "
                 f"(stable survivors={g['n_stable']})")
    lines.append(f"- gate 4 (edge >= min effect size {res['min_eff']*100:.1f}%): {g['gate4_min_effect']}")
    lines.append(f"- gate 5 (combined beats best single): {g['gate5_combined_beats_single']} "
                 f"-> {g['combined']}")
    lines.append(f"- final survivors: {g['final_survivors']}")
    if g["verdict"] == "FAIL":
        lines.append("\n> FAIL = **no demonstrable edge**. This is a successful, honest "
                     "research outcome (final-plan.md 2): it saves the Phase 2/3 weeks. "
                     "Do NOT build a live tool on an unproven signal.")

    report = "\n".join(lines) + "\n"
    out = Path(args.out) if args.out else (project_root() / "backtest" / "ABLATION-REPORT.md")
    out.write_text(report)
    print(report)
    print(f"\n[report written to {out}]")


if __name__ == "__main__":
    main()
