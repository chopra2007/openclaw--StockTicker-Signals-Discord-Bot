"""Owner-only: print the twenty shares the TODO #111 momentum rule would buy.

Read-only and manual. It reads the cached price series and the local DoltHub
option-chain clone, prints a list, and stops. It places no order, contacts no
broker, writes no file, and touches nothing the live bot uses.

    python3 scripts/research/todo_111_momentum_picks.py
    python3 scripts/research/todo_111_momentum_picks.py --month 2026-03
"""
import argparse
import bisect
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import todo_111_momentum_quarter as rule

PACIFIC = ZoneInfo("America/Los_Angeles")
OPTIONS_DB = "/home/openclaw/.openclaw/research-data/todo-111/dolt-stocks/../dolt/options"
RESEARCH = ("/home/openclaw/.openclaw/workspace/.omc/research/"
            "todo-111-proven-trading-edge")


def eligible_symbols(month_end):
    """Every symbol quoted in the option market on the last snapshot on or before
    the formation date. One read-only query against the local clone."""
    lo = "%04d-%s" % (int(month_end[:4]) - 1, month_end[5:])
    dates = subprocess.run(
        ["dolt", "sql", "-q",
         "select distinct date from option_chain "
         "where date>='%s' and date<='%s' order by date" % (lo, month_end),
         "-r", "csv"],
        cwd=OPTIONS_DB, capture_output=True, text=True, check=True).stdout
    snaps = [r["date"] for r in csv.DictReader(io.StringIO(dates))]
    if not snaps:
        raise SystemExit("no option snapshot on or before %s" % month_end)
    snapshot = snaps[-1]
    rows = subprocess.run(
        ["dolt", "sql", "-q",
         "select distinct act_symbol from option_chain where date='%s'" % snapshot,
         "-r", "csv"],
        cwd=OPTIONS_DB, capture_output=True, text=True, check=True).stdout
    return snapshot, sorted({r["act_symbol"] for r in csv.DictReader(io.StringIO(rows))})


def picks(month, month_end, prices, calendar):
    """The frozen rule's ranking, using only prices before the formation close."""
    t1 = rule.month_shift(month, 1)
    t0 = rule.month_shift(month, 12)
    month_ends = json.load(open(rule.PERIODS["untouched"]["calendar"]))["monthEnd"]
    snapshot, symbols = eligible_symbols(month_end)

    ranked, unpriced = [], 0
    for sym in symbols:
        entry = prices.get(sym)
        if entry is None or not entry[0]:
            unpriced += 1
            continue
        dates, vals, bounds, _, _ident = entry
        prior = bisect.bisect_right(dates, month_end)
        if prior == 0 or dates[prior - 1] != month_end:
            continue
        f_i = prior - 1
        signal, _why = rule.signal_for(dates, vals, bounds, f_i,
                                       month_ends[t0], month_ends[t1],
                                       calendar, True)
        if signal is None:
            continue
        ranked.append((signal, sym, vals[f_i]))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return snapshot, len(ranked), unpriced, ranked[:rule.TOP_N]


def header(month, month_end, snapshot, considered, dev, unt):
    now = datetime.now(PACIFIC)
    exit_month = rule.month_shift(month, -3)
    return "\n".join([
        "=" * 78,
        "TODO #111 momentum picks - owner only, nothing is ordered",
        "=" * 78,
        "",
        "The rule: each month, buy the twenty shares that rose the most over the",
        "past year ignoring the most recent month, and sell each one three months",
        "later.",
        "",
        "What it measured on past data, average per trade after costs",
        "(bid/ask spread 5bp + slippage 5bp + $1 commission, each side):",
        "  2019-02 to 2022-09   %+.2f%% per trade over %d trades" % (
            dev["avgReturnPctAfterCosts"], dev["tradeCount"]),
        "  2023-01 to 2026-05   %+.2f%% per trade over %d trades" % (
            unt["avgReturnPctAfterCosts"], unt["tradeCount"]),
        "",
        "Read the first line carefully. Almost all of that first result came from",
        "one year: groups started in 2020 averaged %+.2f%%, and with 2020 taken out"
        % dev["byGroupYear"]["2020"]["avgReturnPct"],
        "the rest of that half is roughly flat. The second period was steadier, but",
        "it contains no sharp market reversal, which is when this kind of rule",
        "historically does its worst.",
        "",
        "These are measurements of what already happened. They are not a forecast",
        "and not a promise of future profit. This script places NO order of any",
        "kind, talks to no broker, and changes nothing.",
        "",
        "-" * 78,
        "Formation month %s   buy at the close of %s (Pacific dates)" % (month, month_end),
        "Sell date under the rule: the last trading day of %s" % exit_month,
        "Option-market snapshot used for the eligible list: %s" % snapshot,
        "Shares ranked: %d" % considered,
        "Printed %s" % now.strftime("%Y-%m-%d %H:%M %Z"),
        "-" * 78,
        "",
    ])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", help="formation month, YYYY-MM "
                                    "(default: the most recent completed month)")
    args = ap.parse_args()

    month_ends = json.load(open(rule.PERIODS["untouched"]["calendar"]))["monthEnd"]
    today = datetime.now(PACIFIC).strftime("%Y-%m")
    month = args.month or rule.month_shift(today, 1)
    if month not in month_ends:
        raise SystemExit("no trading calendar for %s" % month)
    if month >= today:
        raise SystemExit("%s is not a completed month" % month)
    month_end = month_ends[month]

    dev = json.load(open(os.path.join(
        RESEARCH, "development-result-c3-three-component.json")))
    unt = json.load(open(os.path.join(RESEARCH, "untouched-result-c3.json")))

    prices, calendar = rule.load_prices(rule.PERIODS["untouched"]["prices"],
                                        month_end)
    snapshot, considered, unpriced, top = picks(month, month_end, prices,
                                                calendar)

    print(header(month, month_end, snapshot, considered, dev, unt))
    print("%4s  %-8s %14s  %14s" % ("rank", "ticker", "12-month rise", "close paid"))
    print("%4s  %-8s %14s  %14s" % ("-" * 4, "-" * 8, "-" * 14, "-" * 14))
    for i, (signal, sym, price) in enumerate(top, 1):
        print("%4d  %-8s %13.1f%%  %14s" % (i, sym, signal * 100, "$%.2f" % price))
    print()
    print("Twenty positions, $10,000 each. The rise column skips the most recent")
    print("month on purpose - that is the part that tends to reverse.")
    if unpriced:
        print("%d symbols in the snapshot have no cached price history and were "
              "not ranked." % unpriced)


if __name__ == "__main__":
    main()
