"""TODO #111 tournament — turn selection into results.

For the development period only (the sealed grid stays shut per FROZEN-MATRIX
"The sealed period stays shut until every finalist is frozen" — this script
never reads it), runs every FUNDED test in mechanisms 1-4 through the
midpoint-fill engine, using only the leg-minute files already on disk. A date
whose legs aren't owned yet is counted separately from a date selection
already could not build a structure for — the download is still in progress,
this is not a failure.

Reads:
  - frozen_matrix.json    (the 58 frozen tests + the named exit sets)
  - trigger_dates.json    (entry_day / cap_day_14 / cap_day_7 per signal date)
  - selection_dev.json    (built legs or skip reason, per test, per date)
  - owned_index.json      (which symbols already have minute data, and where)

Writes results_dev.json: one row per test (all 42, mechanisms 1-4), every
section-8 field plus the frozen-matrix-row metadata, section 9's cheap
rejection rules (which one killed it, if any), and section 10's finalist
conditions as booleans with reasons. Verdict is capped at REJECTED /
"PROMISING, NOT PROVEN" here — FINALIST is the owner's call, and HISTORICAL
WINNER needs sealed trades this script never touches.

Downloads nothing. Spends nothing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict, OrderedDict

sys.path.insert(0, os.path.dirname(__file__))
import todo_111_tourney_core as core  # noqa: E402

TOURNEY = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
FROZEN_PATH = f"{TOURNEY}/frozen_matrix.json"
TRIGGERS_PATH = f"{TOURNEY}/trigger_dates.json"
SELECTION_PATH = f"{TOURNEY}/selection_dev.json"
OWNED_INDEX_PATH = f"{TOURNEY}/owned_index.json"
RESULTS_OUT = f"{TOURNEY}/results_dev.json"

DISCOVERY_END = "2018-12-31"
CONFIRMATION_END = "2021-12-31"

NO_FUND_TEST_IDS = {21, 22, 24, 31, 32}
NO_FUND_REASONS = {
    21: "sample too small to ever qualify — the trigger fires on 6 development dates against a 30-trade floor",
    22: "sample too small to ever qualify — the trigger fires on 6 development dates against a 30-trade floor",
    24: "sample too small to ever qualify — the trigger fires on 6 development dates against a 30-trade floor",
    31: "sample too small to ever qualify — the trigger fires on 10 development dates against a 30-trade floor",
    32: "sample too small to ever qualify — the trigger fires on 10 development dates against a 30-trade floor",
}

# Frozen matrix 0.11, in plain words, for the section-8 'strikes_rule' field.
STRIKES_RULE = {
    "PCS": "sell put at boundary m, buy put $5 lower (expected-move boundary)",
    "CCS": "sell call at boundary m, buy call $5 higher (expected-move boundary)",
    "IC": "PCS(m) + CCS(m)",
    "STRAD": "buy ATM call + buy ATM put",
    "STRANG": "buy call at boundary m + buy put at boundary m",
    "CDS": "buy ATM call, sell call at boundary m=0.6",
    "PDS": "buy ATM put, sell put at boundary m=0.6",
    "LONG_PUT": "buy one put (ATM or at boundary m)",
    "RR+": "PCS(1.0) + CDS",
    "RR-": "CCS(1.0) + PDS",
}


def strikes_rule_for(code: str) -> str:
    m = re.match(r"^([A-Z_]+)\(([^)]+)\)$", code)
    head = m.group(1) if m else code
    rule = STRIKES_RULE.get(head, "?")
    return f"{rule} (m={m.group(2)})" if m and head in ("PCS", "CCS", "IC", "STRANG", "LONG_PUT") else rule


def period_of(signal_date: str) -> str:
    if signal_date <= DISCOVERY_END:
        return "discovery"
    if signal_date <= CONFIRMATION_END:
        return "confirmation"
    raise ValueError(f"{signal_date} is outside the development period — "
                      "the sealed grid is locked and this script must never touch it")


# ------------------------------------------------------------ owned minutes

def owned_files_for(entry_day: str, symbols: list, owned_index: dict):
    """{file: [symbols in that file]} if EVERY symbol is owned for this day,
    else None."""
    day_idx = owned_index.get(entry_day, {})
    by_file: dict = defaultdict(list)
    for s in symbols:
        rec = day_idx.get(s)
        if rec is None:
            return None
        by_file[rec["file"]].append(s)
    return dict(by_file)


_minutes_cache: "OrderedDict[str, dict]" = OrderedDict()
_MINUTES_CACHE_MAX = 300   # LRU-bounded: the full leg set is 380+ files and
                           # each one's minute book is sizeable; caching every
                           # file forever OOM-killed a run at ~2.4GB RSS once
                           # the leg download grew past the original 246
_file_all_symbols: dict = {}   # path -> every symbol owned_index says lives there


def _cache_get_or_load(path: str) -> dict:
    if path in _minutes_cache:
        _minutes_cache.move_to_end(path)
        return _minutes_cache[path]
    book = core.load_minutes(path, _file_all_symbols[path])
    _minutes_cache[path] = book
    if len(_minutes_cache) > _MINUTES_CACHE_MAX:
        _minutes_cache.popitem(last=False)
    return book


def build_file_symbol_index(owned_index: dict):
    """Reverse owned_index once: file -> the full set of symbols it holds.
    Many tests in the same mechanism share one leg file (16 tests in
    mechanism 1 all read the same 246 condor-pull files, just different
    subsets of their 4 legs) — loading by FILE, not by the subset a given
    structure happens to need, is what makes load_minutes() actually cache
    instead of re-reading and re-holding the same file's DataFrame in memory
    once per distinct subset (this OOM-killed the first run at ~3.5GB RSS)."""
    for day_idx in owned_index.values():
        for sym, rec in day_idx.items():
            _file_all_symbols.setdefault(rec["file"], set()).add(sym)


def load_minutes_merged(files_and_symbols: dict) -> dict:
    """Merge load_minutes() across however many files a structure's legs are
    split over (normally one), through the LRU-bounded cache."""
    paths = list(files_and_symbols)
    if len(paths) == 1:
        return _cache_get_or_load(paths[0])
    merged: dict = defaultdict(dict)
    for path in paths:
        for ts, book in _cache_get_or_load(path).items():
            merged[ts].update(book)
    return dict(merged)


def kind_for_code(code: str) -> str:
    head = re.match(r"^([A-Z_]+)", code).group(1)
    if head in ("PCS", "CCS", "IC"):
        return "credit"
    if code in ("RR+", "RR-"):
        return "net"
    return "debit"  # STRAD, STRANG, CDS, PDS, LONG_PUT


def structure_from_selection(date_rec: dict, structure_code: str, exp: str):
    """Rebuild the structure dict run_trade() needs from selection_dev.json's
    already-recorded strikes (role -> strike) and leg_symbols (in the same
    order build_structure produced them), without re-reading the chain."""
    strikes = date_rec["strikes"]
    symbols = date_rec["leg_symbols"]
    role_by_cp_sign = {
        "short_put": ("P", -1), "long_put": ("P", +1),
        "short_call": ("C", -1), "long_call": ("C", +1),
    }
    legs = []
    for (role, strike), sym in zip(strikes.items(), symbols):
        cp, qty = role_by_cp_sign[role]
        legs.append({"symbol": sym, "strike": strike, "cp": cp, "qty": qty, "role": role})
    kind = kind_for_code(structure_code)
    width = core.WING if kind == "credit" else None
    return {"code": structure_code, "expiration": exp, "legs": legs, "width": width, "kind": kind}


# ----------------------------------------------------------- cheap rejection

CHEAP_RULES = [
    ("fewer than 30 development trades",
     lambda s: (s["dev_trades"] or 0) < 30),
    ("average commission-adjusted return at or below zero",
     lambda s: s["avg_return_after_commission"] is not None and s["avg_return_after_commission"] <= 0),
    ("profit factor below 1.00",
     lambda s: s["profit_factor"] is not None and s["profit_factor"] < 1.0),
    ("the single best trade supplies more than 50% of all positive profit",
     lambda s: s["profit_share_best_trade"] is not None and s["profit_share_best_trade"] > 0.5),
    ("the single best calendar year supplies more than 80% of all positive profit",
     lambda s: s["profit_share_best_year"] is not None and s["profit_share_best_year"] > 0.8),
    ("discovery and confirmation disagree in sign",
     lambda s: _sign_disagrees(s)),
]


def _sign_disagrees(s):
    dvc = s["discovery_vs_confirmation"]
    da, ca = dvc["discovery"]["avg_after_commission"], dvc["confirmation"]["avg_after_commission"]
    if da is None or ca is None:
        return False
    return (da > 0) != (ca > 0) and da != 0 and ca != 0


def apply_cheap_rejection(summary: dict):
    triggered = [name for name, fn in CHEAP_RULES if fn(summary)]
    return triggered


# ------------------------------------------------------------------ one test

def run_test(t: dict, selection: dict, sig: dict, owned_index: dict, exits: dict):
    tid = t["test_id"]
    struct_code, trig_code = t["structure"], t["trigger"]
    exit_code = t["exit_code"]
    exit_rule = exits[exit_code]
    cap_days = exit_rule["cap_days"]
    sel = selection.get(str(tid), {})
    dates = sel.get("dates", {})

    rows = []
    no_minutes_yet = 0
    for entry_day, rec in dates.items():
        sd = rec["signal_date"]
        if "skipped" in rec:
            rows.append({"skipped": rec["skipped"], "date": entry_day, "period": period_of(sd)})
            continue
        structure = structure_from_selection(rec, struct_code, rec["expiration"])
        files_and_symbols = owned_files_for(entry_day, rec["leg_symbols"], owned_index)
        if files_and_symbols is None:
            no_minutes_yet += 1
            rows.append({"skipped": "no minute data yet (leg download pending)",
                         "date": entry_day, "period": period_of(sd)})
            continue
        minutes = load_minutes_merged(files_and_symbols)
        v = sig[sd]
        cap_day = v["cap_day_14"] if cap_days == 14 else v["cap_day_7"]
        row = core.run_trade(minutes, structure, entry_day,
                              {"target": exit_rule["target"], "stop": exit_rule["stop"]}, cap_day)
        row["date"], row["period"] = entry_day, period_of(sd)
        rows.append(row)

    structure_kind = kind_for_code(struct_code)
    summary = core.summarise(rows, structure_kind, dates=list(dates.keys()))
    summary["no_minute_data_yet"] = no_minutes_yet

    cheap = apply_cheap_rejection(summary)
    survives_cheap = len(cheap) == 0
    positive_both = (
        summary["discovery_vs_confirmation"]["discovery"]["avg_after_commission"] is not None and
        summary["discovery_vs_confirmation"]["confirmation"]["avg_after_commission"] is not None and
        summary["discovery_vs_confirmation"]["discovery"]["avg_after_commission"] > 0 and
        summary["discovery_vs_confirmation"]["confirmation"]["avg_after_commission"] > 0)
    at_least_30 = (summary["dev_trades"] or 0) >= 30
    finalist = {
        "survives_cheap_rejection": survives_cheap,
        "positive_both_discovery_and_confirmation": positive_both,
        "has_a_positive_neighbour_in_mechanism": None,  # filled in a second pass, needs every test's summary first
        "at_least_30_dev_trades": at_least_30,
        "sealed_can_supply_30_more": None,  # sealed period is locked per FROZEN-MATRIX; not evaluated
        # eligible/reasons are finished after the neighbour pass, see fill_neighbour_flags()
        "eligible_pending_sealed": None,
        "reasons": [],
    }
    if not survives_cheap:
        finalist["reasons"].append(f"cheap-rejected: {'; '.join(cheap)}")
    if not positive_both:
        finalist["reasons"].append("not positive after commission in both discovery and confirmation")
    if not at_least_30:
        finalist["reasons"].append("fewer than 30 development trades")

    verdict = "REJECTED" if cheap else "PROMISING, NOT PROVEN"

    return {
        "test_id": tid, "mechanism": t["mechanism"], "mechanism_id": t["mechanism_id"],
        "trigger": trig_code, "structure": struct_code, "expiry_window": t["expiry_window"],
        "strikes_rule": strikes_rule_for(struct_code), "exit_code": exit_code, "exit_rule": exit_rule,
        "databento_cost_usd_estimate": databento_cost_estimate(sel, dates),
        **summary,
        "cheap_rejection_triggered": cheap,
        "finalist_conditions": finalist,
        "verdict": verdict,
    }


def databento_cost_estimate(sel: dict, dates: dict) -> float:
    """NOT a ledger figure — an estimate at the frozen matrix's own stated
    median unit costs ($0.0079/chain snapshot, $0.0009/contract/date),
    applied to every date this test actually uses, whether or not those
    contracts happen to already be paid for via another test sharing them.
    Real spend is tracked in spend_ledger.json, split across tests that
    share contracts, which this per-test figure does not attempt."""
    n_days = len(dates)
    n_legs = sum(len(rec["leg_symbols"]) for rec in dates.values() if "leg_symbols" in rec)
    return round(n_days * 0.0079 + n_legs * 0.0009, 4)


def fill_neighbour_flags(rows: list):
    """Second pass: 'at least one neighbouring setting inside the same
    mechanism is also positive after commission' (frozen matrix 10) — a
    neighbour is any OTHER test in the same mechanism_id."""
    by_mech = defaultdict(list)
    for r in rows:
        by_mech[r["mechanism_id"]].append(r)
    for r in rows:
        others = [o for o in by_mech[r["mechanism_id"]] if o["test_id"] != r["test_id"]]
        has_neighbour = any(
            o.get("avg_return_after_commission") is not None and o["avg_return_after_commission"] > 0
            for o in others)
        fc = r["finalist_conditions"]
        fc["has_a_positive_neighbour_in_mechanism"] = has_neighbour
        if not has_neighbour:
            fc["reasons"].append("no other test in the same mechanism is positive after commission "
                                  "(one magic parameter is not a finalist)")
        fc["eligible_pending_sealed"] = (fc["survives_cheap_rejection"] and
                                          fc["positive_both_discovery_and_confirmation"] and
                                          fc["has_a_positive_neighbour_in_mechanism"] and
                                          fc["at_least_30_dev_trades"])


# ----------------------------------------------------------------------- main

def main():
    frozen = json.load(open(FROZEN_PATH))
    trig = json.load(open(TRIGGERS_PATH))
    selection = json.load(open(SELECTION_PATH))
    owned_index = json.load(open(OWNED_INDEX_PATH))
    build_file_symbol_index(owned_index)
    sig = trig["signal"]
    exits = frozen["exits"]

    tests = [t for t in frozen["tests"] if t["mechanism_id"] in (1, 2, 3, 4)]
    rows = []
    for t in tests:
        tid = t["test_id"]
        if tid in NO_FUND_TEST_IDS:
            rows.append({
                "test_id": tid, "mechanism": t["mechanism"], "mechanism_id": t["mechanism_id"],
                "trigger": t["trigger"], "structure": t["structure"], "expiry_window": t["expiry_window"],
                "strikes_rule": strikes_rule_for(t["structure"]), "exit_code": t["exit_code"],
                "exit_rule": t["exit"], "databento_cost_usd_estimate": 0.0,
                "verdict": "REJECTED", "rejection_reason": NO_FUND_REASONS[tid],
                "cheap_rejection_triggered": ["fewer than 30 development trades"],
                "finalist_conditions": None,
            })
            continue
        rows.append(run_test(t, selection, sig, owned_index, exits))

    fill_neighbour_flags([r for r in rows if r["test_id"] not in NO_FUND_TEST_IDS])

    json.dump(rows, open(RESULTS_OUT, "w"), indent=1, default=str)

    def rank_key(r):
        v = r.get("avg_return_on_max_risk")
        return v if v is not None else float("-inf")

    ranked = sorted((r for r in rows if r["test_id"] not in NO_FUND_TEST_IDS),
                     key=rank_key, reverse=True)
    print(f"{'test':>4} {'mech':>4} {'trigger':>7} {'structure':>10} {'exit':>4} "
          f"{'dev_n':>6} {'no_data':>7} {'win%':>6} {'aft_comm':>9} {'ret/maxrisk':>11} "
          f"{'best_yr%':>9} {'best5%':>7} {'verdict':>20}")
    for r in ranked:
        n = r.get("dev_trades") or 0
        wr = r.get("win_rate")
        af = r.get("avg_return_after_commission")
        rmr = r.get("avg_return_on_max_risk")
        by = r.get("profit_share_best_year")
        b5 = r.get("profit_share_best_5_trades")
        print(f"{r['test_id']:>4} {r['mechanism_id']:>4} {r['trigger']:>7} {r['structure']:>10} "
              f"{r['exit_code']:>4} {n:>6} {r.get('no_minute_data_yet', 0):>7} "
              f"{(f'{wr:.1%}' if wr is not None else '-'):>6} "
              f"{(f'{af:+.2%}' if af is not None else '-'):>9} "
              f"{(f'{rmr:+.4f}' if rmr is not None else '-'):>11} "
              f"{(f'{by:.1%}' if by is not None else '-'):>9} "
              f"{(f'{b5:.1%}' if b5 is not None else '-'):>7} {r['verdict']:>20}")

    for tid in sorted(NO_FUND_TEST_IDS):
        r = next(x for x in rows if x["test_id"] == tid)
        print(f"{tid:>4}  (not funded) — {r['verdict']}: {r['rejection_reason']}")

    print("\nmax simultaneous risk, top 10 by rank:")
    for r in ranked[:10]:
        msr = r.get("max_simultaneous_risk_usd")
        print(f"  test {r['test_id']:>3} {r['structure']:>10} {r['exit_code']:>3}: "
              f"max_simultaneous_risk_usd={msr:.0f}" if msr is not None else
              f"  test {r['test_id']:>3}: n/a")

    t11 = next((r for r in rows if r["test_id"] == 11), None)
    if t11 is not None:
        dvc = t11["discovery_vs_confirmation"]
        print("\ntest 11 (PCS(1.0) / X3) discovery vs confirmation:")
        for period in ("discovery", "confirmation"):
            b = dvc[period]
            wr = b.get("win_rate")
            af = b.get("avg_after_commission")
            print(f"  {period:>12}: trades={b['trades']:>4} "
                  f"win_rate={(f'{wr:.1%}' if wr is not None else '-'):>6} "
                  f"avg_after_commission={(f'{af:+.2%}' if af is not None else '-'):>8} "
                  f"total_profit_usd={b['total_profit']:.0f}")

    print(f"\nwrote {RESULTS_OUT}")


if __name__ == "__main__":
    main()
