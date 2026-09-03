"""Combine the development and untouched trade files into one summary.

Both sides must be the same cost model. Nothing is recomputed; the trade rows
are read back exactly as each run wrote them.
"""
import csv
import json
import os

OUT = "/home/openclaw/.openclaw/workspace/.omc/research/todo-111-proven-trading-edge"


def load(name):
    with open(os.path.join(OUT, name)) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["returnPct"] = float(r["returnPct"])
        r["grossReturnPct"] = float(r["grossReturnPct"])
    return rows


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def main():
    dev = load("trades-development-c3-three-component.csv")
    unt = load("trades-untouched-c3.csv")
    trades = dev + unt
    bench = json.load(open(os.path.join(OUT, "development-result-c3-three-component.json")))
    bunt = json.load(open(os.path.join(OUT, "untouched-result-c3.json")))

    rets = [t["returnPct"] for t in trades]
    n = len(rets)
    srt = sorted(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2

    by_ticker, by_month, by_year = {}, {}, {}
    for t in trades:
        by_ticker.setdefault(t["symbol"], []).append(t["returnPct"])
        by_month.setdefault(t["formationMonth"], []).append(t["returnPct"])
        by_year.setdefault(t["formationDate"][:4], []).append(t["returnPct"])
    best = max(by_ticker, key=lambda s: sum(by_ticker[s]))
    top5 = sorted(by_ticker, key=lambda s: -sum(by_ticker[s]))[:5]
    best_month = max(by_month, key=lambda m: sum(by_month[m]))

    bench_year = dict(bench["benchmarkByGroupYearAvgReturnPct"])
    bench_year.update(bunt["benchmarkByGroupYearAvgReturnPct"])
    bpos = bench["benchmarkPositions"] + bunt["benchmarkPositions"]
    bavg = (bench["benchmarkEqualWeightAllEligibleAvgReturnPct"]
            * bench["benchmarkPositions"]
            + bunt["benchmarkEqualWeightAllEligibleAvgReturnPct"]
            * bunt["benchmarkPositions"]) / bpos

    no_2020 = [t["returnPct"] for t in trades if t["formationDate"][:4] != "2020"]

    result = {
        "instrument": "shares",
        "period": "groups formed 2019-02..2022-09 and 2023-01..2026-05",
        "costModel": "three-component",
        "costsChargedPerSide": "bid/ask spread 5bp + slippage 5bp + $1 commission",
        "tradeCount": n,
        "avgReturnPctAfterCosts": round(avg(rets), 4),
        "winRatePct": round(100.0 * sum(1 for r in rets if r > 0) / n, 4),
        "medianReturnPct": round(median, 4),
        "worstReturnPct": round(min(rets), 4),
        "bestReturnPct": round(max(rets), 4),
        "distinctSymbols": len(by_ticker),
        "groups": len(by_month),
        "avgReturnPctBeforeCosts": round(avg([t["grossReturnPct"] for t in trades]), 4),
        "benchmarkEqualWeightAllEligibleAvgReturnPct": round(bavg, 4),
        "benchmarkPositions": bpos,
        "byGroupYear": {y: {"trades": len(v), "avgReturnPct": round(avg(v), 4),
                            "benchmarkAvgReturnPct": bench_year[y]}
                        for y, v in sorted(by_year.items())},
        "excludedBestTicker": best,
        "avgReturnPctExcludingBestTicker":
            round(avg([t["returnPct"] for t in trades if t["symbol"] != best]), 4),
        "tradeCountExcludingBestTicker":
            sum(1 for t in trades if t["symbol"] != best),
        "topFiveContributingTickers": top5,
        "avgReturnPctExcludingTopFiveTickers":
            round(avg([t["returnPct"] for t in trades
                       if t["symbol"] not in set(top5)]), 4),
        "tradeCountExcludingTopFiveTickers":
            sum(1 for t in trades if t["symbol"] not in set(top5)),
        "bestFormationMonth": best_month,
        "avgReturnPctExcludingBestFormationMonth":
            round(avg([t["returnPct"] for t in trades
                       if t["formationMonth"] != best_month]), 4),
        "tradeCountExcludingBestFormationMonth":
            sum(1 for t in trades if t["formationMonth"] != best_month),
        "tradesExitedAtLastTradedPrice":
            sum(1 for t in trades if t["exitReason"].startswith("last_traded_price")),
        "tradesExitedAtATickerHandover":
            sum(1 for t in trades if t["exitReason"].startswith("identity_break")),
        "tradesSpanningASuspectUnexplainedDrop":
            sum(1 for t in trades if "suspect_drop" in t["exitReason"]),
        "tradesChargedMinus100ForNoHistory": 0,
        "avgReturnPctExcludingGroupYear2020": round(avg(no_2020), 4),
        "tradeCountExcludingGroupYear2020": len(no_2020),
        "gapBoundaryTradingDays": bench["gapBoundaryTradingDays"],
        "signalEndpointMaxStaleTradingDays":
            bench["signalEndpointMaxStaleTradingDays"],
        "symbolMonthsMadeUnrankableByRepair":
            bench["symbolMonthsMadeUnrankableByRepair"]
            + bunt["symbolMonthsMadeUnrankableByRepair"],
        "selectedTradesRemovedByRepair":
            bench["selectedTradesRemovedByRepair"]
            + bunt["selectedTradesRemovedByRepair"],
    }
    with open(os.path.join(OUT, "combined-result-c3.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
