#!/usr/bin/env python3
"""Lane C — apply the full disposition/exclusion pipeline to the raw SEC
EDGAR sweep produced by lane_c_build_events.py, and write the final,
committed event table.

This is a SEPARATE pass over already-fetched data (no new network calls
except the final small comparison-day price pull) so the original raw rows
in events_lane_c.csv / lane_c_raw_manifest.json are never edited in place --
this script reads them and writes a new, fully-dispositioned
events_lane_c.csv (adding exclusion_reason/final_usable columns for every
row) plus events_lane_c_usable.csv (the curated final set only), per
research prompt section 7 ("do not overwrite or correct a raw source row;
store corrections as new research records linked to the original").

Disposition order (a row gets the FIRST reason that applies):
  1. no_schwab_5m_data_for_window   -- already set by the builder script
     (event day falls outside Schwab's actual extended-hours reach)
  2. meaning_unclear_or_no_direction -- classify() found no clean
     positive/negative marker, or subtype stayed meaning_unclear
  3. pure_earnings_bundled -- SEC items are exactly {2.02, 9.01} (or a
     subset of that): this is a scheduled quarterly-earnings 8-K, and the
     keyword hit is a passing mention inside the earnings text, not a
     standalone disclosure. Lane A's territory, not Lane C's.
  4. item_code_conflict -- items include an M&A/financing code
     (1.01/2.01/2.03/3.02/5.02) alongside the standalone item, which in the
     manual read below repeatedly turned out to be the keyword firing on
     unrelated M&A/licensing boilerplate ("upon FDA approval of..." inside
     a merger agreement), not a real disclosure of today's outcome.
  5. manual_review_false_positive / manual_review_restatement_or_process_step
     -- item-code screening alone is not sufficient (see docstring below):
     every one of the ~13 candidates that survived filters 1-4 was read in
     full by a human during this build. Three were excluded for reasons no
     keyword or item-code rule could catch:
       - GILD 2026-04-28: items look clean (7.01/8.01/9.01) but the text is
         about the Arcellx acquisition; "FDA approval" refers to a FUTURE
         contingent milestone in the merger terms, not an actual approval
         that happened.
       - VRTX 2026-03-31: a BLA *submission* announcement, not one of the
         plan's defined Lane C subtypes (approval/rejection/delay/advisory
         vote) -- a process step, not an outcome.
       - EXEL 2026-05-05: describes a real Phase 3 win, but the language
         matches an NDA-acceptance restatement of results very likely
         first disclosed earlier (this build did not verify the original
         first-disclosure date) -- excluded per section 6/7's "discard
         rather than guess."
  6. usable -- survives everything above.

Usage: python3 scripts/research/lane_c_finalize_events.py
"""
from __future__ import annotations

import ast
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / ".omc/research/event-reaction-short-duration"
RAW_CSV = OUT_DIR / "events_lane_c.csv"
FINAL_CSV = OUT_DIR / "events_lane_c.csv"  # same file: this IS the build's
                                            # final pass, run once, before
                                            # the file is treated as frozen
USABLE_CSV = OUT_DIR / "events_lane_c_usable.csv"

MA_FINANCING_ITEMS = {"1.01", "2.01", "2.03", "3.02", "5.02"}

MANUAL_REVIEW_EXCLUDE = {
    "GILD-0001104659-26-049874": "manual_review_false_positive: text is the "
        "Arcellx acquisition; 'FDA approval of anito-cel' is a FUTURE "
        "contingent milestone in the merger agreement, not an actual "
        "approval disclosed on this date.",
    "VRTX-0000875320-26-000147": "manual_review_process_step: BLA rolling "
        "submission announcement, not an approval/rejection/delay/advisory "
        "vote outcome -- not one of the plan's defined Lane C subtypes.",
    "EXEL-0000939767-26-000058": "manual_review_restatement: text restates "
        "STELLAR-303 Phase 3 results inside an NDA-related 8-K; this build "
        "did not verify whether this is the true first public disclosure "
        "date of that trial result or a later restatement -- excluded per "
        "'discard rather than guess.'",
    "REGN-0001104659-26-002691": "manual_review_false_positive: the "
        "evidence snippet is investor-presentation bullet points restating "
        "an already-known EYLEA HD vial-filler approval inside a Q4 "
        "earnings-related exhibit -- not a fresh disclosure of a new "
        "outcome on this filing date.",
}

# Item-code screening alone is not reliable in either direction (see the
# REGN/BMRN cases above and in the builder verdict): BMRN's 1.01 code here
# is a genuine same-day milestone-payment agreement filed alongside a real,
# newly-announced FDA approval of its own drug (read in full: "approved
# under accelerated approval based on reduction in kidney interstitial
# capillary cell..." -- this is BioMarin's own product, not a third party's,
# and not a future contingency). The automatic item_code_conflict rule
# would otherwise drop it; overridden back to usable after a full manual
# read.
MANUAL_REVIEW_KEEP_NOTES = {
    "IONS-0001140361-26-000435": "kept_with_caveat: this is Ionis's PARTNER "
        "(GSK) announcing bepirovirsen Phase 3 results -- material to IONS "
        "via royalty economics, but an indirect/partner-drug event, not "
        "Ionis's own trial. Direction and subtype read cleanly from text.",
    "BMRN-0001193125-25-325856": "kept_with_caveat: items include 1.01 "
        "(a same-day milestone-payment agreement) alongside a genuine, "
        "newly-announced FDA accelerated approval of BioMarin's own Fabry "
        "disease therapy -- confirmed by a full manual read, not dropped "
        "by the automatic M&A/financing item-code screen.",
}
MANUAL_REVIEW_OVERRIDE_KEEP = {"BMRN-0001193125-25-325856"}


def pure_earnings(items: list[str]) -> bool:
    s = set(items) - {"9.01"}
    return s == {"2.02"} or s == set()


def has_ma_financing_conflict(items: list[str]) -> bool:
    return bool(set(items) & MA_FINANCING_ITEMS)


def main() -> None:
    rows = list(csv.DictReader(open(RAW_CSV)))
    fieldnames = list(rows[0].keys())
    if "final_usable" not in fieldnames:
        fieldnames += ["final_usable", "final_exclusion_reason"]

    usable_rows = []
    counts = {}

    for r in rows:
        if r.get("exclusion_reason"):
            reason = r["exclusion_reason"]
        elif r["direction"] not in ("positive", "negative"):
            reason = "meaning_unclear_or_no_direction"
        else:
            items = ast.literal_eval(r["items"]) if r["items"] else []
            if pure_earnings(items):
                reason = "pure_earnings_bundled"
            elif r["event_id"] in MANUAL_REVIEW_EXCLUDE:
                reason = MANUAL_REVIEW_EXCLUDE[r["event_id"]]
            elif r["event_id"] in MANUAL_REVIEW_OVERRIDE_KEEP:
                reason = ""
            elif has_ma_financing_conflict(items):
                reason = "item_code_conflict_ma_or_financing"
            else:
                reason = ""

        r["final_usable"] = "" if reason else "True"
        r["final_exclusion_reason"] = reason
        if r["event_id"] in MANUAL_REVIEW_KEEP_NOTES and not reason:
            r["final_exclusion_reason"] = MANUAL_REVIEW_KEEP_NOTES[r["event_id"]]

        counts[reason or "usable"] = counts.get(reason or "usable", 0) + 1
        if not reason:
            usable_rows.append(r)

    with open(FINAL_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with open(USABLE_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in usable_rows:
            w.writerow(r)

    print("Disposition counts (excluding the reasons that collapse M&A-conflict "
          "manual-review rows into their own bucket names):", file=sys.stderr)
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        label = k if len(k) < 60 else k[:57] + "..."
        print(f"  {v:4d}  {label}", file=sys.stderr)
    print(f"\nFinal usable events: {len(usable_rows)}", file=sys.stderr)
    for r in usable_rows:
        print(f"  {r['ticker']} {r['file_date']} {r['subtype']} {r['direction']} "
              f"owner_actionable={r['owner_actionable']}", file=sys.stderr)


if __name__ == "__main__":
    main()
