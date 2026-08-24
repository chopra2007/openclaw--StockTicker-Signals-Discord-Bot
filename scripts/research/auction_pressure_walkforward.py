#!/usr/bin/env python3
"""TODO #93 Phase 3 — walk-forward builder over the development panel only.

Applies the six frozen rules, ranks the candidates with the frozen small
model inside four expanding walk-forward folds, and writes the internal
event file, summary, and report. Reads no evaluation date.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_pressure_common import (  # noqa: E402
    BASE_COST,
    COST_SENSITIVITY,
    FOLDS,
    GATE_DIR,
    MAX_TRADES_PER_DAY,
    PRECISION_MIN,
    PRECISION_MIN_SUPPORT,
    SEED,
    STRESS_COST,
)

N_BOOT = 10_000
N_SHUFFLE = 1_000

MODEL_COLS = [
    "rule_A1", "rule_A2", "rule_A3", "rule_B1", "rule_B2", "rule_B3",
    "dir_signed_pressure", "dir_opening_gap", "dir_first_five_return",
    "dir_prior_closing_pressure",
    "persistence", "cancellation", "paired_size", "flip_count", "growth",
    "same_sign", "late_flip", "cal_month_end", "cal_quarter_end",
]
WINSOR_COLS = [
    "dir_signed_pressure", "dir_opening_gap", "dir_first_five_return",
    "dir_prior_closing_pressure", "persistence", "cancellation", "paired_size",
    "flip_count", "growth",
]
RULE_IDS = ["A1", "A2", "A3", "B1", "B2", "B3"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# the six frozen rules
# --------------------------------------------------------------------------
def apply_rules(panel):
    d = panel
    sign930 = np.sign(d["signed_pressure"])
    sign_close = np.sign(d["prior_closing_pressure"])
    same_sign = (sign_close == sign930) & sign930.ne(0) & d["prior_closing_pressure"].notna()

    def follows(direction, value):
        return (direction * value) > 0

    def fails(direction, value):
        return (direction * value) <= 0

    ok_a = d["lane_a_eligible"] & sign930.ne(0)
    ok_b = d["lane_b_eligible"] & sign930.ne(0)
    esign = d["earlier_pressure_sign"]

    fires = {
        "A1": (ok_a & d["pressure_extreme"] & d["persistent"]
               & fails(sign930, d["opening_gap"]) & fails(sign930, d["first_five_return"])),
        "A2": (ok_a & d["max_pre_extreme"] & esign.ne(0)
               & ((d["cancellation"] >= 0.50) | d["late_flip"])
               & follows(esign, d["opening_gap"])
               & follows(-esign, d["first_five_return"])),
        "A3": (ok_a & d["pressure_extreme"] & d["persistent"]
               & follows(sign930, d["opening_gap"]) & follows(sign930, d["first_five_return"])),
        "B1": (ok_b & d["closing_pressure_extreme"] & d["pressure_extreme"] & same_sign
               & follows(sign930, d["opening_gap"])),
        "B2": (ok_b & d["closing_pressure_extreme"] & d["pressure_extreme"]
               & d["prior_closing_pressure"].notna() & ~same_sign & sign_close.ne(0)
               & follows(sign930, d["opening_gap"])),
        "B3": (ok_b & d["calendar_group"].isin(["month_end", "quarter_end"])
               & d["pressure_extreme"] & d["large_gap"]
               & follows(sign930, d["opening_gap"])),
    }
    directions = {
        "A1": -sign930, "A2": -esign, "A3": sign930,
        "B1": sign930, "B2": sign930, "B3": -sign930,
    }
    lanes = {"A1": "a", "A2": "a", "A3": "a", "B1": "b", "B2": "b", "B3": "b"}

    out = d.copy()
    out["same_sign"] = same_sign.astype(float)
    for rid in RULE_IDS:
        out[f"rule_{rid}"] = fires[rid].fillna(False).astype(bool)
        out[f"dir_{rid}"] = directions[rid].where(fires[rid].fillna(False))
    out["n_rules"] = sum(out[f"rule_{r}"].astype(int) for r in RULE_IDS)
    out["_lanes"] = lanes
    return out


def merge_candidates(scored):
    """One candidate per ticker-date; unanimous direction or dropped."""
    cand = scored[scored["n_rules"] > 0].copy()
    dirs = cand[[f"dir_{r}" for r in RULE_IDS]]
    dmin, dmax = dirs.min(axis=1), dirs.max(axis=1)
    cand["direction"] = dmin
    cand["conflicting"] = dmin != dmax
    cand["rule_ids"] = [
        ",".join(r for r in RULE_IDS if row[f"rule_{r}"]) for _, row in cand.iterrows()
    ]
    cand["lane"] = np.where(
        cand[["rule_A1", "rule_A2", "rule_A3"]].any(axis=1), "a", "b"
    )
    dropped = int(cand["conflicting"].sum())
    cand = cand[~cand["conflicting"]].copy()

    cand["adj"] = np.where(cand["lane"] == "a", cand["adj_a"], cand["adj_b"])
    cand["adj30"] = np.where(cand["lane"] == "a", cand["adj30_a"], cand["adj30_b"])
    up = np.where(cand["lane"] == "a", cand["up_a"], cand["up_b"])
    dn = np.where(cand["lane"] == "a", cand["dn_a"], cand["dn_b"])
    cand["mfe"] = np.where(cand["direction"] > 0, up, -dn)
    cand["mae"] = np.where(cand["direction"] > 0, dn, -up)
    cand["gross"] = cand["direction"] * cand["adj"]
    cand["gross30"] = cand["direction"] * cand["adj30"]
    for c in COST_SENSITIVITY:
        cand[f"net_{int(c*10000)}bps"] = cand["gross"] - c
    cand["net"] = cand["gross"] - BASE_COST
    cand["win"] = cand["net"] > 0

    # model inputs
    cand["dir_signed_pressure"] = cand["direction"] * cand["signed_pressure"]
    cand["dir_opening_gap"] = cand["direction"] * cand["opening_gap"]
    cand["dir_first_five_return"] = np.where(
        cand["lane"] == "a", cand["direction"] * cand["first_five_return"], np.nan
    )
    cand["dir_prior_closing_pressure"] = cand["direction"] * cand["prior_closing_pressure"]
    cand["late_flip"] = cand["late_flip"].astype(float)
    cand["cal_month_end"] = (cand["calendar_group"] == "month_end").astype(float)
    cand["cal_quarter_end"] = (cand["calendar_group"] == "quarter_end").astype(float)
    for r in RULE_IDS:
        cand[f"rule_{r}"] = cand[f"rule_{r}"].astype(float)
    cand = cand.dropna(subset=["gross"])
    return cand.reset_index(drop=True), dropped


# --------------------------------------------------------------------------
# walk-forward ranking
# --------------------------------------------------------------------------
def fit_fold(train, valid):
    lo = train[WINSOR_COLS].quantile(0.01)
    hi = train[WINSOR_COLS].quantile(0.99)

    def prep(df):
        x = df[MODEL_COLS].copy()
        x[WINSOR_COLS] = x[WINSOR_COLS].clip(lo, hi, axis=1)
        return x

    imputer = SimpleImputer(strategy="median", add_indicator=True)
    scaler = StandardScaler()
    clf = LogisticRegression(penalty="l2", C=1.0, max_iter=2000, random_state=SEED)

    xtr = scaler.fit_transform(imputer.fit_transform(prep(train)))
    ytr = train["win"].astype(int).to_numpy()
    clf.fit(xtr, ytr)
    s_tr = clf.decision_function(xtr)
    s_va = clf.decision_function(scaler.transform(imputer.transform(prep(valid))))

    # training precision at each score-or-higher, used as the selection rule
    order = np.argsort(-s_tr)
    sorted_scores = s_tr[order]
    cum_wins = np.cumsum(ytr[order])
    counts = np.arange(1, len(sorted_scores) + 1)
    precision_at = cum_wins / counts

    def qualifies(score):
        n = int(np.searchsorted(-sorted_scores, -score, side="right"))
        if n < PRECISION_MIN_SUPPORT:
            return False, np.nan, n
        return bool(precision_at[n - 1] >= PRECISION_MIN), float(precision_at[n - 1]), n

    quals = [qualifies(s) for s in s_va]
    fold_state = {
        "winsor_low": {k: float(v) for k, v in lo.items()},
        "winsor_high": {k: float(v) for k, v in hi.items()},
        "imputer_statistics": [float(v) for v in imputer.statistics_],
        "scaler_mean": [float(v) for v in scaler.mean_],
        "scaler_scale": [float(v) for v in scaler.scale_],
        "coefficients": dict(zip(
            list(MODEL_COLS) + [f"missing_{c}" for c in
                                np.array(MODEL_COLS)[imputer.indicator_.features_].tolist()],
            [float(c) for c in clf.coef_[0]])),
        "intercept": float(clf.intercept_[0]),
        "train_rows": int(len(train)),
        "train_win_rate": float(ytr.mean()),
    }
    return s_va, quals, fold_state


def run_walkforward(cand, dev_dates):
    pos = {d: i for i, d in enumerate(dev_dates)}
    cand = cand.copy()
    cand["date_pos"] = cand["date"].map(pos)
    all_rows, fold_states = [], {}
    for k, (tlo, thi, vlo, vhi) in enumerate(FOLDS, start=1):
        train = cand[(cand["date_pos"] >= tlo) & (cand["date_pos"] < thi)]
        valid = cand[(cand["date_pos"] >= vlo) & (cand["date_pos"] < vhi)].copy()
        if len(train) < PRECISION_MIN_SUPPORT or valid.empty:
            fold_states[f"fold{k}"] = {"skipped": True, "train_rows": int(len(train)),
                                       "valid_rows": int(len(valid))}
            continue
        scores, quals, state = fit_fold(train, valid)
        valid["score"] = scores
        valid["qualifies"] = [q[0] for q in quals]
        valid["train_precision_at_score"] = [q[1] for q in quals]
        valid["train_support_at_score"] = [q[2] for q in quals]
        valid["fold"] = k
        valid["score_pctile"] = valid["score"].rank(pct=True)
        valid["middle_ranked"] = (valid["score_pctile"] >= 0.40) & (valid["score_pctile"] < 0.60)
        sel = valid[valid["qualifies"]].copy()
        sel = sel.sort_values(["date", "score"], ascending=[True, False])
        sel["rank_in_day"] = sel.groupby("date").cumcount() + 1
        valid["selected"] = False
        chosen = sel[sel["rank_in_day"] <= MAX_TRADES_PER_DAY].index
        valid.loc[chosen, "selected"] = True
        valid["rank_in_day"] = sel["rank_in_day"].reindex(valid.index)
        all_rows.append(valid)
        fold_states[f"fold{k}"] = state
    if not all_rows:
        return pd.DataFrame(), fold_states
    return pd.concat(all_rows).reset_index(drop=True), fold_states


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def bootstrap_by_date(values, dates, stat=None, n=N_BOOT, seed=SEED):
    """Bootstrap the MEAN, resampling whole trading dates, because stocks on
    the same day are not independent."""
    rng = np.random.default_rng(seed)
    codes, _ = pd.factorize(pd.Series(dates))
    n_dates = codes.max() + 1
    sums = np.bincount(codes, weights=np.asarray(values, dtype=float), minlength=n_dates)
    counts = np.bincount(codes, minlength=n_dates).astype(float)
    idx = rng.integers(0, n_dates, size=(n, n_dates))
    return sums[idx].sum(axis=1) / counts[idx].sum(axis=1)


def describe(net, dates, label):
    net = np.asarray(net, dtype=float)
    if len(net) == 0:
        return {"label": label, "n": 0}
    wins = net > 0
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    order = np.argsort(dates)
    curve = np.cumsum(net[order])
    dd = float((np.maximum.accumulate(curve) - curve).max()) if len(curve) else 0.0
    return {
        "label": label,
        "n": int(len(net)),
        "mean_bps": float(net.mean() * 1e4),
        "median_bps": float(np.median(net) * 1e4),
        "win_rate": float(wins.mean()),
        "loss_rate": float((net < 0).mean()),
        "profit_factor": float(pos / neg) if neg > 0 else float("inf"),
        "avg_winner_bps": float(net[net > 0].mean() * 1e4) if wins.any() else 0.0,
        "avg_loser_bps": float(net[net < 0].mean() * 1e4) if (net < 0).any() else 0.0,
        "max_drawdown_bps": dd * 1e4,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()

    panel = pd.read_parquet(GATE_DIR / "dev-panel.parquet")
    hyp = json.load(open(GATE_DIR / "hypotheses-v1.json"))
    assert len(hyp["rules"]) == 6, "hypothesis file must hold exactly six rules"
    assert panel["date"].max() <= "2025-11-28", "panel contains an evaluation date"

    dev_dates = sorted(panel["date"].unique())
    scored = apply_rules(panel)
    cand, conflicts = merge_candidates(scored)
    events, fold_states = run_walkforward(cand, dev_dates)

    summary = {
        "phase": "phase3",
        "seed": SEED,
        "panel_rows": int(len(panel)),
        "panel_hash": sha(GATE_DIR / "dev-panel.parquet"),
        "hypotheses_hash": sha(GATE_DIR / "hypotheses-v1.json"),
        "candidates_total": int(len(cand)),
        "candidates_dropped_conflicting_direction": conflicts,
        "candidates_by_rule": {r: int(cand[f"rule_{r}"].sum()) for r in RULE_IDS},
        "validation_candidates": int(len(events)),
        "fold_states": fold_states,
    }

    if events.empty or not events["selected"].any():
        summary["selected_trades"] = 0
        summary["gate_note"] = ("no candidate met the frozen training-precision selection rule in "
                                "any validation block")
        summary["selected"] = {"n": 0}
    else:
        sel = events[events["selected"]]
        d = sel["date"].to_numpy()
        net = sel["net"].to_numpy()
        summary["selected"] = describe(net, d, "selected")
        boot_mean = bootstrap_by_date(net, d)
        boot_win = bootstrap_by_date((net > 0).astype(float), d)
        summary["selected"]["mean_ci95_bps"] = [float(np.percentile(boot_mean, 2.5) * 1e4),
                                                float(np.percentile(boot_mean, 97.5) * 1e4)]
        summary["selected"]["win_rate_ci95"] = [float(np.percentile(boot_win, 2.5)),
                                                float(np.percentile(boot_win, 97.5))]
        summary["selected"]["distinct_tickers"] = int(sel["symbol"].nunique())
        summary["selected"]["distinct_days"] = int(sel["date"].nunique())
        summary["selected"]["max_trades_in_a_day"] = int(sel.groupby("date").size().max())
        summary["selected"]["trades_per_day"] = float(len(sel) / sel["date"].nunique())
        summary["selected"]["long_share"] = float((sel["direction"] > 0).mean())
        prof = sel.groupby("symbol")["net"].sum()
        total_net = sel["net"].sum()
        summary["selected"]["max_ticker_profit_share"] = (
            float(prof.max() / total_net) if total_net > 0 else None)
        summary["selected"]["by_fold"] = {
            f"fold{k}": describe(g["net"].to_numpy(), g["date"].to_numpy(), f"fold{k}")
            for k, g in sel.groupby("fold")}
        for c in COST_SENSITIVITY:
            col = f"net_{int(c*10000)}bps"
            summary["selected"][f"mean_bps_at_{int(c*10000)}bps_cost"] = float(
                sel[col].mean() * 1e4)
        summary["selected"]["mean_bps_30min_exit"] = float(
            (sel["gross30"] - BASE_COST).mean() * 1e4)
        summary["selected"]["mean_mfe_bps"] = float(sel["mfe"].mean() * 1e4)
        summary["selected"]["mean_mae_bps"] = float(sel["mae"].mean() * 1e4)

        # controls
        mid = events[events["middle_ranked"]]
        summary["middle_ranked"] = describe(mid["net"].to_numpy(), mid["date"].to_numpy(), "middle")
        summary["all_candidates"] = describe(events["net"].to_numpy(),
                                             events["date"].to_numpy(), "all_candidates")

        rng = np.random.default_rng(SEED)
        fired = set(zip(cand["date"], cand["symbol"]))
        pool = panel[(panel["lane_a_eligible"] | panel["lane_b_eligible"])].copy()
        pool = pool[~pd.Series(list(zip(pool["date"], pool["symbol"])),
                               index=pool.index).isin(fired)]
        pool_by_date = {d: g for d, g in pool.groupby("date")}
        rows = []
        for _, r in sel.iterrows():
            g = pool_by_date.get(r["date"])
            if g is None or g.empty:
                continue
            pick = g.iloc[int(rng.integers(len(g)))]
            adj = pick["adj_a"] if r["lane"] == "a" else pick["adj_b"]
            if pd.isna(adj):
                continue
            rows.append({"date": r["date"], "net": r["direction"] * adj - BASE_COST})
        ctrl = pd.DataFrame(rows)
        summary["matched_no_signal"] = (
            describe(ctrl["net"].to_numpy(), ctrl["date"].to_numpy(), "matched_no_signal")
            if len(ctrl) else {"label": "matched_no_signal", "n": 0})

        # direction shuffle within trading date
        shuffled = np.empty(N_SHUFFLE)
        gross_by_date = {dd: g["gross"].to_numpy() for dd, g in sel.groupby("date")}
        dir_by_date = {dd: g["direction"].to_numpy() for dd, g in sel.groupby("date")}
        rng2 = np.random.default_rng(SEED)
        for i in range(N_SHUFFLE):
            vals = []
            for dd in gross_by_date:
                dirs = dir_by_date[dd]
                perm = rng2.permutation(dirs)
                vals.append(gross_by_date[dd] * perm * dirs)  # re-sign within the day
            allv = np.concatenate(vals)
            shuffled[i] = allv.mean() - BASE_COST
        summary["direction_shuffle"] = {
            "n": N_SHUFFLE,
            "mean_bps": float(shuffled.mean() * 1e4),
            "p95_bps": float(np.percentile(shuffled, 95) * 1e4),
            "observed_above_p95": bool(net.mean() > np.percentile(shuffled, 95)),
        }

    # plain-rule secondary tests with Holm correction
    plain = {}
    pvals = {}
    for r in RULE_IDS:
        sub = cand[cand[f"rule_{r}"] > 0]
        if sub.empty:
            plain[r] = {"n": 0}
            continue
        stats = describe(sub["net"].to_numpy(), sub["date"].to_numpy(), r)
        boot = bootstrap_by_date(sub["net"].to_numpy(), sub["date"].to_numpy())
        p = 2 * min((boot <= 0).mean(), (boot >= 0).mean())
        stats["mean_ci95_bps"] = [float(np.percentile(boot, 2.5) * 1e4),
                                  float(np.percentile(boot, 97.5) * 1e4)]
        stats["p_value"] = float(max(p, 1.0 / N_BOOT))
        plain[r] = stats
        pvals[r] = stats["p_value"]
    order = sorted(pvals, key=pvals.get)
    m = len(order)
    prev = 0.0
    for i, r in enumerate(order):
        adj = min(1.0, max(prev, (m - i) * pvals[r]))
        plain[r]["p_value_holm"] = adj
        prev = adj
    summary["plain_rules"] = plain

    if not events.empty:
        events.to_parquet(GATE_DIR / "internal-events.parquet", index=False)
    json.dump(summary, open(GATE_DIR / "internal-summary.json", "w"), indent=2, default=str)

    gate = {
        "phase": "phase3",
        "gate_pass": bool(len(cand) > 0),
        "candidates_total": int(len(cand)),
        "validation_candidates": int(len(events)),
        "selected_trades": int(events["selected"].sum()) if not events.empty else 0,
        "max_panel_date": str(panel["date"].max()),
        "seed": SEED,
    }
    json.dump(gate, open(GATE_DIR / "phase3-gate.json", "w"), indent=2)
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
