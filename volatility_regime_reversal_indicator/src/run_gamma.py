"""Phase-GAMMA CONFIRMATORY run: score the frozen dealer-gamma (tops) and dark-pool-dix
(bottoms) constructions through the reused opportunity-set null + out-of-sample battery, the
QQQ cross-asset transfer (THE binding constraint that killed Phase 2/3), the benchmark battle
(G6) and the alert budget (G7), and write backtest/PHASE-GAMMA-REPORT.md.

    python3 -m src.run_gamma

Reads the FROZEN backtest/preregistration_gamma.yaml. Constructions/thresholds are round
canonical values (gex<0, 0.20/0.90 percentiles, 20/50-day MAs), NOT re-tuned. A NO-GO ships the
tool descriptive-only — an honest, likely outcome. Verdict is reported PER SIDE (tops vs bottoms).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from .backtest import phase2 as P2
from .backtest import phase3 as P3
from .backtest.base_rate import vol_regime_labels
from .backtest.event_study import forward_event_hits
from .config import project_root
from .data import store
from .signals import conditions_gamma as CG
from .signals import conditions_phase2 as C2

# SQZ carries the dealer-gamma (gex) + dark-pool (dix) feed — the only NEW columns vs Phase 3.
_ALL = ["SPY", "QQQ", "RSP", "QQQE", "HYG", "LQD", "TLT",
        "VIX", "VIX3M", "VVIX", "VXN", "SKEW", "BAA10Y", "ABINYSE", "SQZ"]


def _pre() -> dict:
    return yaml.safe_load((project_root() / "backtest" / "preregistration_gamma.yaml").read_text())


def _f(x, nd=3):
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def _window_masks(panel, pre):
    cwin = pre["out_of_sample"]["temporal_holdout"]["confirm_window"]
    dwin = pre["out_of_sample"]["temporal_holdout"]["discover_window"]
    cmask = np.asarray((panel.index >= pd.Timestamp(cwin[0])) & (panel.index <= pd.Timestamp(cwin[1])))
    dmask = np.asarray((panel.index >= pd.Timestamp(dwin[0])) & (panel.index <= pd.Timestamp(dwin[1])))
    return dmask, cmask


def _qqq_transfer(panel, fn, side, seed_offset):
    """Cross-asset transfer: re-map QQQ price into the SPY slot (gex/dix stay market-wide), then
    re-run the SAME construction and score against QQQ's OWN opportunity-set null. No re-tuning."""
    qpanel = P2.qqq_view(panel)
    qhits, _, _ = forward_event_hits(qpanel, [8, 15], P2.EVENT_WINDOW)
    qregime = vol_regime_labels(qpanel)
    qsig = fn(qpanel)
    qhit = qhits[(side, 8)].to_numpy()
    qelig = (C2.eligible_top(qpanel) if side == "top" else C2.eligible_bottom(qpanel)).to_numpy()
    qep = np.flatnonzero(P2.collapse_episodes(qsig, P2.EP_WINDOW).to_numpy())
    return P2.opportunity_set_null(qhit, qep, qelig, qregime, seed_offset=seed_offset)


def main() -> None:
    pre = _pre()
    panel = store.load_panel(_ALL, start=pre["meta"]["backtest_start"],
                             end=pre["meta"].get("backtest_end"))
    hits, _, _ = forward_event_hits(panel, [8, 15], P2.EVENT_WINDOW)
    regime = vol_regime_labels(panel)
    # in-window subset of the 12 enumerated tops. searchsorted CLAMPS a pre-window peak to the
    # first row, so exclude any episode whose true peak date precedes the SQZ start (else the
    # 2010-04 + 2011-04 tops would be falsely counted as in-window at 2011-05-02).
    win_start = panel.index.min()
    eps_top = P2._episode_positions(panel.index, pre["target_events"]["episode_list_top_8pct"])
    eps_top = [e for e in eps_top if pd.Timestamp(e["peak"]) >= win_start]
    eps_bot: list = []

    cons = CG.build_constructions()
    by_name = {c.name: c for c in cons}
    rows = [P2.score_construction(c, panel, hits, regime, eps_top, eps_bot, seed_offset=i)
            for i, c in enumerate(cons)]

    tops = [r for r in rows if r["side"] == "top" and r["role"] in ("primary", "variant")]
    bots = [r for r in rows if r["side"] == "bottom" and r["role"] in ("primary", "variant")]
    best_top = max(tops, key=lambda r: (r["edge"] if np.isfinite(r["edge"]) else -9))
    best_bot = max(bots, key=lambda r: (r["edge"] if np.isfinite(r["edge"]) else -9))

    dmask, cmask = _window_masks(panel, pre)

    # ---- TOP out-of-sample battery ----
    bt = by_name[best_top["name"]]
    sig_t = bt.fn(panel)
    hit_t = hits[("top", 8)].to_numpy()
    elig_t = C2.eligible_top(panel).to_numpy()
    confirm_t = P2._precision_in_window(sig_t, hit_t, elig_t, regime, cmask, 200)
    discover_t = P2._precision_in_window(sig_t, hit_t, elig_t, regime, dmask, 201)
    qres_t = _qqq_transfer(panel, bt.fn, "top", 300)
    loeo = P2.leave_one_episode_out(sig_t, hit_t, elig_t, regime, eps_top)

    # ---- BOTTOM out-of-sample battery ----
    bb = by_name[best_bot["name"]]
    sig_b = bb.fn(panel)
    hit_b = hits[("bottom", 8)].to_numpy()
    elig_b = C2.eligible_bottom(panel).to_numpy()
    confirm_b = P2._precision_in_window(sig_b, hit_b, elig_b, regime, cmask, 400)
    discover_b = P2._precision_in_window(sig_b, hit_b, elig_b, regime, dmask, 401)
    qres_b = _qqq_transfer(panel, bb.fn, "bottom", 500)

    # ---- shared: max-stat reality across the frozen confirmatory grid (primary+variant only) ----
    grid = [by_name[r["name"]] for r in tops + bots]
    reality = P2.max_stat_reality(grid, panel, hits, regime)

    # ---- G5 stack-beats-parts ----
    # top gated vs its control (neg_gamma_only); bottom gated vs its control (dix_only)
    g5_top = P3.beats_benchmark(panel, hits, bt.fn, by_name["ctl_neg_gamma_only"].fn, "top", 600)
    g5_bot = P3.beats_benchmark(panel, hits, bb.fn, by_name["ctl_dix_only"].fn, "bottom", 601)

    # ---- G6 benchmark battle, both sides ----
    b6_top = P3.beats_benchmark(panel, hits, bt.fn, by_name["bench_top_200"].fn, "top", 700)
    b6_bot = P3.beats_benchmark(panel, hits, bb.fn, by_name["bench_bot_200"].fn, "bottom", 701)

    # ---- G7 alert budget, both sides ----
    ab = pre["alert_budget"]
    bud_top = P3.alert_budget_compliance(sig_t, panel.index, ab["tops_per_year"]["min"], ab["tops_per_year"]["max"])
    bud_bot = P3.alert_budget_compliance(sig_b, panel.index, ab["bottoms_per_year"]["min"], ab["bottoms_per_year"]["max"])

    # ---- KILL-GATE (per side) ----
    min_edge = pre["min_effect_size"]["precision_edge_pp"] / 100.0
    alpha = pre["min_effect_size"]["alpha"]
    recall_floor = pre["min_effect_size"]["recall_floor_organic"]

    g2 = bool(np.isfinite(reality["reality_p"]) and reality["reality_p"] < alpha)

    g1_t = bool(np.isfinite(best_top["edge"]) and best_top["edge"] >= min_edge and best_top["null_p"] < alpha)
    g3_t = bool(confirm_t["edge"] > 0 and qres_t["edge"] > 0 and qres_t["null_p"] < alpha
                and loeo["no_single_collapse"])
    g4_t = bool(best_top["recall_n_caught_organic"] >= recall_floor)
    g5_t = bool(g5_top["beats"])
    g6_t = bool(b6_top["beats"])
    g7_t = bool(bud_top["within_cap"])
    TOP_GO = g1_t and g2 and g3_t and g4_t and g5_t and g6_t and g7_t

    g1_b = bool(np.isfinite(best_bot["edge"]) and best_bot["edge"] >= min_edge and best_bot["null_p"] < alpha)
    g3_b = bool(confirm_b["edge"] > 0 and qres_b["edge"] > 0 and qres_b["null_p"] < alpha)
    g5_b = bool(g5_bot["beats"])
    g6_b = bool(b6_bot["beats"])
    g7_b = bool(bud_bot["within_cap"])
    BOT_GO = g1_b and g2 and g3_b and g5_b and g6_b and g7_b

    overall = TOP_GO or BOT_GO

    # ---- report ----
    L: list[str] = []
    L.append("# Phase-GAMMA Detector — CONFIRMATORY Report (dealer-gamma tops / dark-pool-dix bottoms)\n")
    L.append(f"- panel: {panel.shape[0]} rows, {panel.index.min().date()}..{panel.index.max().date()}")
    L.append("- frozen contract: backtest/preregistration_gamma.yaml (builds on the Phase-3 NO-GO; round canonical thresholds, NOT re-tuned)")
    L.append(f"- in-window enumerated tops scored: {len(eps_top)} of 12 (SQZ starts 2011-05-02 — pre-2011-05 tops not covered)")
    L.append(f"- 8% top base rate (all days): {_f(best_top['all_days_base'])} | bottom base: {_f(best_bot['all_days_base'])}")
    L.append("- HONESTY: raw ratios lead; an opportunity-set null_p in [0.05,0.10] is SUGGESTIVE only.")
    L.append("  Dealer gamma (gex) is the ONE genuinely-new, NON-VIX-derived free input; the make-or-break")
    L.append("  test is the QQQ cross-asset transfer — the constraint that killed Phases 2 and 3.\n")

    L.append("## Per-construction precision vs OPPORTUNITY-SET null (the hard null)\n")
    L.append("| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['name']} | {r['side']} | {r['role']} | {r['n_ep']} | {r['tp']} | "
                 f"{_f(r['precision'])} | {_f(r['elig_base'])} | {_f(r['edge'])} | "
                 f"{_f(r['null_p'])} | {_f(r['all_days_base'])} |")

    L.append("\n## Recall over the enumerated tops (raw counts — the honest headline)\n")
    L.append(f"| construction | caught (all/{len(eps_top)} in-window) | caught organic | caught distribution |")
    L.append("|---|---|---|---|")
    for r in rows:
        if r["side"] == "top":
            L.append(f"| {r['name']} | {r['recall_n_caught']}/{len(eps_top)} | "
                     f"{r['recall_n_caught_organic']} | {r['recall_n_caught_distribution']} |")

    L.append(f"\n## Best top construction: **{best_top['name']}**  (best of {len(tops)} by opportunity-set edge)\n")
    L.append(f"- precision {_f(best_top['precision'])} vs eligible-base {_f(best_top['elig_base'])} "
             f"= edge {_f(best_top['edge'])} pp; opportunity-set null_p = **{_f(best_top['null_p'])}**")
    L.append(f"- raw: {best_top['tp']} of {best_top['n_ep']} alerts preceded a >=8% top; "
             f"caught {best_top['recall_n_caught_organic']} organic tops")
    L.append(f"- TEMPORAL hold-out — discover(2011-21) edge {_f(discover_t['edge'])} (p {_f(discover_t['null_p'])}, n={discover_t['n_ep']}) "
             f"| CONFIRM(2022-26) edge {_f(confirm_t['edge'])} (p {_f(confirm_t['null_p'])}, n={confirm_t['n_ep']})")
    L.append(f"- **CROSS-ASSET transfer to QQQ (THE BINDING CONSTRAINT) — edge {_f(qres_t['edge'])}, null_p {_f(qres_t['null_p'])}, n={qres_t['n_ep']}**")
    L.append(f"- LEAVE-ONE-EPISODE-OUT — full precision {_f(loeo['full_precision'])}, base {_f(loeo['base'])}, "
             f"max single-episode precision drop {_f(loeo['max_leverage_drop'])}, "
             f"no-single-collapse={loeo['no_single_collapse']}")

    L.append(f"\n## Best bottom construction: **{best_bot['name']}**  (best of {len(bots)} by opportunity-set edge)\n")
    L.append(f"- precision {_f(best_bot['precision'])} vs eligible-base {_f(best_bot['elig_base'])} "
             f"= edge {_f(best_bot['edge'])} pp; opportunity-set null_p = **{_f(best_bot['null_p'])}**; "
             f"raw {best_bot['tp']}/{best_bot['n_ep']}")
    L.append(f"- TEMPORAL hold-out — discover edge {_f(discover_b['edge'])} (p {_f(discover_b['null_p'])}, n={discover_b['n_ep']}) "
             f"| CONFIRM edge {_f(confirm_b['edge'])} (p {_f(confirm_b['null_p'])}, n={confirm_b['n_ep']})")
    L.append(f"- **CROSS-ASSET transfer to QQQ — edge {_f(qres_b['edge'])}, null_p {_f(qres_b['null_p'])}, n={qres_b['n_ep']}**")

    L.append("\n## Controls / stack-beats-parts (G5) — does the trigger/sequence matter, matched count?\n")
    L.append(f"- TOP gated vs ctl_neg_gamma_only: detector prec {_f(g5_top['detector_precision'])} (n={g5_top['detector_n']}) vs "
             f"control {_f(g5_top['bench_precision'])} (n={g5_top['bench_n']}); diff_p05 {_f(g5_top['diff_p05'])} -> beats={g5_top['beats']}")
    L.append(f"- BOTTOM gated vs ctl_dix_only: detector prec {_f(g5_bot['detector_precision'])} (n={g5_bot['detector_n']}) vs "
             f"control {_f(g5_bot['bench_precision'])} (n={g5_bot['bench_n']}); diff_p05 {_f(g5_bot['diff_p05'])} -> beats={g5_bot['beats']}")

    L.append("\n## Confirmatory MULTIPLE-TESTING reality check\n")
    L.append(f"- max-stat reality_p across {reality['cells']} frozen cells (opportunity-set null): "
             f"**{_f(reality['reality_p'])}** (V_obs={_f(reality['v_obs'])})")

    L.append("\n## Benchmark battle (G6) — detector vs the late-but-robust 200-day trend baseline, matched count\n")
    L.append(f"- TOP: {best_top['name']} precision {_f(b6_top['detector_precision'])} (n={b6_top['detector_n']}) vs "
             f"bench_top_200 {_f(b6_top['bench_precision'])} (n={b6_top['bench_n']}); diff_p05 {_f(b6_top['diff_p05'])} -> beats={b6_top['beats']}")
    L.append(f"- BOTTOM: {best_bot['name']} precision {_f(b6_bot['detector_precision'])} (n={b6_bot['detector_n']}) vs "
             f"bench_bot_200 {_f(b6_bot['bench_precision'])} (n={b6_bot['bench_n']}); diff_p05 {_f(b6_bot['diff_p05'])} -> beats={b6_bot['beats']}")

    L.append("\n## Alert budget (G7) — collapsed episodes/year vs the pre-registered cap\n")
    L.append(f"- TOP: {_f(bud_top['episodes_per_year'],2)}/yr (cap {bud_top['cap']}, min {bud_top['min']}) "
             f"within_cap={bud_top['within_cap']} above_min={bud_top['above_min']}")
    L.append(f"- BOTTOM: {_f(bud_bot['episodes_per_year'],2)}/yr (cap {bud_bot['cap']}, min {bud_bot['min']}) "
             f"within_cap={bud_bot['within_cap']} above_min={bud_bot['above_min']}")

    L.append("\n## KILL-GATE (Phase-GAMMA, per side)\n")
    L.append(f"- **TOP VERDICT: {'GO' if TOP_GO else 'NO-GO'}**  |  **BOTTOM VERDICT: {'GO' if BOT_GO else 'NO-GO'}**  |  overall: {'GO' if overall else 'NO-GO'}")
    L.append(f"- G1 precision floor (>= base+{min_edge*100:.0f}pp AND oppset p<{alpha}): top={g1_t} (edge {_f(best_top['edge'])}, p {_f(best_top['null_p'])}) | bottom={g1_b} (edge {_f(best_bot['edge'])}, p {_f(best_bot['null_p'])})")
    L.append(f"- G2 confirmatory MTC (reality_p<{alpha}): {g2} (reality_p {_f(reality['reality_p'])})")
    L.append(f"- G3 out-of-sample (confirm>0 AND QQQ beats null [AND top LOEO no-collapse]): top={g3_t} | bottom={g3_b}")
    L.append(f"  - QQQ-transfer detail: top edge {_f(qres_t['edge'])} p {_f(qres_t['null_p'])} | bottom edge {_f(qres_b['edge'])} p {_f(qres_b['null_p'])}")
    L.append(f"- G4 recall floor (top only, >= {recall_floor} organic in-window): {g4_t} ({best_top['recall_n_caught_organic']} organic)")
    L.append(f"- G5 stack beats parts (matched): top vs neg_gamma_only={g5_t} | bottom vs dix_only={g5_b}")
    L.append(f"- G6 benchmark battle (beats 200-day baseline): top={g6_t} | bottom={g6_b}")
    L.append(f"- G7 alert budget (within cap): top={g7_t} | bottom={g7_b}")
    if not overall:
        L.append("\n> NO-GO (both sides) = **no demonstrably-validated edge**. Ship DESCRIPTIVE-ONLY "
                 "(display where dealer gamma / dark-pool dix stand today; no predictive-confidence "
                 "claim, no live alert). This is the honest outcome the pre-registration anticipated: "
                 "dealer gamma was the last free, non-VIX lever — if it does not transfer to QQQ or "
                 "beat the regime-matched base, the free-data search for a validated TOP/BOTTOM "
                 "detector is exhausted, and the next attempt needs paid decomposed-surface data.")
    elif not TOP_GO:
        L.append("\n> TOP side NO-GO -> ship the dealer-gamma fragility readout DESCRIPTIVE-ONLY. "
                 "BOTTOM side GO -> may ship per its alert budget after a live shadow check.")
    elif not BOT_GO:
        L.append("\n> BOTTOM side NO-GO -> descriptive-only. TOP side GO -> may ship per its alert "
                 "budget after a live shadow check.")

    report = "\n".join(L) + "\n"
    out = project_root() / "backtest" / "PHASE-GAMMA-REPORT.md"
    out.write_text(report)
    print(report)
    print(f"[report written to {out}]")


if __name__ == "__main__":
    main()
