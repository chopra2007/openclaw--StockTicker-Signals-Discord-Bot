"""TODO #111 tournament — sealed-period preparation. The loaded gun, not the
trigger.

FROZEN-MATRIX: "The sealed period stays shut until every finalist is frozen."
This file has two entry points and they are NOT equally locked:

  build_manifest(finalist_ids) — may read a sealed CHAIN snapshot once one
    exists on disk (needed to pick strikes for a leg-minute purchase, the
    same job todo_111_tourney_select.py does for development). A chain
    snapshot is a structural quote, not a trade outcome. This function
    NEVER reads a leg-minute file and NEVER computes a return. If a
    sealed-period trigger needs option data to even know which dates fire
    (S1/S2 — see skew_dates_for_sealed()) and the chain data to compute
    that isn't fully on disk yet, it declares the full sealed grid's chain
    snapshots as needed rather than guessing a subset.

  run_evaluation(finalist_ids) — the only function in this whole tournament
    codebase allowed to read a sealed leg-minute file or call
    core.run_trade() on a sealed date. It refuses to run unless given a
    non-empty, EXPLICIT list of finalist test ids — no default, no "all
    funded tests" fallback, at both the CLI and the function-call level.
    It records that exact list plus a UTC timestamp in results_sealed.json,
    so the output file itself is the proof the finalists were fixed before
    any sealed outcome was read.

Neither function downloads anything — both only read files already on disk,
or report what is still missing. Reuses todo_111_tourney_select.py (chain
reading, expiry/strike/structure selection) and todo_111_tourney_run.py
(leg-file lookup, the midpoint-fill call, cheap-rejection check) as library
functions, unmodified — this file only adds the sealed-scoped wiring.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import todo_111_tourney_core as core        # noqa: E402
import todo_111_tourney_select as tsel      # noqa: E402
import todo_111_tourney_run as trun         # noqa: E402

TOURNEY = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
FROZEN_PATH = f"{TOURNEY}/frozen_matrix.json"
TRIGGERS_PATH = f"{TOURNEY}/trigger_dates.json"
OWNED_INDEX_PATH = f"{TOURNEY}/owned_index.json"
SELECTION_OUT = f"{TOURNEY}/selection_sealed.json"
MANIFEST_OUT = f"{TOURNEY}/manifest_sealed.json"
RESULTS_OUT = f"{TOURNEY}/results_sealed.json"

DEV_START, DEV_END = "2014-01-01", "2021-12-31"
SEALED_START, SEALED_END = "2022-01-01", "2026-08-31"
SKEW_TRIGGERS = {"S1", "S2"}


# ------------------------------------------------------------------- grids

def _grid(trig: dict, lo: str, hi: str):
    sig = trig["signal"]
    rows = [(sd, v["entry_day"], v["cap_day_14"], v["cap_day_7"])
            for sd, v in sig.items() if lo <= sd <= hi]
    return sorted(rows)


def dev_grid(trig: dict):
    return _grid(trig, DEV_START, DEV_END)


def sealed_grid(trig: dict):
    return _grid(trig, SEALED_START, SEALED_END)


def skew_dates_for_sealed(trig: dict):
    """S1/S2 fire dates within the sealed period.

    Frozen matrix 0.10: S1/S2 are ranked against an EXPANDING history of
    prior entries — that window never resets, so a sealed date's reading is
    ranked against every earlier reading back to the start of development.
    The only way to know which sealed dates fire is to compute the reading
    at every grid date, development through sealed, in order — there is no
    way to pick a subset in advance. Reuses todo_111_tourney_select.py's
    compute_skew_triggers() unmodified, on the combined dev+sealed grid.

    Returns (sealed_s1_dates, sealed_s2_dates, still_missing) where
    still_missing is the count of grid dates (development AND sealed) whose
    chain snapshot is not yet on disk — while that is above 0, the returned
    date lists are provisional and must not be trusted as final.
    """
    combined = dev_grid(trig) + sealed_grid(trig)
    s1, s2, missing, _n = tsel.compute_skew_triggers(combined)
    return ([d for d in s1 if d >= SEALED_START],
            [d for d in s2 if d >= SEALED_START],
            missing)


# --------------------------------------------------------------- manifest

def build_manifest(finalist_ids):
    """Build the sealed selection for exactly these test ids and write
    manifest_sealed.json (the pull script's manifest shape) — chain days
    and leg contracts, nothing for any test not in finalist_ids. Reads a
    sealed chain snapshot only where one is already on disk; never reads a
    leg-minute file. Returns {"selection": ..., "manifest": ...}.
    """
    if not finalist_ids:
        raise ValueError("build_manifest requires a non-empty, explicit list "
                          "of finalist test ids — no default, no 'all tests'.")
    finalist_ids = list(finalist_ids)

    frozen = json.load(open(FROZEN_PATH))
    trig = json.load(open(TRIGGERS_PATH))
    sig = trig["signal"]
    triggers = dict(trig["triggers"])
    tests_by_id = {t["test_id"]: t for t in frozen["tests"]}

    needs_skew = any(tests_by_id[tid]["trigger"] in SKEW_TRIGGERS for tid in finalist_ids)
    skew_missing = 0
    if needs_skew:
        s1, s2, skew_missing = skew_dates_for_sealed(trig)
        triggers["S1"] = {"sealed": s1}
        triggers["S2"] = {"sealed": s2}
        if skew_missing:
            print(f"NOTE: {skew_missing} grid dates (development + sealed) still need "
                  f"a chain snapshot before S1/S2 sealed fire dates can be trusted. "
                  f"Declaring the full sealed grid's chain snapshots as needed for any "
                  f"S1/S2 finalist rather than guessing a subset.")

    sgrid = sealed_grid(trig)
    selection: dict = {}
    manifest_legs: dict = {}
    manifest_chain_days: set = set()
    table_rows = []

    for tid in finalist_ids:
        t = tests_by_id[tid]
        trig_code, struct_code = t["trigger"], t["structure"]
        cap_days = t["exit"]["cap_days"]

        if trig_code in SKEW_TRIGGERS and skew_missing:
            for _sd, entry_day, _c14, _c7 in sgrid:
                manifest_chain_days.add(entry_day)
            selection[str(tid)] = {
                "trigger": trig_code, "structure": struct_code,
                "mechanism_id": t["mechanism_id"], "dates": {},
                "blocked": f"{skew_missing} grid dates still need a chain snapshot "
                           f"before {trig_code} sealed fire dates can be trusted",
            }
            table_rows.append((tid, trig_code, struct_code, 0, 0, 0, 0, "BLOCKED"))
            continue

        dates = triggers.get(trig_code, {}).get("sealed", [])
        per_date, built_n, missing_n, skip_n = {}, 0, 0, 0
        for sd in dates:
            v = sig.get(sd)
            if v is None:
                continue
            entry_day = v["entry_day"]
            manifest_chain_days.add(entry_day)
            status, payload = tsel.structure_for(entry_day, struct_code)
            if status == "skip":
                if payload == "chain snapshot missing":
                    missing_n += 1
                else:
                    skip_n += 1
                per_date[entry_day] = {"signal_date": sd, "skipped": payload}
                continue
            built_n += 1
            symbols = [l["symbol"] for l in payload["legs"]]
            per_date[entry_day] = {
                "signal_date": sd, "expiration": payload["expiration"],
                "spot": payload["spot"], "expected_move": payload["expected_move"],
                "strikes": {l["role"]: l["strike"] for l in payload["legs"]},
                "leg_symbols": symbols,
            }
            end_day = v["cap_day_14"] if cap_days == 14 else v["cap_day_7"]
            slot = manifest_legs.setdefault(entry_day, {"symbols": set(), "end_day": None})
            slot["symbols"].update(symbols)
            if slot["end_day"] is None or end_day > slot["end_day"]:
                slot["end_day"] = end_day

        selection[str(tid)] = {"trigger": trig_code, "structure": struct_code,
                                "mechanism_id": t["mechanism_id"], "dates": per_date}
        table_rows.append((tid, trig_code, struct_code, len(dates), built_n,
                            missing_n, skip_n, "ok"))

    json.dump(selection, open(SELECTION_OUT, "w"), indent=1, default=str)
    manifest = {"label": "sealed-finalists",
                "chain_days": sorted(manifest_chain_days),
                "legs": {d: {"symbols": sorted(v["symbols"]), "end_day": v["end_day"]}
                         for d, v in manifest_legs.items()}}
    json.dump(manifest, open(MANIFEST_OUT, "w"), indent=1)

    print(f"sealed manifest for finalists {finalist_ids}:")
    print(f"{'test':>4} {'trigger':>7} {'structure':>10} {'fired':>6} {'built':>6} "
          f"{'chain_missing':>13} {'skip':>5} {'status':>8}")
    for row in table_rows:
        print(f"{row[0]:>4} {row[1]:>7} {row[2]:>10} {row[3]:>6} {row[4]:>6} "
              f"{row[5]:>13} {row[6]:>5} {row[7]:>8}")
    total_contract_days = sum(len(v["symbols"]) for v in manifest["legs"].values())
    print(f"\nmanifest: {len(manifest['chain_days'])} chain snapshots needed, "
          f"{len(manifest['legs'])} entry days with resolvable legs so far, "
          f"{total_contract_days} contract-days")
    print(f"wrote {SELECTION_OUT}")
    print(f"wrote {MANIFEST_OUT}")
    return {"selection": selection, "manifest": manifest}


# -------------------------------------------------------------- evaluation

def run_evaluation(finalist_ids):
    """Run the frozen finalists against sealed leg-minute data and write
    results_sealed.json, in the same row shape as results_dev.json.

    Refuses to run unless finalist_ids is a non-empty, explicitly passed
    list — this is the safeguard, not a formality: this function is the
    only place in the tournament codebase that reads a sealed leg-minute
    file or calls core.run_trade() on a sealed date. The output records
    the exact finalist list and a UTC timestamp, so the file itself proves
    the finalists were fixed before this ran.
    """
    if not finalist_ids:
        raise ValueError("run_evaluation refuses to run: finalist_ids must be a "
                          "non-empty, EXPLICITLY passed list. No default, no "
                          "'all tests'. This is the only function allowed to "
                          "read sealed leg-minute data — it will not guess.")
    finalist_ids = list(finalist_ids)
    frozen_at = datetime.now(timezone.utc).isoformat()

    frozen = json.load(open(FROZEN_PATH))
    trig = json.load(open(TRIGGERS_PATH))
    selection = json.load(open(SELECTION_OUT))
    owned_index = json.load(open(OWNED_INDEX_PATH))
    trun.build_file_symbol_index(owned_index)
    sig = trig["signal"]
    exits = frozen["exits"]
    tests_by_id = {t["test_id"]: t for t in frozen["tests"]}

    rows = []
    for tid in finalist_ids:
        t = tests_by_id[tid]
        struct_code, trig_code = t["structure"], t["trigger"]
        exit_code = t["exit_code"]
        exit_rule = exits[exit_code]
        cap_days = exit_rule["cap_days"]
        sel = selection.get(str(tid), {})
        dates = sel.get("dates", {})

        trade_rows = []
        no_minutes_yet = 0
        for entry_day, rec in dates.items():
            sd = rec["signal_date"]
            if "skipped" in rec:
                trade_rows.append({"skipped": rec["skipped"], "date": entry_day, "period": "sealed"})
                continue
            structure = trun.structure_from_selection(rec, struct_code, rec["expiration"])
            files_and_symbols = trun.owned_files_for(entry_day, rec["leg_symbols"], owned_index)
            if files_and_symbols is None:
                no_minutes_yet += 1
                trade_rows.append({"skipped": "no minute data yet (leg download pending)",
                                    "date": entry_day, "period": "sealed"})
                continue
            minutes = trun.load_minutes_merged(files_and_symbols)
            v = sig[sd]
            cap_day = v["cap_day_14"] if cap_days == 14 else v["cap_day_7"]
            row = core.run_trade(minutes, structure, entry_day,
                                  {"target": exit_rule["target"], "stop": exit_rule["stop"]}, cap_day)
            row["date"], row["period"] = entry_day, "sealed"
            trade_rows.append(row)

        structure_kind = trun.kind_for_code(struct_code)
        summary = core.summarise(trade_rows, structure_kind, dates=list(dates.keys()))
        summary["no_minute_data_yet"] = no_minutes_yet
        cheap = trun.apply_cheap_rejection(summary)

        rows.append({
            "test_id": tid, "mechanism": t["mechanism"], "mechanism_id": t["mechanism_id"],
            "trigger": trig_code, "structure": struct_code, "expiry_window": t["expiry_window"],
            "strikes_rule": trun.strikes_rule_for(struct_code), "exit_code": exit_code,
            "exit_rule": exit_rule,
            "databento_cost_usd_estimate": trun.databento_cost_estimate(sel, dates),
            **summary,
            "cheap_rejection_triggered": cheap,
            "verdict": "REJECTED" if cheap else "PROMISING, NOT PROVEN",
        })

    out = {
        "frozen_finalist_ids": finalist_ids,
        "frozen_at_utc": frozen_at,
        "note": "sealed-period rows only, same row shape as results_dev.json — "
                "compare field by field against the development row for the same "
                "test_id, which this file does not repeat.",
        "rows": rows,
    }
    json.dump(out, open(RESULTS_OUT, "w"), indent=1, default=str)

    print(f"sealed evaluation for finalists {finalist_ids}, frozen_at_utc={frozen_at}")
    for r in rows:
        print(f"  test {r['test_id']:>3} {r['structure']:>10} {r['exit_code']:>3}: "
              f"sealed_trades={r['sealed_trades']} no_data={r['no_minute_data_yet']} "
              f"win_rate={r['win_rate']} avg_after_commission={r['avg_return_after_commission']} "
              f"verdict={r['verdict']}")
    print(f"wrote {RESULTS_OUT}")
    return out


# ----------------------------------------------------------------------- CLI

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("manifest", help="build sealed selection + manifest_sealed.json "
                                          "(reads chain snapshots only, never leg data)")
    p1.add_argument("finalist_ids", type=int, nargs="+",
                     help="the frozen finalist test ids — explicit, no default")

    p2 = sub.add_parser("evaluate", help="run the sealed evaluation and write "
                                          "results_sealed.json (reads sealed leg data)")
    p2.add_argument("finalist_ids", type=int, nargs="+",
                     help="the frozen finalist test ids — explicit, no default")

    args = ap.parse_args()
    if args.cmd == "manifest":
        build_manifest(args.finalist_ids)
    elif args.cmd == "evaluate":
        run_evaluation(args.finalist_ids)
