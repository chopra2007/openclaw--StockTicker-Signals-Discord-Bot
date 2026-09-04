"""TODO #111 tournament — mechanism 5 (scheduled-event volatility), lane owner: events.

Stage 1: build the development/sealed entry-date lists for FOMC, CPI, JOBS
and the pooled set (tests 43-50 of FROZEN-MATRIX.md section 5), and report
counts. Stage 2: write the manifest of entry-minute whole-chain snapshots the
DEVELOPMENT dates still need. Spends nothing, downloads nothing.

Priming rule (frozen): each class's chronological history starts wherever the
calendar starts (2013-01-01). The first 12 occurrences of a class are used
only to prime the trailing-12 historical-move median; they are never traded,
even if they fall inside the development window. Unscheduled
(scheduled: false) events are dropped from the class's trading sequence
entirely and reported separately.
"""
from __future__ import annotations

import json
import os
import statistics
import sys

CALENDAR = "/home/openclaw/.openclaw/research-data/todo-111-tournament/event_calendar.json"
SPY_DAILY = "/home/openclaw/.openclaw/workspace/data/mmhl_daily/SPY.json"
OUT_DIR = "/home/openclaw/.openclaw/research-data/todo-111-tournament"

DEV_START, DEV_END = "2014-01-01", "2021-12-31"
SEALED_START, SEALED_END = "2022-01-01", "2026-08-31"
PRIME_N = 12
EVENT_DTE_LO, EVENT_DTE_HI, EVENT_DTE_TARGET = 5, 20, 10  # section 5 expiry window

sys.path.insert(0, "/home/openclaw/.openclaw/workspace/scripts/research")
from todo_111_tourney_pull import chain_path  # noqa: E402  (import only, never run)
from todo_111_tourney_core import load_chain, pick_expiry, reference, build_structure  # noqa: E402


def load_calendar():
    return json.load(open(CALENDAR))


def load_sessions():
    d = json.load(open(SPY_DAILY))
    return sorted(d.keys())


def session_before(sessions, iso_date):
    """The last trading session strictly before iso_date, or None."""
    best = None
    for s in sessions:
        if s < iso_date:
            best = s
        else:
            break
    return best


def build_class_sequence(events, cls):
    """All scheduled events of one class, chronological. Returns
    (sequence, dropped_unscheduled)."""
    all_of_class = [e for e in events if e["class"] == cls]
    scheduled = sorted((e for e in all_of_class if e.get("scheduled", True)),
                        key=lambda e: e["date"])
    dropped = sorted((e for e in all_of_class if not e.get("scheduled", True)),
                      key=lambda e: e["date"])
    return scheduled, dropped


def split_dev_sealed(usable, start, end):
    return [e for e in usable if start <= e["date"] <= end]


# ------------------------------------------------------------------------
# Stage 3, the parts that need no option data: the two move measures, the
# E1/E2 decision, and the exit cap. Nothing below reads a chain or a leg
# file, downloads anything, or computes a trade outcome.
# ------------------------------------------------------------------------

def close_to_close_return(sessions, closes, release_date):
    """abs((close on the release session) - (close on the prior session)) /
    prior close — "the close-to-close return on the release day itself"
    (section 5).

    The release session is the first trading session ON OR AFTER
    release_date, not release_date itself — because 6 CPI/jobs releases in
    this calendar fall on Good Friday, when the NYSE is closed but BLS
    still publishes: 2015-04-03, 2017-04-14, 2020-04-10, 2021-04-02,
    2023-04-07, 2026-04-03. On every other date this is exactly the same
    number (release_date IS the release session); on those 6 it uses the
    next trading day's real close instead of inventing one for a day the
    market never opened. No close is ever invented — both closes used are
    real, already-recorded prices from data/mmhl_daily/SPY.json.

    None if either close is missing.
    """
    prev = session_before(sessions, release_date)
    rel = session_on_or_after(sessions, release_date)
    if prev is None or rel is None or prev not in closes or rel not in closes:
        return None
    c0, c1 = closes[prev], closes[rel]
    if c0 == 0:
        return None
    return abs((c1 - c0) / c0)


def class_returns(class_seq, sessions, closes):
    """class_seq: one class's full chronological event list (scheduled
    only, priming events included). Returns a same-length list of each
    event's close-to-close return (or None if a close is missing).

    class_seq MUST already be sorted ascending by date — asserted here,
    because historical_event_move()'s no-lookahead guarantee depends on
    index order matching date order.
    """
    dates = [e["date"] for e in class_seq]
    assert dates == sorted(dates), "class_seq must be chronological"
    return [close_to_close_return(sessions, closes, e["date"]) for e in class_seq]


def historical_event_move(returns, i):
    """The median of the 12 occurrences immediately BEFORE index i in a
    chronologically-sorted return list (section 5: "previous 12
    occurrences", expanding forward one event at a time).

    Only ever reads returns[i-12:i] — strictly earlier indices, which
    (because class_returns() is built from a date-sorted sequence) are
    strictly earlier dates. It never looks at returns[i] itself or
    anything after it. None for i < 12: those are the priming events,
    with fewer than 12 predecessors, and are not traded.
    """
    if i < 12:
        return None
    window = returns[i - 12:i]
    if any(r is None for r in window):
        return None
    return statistics.median(window)


def verify_no_lookahead(class_seq, i):
    """Proves, for one event, that its historical-move window used only
    strictly earlier dates. Raises if not. Used by the unit test below and
    safe to call from Stage 3's real run before every trigger decision."""
    if i < 12:
        return True
    window_dates = [class_seq[j]["date"] for j in range(i - 12, i)]
    current_date = class_seq[i]["date"]
    assert all(d < current_date for d in window_dates), (
        f"lookahead: window {window_dates} is not all strictly before {current_date}")
    assert i - 12 >= 0 and (i - 12) + 12 == i, "window is not exactly the 12 immediately before i"
    return True


def implied_event_move(ref):
    """mid(ATM straddle) / spot, at the entry minute — the move priced over
    the option's WHOLE remaining life (still reported for reference; this
    raw number is what amendment 3 found could not be compared directly to
    a one-day historical move — see implied_sigma_1d)."""
    return ref["expected_move"] / ref["spot"]


# Amendment 3 (FROZEN-MATRIX.md section 17): fixed properties of the normal
# distribution, declared before any mechanism-5 return was computed, not
# tuned. A straddle costs about 0.7979 standard deviations; the median
# absolute value of a normal variable is about 0.6745 standard deviations.
STRADDLE_TO_SIGMA = 0.7979
MAD_TO_SIGMA = 0.6745


def trading_days_between(sessions, day1, day2):
    """Trading-session count from day1 to day2 (section 17's T). day2 is
    usually a listed expiry, which is normally itself a trading session; if
    it somehow is not, anchors on the first session on or after it."""
    i0 = sessions.index(day1)
    d2 = day2 if day2 in sessions else session_on_or_after(sessions, day2)
    if d2 is None:
        return None
    i1 = sessions.index(d2)
    return i1 - i0


def implied_sigma_1d(ref, sessions, entry_day, exp):
    """sigma_implied_period / sqrt(T) — amendment 3's fix, putting the
    option-implied move on a one-day clock so it can be compared to
    historical_sigma_1d. None if T is not positive (entry on or after
    expiry, which pick_expiry should never produce)."""
    sigma_period = implied_event_move(ref) / STRADDLE_TO_SIGMA
    T = trading_days_between(sessions, entry_day, exp)
    if not T or T <= 0:
        return None
    return sigma_period / (T ** 0.5)


def historical_sigma_1d(returns, i):
    """historical_event_move (the previous-12-occurrence median) / 0.6745
    — amendment 3's fix, already on a one-day clock since the median
    itself is of one-day returns. None if historical_event_move is None
    (priming events, or a still-missing daily close)."""
    med = historical_event_move(returns, i)
    if med is None:
        return None
    return med / MAD_TO_SIGMA


def event_trigger(implied, historical):
    """E1 (cheap, ratio <= 0.90), E2 (rich, ratio >= 1.30), or None. Takes
    whatever two same-clock quantities the caller passes — as of amendment
    3, that's implied_sigma_1d and historical_sigma_1d, both one-day
    numbers. None if historical is unknown or zero (ratio undefined)."""
    if historical is None or historical == 0:
        return None
    ratio = implied / historical
    if ratio <= 0.90:
        return "E1"
    if ratio >= 1.30:
        return "E2"
    return None


def trading_days_after(sessions, day, n):
    """The session n trading days after `day` (day itself is 0 days
    after). Clamped to the last available session. `day` must itself be a
    trading session — use session_on_or_after() first if it might not be
    (e.g. Good Friday, when BLS still releases CPI/jobs data but the NYSE
    is closed: 2015-04-03, 2017-04-14, 2020-04-10, 2021-04-02, 2023-04-07,
    2026-04-03 all do this)."""
    idx = sessions.index(day)
    j = min(idx + n, len(sessions) - 1)
    return sessions[j]


def session_on_or_after(sessions, iso_date):
    """The first trading session on or after iso_date, or None if the
    calendar doesn't reach that far. Needed because a release date is
    sometimes a market holiday (Good Friday) with no session of its own."""
    for s in sessions:
        if s >= iso_date:
            return s
    return None


def mechanism5_last_trading_day(sessions, entry_day, release_day, cap_trading_days=14):
    """Section 5's exit cap: "capped at the close of the second session
    after the release, or the exit set's cap [X1/Y1 = 14 trading days],
    whichever is sooner." Returns the SOONER (earlier) of the two dates.

    release_day is not always a trading session itself (Good Friday releases
    — see trading_days_after's docstring); the "2 sessions after the
    release" count anchors on the first trading session on or after it,
    since that is the first session the market can actually react in."""
    cap_by_trading_days = trading_days_after(sessions, entry_day, cap_trading_days)
    release_session = session_on_or_after(sessions, release_day)
    cap_by_event = (trading_days_after(sessions, release_session, 2)
                     if release_session else cap_by_trading_days)
    return min(cap_by_trading_days, cap_by_event)


def _run_unit_tests():
    """Hand-worked check of historical_event_move and the no-lookahead
    guarantee, plus a sanity check of the exit-cap rule against real
    calendar dates. No option data, no network, no download."""
    # --- historical_event_move, worked by hand ---------------------------
    # 12 priming returns, then 2 more tradeable events. Values are made up
    # round numbers, not real prices, chosen so the median is easy to check
    # by hand.
    priming = [0.01, 0.02, 0.01, 0.03, 0.02, 0.01, 0.04, 0.02, 0.01, 0.03, 0.02, 0.01]
    event_13 = 0.05
    event_14 = 0.02
    returns = priming + [event_13, event_14]

    # event 13 (index 12): historical move = median of the 12 priming
    # returns. Sorted: five 0.01s, four 0.02s, two 0.03s, one 0.04 -> the
    # 6th and 7th of 12 values are both 0.02 -> median 0.02.
    got = historical_event_move(returns, 12)
    assert got == 0.02, f"expected 0.02, got {got}"

    # event 14 (index 13): window drops the first 0.01 and picks up
    # event_13's own return (0.05). Sorted: four 0.01s, four 0.02s, two
    # 0.03s, one 0.04, one 0.05 -> the 6th and 7th of 12 are again both
    # 0.02 -> median 0.02.
    got = historical_event_move(returns, 13)
    assert got == 0.02, f"expected 0.02, got {got}"

    # the first 12 events are priming: no historical move, not traded.
    for i in range(12):
        assert historical_event_move(returns, i) is None

    # --- E1/E2 decision ---------------------------------------------------
    # historical = 1.0 so implied IS the ratio, with no float division noise
    # at the boundary.
    assert event_trigger(0.90, 1.0) == "E1"   # ratio 0.90 exactly -> E1 (<=)
    assert event_trigger(0.89, 1.0) == "E1"   # ratio 0.89 -> E1
    assert event_trigger(1.30, 1.0) == "E2"   # ratio 1.30 exactly -> E2 (>=)
    assert event_trigger(1.31, 1.0) == "E2"   # ratio 1.31 -> E2
    assert event_trigger(1.10, 1.0) is None   # ratio 1.10 -> neither
    assert event_trigger(0.010, None) is None
    assert event_trigger(0.010, 0.0) is None

    # --- no-lookahead proof, on a synthetic chronological sequence -------
    fake_seq = [{"date": f"2020-{1 + i // 12:02d}-{1 + i % 12:02d}"} for i in range(20)]
    for i in range(20):
        verify_no_lookahead(fake_seq, i)

    # --- amendment 3's one-day-clock conversion, worked by hand -----------
    # straddle = 5% of spot (ref['expected_move']/ref['spot'] = 0.05),
    # expiry 3 trading days after entry.
    # sigma_implied_period = 0.05 / 0.7979 = 0.0626644942975...
    # sigma_implied_1d     = 0.0626644942975... / sqrt(3) = 0.0361793626513...
    fake_ref = {"expected_move": 5.0, "spot": 100.0}
    fake_sessions = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]
    got = implied_sigma_1d(fake_ref, fake_sessions, "2020-01-01", "2020-01-06")
    assert abs(got - 0.0361793626513113) < 1e-12, f"expected 0.03618..., got {got}"

    # historical median = 0.006745 -> sigma_historical_1d = 0.006745/0.6745
    # = 0.01 exactly.
    got = historical_sigma_1d([0.006745] * 12, 12)
    assert got == 0.01, f"expected 0.01, got {got}"

    # ratio = 0.0361793.../0.01 = 3.6179... -> E2 (>= 1.30)
    assert event_trigger(0.0361793626513113, 0.01) == "E2"

    print("unit tests: PASS (historical_event_move hand-check, "
          "E1/E2 boundaries, no-lookahead proof, amendment-3 sigma conversion)")


def _exit_cap_sanity_check():
    """Confirms the walk applies the SOONER of the 14-trading-day cap and
    the second-session-after-release cap, on real development dates. Dates
    only — no option data."""
    cal = load_calendar()
    sessions = load_sessions()
    seq, _ = build_class_sequence(cal["events"], "CPI")
    usable = seq[PRIME_N:]
    dev = split_dev_sealed(usable, DEV_START, DEV_END)[:5]
    print("\nexit-cap sanity check (5 real CPI development dates):")
    for e in dev:
        entry_day = session_before(sessions, e["date"])
        if entry_day is None:
            continue
        cap_days = trading_days_after(sessions, entry_day, 14)
        cap_event = trading_days_after(sessions, e["date"], 2)
        applied = mechanism5_last_trading_day(sessions, entry_day, e["date"], 14)
        sooner = "event cap" if applied == cap_event else "14-day cap"
        print(f"  release {e['date']}  entry {entry_day}  "
              f"14-day cap -> {cap_days}   2-session-after-release cap -> {cap_event}   "
              f"applied (sooner) -> {applied}  ({sooner})")
        assert applied == min(cap_days, cap_event)
    print("in every one of these, and in every mechanism-5 row (entry is always "
          "exactly one session before the release), the second-session-after-"
          "release cap is the sooner one — it lands about 3 trading sessions "
          "after entry, far inside the 14-day cap. So a typical mechanism-5 "
          "trade is a roughly 3-trading-day hold, not a 14-day one, unless the "
          "target or stop ends it even sooner.")


# ------------------------------------------------------------------------
# Stage 3, part 2: real E1/E2 triggers from the owned chain snapshots, and
# the structures for tests 43-50. Reads only .dbn.zst files already on
# disk. Never downloads. Never computes a trade outcome (no minute-level
# exit walk here) — this only decides WHICH dates fire and WHAT legs each
# one needs, then writes that as a manifest for the orchestrator to price.
# ------------------------------------------------------------------------

TRIGGER_STRUCTURE = {"E1": "STRAD", "E2": "IC(1.0)"}


def class_dev_events_with_index(events, cls):
    """Full chronological (scheduled-only) sequence for one class, plus the
    list of (full_seq_index, event) pairs that are development, post-priming
    — i.e. eligible to fire a trigger."""
    seq, dropped = build_class_sequence(events, cls)
    dev_pairs = [(i, e) for i, e in enumerate(seq)
                 if i >= PRIME_N and DEV_START <= e["date"] <= DEV_END]
    return seq, dropped, dev_pairs


def compute_class_triggers(events, cls, sessions, closes):
    """For every development, post-priming event of one class: entry day,
    implied/historical move, and the trigger (or None), plus why a date was
    skipped before a trigger could even be evaluated.

    Returns (rows, skip_counts) where each row is
    {date, entry_day, sigma_implied, sigma_historical, ratio, trigger} or,
    for a skip, {date, skip_reason}. Both sigma values are on amendment 3's
    one-day clock (FROZEN-MATRIX.md section 17).
    """
    seq, dropped, dev_pairs = class_dev_events_with_index(events, cls)
    returns = class_returns(seq, sessions, closes)
    rows = []
    skip_counts = {}

    def skip(date_, reason):
        skip_counts[reason] = skip_counts.get(reason, 0) + 1
        rows.append({"date": date_, "skip_reason": reason})

    for i, e in dev_pairs:
        release = e["date"]
        entry_day = session_before(sessions, release)
        if entry_day is None:
            skip(release, "no prior trading session for entry")
            continue

        sigma_hist = historical_sigma_1d(returns, i)
        if sigma_hist is None:
            skip(release, "historical move undefined (missing daily close in the "
                           "trailing 12)")
            continue

        path = chain_path(entry_day)
        if not os.path.exists(path):
            skip(release, "chain snapshot not on disk")
            continue

        chain = load_chain(path)
        exp = pick_expiry(chain, entry_day, EVENT_DTE_LO, EVENT_DTE_HI, EVENT_DTE_TARGET)
        if exp is None:
            skip(release, f"no expiry listed {EVENT_DTE_LO}-{EVENT_DTE_HI} days out")
            continue

        ref = reference(chain, exp)
        if ref is None:
            skip(release, "no strike with both a call and a put quote (no parity spot)")
            continue

        sigma_implied = implied_sigma_1d(ref, sessions, entry_day, exp)
        if sigma_implied is None:
            skip(release, "expiry is not after entry on the trading-day count (T <= 0)")
            continue

        ratio = sigma_implied / sigma_hist if sigma_hist else None
        trigger = event_trigger(sigma_implied, sigma_hist)

        rows.append({"date": release, "entry_day": entry_day, "exp": exp,
                      "sigma_implied": sigma_implied, "sigma_historical": sigma_hist,
                      "ratio": ratio, "trigger": trigger, "chain": chain})
    return rows, skip_counts


def build_legs_for_row(row):
    """STRAD for E1, IC(1.0) for E2. Returns (structure_or_None, error_or_None)."""
    code = TRIGGER_STRUCTURE[row["trigger"]]
    ref = reference(row["chain"], row["exp"])
    structure = build_structure(row["chain"], row["exp"], ref, code)
    if isinstance(structure, str):
        return None, structure
    return structure, None


def stage3_triggers_and_manifest():
    """Compute real E1/E2 triggers on the owned chain snapshots, build the
    STRAD/IC(1.0) legs for every date that fires, and write
    events_manifest_legs.json — the legs the orchestrator still needs to
    price and buy. Never downloads; never walks a minute file; never
    computes a trade outcome."""
    cal = load_calendar()
    events = cal["events"]
    sessions = load_sessions()
    closes = {d: v[3] for d, v in json.load(open(SPY_DAILY)).items()}  # v = [o,h,l,c,vol]

    classes = ["FOMC", "CPI", "JOBS"]
    per_class = {}
    manifest_legs = {}
    build_fail_counts = {}
    pooled_fired = {"E1": 0, "E2": 0}

    for cls in classes:
        rows, skip_counts = compute_class_triggers(events, cls, sessions, closes)
        fired = {"E1": 0, "E2": 0}
        no_trigger = 0
        for row in rows:
            if "skip_reason" in row:
                continue
            if row["trigger"] is None:
                no_trigger += 1
                continue
            structure, err = build_legs_for_row(row)
            if err:
                build_fail_counts[err] = build_fail_counts.get(err, 0) + 1
                continue
            fired[row["trigger"]] += 1
            pooled_fired[row["trigger"]] += 1
            entry_day = row["entry_day"]
            end_day = mechanism5_last_trading_day(sessions, entry_day, row["date"], 14)
            symbols = {l["symbol"] for l in structure["legs"]}
            slot = manifest_legs.setdefault(entry_day, {"symbols": set(), "end_day": end_day})
            slot["symbols"] |= symbols
            slot["end_day"] = max(slot["end_day"], end_day)

        per_class[cls] = {
            "usable_dev_events": len(rows),
            "fired_E1": fired["E1"], "fired_E2": fired["E2"],
            "no_trigger": no_trigger,
            "skipped_before_trigger": sum(skip_counts.values()),
            "skip_reasons": skip_counts,
        }

    for slot in manifest_legs.values():
        slot["symbols"] = sorted(slot["symbols"])

    print("\n=== Stage 3, part 2: real E1/E2 triggers and the leg manifest ===\n")
    for cls in classes:
        r = per_class[cls]
        print(f"{cls}: {r['usable_dev_events']} development dates checked -> "
              f"E1 fired {r['fired_E1']}, E2 fired {r['fired_E2']}, "
              f"neither fired {r['no_trigger']}, "
              f"could not even be checked {r['skipped_before_trigger']} "
              f"({r['skip_reasons'] if r['skip_reasons'] else 'none'})")

    pooled_dev_e1 = pooled_fired["E1"]
    pooled_dev_e2 = pooled_fired["E2"]
    print(f"\npooled (test 49, E1/STRAD): {pooled_dev_e1} development trades")
    print(f"pooled (test 50, E2/IC(1.0)): {pooled_dev_e2} development trades")
    print(f"test 49 clears 100 development trades: {'YES' if pooled_dev_e1 >= 100 else 'NO'}")
    print(f"test 50 clears 100 development trades: {'YES' if pooled_dev_e2 >= 100 else 'NO'}")
    if build_fail_counts:
        print(f"\nstructure could not be built (strike not listed) on "
              f"{sum(build_fail_counts.values())} fired dates: {build_fail_counts}")

    total_contract_days = sum(len(v["symbols"]) for v in manifest_legs.values())
    print(f"\nmanifest: {len(manifest_legs)} entry days need leg data, "
          f"{total_contract_days} contract-days total "
          f"({total_contract_days / len(manifest_legs):.1f} contracts/day on average)"
          if manifest_legs else "\nmanifest: nothing fired, nothing to buy")

    manifest = {"label": "mechanism-5-events-development-legs",
                "chain_days": [],
                "legs": manifest_legs}
    out_path = f"{OUT_DIR}/events_manifest_legs.json"
    json.dump(manifest, open(out_path, "w"), indent=1)
    print(f"wrote {out_path}")

    json.dump({"per_class": per_class,
               "pooled_dev_E1": pooled_dev_e1,
               "pooled_dev_E2": pooled_dev_e2,
               "build_fail_counts": build_fail_counts,
               "manifest_entry_days": len(manifest_legs),
               "manifest_contract_days": total_contract_days},
              open(f"{OUT_DIR}/events_stage3_report.json", "w"), indent=1)
    print(f"wrote {OUT_DIR}/events_stage3_report.json")


def main():
    cal = load_calendar()
    events = cal["events"]
    sessions = load_sessions()

    classes = ["FOMC", "CPI", "JOBS"]
    report = {}
    pooled_dev, pooled_sealed = [], []
    dev_entry_days = set()

    for cls in classes:
        seq, dropped = build_class_sequence(events, cls)
        priming = seq[:PRIME_N]
        usable = seq[PRIME_N:]
        dev = split_dev_sealed(usable, DEV_START, DEV_END)
        sealed = split_dev_sealed(usable, SEALED_START, SEALED_END)
        leftover = [e for e in usable if e not in dev and e not in sealed]

        for e in dev:
            entry_day = session_before(sessions, e["date"])
            e["entry_day"] = entry_day
            if entry_day:
                dev_entry_days.add(entry_day)
        for e in sealed:
            e["entry_day"] = session_before(sessions, e["date"])

        pooled_dev.extend(dev)
        pooled_sealed.extend(sealed)

        report[cls] = dict(
            total_scheduled_events=len(seq),
            dropped_unscheduled=[e["date"] for e in dropped],
            priming_events=len(priming),
            priming_range=(priming[0]["date"], priming[-1]["date"]) if priming else None,
            usable_events=len(usable),
            dev_events=len(dev),
            sealed_events=len(sealed),
            leftover_events_outside_both_windows=len(leftover),
            dev_range=(dev[0]["date"], dev[-1]["date"]) if dev else None,
            sealed_range=(sealed[0]["date"], sealed[-1]["date"]) if sealed else None,
        )

    pooled_dev.sort(key=lambda e: e["date"])
    pooled_sealed.sort(key=lambda e: e["date"])

    print("=== Stage 1: dates and sample size ===\n")
    for cls in classes:
        r = report[cls]
        print(f"{cls}:")
        print(f"  scheduled events on the calendar: {r['total_scheduled_events']}"
              + (f"  (also {len(r['dropped_unscheduled'])} unscheduled dropped: "
                 f"{r['dropped_unscheduled']})" if r['dropped_unscheduled'] else ""))
        print(f"  first {r['priming_events']} occurrences used only to prime the "
              f"12-event median ({r['priming_range'][0]} to {r['priming_range'][1]}), "
              f"not traded")
        print(f"  usable (tradeable) events after priming: {r['usable_events']}")
        print(f"  development (2014-2021) usable events: {r['dev_events']} "
              f"({r['dev_range'][0]} to {r['dev_range'][1]})" if r['dev_events'] else
              f"  development (2014-2021) usable events: 0")
        print(f"  sealed (2022-2026) usable events: {r['sealed_events']} "
              f"({r['sealed_range'][0]} to {r['sealed_range'][1]})" if r['sealed_events'] else
              f"  sealed (2022-2026) usable events: 0")
        if r["leftover_events_outside_both_windows"]:
            print(f"  WARNING: {r['leftover_events_outside_both_windows']} usable events "
                  f"fall outside both the development and sealed windows")
        print()

    print("Pooled (tests 49, 50 — all three classes combined):")
    print(f"  development entries: {len(pooled_dev)}")
    print(f"  sealed entries: {len(pooled_sealed)}")
    print(f"  can reach 100 development and 100 sealed trades: "
          f"{'YES, on date count alone' if len(pooled_dev) >= 100 and len(pooled_sealed) >= 100 else 'NO'}")
    print("  (these are event-DATE counts, an upper bound; the actual trade count in "
          "each row will be lower once the liquidity gate and missing-minute skips "
          "of Stage 3 are applied)")
    print()

    missing_entry_day = [e["date"] for e in pooled_dev if not e.get("entry_day")]
    if missing_entry_day:
        print(f"WARNING: {len(missing_entry_day)} development events have no prior "
              f"trading session in data/mmhl_daily/SPY.json: {missing_entry_day}")

    # ---------------------------------------------------------------- Stage 2
    print("\n=== Stage 2: manifest of chain snapshots still needed (development only) ===\n")
    chain_days = sorted(dev_entry_days)
    need = [d for d in chain_days if not os.path.exists(chain_path(d))]
    have = [d for d in chain_days if d not in need]
    print(f"development entry days (deduped across classes): {len(chain_days)}")
    print(f"already on disk (free): {len(have)}")
    print(f"still needed: {len(need)}")

    manifest = {"label": "mechanism-5-events-development-chains",
                "chain_days": need}
    out_path = f"{OUT_DIR}/events_manifest_chains.json"
    json.dump(manifest, open(out_path, "w"), indent=1)
    print(f"\nwrote {out_path}")

    json.dump({"per_class": report,
               "pooled_dev_count": len(pooled_dev),
               "pooled_sealed_count": len(pooled_sealed),
               "dev_entry_days": chain_days,
               "chain_days_needed": need,
               "chain_days_owned": have},
              open(f"{OUT_DIR}/events_stage1_report.json", "w"), indent=1)
    print(f"wrote {OUT_DIR}/events_stage1_report.json")

    print("\n=== Stage 3 (data-free parts): move measures, E1/E2, exit cap ===")
    _run_unit_tests()
    _exit_cap_sanity_check()

    stage3_triggers_and_manifest()


if __name__ == "__main__":
    main()
