#!/usr/bin/env python3
"""
Build a point-in-time calendar of US scheduled economic releases
(FOMC decision days, CPI, Employment Situation / jobs report) for
2013-01-01 through 2026-08-31.

Sources are read by hand from the primary publishers (federalreserve.gov
FOMC historical-year pages, bls.gov per-year release-schedule pages) and
hardcoded below as RAW_* tables, because those pages require a browser-like
fetch this script does not perform itself. Re-running this script re-derives
the JSON output and re-runs every sanity check against the hardcoded tables;
it does not re-fetch the web pages. To refresh the underlying facts, re-check
the SOURCES list below by hand and update the RAW_* tables.

Output: /home/openclaw/.openclaw/research-data/todo-111-tournament/event_calendar.json
"""
import json
import datetime
from collections import defaultdict

OUT_PATH = "/home/openclaw/.openclaw/research-data/todo-111-tournament/event_calendar.json"
SPY_DAILY_PATH = "/home/openclaw/.openclaw/workspace/data/mmhl_daily/SPY.json"

SOURCES = {
    "FOMC": [
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2013.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2014.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2015.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2016.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2017.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2018.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2019.htm",
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200303a.htm",
        "https://www.washingtonpost.com/business/2020/03/15/federal-reserve-slashes-interest-rates-zero-part-wide-ranging-emergency-intervention/",
    ],
    "CPI_JOBS": [
        "https://www.bls.gov/schedule/2013/home.htm",
        "https://www.bls.gov/schedule/2014/home.htm",
        "https://www.bls.gov/schedule/2015/home.htm",
        "https://www.bls.gov/schedule/2016/home.htm",
        "https://www.bls.gov/schedule/2017/home.htm",
        "https://www.bls.gov/schedule/2018/home.htm",
        "https://www.bls.gov/schedule/2019/home.htm",
        "https://www.bls.gov/schedule/2020/home.htm",
        "https://www.bls.gov/schedule/2021/home.htm",
        "https://www.bls.gov/schedule/2022/home.htm",
        "https://www.bls.gov/schedule/2023/home.htm",
        "https://www.bls.gov/schedule/2024/home.htm",
        "https://www.bls.gov/schedule/2025/home.htm",
        "https://www.bls.gov/schedule/2026/home.htm",
        "https://www.bls.gov/schedule/news_release/empsit.htm",
    ],
}

# ---------------------------------------------------------------------------
# FOMC: last day of each regularly scheduled meeting (the decision/announcement
# day), read off federalreserve.gov's per-year historical meeting pages.
# Unscheduled/emergency calls are listed separately below and only included
# when they produced a dated policy decision announcement.
# ---------------------------------------------------------------------------

FOMC_SCHEDULED = [
    # 2013
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
    "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    # 2014
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
    "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
    "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
    "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020: regular meeting for March (originally 17-18) was cancelled/
    # superseded by the emergency actions below; only 7 regular decisions.
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (through Aug 2026 only)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29",
]

# Unscheduled/emergency FOMC actions with a dated, publicly announced rate
# decision. Non-decision conference calls (2013-10-16, 2014-03-04,
# 2019-10-04) are deliberately excluded: those calls did not announce a
# rate decision, so they are not "the day the decision is announced".
FOMC_UNSCHEDULED = [
    "2020-03-03",  # emergency 50bp cut, announced Tue (a normal session)
    "2020-03-15",  # emergency cut to zero, announced Sunday evening
]

# ---------------------------------------------------------------------------
# CPI and JOBS release dates, read off bls.gov/schedule/<year>/home.htm for
# each year 2013-2026 (through Aug 2026). Dates below are the actual release
# date (not the "reference month" the release covers).
# ---------------------------------------------------------------------------

CPI_DATES = [
    # 2013
    "2013-01-16", "2013-02-21", "2013-03-15", "2013-04-16", "2013-05-16",
    "2013-06-18", "2013-07-16", "2013-08-15", "2013-09-17", "2013-10-30",
    "2013-11-20", "2013-12-17",
    # 2014
    "2014-01-16", "2014-02-20", "2014-03-18", "2014-04-15", "2014-05-15",
    "2014-06-17", "2014-07-22", "2014-08-19", "2014-09-17", "2014-10-22",
    "2014-11-20", "2014-12-17",
    # 2015
    "2015-01-16", "2015-02-26", "2015-03-24", "2015-04-17", "2015-05-22",
    "2015-06-18", "2015-07-17", "2015-08-19", "2015-09-16", "2015-10-15",
    "2015-11-17", "2015-12-15",
    # 2016
    "2016-01-20", "2016-02-19", "2016-03-16", "2016-04-14", "2016-05-17",
    "2016-06-16", "2016-07-15", "2016-08-16", "2016-09-16", "2016-10-18",
    "2016-11-17", "2016-12-15",
    # 2017
    "2017-01-18", "2017-02-15", "2017-03-15", "2017-04-14", "2017-05-12",
    "2017-06-14", "2017-07-14", "2017-08-11", "2017-09-14", "2017-10-13",
    "2017-11-15", "2017-12-13",
    # 2018
    "2018-01-12", "2018-02-14", "2018-03-13", "2018-04-11", "2018-05-10",
    "2018-06-12", "2018-07-12", "2018-08-10", "2018-09-13", "2018-10-11",
    "2018-11-14", "2018-12-12",
    # 2019
    "2019-01-11", "2019-02-13", "2019-03-12", "2019-04-10", "2019-05-10",
    "2019-06-12", "2019-07-11", "2019-08-13", "2019-09-12", "2019-10-10",
    "2019-11-13", "2019-12-11",
    # 2020
    "2020-01-14", "2020-02-13", "2020-03-11", "2020-04-10", "2020-05-12",
    "2020-06-10", "2020-07-14", "2020-08-12", "2020-09-11", "2020-10-13",
    "2020-11-12", "2020-12-10",
    # 2021
    "2021-01-13", "2021-02-10", "2021-03-10", "2021-04-13", "2021-05-12",
    "2021-06-10", "2021-07-13", "2021-08-11", "2021-09-14", "2021-10-13",
    "2021-11-10", "2021-12-10",
    # 2022
    "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12", "2022-05-11",
    "2022-06-10", "2022-07-13", "2022-08-10", "2022-09-13", "2022-10-13",
    "2022-11-10", "2022-12-13",
    # 2023
    "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10",
    "2023-06-13", "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12",
    "2023-11-14", "2023-12-12",
    # 2024
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15",
    "2024-06-12", "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10",
    "2024-11-13", "2024-12-11",
    # 2025: only 11 releases published — the "for October 2025" CPI release
    # was skipped/absorbed due to the Oct-Nov 2025 government shutdown; see
    # `missing` below.
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
    "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24",
    "2025-12-18",
    # 2026 (through Aug 2026)
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12",
    "2026-06-10", "2026-07-14", "2026-08-12",
]

JOBS_DATES = [
    # 2013
    "2013-01-04", "2013-02-01", "2013-03-08", "2013-04-05", "2013-05-03",
    "2013-06-07", "2013-07-05", "2013-08-02", "2013-09-06", "2013-10-22",
    "2013-11-08", "2013-12-06",
    # 2014
    "2014-01-10", "2014-02-07", "2014-03-07", "2014-04-04", "2014-05-02",
    "2014-06-06", "2014-07-03", "2014-08-01", "2014-09-05", "2014-10-03",
    "2014-11-07", "2014-12-05",
    # 2015
    "2015-01-09", "2015-02-06", "2015-03-06", "2015-04-03", "2015-05-08",
    "2015-06-05", "2015-07-02", "2015-08-07", "2015-09-04", "2015-10-02",
    "2015-11-06", "2015-12-04",
    # 2016
    "2016-01-08", "2016-02-05", "2016-03-04", "2016-04-01", "2016-05-06",
    "2016-06-03", "2016-07-08", "2016-08-05", "2016-09-02", "2016-10-07",
    "2016-11-04", "2016-12-02",
    # 2017
    "2017-01-06", "2017-02-03", "2017-03-10", "2017-04-07", "2017-05-05",
    "2017-06-02", "2017-07-07", "2017-08-04", "2017-09-01", "2017-10-06",
    "2017-11-03", "2017-12-08",
    # 2018
    "2018-01-05", "2018-02-02", "2018-03-09", "2018-04-06", "2018-05-04",
    "2018-06-01", "2018-07-06", "2018-08-03", "2018-09-07", "2018-10-05",
    "2018-11-02", "2018-12-07",
    # 2019
    "2019-01-04", "2019-02-01", "2019-03-08", "2019-04-05", "2019-05-03",
    "2019-06-07", "2019-07-05", "2019-08-02", "2019-09-06", "2019-10-04",
    "2019-11-01", "2019-12-06",
    # 2020
    "2020-01-10", "2020-02-07", "2020-03-06", "2020-04-03", "2020-05-08",
    "2020-06-05", "2020-07-02", "2020-08-07", "2020-09-04", "2020-10-02",
    "2020-11-06", "2020-12-04",
    # 2021
    "2021-01-08", "2021-02-05", "2021-03-05", "2021-04-02", "2021-05-07",
    "2021-06-04", "2021-07-02", "2021-08-06", "2021-09-03", "2021-10-08",
    "2021-11-05", "2021-12-03",
    # 2022
    "2022-01-07", "2022-02-04", "2022-03-04", "2022-04-01", "2022-05-06",
    "2022-06-03", "2022-07-08", "2022-08-05", "2022-09-02", "2022-10-07",
    "2022-11-04", "2022-12-02",
    # 2023
    "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07", "2023-05-05",
    "2023-06-02", "2023-07-07", "2023-08-04", "2023-09-01", "2023-10-06",
    "2023-11-03", "2023-12-08",
    # 2024
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
    "2024-11-01", "2024-12-06",
    # 2025: only 11 releases published — the "for October 2025" Employment
    # Situation report was cancelled outright (data collection didn't
    # happen) due to the Oct-Nov 2025 government shutdown; see `missing`.
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
    "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05", "2025-11-20",
    "2025-12-16",
    # 2026 (through Aug 2026); 2026-01-09 confirmed via
    # bls.gov/schedule/news_release/empsit.htm (for December 2025 data),
    # not shown on the /schedule/2026/home.htm fetch.
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08",
    "2026-06-05", "2026-07-02", "2026-08-07",
]

MISSING = [
    {"year": 2025, "class": "CPI", "note": "the release covering October 2025 data was skipped/absorbed into the November 2025 data release (published 2025-12-18) because of the Oct-Nov 2025 government shutdown; bls.gov/schedule/2025/home.htm lists only 11 CPI releases for the year"},
    {"year": 2025, "class": "JOBS", "note": "the October 2025 Employment Situation report was cancelled outright (BLS could not collect the data during the Oct-Nov 2025 shutdown); bls.gov/schedule/2025/home.htm lists only 11 releases for the year"},
]


def build_events():
    events = []
    for d in FOMC_SCHEDULED:
        events.append({"date": d, "class": "FOMC", "scheduled": True,
                        "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"})
    for d in FOMC_UNSCHEDULED:
        events.append({"date": d, "class": "FOMC", "scheduled": False,
                        "source": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200303a.htm"})
    for d in CPI_DATES:
        events.append({"date": d, "class": "CPI", "scheduled": True,
                        "source": f"https://www.bls.gov/schedule/{d[:4]}/home.htm"})
    for d in JOBS_DATES:
        events.append({"date": d, "class": "JOBS", "scheduled": True,
                        "source": f"https://www.bls.gov/schedule/{d[:4]}/home.htm"})
    events.sort(key=lambda e: (e["date"], e["class"]))
    return events


def counts_by_year(events):
    counts = defaultdict(lambda: defaultdict(int))
    for e in events:
        counts[e["class"]][e["date"][:4]] += 1
    return {cls: dict(sorted(years.items())) for cls, years in counts.items()}


def sanity_checks(events, spy_sessions):
    print("=" * 70)
    print("SANITY CHECKS")
    print("=" * 70)
    ok = True

    by_class_year = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_class_year[e["class"]][e["date"][:4]].append(e["date"])

    # FOMC: 8 scheduled decisions in a normal year (2013-2025 except 2020).
    print("\n-- FOMC: scheduled decisions per year (expect 8, except 2020=7, 2026 partial) --")
    for y in sorted(by_class_year["FOMC"]):
        sched = [d for d in by_class_year["FOMC"][y]
                 if d not in FOMC_UNSCHEDULED]
        n = len(sched)
        flag = ""
        if y == "2020":
            flag = "" if n == 7 else "  <-- UNEXPECTED"
        elif y == "2026":
            flag = "" if n <= 8 else "  <-- UNEXPECTED"
        else:
            flag = "" if n == 8 else "  <-- UNEXPECTED (not 8)"
        print(f"  {y}: {n}{flag}")

    # CPI: 12 per year, one per month, business days.
    print("\n-- CPI: releases per year (expect 12, except 2025=11, 2026 partial) --")
    for y in sorted(by_class_year["CPI"]):
        n = len(by_class_year["CPI"][y])
        expect_ok = (n == 12) or (y == "2025" and n == 11) or (y == "2026" and n <= 12)
        flag = "" if expect_ok else "  <-- UNEXPECTED"
        print(f"  {y}: {n}{flag}")
        if not expect_ok:
            ok = False

    weekend_cpi = [d for d in CPI_DATES
                   if datetime.date.fromisoformat(d).weekday() >= 5]
    print(f"  CPI dates falling on a weekend: {len(weekend_cpi)} {weekend_cpi}")
    if weekend_cpi:
        ok = False

    # JOBS: 12 per year, almost always Friday.
    print("\n-- JOBS: releases per year (expect 12, except 2025=11, 2026 partial) --")
    for y in sorted(by_class_year["JOBS"]):
        n = len(by_class_year["JOBS"][y])
        expect_ok = (n == 12) or (y == "2025" and n == 11) or (y == "2026" and n <= 12)
        flag = "" if expect_ok else "  <-- UNEXPECTED"
        print(f"  {y}: {n}{flag}")
        if not expect_ok:
            ok = False

    non_friday = [d for d in JOBS_DATES
                  if datetime.date.fromisoformat(d).weekday() != 4]
    print(f"\n  JOBS dates NOT a Friday ({len(non_friday)} of {len(JOBS_DATES)}): {non_friday}")
    if len(non_friday) > len(JOBS_DATES) * 0.15:
        print("  <-- more than ~15% not-Friday, looks like a parsing error")
        ok = False

    # No weekend / no non-session date, checked against SPY.json sessions.
    print("\n-- Non-session release dates (checked against data/mmhl_daily/SPY.json) --")
    non_session = []
    for e in events:
        if e["date"] not in spy_sessions:
            non_session.append(e)
    if non_session:
        for e in non_session:
            wd = datetime.date.fromisoformat(e["date"]).strftime("%A")
            print(f"  {e['date']} ({wd}) class={e['class']} scheduled={e['scheduled']}")
        print("  (expected: BLS/Fed operate on Good Friday even though the stock")
        print("   market is closed that day; the 2020-03-15 FOMC date is the real,")
        print("   Sunday-evening emergency announcement of the cut to zero.)")
    else:
        print("  none")

    # Duplicate (date, class) pairs.
    print("\n-- Duplicate (date, class) pairs --")
    seen = defaultdict(int)
    for e in events:
        seen[(e["date"], e["class"])] += 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    if dupes:
        print(f"  {dupes}")
        ok = False
    else:
        print("  none")

    print("\n" + "=" * 70)
    print("PASS" if ok else "FAIL — see UNEXPECTED / dup lines above")
    print("=" * 70)
    return ok


def main():
    events = build_events()
    with open(SPY_DAILY_PATH) as f:
        spy_sessions = set(json.load(f).keys())

    ok = sanity_checks(events, spy_sessions)

    counts = counts_by_year(events)
    out = {
        "generated": datetime.date.today().isoformat(),
        "sources": SOURCES["FOMC"] + SOURCES["CPI_JOBS"],
        "events": events,
        "missing": MISSING,
        "counts": counts,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {len(events)} events to {OUT_PATH}")
    print(f"Sanity checks: {'PASS' if ok else 'FAIL (see above)'}")


if __name__ == "__main__":
    main()
