"""Build split- and dividend-adjusted daily closes from the DoltHub stocks clone.

Raw bars, splits and dividends come from post-no-preference/stocks, which unlike
yfinance still carries companies that were later delisted or acquired. The
adjustment is the CRSP/Yahoo convention: walking backwards, each split of ratio r
scales earlier prices by 1/r and each cash dividend D with ex-date t scales
prices before t by (1 - D / close[t-1]).

Three defects in the raw source are handled. All three rules were written and
fixed before any trade return was computed, and none of them depends on a return.

1. The split table repeats a split under two dates (an announcement date and the
   real ex-date) -- AMZN 20:1 appears on 2022-05-26 and again on 2022-06-06 --
   and sometimes dates it on a non-trading day (GE 1:8 on 2021-08-02, a day GE
   has no bar). A split row is applied at the first trading day on or after its
   ex-date, and only if the close actually gapped by the ratio it claims.

2. Isolated bad prints. A close that is 3x above or below BOTH its neighbours is
   a single corrupt bar; the bar is dropped.

3. A ticker can change hands mid-series. DoltHub's META is Meta Materials at $15
   until 2022-06-10 and Facebook at $164 from 2022-06-13. An unexplained one-day
   move of 3x or more whose new level PERSISTS -- the close 20 trading days later
   is still past 2x or under 1/2 of the pre-gap close -- marks a boundary between
   two different securities, and the series is cut there. The persistence test is
   what keeps a real event in: GameStop's +4.5x day in January 2021 is back to
   1.3x within 20 days, so its series stays whole.

Only this source is used; yfinance is never mixed into a calculation.
"""
import csv
import json
import os
from collections import defaultdict

import argparse

TMP = "/root/.claude/jobs/5622c81c/tmp"
DEV = ("/home/openclaw/.openclaw/research-data/todo-111/prices-dolt",
       range(2017, 2023), "2022-12-31", "universe_all.txt",
       ["splits.csv"], ["divs.csv"])
FULL = ("/home/openclaw/.openclaw/research-data/todo-111/prices-dolt-full",
        range(2017, 2027), "2026-09-01", "universe_full.txt",
        ["splits.csv", "splits_late.csv"], ["divs.csv", "divs_late.csv"])
SPLIT_TOLERANCE = 0.25
JUMP = 3.0                 # size of an unexplained one-day move worth judging
PERSIST_DAYS = 20
PERSIST = 2.0              # level still this far from the pre-gap close = persistent
SUSPECT_DROP = 0.40        # residual-risk probe only, never acted on


def load(YEARS, CUTOFF, SPLIT_FILES, DIV_FILES):
    closes = defaultdict(dict)
    for y in YEARS:
        with open(os.path.join(TMP, "ohlcv_%d.csv" % y)) as f:
            for r in csv.DictReader(f):
                if r["date"] <= CUTOFF and r["close"]:
                    c = float(r["close"])
                    if c > 0:
                        closes[r["act_symbol"]][r["date"]] = c
    splits = defaultdict(list)
    for name in SPLIT_FILES:
        with open(os.path.join(TMP, name)) as f:
            for r in csv.DictReader(f):
                to_f, for_f = float(r["to_factor"]), float(r["for_factor"])
                if to_f > 0 and for_f > 0 and r["ex_date"] <= CUTOFF:
                    splits[r["act_symbol"]].append((r["ex_date"], to_f / for_f))
    divs = defaultdict(list)
    for name in DIV_FILES:
        with open(os.path.join(TMP, name)) as f:
            for r in csv.DictReader(f):
                if r["amount"] and r["ex_date"] <= CUTOFF:
                    divs[r["act_symbol"]].append((r["ex_date"], float(r["amount"])))
    return closes, splits, divs


def first_on_or_after(dates, day):
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < day:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(dates) else None


def drop_bad_prints(dates, raw):
    keep = []
    for i in range(len(dates)):
        if 0 < i < len(dates) - 1:
            a, b, c = raw[i - 1], raw[i], raw[i + 1]
            up = b / a >= JUMP and b / c >= JUMP
            down = a / b >= JUMP and c / b >= JUMP
            if up or down:
                continue
        keep.append(i)
    return [dates[i] for i in keep], [raw[i] for i in keep]


def build(dates, raw, splits, divs):
    applied = {}
    for ex, ratio in sorted(splits):
        i = first_on_or_after(dates, ex)
        if i is None or i == 0 or i in applied:
            continue
        if abs((raw[i] / raw[i - 1]) * ratio - 1.0) <= SPLIT_TOLERANCE:
            applied[i] = 1.0 / ratio

    breaks, suspects = [], []
    for i in range(1, len(dates)):
        if i in applied:
            continue
        move = raw[i] / raw[i - 1]
        j = min(i + PERSIST_DAYS, len(dates) - 1)
        after = raw[j] / raw[i - 1]
        if move >= JUMP or move <= 1.0 / JUMP:
            if after >= PERSIST or after <= 1.0 / PERSIST:
                breaks.append(i)
                continue
        if move <= 1.0 - SUSPECT_DROP and after <= 1.0 - SUSPECT_DROP / 2:
            suspects.append(i)

    div_at = defaultdict(float)
    for ex, amount in divs:
        i = first_on_or_after(dates, ex)
        if i is not None and i > 0 and 0 < amount < raw[i - 1]:
            div_at[i] += amount

    factor = 1.0
    out = [0.0] * len(dates)
    for i in range(len(dates) - 1, -1, -1):
        out[i] = raw[i] * factor
        if i in applied:
            factor *= applied[i]
        if i in div_at:
            factor *= (1.0 - div_at[i] / raw[i - 1])
    return out, applied, breaks, suspects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--span", choices=("development", "full"), default="development")
    args = ap.parse_args()
    OUT, YEARS, CUTOFF, UNIVERSE, SPLIT_FILES, DIV_FILES = (
        DEV if args.span == "development" else FULL)
    os.makedirs(OUT, exist_ok=True)
    closes, splits, divs = load(YEARS, CUTOFF, SPLIT_FILES, DIV_FILES)
    universe = sorted({s.strip() for s in
                       open(os.path.join(TMP, UNIVERSE)) if s.strip()})
    stats = defaultdict(int)
    for sym in universe:
        series = closes.get(sym, {})
        dates = sorted(series)
        raw = [series[d] for d in dates]
        before = len(dates)
        dates, raw = drop_bad_prints(dates, raw)
        stats["barsDropped"] += before - len(dates)
        if dates:
            adj, applied, breaks, suspects = build(
                dates, raw, splits.get(sym, []), divs.get(sym, []))
            stats["splitRowsUnconfirmed"] += len(splits.get(sym, [])) - len(applied)
        else:
            adj, breaks, suspects = [], [], []
            stats["noBars"] += 1
        if breaks:
            stats["symbolsWithIdentityBreak"] += 1
        if suspects:
            stats["symbolsWithSuspectDrop"] += 1
        with open(os.path.join(OUT, sym.replace("/", "_") + ".json"), "w") as f:
            json.dump({"symbol": sym, "source": "dolthub-stocks",
                       "adjClose": dict(zip(dates, adj)),
                       "identityBreakDates": [dates[i] for i in breaks],
                       "suspectDropDates": [dates[i] for i in suspects]}, f)
    print("span=%s universe %d %s" % (args.span, len(universe), dict(stats)), flush=True)


if __name__ == "__main__":
    main()
