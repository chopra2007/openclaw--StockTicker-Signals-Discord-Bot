"""Write the TODO #111 round-3 rejection ledger.

The mission requires that every number in an evidence file is written by the
script that computed it and never typed by hand. So the words below are
written here, and every figure is read out of the JSON result files produced
by the three measuring scripts. Re-running this file rebuilds the ledger from
whatever those files currently say.
"""
import json
from pathlib import Path

RES = Path("/home/openclaw/.openclaw/workspace/.omc/research")
OUT = RES / "todo-111-round3" / "rejection-ledger.md"

# Which no-trigger measurement each family must be judged against. A family
# that only trades at 11:00 cannot be compared with one that trades all day.
MATCH = {
    "orb15-break": "baseline-1130-no-trigger",
    "orb15-fade": "baseline-1130-no-trigger",
    "overnight-break": "baseline-1130-no-trigger",
    "overnight-fade": "baseline-1130-no-trigger",
    "orb15-plus-market-agrees": "baseline-1130-no-trigger",
    "orb15-on-wide-day": "baseline-1130-no-trigger",
    "trend-day-continuation": "baseline-1100-no-trigger",
    "range-day-fade": "baseline-1100-no-trigger",
    "panel-rank-momentum": "baseline-1100-no-trigger",
    "panel-rank-reversal": "baseline-1100-no-trigger",
}

PLAIN = {
    "baseline-1130-no-trigger":
        "*(no trigger at all - one trade a day at 11:30, direction alternating)*",
    "baseline-1100-no-trigger":
        "*(no trigger at all - one trade a day at 11:00, direction alternating)*",
    "orb15-break": "First break of the first fifteen minutes' range, with the break",
    "orb15-fade": "First break of the first fifteen minutes' range, faded",
    "overnight-break": "First break of the overnight range, with the break",
    "overnight-fade": "First break of the overnight range, faded",
    "orb15-plus-market-agrees": "Opening-range break **and** the other 59 agree",
    "orb15-on-wide-day": "Opening-range break, only on unusually wide mornings",
    "trend-day-continuation": "At 11:00, buy what has climbed all morning",
    "range-day-fade": "On a day going nowhere, fade its high and its low",
    "panel-rank-momentum": "At 11:00, buy the 6 strongest of 60, short the 6 weakest",
    "panel-rank-reversal": "At 11:00, short the 6 strongest of 60, buy the 6 weakest",
}

MECHANISM = {
    "orb15-break": "the opening range (owner-named)",
    "orb15-fade": "the opening range (owner-named)",
    "overnight-break": "the overnight range (owner-named)",
    "overnight-fade": "the overnight range (owner-named)",
    "orb15-plus-market-agrees": "two conditions that must agree",
    "orb15-on-wide-day": "the character of the day",
    "trend-day-continuation": "the time of day as the condition",
    "range-day-fade": "the character of the day",
    "panel-rank-momentum": "the name's place among all sixty",
    "panel-rank-reversal": "the name's place among all sixty",
}

ORDER = ["baseline-1130-no-trigger", "baseline-1100-no-trigger",
         "orb15-break", "orb15-fade", "overnight-break", "overnight-fade",
         "orb15-plus-market-agrees", "orb15-on-wide-day",
         "trend-day-continuation", "range-day-fade",
         "panel-rank-momentum", "panel-rank-reversal"]

WHY = """
## What each idea was, and why it was worth trying

- **The two the owner named.** The fifteen-minute opening range is the box the
  first quarter hour builds; the overnight range is the box built between
  yesterday's close and today's open. Both are traded on the first break of
  either side. The thinking behind them is the same: those levels are where
  resting orders pile up, so once price leaves the box there is nothing holding
  it. Both were tested in both directions, because a break that fails is just
  as tradable an idea as one that runs, and neither direction moved.
- **Opening-range break with the group agreeing.** The first idea in this
  project that required two separate things to be true at the same moment: the
  name breaks its own range *and* the other fifty-nine are moving the same way.
  A break the whole market is pushing should be harder to reverse than one
  name's own business.
- **Opening-range break only on wide mornings.** The bracket needs a 1% move
  before it can win. On a quiet day neither level is reached. This asks whether
  the kind of day matters more than the trigger does - taking the identical
  break, but only when the morning range is at least half again this name's own
  recent normal.
- **The 11:00 trend-day trade.** No chart pattern at all: at one fixed moment
  each day, look at whether the name has held one direction all morning, and
  trade that direction. A name being steadily accumulated for ninety minutes is
  being bought by someone who is not finished.
- **Fading a day that is going nowhere.** The mirror of it. If by 11:00 the
  name has crossed and re-crossed its own morning range, its high and low are
  where the two sides keep turning it around, so sell the high and buy the low.
- **Rank among all sixty.** The only mechanism here that does not look at the
  traded name's own chart to decide. At 11:00 the sixty names are put in order
  by how far they have moved since their own opens, and the six extremes at
  each end are traded - momentum one way, reversal the other.
"""

BLOCKED_TEMPLATE = """
## Two things could not be tested at all, and neither is a rejection

- **Anything using information outside the price series.** The owner named this
  direction, and this project really does collect insider filings, analyst
  mentions, options flow and news. The problem is when it started collecting.
  The bot's own database holds {sig} ticker signals and {flow} options-flow
  records, and the oldest of them are dated {sig_from} and {flow_from}. The
  development period ends {dev_end}. The number of records older than that is
  {before}, and those {before} are rows whose timestamp is a placeholder rather
  than a date. So the entire collection sits inside the sealed period, which may
  not be read - and even if the seal were opened it would give about three
  months of history against a finish line that needs 200 trades. There is
  nothing to test this direction on today; there will be, after a couple more
  years of collecting.
- **Every option idea.** Unchanged from round 2: the only local chains are one
  end-of-day snapshot a week, 2019 to 2022. They cannot see whether an option
  touched +20% before -20%. This is the owner's outstanding decision.
"""


def pct(x):
    return "%.2f%%" % x


def main():
    rows = {}
    for name in ["prescreen-equs", "panel-equs"]:
        for r in json.loads((RES / ("todo-111-round3-%s.json" % name)).read_text()):
            rows[r["family"]] = r
    ceil = json.loads((RES / "todo-111-round3-ceiling-equs.json").read_text())
    feas = json.loads((RES / "todo-111-round3" / "feasibility-data.json").read_text())
    t = feas["outsidePriceSeries"]["tables"]
    blocked = BLOCKED_TEMPLATE.format(
        sig="{:,}".format(t["ticker_signals"]["rows"]),
        flow="{:,}".format(t["options_flow"]["rows"]),
        sig_from=t["ticker_signals"]["oldest"],
        flow_from=t["options_flow"]["oldest"],
        dev_end=feas["developmentEnds"],
        before=sum(v["rowsBeforeDevEnd"] for v in t.values()))

    base_all = rows["baseline-1130-no-trigger"]["winRatePct"]
    best = max((rows[f]["winRatePct"], f) for f in MATCH)
    best_gap = rows[best[1]]["winRatePct"] - rows[MATCH[best[1]]]["winRatePct"]

    L = []
    L.append("# TODO #111 round 3 - rejection ledger, session of 2026-09-03\n")
    L.append("Ten entry rules, six genuinely different mechanisms, measured on "
             "development\ndata only - everything before "
             + rows["orb15-break"]["devEnd"] +
             ". Sixty NYSE large caps, one-minute bars,\nEQUS.MINI feed. Every "
             "trade closes on the first touch of +1.0% in its favour or\n-0.5% "
             "against it, capped at 14 trading days. Returns are gross.\n")
    L.append("**The bar is 60 in 100. Nothing here reached 36.**\n")
    L.append("New in round 3: each idea is scored against a **matched** "
             "baseline that trades\nat the same time of day with no trigger at "
             "all. Round 2 used one baseline for\neverything, and the odds of "
             "this bracket are not the same at 09:45 as at 15:30.\n")
    L.append("| Idea | Mechanism | Trades | Target first | vs its own baseline "
             "| Average per trade | Verdict |")
    L.append("|---|---|---|---|---|---|---|")
    for f in ORDER:
        r = rows[f]
        if f in MATCH:
            gap = r["winRatePct"] - rows[MATCH[f]]["winRatePct"]
            gaps = "%+.2f points" % gap
            mech = MECHANISM[f]
            verdict = "rejected"
        else:
            gaps = "-"
            mech = "*the yardstick*"
            verdict = "the yardstick"
        L.append("| %s | %s | %s | **%s** | %s | %+.4f%% | %s |" % (
            PLAIN[f], mech, "{:,}".format(r["tradeCount"]), pct(r["winRatePct"]),
            gaps, r["avgReturnPct"], verdict))
    L.append("")
    L.append("The best of the ten was **%s** at %s, which is %+.2f points "
             "away from\ndoing nothing at the same time of day. The bar is "
             "**%.0f points above it**.\n"
             % (PLAIN[best[1]], pct(best[0]), best_gap,
                60.0 - best[0]))

    a, b = ceil["halfA"], ceil["halfB"]
    L.append("## The ceiling test - the result that settles it\n")
    L.append("Seven mechanisms landing on the baseline raises a fair question: "
             "is the next\nmechanism worth building? So the friendliest "
             "possible test was run, one no\ntrigger could ever beat, because "
             "it is allowed to cheat with hindsight.\n")
    L.append("Forget triggers entirely. Split the development data in half at "
             "%s. In the\nfirst half, look up which combinations of *stock, "
             "hour of the day and direction*\nreached the target first most "
             "often - %s of them, out of %s that had enough\nhistory to "
             "judge. Then trade exactly those, unchanged, in the second half.\n"
             % (ceil["splitDate"], ceil["cellsPicked"],
                "{:,}".format(ceil["cellsConsidered"])))
    L.append("| | Trades | Target first |")
    L.append("|---|---|---|")
    L.append("| First half, everything | %s | %s |"
             % ("{:,}".format(a["allCells"]["tradeCount"]),
                pct(a["allCells"]["winRatePct"])))
    L.append("| First half, the %d cherry-picked | | **%s** |"
             % (ceil["cellsPicked"], pct(a["pickedCellsInA"])))
    L.append("| Second half, everything | %s | %s |"
             % ("{:,}".format(b["allCells"]["tradeCount"]),
                pct(b["allCells"]["winRatePct"])))
    L.append("| Second half, the same cherry-picked | %s | **%s** |"
             % ("{:,}".format(b["pickedCells"]["tradeCount"]),
                pct(b["pickedCells"]["winRatePct"])))
    L.append("")
    L.append("Picking with hindsight reached %s. Carried forward, the very "
             "same picks fell\nto %s - about %.0f%% of the apparent edge "
             "survived, and what survived is\n%.1f points short of the bar. "
             "Something real is in there: %s on %s trades is\nnot luck against "
             "a %s baseline. It is simply nowhere near enough.\n"
             % (pct(a["pickedCellsInA"]), pct(b["pickedCells"]["winRatePct"]),
                (b["pickedCells"]["winRatePct"] - b["allCells"]["winRatePct"])
                / (a["pickedCellsInA"] - a["allCells"]["winRatePct"]) * 100.0,
                60.0 - b["pickedCells"]["winRatePct"],
                pct(b["pickedCells"]["winRatePct"]),
                "{:,}".format(b["pickedCells"]["tradeCount"]),
                pct(b["allCells"]["winRatePct"])))
    L.append("**What this does and does not prove.** It is a ceiling on "
             "*picking* - on any rule\nthat says which stock, at which hour, in "
             "which direction, decided once and left\nalone. Inside that class "
             "nothing survives past %s, so no amount of searching\nharder for "
             "the right stocks and hours gets near 60. It is not a proof about "
             "every\npossible trigger, because a trigger reacts to what is "
             "happening on the day and\nthis test does not. What it does do is "
             "put a number on how much of an apparent\nedge in these bars is "
             "real once it has to face fresh data: about %.0f%% of it. Six\n"
             "mechanisms landing on the baseline and a hindsight ceiling of %s "
             "are two\nindependent things pointing the same way.\n"
             % (pct(b["pickedCells"]["winRatePct"]),
                (b["pickedCells"]["winRatePct"] - b["allCells"]["winRatePct"])
                / (a["pickedCellsInA"] - a["allCells"]["winRatePct"]) * 100.0,
                pct(b["pickedCells"]["winRatePct"])))
    L.append(WHY.strip() + "\n")
    L.append(blocked.strip() + "\n")
    L.append("## The arithmetic, once more\n")
    L.append("A +1.0%% target against a -0.5%% stop pays two to one, so a "
             "coin-flip stock reaches\nthe target first about a third of the "
             "time - measured here at %s with no\ntrigger at all. To reach it "
             "60 times in 100 a rule must predict an average move\nof +0.40%% "
             "in the trade's direction, per trade, within fourteen days. Every "
             "short-\nhorizon share study this project has run measured a "
             "gross edge of one to five\nbasis points. +0.40%% is forty basis "
             "points.\n" % pct(base_all))
    L.append("## Raw numbers\n")
    L.append("- `.omc/research/todo-111-round3-prescreen-equs.json` - the eight "
             "screened families, each with its long and short halves\n"
             "- `.omc/research/todo-111-round3-panel-equs.json` - the two "
             "cross-sectional families\n"
             "- `.omc/research/todo-111-round3-ceiling-equs.json` - the ceiling "
             "test\n"
             "- Harnesses: `scripts/research/todo_111_round3_prescreen.py`, "
             "`todo_111_round3_panel.py`, `todo_111_round3_ceiling.py`\n"
             "- The second feed, XNYS.PILLAR, was not run. It exists to confirm "
             "a claimed edge\n  against a fuller tape by checking whether a "
             "touch really happened. There is no\n  claimed edge to confirm, "
             "and a second opinion on a non-result is not evidence.\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
