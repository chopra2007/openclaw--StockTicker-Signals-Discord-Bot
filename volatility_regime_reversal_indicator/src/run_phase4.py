"""Phase-4 CONFIRMATORY run: score the frozen capitulation->thrust (Lowry 90/90) bottom
constructions on true NYSE up/down VOLUME (NYSE_UDVOL) + long-history S&P 500 price (GSPC),
through the reused opportunity-set null + 55-year out-of-sample battery, the controls battle
(G5), the benchmark battle (G6) and the alert budget (G7); write backtest/PHASE4-BOTTOM-REPORT.md.

    python3 -m src.run_phase4

Reads the FROZEN backtest/preregistration_phase4.yaml. The CRUX is the OPPORTUNITY-SET null:
the random-timing comparison draws ONLY from EQUALLY-DISTRESSED eligible days (>=5% drawdown),
NOT all days — because among distressed days a bounce is the base case, so beating ALL-days is
meaningless. A NO-GO ships the tool descriptive-only — an honest, expected-possible outcome.

The reused scorers (P2.opportunity_set_null, P2._precision_in_window, P2.max_stat_reality
machinery, P3.beats_benchmark, P3.alert_budget_compliance) are UNCHANGED. We do NOT use
P2.score_construction directly because it hardcodes the SPY-based C2 eligibility; Phase 4 needs
GSPC-based equally-distressed eligibility, so we wire the same primitives with our own
eligibility + a VIX-free (GSPC realized-vol) regime, which is the honest point-in-time choice
for a 1965-start window where VIX does not exist.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from .backtest import phase2 as P2
from .backtest import phase3 as P3
from .backtest.event_study import collapse_episodes, forward_event_hits
from .config import project_root
from .data import store
from .features import utils as U
from .signals import conditions_phase4 as C4

TIER = 8
EP_WINDOW = P2.EP_WINDOW
EVENT_WINDOW = P2.EVENT_WINDOW


def _pre() -> dict:
    return yaml.safe_load((project_root() / "backtest" / "preregistration_phase4.yaml").read_text())


def _f(x, nd=3):
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def _load_panel(pre: dict) -> pd.DataFrame:
    """GSPC INTERSECT genuine NYSE_UDVOL sessions over the frozen window (no ffilled volume)."""
    panel = store.load_panel(["GSPC", "NYSE_UDVOL"])
    ud = store.read_series("NYSE_UDVOL")
    panel = panel.loc[panel.index.intersection(ud.index)]   # genuine UDVOL sessions only
    w = pre["meta"]["window"]
    panel = panel[(panel.index >= pd.Timestamp(w["start"])) & (panel.index <= pd.Timestamp(w["end"]))]
    return panel


def _gspc_vol_regime(panel: pd.DataFrame, n_buckets: int = 3) -> np.ndarray:
    """VIX-free regime: bucket each day by its trailing-252 GSPC realized-vol percentile.

    Point-in-time (trailing realized vol + trailing percentile). Used in place of
    vol_regime_labels (which needs VIX_close, unavailable pre-1990) to regime-match the null.
    """
    rv = U.realized_vol(panel["GSPC_close"], 20, annualize=True)
    rvp = U.trailing_percentile(rv, 252)
    edges = np.linspace(0.0, 1.0, n_buckets + 1)[1:-1]
    return np.digitize(rvp.fillna(0.0).to_numpy(), edges).astype(int)


def _window_masks(panel, pre):
    cwin = pre["out_of_sample"]["temporal_holdout"]["confirm_window"]
    dwin = pre["out_of_sample"]["temporal_holdout"]["discover_window"]
    cmask = np.asarray((panel.index >= pd.Timestamp(cwin[0])) & (panel.index <= pd.Timestamp(cwin[1])))
    dmask = np.asarray((panel.index >= pd.Timestamp(dwin[0])) & (panel.index <= pd.Timestamp(dwin[1])))
    return dmask, cmask


def _score(fn, panel, hit, elig, regime, seed_offset) -> dict:
    """Opportunity-set-null score for one construction + the all-days base (reused P2 null)."""
    sig = fn(panel)
    ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
    res = P2.opportunity_set_null(hit, ep, elig, regime, seed_offset=seed_offset)
    valid = np.isfinite(hit)
    res["all_days_base"] = float(hit[valid].mean()) if valid.any() else np.nan
    res["raw_days"] = int(sig.sum())
    return res


def _loeo_episodes(fn, panel, hit, elig, regime, seed_offset) -> dict:
    """Leave-one-EPISODE-out: drop each collapsed episode, recompute the pooled opportunity-set
    edge on the rest; no single episode may carry the edge (its removal must not collapse
    precision to the eligible base). Pooled-precision version (bottoms have no enumerated list)."""
    sig = fn(panel)
    ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
    valid = np.isfinite(hit)
    eps = [p for p in ep if valid[p]]
    pool = np.flatnonzero(valid & elig)
    base = float(hit[pool].mean()) if len(pool) else np.nan
    full = float(hit[eps].mean()) if eps else np.nan
    drops = []
    for k in range(len(eps)):
        rest = eps[:k] + eps[k + 1:]
        drops.append(float(hit[rest].mean()) if rest else np.nan)
    min_wo = float(np.nanmin(drops)) if drops else np.nan
    return {"n_ep": len(eps), "full_precision": full, "elig_base": base,
            "min_precision_leave_one": min_wo,
            "no_single_collapse": bool(np.isfinite(min_wo) and min_wo > base)}


def _max_stat(grid_fns, panel, hit, elig, regime) -> dict:
    """Max-stat reality across the frozen cells using opportunity-set-null edge distributions
    (same machinery as P2.max_stat_reality, but with the phase-4 GSPC eligibility)."""
    edges, nulls = [], []
    valid = np.isfinite(hit)
    pool = np.flatnonzero(valid & elig)
    for i, fn in enumerate(grid_fns):
        sig = fn(panel)
        ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
        eps_v = np.array([p for p in ep if valid[p]], dtype=int)
        if len(eps_v) == 0 or len(pool) == 0:
            continue
        eb = float(hit[pool].mean())
        edges.append(float(hit[eps_v].mean()) - eb)
        rng = np.random.default_rng(P2.SEED + 7000 + i)
        nd = np.array([hit[rng.choice(pool, size=len(eps_v), replace=len(pool) < len(eps_v))].mean() - eb
                       for _ in range(2000)])
        nulls.append(nd)
    if not edges:
        return {"reality_p": np.nan, "v_obs": np.nan, "cells": 0}
    V = float(np.nanmax(edges))
    null_max = np.nanmax(np.vstack(nulls), axis=0)
    p = float((1 + np.sum(null_max >= V)) / (len(null_max) + 1))
    return {"reality_p": p, "v_obs": V, "cells": len(edges)}


def main() -> None:
    pre = _pre()
    panel = _load_panel(pre)
    # forward outcome = trough-to-peak rally on GSPC within 60 trading days (reuse the scorer,
    # pointed at GSPC). Forward outcomes are NOT features — no look-ahead is introduced.
    hits, _, _ = forward_event_hits(panel, [8, 15], EVENT_WINDOW, ticker="GSPC")
    hit8 = hits[("bottom", 8)].to_numpy()
    hit15 = hits[("bottom", 15)].to_numpy()
    regime = _gspc_vol_regime(panel)

    # the make-or-break opportunity set: EQUALLY-DISTRESSED days (>=5% drawdown)
    elig = C4.eligible_drawdown(panel, -0.05).to_numpy()
    elig_alt = C4.eligible_post_capitulation(panel, 25).to_numpy()

    cons = C4.build_constructions()
    by_name = {c.name: c for c in cons}
    grid = [c for c in cons if c.role in ("primary", "variant")]

    # ---- per-construction score (8% tier, primary opportunity set) ----
    rows = {}
    for i, c in enumerate(cons):
        rows[c.name] = _score(c.fn, panel, hit8, elig, regime, seed_offset=i)

    bots = [c for c in grid]
    best = max(bots, key=lambda c: (rows[c.name]["edge"] if np.isfinite(rows[c.name]["edge"]) else -9))
    bb = by_name[best.name]

    # ---- 15% tier for the best (deeper-rally robustness) ----
    res15 = _score(bb.fn, panel, hit15, elig, regime, seed_offset=99)
    # ---- alt eligibility (post-capitulation peers) for the best ----
    res_alt = _score(bb.fn, panel, hit8, elig_alt, regime, seed_offset=98)

    # ---- temporal hold-out (55-year split) ----
    dmask, cmask = _window_masks(panel, pre)
    sig_b = bb.fn(panel)
    discover = P2._precision_in_window(sig_b, hit8, elig, regime, dmask, 401)
    confirm = P2._precision_in_window(sig_b, hit8, elig, regime, cmask, 400)

    # ---- leave-one-episode-out (pooled precision) ----
    loeo = _loeo_episodes(bb.fn, panel, hit8, elig, regime, 500)

    # ---- max-stat reality across the 5 frozen cells ----
    reality = _max_stat([c.fn for c in grid], panel, hit8, elig, regime)

    # ---- G5 stack-beats-parts: the SEQUENCE vs each control (matched count) ----
    hits_g = {("bottom", TIER): hits[("bottom", TIER)]}
    g5_thr = P3.beats_benchmark(panel, hits_g, bb.fn, by_name["ctl_thrust_only"].fn, "bottom", 600)
    g5_cap = P3.beats_benchmark(panel, hits_g, bb.fn, by_name["ctl_capitulation_only"].fn, "bottom", 601)

    # ---- G6 benchmark battle vs the 200-day MA reclaim ----
    b6 = P3.beats_benchmark(panel, hits_g, bb.fn, by_name["bench_bot_200"].fn, "bottom", 700)

    # ---- G7 alert budget ----
    ab = pre["alert_budget"]["bottoms_per_year"]
    bud = P3.alert_budget_compliance(sig_b, panel.index, ab["min"], ab["max"])

    # ---- KILL-GATE ----
    min_edge = pre["min_effect_size"]["precision_edge_pp"] / 100.0
    alpha = pre["min_effect_size"]["alpha"]
    rb = rows[best.name]

    g1 = bool(np.isfinite(rb["edge"]) and rb["edge"] >= min_edge and rb["null_p"] < alpha)
    g2 = bool(np.isfinite(reality["reality_p"]) and reality["reality_p"] < alpha)
    g3 = bool(np.isfinite(confirm["edge"]) and confirm["edge"] > 0
              and np.isfinite(discover["edge"]) and discover["edge"] > 0)
    g4 = bool(loeo["no_single_collapse"])
    g5 = bool(g5_thr["beats"] and g5_cap["beats"])
    g6 = bool(b6["beats"])
    g7 = bool(bud["within_cap"])
    BOT_GO = g1 and g2 and g3 and g4 and g5 and g6 and g7

    # ---- report ----
    L: list[str] = []
    L.append("# Phase-4 BOTTOM Detector — CONFIRMATORY Report (capitulation -> rare breadth THRUST, Lowry 90/90)\n")
    L.append(f"- panel: {panel.shape[0]} rows, {panel.index.min().date()}..{panel.index.max().date()} "
             f"({(panel.index.max()-panel.index.min()).days/365.25:.1f} years)")
    L.append("- breadth: NYSE_UDVOL (true NYSE advancing-vs-declining share VOLUME) | price: GSPC (^GSPC)")
    L.append("- frozen contract: backtest/preregistration_phase4.yaml (builds on the Phase-3 NO-GO; bottom-only)")
    L.append(f"- 8% rally base rate (ALL days): {_f(rb['all_days_base'])} | "
             f"15% rally base (all days): {_f(res15['all_days_base'])}")
    L.append(f"- # of 90% DOWN days: {int(C4.capitulation_90(panel).sum())} | "
             f"# of 90% UP days: {int(C4.thrust_90(panel).sum())} | "
             f"equally-distressed eligible days (>=5% DD): {int(elig.sum())}")
    L.append("- HONESTY: raw ratios lead; the OPPORTUNITY-SET null (random timing among equally-distressed")
    L.append("  days) is the make-or-break test, NOT the all-days base. A null_p in [0.05,0.10] is SUGGESTIVE only.")
    L.append("- LIMITATION: data ends 2020-02-10 (no COVID-2020 / 2022 / 2025 bottoms); no QQQ transfer "
             "(NYSE-index feed, QQQ starts 1999).\n")

    L.append("## Per-construction precision vs the OPPORTUNITY-SET null (equally-distressed days)\n")
    L.append("| construction | role | episodes | TP | precision | elig-base (>=5% DD) | edge | oppset null_p | all-days base |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c in cons:
        r = rows[c.name]
        L.append(f"| {c.name} | {c.role} | {r['n_ep']} | {r['tp']} | {_f(r['precision'])} | "
                 f"{_f(r['elig_base'])} | {_f(r['edge'])} | {_f(r['null_p'])} | {_f(r['all_days_base'])} |")

    L.append(f"\n## Best bottom construction: **{best.name}**  (best of {len(grid)} cells by opportunity-set edge)\n")
    L.append(f"- raw ratio: **{rb['tp']} of {rb['n_ep']}** thrust episodes preceded a >=8% rally within 60 days")
    L.append(f"- precision {_f(rb['precision'])} vs equally-distressed base {_f(rb['elig_base'])} "
             f"= **edge {_f(rb['edge'])}** pp; OPPORTUNITY-SET null_p = **{_f(rb['null_p'])}**  <- the make-or-break number")
    L.append(f"- vs ALL-days base {_f(rb['all_days_base'])} = +{_f(rb['precision']-rb['all_days_base'])} "
             f"(the base-rate trap — reported, NOT the gate)")
    L.append(f"- ALT eligibility (within 25d of a 90% down day): precision {_f(res_alt['precision'])} vs "
             f"base {_f(res_alt['elig_base'])} = edge {_f(res_alt['edge'])} (null_p {_f(res_alt['null_p'])}, n={res_alt['n_ep']})")
    L.append(f"- 15% deeper-rally tier: precision {_f(res15['precision'])} vs base {_f(res15['elig_base'])} "
             f"= edge {_f(res15['edge'])} (null_p {_f(res15['null_p'])}, n={res15['n_ep']})")

    L.append("\n## OPPORTUNITY-SET NULL block (the make-or-break test, restated)\n")
    L.append(f"- 90/90 thrust precision = {_f(rb['precision'])}; among equally-distressed days the SAME-COUNT")
    L.append(f"  random-timing precision averages ~{_f(rb['elig_base'])} (the eligible base).")
    L.append(f"- edge over equally-distressed = **{_f(rb['edge'])} pp**, null_p = **{_f(rb['null_p'])}**.")
    if np.isfinite(rb["null_p"]) and rb["null_p"] >= alpha:
        L.append("- VERDICT on the crux: the 90/90 thrust does NOT clear the equally-distressed base at p<0.05 "
                 "-> the apparent edge is (mostly) the distressed base rate, not the sequence.")
    elif np.isfinite(rb["null_p"]) and rb["null_p"] < alpha and rb["edge"] >= min_edge:
        L.append("- VERDICT on the crux: the 90/90 thrust DOES beat the equally-distressed base at p<0.05 with a "
                 ">=20pp edge -> the sequence carries real information beyond the base rate.")
    else:
        L.append("- VERDICT on the crux: SUGGESTIVE band / sub-threshold edge — does NOT flip the tool ON.")

    L.append("\n## Temporal hold-out (55-year split: discover 1965-1994 / confirm 1995-2020)\n")
    L.append(f"- DISCOVER edge {_f(discover['edge'])} (null_p {_f(discover['null_p'])}, n={discover['n_ep']}) "
             f"| CONFIRM edge {_f(confirm['edge'])} (null_p {_f(confirm['null_p'])}, n={confirm['n_ep']})")

    L.append("\n## CONTROLS — the SEQUENCE must beat both pieces (load-bearing)\n")
    rt, rc = rows["ctl_thrust_only"], rows["ctl_capitulation_only"]
    L.append(f"- ctl_thrust_only       (90% UP, no capitulation): precision {_f(rt['precision'])} edge {_f(rt['edge'])} "
             f"null_p {_f(rt['null_p'])} (n={rt['n_ep']})")
    L.append(f"- ctl_capitulation_only (ANY 90% DOWN = base-rate trap): precision {_f(rc['precision'])} edge {_f(rc['edge'])} "
             f"null_p {_f(rc['null_p'])} (n={rc['n_ep']})")
    L.append(f"- G5 stack-beats-parts (matched count): vs thrust_only diff_p05 {_f(g5_thr['diff_p05'])} beats={g5_thr['beats']} "
             f"| vs capitulation_only diff_p05 {_f(g5_cap['diff_p05'])} beats={g5_cap['beats']}")
    L.append("- READ: if the controls are about as strong as the sequence, the capitulation->thrust pairing adds nothing.")

    L.append("\n## Leave-one-episode-out (pooled precision)\n")
    L.append(f"- full precision {_f(loeo['full_precision'])}, eligible base {_f(loeo['elig_base'])}, "
             f"min precision after dropping any one episode {_f(loeo['min_precision_leave_one'])}, "
             f"no-single-collapse={loeo['no_single_collapse']} (n_ep={loeo['n_ep']})")

    L.append("\n## Confirmatory MULTIPLE-TESTING reality check\n")
    L.append(f"- max-stat reality_p across {reality['cells']} frozen cells (opportunity-set null): "
             f"**{_f(reality['reality_p'])}** (V_obs={_f(reality['v_obs'])})")

    L.append("\n## Benchmark battle (G6) vs bench_bot_200 (GSPC reclaims its 200-day MA), matched count\n")
    L.append(f"- {best.name} precision {_f(b6['detector_precision'])} (n={b6['detector_n']}) vs "
             f"bench_bot_200 {_f(b6['bench_precision'])} (n={b6['bench_n']}); diff_p05 {_f(b6['diff_p05'])} -> beats={b6['beats']}")

    L.append("\n## Alert budget (G7) — collapsed episodes/year vs the recalibrated cap\n")
    L.append(f"- {_f(bud['episodes_per_year'],2)}/yr (cap {bud['cap']}, min {bud['min']}) "
             f"within_cap={bud['within_cap']} above_min={bud['above_min']}")

    L.append("\n## KILL-GATE (Phase-4, bottom side)\n")
    L.append(f"- **BOTTOM VERDICT: {'GO' if BOT_GO else 'NO-GO'}**")
    L.append(f"- G1 precision floor (>= base+{min_edge*100:.0f}pp AND oppset p<{alpha}): {g1} "
             f"(edge {_f(rb['edge'])}, p {_f(rb['null_p'])})")
    L.append(f"- G2 confirmatory MTC (reality_p<{alpha}): {g2} (reality_p {_f(reality['reality_p'])})")
    L.append(f"- G3 out-of-sample (BOTH halves edge>0): {g3} (discover {_f(discover['edge'])}, confirm {_f(confirm['edge'])})")
    L.append(f"- G4 leave-one-episode-out (no single episode carries the edge): {g4}")
    L.append(f"- G5 stack beats parts (sequence > both controls, matched): {g5}")
    L.append(f"- G6 benchmark battle (beats 200-day MA reclaim): {g6}")
    L.append(f"- G7 alert budget (within cap {bud['cap']}/yr): {g7}")
    if not BOT_GO:
        L.append("\n> BOTTOM NO-GO = **no demonstrable edge over equally-distressed days**. Ship DESCRIPTIVE-ONLY "
                 "(display where the 90/90 breadth-thrust state stands today; no predictive-confidence claim, no "
                 "live alert). This is the honest, expected-possible outcome the pre-registration anticipated. The "
                 "55-year window finally gave the test real power — and the SEQUENCE still has to beat the fact that "
                 "distressed days bounce anyway.")
    else:
        L.append("\n> BOTTOM GO = the capitulation->thrust SEQUENCE beats the equally-distressed base, survives the "
                 "55-year temporal split, beats both controls and the 200-day benchmark, and fits the alert budget. "
                 "May ship per its alert budget after a live shadow check (note: live NYSE up/down volume must be "
                 "forward-collected — the archive feed ends 2020-02).")

    report = "\n".join(L) + "\n"
    out = project_root() / "backtest" / "PHASE4-BOTTOM-REPORT.md"
    out.write_text(report)
    print(report)
    print(f"[report written to {out}]")


if __name__ == "__main__":
    main()
