"""TODO #111 tournament — emit the frozen 58-test matrix as machine-readable JSON.

The matrix is frozen in .omc/research/todo-111-tournament/FROZEN-MATRIX.md.
This script is the machine-readable copy of the same tables. It reads nothing
and computes no outcome; it only writes the rows out so the lanes cannot
disagree about what was frozen.
"""
from __future__ import annotations
import hashlib, json, os

OUT = "/home/openclaw/.openclaw/research-data/todo-111-tournament"

# exit sets: (target, stop, cap in trading days) as a fraction of entry credit/debit
EXITS = {
    "X1": {"target": 0.50, "stop": -1.00, "cap_days": 14, "base": "credit"},
    "X2": {"target": 0.25, "stop": -1.00, "cap_days": 14, "base": "credit"},
    "X3": {"target": 0.50, "stop": -2.00, "cap_days": 14, "base": "credit"},
    "X4": {"target": 0.50, "stop": -1.00, "cap_days": 7, "base": "credit"},
    "Y1": {"target": 0.50, "stop": -0.50, "cap_days": 14, "base": "debit"},
    "Y2": {"target": 1.00, "stop": -0.50, "cap_days": 14, "base": "debit"},
    "Y3": {"target": 1.00, "stop": None, "cap_days": 14, "base": "debit"},
    "Y4": {"target": 0.50, "stop": -0.50, "cap_days": 7, "base": "debit"},
    "HOLD_NEAR": {"target": None, "stop": None, "cap_days": 14, "base": "debit",
                  "note": "hold to the near expiry, capped at 14 trading days"},
}

WINDOWS = {
    "std": {"dte_lo": 30, "dte_hi": 45, "dte_target": 37},
    "event": {"dte_lo": 5, "dte_hi": 20, "dte_target": 10},
    "cal_near": {"dte_lo": 7, "dte_hi": 20, "dte_target": 14},
    "cal_far": {"dte_lo": 45, "dte_hi": 75, "dte_target": 60},
}

# (id, mechanism, trigger, structure, exit, expiry window, note)
ROWS = [
    # 1 - managed option-premium selling
    (1, 1, "V2", "PCS(1.0)", "X1", "std", "pre-frozen candidate; do not tune"),
    (2, 1, "V2", "PCS(0.6)", "X1", "std", ""),
    (3, 1, "V2", "PCS(1.4)", "X1", "std", ""),
    (4, 1, "V2", "CCS(1.0)", "X1", "std", ""),
    (5, 1, "V2", "CCS(0.6)", "X1", "std", ""),
    (6, 1, "V2", "CCS(1.4)", "X1", "std", ""),
    (7, 1, "V2", "IC(1.0)", "X1", "std", "the rejected condor at midpoint fills"),
    (8, 1, "V2", "IC(0.6)", "X1", "std", ""),
    (9, 1, "V2", "IC(1.4)", "X1", "std", ""),
    (10, 1, "V2", "PCS(1.0)", "X2", "std", ""),
    (11, 1, "V2", "PCS(1.0)", "X3", "std", ""),
    (12, 1, "V2", "PCS(1.0)", "X4", "std", ""),
    (13, 1, "V2", "IC(1.0)", "X2", "std", ""),
    (14, 1, "V2", "IC(1.0)", "X3", "std", ""),
    (15, 1, "V2", "IC(1.0)", "X4", "std", ""),
    (16, 1, "V0", "PCS(1.0)", "X1", "std", "wider, less selective sample"),
    # 2 - cheap-volatility buying
    (17, 2, "C1", "STRAD", "Y1", "std", ""),
    (18, 2, "C1", "STRANG(0.6)", "Y1", "std", ""),
    (19, 2, "C2", "STRAD", "Y1", "std", ""),
    (20, 2, "C2", "STRANG(0.6)", "Y1", "std", ""),
    (21, 2, "C3", "STRAD", "Y1", "std", ""),
    (22, 2, "C3", "STRANG(0.6)", "Y1", "std", ""),
    (23, 2, "C1", "STRAD", "Y2", "std", ""),
    (24, 2, "C3", "STRAD", "Y2", "std", ""),
    # 3 - directional debit spreads
    (25, 3, "U1", "CDS", "Y1", "std", "option expression of the momentum signal"),
    (26, 3, "U1", "CDS", "Y3", "std", ""),
    (27, 3, "U2", "CDS", "Y1", "std", ""),
    (28, 3, "U2", "CDS", "Y3", "std", ""),
    (29, 3, "D1", "PDS", "Y1", "std", ""),
    (30, 3, "D1", "PDS", "Y3", "std", ""),
    (31, 3, "D2", "PDS", "Y1", "std", ""),
    (32, 3, "D2", "PDS", "Y3", "std", ""),
    (33, 3, "U1", "CDS", "Y4", "std", ""),
    (34, 3, "D1", "PDS", "Y4", "std", ""),
    # 4 - skew and relative value
    (35, 4, "S1", "RR+", "X1", "std", ""),
    (36, 4, "S1", "PCS(1.0)", "X1", "std", ""),
    (37, 4, "S1", "CCS(1.0)", "X1", "std", ""),
    (38, 4, "S2", "RR-", "X1", "std", ""),
    (39, 4, "S2", "CCS(1.0)", "X1", "std", ""),
    (40, 4, "S2", "PCS(1.0)", "X1", "std", ""),
    (41, 4, "S1", "RR+", "Y1", "std", ""),
    (42, 4, "S1", "RR+", "X4", "std", ""),
    # 5 - scheduled-event volatility
    (43, 5, "FOMC+E1", "STRAD", "Y1", "event", ""),
    (44, 5, "FOMC+E2", "IC(1.0)", "X1", "event", ""),
    (45, 5, "CPI+E1", "STRAD", "Y1", "event", ""),
    (46, 5, "CPI+E2", "IC(1.0)", "X1", "event", ""),
    (47, 5, "JOBS+E1", "STRAD", "Y1", "event", ""),
    (48, 5, "JOBS+E2", "IC(1.0)", "X1", "event", ""),
    (49, 5, "POOLED+E1", "STRAD", "Y1", "event", "pooling frozen before any outcome"),
    (50, 5, "POOLED+E2", "IC(1.0)", "X1", "event", "pooling frozen before any outcome"),
    # 6 - external-information option trades (feasibility-gated)
    (51, 6, "PUTFLOW", "LONG_PUT(atm)", "Y1", "std", "runs only if selection is reconstructable"),
    (52, 6, "PUTFLOW", "LONG_PUT(0.6)", "Y1", "std", "runs only if selection is reconstructable"),
    (53, 6, "PUTFLOW", "PDS", "Y1", "std", "runs only if selection is reconstructable"),
    (54, 6, "PUTFLOW", "LONG_PUT(atm)", "Y4", "std", "runs only if selection is reconstructable"),
    # 7 - calendar spreads
    (55, 7, "T1", "CAL", "Y1", "cal", ""),
    (56, 7, "T2", "CAL-", "Y1", "cal", ""),
    (57, 7, "T1", "CAL", "Y4", "cal", ""),
    (58, 7, "T1", "CAL", "HOLD_NEAR", "cal", ""),
]

MECHANISMS = {
    1: "managed option-premium selling",
    2: "cheap-volatility buying",
    3: "directional debit spreads",
    4: "skew and relative value",
    5: "scheduled-event volatility",
    6: "external-information option trades",
    7: "calendar spreads",
}

COMMON = {
    "underlying": "SPY",
    "quote_source": "Databento OPRA.PILLAR cbbo-1m (minute national best bid and offer)",
    "entry_time_exchange": "10:00 America/New_York on the session after the signal session",
    "fills": "midpoint of bid and ask on every leg, entry and exit",
    "commission_usd_per_contract_per_side": 0.45,
    "wing_width_usd": 5.0,
    "liquidity_gate": {"bid_gt": 0, "ask_gt": 0, "bid_size_min": 1, "ask_size_min": 1,
                       "max_relative_spread": 0.25, "applies_to": "every leg"},
    "session_window_exchange": ["09:30", "16:00"],
    "hard_hold_cap_trading_days": 14,
    "grid": {"cadence": "one session per ISO week: Wednesday, else Tuesday, else Thursday",
             "discovery": ["2014-01-01", "2018-12-31"],
             "confirmation": ["2019-01-01", "2021-12-31"],
             "development": ["2014-01-01", "2021-12-31"],
             "sealed": ["2022-01-01", "2026-08-31"]},
    "budget": {"already_spent_usd": 3.4836, "ceiling_usd": 20.00,
               "development_allowance_usd": 7.00, "sealed_reserve_usd": 5.00},
    "cheap_rejection_rules": [
        "fewer than 30 development trades",
        "average commission-adjusted return at or below zero",
        "profit factor below 1.00",
        "the best single trade supplies more than 50% of all positive profit",
        "the best single year supplies more than 80% of all positive profit",
        "discovery and confirmation disagree in sign",
    ],
    "max_finalists": 5,
}


def build():
    tests = []
    for tid, mech, trig, struct, ex, win, note in ROWS:
        tests.append({
            "test_id": tid,
            "mechanism_id": mech,
            "mechanism": MECHANISMS[mech],
            "trigger": trig,
            "structure": struct,
            "exit_code": ex,
            "exit": EXITS[ex],
            "expiry_window": win,
            "note": note,
            "verdict": None,
        })
    return {"frozen_on": "2026-09-03", "common": COMMON, "exits": EXITS,
            "expiry_windows": WINDOWS, "tests": tests}


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    m = build()
    assert len(m["tests"]) == 58, len(m["tests"])
    assert len({t["test_id"] for t in m["tests"]}) == 58
    blob = json.dumps(m, indent=1, sort_keys=True)
    p = f"{OUT}/frozen_matrix.json"
    open(p, "w").write(blob)
    print("wrote", p, len(m["tests"]), "tests")
    print("sha256", hashlib.sha256(blob.encode()).hexdigest())
