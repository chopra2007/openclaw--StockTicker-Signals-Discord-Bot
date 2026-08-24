#!/usr/bin/env python3
"""TODO #93 — robustness check on one ambiguity in the frozen threshold wording.

The plan says magnitude thresholds use "the ticker's trailing 60 valid trading
sessions". The builder reads that as the last 60 sessions that actually have a
value. The independent auditor read it as the last 60 calendar sessions, some
of which may be blank. This script re-fires all six rules under the auditor's
reading and reports whether the conclusion moves.

It does not change any frozen rule. It only measures how much the answer
depends on that one wording choice. Development dates only.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auction_pressure_walkforward as W  # noqa: E402
from auction_pressure_common import (  # noqa: E402
    BASE_COST, EXTREME_PCTL, GATE_DIR, LARGE_GAP_PCTL, TRAILING_MIN, TRAILING_WINDOW,
)


def calendar_trailing(series, how, q=0.0):
    """The auditor's reading: last 60 calendar sessions, blanks included."""
    roll = series.shift(1).rolling(TRAILING_WINDOW, min_periods=TRAILING_MIN)
    return roll.quantile(q) if how == "quantile" else roll.median()


def main():
    p = pd.read_parquet(GATE_DIR / "dev-panel.parquet").sort_values(["symbol", "date"])

    # --- confirm what basis the builder's closing-pressure threshold actually uses ---
    probe = []
    for sym, g in p.groupby("symbol"):
        g = g.reset_index(drop=True)
        for i in range(200, min(260, len(g))):
            stored = g.loc[i, "closing_pressure_pctl"]
            if not np.isfinite(stored):
                continue
            cp = g.loc[: i - 1, "closing_pressure"].abs().dropna()
            excl = np.quantile(cp.iloc[-61:-1], EXTREME_PCTL) if len(cp) >= 61 else np.nan
            incl = np.quantile(cp.iloc[-60:], EXTREME_PCTL) if len(cp) >= 60 else np.nan
            probe.append((stored, excl, incl))
        if len(probe) > 300:
            break
    probe = np.array(probe)
    excl_match = float(np.isclose(probe[:, 0], probe[:, 1], rtol=1e-9).mean())
    incl_match = float(np.isclose(probe[:, 0], probe[:, 2], rtol=1e-9).mean())

    # --- re-fire the six rules under the alternative threshold basis ---
    parts = []
    for _, g in p.groupby("symbol", sort=False):
        g = g.copy()
        g["pressure_pctl"] = calendar_trailing(g["signed_pressure"].abs(), "quantile", EXTREME_PCTL)
        g["closing_pressure_pctl"] = calendar_trailing(
            g["closing_pressure"].abs().shift(1), "quantile", EXTREME_PCTL)
        g["paired_median"] = calendar_trailing(g["paired_qty_0930"], "median")
        g["gap_pctl"] = calendar_trailing(g["opening_gap"].abs(), "quantile", LARGE_GAP_PCTL)
        parts.append(g)
    alt = pd.concat(parts)
    alt["pressure_extreme"] = alt["signed_pressure"].abs() >= alt["pressure_pctl"]
    alt["max_pre_extreme"] = alt["max_pre_pressure"] >= alt["pressure_pctl"]
    alt["closing_pressure_extreme"] = (
        alt["prior_closing_pressure"].abs() >= alt["closing_pressure_pctl"])
    alt["paired_size"] = alt["paired_qty_0930"] / alt["paired_median"]
    alt["large_gap"] = alt["opening_gap"].abs() >= alt["gap_pctl"]
    for lane in ("a", "b"):
        col = f"lane_{lane}_eligible"
        alt[col] = alt[col] & alt["pressure_pctl"].notna() & alt["gap_pctl"].notna()
    alt["lane_b_eligible"] = alt["lane_b_eligible"] & alt["closing_pressure_pctl"].notna()

    def rule_table(panel):
        cand, dropped = W.merge_candidates(W.apply_rules(panel))
        out = {"candidates": int(len(cand)), "dropped_conflicting": int(dropped), "rules": {}}
        for r in W.RULE_IDS:
            sub = cand[cand[f"rule_{r}"] > 0]
            out["rules"][r] = {
                "n": int(len(sub)),
                "gross_bps": float(sub["gross"].mean() * 1e4) if len(sub) else None,
                "net_bps": float(sub["net"].mean() * 1e4) if len(sub) else None,
                "win_rate": float(sub["win"].mean()) if len(sub) else None,
            }
        return out

    frozen = rule_table(p)
    alternative = rule_table(alt)
    best_gross = max(v["gross_bps"] for v in alternative["rules"].values()
                     if v["gross_bps"] is not None)

    result = {
        "purpose": "does the negative verdict depend on how 'trailing 60 valid sessions' is read?",
        "closing_pressure_threshold_basis": {
            "matches_window_excluding_the_tested_value": excl_match,
            "matches_window_including_the_tested_value": incl_match,
            "conclusion": ("the builder's closing-pressure threshold EXCLUDES the value being "
                           "tested" if excl_match > incl_match else
                           "the builder's closing-pressure threshold INCLUDES the value being tested"),
            "sample_rows": int(len(probe)),
        },
        "frozen_reading_60_valid_sessions": frozen,
        "alternative_reading_60_calendar_sessions": alternative,
        "gross_needed_to_pass_the_gate_bps": 35.0,
        "best_rule_gross_under_alternative_bps": best_gross,
        "verdict_changes": bool(best_gross >= 35.0),
    }
    (GATE_DIR / "threshold-sensitivity.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
