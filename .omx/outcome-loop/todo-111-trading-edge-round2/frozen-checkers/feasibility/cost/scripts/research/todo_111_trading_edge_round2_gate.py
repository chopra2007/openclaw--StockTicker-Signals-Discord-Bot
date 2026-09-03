#!/usr/bin/env python3
"""Frozen pass/fail gate for the todo-111-trading-edge-round2 outcome-loop mission.

Modes:
  data | access | cost | permission   feasibility checks, one evidence file each
  final                               the finish line, all evidence files in order

Every threshold below was set by the owner during the /loopgoal interview on
2026-09-02 (Pacific). Nothing in this file may be lowered, reworded, or argued
down. Round 2 differs from round 1 in four ways: a hard 14-trading-day holding
cap, a target-and-stop rule exited on first touch, a win-rate bar instead of a
hold-to-a-date average, and returns measured gross (the owner subtracts costs
himself at the end).
"""

import hashlib
import json
import sys

# --- The finish line, set by the owner ------------------------------------

# A share trade closes when the stock has moved 1.0% in the trade's direction...
SHARE_TARGET_PCT = 1.0

# ...or 0.5% against it, whichever happens FIRST.
SHARE_STOP_PCT = 0.5

# The target must be reached before the stop in at least 60 trades out of 100.
SHARES_MIN_WIN_RATE_PCT = 60.0

# Which, with a +1.0% win against a -0.5% loss, averages at least +0.40% a trade.
SHARES_MIN_AVG_RETURN_PCT = 0.40

# ...across at least 200 trades, so a lucky streak cannot carry the result.
SHARES_MIN_TRADES = 200

# An option trade closes at 20% profit...
OPTION_TARGET_PCT = 20.0

# ...or 20% loss, whichever happens FIRST.
OPTION_STOP_PCT = 20.0

# The target must be reached before the stop in at least 60 trades out of 100.
OPTIONS_MIN_WIN_RATE_PCT = 60.0

# Which, at even money, averages at least +4.00% a trade.
OPTIONS_MIN_AVG_RETURN_PCT = 4.00

# ...across at least 100 trades. Raised from 40 on 2026-09-02: the local weekly
# chains hold roughly 300,000 observations, so 100 costs nothing and a 60-in-100
# win rate on 40 trades could too easily be luck.
OPTIONS_MIN_TRADES = 100

# No trade may stay open longer than 14 trading days, whatever its profit.
# This is the hole the three-month rule walked through in round 1.
MAX_HOLD_TRADING_DAYS = 14

# Returns are measured GROSS, with no commission, spread or slippage removed.
# The owner subtracts costs himself once a rule passes. A result that quietly
# claims to be net of costs is a different measurement and is refused.
REQUIRED_COST_BASIS = "gross_no_costs"

# The exit must be decided on prices fine enough to see a touch. Daily bars
# cannot tell whether +1.0% or -0.5% came first inside the same day.
ALLOWED_PRICE_RESOLUTIONS = {"one_minute", "one_second", "tick"}

# This session spends nothing. Any purchase is an owner decision taken later.
MAX_SPEND_USD = 0.00
MAX_PURCHASES = 0

# At least five genuinely different profit mechanisms must be considered.
MIN_CANDIDATE_FAMILIES = 5

INSTRUMENTS = {
    "shares": (SHARES_MIN_WIN_RATE_PCT, SHARES_MIN_AVG_RETURN_PCT, SHARES_MIN_TRADES,
               SHARE_TARGET_PCT, SHARE_STOP_PCT),
    "options": (OPTIONS_MIN_WIN_RATE_PCT, OPTIONS_MIN_AVG_RETURN_PCT, OPTIONS_MIN_TRADES,
                OPTION_TARGET_PCT, OPTION_STOP_PCT),
}


class Fail(Exception):
    pass


def sha256_of(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def load(path):
    try:
        with open(path, "rb") as handle:
            value = json.loads(handle.read().decode("utf-8"))
    except FileNotFoundError:
        raise Fail("evidence file does not exist: %s" % path)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Fail("evidence is not valid JSON: %s (%s)" % (path, exc))
    if not isinstance(value, dict):
        raise Fail("evidence must be a JSON object: %s" % path)
    return value


def need(doc, key, path):
    if key not in doc:
        raise Fail("%s is missing the field %r" % (path, key))
    return doc[key]


def need_true(doc, key, path):
    value = need(doc, key, path)
    if value is not True:
        raise Fail("%s: %r must be true, got %r" % (path, key, value))
    return value


def need_false(doc, key, path):
    value = need(doc, key, path)
    if value is not False:
        raise Fail("%s: %r must be false, got %r" % (path, key, value))
    return value


def need_number(doc, key, path):
    value = need(doc, key, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Fail("%s: %r must be a number, got %r" % (path, key, value))
    return float(value)


def need_list(doc, key, path, minimum=1):
    value = need(doc, key, path)
    if not isinstance(value, list) or len(value) < minimum:
        raise Fail("%s: %r must be a list of at least %d items" % (path, key, minimum))
    return value


def need_text(doc, key, path, min_chars=1):
    value = need(doc, key, path)
    if not isinstance(value, str) or len(value.strip()) < min_chars:
        raise Fail("%s: %r must be a string of at least %d characters"
                   % (path, key, min_chars))
    return value.strip()


# --- Feasibility ----------------------------------------------------------

def check_data(doc, path):
    sources = need_list(doc, "sources", path)
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise Fail("%s: sources[%d] must be an object" % (path, index))
        for key in ("name", "fields", "startDate", "endDate", "sampleOutput"):
            if key not in source:
                raise Fail("%s: sources[%d] is missing %r" % (path, index, key))
    need_true(doc, "fieldsVerifiedAgainstSample", path)
    # A first-touch rule cannot be judged on daily bars, so at least one source
    # must carry prices at one-minute resolution or finer.
    fine = [s for s in sources if s.get("priceResolution") in ALLOWED_PRICE_RESOLUTIONS]
    if not fine:
        raise Fail("%s: no source carries prices at one-minute resolution or finer, "
                   "so a first-touch exit cannot be measured" % path)
    return ["%d data source(s) inventoried with verified fields, dates and sample output"
            % len(sources),
            "%d source(s) fine enough to see a touch" % len(fine)]


def check_access(doc, path):
    reachable = need_list(doc, "reachable", path)
    blocked = need(doc, "blocked", path)
    if not isinstance(blocked, list):
        raise Fail("%s: 'blocked' must be a list (empty is fine)" % path)
    need_true(doc, "existingAccountsReadOnly", path)
    return ["%d source(s) reachable now, %d blocked" % (len(reachable), len(blocked)),
            "existing accounts confirmed read-only"]


def check_cost(doc, path):
    planned = need_number(doc, "plannedSpendUsd", path)
    if planned > MAX_SPEND_USD:
        raise Fail("%s: planned spend $%.2f exceeds the $%.2f cap for this session"
                   % (path, planned, MAX_SPEND_USD))
    purchases = need_number(doc, "plannedPurchaseCount", path)
    if purchases > MAX_PURCHASES:
        raise Fail("%s: %d planned purchases exceeds the limit of %d"
                   % (path, int(purchases), MAX_PURCHASES))
    need_true(doc, "ownerDecidesAnyPurchaseLater", path)
    return ["planned spend $%.2f of the $%.2f cap, %d purchase(s)"
            % (planned, MAX_SPEND_USD, int(purchases)),
            "any purchase is deferred to the owner"]


def check_permission(doc, path):
    need_false(doc, "realMoneyOrderPossible", path)
    need_false(doc, "productionAlertEnabled", path)
    need_true(doc, "outputOwnerOnly", path)
    acknowledged = need_list(doc, "forbiddenActionsAcknowledged", path)
    return ["no real-money order path, no production alert, output owner-only",
            "%d forbidden action(s) acknowledged" % len(acknowledged)]


FEASIBILITY = {"data": check_data, "access": check_access,
               "cost": check_cost, "permission": check_permission}


# --- The finish line ------------------------------------------------------

FINAL_ORDER = [
    "final-proof-bundle", "candidate-slate", "frozen-gates", "development-result",
    "untouched-result", "exit-rule-audit", "entry-trigger-audit",
    "point-in-time-audit", "independent-reproduction", "owner-only-implementation",
    "no-real-order-audit", "purchase-audit", "rejection-ledger",
]


def bar_for(instrument, path):
    if instrument not in INSTRUMENTS:
        raise Fail("%s: instrument must be one of %s, got %r"
                   % (path, sorted(INSTRUMENTS), instrument))
    return INSTRUMENTS[instrument]


def clears_bar(doc, path, instrument, label):
    """Every result file must clear the win rate, the average, the trade count
    and the 14-trading-day holding cap. All four, or it is not a pass."""
    min_win, min_avg, min_trades, _target, _stop = bar_for(instrument, path)
    trades = need_number(doc, "tradeCount", path)
    win_rate = need_number(doc, "winRatePct", path)
    average = need_number(doc, "avgReturnPct", path)
    longest = need_number(doc, "maxHoldingTradingDays", path)
    if trades < min_trades:
        raise Fail("%s: %s has %d trades, the bar is %d"
                   % (path, label, int(trades), min_trades))
    if win_rate < min_win:
        raise Fail("%s: %s wins %.4f%% of trades, the bar is %.4f%%"
                   % (path, label, win_rate, min_win))
    if average < min_avg:
        raise Fail("%s: %s averages %.4f%% per trade, the bar is %.4f%%"
                   % (path, label, average, min_avg))
    if longest > MAX_HOLD_TRADING_DAYS:
        raise Fail("%s: %s holds a trade for %.4f trading days, the cap is %d"
                   % (path, label, longest, MAX_HOLD_TRADING_DAYS))
    return ("%s: wins %.4f%% of %d trades, averages %.4f%% each, longest hold "
            "%.4f trading days (bars %.4f%% / %.4f%% / %d / %d days)"
            % (label, win_rate, int(trades), average, longest,
               min_win, min_avg, min_trades, MAX_HOLD_TRADING_DAYS))


def check_final(paths):
    if len(paths) != len(FINAL_ORDER):
        raise Fail("final needs %d evidence files in the frozen order, got %d"
                   % (len(FINAL_ORDER), len(paths)))
    doc = {}
    where = {}
    for name, path in zip(FINAL_ORDER, paths):
        doc[name] = load(path)
        where[name] = path
    facts = []

    bundle, bundle_path = doc["final-proof-bundle"], where["final-proof-bundle"]
    instrument = need_text(bundle, "instrument", bundle_path)
    basis = need_text(bundle, "costBasis", bundle_path)
    if basis != REQUIRED_COST_BASIS:
        raise Fail("%s: costBasis must be %r (returns measured gross), got %r"
                   % (bundle_path, REQUIRED_COST_BASIS, basis))
    facts.append("instrument %s, returns measured gross with no costs removed" % instrument)
    facts.append(clears_bar(bundle, bundle_path, instrument, "headline result"))

    facts.append(clears_bar(doc["development-result"], where["development-result"],
                            instrument, "development period"))

    untouched, untouched_path = doc["untouched-result"], where["untouched-result"]
    need_true(untouched, "frozenBeforeOutcomesRead", untouched_path)
    need_true(untouched, "periodNeverUsedInDevelopment", untouched_path)
    facts.append(clears_bar(untouched, untouched_path, instrument, "untouched period"))

    gates, gates_path = doc["frozen-gates"], where["frozen-gates"]
    need_true(gates, "frozenBeforeOutcomesRead", gates_path)
    min_win, min_avg, min_trades, target, stop = bar_for(instrument, gates_path)
    frozen = [
        ("frozenMinWinRatePct", min_win),
        ("frozenMinAvgReturnPct", min_avg),
        ("frozenMinTradeCount", min_trades),
        ("frozenTargetPct", target),
        ("frozenStopPct", stop),
        ("frozenMaxHoldingTradingDays", MAX_HOLD_TRADING_DAYS),
    ]
    for key, expected in frozen:
        if need_number(gates, key, gates_path) != float(expected):
            raise Fail("%s: the frozen bar was changed - %s is %r, this checker says %r"
                       % (gates_path, key, gates[key], expected))
    facts.append("frozen bar matches this checker and was set before outcomes were read")

    slate, slate_path = doc["candidate-slate"], where["candidate-slate"]
    families = need_list(slate, "families", slate_path, MIN_CANDIDATE_FAMILIES)
    names = [f.get("name") if isinstance(f, dict) else f for f in families]
    if len(set(names)) < MIN_CANDIDATE_FAMILIES:
        raise Fail("%s: needs %d distinct families, found %d"
                   % (slate_path, MIN_CANDIDATE_FAMILIES, len(set(names))))
    facts.append("%d distinct candidate families considered" % len(set(names)))

    exits, exits_path = doc["exit-rule-audit"], where["exit-rule-audit"]
    need_true(exits, "exitOnFirstTouch", exits_path)
    if need_number(exits, "targetPct", exits_path) != float(target):
        raise Fail("%s: target is %r, the frozen target is %r"
                   % (exits_path, exits["targetPct"], target))
    if need_number(exits, "stopPct", exits_path) != float(stop):
        raise Fail("%s: stop is %r, the frozen stop is %r"
                   % (exits_path, exits["stopPct"], stop))
    if need_number(exits, "holdingCapTradingDays", exits_path) != float(MAX_HOLD_TRADING_DAYS):
        raise Fail("%s: holding cap is %r, the frozen cap is %d"
                   % (exits_path, exits["holdingCapTradingDays"], MAX_HOLD_TRADING_DAYS))
    resolution = need_text(exits, "priceResolution", exits_path)
    if resolution not in ALLOWED_PRICE_RESOLUTIONS:
        raise Fail("%s: priceResolution must be one of %s to see a touch, got %r"
                   % (exits_path, sorted(ALLOWED_PRICE_RESOLUTIONS), resolution))
    facts.append("exits on first touch of +%.4f%% or -%.4f%%, decided on %s prices, "
                 "capped at %d trading days" % (target, stop, resolution,
                                                MAX_HOLD_TRADING_DAYS))

    entry, entry_path = doc["entry-trigger-audit"], where["entry-trigger-audit"]
    need_false(entry, "entryIsFixedSchedule", entry_path)
    need_text(entry, "entryTriggerDescription", entry_path, 40)
    observed = need_list(entry, "observedSignals", entry_path)
    facts.append("entry is triggered by %d observed signal(s), not a fixed schedule"
                 % len(observed))

    pit, pit_path = doc["point-in-time-audit"], where["point-in-time-audit"]
    need_false(pit, "usesFutureInformation", pit_path)
    need_false(pit, "usesCurrentSurvivorSelection", pit_path)
    facts.append("no future information, no current-survivor selection")

    repro, repro_path = doc["independent-reproduction"], where["independent-reproduction"]
    need_true(repro, "reproducedIndependently", repro_path)
    need_true(repro, "reviewerDifferentFromBuilder", repro_path)
    need_true(repro, "reviewerApproved", repro_path)
    facts.append(clears_bar(repro, repro_path, instrument, "independent reproduction"))

    impl, impl_path = doc["owner-only-implementation"], where["owner-only-implementation"]
    need_true(impl, "ownerOnly", impl_path)
    need_false(impl, "productionAlertEnabled", impl_path)
    facts.append("feature built owner-only, no production alert enabled")

    orders, orders_path = doc["no-real-order-audit"], where["no-real-order-audit"]
    placed = need_number(orders, "realMoneyOrdersPlaced", orders_path)
    if placed != 0:
        raise Fail("%s: %d real-money order(s) were placed" % (orders_path, int(placed)))
    facts.append("no order of any kind was placed")

    buys, buys_path = doc["purchase-audit"], where["purchase-audit"]
    spent = need_number(buys, "totalSpendUsd", buys_path)
    count = need_number(buys, "purchaseCount", buys_path)
    if spent > MAX_SPEND_USD:
        raise Fail("%s: spent $%.2f, the cap for this session is $%.2f"
                   % (buys_path, spent, MAX_SPEND_USD))
    if count > MAX_PURCHASES:
        raise Fail("%s: %d purchases, the limit is %d" % (buys_path, int(count), MAX_PURCHASES))
    facts.append("spent $%.2f of the $%.2f cap in %d purchase(s)"
                 % (spent, MAX_SPEND_USD, int(count)))

    ledger, ledger_path = doc["rejection-ledger"], where["rejection-ledger"]
    rejected = need(ledger, "rejectedFamilies", ledger_path)
    if not isinstance(rejected, list):
        raise Fail("%s: 'rejectedFamilies' must be a list (empty is fine)" % ledger_path)
    need_true(ledger, "handoffNotesWritten", ledger_path)
    ownerq = need(ledger, "ownerDecisionsPending", ledger_path)
    if not isinstance(ownerq, list):
        raise Fail("%s: 'ownerDecisionsPending' must be a list (empty is fine)" % ledger_path)
    facts.append("%d rejected family/families recorded, %d owner decision(s) queued"
                 % (len(rejected), len(ownerq)))

    return facts


# --- Entry point ----------------------------------------------------------

def main(argv):
    if len(argv) < 3:
        print("usage: %s <data|access|cost|permission|final> <evidence.json> ..." % argv[0],
              file=sys.stderr)
        return 2
    mode, paths = argv[1], argv[2:]
    try:
        if mode in FEASIBILITY:
            if len(paths) != 1:
                raise Fail("%s takes exactly one evidence file" % mode)
            facts = FEASIBILITY[mode](load(paths[0]), paths[0])
            result = {"status": "PASS", "mode": mode,
                      "evidenceSha256": sha256_of(paths[0]), "facts": facts}
        elif mode == "final":
            facts = check_final(paths)
            result = {"status": "PASS", "mode": "final",
                      "evidenceSha256": sha256_of(paths[0]), "facts": facts}
        else:
            raise Fail("unknown mode %r" % mode)
    except Fail as exc:
        print(json.dumps({"status": "FAIL", "mode": mode, "reason": str(exc)}), file=sys.stderr)
        return 1
    if not result["facts"]:
        print(json.dumps({"status": "FAIL", "mode": mode, "reason": "no facts produced"}),
              file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
