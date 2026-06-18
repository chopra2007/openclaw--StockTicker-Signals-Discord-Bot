"""Phase-2 CONFIRMATORY run: score the frozen confluence constructions through the
opportunity-set null + out-of-sample battery and write backtest/PHASE2-REPORT.md.

    python3 -m src.run_phase2

Reads the FROZEN backtest/preregistration_phase2.yaml. Constructions/thresholds are
post-selected (disclosed); the GO/NO-GO rides on the out-of-sample battery, not the
in-sample p-value. A FAIL ships the tool descriptive-only — an honest outcome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from .backtest import phase2 as P2
from .backtest.base_rate import vol_regime_labels
from .backtest.event_study import forward_event_hits
from .config import project_root
from .data import store
from .signals import conditions_phase2 as C2

_ALL = ["SPY", "QQQ", "RSP", "QQQE", "HYG", "LQD", "TLT",
        "VIX", "VIX3M", "VVIX", "VXN", "SKEW", "BAA10Y", "ABINYSE"]


def _pre() -> dict:
    return yaml.safe_load((project_root() / "backtest" / "preregistration_phase2.yaml").read_text())


def _f(x, nd=3):
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def main() -> None:
    pre = _pre()
    panel = store.load_panel(_ALL, start=pre["meta"]["backtest_start"])
    hits, _, _ = forward_event_hits(panel, [8, 15], P2.EVENT_WINDOW)
    regime = vol_regime_labels(panel)
    eps_all = P2._episode_positions(panel.index, pre["target_events"]["episode_list_top_8pct"])
    eps_top = eps_all
    eps_bot: list = []  # bottoms scored by recall over pullbacks, not an enumerated list

    cons = C2.build_constructions()
    rows = [P2.score_construction(c, panel, hits, regime, eps_top, eps_bot, seed_offset=i)
            for i, c in enumerate(cons)]

    # primary picks: best top by opportunity-set edge among T-constructions; primary bottom B1
    tops = [r for r in rows if r["side"] == "top" and r["role"] in ("primary", "variant")]
    bots = [r for r in rows if r["side"] == "bottom" and r["role"] in ("primary", "variant")]
    best_top = max(tops, key=lambda r: (r["edge"] if np.isfinite(r["edge"]) else -9))
    best_bot = max(bots, key=lambda r: (r["edge"] if np.isfinite(r["edge"]) else -9))
    by_name = {c.name: c for c in cons}

    # out-of-sample battery on the best top
    bt = by_name[best_top["name"]]
    sig = bt.fn(panel)
    hit_top = hits[("top", 8)].to_numpy()
    elig_top = C2.eligible_top(panel).to_numpy()
    cwin = pre["out_of_sample"]["temporal_holdout"]["confirm_window"]
    dwin = pre["out_of_sample"]["temporal_holdout"]["discover_window"]
    cmask = np.asarray((panel.index >= pd.Timestamp(cwin[0])) & (panel.index <= pd.Timestamp(cwin[1])))
    dmask = np.asarray((panel.index >= pd.Timestamp(dwin[0])) & (panel.index <= pd.Timestamp(dwin[1])))
    confirm = P2._precision_in_window(sig, hit_top, elig_top, regime, cmask, 200)
    discover = P2._precision_in_window(sig, hit_top, elig_top, regime, dmask, 201)

    # cross-asset transfer to QQQ
    qpanel = P2.qqq_view(panel)
    qhits, _, _ = forward_event_hits(qpanel, [8, 15], P2.EVENT_WINDOW)
    qregime = vol_regime_labels(qpanel)
    qsig = bt.fn(qpanel)
    qhit = qhits[("top", 8)].to_numpy()
    qelig = C2.eligible_top(qpanel).to_numpy()
    qep = np.flatnonzero(P2.collapse_episodes(qsig, P2.EP_WINDOW).to_numpy())
    qres = P2.opportunity_set_null(qhit, qep, qelig, qregime, seed_offset=300)

    loeo = P2.leave_one_episode_out(sig, hit_top, elig_top, regime, eps_top)
    reality = P2.max_stat_reality([by_name[r["name"]] for r in tops + bots], panel, hits, regime)
    g5 = P2.stack_beats_parts(panel, hits, regime)

    # ---- kill-gate ----
    base = best_top["all_days_base"]
    min_edge = pre["min_effect_size"]["precision_edge_pp"] / 100.0
    alpha = pre["min_effect_size"]["alpha"]
    recall_floor = pre["min_effect_size"]["recall_floor_organic"]

    g1 = bool(np.isfinite(best_top["edge"]) and best_top["edge"] >= min_edge
              and best_top["null_p"] < alpha)
    g2 = bool(np.isfinite(reality["reality_p"]) and reality["reality_p"] < alpha)
    g3 = bool(confirm["edge"] > 0 and qres["edge"] > 0 and qres["null_p"] < alpha
              and loeo["no_single_collapse"])
    g4 = bool(best_top["recall_n_caught_organic"] >= recall_floor)
    g5_ok = bool(g5["beats"].get("ungated_watch", {}).get("t1_beats", False))
    verdict = g1 and g2 and g3 and g4 and g5_ok

    # ---- report ----
    L: list[str] = []
    L.append("# Phase-2 Confluence Detector — CONFIRMATORY Report (SPY tops / bottoms)\n")
    L.append(f"- panel: {panel.shape[0]} rows, {panel.index.min().date()}..{panel.index.max().date()}")
    L.append("- frozen contract: backtest/preregistration_phase2.yaml (hypotheses post-selected, disclosed)")
    L.append(f"- 8% top base rate (all days): {_f(base)} | opportunity-set = near-high watch days only")
    L.append("- HONESTY: raw ratios lead; an opportunity-set null_p in [0.05,0.10] is SUGGESTIVE only.\n")

    L.append("## Per-construction precision vs OPPORTUNITY-SET null (the hard null)\n")
    L.append("| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['name']} | {r['side']} | {r['role']} | {r['n_ep']} | {r['tp']} | "
                 f"{_f(r['precision'])} | {_f(r['elig_base'])} | {_f(r['edge'])} | "
                 f"{_f(r['null_p'])} | {_f(r['all_days_base'])} |")

    L.append("\n## Recall over the 12 enumerated tops (raw counts — the honest headline)\n")
    L.append("| construction | caught (all/12) | caught organic (/10) | caught distribution (/7) |")
    L.append("|---|---|---|---|")
    for r in rows:
        if r["side"] == "top":
            L.append(f"| {r['name']} | {r['recall_n_caught']}/12 | "
                     f"{r['recall_n_caught_organic']}/10 | {r['recall_n_caught_distribution']}/7 |")

    L.append(f"\n## Best top construction: **{best_top['name']}**  (best of {len(tops)} by opportunity-set edge)\n")
    L.append(f"- precision {_f(best_top['precision'])} vs eligible-base {_f(best_top['elig_base'])} "
             f"= edge {_f(best_top['edge'])} pp; opportunity-set null_p = **{_f(best_top['null_p'])}**")
    L.append(f"- raw: {best_top['tp']} of {best_top['n_ep']} alerts preceded a >=8% top; "
             f"caught {best_top['recall_n_caught_organic']}/10 organic tops")
    L.append(f"- TEMPORAL hold-out — discover(2010-21) edge {_f(discover['edge'])} (p {_f(discover['null_p'])}, n={discover['n_ep']}) "
             f"| CONFIRM(2022-26) edge {_f(confirm['edge'])} (p {_f(confirm['null_p'])}, n={confirm['n_ep']})")
    L.append(f"- CROSS-ASSET transfer to QQQ — edge {_f(qres['edge'])}, null_p {_f(qres['null_p'])}, n={qres['n_ep']}")
    L.append(f"- LEAVE-ONE-EPISODE-OUT — full precision {_f(loeo['full_precision'])}, base {_f(loeo['base'])}, "
             f"max single-episode precision drop {_f(loeo['max_leverage_drop'])}, "
             f"no-single-collapse={loeo['no_single_collapse']}")

    L.append(f"\n## Best bottom construction: **{best_bot['name']}**\n")
    L.append(f"- precision {_f(best_bot['precision'])} vs eligible-base {_f(best_bot['elig_base'])} "
             f"= edge {_f(best_bot['edge'])} pp; opportunity-set null_p = **{_f(best_bot['null_p'])}**; "
             f"raw {best_bot['tp']}/{best_bot['n_ep']}")

    L.append("\n## Confirmatory MULTIPLE-TESTING reality check\n")
    L.append(f"- max-stat reality_p across {reality['cells']} frozen cells (opportunity-set null): "
             f"**{_f(reality['reality_p'])}** (V_obs={_f(reality['v_obs'])})")
    L.append("- discloses: hypotheses were chosen from ~10+ exploratory combos, so even this "
             "understates the true search burden — the OOS battery is the real evidence.")

    L.append("\n## G5 stack-beats-parts (T1 gated vs ungated watch + legs, matched alert count)\n")
    L.append(f"- T1 precision {_f(g5['t1_precision'])} (n={g5['t1_n']})")
    for nm, d in g5["beats"].items():
        L.append(f"  - vs {nm}: comparator precision {_f(d['comparator_precision'])}, "
                 f"diff p05 {_f(d['diff_p05'])}, T1 beats = {d['t1_beats']}")

    L.append("\n## KILL-GATE (Phase-2)\n")
    L.append(f"- **VERDICT: {'GO' if verdict else 'NO-GO'}**")
    L.append(f"- G1 precision floor (>= base+{min_edge*100:.0f}pp AND oppset p<{alpha}): {g1} "
             f"(edge {_f(best_top['edge'])}, p {_f(best_top['null_p'])})")
    L.append(f"- G2 confirmatory MTC (reality_p<{alpha}): {g2} (reality_p {_f(reality['reality_p'])})")
    L.append(f"- G3 out-of-sample (confirm>0 AND QQQ beats null AND no LOEO collapse): {g3}")
    L.append(f"- G4 recall floor (>= {recall_floor}/10 organic): {g4} ({best_top['recall_n_caught_organic']}/10)")
    L.append(f"- G5 stack beats parts (T1 > ungated watch, matched): {g5_ok}")
    if not verdict:
        L.append("\n> NO-GO = **no demonstrably-validated confluence edge**. Ship DESCRIPTIVE-ONLY "
                 "(show where breadth/vol/compression stand today; no predictive-confidence claim). "
                 "This is the honest, successful outcome the pre-registration anticipated — it does "
                 "NOT flip a live alerting feature ON. The best constructions are logged as candidates "
                 "for a future, independent confirmatory test on fresh/forward data.")

    report = "\n".join(L) + "\n"
    out = project_root() / "backtest" / "PHASE2-REPORT.md"
    out.write_text(report)
    print(report)
    print(f"[report written to {out}]")


if __name__ == "__main__":
    main()
