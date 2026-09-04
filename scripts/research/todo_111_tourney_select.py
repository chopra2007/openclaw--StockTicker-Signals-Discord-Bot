"""TODO #111 tournament — selection: pick expiries, strikes and legs for every
development-period test in mechanisms 1-4. No downloads, no trade outcomes.

Reads only what is already on disk:
  - trigger_dates.json          (the free trigger signal-date lists)
  - frozen_matrix.json          (the 58 frozen tests, machine-readable)
  - whole-chain entry-minute snapshots, wherever chain_path() in
    todo_111_tourney_pull.py finds them (old condor folder or
    .../todo-111-tournament/chains/)

Mechanisms 1-3 (tests 1-34) use the free triggers already in trigger_dates.json
(V0, V2, C1, C2, C3, U1, U2, D1, D2). Mechanism 4 (tests 35-42) uses S1/S2,
which are NOT free — the skew ratio needs the chain snapshot itself, at every
grid date, ranked against an EXPANDING window of prior readings (frozen
matrix 0.10). This script computes S1/S2 itself, over the development grid,
before running the 58-test loop; see compute_skew_triggers().

A missing chain snapshot (a whole-chain download is still filling in gaps as
this script runs) is not a failure: the date is skipped and counted, both in
the skew-trigger scan and in the per-test structure build.

Writes:
  - selection_dev.json      per test id, per entry day: expiry/spot/strikes/
    legs, or the skip reason
  - manifest_dev_legs.json  in todo_111_tourney_pull.py's manifest shape,
    ready to hand to that script for pricing and download
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
import todo_111_tourney_core as core  # noqa: E402
from todo_111_tourney_pull import chain_path  # noqa: E402

TOURNEY = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
FROZEN_PATH = f"{TOURNEY}/frozen_matrix.json"
TRIGGERS_PATH = f"{TOURNEY}/trigger_dates.json"
SELECTION_OUT = f"{TOURNEY}/selection_dev.json"
MANIFEST_OUT = f"{TOURNEY}/manifest_dev_legs.json"

DTE_LO, DTE_HI, DTE_TARGET = 30, 45, 37   # the 'std' window — every test in
                                          # mechanisms 1-4 uses it
MIN_PRIOR = 40                            # S1/S2: minimum prior readings
PCTL = 0.20                               # S1/S2: top/bottom 20%
DEV_END = "2021-12-31"                    # development = discovery+confirmation

# Owner's call (2026-09-04): these triggers are structurally too rare to ever
# clear the 30-trade floor (C3 fires 6x, D2 fires 10x on the whole dev grid).
# Still SELECT and record them so they appear honestly in the table, but
# never fund them — leave their legs out of the manifest.
NO_FUND_TEST_IDS = {21, 22, 24, 31, 32}


# --------------------------------------------------------------- chain cache

_chain_cache: dict = {}


def get_chain(entry_day: str):
    """load_chain(), cached; None (and cached as such) if the snapshot isn't
    on disk yet."""
    if entry_day in _chain_cache:
        return _chain_cache[entry_day]
    path = chain_path(entry_day)
    chain = core.load_chain(path) if os.path.exists(path) else None
    _chain_cache[entry_day] = chain
    return chain


# ------------------------------------------------------------- S1/S2 (skew)

def skew_ratio(entry_day: str):
    """mid(short put @ m=1.0) / mid(short call @ m=1.0) on the 'std' expiry,
    or None if the chain snapshot, the expiry, the parity spot, or either
    boundary strike isn't available."""
    chain = get_chain(entry_day)
    if chain is None:
        return None
    exp = core.pick_expiry(chain, entry_day, DTE_LO, DTE_HI, DTE_TARGET)
    if exp is None:
        return None
    ref = core.reference(chain, exp)
    if ref is None:
        return None
    sp = core.boundary_strike(chain, exp, ref, 1.0, "put")
    sc = core.boundary_strike(chain, exp, ref, 1.0, "call")
    if sp is None or sc is None:
        return None
    put_q, call_q = chain[exp][sp]["P"], chain[exp][sc]["C"]
    call_mid = core.mid(call_q.bid, call_q.ask)
    if call_mid <= 0:
        return None
    return core.mid(put_q.bid, put_q.ask) / call_mid


def compute_skew_triggers(grid):
    """S1/S2 fire dates over the development grid, in date order.

    Expanding window: a date's reading is ranked only against EARLIER
    readings (min 40), never later ones. Percentile method: sort the prior
    readings ascending (n of them); the value at index floor(0.8n) stands in
    for the 80th percentile (S1: today's reading >= it), and the value at
    index floor(0.2n) for the 20th (S2: today's reading <= it). A date that
    itself has no usable reading (missing/unusable chain) is never a
    trigger date and contributes nothing to the history.

    Returns (s1_dates, s2_dates, n_missing, n_usable_readings) — the two
    date lists are signal dates (matching the free-trigger lists' shape).
    """
    readings: list[float] = []
    s1_dates, s2_dates = [], []
    missing = 0
    for sd, entry_day, _cap14, _cap7 in grid:
        r = skew_ratio(entry_day)
        if r is None:
            missing += 1
            continue
        if len(readings) >= MIN_PRIOR:
            prior = sorted(readings)
            n = len(prior)
            hi = prior[min(n - 1, int((1 - PCTL) * n))]
            lo = prior[int(PCTL * n)]
            if r >= hi:
                s1_dates.append(sd)
            elif r <= lo:
                s2_dates.append(sd)
        readings.append(r)
    return s1_dates, s2_dates, missing, len(readings)


# --------------------------------------------------------------- structures

_structure_cache: dict = {}


def structure_for(entry_day: str, structure_code: str):
    """('ok', payload) or ('skip', reason). Cached per (entry_day, code) so
    tests that share a structure (e.g. PCS(1.0) in tests 1, 10, 11, 12) only
    build it once."""
    key = (entry_day, structure_code)
    if key in _structure_cache:
        return _structure_cache[key]

    chain = get_chain(entry_day)
    if chain is None:
        result = ("skip", "chain snapshot missing")
    else:
        exp = core.pick_expiry(chain, entry_day, DTE_LO, DTE_HI, DTE_TARGET)
        if exp is None:
            result = ("skip", "no listed expiry in the 30-45 day window")
        else:
            ref = core.reference(chain, exp)
            if ref is None:
                result = ("skip", "no strike with both a call and a put (no parity spot)")
            else:
                built = core.build_structure(chain, exp, ref, structure_code)
                if isinstance(built, str):
                    result = ("skip", built)
                else:
                    result = ("ok", {
                        "expiration": exp, "spot": ref["spot"],
                        "atm_strike": ref["atm_strike"], "expected_move": ref["expected_move"],
                        "legs": built["legs"], "kind": built["kind"], "width": built["width"],
                    })
    _structure_cache[key] = result
    return result


# ----------------------------------------------------------------------- main

def dev_grid(trig: dict):
    """[(signal_date, entry_day, cap_day_14, cap_day_7), ...] for the
    development period, in date order."""
    sig = trig["signal"]
    rows = [(sd, v["entry_day"], v["cap_day_14"], v["cap_day_7"])
            for sd, v in sig.items() if sd <= DEV_END]
    return sorted(rows)


def main():
    frozen = json.load(open(FROZEN_PATH))
    trig = json.load(open(TRIGGERS_PATH))
    sig = trig["signal"]
    grid = dev_grid(trig)

    print(f"development grid: {len(grid)} candidate weeks")
    print("computing S1/S2 skew triggers over the grid (needs a chain "
          "snapshot at every candidate date)...")
    s1_dates, s2_dates, skew_missing, n_readings = compute_skew_triggers(grid)
    triggers = dict(trig["triggers"])
    triggers["S1"] = {"development": s1_dates}
    triggers["S2"] = {"development": s2_dates}
    print(f"  S1 fired {len(s1_dates)}x, S2 fired {len(s2_dates)}x "
          f"({n_readings} usable skew readings, {skew_missing} grid dates "
          f"had no usable chain snapshot yet)\n")

    tests = [t for t in frozen["tests"] if t["mechanism_id"] in (1, 2, 3, 4)]

    selection: dict = {}
    manifest_legs: dict = defaultdict(lambda: {"symbols": set(), "end_day": None})
    manifest_chain_days: set = set()
    table_rows = []

    for t in tests:
        tid, trig_code, struct_code = t["test_id"], t["trigger"], t["structure"]
        cap_days = t["exit"]["cap_days"]
        fund = tid not in NO_FUND_TEST_IDS
        dates = triggers.get(trig_code, {}).get("development", [])
        per_date, skip_reasons = {}, Counter()
        missing_n = 0
        built_n = 0

        for sd in dates:
            v = sig.get(sd)
            if v is None:
                skip_reasons["signal date not in the grid"] += 1
                continue
            entry_day = v["entry_day"]
            status, payload = structure_for(entry_day, struct_code)
            if status == "skip":
                if payload == "chain snapshot missing":
                    missing_n += 1
                else:
                    skip_reasons[payload] += 1
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
            if fund:
                end_day = v["cap_day_14"] if cap_days == 14 else v["cap_day_7"]
                manifest_chain_days.add(entry_day)
                slot = manifest_legs[entry_day]
                slot["symbols"].update(symbols)
                if slot["end_day"] is None or end_day > slot["end_day"]:
                    slot["end_day"] = end_day

        selection[tid] = {"trigger": trig_code, "structure": struct_code,
                           "mechanism_id": t["mechanism_id"], "dates": per_date,
                           "funded": fund,
                           "not_funded_reason": None if fund else
                           "trigger too rare to ever clear the 30-trade "
                           "development floor; recorded but not funded"}
        table_rows.append((tid, t["mechanism_id"], trig_code, struct_code,
                            len(dates), built_n, missing_n,
                            len(dates) - built_n - missing_n,
                            skip_reasons.most_common(3), fund))

    json.dump(selection, open(SELECTION_OUT, "w"), indent=1, default=str)

    manifest = {"label": "mechanisms-1-4-development",
                "chain_days": sorted(manifest_chain_days),
                "legs": {d: {"symbols": sorted(v["symbols"]), "end_day": v["end_day"]}
                         for d, v in manifest_legs.items()}}
    json.dump(manifest, open(MANIFEST_OUT, "w"), indent=1)

    total_contract_days = sum(len(v["symbols"]) for v in manifest["legs"].values())

    print(f"{'test':>4} {'mech':>4} {'trigger':>7} {'structure':>10} "
          f"{'fired':>6} {'built':>6} {'missing':>7} {'skipped':>7} {'funded':>6}  "
          f"top build-skip reasons")
    for tid, mech, trig_code, struct_code, fired, built_n, missing_n, skipped, reasons, fund in table_rows:
        rs = "; ".join(f"{r} x{c}" for r, c in reasons)
        print(f"{tid:>4} {mech:>4} {trig_code:>7} {struct_code:>10} "
              f"{fired:>6} {built_n:>6} {missing_n:>7} {skipped:>7} "
              f"{('yes' if fund else 'NO'):>6}  {rs}")

    print(f"\nmanifest: {len(manifest['legs'])} entry days, "
          f"{total_contract_days} distinct contract-days requested "
          f"(symbol x entry-day pairs; each still spans entry->end_day of "
          f"actual minutes once downloaded)")
    print(f"wrote {SELECTION_OUT}")
    print(f"wrote {MANIFEST_OUT}")


if __name__ == "__main__":
    main()
