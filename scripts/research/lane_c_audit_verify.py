#!/usr/bin/env python3
"""Lane C INDEPENDENT AUDIT — re-derivation script.

Written by the Lane C auditor (not the builder). Read-only. Does NOT touch
lane_c_build_events.py / lane_c_finalize_events.py or any file they wrote.

Reproduces, from scratch, the four checks the audit's findings rest on:

  1. filings   -- re-fetch all 5 "usable" filings' primary documents from SEC
                  EDGAR and dump plain text for independent classification,
                  plus the filing index pages for Accepted-time / item-code
                  verification.
  2. prices    -- re-derive the Schwab 5-minute extended-hours entry price and
                  60-minute outcome for every usable event, independently of
                  the builder's cached numbers, and additionally compute the
                  outcome under a 6:15 a.m. Pacific entry floor (plan section
                  9's stated start of the owner's action window, which the
                  builder's frozen owner_actionable rule omits).
  3. wire      -- pull Finnhub company-news for each event date and report the
                  earliest wire timestamp vs. the SEC "Accepted" timestamp.
                  This is the check the builder named as untested weakness #1.
  4. structure -- distribution of all 165 raw rows by Pacific time-of-day and
                  by Schwab price-data reach, for the section-16 question of
                  what would make Lane C forward-collectible.

Usage:
    python3 scripts/research/lane_c_audit_verify.py [filings|prices|wire|structure|all]

All times Pacific per project rule.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / ".omc/research/event-reaction-short-duration"
RAW_CSV = OUT_DIR / "events_lane_c.csv"
USABLE_CSV = OUT_DIR / "events_lane_c_usable.csv"
SCRATCH = Path("/tmp/lanec_audit")

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "OpenClaw Research Audit arashchopra@gmail.com"}

# Owner action window, plan section 9: "The owner can act only from 6:15 to
# 6:45 a.m. Pacific."  The builder froze only the 6:45 upper bound.
OWNER_START_H, OWNER_START_M = 6, 15
OWNER_END_HOURS = 6.75


def _get(url: str, timeout: int = 45) -> str:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout
    ).read().decode("utf-8", "replace")


def _detag(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&#8217;|&rsquo;", "'", t)
    t = re.sub(r"&#8211;|&#8212;|&#8722;", "-", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&#\d+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def usable_rows() -> list[dict]:
    return list(csv.DictReader(open(USABLE_CSV)))


def cmd_filings() -> None:
    """Re-pull the 5 filings + their index pages. Verifies Accepted time and
    item codes against the builder's CSV and dumps text for manual reading."""
    SCRATCH.mkdir(exist_ok=True)
    for r in usable_rows():
        eid = r["event_id"]
        cik = r["sec_url"].split("/data/")[1].split("/")[0]
        acc = eid.split("-", 1)[1]
        idx = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
               f"{acc.replace('-', '')}/{acc}-index.htm")

        txt = _detag(_get(r["sec_url"]))
        (SCRATCH / f"{eid}.txt").write_text(txt)

        it = _detag(_get(idx)).replace("<", "|")
        m = re.search(r"Accepted\s*([\d\-]{10}\s[\d:]{8})", it)
        accepted = m.group(1) if m else "??"
        items = sorted(set(re.findall(r"Item\s+(\d+\.\d+)", it)))
        dt = (datetime.strptime(accepted, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
              if m else None)

        print(f"{eid}  ({len(txt)} chars of text -> {SCRATCH / (eid + '.txt')})")
        print(f"   EDGAR Accepted  {accepted} ET"
              f"  = {dt.astimezone(PT):%Y-%m-%d %H:%M:%S} PT" if dt else "")
        print(f"   CSV  accepted_et {r['accepted_et']}"
              f"   {'MATCH' if dt and dt.isoformat() == r['accepted_et'] else 'DIFFERS'}")
        print(f"   EDGAR items {items}   CSV items {r['items']}")
        print()


def _bars(sym: str, day, back_days: int = 2):
    from consensus_engine.scanners import schwab_client as sc
    d = sc.get_price_history(
        sym, interval="5m",
        start=datetime(day.year, day.month, day.day) - timedelta(days=back_days),
        end=datetime(day.year, day.month, day.day) + timedelta(days=1),
        extended_hours=True)
    if d is None or len(d) == 0:
        return None
    d = d.copy()
    d.index = d.index.tz_convert(PT)
    d = d[d.index.date == day]
    return d if len(d) else None


def _window(df, start_pt, mins: int = 60):
    """(status, n_bars, entry_open, pct_return) over [start, start+mins]."""
    if df is None:
        return ("no_data", 0, None, None)
    w = df[(df.index >= start_pt) & (df.index <= start_pt + timedelta(minutes=mins))]
    if len(w) < 2:
        return ("too_thin", len(w), None, None)
    o, c = float(w["Open"].iloc[0]), float(w["Close"].iloc[-1])
    return ("ok", len(w), o, (c / o - 1) * 100)


def cmd_prices() -> None:
    """Re-derive entry and 60-minute outcome for each usable event, plus the
    same outcome under the plan's 6:15 a.m. Pacific entry floor."""
    for r in usable_rows():
        day = datetime.fromisoformat(r["resulting_et"]).astimezone(PT)
        resulting = day
        d = day.date()
        tick = r["ticker"]
        df, spy, xbi = _bars(tick, d), _bars("SPY", d), _bars("XBI", d)
        sign = int(r["direction_sign_used"])

        print(f"===== {r['event_id']}  resulting {resulting:%Y-%m-%d %H:%M:%S} PT =====")
        if df is None:
            print("   no ticker bars\n")
            continue
        nxt = df[df.index >= resulting]
        if not len(nxt):
            print("   no bar at/after resulting time\n")
            continue

        ets = nxt.index[0]
        st, n, o, ret = _window(df, ets)
        signed = None if ret is None else ret * sign
        print(f"   entry {ets:%H:%M} PT @ {o}   bars={n} ({st})")
        print(f"   raw 60m {None if ret is None else round(ret, 3)}"
              f"   direction-signed {None if signed is None else round(signed, 3)}"
              f"   builder ret_60min_raw_pct={r['ret_60min_raw_pct']}")
        for name, bench in (("SPY", spy), ("XBI", xbi)):
            bs, bn, _, bret = _window(bench, ets)
            print(f"   {name:3} over identical clock: {bs} bars={bn} "
                  f"ret={None if bret is None else round(bret, 3)}")

        floor = resulting.replace(hour=OWNER_START_H, minute=OWNER_START_M,
                                  second=0, microsecond=0)
        # Only meaningful for events whose own clock lands at/before the owner
        # window closes; for an afternoon event a 6:15 a.m. entry would price a
        # moment hours BEFORE the news existed.
        ow = df[df.index >= floor] if resulting <= floor.replace(
            hour=6, minute=45) else df.iloc[0:0]
        if len(ow):
            ots = ow.index[0]
            _, _, o2, ret2 = _window(df, ots)
            print(f"   under 6:15am PT entry floor: entry {ots:%H:%M} @ {o2}"
                  f"  raw 60m {None if ret2 is None else round(ret2, 3)}")
        print()


def _finnhub_key() -> str:
    for line in open("/root/.openclaw/.env"):
        m = re.match(r"export FINNHUB_API_KEY=(.+)", line.strip())
        if m:
            return m.group(1).strip().strip("\"'")
    raise SystemExit("FINNHUB_API_KEY not found")


def cmd_wire() -> None:
    """Earliest wire timestamp vs. the SEC Accepted timestamp, per event.
    This is the builder's named-but-untested weakness #1."""
    key = _finnhub_key()
    for r in usable_rows():
        acc_pt = datetime.fromisoformat(r["accepted_et"]).astimezone(PT)
        day = acc_pt.date()
        u = (f"https://finnhub.io/api/v1/company-news?symbol={r['ticker']}"
             f"&from={day}&to={day}&token={key}")
        try:
            rows = json.load(urllib.request.urlopen(u, timeout=30))
        except Exception as e:  # noqa: BLE001
            print(f"{r['event_id']}: Finnhub error {e}")
            continue
        rows.sort(key=lambda x: x.get("datetime", 0))
        print(f"===== {r['event_id']}   8-K Accepted {acc_pt:%Y-%m-%d %H:%M:%S} PT "
              f"({len(rows)} Finnhub rows)")
        for x in rows[:6]:
            ts = datetime.fromtimestamp(x["datetime"], tz=PT)
            lead = (acc_pt - ts).total_seconds() / 3600
            print(f"   {ts:%m-%d %H:%M:%S} PT  (wire leads filing by {lead:+.2f} h)"
                  f"  {x.get('source', '')[:14]:14} | {x.get('headline', '')[:88]}")
        print()


def cmd_structure() -> None:
    """Section-16 inputs: where the 165 raw rows actually die, and whether the
    owner's 6:15-6:45 a.m. Pacific window is the binding constraint."""
    import collections
    rows = list(csv.DictReader(open(RAW_CSV)))
    reach, buckets = collections.Counter(), collections.Counter()
    in_window = 0
    for r in rows:
        excl = r["final_exclusion_reason"] or r["exclusion_reason"] or ""
        reach["no_schwab_5m" if "no_schwab" in excl else "priceable"] += 1
        if not r["accepted_et"]:
            continue
        dt = datetime.fromisoformat(r["accepted_et"]).astimezone(PT) + timedelta(minutes=10)
        h = dt.hour + dt.minute / 60
        if h <= OWNER_END_HOURS:
            in_window += 1
        buckets["<= 6:45am PT (builder rule)" if h <= OWNER_END_HOURS
                else "after 6:45am PT"] += 1

    print("Raw rows:", len(rows))
    for k, v in reach.most_common():
        print(f"   {v:4d}  {k}")
    print()
    for k, v in buckets.most_common():
        print(f"   {v:4d}  {v / len(rows) * 100:5.1f}%  delayed-entry clock {k}")
    print(f"\nOwner-clock-eligible: {in_window}/{len(rows)} "
          f"({in_window / len(rows) * 100:.1f}%) -- the owner window is NOT the "
          f"binding constraint; Schwab price reach is.")

    # earliest date that priced successfully = the real Schwab 5m wall
    ok = [r["file_date"] for r in rows
          if "no_schwab" not in (r["final_exclusion_reason"] or r["exclusion_reason"] or "")]
    print(f"Earliest priceable file_date (the Schwab 5m wall): {min(ok)}")


CMDS = {"filings": cmd_filings, "prices": cmd_prices,
        "wire": cmd_wire, "structure": cmd_structure}

if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name in ([which] if which in CMDS else list(CMDS)):
        print(f"\n########## {name} ##########\n")
        CMDS[name]()
