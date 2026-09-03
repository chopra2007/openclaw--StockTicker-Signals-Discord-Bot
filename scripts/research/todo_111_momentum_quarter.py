"""TODO #111 candidate 3 -- twelve-month winners held for a quarter.

Implements frozen-rule-candidate-3.md. The rule itself is never varied: signal,
top 20, three-month hold, 250-day minimum, monthly overlapping groups and the
point-in-time option-chain universe are all fixed.

Two things are selectable from the command line, and neither touches the rule:

* --period development (groups formed 2019-02..2022-09) or untouched
  (2023-01 onward). The untouched window was not computed until the development
  number was recorded.
* --costs frozen (5bp per side, $1 per side) or three-component (bid/ask spread
  5bp + slippage 5bp = 10bp per side, $1 per side). The three-component model is
  strictly more expensive on every trade, so it cannot turn a fail into a pass.

Prices are hard-truncated at the period's cutoff on load, so a price from after
the window cannot reach the result.
"""
import argparse
import bisect
import csv
import glob
import json
import os

TMP = "/root/.claude/jobs/5622c81c/tmp"
OUT = "/home/openclaw/.openclaw/workspace/.omc/research/todo-111-proven-trading-edge"

POSITION_USD = 10000.0
COMMISSION_USD_PER_SIDE = 1.0
SPREAD_BPS_PER_SIDE = 5.0
SLIPPAGE_BPS_PER_SIDE = 5.0
TOP_N = 20
MIN_PRIOR_DAYS = 250

# Repair after independent verification. A ticker can become a different company
# across a HOLE in the data, where there is no price jump to detect: DoltHub's
# BBWI stops in June 2019 as L Brands and restarts in August 2021 as Bath & Body
# Works. Two clauses close that, and neither looks at a return.
GAP_BOUNDARY_TRADING_DAYS = 21          # a hole this long is a segment boundary
SIGNAL_ENDPOINT_MAX_STALE_TRADING_DAYS = 5   # both signal prices must be fresh
CALENDAR_SYMBOL_SHARE = 0.2             # a market day is one at least this many
                                        # of the priced symbols traded on

COSTS = {
    # name: rate charged against the position on each side, on top of commission
    "frozen": (SLIPPAGE_BPS_PER_SIDE) / 10000.0,
    "three-component": (SPREAD_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE) / 10000.0,
}

PERIODS = {
    "development": {"first": "2019-02", "last": "2022-09", "cutoff": "2022-12-31",
                    "prices": "/home/openclaw/.openclaw/research-data/todo-111/prices-dolt",
                    "formation": os.path.join(TMP, "formation.json"),
                    "calendar": os.path.join(TMP, "calendar.json"),
                    "symbols": os.path.join(TMP, "symbols")},
    "untouched": {"first": "2023-01", "last": "2026-05", "cutoff": "2026-09-01",
                  "prices": "/home/openclaw/.openclaw/research-data/todo-111/prices-dolt-full",
                  "formation": os.path.join(TMP, "formation_untouched.json"),
                  "calendar": os.path.join(TMP, "calendar_full.json"),
                  "symbols": os.path.join(TMP, "symbols_untouched")},
}


def load_prices(price_dir, cutoff):
    """(per-symbol series, market trading calendar).

    Per symbol: (dates, values, segment boundaries, suspect-drop dates,
    identity-only boundaries). A boundary is a date at which the ticker changed
    hands -- either a detected price-jump handover (see the price builder) or a
    hole of GAP_BOUNDARY_TRADING_DAYS or more in the symbol's own series, which
    is the same event with no jump to see. Prices either side of one belong to
    different companies, so a signal, an entry and an exit must all sit inside
    one segment.

    The trading calendar is derived from the price set itself: a market day is
    one that at least CALENDAR_SYMBOL_SHARE of the symbols traded on. It matches
    SPY's own calendar exactly over the overlap, and drops 2020-02-17, a market
    holiday on which the source carries bars for 170 symbols.
    """
    loaded, day_count = [], {}
    for path in glob.glob(os.path.join(price_dir, "*.json")):
        with open(path) as f:
            rec = json.load(f)
        series = {d: v for d, v in rec["adjClose"].items() if d <= cutoff}
        dates = sorted(series)
        for d in dates:
            day_count[d] = day_count.get(d, 0) + 1
        loaded.append((rec, dates, [series[d] for d in dates]))

    floor = CALENDAR_SYMBOL_SHARE * len(loaded)
    calendar = sorted(d for d, k in day_count.items() if k >= floor)

    out = {}
    for rec, dates, vals in loaded:
        idx = {d: i for i, d in enumerate(dates)}
        ident = sorted(idx[d] for d in rec.get("identityBreakDates", []) if d in idx)
        bounds = set(ident)
        for i in range(1, len(dates)):
            if trading_days_between(calendar, dates[i - 1], dates[i]) \
                    >= GAP_BOUNDARY_TRADING_DAYS:
                bounds.add(i)
        suspects = {d for d in rec.get("suspectDropDates", []) if d <= cutoff}
        out[rec["symbol"]] = (dates, vals, sorted(bounds), suspects, ident)
    return out, calendar


def calendar_pos(calendar, day):
    """Index of day in the market calendar, or of the last market day before it."""
    return bisect.bisect_right(calendar, day) - 1


def trading_days_between(calendar, earlier, later):
    """Market days skipped between two consecutive observations."""
    return calendar_pos(calendar, later) - calendar_pos(calendar, earlier) - 1


def signal_for(dates, vals, bounds, f_i, t0, t1, calendar, fresh):
    """The frozen 12-month-skip-1 signal, or (None, why it cannot be ranked)."""
    lo, _hi = segment(bounds, f_i, len(dates))
    if f_i - lo + 1 < MIN_PRIOR_DAYS:
        return None, "tooShort"
    d0, p0, _ = as_of(dates, vals, t0, lo)
    d1, p1, _ = as_of(dates, vals, t1, lo)
    if p0 is None or p1 is None or p0 <= 0:
        return None, "noSignalPrice"
    if fresh:
        stale = max(trading_days_between(calendar, d0, t0) + 1,
                    trading_days_between(calendar, d1, t1) + 1)
        if stale > SIGNAL_ENDPOINT_MAX_STALE_TRADING_DAYS:
            return None, "staleSignalEndpoint"
    return p1 / p0 - 1.0, None


def segment(bounds, i, n):
    """Half-open [lo, hi) of the segment containing index i."""
    lo, hi = 0, n
    for b in bounds:
        if b <= i:
            lo = b
        else:
            hi = b
            break
    return lo, hi


def as_of(dates, vals, day, lo=0):
    """Last close on or before day, not earlier than index lo."""
    i = bisect.bisect_right(dates, day) - 1
    if i < lo:
        return None, None, None
    return dates[i], vals[i], i


def month_shift(month, back):
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) - back
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def run(period, cost_name):
    cfg = PERIODS[period]
    rate = COSTS[cost_name]
    cutoff = cfg["cutoff"]
    formation = json.load(open(cfg["formation"]))
    month_end = json.load(open(cfg["calendar"]))["monthEnd"]
    prices, calendar = load_prices(cfg["prices"], cutoff)

    universe = {}
    for month, info in formation.items():
        with open(os.path.join(cfg["symbols"], info["snapshot"] + ".csv")) as f:
            universe[month] = sorted({r["act_symbol"] for r in csv.DictReader(f)})

    trades, bench = [], []
    skipped = {"noHistoryAtAll": 0, "tooShort": 0, "noSignalPrice": 0,
               "noCloseOnFormationDate": 0, "staleSignalEndpoint": 0}
    no_history_symbols = set()
    made_unrankable_by_repair = 0
    removed_by_repair = []

    for month in sorted(formation):
        f_date = month_end[month]
        t1 = month_end[month_shift(month, 1)]
        t0 = month_end[month_shift(month, 12)]
        x_date = month_end[month_shift(month, -3)]
        assert x_date <= cutoff, (month, x_date)

        ranked, ranked_before = [], []
        for sym in universe[month]:
            entry = prices.get(sym)
            if entry is None or not entry[0]:
                skipped["noHistoryAtAll"] += 1
                no_history_symbols.add(sym)
                continue
            dates, vals, bounds, _, ident = entry
            prior = bisect.bisect_right(dates, f_date)
            if prior == 0 or dates[prior - 1] != f_date:
                skipped["noCloseOnFormationDate"] += 1
                continue
            f_i = prior - 1
            # The same ranking without the repair, kept only to report what the
            # two new clauses changed.
            before, _ = signal_for(dates, vals, ident, f_i, t0, t1,
                                   calendar, False)
            if before is not None:
                ranked_before.append((before, sym))
            signal, why = signal_for(dates, vals, bounds, f_i, t0, t1,
                                     calendar, True)
            if signal is None:
                skipped[why] += 1
                if before is not None:
                    made_unrankable_by_repair += 1
                continue
            ranked.append((signal, sym, vals[f_i]))

        ranked.sort(key=lambda r: (-r[0], r[1]))
        ranked_before.sort(key=lambda r: (-r[0], r[1]))
        selected = {r[1] for r in ranked[:TOP_N]}
        for _sig, sym in ranked_before[:TOP_N]:
            if sym not in selected:
                removed_by_repair.append("%s %s" % (month, sym))

        def build(rank, signal, sym, entry_price):
            dates, vals, bounds, suspects, _ident = prices[sym]
            f_i = bisect.bisect_right(dates, f_date) - 1
            _lo, hi = segment(bounds, f_i, len(dates))
            j = bisect.bisect_right(dates, x_date) - 1
            if j >= hi:                       # the ticker changed hands mid-hold
                j = hi - 1
                reason = "identity_break"
            elif dates[j] != x_date:
                reason = "last_traded_price"
            else:
                reason = "scheduled"
            xd, xp = dates[j], vals[j]
            if any(f_date < d <= xd for d in suspects):
                reason += "+suspect_drop"
            shares = POSITION_USD / entry_price
            cost = POSITION_USD * (1 + rate) + COMMISSION_USD_PER_SIDE
            value = shares * xp * (1 - rate) - COMMISSION_USD_PER_SIDE
            return {"symbol": sym, "formationMonth": month, "formationDate": f_date,
                    "entryDate": f_date, "entryPrice": round(entry_price, 6),
                    "exitDate": xd, "exitPrice": round(xp, 6),
                    "signal": round(signal, 6), "rank": rank,
                    "costsUsd": round(POSITION_USD * rate * 2
                                      + 2 * COMMISSION_USD_PER_SIDE, 4),
                    "returnPct": round((value - cost) / cost * 100, 6),
                    "grossReturnPct": round((shares * xp - POSITION_USD)
                                            / POSITION_USD * 100, 6),
                    "exitReason": reason}

        for rank, row in enumerate(ranked[:TOP_N], 1):
            trades.append(build(rank, *row))
        for rank, row in enumerate(ranked, 1):
            b = build(rank, *row)
            bench.append((f_date[:4], b["returnPct"]))

    return (trades, bench, skipped, no_history_symbols, formation,
            made_unrankable_by_repair, removed_by_repair)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def summarise(period, cost_name, trades, bench, skipped, no_history, formation,
              unrankable_by_repair, removed_by_repair):
    rets = [t["returnPct"] for t in trades]
    n = len(rets)
    srt = sorted(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2

    by_ticker, by_month, by_year = {}, {}, {}
    for t in trades:
        by_ticker.setdefault(t["symbol"], []).append(t["returnPct"])
        by_month.setdefault(t["formationMonth"], []).append(t["returnPct"])
        by_year.setdefault(t["formationDate"][:4], []).append(t["returnPct"])

    best_ticker = max(by_ticker, key=lambda s: sum(by_ticker[s]))
    top5 = sorted(by_ticker, key=lambda s: -sum(by_ticker[s]))[:5]
    best_month = max(by_month, key=lambda m: sum(by_month[m]))

    no_best = [t["returnPct"] for t in trades if t["symbol"] != best_ticker]
    no_top5 = [t["returnPct"] for t in trades if t["symbol"] not in set(top5)]
    no_month = [t["returnPct"] for t in trades if t["formationMonth"] != best_month]
    no_2020 = [t["returnPct"] for t in trades if t["formationDate"][:4] != "2020"]

    bench_year = {}
    for y, r in bench:
        bench_year.setdefault(y, []).append(r)
    bench_rets = [r for _, r in bench]

    return {
        "instrument": "shares",
        "period": "groups formed %s..%s" % (PERIODS[period]["first"],
                                            PERIODS[period]["last"]),
        "costModel": cost_name,
        "costsChargedPerSide": ("bid/ask spread 5bp + slippage 5bp + $1 commission"
                                if cost_name == "three-component"
                                else "slippage 5bp + $1 commission"),
        "tradeCount": n,
        "avgReturnPctAfterCosts": round(avg(rets), 4),
        "winRatePct": round(100.0 * sum(1 for r in rets if r > 0) / n, 4),
        "medianReturnPct": round(median, 4),
        "worstReturnPct": round(min(rets), 4),
        "bestReturnPct": round(max(rets), 4),
        "distinctSymbols": len(by_ticker),
        "groups": len(formation),
        "tradesExitedAtLastTradedPrice":
            sum(1 for t in trades if t["exitReason"].startswith("last_traded_price")),
        "tradesExitedAtATickerHandover":
            sum(1 for t in trades if t["exitReason"].startswith("identity_break")),
        "tradesSpanningASuspectUnexplainedDrop":
            sum(1 for t in trades if "suspect_drop" in t["exitReason"]),
        "tradesChargedMinus100ForNoHistory": 0,
        "avgReturnPctBeforeCosts": round(avg([t["grossReturnPct"] for t in trades]), 4),
        "benchmarkEqualWeightAllEligibleAvgReturnPct": round(avg(bench_rets), 4),
        "benchmarkPositions": len(bench_rets),
        "benchmarkByGroupYearAvgReturnPct":
            {y: round(avg(v), 4) for y, v in sorted(bench_year.items())},
        "byGroupYear": {y: {"trades": len(v), "avgReturnPct": round(avg(v), 4),
                            "benchmarkAvgReturnPct": round(avg(bench_year[y]), 4)}
                        for y, v in sorted(by_year.items())},
        "excludedBestTicker": best_ticker,
        "avgReturnPctExcludingBestTicker": round(avg(no_best), 4),
        "tradeCountExcludingBestTicker": len(no_best),
        "topFiveContributingTickers": top5,
        "avgReturnPctExcludingTopFiveTickers": round(avg(no_top5), 4),
        "tradeCountExcludingTopFiveTickers": len(no_top5),
        "bestFormationMonth": best_month,
        "avgReturnPctExcludingBestFormationMonth": round(avg(no_month), 4),
        "tradeCountExcludingBestFormationMonth": len(no_month),
        "avgReturnPctExcludingGroupYear2020":
            round(avg(no_2020), 4) if no_2020 else None,
        "tradeCountExcludingGroupYear2020": len(no_2020),
        "gapBoundaryTradingDays": GAP_BOUNDARY_TRADING_DAYS,
        "signalEndpointMaxStaleTradingDays": SIGNAL_ENDPOINT_MAX_STALE_TRADING_DAYS,
        "symbolMonthsMadeUnrankableByRepair": unrankable_by_repair,
        "selectedTradesRemovedByRepair": removed_by_repair,
        "eligibilitySkips": skipped,
        "symbolsWithNoPriceHistoryAtAll": len(no_history),
    }


def write_trades(path, trades):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0]))
        w.writeheader()
        w.writerows(trades)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=sorted(PERIODS), default="development")
    ap.add_argument("--costs", choices=sorted(COSTS), default="frozen")
    ap.add_argument("--out")
    ap.add_argument("--trades")
    args = ap.parse_args()

    (trades, bench, skipped, no_hist, formation, unrankable,
     removed) = run(args.period, args.costs)
    result = summarise(args.period, args.costs, trades, bench, skipped, no_hist,
                       formation, unrankable, removed)
    if args.out:
        with open(os.path.join(OUT, args.out), "w") as f:
            json.dump(result, f, indent=1)
    if args.trades:
        write_trades(os.path.join(OUT, args.trades), trades)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
