#!/usr/bin/env python3
"""Freeze the TODO #106 policy and fingerprint everything it depends on.

Writes frozen-policy.json, frozen-code.sha256 and frozen-policy.sha256.
Run once, after design reconciliation and before any profit number exists.
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdtm_common import DEV_LAST, RES_DIR, SEALED_FIRST, SPLITS  # noqa: E402

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
CODE = ["pdtm_common.py", "pdtm_context.py", "pdtm_methods.py", "pdtm_engine.py",
        "pdtm_gates.py", "pdtm_controls.py", "pdtm_predictors.py", "pdtm_run.py",
        "pdtm_build_context.py", "pdtm_extract_all_minutes.py",
        "pdtm_data_capability.py", "pdtm_count.py"]
DATA = ["bars-equs-allmin.parquet", "bars-pillar-allmin.parquet"]
DOCS = ["mechanical-definitions.md", "selected-method-cards.md",
        "method-universe.md", "method-exclusions.md", "source-map.md",
        "data-capability.md", "designer-one.md", "designer-two.md",
        "design-reconciliation.md", "clean-room-review.md"]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    import pdtm_run as R

    code = {f: sha(HERE / f) for f in CODE}
    (RES_DIR / "frozen-code.sha256").write_text(
        "".join(f"{v}  scripts/research/{k}\n" for k, v in sorted(code.items())))

    policy = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "todo": 106,
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WS,
                                   capture_output=True, text=True).stdout.strip(),
        "network_used": False,
        "new_data_spend_usd": 0.0,
        "primary_feed": "EQUS.MINI consolidated 1-minute trade bars, 60 NYSE large caps",
        "independent_feed": "XNYS.PILLAR 1-minute trade bars, same 60 companies",
        "universe_note": ("fixed current list, chosen with liquidity facts running to "
                          "August 2026 and applied backwards; every result on it is "
                          "conditional and can reach at most CONDITIONAL CANDIDATE"),
        "date_split": {
            "development_first": "2023-03-28", "development_last": DEV_LAST,
            "sealed_first": SEALED_FIRST, "sealed_last": "2026-08-21",
            "sealed_days": 182,
            "reused_from": "TODO #104, whose FINAL-VERDICT records the block was never opened",
        },
        "clock": {
            "shown_to_owner": "Pacific only",
            "opening_range": "06:30-06:44 Pacific, complete at 06:45",
            "earliest_signal": "06:45 Pacific",
            "latest_signal": "09:30 Pacific",
            "all_positions_closed_by": "12:55 Pacific",
        },
        "thresholds": {
            "relative_volume_min": R.RELVOL_MIN,
            "market_composite_band": R.MKT_TOL,
            "m3_extension_fraction": R.EXT_FRAC,
            "reward_to_risk_m1_m3": 1.5,
            "stop_cap": "never wider than the 20-day median daily range",
            "chosen_how": ("relative volume set on SAMPLE SIZE alone - the lowest round "
                           "value at which the tightest method reaches the sealed-period "
                           "sample gates; the market band from the development "
                           "distribution of the composite at 06:45. No profit number was "
                           "consulted for any threshold."),
        },
        "costs_bps_round_trip": {"normal": R.COST_NORMAL, "harsh": R.COST_HARSH,
                                 "diagnostic": 0.0},
        "risk": {"per_position_frac_of_starting_capital": 0.0025,
                 "max_concurrent_frac": 0.01,
                 "held_against": "starting capital, never current equity"},
        "corporate_actions": {"splits_dropped": sorted(f"{s} {d}" for s, d in SPLITS)},
        "short_side": "assumed always borrowable at no charge; every short result is an upper bound",
        "methods_frozen": ["M1", "M2", "M3-fib"],
        "controls_frozen": ["M1-control", "M2-control", "M3-mid", "M3-even",
                            "random-direction placebo (10,000 coin flips)"],
        "sealed_rule": ("at most ONE method reaches the sealed period, chosen by the "
                        "frozen development gates; if more than one were carried, a "
                        "Bonferroni correction over the number carried is applied to "
                        "every interval before any sealed number is read"),
        "options_track": ("UNTESTABLE - the project holds two-sided option quotes for 3 "
                          "trading days on 11 companies against a gate of 250 spreads "
                          "over 100 days; no option price may be synthesised from stock "
                          "bars, Black-Scholes, implied volatility or expiration payoff"),
        "code_sha256": code,
        "raw_data_sha256": {f: sha(RES_DIR / f) for f in DATA},
        "documents_sha256": {f: sha(RES_DIR / f) for f in DOCS if (RES_DIR / f).exists()},
    }
    p = RES_DIR / "frozen-policy.json"
    p.write_text(json.dumps(policy, indent=2))
    fp = sha(p)
    (RES_DIR / "frozen-policy.sha256").write_text(
        f"{fp}  .omc/research/professional-day-trader-methods/frozen-policy.json\n")
    print("frozen-policy fingerprint:", fp)


if __name__ == "__main__":
    main()
