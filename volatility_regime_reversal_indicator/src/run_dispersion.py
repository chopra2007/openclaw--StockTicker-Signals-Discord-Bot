"""Phase-DISPERSION CONFIRMATORY run: cross-sectional return dispersion as a TOP precursor.

    python3 -m src.run_dispersion

Tests Maio & Saffi (2016) OOS evidence under the same honesty harness as Phase-2/3/GAMMA:
opportunity-set null, temporal hold-out (2006-2021 discover / 2022-2026 confirm), QQQ cross-
asset transfer (THE binding constraint), leave-one-episode-out, confirmatory MTC reality check,
and a stack-beats-parts (G5) test.

Reads the FROZEN backtest/preregistration_dispersion.yaml. Constructions/thresholds are round
canonical values (0.80 pct trigger, near-high k=0.97), NOT re-tuned. A NO-GO is an honest,
anticipated outcome — ships DESCRIPTIVE-ONLY (display the current dispersion percentile).

SURVIVORSHIP BIAS DISCLOSED: SP500_DISP / NDX_DISP use today's membership applied backward.
Historical dispersion is understated near stress events. Precision is an UPPER BOUND.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
import yaml

from .backtest import phase2 as P2
from .backtest import phase3 as P3
from .backtest.base_rate import vol_regime_labels
from .backtest.event_study import forward_event_hits, collapse_episodes
from .config import project_root
from .data import store
from .signals import conditions_dispersion as CD
from .signals import conditions_phase2 as C2

# Series loaded from the store
_CORE = ["SPY", "QQQ", "RSP", "QQQE", "VIX", "VIX3M", "VVIX", "VXN",
         "SKEW", "BAA10Y", "ABINYSE"]
_DISP_SERIES = ["SP500_DISP", "SP500_DOWN_DISP", "NDX_DISP", "NDX_DOWN_DISP"]


def _pre() -> dict:
    return yaml.safe_load((project_root() / "backtest" / "preregistration_dispersion.yaml").read_text())


def _f(x, nd: int = 3) -> str:
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def _window_masks(panel: pd.DataFrame, pre: dict):
    cwin = pre["out_of_sample"]["temporal_holdout"]["confirm_window"]
    dwin = pre["out_of_sample"]["temporal_holdout"]["discover_window"]
    cmask = np.asarray((panel.index >= pd.Timestamp(cwin[0])) & (panel.index <= pd.Timestamp(cwin[1])))
    dmask = np.asarray((panel.index >= pd.Timestamp(dwin[0])) & (panel.index <= pd.Timestamp(dwin[1])))
    return dmask, cmask


def _qqq_transfer(panel: pd.DataFrame, seed_offset: int) -> dict:
    """Cross-asset transfer: apply the frozen primary SPY dispersion thresholds to QQQ.

    Construction: NDX_DISP percentile >= 0.80 AND SPY near-high (SAME threshold, no re-tuning).
    SPY near-high stays as-is (market regime gate); only the dispersion index changes.
    Scored against QQQ's OWN opportunity-set null (eligible = near-high days, QQQ's returns).
    """
    # Build QQQ view: relabel QQQ->SPY price columns so forward_event_hits uses QQQ prices,
    # but keep the same dispersion columns (NDX_DISP is already the Nasdaq version).
    qpanel = P2.qqq_view(panel)
    # For QQQ transfer: the construction uses NDX_DISP with frozen 0.80 threshold
    # and the SPY near-high gate (the near-high in qpanel refers to the original SPY,
    # but we're assessing QQQ's forward returns; keep SPY price gate consistent with
    # the frozen spec: "SPY near-high gate uses SPY, unchanged").
    # Signal: d_ndx_high_disp_near_high uses NDX_DISP_value + near_high(SPY), no re-tuning.
    qhits, _, _ = forward_event_hits(qpanel, [8, 15], P2.EVENT_WINDOW)
    qregime = vol_regime_labels(qpanel)
    qsig = CD.d_ndx_high_disp_near_high(panel, pct=0.80, window=252, k=0.97)
    qhit = qhits[("top", 8)].to_numpy()
    qelig = C2.eligible_top(qpanel).to_numpy()
    qep = np.flatnonzero(collapse_episodes(qsig, P2.EP_WINDOW).to_numpy())
    return P2.opportunity_set_null(qhit, qep, qelig, qregime, seed_offset=seed_offset)


def main() -> None:
    pre = _pre()

    # Load core series
    missing_disp = [s for s in _DISP_SERIES if not store.series_exists(s)]
    if missing_disp:
        print(f"[FATAL] Missing dispersion series in store: {missing_disp}")
        print("  Run: python3 -m src.data.fetch_constituents  to fetch and cache them.")
        sys.exit(1)

    all_series = _CORE + _DISP_SERIES
    panel = store.load_panel(all_series, start=pre["meta"]["backtest_start"],
                             end=pre["meta"].get("backtest_end"))

    # Check coverage
    disp_col = "SP500_DISP_value"
    n_disp_valid = int(panel[disp_col].notna().sum()) if disp_col in panel.columns else 0
    n_total = len(panel)
    print(f"[INFO] Panel: {n_total} rows, "
          f"{panel.index.min().date()}..{panel.index.max().date()}")
    print(f"[INFO] SP500_DISP valid rows: {n_disp_valid}/{n_total} "
          f"({n_disp_valid/n_total*100:.0f}%)")

    hits, _, _ = forward_event_hits(panel, [8, 15], P2.EVENT_WINDOW)
    regime = vol_regime_labels(panel)

    # Enumerated tops (all 12; in-window depends on backtest_start)
    win_start = panel.index.min()
    eps_top = P2._episode_positions(panel.index, pre["target_events"]["episode_list_top_8pct"])
    eps_top = [e for e in eps_top if pd.Timestamp(e["peak"]) >= win_start]

    # Score all constructions
    cons = CD.build_constructions()
    by_name = {c.name: c for c in cons}
    rows = [P2.score_construction(c, panel, hits, regime, eps_top, [], seed_offset=i)
            for i, c in enumerate(cons)]

    tops = [r for r in rows if r["side"] == "top" and r["role"] in ("primary", "variant")]
    best_top = max(tops, key=lambda r: (r["edge"] if np.isfinite(r["edge"]) else -9))

    dmask, cmask = _window_masks(panel, pre)

    # ---- TOP out-of-sample battery ----
    bt = by_name[best_top["name"]]
    sig_t = bt.fn(panel)
    hit_t = hits[("top", 8)].to_numpy()
    elig_t = C2.eligible_top(panel).to_numpy()
    confirm_t = P2._precision_in_window(sig_t, hit_t, elig_t, regime, cmask, 200)
    discover_t = P2._precision_in_window(sig_t, hit_t, elig_t, regime, dmask, 201)
    qres_t = _qqq_transfer(panel, seed_offset=300)
    loeo = P2.leave_one_episode_out(sig_t, hit_t, elig_t, regime, eps_top)

    # ---- Also score the primary construction (not just best_top) ----
    primary_name = "D_high_disp_near_high[0.80,252]"
    primary_row = next((r for r in rows if r["name"] == primary_name), None)

    # ---- shared: max-stat reality check across frozen primary+variant cells ----
    grid_cons = [by_name[r["name"]] for r in tops]
    reality = P2.max_stat_reality(grid_cons, panel, hits, regime)

    # ---- G5 stack-beats-parts: gated vs dispersion-only control ----
    g5_top = P3.beats_benchmark(panel, hits, bt.fn, by_name["ctl_disp_only[0.80,252]"].fn,
                                 "top", 600)

    # ---- G6 benchmark battle: detector vs 200-day trend baseline ----
    b6_top = P3.beats_benchmark(panel, hits, bt.fn, by_name["bench_top_200"].fn, "top", 700)

    # ---- G7 alert budget ----
    ab = pre.get("alert_budget", {})
    tops_min = 1.0
    tops_max = 6.0
    bud_top = P3.alert_budget_compliance(sig_t, panel.index, tops_min, tops_max)

    # ---- KILL-GATE ----
    min_edge = pre["min_effect_size"]["precision_edge_pp"] / 100.0
    alpha = pre["min_effect_size"]["alpha"]
    recall_floor = pre["min_effect_size"]["recall_floor_organic"]

    g2 = bool(np.isfinite(reality["reality_p"]) and reality["reality_p"] < alpha)

    g1 = bool(np.isfinite(best_top["edge"]) and best_top["edge"] >= min_edge
               and best_top["null_p"] < alpha)
    g3 = bool(confirm_t["edge"] > 0 and qres_t["edge"] > 0 and qres_t["null_p"] < alpha
              and loeo["no_single_collapse"])
    g4 = bool(best_top["recall_n_caught_organic"] >= recall_floor)
    g5 = bool(g5_top["beats"])
    TOP_GO = g1 and g2 and g3 and g4 and g5

    # ---- report ----
    L: list[str] = []
    L.append("# Phase-DISPERSION Detector — CONFIRMATORY Report\n")
    L.append("## Cross-Sectional Return Dispersion as a TOP Precursor (Maio & Saffi 2016)\n")
    L.append(f"- panel: {n_total} rows, {panel.index.min().date()}..{panel.index.max().date()}")
    L.append(f"- SP500_DISP valid rows: {n_disp_valid}/{n_total} ({n_disp_valid/n_total*100:.0f}%)")
    L.append(f"- frozen contract: backtest/preregistration_dispersion.yaml")
    L.append(f"- in-window enumerated tops scored: {len(eps_top)} of 12")
    L.append(f"- 8% top base rate (all days): {_f(best_top['all_days_base'])}")
    L.append("- SURVIVORSHIP CAVEAT: SP500_DISP uses today's membership applied backward.")
    L.append("  Historical dispersion is UNDERSTATED near stress events. Precision is an UPPER BOUND.")
    L.append("- HONESTY: raw ratios lead; null_p in [0.05,0.10] is SUGGESTIVE only.")
    L.append("  The make-or-break test is the QQQ cross-asset transfer (same threshold applied to")
    L.append("  NDX_DISP with NO re-tuning). Failure here = the SPY edge is index-specific noise.\n")

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
    L.append(f"- TEMPORAL hold-out — discover({pre['out_of_sample']['temporal_holdout']['discover_window'][0][:4]}-"
             f"{pre['out_of_sample']['temporal_holdout']['discover_window'][1][:4]}) "
             f"edge {_f(discover_t['edge'])} (p {_f(discover_t['null_p'])}, n={discover_t['n_ep']}) "
             f"| CONFIRM({pre['out_of_sample']['temporal_holdout']['confirm_window'][0][:4]}-"
             f"{pre['out_of_sample']['temporal_holdout']['confirm_window'][1][:4]}) "
             f"edge {_f(confirm_t['edge'])} (p {_f(confirm_t['null_p'])}, n={confirm_t['n_ep']})")
    L.append(f"- **CROSS-ASSET transfer to QQQ (THE BINDING CONSTRAINT) — "
             f"edge {_f(qres_t['edge'])}, null_p {_f(qres_t['null_p'])}, n={qres_t['n_ep']}**")
    L.append(f"- LEAVE-ONE-EPISODE-OUT — full precision {_f(loeo['full_precision'])}, "
             f"base {_f(loeo['base'])}, "
             f"max single-episode precision drop {_f(loeo['max_leverage_drop'])}, "
             f"no-single-collapse={loeo['no_single_collapse']}")

    L.append("\n## Controls / stack-beats-parts (G5) — does the near-high gate matter, matched count?\n")
    L.append(f"- TOP gated vs ctl_disp_only: detector prec {_f(g5_top['detector_precision'])} "
             f"(n={g5_top['detector_n']}) vs control {_f(g5_top['bench_precision'])} "
             f"(n={g5_top['bench_n']}); diff_p05 {_f(g5_top['diff_p05'])} -> beats={g5_top['beats']}")

    L.append("\n## Confirmatory MULTIPLE-TESTING reality check\n")
    L.append(f"- max-stat reality_p across {reality['cells']} frozen cells (opportunity-set null): "
             f"**{_f(reality['reality_p'])}** (V_obs={_f(reality['v_obs'])})")

    L.append("\n## Benchmark battle (G6 analogue) — detector vs 200-day trend baseline, matched count\n")
    L.append(f"- TOP: {best_top['name']} precision {_f(b6_top['detector_precision'])} "
             f"(n={b6_top['detector_n']}) vs bench_top_200 {_f(b6_top['bench_precision'])} "
             f"(n={b6_top['bench_n']}); diff_p05 {_f(b6_top['diff_p05'])} -> beats={b6_top['beats']}")

    L.append("\n## Alert budget — collapsed episodes/year vs pre-registered cap\n")
    L.append(f"- TOP: {_f(bud_top['episodes_per_year'],2)}/yr (cap {bud_top['cap']}, "
             f"min {bud_top['min']}) within_cap={bud_top['within_cap']} "
             f"above_min={bud_top['above_min']}")

    L.append("\n## KILL-GATE (Phase-DISPERSION)\n")
    L.append(f"- **VERDICT: {'GO' if TOP_GO else 'NO-GO'}**")
    L.append(f"- G1 precision floor (>= base+{min_edge*100:.0f}pp AND oppset p<{alpha}): "
             f"{g1} (edge {_f(best_top['edge'])}, p {_f(best_top['null_p'])})")
    L.append(f"- G2 confirmatory MTC (reality_p<{alpha}): {g2} (reality_p {_f(reality['reality_p'])})")
    L.append(f"- G3 out-of-sample (confirm>0 AND QQQ beats null AND LOEO no-collapse): {g3}")
    L.append(f"  - QQQ-transfer detail: edge {_f(qres_t['edge'])} p {_f(qres_t['null_p'])} n={qres_t['n_ep']}")
    L.append(f"  - LOEO no-single-collapse: {loeo['no_single_collapse']}")
    L.append(f"- G4 recall floor (>= {recall_floor} organic in-window): "
             f"{g4} ({best_top['recall_n_caught_organic']} organic)")
    L.append(f"- G5 stack beats parts (gated > disp-only at matched count): {g5} "
             f"(diff_p05 {_f(g5_top['diff_p05'])})")

    if not TOP_GO:
        L.append("\n> NO-GO = **no demonstrably-validated edge**. Ship DESCRIPTIVE-ONLY:")
        L.append("> display the current S&P 500 cross-sectional dispersion percentile reading.")
        L.append("> No predictive-confidence claim. No live alert.")
        L.append(">")
        L.append("> Root causes for NO-GO (check which gates failed above):")
        if not g1:
            L.append(f">  - G1: precision edge {_f(best_top['edge'])} pp below {min_edge*100:.0f}pp floor, "
                     f"or null_p {_f(best_top['null_p'])} >= {alpha}")
        if not g2:
            L.append(f">  - G2: reality check p={_f(reality['reality_p'])} >= {alpha} (no cell survives MTC)")
        if not g3:
            reasons = []
            if confirm_t["edge"] <= 0:
                reasons.append(f"confirm edge {_f(confirm_t['edge'])} <= 0")
            if not (qres_t["edge"] > 0 and qres_t["null_p"] < alpha):
                reasons.append(f"QQQ transfer edge {_f(qres_t['edge'])} p {_f(qres_t['null_p'])}")
            if not loeo["no_single_collapse"]:
                reasons.append("LOEO: single episode collapses precision")
            L.append(f">  - G3: OOS failure: {'; '.join(reasons)}")
        if not g4:
            L.append(f">  - G4: only {best_top['recall_n_caught_organic']} organic tops caught "
                     f"(floor: {recall_floor})")
        if not g5:
            L.append(f">  - G5: near-high gate does not add precision over raw dispersion")
        L.append(">")
        L.append("> The survivorship bias in the constituent data likely inflated in-sample")
        L.append("> precision. A real-time implementation would see HIGHER dispersion in")
        L.append("> stress (more losers included); the signal would be noisier and less")
        L.append("> precise than these results suggest.")
    else:
        L.append("\n> GO: dispersion signal clears all 5 kill-gate conditions. The edge is")
        L.append("> present in the confirm window AND transfers to QQQ. HOWEVER, note that")
        L.append("> survivorship bias in the constituent data inflates in-sample precision.")
        L.append("> A live shadow check is owed before any real alert fires.")

    report = "\n".join(L) + "\n"
    out = project_root() / "backtest" / "PHASE-DISPERSION-REPORT.md"
    out.write_text(report)
    print(report)
    print(f"[report written to {out}]")


if __name__ == "__main__":
    main()
