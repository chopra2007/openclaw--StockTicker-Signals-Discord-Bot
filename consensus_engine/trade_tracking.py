"""Pure Batch 2 rules for exact option and share trade tracking."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from math import isfinite
import time
import uuid

from consensus_engine import db


OPTION_TYPES = {"call", "put"}
SPECIAL_OUTCOMES = {
    "adjusted_contract", "expired", "early_assignment_risk", "halted",
    "gap", "cannot_close",
}
_MICRODOLLARS = Decimal("1000000")


def dollars_to_micros(value) -> int | None:
    """Convert a dollar value to exact integer microdollars for storage."""
    if value is None:
        return None
    number = _number(value, "dollar value")
    return int((Decimal(str(number)) * _MICRODOLLARS).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP,
    ))


def micros_to_dollars(value) -> float | None:
    if value is None:
        return None
    return float(Decimal(int(value)) / _MICRODOLLARS)


def _new_id(kind: str) -> str:
    return f"{kind}_{uuid.uuid4().hex}"


def _json(values: dict) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(kind: str, values: dict) -> str:
    digest = hashlib.sha256(_json(values).encode("utf-8")).hexdigest()
    return f"{kind}_{digest}"


def build_trade_id(
    *, candidate_id: str, instrument_type: str, direction: str, rule_version: str,
) -> str:
    return _stable_id("trade", {
        "candidate_id": _required_text(candidate_id, "candidate id"),
        "instrument_type": _required_text(instrument_type, "instrument type").lower(),
        "direction": _required_text(direction, "trade direction").lower(),
        "rule_version": _required_text(rule_version, "rule version"),
    })


def build_contract_selection_id(*, trade_id: str, contract: dict) -> str:
    validated = validate_option_contract(contract)
    identity = {
        "contract_symbol": _required_text(
            validated.get("contract_symbol"), "contract symbol",
        ).upper(),
        "underlying": _required_text(validated.get("underlying"), "underlying").upper(),
        "option_type": _required_text(
            validated.get("option_type"), "option type",
        ).lower(),
        "action": _required_text(validated.get("action"), "option action").lower(),
        "strategy": _required_text(
            validated.get("strategy", "single_leg"), "option strategy",
        ).lower(),
        "strike_micros": dollars_to_micros(validated.get("strike")),
        "expiration": _required_text(validated.get("expiration"), "expiration"),
        "multiplier": int(_number(validated.get("multiplier"), "multiplier", positive=True)),
        "quote_source": _required_text(validated.get("quote_source"), "quote source"),
        "selection_rule_version": _required_text(
            validated.get("selection_rule_version"), "selection rule version",
        ),
        "scorer_version": _required_text(
            validated.get("scorer_version"), "scorer version",
        ),
    }
    identity["trade_id"] = _required_text(trade_id, "trade id")
    return _stable_id("contract_selection", identity)


def build_trade_result_id(
    *, trade_id: str, result_rule_version: str, is_primary: bool = True,
) -> str:
    return _stable_id("trade_result", {
        "trade_id": _required_text(trade_id, "trade id"),
        "result_rule_version": _required_text(
            result_rule_version, "result rule version",
        ),
        "is_primary": bool(is_primary),
    })


def _required_text(value, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _number(value, label: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'finite'}")
    return number


def validate_option_contract(contract: dict) -> dict:
    """Validate and return one complete, immutable option-contract identity."""
    required = {
        "contract_symbol": "contract symbol",
        "underlying": "underlying",
        "action": "option action",
        "expiration": "expiration",
        "quote_source": "quote source",
        "selection_rule_version": "selection rule version",
        "scorer_version": "scorer version",
    }
    for field, label in required.items():
        _required_text(contract.get(field), label)
    option_type = _required_text(contract.get("option_type"), "option type").lower()
    if option_type not in OPTION_TYPES:
        raise ValueError("option type must be call or put")
    _number(contract.get("strike"), "strike", positive=True)
    _number(contract.get("multiplier"), "multiplier", positive=True)
    return deepcopy(contract)


def assess_option_strategy(contract: dict) -> dict:
    validate_option_contract(contract)
    eligible = (
        str(contract.get("action", "")).lower() == "buy_to_open"
        and str(contract.get("option_type", "")).lower() in OPTION_TYPES
        and str(contract.get("strategy", "")).lower() == "single_leg"
        and contract.get("leg_count") == 1
    )
    if eligible:
        return {"eligible": True, "classification": "performance_eligible"}
    return {
        "eligible": False,
        "classification": "research_only",
        "reason": "unsupported_strategy",
    }


def classify_option_quote(
    quote: dict,
    *,
    purpose: str,
    max_age_seconds: float,
    zero_bid_rule: str = "cannot_close",
    result_rule_version: str = "",
) -> dict:
    """Classify a timestamped bid/ask observation without dropping bad quotes."""
    if purpose not in {"selection", "entry", "exit"}:
        raise ValueError("quote purpose must be selection, entry, or exit")
    result = deepcopy(quote)
    provider_at = _number(quote.get("provider_timestamp"), "provider timestamp", positive=True)
    received_at = _number(quote.get("received_timestamp"), "received timestamp", positive=True)
    computed_age = received_at - provider_at
    reported_age = _number(quote.get("quote_age_seconds", computed_age), "quote age")
    age = max(computed_age, reported_age)
    result["quote_age_seconds"] = age
    result["purpose"] = purpose
    result["usable"] = False
    result["unusable_reason"] = ""
    bid = quote.get("bid")
    ask = quote.get("ask")
    if computed_age < 0:
        result["unusable_reason"] = "provider_after_receipt"
    elif reported_age < 0:
        result["unusable_reason"] = "negative_quote_age"
    elif bid is None:
        result["unusable_reason"] = "missing_bid"
    elif ask is None:
        result["unusable_reason"] = "missing_ask"
    else:
        bid = _number(bid, "bid")
        ask = _number(ask, "ask")
        if bid > ask:
            result["unusable_reason"] = "crossed"
        elif age > float(max_age_seconds):
            result["unusable_reason"] = "stale"
        elif purpose == "exit" and bid == 0:
            result["unusable_reason"] = "zero_bid"
            result["result_treatment"] = zero_bid_rule
            result["result_rule_version"] = result_rule_version
            if zero_bid_rule == "zero_value":
                result["executable_price"] = 0.0
        elif bid < 0 or ask <= 0:
            result["unusable_reason"] = "invalid_price"
        else:
            result["usable"] = True
            result["executable_price"] = ask if purpose == "entry" else bid
    return result


def assess_option_quote(
    quote: dict,
    *,
    purpose: str,
    confirmed_delivery_at: float | None,
    max_age_seconds: float,
    max_delivery_delay_seconds: float,
    min_midpoint: float,
    max_spread_pct: float,
    min_open_interest: int,
    result_rule_version: str,
) -> dict:
    """Apply the frozen Batch 2 execution and liquidity rules to one quote."""
    result = classify_option_quote(
        quote,
        purpose=purpose,
        max_age_seconds=max_age_seconds,
        result_rule_version=result_rule_version,
    )
    result["result_rule_version"] = result_rule_version
    if result["unusable_reason"]:
        return result
    if str(quote.get("market_session") or "").lower() != "regular":
        result.update(usable=False, unusable_reason="outside_regular_session")
        return result
    if bool(quote.get("is_delayed", False)):
        result.update(usable=False, unusable_reason="delayed")
        return result
    provider_at = float(result["provider_timestamp"])
    received_at = float(result["received_timestamp"])
    if confirmed_delivery_at is not None:
        delivered = _number(confirmed_delivery_at, "confirmed delivery time", positive=True)
        result["delivery_to_quote_seconds"] = received_at - delivered
        if provider_at < delivered:
            result.update(usable=False, unusable_reason="pre_delivery")
            return result
        if received_at - delivered > float(max_delivery_delay_seconds):
            result.update(usable=False, unusable_reason="entry_delay_exceeded")
            return result
    bid = float(result["bid"])
    ask = float(result["ask"])
    midpoint = (bid + ask) / 2.0
    spread = ask - bid
    spread_pct = spread / midpoint * 100.0 if midpoint > 0 else float("inf")
    result.update(midpoint=midpoint, spread=spread, spread_pct=spread_pct)
    if bid <= 0:
        result.update(usable=False, unusable_reason="zero_bid")
    elif midpoint < float(min_midpoint):
        result.update(usable=False, unusable_reason="low_midpoint")
    elif spread_pct > float(max_spread_pct):
        result.update(usable=False, unusable_reason="wide_spread")
    elif int(quote.get("open_interest") or 0) < int(min_open_interest):
        result.update(usable=False, unusable_reason="low_open_interest")
    return result


def assess_share_quote(
    quote: dict,
    *,
    direction: str,
    purpose: str,
    confirmed_delivery_at: float | None,
    max_age_seconds: float,
    max_delivery_delay_seconds: float,
    slippage_bps: float,
    result_rule_version: str,
    min_price: float | None = None,
    max_spread_pct: float | None = None,
    min_average_daily_dollar_volume: float | None = None,
    require_normal_halt: bool = False,
) -> dict:
    """Classify one timestamped share quote and calculate its adverse fill."""
    direction = _required_text(direction, "share direction").lower()
    if direction not in {"long", "short"}:
        raise ValueError("share direction must be long or short")
    result = classify_option_quote(
        quote,
        purpose=purpose,
        max_age_seconds=max_age_seconds,
        result_rule_version=result_rule_version,
    )
    result["result_rule_version"] = result_rule_version
    if result["unusable_reason"]:
        return result
    if str(quote.get("market_session") or "").lower() != "regular":
        result.update(usable=False, unusable_reason="outside_regular_session")
        return result
    provider_at = float(result["provider_timestamp"])
    received_at = float(result["received_timestamp"])
    if confirmed_delivery_at is not None:
        delivered = _number(confirmed_delivery_at, "confirmed delivery time", positive=True)
        result["delivery_to_quote_seconds"] = received_at - delivered
        if provider_at < delivered:
            result.update(usable=False, unusable_reason="pre_delivery")
            return result
        if received_at - delivered > float(max_delivery_delay_seconds):
            result.update(usable=False, unusable_reason="entry_delay_exceeded")
            return result
    bid = float(result["bid"])
    ask = float(result["ask"])
    midpoint = (bid + ask) / 2.0
    spread = ask - bid
    spread_pct = spread / midpoint * 100.0 if midpoint > 0 else float("inf")
    result.update(midpoint=midpoint, spread=spread, spread_pct=spread_pct)
    if min_price is not None and midpoint < float(min_price):
        result.update(usable=False, unusable_reason="share_price_too_low")
        return result
    if max_spread_pct is not None and spread_pct > float(max_spread_pct):
        result.update(usable=False, unusable_reason="share_spread_too_wide")
        return result
    if min_average_daily_dollar_volume is not None:
        average_volume = quote.get("average_daily_dollar_volume")
        if average_volume is None:
            result.update(usable=False, unusable_reason="missing_average_dollar_volume")
            return result
        if float(average_volume) < float(min_average_daily_dollar_volume):
            result.update(usable=False, unusable_reason="low_average_dollar_volume")
            return result
    if require_normal_halt:
        halt_status = str(quote.get("halt_status") or "").strip().lower()
        if halt_status not in {"normal", "not_halted"}:
            result.update(usable=False, unusable_reason="halt_status_unusable")
            return result
    slip = float(slippage_bps) / 10_000.0
    if purpose == "entry":
        reference = ask if direction == "long" else bid
        executable = reference * (1.0 + slip if direction == "long" else 1.0 - slip)
    else:
        reference = bid if direction == "long" else ask
        executable = reference * (1.0 - slip if direction == "long" else 1.0 + slip)
    result.update(reference_price=reference, executable_price=executable)
    return result


def calculate_share_result(
    *, direction: str, entry_price: float, exit_price: float, quantity: int,
    spread_dollars: float, commission_dollars: float, slippage_dollars: float,
    planned_risk_dollars: float, fee_rule_version: str,
    result_rule_version: str,
) -> dict:
    """Return a reproducible long/short share result from stored values only."""
    direction = _required_text(direction, "share direction").lower()
    if direction not in {"long", "short"}:
        raise ValueError("share direction must be long or short")
    entry = _number(entry_price, "entry price", positive=True)
    exit_price = _number(exit_price, "exit price", positive=True)
    quantity = int(_number(quantity, "quantity", positive=True))
    sign = 1 if direction == "long" else -1
    gross = (exit_price - entry) * quantity * sign
    commission = _number(commission_dollars, "commission dollars")
    risk = _number(planned_risk_dollars, "planned risk dollars", positive=True)
    net = gross - commission
    return {
        "direction": direction,
        "entry_price": entry,
        "exit_price": exit_price,
        "quantity": quantity,
        "gross_dollars": gross,
        "net_dollars": net,
        "spread_dollars": _number(spread_dollars, "spread dollars"),
        "commission_dollars": commission,
        "slippage_dollars": _number(slippage_dollars, "slippage dollars"),
        "planned_risk_dollars": risk,
        "result_per_planned_risk": net / risk,
        "fee_rule_version": _required_text(fee_rule_version, "fee rule version"),
        "result_rule_version": _required_text(result_rule_version, "result rule version"),
    }


def reproduce_share_result(stored: dict) -> dict:
    """Rebuild share result math using only immutable stored values."""
    return calculate_share_result(
        direction=stored.get("direction"),
        entry_price=stored.get("entry_price"),
        exit_price=stored.get("exit_price"),
        quantity=stored.get("quantity"),
        spread_dollars=stored.get("spread_dollars"),
        commission_dollars=stored.get("commission_dollars"),
        slippage_dollars=stored.get("slippage_dollars"),
        planned_risk_dollars=stored.get("planned_risk_dollars"),
        fee_rule_version=stored.get("fee_rule_version"),
        result_rule_version=stored.get("result_rule_version"),
    )


def missing_quote_observation(
    *, trade_id: str, purpose: str, reason: str, observed_at: float,
    result_rule_version: str,
) -> dict:
    return {
        "trade_id": _required_text(trade_id, "trade id"),
        "purpose": _required_text(purpose, "quote purpose"),
        "status": "missing_data",
        "missing_data_reason": _required_text(reason, "missing data reason"),
        "observed_at": _number(observed_at, "observed time", positive=True),
        "result_rule_version": _required_text(result_rule_version, "result rule version"),
    }


def calculate_option_result(
    *, entry_quote: dict, exit_quote: dict, contract_multiplier: int,
    contract_count: int, fee_rule: dict, result_rule_version: str,
) -> dict:
    multiplier = _number(contract_multiplier, "contract multiplier", positive=True)
    count = int(_number(contract_count, "contract count", positive=True))
    entry_ask = _number(entry_quote.get("ask"), "entry ask", positive=True)
    entry_bid = _number(entry_quote.get("bid"), "entry bid")
    exit_bid = _number(exit_quote.get("bid"), "exit bid")
    exit_ask = _number(exit_quote.get("ask"), "exit ask", positive=True)
    per_side = _number(
        fee_rule.get("per_contract_per_transaction"),
        "per-contract transaction fee",
    )
    if per_side < 0:
        raise ValueError("per-contract transaction fee cannot be negative")
    extras = []
    for item in fee_rule.get("extra_fees", []) or []:
        name = _required_text(item.get("name"), "fee name")
        amount = _number(item.get("amount"), f"{name} fee")
        if amount < 0:
            raise ValueError("extra fee cannot be negative")
        extras.append({"name": name, "amount": amount})
    buy_fee = per_side * count
    sell_fee = per_side * count
    contract_fees = buy_fee + sell_fee
    extra_total = sum(item["amount"] for item in extras)
    gross = (exit_bid - entry_ask) * multiplier * count
    return {
        "entry_ask": entry_ask,
        "entry_bid": entry_bid,
        "exit_bid": exit_bid,
        "exit_ask": exit_ask,
        "contract_multiplier": multiplier,
        "contract_count": count,
        "entry_spread_dollars": entry_ask - entry_bid,
        "exit_spread_dollars": exit_ask - exit_bid,
        "buy_contract_fee": buy_fee,
        "sell_contract_fee": sell_fee,
        "contract_fees_total": contract_fees,
        "extra_fees": extras,
        "extra_fees_total": extra_total,
        "gross_dollars": gross,
        "net_dollars": gross - contract_fees - extra_total,
        "fee_rule_version": _required_text(fee_rule.get("version"), "fee rule version"),
        "result_rule_version": _required_text(result_rule_version, "result rule version"),
    }


def reproduce_option_result(stored: dict) -> dict:
    """Rebuild result math using only immutable values saved with the result."""
    multiplier = _number(stored.get("contract_multiplier"), "contract multiplier", positive=True)
    count = int(_number(stored.get("contract_count"), "contract count", positive=True))
    gross = (
        _number(stored.get("exit_bid"), "exit bid")
        - _number(stored.get("entry_ask"), "entry ask")
    ) * multiplier * count
    contract_fees = (
        _number(stored.get("buy_contract_fee"), "buy contract fee")
        + _number(stored.get("sell_contract_fee"), "sell contract fee")
    )
    extra_fees = _number(stored.get("extra_fees_total", 0), "extra fees")
    rebuilt = deepcopy(stored)
    rebuilt.update({
        "gross_dollars": gross,
        "contract_fees_total": contract_fees,
        "net_dollars": gross - contract_fees - extra_fees,
    })
    return rebuilt


def assess_share_eligibility(plan: dict) -> dict:
    direction = _required_text(plan.get("direction"), "share direction").lower()
    if direction not in {"long", "short"}:
        raise ValueError("share direction must be long or short")
    entry = _number(plan.get("entry_price"), "share entry price", positive=True)
    stop = _number(plan.get("stop_price"), "share stop price", positive=True)
    quantity = _number(plan.get("quantity"), "share quantity", positive=True)
    for field in ("entry_time", "exit_time", "exit_price", "target_price"):
        _number(plan.get(field), field.replace("_", " "), positive=True)
    for field in (
        "path_status", "halt_status", "fee_rule_version", "result_rule_version",
    ):
        _required_text(plan.get(field), field.replace("_", " "))
    spread = _number(plan.get("spread_dollars", 0), "spread dollars")
    commission = _number(plan.get("commission_dollars", 0), "commission dollars")
    planned_risk = (abs(entry - stop) + spread) * quantity + commission
    if direction == "short":
        short_fields = (
            "borrow_available", "borrow_checked_at", "borrow_cost_dollars",
            "dividends_dollars", "corporate_action_status",
        )
        if any(field not in plan or plan[field] is None for field in short_fields):
            return {
                "eligible": False,
                "classification": "research_only",
                "reason": "missing_short_borrow_facts",
                "planned_risk_dollars": planned_risk,
            }
        if plan.get("borrow_available") is not True:
            return {
                "eligible": False,
                "classification": "research_only",
                "reason": "borrow_unavailable",
                "planned_risk_dollars": planned_risk,
            }
    return {
        "eligible": True,
        "classification": "performance_eligible",
        "planned_risk_dollars": planned_risk,
    }


def build_special_outcome(
    *, trade_id: str, status: str, reason: str, observed_at: float,
    result_rule_version: str,
) -> dict:
    if status not in SPECIAL_OUTCOMES:
        raise ValueError("unsupported special outcome status")
    return {
        "trade_id": _required_text(trade_id, "trade id"),
        "status": status,
        "reason": _required_text(reason, "outcome reason"),
        "observed_at": _number(observed_at, "observed time", positive=True),
        "result_rule_version": _required_text(result_rule_version, "result rule version"),
    }


async def _existing_row(table: str, id_column: str, stable_id: str):
    conn = await db.get_db()
    cursor = await conn.execute(
        f"SELECT * FROM {table} WHERE {id_column} = ? LIMIT 1", (stable_id,),
    )
    return await cursor.fetchone()


async def _insert_stable(
    *, table: str, id_column: str, stable_id: str, sql: str, row: tuple,
) -> str:
    """Make exact retry IDs safe without accepting changed retry payloads."""
    existing = await _existing_row(table, id_column, stable_id)
    if existing is not None:
        existing_values = tuple(existing)
        if existing_values != row:
            raise ValueError(f"{id_column} already exists with different data")
        return stable_id
    conn = await db.get_db()
    await conn.execute(sql, row)
    await conn.commit()
    return stable_id


async def record_trade_rule_set(**values) -> str:
    """Freeze the quote, cost, liquidity, exit, and share rules as one fact."""
    rule_version = _required_text(values.get("rule_version"), "rule version")
    per_contract = values.get(
        "fee_per_contract_per_transaction",
        values.get("per_contract_per_transaction", 0.45),
    )
    fee_micros = dollars_to_micros(per_contract)
    if fee_micros != 450_000:
        raise ValueError("Batch 2 contract fee must be $0.45 per transaction")
    max_quote_age = _number(
        values.get("max_quote_age_seconds"), "maximum quote age", positive=True,
    )
    max_entry_delay = _number(
        values.get("max_delivery_entry_delay_seconds"),
        "maximum delivery-to-entry delay", positive=True,
    )
    liquidity_rule = deepcopy(values.get("liquidity_rule") or {})
    exit_rule = deepcopy(values.get("exit_rule") or {})
    share_rule = deepcopy(values.get("share_rule") or {})
    frozen = {
        "rule_version": rule_version,
        "fee_per_contract_transaction_micros": fee_micros,
        "max_quote_age_seconds": max_quote_age,
        "max_delivery_entry_delay_seconds": max_entry_delay,
        "liquidity_rule": liquidity_rule,
        "exit_rule": exit_rule,
        "share_rule": share_rule,
    }
    rule_set_id = values.get("rule_set_id") or _stable_id("trade_rules", frozen)
    created_at = _number(values.get("created_at", time.time()), "created time", positive=True)
    payload = {**frozen, "rule_set_id": rule_set_id, "created_at": created_at}
    row = (
        rule_set_id, rule_version, fee_micros, max_quote_age, max_entry_delay,
        _json(liquidity_rule), _json(exit_rule), _json(share_rule),
        created_at, _json(payload),
    )
    if values.get("_return_row"):
        return row, rule_set_id
    existing = await _existing_row(
        "measurement_trade_rule_sets_v1", "rule_set_id", rule_set_id,
    )
    if existing is not None:
        if tuple(existing)[1:8] != row[1:8]:
            raise ValueError("rule_set_id already exists with different frozen rules")
        return rule_set_id
    return await _insert_stable(
        table="measurement_trade_rule_sets_v1", id_column="rule_set_id", stable_id=rule_set_id,
        sql="INSERT INTO measurement_trade_rule_sets_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )


async def record_trade_plan(**values) -> str:
    """Store one immutable share or option plan linked to a Batch 1 decision."""
    instrument = _required_text(
        values.get("instrument_type") or values.get("instrument"), "instrument type",
    ).lower()
    if instrument not in {"option", "share"}:
        raise ValueError("instrument type must be option or share")
    direction = _required_text(values.get("direction"), "trade direction").lower()
    if direction not in {"long", "short"}:
        raise ValueError("trade direction must be long or short")
    candidate_id = _required_text(values.get("candidate_id"), "candidate id")
    rule_version = _required_text(
        values.get("rule_version", values.get("result_rule_version")), "rule version",
    )
    trade_id = values.get("trade_id") or build_trade_id(
        candidate_id=candidate_id, instrument_type=instrument,
        direction=direction, rule_version=rule_version,
    )
    event_id = values.get("event_id") or _new_id("trade_plan_event")
    raw_status = str(values.get("status") or values.get("classification") or "pending").lower()
    status = "eligible" if raw_status == "performance_eligible" else raw_status
    if status not in {"registered", "pending", "eligible", "research_only", "ineligible"}:
        raise ValueError("invalid trade plan status")
    quantity = int(_number(values.get("quantity", 1), "quantity", positive=True))
    contract_count = values.get("contract_count")
    if instrument == "option":
        contract_count = int(_number(
            contract_count if contract_count is not None else quantity,
            "contract count", positive=True,
        ))
    elif contract_count is not None:
        contract_count = int(_number(contract_count, "contract count", positive=True))
    created_at = _number(values.get("created_at", time.time()), "created time", positive=True)
    payload = deepcopy(values)
    payload.pop("_return_row", None)
    payload.update({
        "trade_id": trade_id,
        "event_id": event_id,
        "status": status,
        "instrument_type": instrument,
        "direction": direction,
        "candidate_id": candidate_id,
        "rule_version": rule_version,
        "quantity": quantity,
        "contract_count": contract_count,
        "created_at": created_at,
    })
    row = (
        event_id,
        trade_id,
        status,
        candidate_id,
        _required_text(values.get("decision_id"), "decision id"),
        _required_text(values.get("outcome_id"), "outcome id"),
        _required_text(values.get("delivery_id"), "delivery id"),
        _required_text(values.get("rule_set_id"), "rule set id"),
        instrument,
        _required_text(values.get("ticker"), "ticker").upper(),
        direction,
        _required_text(
            values.get("classification")
            or ("performance_eligible" if status == "eligible" else status),
            "classification",
        ),
        (_number(values.get("confirmed_delivery_at"), "confirmed delivery time", positive=True)
         if values.get("confirmed_delivery_at") is not None else None),
        (_number(values.get("primary_horizon_seconds"), "primary horizon", positive=True)
         if values.get("primary_horizon_seconds") is not None else None),
        str(values.get("reason") or ""),
        str(values.get("scorer_version") or ""),
        str(values.get("selection_rule_version") or ""),
        quantity,
        contract_count,
        _required_text(values.get("entry_rule", "unspecified"), "entry rule"),
        _required_text(values.get("exit_rule", "unspecified"), "exit rule"),
        dollars_to_micros(values.get("stop_price")),
        dollars_to_micros(values.get("target_price")),
        dollars_to_micros(
            values.get("planned_risk_dollars", values.get("planned_risk"))
        ),
        _required_text(values.get("fee_rule_version"), "fee rule version"),
        _required_text(values.get("result_rule_version"), "result rule version"),
        created_at,
        _json(payload),
    )
    if values.get("_return_row"):
        return row, trade_id, event_id
    await _insert_stable(
        table="measurement_trade_plan_events_v1", id_column="event_id", stable_id=event_id,
        sql="INSERT INTO measurement_trade_plan_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )
    return trade_id


async def record_contract_selection(**values) -> str:
    """Store the exact immutable option contract selected for a trade."""
    contract = values.get("contract")
    if contract is None:
        contract = values
    contract = validate_option_contract(contract)
    trade_id = _required_text(values.get("trade_id"), "trade id")
    selection_id = values.get("selection_id") or build_contract_selection_id(
        trade_id=trade_id, contract=contract,
    )
    event_id = values.get("event_id") or _new_id("contract_selection_event")
    status = _required_text(values.get("status", "selected"), "selection status").lower()
    selected_at = _number(
        values.get("selected_at", time.time()), "selection time", positive=True,
    )
    payload = deepcopy(contract)
    payload.pop("_return_row", None)
    payload.update({
        "event_id": event_id, "selection_id": selection_id, "trade_id": trade_id,
        "status": status, "selected_at": selected_at,
    })
    row = (
        event_id, selection_id, trade_id, status,
        _required_text(contract.get("contract_symbol"), "contract symbol"),
        _required_text(contract.get("underlying"), "underlying").upper(),
        _required_text(contract.get("option_type"), "option type").lower(),
        _required_text(contract.get("action"), "option action").lower(),
        _required_text(contract.get("strategy", "single_leg"), "option strategy").lower(),
        dollars_to_micros(contract.get("strike")),
        _required_text(contract.get("expiration"), "expiration"),
        int(_number(contract.get("multiplier"), "multiplier", positive=True)),
        _required_text(contract.get("quote_source"), "quote source"),
        _required_text(contract.get("selection_rule_version"), "selection rule version"),
        _required_text(contract.get("scorer_version"), "scorer version"),
        selected_at, _json(payload),
    )
    if values.get("_return_row"):
        return row, selection_id, event_id
    await _insert_stable(
        table="measurement_contract_selection_events_v1", id_column="event_id",
        stable_id=event_id,
        sql="INSERT INTO measurement_contract_selection_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )
    return selection_id


async def record_market_observation(**values) -> str:
    """Store a usable quote or an explicit missing-data observation."""
    observation_id = values.get("observation_id") or _new_id("market_observation")
    trade_id = _required_text(values.get("trade_id"), "trade id")
    purpose = _required_text(values.get("purpose"), "quote purpose").lower()
    if purpose not in {"selection", "entry", "exit"}:
        raise ValueError("quote purpose must be selection, entry, or exit")
    status = _required_text(values.get("status", "observed"), "observation status").lower()
    if status not in {"observed", "missing_data"}:
        raise ValueError("observation status must be observed or missing_data")
    missing_reason = str(values.get("missing_data_reason") or "").strip()
    if status == "missing_data" and not missing_reason:
        raise ValueError("missing_data observation requires missing_data_reason")
    provider_at = values.get("provider_timestamp")
    received_at = values.get("received_timestamp")
    if status == "observed":
        provider_at = _number(provider_at, "provider timestamp", positive=True)
        received_at = _number(received_at, "received timestamp", positive=True)
    observed_at = _number(
        values.get("observed_at", received_at or time.time()),
        "observed time", positive=True,
    )
    usable = bool(values.get("usable", False)) if status == "observed" else False
    payload = deepcopy(values)
    payload.pop("_return_row", None)
    payload.update({
        "observation_id": observation_id, "trade_id": trade_id,
        "purpose": purpose, "status": status, "observed_at": observed_at,
        "usable": usable,
    })
    bid_micros = dollars_to_micros(values.get("bid"))
    ask_micros = dollars_to_micros(values.get("ask"))
    midpoint_micros = values.get("midpoint_micros")
    spread_micros = values.get("spread_micros")
    if midpoint_micros is None and bid_micros is not None and ask_micros is not None:
        midpoint_micros = (bid_micros + ask_micros) // 2
    if spread_micros is None and bid_micros is not None and ask_micros is not None:
        spread_micros = ask_micros - bid_micros
    spread_pct = values.get("spread_pct")
    if spread_pct is None and midpoint_micros:
        spread_pct = (float(spread_micros) / float(midpoint_micros)) * 100.0
    selection_delay = values.get("selection_to_delivery_seconds")
    delivery_delay = values.get("delivery_to_quote_seconds")
    volume = values.get("volume")
    open_interest = values.get("open_interest")
    row = (
        observation_id, trade_id, values.get("contract_selection_id"), purpose, status,
        provider_at, received_at, observed_at, values.get("quote_age_seconds"),
        bid_micros,
        ask_micros,
        dollars_to_micros(values.get("underlying_price")),
        dollars_to_micros(values.get("average_daily_dollar_volume")),
        dollars_to_micros(values.get("executable_price")),
        (_number(selection_delay, "selection-to-delivery delay")
         if selection_delay is not None else None),
        (_number(delivery_delay, "delivery-to-quote delay")
         if delivery_delay is not None else None),
        int(midpoint_micros) if midpoint_micros is not None else None,
        int(spread_micros) if spread_micros is not None else None,
        (_number(spread_pct, "spread percent") if spread_pct is not None else None),
        int(_number(volume, "volume")) if volume is not None else None,
        int(_number(open_interest, "open interest")) if open_interest is not None else None,
        int(bool(values.get("is_delayed", False))),
        str(values.get("halt_status") or ""),
        int(usable), str(values.get("unusable_reason") or ""), missing_reason,
        str(values.get("market_session") or ""), str(values.get("quote_source") or ""),
        str(values.get("result_rule_version") or ""), _json(payload),
    )
    if values.get("_return_row"):
        return row, observation_id
    return await _insert_stable(
        table="measurement_market_observations_v1", id_column="observation_id",
        stable_id=observation_id,
        sql="INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )


async def record_trade_result(**values) -> str:
    """Store one reproducible result event with exact linked observations."""
    trade_id = _required_text(values.get("trade_id"), "trade id")
    status = _required_text(values.get("status"), "result status").lower()
    if status not in {"pending", "resolved", *SPECIAL_OUTCOMES}:
        raise ValueError("invalid trade result status")
    is_primary = bool(values.get("is_primary", True))
    result_rule_version = _required_text(
        values.get("result_rule_version"), "result rule version",
    )
    result_id = values.get("result_id") or build_trade_result_id(
        trade_id=trade_id, result_rule_version=result_rule_version,
        is_primary=is_primary,
    )
    event_id = values.get("event_id") or _new_id("trade_result_event")
    created_at = _number(values.get("created_at", time.time()), "created time", positive=True)
    resolved_at = values.get("resolved_at")
    if status == "resolved":
        if not values.get("entry_observation_id") or not values.get("exit_observation_id"):
            raise ValueError("resolved result requires entry and exit observations")
        resolved_at = _number(resolved_at or created_at, "resolved time", positive=True)
    elif status in SPECIAL_OUTCOMES:
        _required_text(values.get("reason"), "special outcome reason")
        resolved_at = _number(
            values.get("observed_at", resolved_at or created_at),
            "special outcome time",
            positive=True,
        )
    payload = deepcopy(values)
    payload.pop("_return_row", None)
    payload.update({
        "event_id": event_id, "result_id": result_id,
        "trade_id": trade_id, "status": status,
        "created_at": created_at, "resolved_at": resolved_at,
    })
    outcome_id = values.get("outcome_id")
    if not outcome_id and not values.get("_return_row"):
        plan = await get_trade_plan(trade_id)
        outcome_id = plan["outcome_id"] if plan else None
    outcome_id = _required_text(outcome_id, "outcome id")
    payload["outcome_id"] = outcome_id
    row = (
        event_id, result_id, trade_id, outcome_id,
        values.get("contract_selection_id"),
        values.get("entry_observation_id"), values.get("exit_observation_id"),
        status, int(is_primary),
        dollars_to_micros(values.get("gross_dollars")),
        dollars_to_micros(values.get("net_dollars")),
        dollars_to_micros(values.get("planned_risk_dollars")),
        dollars_to_micros(values.get("entry_spread_dollars")),
        dollars_to_micros(values.get("exit_spread_dollars")),
        dollars_to_micros(
            values.get("contract_fees_total", values.get("contract_fees_dollars"))
        ),
        dollars_to_micros(
            values.get("extra_fees_total", values.get("extra_fees_dollars"))
        ),
        _required_text(values.get("fee_rule_version"), "fee rule version"),
        result_rule_version,
        resolved_at, created_at, _json(payload),
    )
    if values.get("_return_row"):
        return row, result_id, event_id
    await _insert_stable(
        table="measurement_trade_result_events_v1", id_column="event_id", stable_id=event_id,
        sql="INSERT INTO measurement_trade_result_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )
    return result_id


async def write_initial_trade_tracking_bundle(
    *, plan: dict, rule_set: dict | None = None,
    contract_selection: dict | None = None,
    observation: dict | None = None, result: dict | None = None,
) -> dict[str, str]:
    """Atomically write the initial exact-trade facts or none of them."""
    statements: list[tuple[str, tuple]] = []
    ids: dict[str, str] = {}
    plan_values = deepcopy(plan)
    if rule_set is not None:
        rule_row, rule_set_id = await record_trade_rule_set(
            **rule_set, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_trade_rule_sets_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rule_row,
        ))
        plan_values.setdefault("rule_set_id", rule_set_id)
        ids["rule_set_id"] = rule_set_id
    plan_row, trade_id, plan_event_id = await record_trade_plan(
        **plan_values, _return_row=True,
    )
    statements.append((
        "INSERT INTO measurement_trade_plan_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        plan_row,
    ))
    ids.update({"trade_id": trade_id, "plan_event_id": plan_event_id})
    selection_id = None
    if contract_selection is not None:
        contract_values = {**contract_selection, "trade_id": trade_id}
        contract_row, selection_id, selection_event_id = await record_contract_selection(
            **contract_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_contract_selection_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            contract_row,
        ))
        ids.update({
            "selection_id": selection_id,
            "selection_event_id": selection_event_id,
        })
    if observation is not None:
        observation_values = {**observation, "trade_id": trade_id}
        if selection_id is not None:
            observation_values.setdefault("contract_selection_id", selection_id)
        observation_row, observation_id = await record_market_observation(
            **observation_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            observation_row,
        ))
        ids["observation_id"] = observation_id
    if result is not None:
        result_values = {**result, "trade_id": trade_id}
        result_values.setdefault("outcome_id", plan_values.get("outcome_id"))
        if selection_id is not None:
            result_values.setdefault("contract_selection_id", selection_id)
        result_row, result_id, result_event_id = await record_trade_result(
            **result_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_trade_result_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            result_row,
        ))
        ids.update({"result_id": result_id, "result_event_id": result_event_id})
    conn = await db.get_db()
    await conn.execute_transaction(statements)
    return ids


write_initial_trade_bundle = write_initial_trade_tracking_bundle


async def write_trade_exit_bundle(
    *, observation: dict, result: dict,
) -> dict[str, str]:
    """Atomically store a qualifying exit quote and its final result."""
    observation_values = deepcopy(observation)
    observation_values.setdefault("observation_id", _new_id("market_observation"))
    observation_row, observation_id = await record_market_observation(
        **observation_values, _return_row=True,
    )
    result_values = deepcopy(result)
    result_values.setdefault("trade_id", observation_values.get("trade_id"))
    result_values.setdefault("exit_observation_id", observation_id)
    result_row, result_id, result_event_id = await record_trade_result(
        **result_values, _return_row=True,
    )
    conn = await db.get_db()
    await conn.execute_transaction([
        (
            "INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            observation_row,
        ),
        (
            "INSERT INTO measurement_trade_result_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            result_row,
        ),
    ])
    return {
        "observation_id": observation_id,
        "result_id": result_id,
        "result_event_id": result_event_id,
    }


async def write_trade_entry_bundle(
    *, entry_observation: dict, plan: dict | None = None,
    result: dict | None = None, contract_selection: dict | None = None,
    selection_observation: dict | None = None,
) -> dict[str, str]:
    """Atomically store the exact contract, entry quote, plan, and pending result."""
    statements: list[tuple[str, tuple]] = []
    ids: dict[str, str] = {}
    trade_id = _required_text(entry_observation.get("trade_id"), "trade id")
    selection_id = entry_observation.get("contract_selection_id")
    if contract_selection is not None:
        contract_values = {**contract_selection, "trade_id": trade_id}
        contract_row, selection_id, selection_event_id = await record_contract_selection(
            **contract_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_contract_selection_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            contract_row,
        ))
        ids.update({
            "selection_id": selection_id,
            "selection_event_id": selection_event_id,
        })
    if selection_observation is not None:
        selection_values = {**selection_observation, "trade_id": trade_id}
        selection_values.setdefault("contract_selection_id", selection_id)
        selection_row, selection_observation_id = await record_market_observation(
            **selection_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            selection_row,
        ))
        ids["selection_observation_id"] = selection_observation_id
    entry_values = {**entry_observation, "trade_id": trade_id}
    entry_values.setdefault("contract_selection_id", selection_id)
    entry_row, entry_observation_id = await record_market_observation(
        **entry_values, _return_row=True,
    )
    statements.append((
        "INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        entry_row,
    ))
    ids["entry_observation_id"] = entry_observation_id
    if plan is not None:
        plan_values = deepcopy(plan)
        plan_values.setdefault("trade_id", trade_id)
        plan_values.setdefault("entry_observation_id", entry_observation_id)
        if selection_id is not None:
            plan_values.setdefault("contract_selection_id", selection_id)
        plan_row, _, plan_event_id = await record_trade_plan(
            **plan_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_trade_plan_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            plan_row,
        ))
        ids["plan_event_id"] = plan_event_id
    if result is not None:
        result_values = deepcopy(result)
        result_values.setdefault("trade_id", trade_id)
        result_values.setdefault("entry_observation_id", entry_observation_id)
        if selection_id is not None:
            result_values.setdefault("contract_selection_id", selection_id)
        result_row, result_id, result_event_id = await record_trade_result(
            **result_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_trade_result_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            result_row,
        ))
        ids.update({"result_id": result_id, "result_event_id": result_event_id})
    conn = await db.get_db()
    await conn.execute_transaction(statements)
    return ids


async def write_special_trade_bundle(
    *, contract_selection: dict | None, observation: dict,
    result: dict, plan: dict,
) -> dict[str, str]:
    """Atomically store special quote evidence, its result, and final plan state."""
    statements: list[tuple[str, tuple]] = []
    ids: dict[str, str] = {}
    trade_id = _required_text(observation.get("trade_id"), "trade id")
    selection_id = observation.get("contract_selection_id")
    if contract_selection is not None:
        contract_values = {**contract_selection, "trade_id": trade_id}
        contract_row, selection_id, selection_event_id = await record_contract_selection(
            **contract_values, _return_row=True,
        )
        statements.append((
            "INSERT INTO measurement_contract_selection_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            contract_row,
        ))
        ids.update({
            "selection_id": selection_id,
            "selection_event_id": selection_event_id,
        })
    observation_values = deepcopy(observation)
    observation_values.setdefault("contract_selection_id", selection_id)
    observation_row, observation_id = await record_market_observation(
        **observation_values, _return_row=True,
    )
    statements.append((
        "INSERT INTO measurement_market_observations_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        observation_row,
    ))
    result_values = deepcopy(result)
    result_values.setdefault("trade_id", trade_id)
    result_values.setdefault("contract_selection_id", selection_id)
    if observation_values.get("purpose") == "exit":
        result_values.setdefault("exit_observation_id", observation_id)
    else:
        result_values.setdefault("entry_observation_id", observation_id)
    result_row, result_id, result_event_id = await record_trade_result(
        **result_values, _return_row=True,
    )
    statements.append((
        "INSERT INTO measurement_trade_result_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        result_row,
    ))
    plan_values = deepcopy(plan)
    plan_values.setdefault("trade_id", trade_id)
    plan_row, _, plan_event_id = await record_trade_plan(
        **plan_values, _return_row=True,
    )
    statements.append((
        "INSERT INTO measurement_trade_plan_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        plan_row,
    ))
    conn = await db.get_db()
    await conn.execute_transaction(statements)
    ids.update({
        "observation_id": observation_id,
        "result_id": result_id,
        "result_event_id": result_event_id,
        "plan_event_id": plan_event_id,
    })
    return ids


async def append_tracking_correction(
    *, entity_type: str, entity_id: str, prior_event_id: str, reason: str,
    corrected_fields: dict, actor_version: str, correction_id: str | None = None,
    created_at: float | None = None,
) -> str:
    correction_id = correction_id or _new_id("trade_correction")
    row = (
        correction_id, _required_text(entity_type, "entity type"),
        _required_text(entity_id, "entity id"),
        _required_text(prior_event_id, "prior event id"),
        _required_text(reason, "correction reason"), _json(corrected_fields),
        _required_text(actor_version, "actor version"),
        _number(created_at or time.time(), "created time", positive=True),
    )
    return await _insert_stable(
        table="measurement_corrections_v1", id_column="correction_id",
        stable_id=correction_id,
        sql="INSERT INTO measurement_corrections_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        row=row,
    )


def _decode_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for json_column in (
        "rule_json", "plan_json", "contract_json", "observation_json", "result_json",
    ):
        if json_column in item:
            item[json_column.removesuffix("_json")] = json.loads(item[json_column])
    return item


async def get_trade_plan(trade_id: str) -> dict | None:
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT * FROM measurement_trade_plan_events_v1
           WHERE trade_id=? ORDER BY rowid DESC LIMIT 1""",
        (trade_id,),
    )
    return _decode_row(await cursor.fetchone())


async def get_trade_rule_set(rule_set_id: str) -> dict | None:
    return _decode_row(await _existing_row(
        "measurement_trade_rule_sets_v1", "rule_set_id", rule_set_id,
    ))


async def get_contract_selection(
    trade_id: str, selection_id: str | None = None,
) -> dict | None:
    conn = await db.get_db()
    if selection_id:
        cursor = await conn.execute(
            """SELECT * FROM measurement_contract_selection_events_v1
               WHERE trade_id=? AND selection_id=?
               ORDER BY selected_at DESC, rowid DESC LIMIT 1""",
            (trade_id, selection_id),
        )
    else:
        cursor = await conn.execute(
            "SELECT * FROM measurement_contract_selection_events_v1 WHERE trade_id=? ORDER BY selected_at DESC, rowid DESC LIMIT 1",
            (trade_id,),
        )
    return _decode_row(await cursor.fetchone())


async def get_first_usable_observation(trade_id: str, purpose: str) -> dict | None:
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT * FROM measurement_market_observations_v1
           WHERE trade_id=? AND purpose=? AND usable=1
           ORDER BY observed_at, observation_id LIMIT 1""",
        (trade_id, purpose),
    )
    return _decode_row(await cursor.fetchone())


async def list_trade_observations(trade_id: str, purpose: str | None = None) -> list[dict]:
    conn = await db.get_db()
    if purpose is None:
        cursor = await conn.execute(
            "SELECT * FROM measurement_market_observations_v1 WHERE trade_id=? ORDER BY observed_at",
            (trade_id,),
        )
    else:
        cursor = await conn.execute(
            "SELECT * FROM measurement_market_observations_v1 WHERE trade_id=? AND purpose=? ORDER BY observed_at",
            (trade_id, purpose),
        )
    return [_decode_row(row) for row in await cursor.fetchall()]


async def get_trade_tracking_chain(trade_id: str) -> dict:
    conn = await db.get_db()
    plan = await get_trade_plan(trade_id)
    result = {
        "plan": plan,
        "rule_set": await get_trade_rule_set(plan["rule_set_id"]) if plan else None,
        "contracts": [], "observations": [], "results": [], "corrections": [],
    }
    for key, table in (
        ("contracts", "measurement_contract_selection_events_v1"),
        ("observations", "measurement_market_observations_v1"),
        ("results", "measurement_trade_result_events_v1"),
    ):
        cursor = await conn.execute(
            f"SELECT * FROM {table} WHERE trade_id=? ORDER BY rowid", (trade_id,),
        )
        result[key] = [_decode_row(row) for row in await cursor.fetchall()]
    entity_ids = {trade_id}
    for key, id_column in (
        ("contracts", "selection_id"), ("observations", "observation_id"),
        ("results", "result_id"),
    ):
        entity_ids.update(item[id_column] for item in result[key])
    for entity_id in entity_ids:
        cursor = await conn.execute(
            "SELECT * FROM measurement_corrections_v1 WHERE entity_id=? ORDER BY created_at",
            (entity_id,),
        )
        for row in await cursor.fetchall():
            item = dict(row)
            item["corrected_fields"] = json.loads(item["corrected_fields_json"])
            result["corrections"].append(item)
    return result
