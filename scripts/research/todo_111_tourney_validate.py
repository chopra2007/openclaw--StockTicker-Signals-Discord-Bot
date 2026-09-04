"""TODO #111 tournament — validate todo_111_tourney_core.py against real data.

Runs frozen tests #1 (PCS(1.0), exit X1) and #7 (IC(1.0), exit X1) over the
already-downloaded condor development files — no new Databento spend, since
the condor's short_put/long_put/short_call/long_call legs at m=1.0 already
ARE the PCS(1.0)/CCS(1.0) legs. Then re-prices one trade by an independent
second code path, and re-derives one date's PCS(1.0)/IC(1.0) legs from the
raw chain snapshot through build_structure() to check that path too, since
the chain files needed for that are already on disk at $0.

Writes everything to research-data/todo-111-tournament/validation.json.
"""
from __future__ import annotations

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
import todo_111_tourney_core as core  # noqa: E402
import databento as db  # noqa: E402

RD = "/home/openclaw/.openclaw/research-data/todo-111-condor"
OUT_DIR = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
X1 = {"target": 0.5, "stop": -1.0}


def legs_to_structure(legs: dict, spec: str):
    """Build a PCS(1.0)/IC(1.0) structure dict straight from the condor
    pull's already-boundary-1.0 legs, no new chain read needed."""
    put_legs = [
        {"symbol": legs["symbols"]["short_put"], "strike": legs["short_put"],
         "cp": "P", "qty": -1, "role": "short_put"},
        {"symbol": legs["symbols"]["long_put"], "strike": legs["long_put"],
         "cp": "P", "qty": +1, "role": "long_put"},
    ]
    if spec == "PCS(1.0)":
        return {"code": spec, "expiration": legs["expiration"], "legs": put_legs,
                "width": core.WING, "kind": "credit", "max_risk_rule": "width - credit"}
    call_legs = [
        {"symbol": legs["symbols"]["short_call"], "strike": legs["short_call"],
         "cp": "C", "qty": -1, "role": "short_call"},
        {"symbol": legs["symbols"]["long_call"], "strike": legs["long_call"],
         "cp": "C", "qty": +1, "role": "long_call"},
    ]
    return {"code": spec, "expiration": legs["expiration"], "legs": put_legs + call_legs,
            "width": core.WING, "kind": "credit",
            "max_risk_rule": "width - credit (equal $5 wings)"}


def run_test(trades, spec):
    rows = []
    for t in trades:
        if "legs_file" not in t:
            rows.append({"skipped": t.get("skipped", "no legs"), "date": t["entry_day"]})
            continue
        legs = t["legs"]
        structure = legs_to_structure(legs, spec)
        minutes = core.load_minutes(t["legs_file"], [l["symbol"] for l in structure["legs"]])
        row = core.run_trade(minutes, structure, t["entry_day"], X1, t["last_day"])
        row["date"] = t["entry_day"]
        row["period"] = "development"
        rows.append(row)
    return rows


def report(rows, label):
    trades = [r for r in rows if "ret" in r]
    n = len(trades)
    if n == 0:
        print(f"{label}: 0 trades")
        return {"trades": 0}
    after = [r["ret"] - core.commission({"legs": [None] * r["n_legs"]}) / (100 * r["credit_or_debit"])
             for r in trades]
    profit = [100 * (r["exit_value"] - r["entry_value"])
              - core.commission({"legs": [None] * r["n_legs"]}) for r in trades]
    on_max_risk = [p / (100 * r["max_risk"]) for p, r in zip(profit, trades)]
    win_rate = sum(1 for p in profit if p > 0) / n
    avg_gross = statistics.mean(r["ret"] for r in trades)
    avg_after = statistics.mean(after)
    avg_on_mr = statistics.mean(on_max_risk)
    print(f"{label}: {n} trades, win rate {win_rate:.2%}, "
          f"avg gross return {avg_gross:+.2%}, avg after commission {avg_after:+.2%}, "
          f"avg return on max risk {avg_on_mr:+.2%}")
    return {"trades": n, "win_rate": win_rate, "avg_gross_return": avg_gross,
            "avg_return_after_commission": avg_after, "avg_return_on_max_risk": avg_on_mr}


def reprice_one_trade(trades):
    """Second, independent code path: re-read the raw DBN records for one
    trade's PCS(1.0) legs, pull the quotes at the entry minute and the
    engine's own exit minute by hand, and recompute the return without
    calling core.value()/core.run_trade() at all."""
    t = next(t for t in trades if "legs_file" in t)
    legs = t["legs"]
    structure = legs_to_structure(legs, "PCS(1.0)")
    minutes = core.load_minutes(t["legs_file"], [l["symbol"] for l in structure["legs"]])
    engine_row = core.run_trade(minutes, structure, t["entry_day"], X1, t["last_day"])

    df = db.DBNStore.from_file(t["legs_file"]).to_df()
    sp_sym, lp_sym = legs["symbols"]["short_put"], legs["symbols"]["long_put"]

    def quote_at(ts_str):
        import pandas as pd
        ts = pd.Timestamp(ts_str)
        rows = df[(df.index == ts) & (df["symbol"].isin([sp_sym, lp_sym]))]
        q = {r["symbol"]: (float(r["bid_px_00"]), float(r["ask_px_00"])) for _, r in rows.iterrows()}
        return q

    entry_q = quote_at(engine_row["entry_ts"])
    exit_q = quote_at(engine_row["exit_ts"])
    hand_entry_value = sum(qty * ((entry_q[sym][0] + entry_q[sym][1]) / 2)
                            for sym, qty in [(sp_sym, -1), (lp_sym, +1)])
    hand_exit_value = sum(qty * ((exit_q[sym][0] + exit_q[sym][1]) / 2)
                           for sym, qty in [(sp_sym, -1), (lp_sym, +1)])
    hand_credit = -hand_entry_value
    hand_x = -hand_exit_value
    hand_ret = (hand_credit - hand_x) / hand_credit

    print(f"\nreprice check — {t['entry_day']} {sp_sym.strip()}/{lp_sym.strip()}:")
    print(f"  engine: entry_value={engine_row['entry_value']:.4f} "
          f"exit_value={engine_row['exit_value']:.4f} ret={engine_row['ret']:.6f}")
    print(f"  hand:   entry_value={hand_entry_value:.4f} "
          f"exit_value={hand_exit_value:.4f} ret={hand_ret:.6f}")
    assert abs(hand_entry_value - engine_row["entry_value"]) < 0.001
    assert abs(hand_exit_value - engine_row["exit_value"]) < 0.001
    assert abs(hand_ret - engine_row["ret"]) < 0.001
    print("  MATCH within $0.001 / 0.1%")
    return {"date": t["entry_day"], "engine": engine_row,
            "hand_entry_value": hand_entry_value, "hand_exit_value": hand_exit_value,
            "hand_ret": hand_ret}


def check_build_structure_matches_pull(trades):
    """Free bonus check (no new download): for one already-downloaded
    date, rebuild PCS(1.0)/IC(1.0) from the raw chain snapshot through
    load_chain/pick_expiry/reference/boundary_strike/build_structure, and
    confirm the strikes match what todo_111_condor_pull.choose_legs already
    computed for that date."""
    t = next(t for t in trades if "legs_file" in t)
    entry_day = t["entry_day"]
    chain_path = f"{RD}/development/chain_{entry_day}.dbn.zst"
    if not os.path.exists(chain_path):
        print(f"\nbuild_structure cross-check: no chain snapshot for {entry_day}, skipped")
        return None
    chain = core.load_chain(chain_path)
    exp = core.pick_expiry(chain, entry_day, 30, 45, 37)
    ref = core.reference(chain, exp)
    ic = core.build_structure(chain, exp, ref, "IC(1.0)")
    ok = (not isinstance(ic, str) and exp == t["legs"]["expiration"] and
          {l["strike"] for l in ic["legs"] if l["role"] == "short_put"} == {t["legs"]["short_put"]} and
          {l["strike"] for l in ic["legs"] if l["role"] == "long_put"} == {t["legs"]["long_put"]} and
          {l["strike"] for l in ic["legs"] if l["role"] == "short_call"} == {t["legs"]["short_call"]} and
          {l["strike"] for l in ic["legs"] if l["role"] == "long_call"} == {t["legs"]["long_call"]})
    print(f"\nbuild_structure cross-check ({entry_day}): "
          f"{'MATCH' if ok else 'MISMATCH'} vs todo_111_condor_pull.choose_legs")
    if not ok:
        print(f"  pull: {t['legs']}")
        print(f"  core: expiry={exp} ic={ic}")
    return {"date": entry_day, "match": bool(ok)}


def main():
    trades = json.load(open(f"{RD}/development_trades.json"))
    os.makedirs(OUT_DIR, exist_ok=True)

    pcs_rows = run_test(trades, "PCS(1.0)")
    test1 = report(pcs_rows, "Test #1  V2 / PCS(1.0) / X1")

    ic_rows = run_test(trades, "IC(1.0)")
    test7 = report(ic_rows, "Test #7  V2 / IC(1.0) / X1")

    reprice = reprice_one_trade(trades)
    structure_check = check_build_structure_matches_pull(trades)

    out = {"test_1_pcs_x1": test1, "test_7_ic_x1": test7,
           "reprice_check": {k: v for k, v in reprice.items() if k != "engine"} | {
               "engine_entry_value": reprice["engine"]["entry_value"],
               "engine_exit_value": reprice["engine"]["exit_value"],
               "engine_ret": reprice["engine"]["ret"]},
           "build_structure_cross_check": structure_check}
    json.dump(out, open(f"{OUT_DIR}/validation.json", "w"), indent=1, default=str)
    print(f"\nwrote {OUT_DIR}/validation.json")


if __name__ == "__main__":
    main()
