#!/usr/bin/env python3
"""Frozen pass/fail gate for the todo-111-proven-trading-edge outcome-loop mission.

Modes:
  data | access | cost | permission   feasibility checks, one evidence file each
  final                               the finish line, all evidence files in order

Every threshold below was set by the owner during the /loopgoal interview on
2026-09-01. Nothing in this file may be lowered, reworded, or argued down.
"""

import hashlib
import json
import sys

# --- The finish line, set by the owner ------------------------------------

# Share trades must average at least 1% profit per trade after all costs.
SHARES_MIN_AVG_RETURN_PCT = 1.0

# ...across at least 200 trades, so a lucky streak cannot carry the result.
SHARES_MIN_TRADES = 200

# Option trades must average at least 20% profit per trade after all costs.
OPTIONS_MIN_AVG_RETURN_PCT = 20.0

# ...across at least 40 trades.
OPTIONS_MIN_TRADES = 40

# How profit per trade is measured, by trade structure:
#   debit  (long shares, long options, debit spreads)
#       return = (exit value - entry cost) / entry cost
#   credit (credit spreads)
#       return = (premium collected - premium paid to close) / premium collected
#       collect $100, buy to close at $80  -> +20%
#       collect $100, buy to close at $120 -> -20%
RETURN_DEFINITIONS = {"debit", "credit", "mixed"}

# The whole job may spend at most $50, in at most one purchase, and only after
# the owner approves it and free sources have been exhausted.
MAX_SPEND_USD = 50.00
MAX_PURCHASES = 1

# At least five genuinely different profit mechanisms must be considered.
MIN_CANDIDATE_FAMILIES = 5

# The averages must be after commissions, the bid/ask spread, and slippage.
REQUIRED_COST_COMPONENTS = ["commission", "spread", "slippage"]

INSTRUMENTS = {"shares": (SHARES_MIN_AVG_RETURN_PCT, SHARES_MIN_TRADES),
               "options": (OPTIONS_MIN_AVG_RETURN_PCT, OPTIONS_MIN_TRADES)}


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


def need_text(doc, key, path):
    value = need(doc, key, path)
    if not isinstance(value, str) or not value.strip():
        raise Fail("%s: %r must be a non-empty string" % (path, key))
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
    return ["%d data source(s) inventoried with verified fields, dates and sample output"
            % len(sources)]


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
        raise Fail("%s: planned spend $%.2f exceeds the $%.2f cap" % (path, planned, MAX_SPEND_USD))
    purchases = need_number(doc, "plannedPurchaseCount", path)
    if purchases > MAX_PURCHASES:
        raise Fail("%s: %d planned purchases exceeds the limit of %d"
                   % (path, int(purchases), MAX_PURCHASES))
    if planned > 0:
        need_true(doc, "freeSourcesExhausted", path)
        need_true(doc, "ownerApprovalRequestedBeforePaying", path)
    return ["planned spend $%.2f of the $%.2f cap, %d purchase(s)"
            % (planned, MAX_SPEND_USD, int(purchases))]


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
    "untouched-result", "realistic-cost-audit", "point-in-time-audit",
    "concentration-audit", "instrument-fill-audit", "independent-reproduction",
    "owner-only-implementation", "no-real-order-audit", "purchase-audit",
    "rejection-ledger",
]


def bar_for(instrument, path):
    if instrument not in INSTRUMENTS:
        raise Fail("%s: instrument must be one of %s, got %r"
                   % (path, sorted(INSTRUMENTS), instrument))
    return INSTRUMENTS[instrument]


def clears_bar(doc, path, instrument, label):
    min_return, min_trades = bar_for(instrument, path)
    trades = need_number(doc, "tradeCount", path)
    average = need_number(doc, "avgReturnPctAfterCosts", path)
    if trades < min_trades:
        raise Fail("%s: %s has %d trades, the bar is %d" % (path, label, int(trades), min_trades))
    if average < min_return:
        raise Fail("%s: %s averages %.4f%% per trade, the bar is %.4f%%"
                   % (path, label, average, min_return))
    return "%s: %.4f%% average per trade over %d trades (bar %.4f%% / %d)" % (
        label, average, int(trades), min_return, min_trades)


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
    definition = need_text(bundle, "returnDefinition", bundle_path)
    if definition not in RETURN_DEFINITIONS:
        raise Fail("%s: returnDefinition must be one of %s, got %r"
                   % (bundle_path, sorted(RETURN_DEFINITIONS), definition))
    facts.append("instrument %s, returns measured as %s" % (instrument, definition))
    facts.append(clears_bar(bundle, bundle_path, instrument, "headline result"))

    facts.append(clears_bar(doc["development-result"], where["development-result"],
                            instrument, "development period"))
    untouched, untouched_path = doc["untouched-result"], where["untouched-result"]
    need_true(untouched, "frozenBeforeOutcomesRead", untouched_path)
    need_true(untouched, "periodNeverUsedInDevelopment", untouched_path)
    facts.append(clears_bar(untouched, untouched_path, instrument, "untouched period"))

    gates, gates_path = doc["frozen-gates"], where["frozen-gates"]
    need_true(gates, "frozenBeforeOutcomesRead", gates_path)
    min_return, min_trades = bar_for(instrument, gates_path)
    if need_number(gates, "frozenMinAvgReturnPct", gates_path) != min_return:
        raise Fail("%s: the frozen return bar was changed" % gates_path)
    if need_number(gates, "frozenMinTradeCount", gates_path) != min_trades:
        raise Fail("%s: the frozen trade-count bar was changed" % gates_path)
    facts.append("frozen bar matches this checker and was set before outcomes were read")

    slate, slate_path = doc["candidate-slate"], where["candidate-slate"]
    families = need_list(slate, "families", slate_path, MIN_CANDIDATE_FAMILIES)
    names = [f.get("name") if isinstance(f, dict) else f for f in families]
    if len(set(names)) < MIN_CANDIDATE_FAMILIES:
        raise Fail("%s: needs %d distinct families, found %d"
                   % (slate_path, MIN_CANDIDATE_FAMILIES, len(set(names))))
    facts.append("%d distinct candidate families considered" % len(set(names)))

    costs, costs_path = doc["realistic-cost-audit"], where["realistic-cost-audit"]
    applied = need_list(costs, "costComponentsApplied", costs_path)
    missing = [c for c in REQUIRED_COST_COMPONENTS if c not in applied]
    if missing:
        raise Fail("%s: these costs were not applied: %s" % (costs_path, ", ".join(missing)))
    need_true(costs, "returnsAreNetOfTheseCosts", costs_path)
    facts.append("returns are net of %s" % ", ".join(REQUIRED_COST_COMPONENTS))

    pit, pit_path = doc["point-in-time-audit"], where["point-in-time-audit"]
    need_false(pit, "usesFutureInformation", pit_path)
    need_false(pit, "usesCurrentSurvivorSelection", pit_path)
    facts.append("no future information, no current-survivor selection")

    conc, conc_path = doc["concentration-audit"], where["concentration-audit"]
    need_false(conc, "explainedBySingleTickerDateOrTrade", conc_path)
    facts.append(clears_bar({"tradeCount": need_number(conc, "tradeCountExcludingTopTicker", conc_path),
                             "avgReturnPctAfterCosts": need_number(conc, "avgReturnPctExcludingTopTicker", conc_path)},
                            conc_path, instrument, "with the best ticker removed"))

    fills, fills_path = doc["instrument-fill-audit"], where["instrument-fill-audit"]
    basis = need_text(fills, "priceBasis", fills_path)
    if instrument == "options":
        for key in ("contract", "strike", "expiration", "tradeDate", "entryTime", "exitTime", "source"):
            need(fills, key, fills_path)
        harsh = need(fills, "harshFillRetest", fills_path)
        if not isinstance(harsh, dict):
            raise Fail("%s: harshFillRetest must be an object" % fills_path)
        facts.append(clears_bar(harsh, fills_path, instrument, "harsh conservative fills"))
    facts.append("fill price basis disclosed as %s" % basis)

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
    facts.append("no real-money order was placed")

    buys, buys_path = doc["purchase-audit"], where["purchase-audit"]
    spent = need_number(buys, "totalSpendUsd", buys_path)
    count = need_number(buys, "purchaseCount", buys_path)
    if spent > MAX_SPEND_USD:
        raise Fail("%s: spent $%.2f, the cap is $%.2f" % (buys_path, spent, MAX_SPEND_USD))
    if count > MAX_PURCHASES:
        raise Fail("%s: %d purchases, the limit is %d" % (buys_path, int(count), MAX_PURCHASES))
    if spent > 0:
        need_true(buys, "ownerApprovedBeforePaying", buys_path)
        need_true(buys, "freeSourcesExhaustedFirst", buys_path)
    facts.append("spent $%.2f of the $%.2f cap in %d purchase(s)" % (spent, MAX_SPEND_USD, int(count)))

    ledger, ledger_path = doc["rejection-ledger"], where["rejection-ledger"]
    rejected = need(ledger, "rejectedFamilies", ledger_path)
    if not isinstance(rejected, list):
        raise Fail("%s: 'rejectedFamilies' must be a list (empty is fine)" % ledger_path)
    need_true(ledger, "handoffNotesWritten", ledger_path)
    facts.append("%d rejected family/families recorded for the next session" % len(rejected))

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
