"""Shadow-only Batch 2 trade quote collection.

The visible Discord alert is sent first. This module then records exact,
timestamped evidence without changing the alert, score, or live reader.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time as datetime_time, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg, db, measurement, trade_tracking as tracking
from consensus_engine.scanners import schwab_client
from consensus_engine.utils.time_context import nyse_open_now


log = logging.getLogger("consensus_engine.trade_collector")

_entry_queue: asyncio.Queue[str] | None = None
_entry_tasks: set[asyncio.Task] = set()


def _finish_entry_task(task: asyncio.Task) -> None:
    _entry_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        log.warning("Batch 2 entry task failed (%s)", type(error).__name__)


def _setting(name: str, default: Any) -> Any:
    return cfg.get(f"measurement.batch2.{name}", default)


def _journal_path() -> Path:
    configured = str(_setting("delivery_journal_path", "") or "").strip()
    if configured:
        return Path(configured)
    database_path = Path(str(cfg.get("database.path", "consensus.db")))
    return database_path.with_suffix(".batch2-delivery-journal.jsonl")


def _journal_append(event: dict) -> None:
    path = _journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    created = not path.exists()
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        remaining = memoryview(line.encode("utf-8"))
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Batch 2 journal write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if created:
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def _journal_events() -> list[dict]:
    path = _journal_path()
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def collection_enabled() -> bool:
    return bool(_setting("collect_enabled", False))


def quote_collection_enabled() -> bool:
    return collection_enabled() and bool(
        _setting("collect_quotes_enabled", _setting("quote_collect_enabled", False))
    )


def exit_collection_enabled() -> bool:
    return collection_enabled() and bool(_setting("exit_collect_enabled", True))


def _frozen_rules() -> dict:
    return {
        "rule_version": str(_setting("rule_version", "batch2-v1")),
        "fee_rule_version": str(
            _setting("fee_rule_version", "owner-contract-fee-v1")
        ),
        "result_rule_version": str(_setting("result_rule_version", "batch2-result-v1")),
        "selection_rule_version": str(
            _setting("selection_rule_version", "exact-contract-v1")
        ),
        "scorer_version": str(
            cfg.get("measurement.batch1.scorer_version", "consensus-v1")
        ),
        "option_fee": float(
            _setting("option_fee_per_contract_per_transaction", 0.45)
        ),
        "max_quote_age": float(_setting("max_quote_age_seconds", 30)),
        "max_entry_delay": float(_setting("max_delivery_to_entry_seconds", 60)),
        "min_midpoint": float(_setting("min_option_midpoint", 0.20)),
        "max_spread_pct": float(_setting("max_option_spread_pct", 20)),
        "min_open_interest": int(_setting("min_option_open_interest", 100)),
        "share_slippage_bps": float(_setting("share_slippage_bps", 10)),
        "min_share_price": float(_setting("min_share_price", 2)),
        "max_share_spread_pct": float(_setting("max_share_spread_pct", 0.5)),
        "min_share_average_daily_dollar_volume": float(
            _setting("min_share_average_daily_dollar_volume", 10_000_000)
        ),
        "primary_horizon": int(_setting("primary_horizon_seconds", 3600)),
        "option_stop_loss_pct": float(_setting("option_stop_loss_pct", 25)),
        "option_target_gain_pct": float(_setting("option_target_gain_pct", 50)),
        "share_stop_loss_pct": float(_setting("share_stop_loss_pct", 2)),
        "share_target_gain_pct": float(_setting("share_target_gain_pct", 4)),
        "share_gap_special_pct": float(_setting("share_gap_special_pct", 2)),
    }


async def _record_rule_set(rules: dict) -> str:
    return await tracking.record_trade_rule_set(
        rule_version=rules["rule_version"],
        fee_per_contract_per_transaction=rules["option_fee"],
        max_quote_age_seconds=rules["max_quote_age"],
        max_delivery_entry_delay_seconds=rules["max_entry_delay"],
        liquidity_rule={
            "regular_session_only": True,
            "min_midpoint": rules["min_midpoint"],
            "max_spread_pct": rules["max_spread_pct"],
            "min_open_interest": rules["min_open_interest"],
            "positive_exit_bid": True,
        },
        exit_rule={
            "primary_horizon_seconds": rules["primary_horizon"],
            "first_stop_or_target": True,
            "option_stop_loss_pct": rules["option_stop_loss_pct"],
            "option_target_gain_pct": rules["option_target_gain_pct"],
            "share_stop_loss_pct": rules["share_stop_loss_pct"],
            "share_target_gain_pct": rules["share_target_gain_pct"],
            "zero_bid": "zero_value",
            "early_assignment_risk": "not_applicable_buy_to_open_only",
        },
        share_rule={
            "entry": "first_complete_one_minute_vwap_after_delivery",
            "current_provider_support": "unavailable_no_trade_value_or_ticks",
            "slippage_bps_each_side": rules["share_slippage_bps"],
            "commission_dollars": 0.0,
            "min_price": rules["min_share_price"],
            "max_spread_pct": rules["max_share_spread_pct"],
            "min_average_daily_dollar_volume": (
                rules["min_share_average_daily_dollar_volume"]
            ),
            "halt_status": "normal",
            "short_requires_borrow_facts": True,
            "gap_special_pct": rules["share_gap_special_pct"],
        },
    )


async def _rules_for_plan(plan: dict) -> dict:
    rules = _frozen_rules()
    stored = await tracking.get_trade_rule_set(plan["rule_set_id"])
    if stored is not None:
        frozen = dict(stored.get("rule") or {})
        liquidity = dict(frozen.get("liquidity_rule") or {})
        exit_rule = dict(frozen.get("exit_rule") or {})
        share_rule = dict(frozen.get("share_rule") or {})
        rules.update(
            option_fee=float(stored["fee_per_contract_transaction_micros"]) / 1_000_000,
            max_quote_age=float(stored["max_quote_age_seconds"]),
            max_entry_delay=float(stored["max_delivery_entry_delay_seconds"]),
            min_midpoint=float(liquidity.get("min_midpoint", rules["min_midpoint"])),
            max_spread_pct=float(
                liquidity.get("max_spread_pct", rules["max_spread_pct"])
            ),
            min_open_interest=int(
                liquidity.get("min_open_interest", rules["min_open_interest"])
            ),
            primary_horizon=int(
                plan.get("primary_horizon_seconds")
                or exit_rule.get("primary_horizon_seconds")
                or rules["primary_horizon"]
            ),
            fee_rule_version=plan.get("fee_rule_version") or rules["fee_rule_version"],
            result_rule_version=(
                plan.get("result_rule_version") or rules["result_rule_version"]
            ),
            selection_rule_version=(
                plan.get("selection_rule_version") or rules["selection_rule_version"]
            ),
            scorer_version=plan.get("scorer_version") or rules["scorer_version"],
            share_gap_special_pct=float(
                share_rule.get("gap_special_pct", rules["share_gap_special_pct"])
            ),
            option_stop_loss_pct=float(
                exit_rule.get(
                    "option_stop_loss_pct", rules["option_stop_loss_pct"]
                )
            ),
            option_target_gain_pct=float(
                exit_rule.get(
                    "option_target_gain_pct", rules["option_target_gain_pct"]
                )
            ),
            share_stop_loss_pct=float(
                exit_rule.get(
                    "share_stop_loss_pct", rules["share_stop_loss_pct"]
                )
            ),
            share_target_gain_pct=float(
                exit_rule.get(
                    "share_target_gain_pct", rules["share_target_gain_pct"]
                )
            ),
            share_slippage_bps=float(
                share_rule.get(
                    "slippage_bps_each_side", rules["share_slippage_bps"]
                )
            ),
            min_share_price=float(
                share_rule.get("min_price", rules["min_share_price"])
            ),
            max_share_spread_pct=float(
                share_rule.get("max_spread_pct", rules["max_share_spread_pct"])
            ),
            min_share_average_daily_dollar_volume=float(
                share_rule.get(
                    "min_average_daily_dollar_volume",
                    rules["min_share_average_daily_dollar_volume"],
                )
            ),
        )
    return rules


def _option_payload(options: Any) -> dict:
    if options is None:
        return {}
    if isinstance(options, dict):
        return dict(options)
    return {
        "present": bool(getattr(options, "present", False)),
        "strike": getattr(options, "strike", None),
        "expiry": getattr(options, "expiry", None),
        "option_type": getattr(options, "option_type", None),
        "action": getattr(options, "action", None),
        "strategy": getattr(options, "strategy", None),
        "leg_count": getattr(options, "leg_count", None),
        "target_price": getattr(options, "target_price", None),
        "profit_target_pct": getattr(options, "profit_target_pct", None),
    }


def _valid_iso_date(value: Any) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _option_contract_fields_complete(options: dict) -> bool:
    """True when strike/expiry/option_type/action are all set and expiry parses."""
    required = (
        options.get("strike"), options.get("expiry"),
        options.get("option_type"), options.get("action"),
    )
    return not any(value in (None, "") for value in required) and _valid_iso_date(
        options.get("expiry")
    )


def _expiry_already_past(expiry: Any, reference: float | None) -> bool:
    """True when a format-valid expiry date is already behind the alert.

    An upstream source (an LLM-parsed tweet) can name a real-looking but
    stale or hallucinated expiration. Batch 2 can only track a contract that
    could actually be bought at delivery time, so a same-or-earlier expiry
    is treated the same as a missing one rather than being sent to Schwab.
    """
    try:
        expiry_date = datetime.strptime(str(expiry), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    at = reference if reference is not None else time.time()
    today = datetime.fromtimestamp(at, ZoneInfo("America/New_York")).date()
    return expiry_date < today


def _initial_classification(direction: str, options: dict) -> tuple[str, str]:
    if not options:
        if direction == "short":
            return "research_only", "missing_short_borrow_facts"
        return "pending", ""
    if not _option_contract_fields_complete(options):
        return "research_only", "missing_exact_contract_fields"
    option_type = str(options.get("option_type")).lower()
    action = str(options.get("action")).lower()
    strategy = str(options.get("strategy") or "").lower()
    leg_count = options.get("leg_count")
    if action != "buy_to_open":
        return "research_only", "unsupported_strategy"
    if strategy != "single_leg" or leg_count != 1:
        return "research_only", "unsupported_or_unknown_strategy"
    if option_type not in {"call", "put"}:
        return "research_only", "invalid_option_type"
    expected_direction = "long" if option_type == "call" else "short"
    if direction != expected_direction:
        return "research_only", "direction_contract_mismatch"
    return "pending", ""


async def register_confirmed_delivery(
    *, candidate_id: str, decision_id: str, outcome_id: str, delivery_id: str,
    confirmed_delivery_at: float | None, ticker: str, direction: str,
    options: Any = None, source_fingerprint: str = "",
    scorer_version: str | None = None, contract: dict | None = None,
    selection_quote: dict | None = None, rule_set: dict | None = None,
    primary_horizon_seconds: int | None = None,
    alert_output: Any = None,
    _queue_entry: bool = True,
    _registered: bool = False,
    frozen_rules: dict | None = None,
) -> dict | None:
    """Create or confirm the durable denominator row for a visible delivery."""
    if not collection_enabled():
        return None
    direction = str(direction).lower()
    if direction not in {"long", "short"}:
        raise ValueError("Batch 2 trade direction must be long or short")
    rules = dict(frozen_rules) if frozen_rules else _frozen_rules()
    if rule_set is not None:
        rules.update(
            rule_version=str(rule_set["rule_version"]),
            max_quote_age=float(rule_set["max_quote_age_seconds"]),
            max_entry_delay=float(rule_set["max_delivery_entry_delay_seconds"]),
            primary_horizon=int(
                primary_horizon_seconds
                or (rule_set.get("exit_rule") or {}).get(
                    "primary_horizon_seconds", rules["primary_horizon"]
                )
            ),
        )
        liquidity = dict(rule_set.get("liquidity_rule") or {})
        rules.update(
            min_midpoint=float(liquidity.get("min_midpoint", rules["min_midpoint"])),
            max_spread_pct=float(
                liquidity.get("max_spread_pct", rules["max_spread_pct"])
            ),
            min_open_interest=int(
                liquidity.get("min_open_interest", rules["min_open_interest"])
            ),
        )
    option_values = _option_payload(options)
    if contract is not None:
        option_values = {
            "present": True,
            "strike": contract.get("strike"),
            "expiry": contract.get("expiration"),
            "option_type": contract.get("option_type"),
            "action": contract.get("action"),
            "strategy": contract.get("strategy"),
            "leg_count": contract.get("leg_count"),
        }
    elif option_values and (
        not _option_contract_fields_complete(option_values)
        or _expiry_already_past(option_values.get("expiry"), confirmed_delivery_at)
    ):
        # options= here came from an LLM-parsed tweet, not a verified live
        # contract pick (that only happens via the `contract=` kwarg above).
        # "present: true" with no real strike/expiry/type/action, or an
        # already-past expiry, is not a chosen contract -- track the idea
        # honestly as a share idea instead of an unresolvable option idea.
        option_values = {}
    instrument = "option" if option_values else "share"
    status, reason = _initial_classification(direction, option_values)
    if contract is not None and status == "pending":
        status = "eligible"
    trade_id = tracking.build_trade_id(
        candidate_id=candidate_id,
        instrument_type=instrument,
        direction=direction,
        rule_version=rules["rule_version"],
    )
    plan_values = {
        "trade_id": trade_id,
        "status": status,
        "reason": reason,
        "candidate_id": candidate_id,
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "delivery_id": delivery_id,
        "instrument_type": instrument,
        "ticker": ticker,
        "direction": direction,
        "classification": (
            "research_only" if status == "research_only"
            else "performance_eligible" if status == "eligible"
            else "pending"
        ),
        "quantity": 1,
        "contract_count": 1 if instrument == "option" else None,
        "entry_rule": (
            "first_executable_ask_at_or_after_confirmed_delivery"
            if instrument == "option"
            else "first_complete_one_minute_vwap_after_delivery"
        ),
        "exit_rule": "first_stop_or_target_else_primary_horizon",
        "confirmed_delivery_at": confirmed_delivery_at,
        "primary_horizon_seconds": int(
            primary_horizon_seconds or rules["primary_horizon"]
        ),
        "rule_version": rules["rule_version"],
        "fee_rule_version": rules["fee_rule_version"],
        "result_rule_version": rules["result_rule_version"],
        "selection_rule_version": (
            (contract or {}).get("selection_rule_version")
            or rules["selection_rule_version"]
        ),
        "scorer_version": (
            scorer_version or (contract or {}).get("scorer_version")
            or rules["scorer_version"]
        ),
        "source_fingerprint": source_fingerprint,
        "options": option_values,
        "frozen_rules": rules,
    }
    intended_status = status
    intended_reason = reason
    if _registered:
        plan_values.update(
            status="registered",
            reason="",
            classification="awaiting_delivery",
            intended_status=intended_status,
            intended_reason=intended_reason,
        )
    existing = await tracking.get_trade_plan(trade_id)
    if existing is None:
        if contract is not None and selection_quote is not None and rule_set is not None:
            selection = tracking.classify_option_quote(
                selection_quote,
                purpose="selection",
                max_age_seconds=rules["max_quote_age"],
                result_rule_version=rules["result_rule_version"],
            )
            selection.update(
                purpose="selection",
                status="observed",
                observed_at=selection_quote["received_timestamp"],
                selection_to_delivery_seconds=(
                    float(confirmed_delivery_at)
                    - float(selection_quote["provider_timestamp"])
                ),
                delivery_to_quote_seconds=(
                    float(selection_quote["received_timestamp"])
                    - float(confirmed_delivery_at)
                ),
                result_rule_version=rules["result_rule_version"],
            )
            ids = await tracking.write_initial_trade_tracking_bundle(
                rule_set=rule_set,
                plan=plan_values,
                contract_selection={
                    "contract": contract,
                    "status": "selected",
                    "selected_at": selection_quote["received_timestamp"],
                },
                observation=selection,
            )
            ids["alert_output"] = alert_output
            return ids
        rule_set_id = await _record_rule_set(rules)
        await tracking.record_trade_plan(**plan_values, rule_set_id=rule_set_id)
    elif confirmed_delivery_at is not None and existing["status"] == "registered":
        frozen = _plan_values(existing)
        frozen_intended_status = frozen.pop("intended_status", intended_status)
        frozen_intended_reason = frozen.pop("intended_reason", intended_reason)
        frozen.update(
            status=frozen_intended_status,
            reason=frozen_intended_reason,
            classification=(
                "research_only"
                if frozen_intended_status == "research_only"
                else "performance_eligible"
                if frozen_intended_status == "eligible"
                else "pending"
            ),
            confirmed_delivery_at=confirmed_delivery_at,
        )
        await tracking.record_trade_plan(**frozen)
    if confirmed_delivery_at is None:
        return {"trade_id": trade_id, "alert_output": alert_output}
    if status == "research_only" and reason == "missing_exact_contract_fields":
        observations = await tracking.list_trade_observations(trade_id, "selection")
        if not observations:
            await tracking.record_market_observation(
                trade_id=trade_id,
                purpose="selection",
                status="missing_data",
                missing_data_reason=reason,
                observed_at=confirmed_delivery_at,
                quote_source="schwab",
                result_rule_version=rules["result_rule_version"],
            )
        return {"trade_id": trade_id, "alert_output": alert_output}
    if quote_collection_enabled() and contract is None and _queue_entry:
        if _entry_queue is not None:
            _entry_queue.put_nowait(trade_id)
        else:
            task = asyncio.create_task(
                _retry_entry(trade_id), name=f"batch2-entry-{trade_id}",
            )
            _entry_tasks.add(task)
            task.add_done_callback(_finish_entry_task)
    return {"trade_id": trade_id, "alert_output": alert_output}


async def prepare_delivery_registration(**values) -> dict | None:
    """Persist the complete Batch 2 intent before the visible alert is sent."""
    if not collection_enabled():
        return None
    values = dict(values)
    values["confirmed_delivery_at"] = None
    values["_queue_entry"] = False
    values["_registered"] = True
    journal_values = dict(values)
    journal_values["options"] = _option_payload(journal_values.get("options"))
    journal_values.pop("alert_output", None)
    _journal_append({
        "event": "intent",
        "delivery_id": values["delivery_id"],
        "recorded_at": time.time(),
        "values": journal_values,
    })
    return await register_confirmed_delivery(**values)


def _confirmation_event_id(delivery_id: str, confirmed_at: float) -> str:
    digest = hashlib.sha256(
        f"{delivery_id}:{confirmed_at:.6f}".encode("utf-8")
    ).hexdigest()
    return f"batch2_confirm_{digest}"


async def confirm_delivery_registration(
    *, delivery_id: str, decision_id: str, external_message_id: str,
    confirmed_delivery_at: float, registration: dict | None = None,
) -> dict:
    """Atomically confirm the delivery and promote its frozen registration."""
    journal_registration = dict(registration or {})
    if journal_registration:
        rules = _frozen_rules()
        if journal_registration.get("primary_horizon_seconds"):
            rules["primary_horizon"] = int(
                journal_registration["primary_horizon_seconds"]
            )
        journal_registration.setdefault("frozen_rules", rules)
        journal_registration["options"] = _option_payload(
            journal_registration.get("options")
        )
        journal_registration.pop("alert_output", None)
    journal_event = {
        "event": "confirmed",
        "delivery_id": delivery_id,
        "decision_id": decision_id,
        "external_message_id": str(external_message_id),
        "confirmed_delivery_at": confirmed_delivery_at,
        "recorded_at": time.time(),
        "registration": journal_registration,
    }
    try:
        _journal_append(journal_event)
    except OSError as exc:
        log.warning("Batch 2 confirmation journal write failed (%s)", type(exc).__name__)
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT * FROM measurement_trade_plan_events_v1
           WHERE delivery_id=? AND status='registered'
           ORDER BY created_at DESC, rowid DESC LIMIT 1""",
        (delivery_id,),
    )
    registered = tracking._decode_row(await cursor.fetchone())
    if registered is None:
        if journal_registration:
            intent = dict(journal_registration)
            intent.update(
                delivery_id=delivery_id,
                decision_id=decision_id,
                confirmed_delivery_at=None,
                _registered=True,
                _queue_entry=False,
            )
            await register_confirmed_delivery(**intent)
            cursor = await conn.execute(
                """SELECT * FROM measurement_trade_plan_events_v1
                   WHERE delivery_id=? AND status='registered'
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (delivery_id,),
            )
            registered = tracking._decode_row(await cursor.fetchone())
    if registered is None:
        intents = [
            event for event in _journal_events()
            if event.get("delivery_id") == delivery_id
            and event.get("event") == "intent"
        ]
        if not intents:
            raise ValueError("confirmed delivery requires a frozen Batch 2 registration")
        intent = dict(intents[-1]["values"])
        await register_confirmed_delivery(**intent)
        cursor = await conn.execute(
            """SELECT * FROM measurement_trade_plan_events_v1
               WHERE delivery_id=? AND status='registered'
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (delivery_id,),
        )
        registered = tracking._decode_row(await cursor.fetchone())
    if registered is None:
        raise ValueError("confirmed delivery requires frozen Batch 2 trade facts")
    frozen = _plan_values(registered)
    intended_status = frozen.pop("intended_status", "pending")
    intended_reason = frozen.pop("intended_reason", "")
    frozen.update(
        event_id=_confirmation_event_id(delivery_id, confirmed_delivery_at),
        status=intended_status,
        reason=intended_reason,
        classification=(
            "research_only" if intended_status == "research_only"
            else "performance_eligible" if intended_status == "eligible"
            else "pending"
        ),
        confirmed_delivery_at=confirmed_delivery_at,
        created_at=confirmed_delivery_at,
    )
    plan_row, trade_id, _ = await tracking.record_trade_plan(
        **frozen, _return_row=True,
    )
    delivery_row = measurement._delivery_values({
        "event_id": f"delivery_{_confirmation_event_id(delivery_id, confirmed_delivery_at)}",
        "delivery_id": delivery_id,
        "decision_id": decision_id,
        "attempt_id": delivery_id,
        "status": "confirmed_delivered",
        "external_message_id": external_message_id,
        "confirmed_at": confirmed_delivery_at,
        "created_at": confirmed_delivery_at,
    })
    try:
        await conn.execute_transaction([
            (
                "INSERT INTO measurement_delivery_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                delivery_row,
            ),
            (
                "INSERT INTO measurement_trade_plan_events_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                plan_row,
            ),
        ])
    except sqlite3.IntegrityError:
        delivery_cursor = await conn.execute(
            "SELECT * FROM measurement_delivery_events_v1 WHERE event_id=?",
            (delivery_row[0],),
        )
        plan_cursor = await conn.execute(
            "SELECT * FROM measurement_trade_plan_events_v1 WHERE event_id=?",
            (plan_row[0],),
        )
        stored_delivery = await delivery_cursor.fetchone()
        stored_plan = await plan_cursor.fetchone()
        if (
            stored_delivery is None
            or stored_plan is None
            or tuple(stored_delivery) != delivery_row
            or tuple(stored_plan) != plan_row
        ):
            raise
    if quote_collection_enabled() and intended_status == "pending":
        if _entry_queue is not None:
            _entry_queue.put_nowait(trade_id)
        else:
            task = asyncio.create_task(
                _retry_entry(trade_id), name=f"batch2-entry-{trade_id}",
            )
            _entry_tasks.add(task)
            task.add_done_callback(_finish_entry_task)
    _journal_append({
        "event": "committed",
        "delivery_id": delivery_id,
        "recorded_at": time.time(),
    })
    return {"trade_id": trade_id}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quote_timestamps_valid(quote: dict) -> bool:
    provider_at = _epoch_seconds(quote.get("provider_timestamp"))
    received_at = _epoch_seconds(quote.get("received_timestamp"))
    return (
        provider_at is not None
        and received_at is not None
        and provider_at <= received_at
    )


def _epoch_seconds(value: Any) -> float | None:
    number = _finite(value)
    if number is None or number <= 0:
        return None
    return number / 1000.0 if number > 10_000_000_000 else number


def _regular_session(at: float | None) -> str:
    if at is None:
        return "unknown"
    current = datetime.fromtimestamp(at, tz=timezone.utc)
    return "regular" if nyse_open_now(current) else "closed"


class SchwabQuoteProvider:
    """Small async wrapper around the existing synchronous Schwab client."""

    async def option_contract(
        self, *, ticker: str, option_type: str, strike: float, expiration: str,
        contract_symbol: str | None = None,
    ) -> dict | None:
        chain = await asyncio.to_thread(
            schwab_client.get_option_chain,
            ticker,
            contract_type=option_type.upper(),
            from_date=expiration,
            to_date=expiration,
            strike_count=40,
        )
        if chain is None:
            return None
        frame = chain.calls if option_type == "call" else chain.puts
        matches = []
        for _, row in frame.iterrows():
            row_symbol = str(row.get("contractSymbol") or "")
            if contract_symbol and row_symbol != contract_symbol:
                continue
            if str(row.get("expiry") or "") != expiration:
                continue
            row_strike = _finite(row.get("strike"))
            if row_strike is None or abs(row_strike - float(strike)) > 0.000001:
                continue
            matches.append(row)
        standard = [
            row for row in matches
            if not bool(row.get("nonStandard", False))
            and not str(row.get("deliverableNote") or "").strip()
            and int(_finite(row.get("multiplier")) or 0) == 100
        ]
        if len(standard) != 1:
            if matches and any(
                bool(row.get("nonStandard", False))
                or bool(str(row.get("deliverableNote") or "").strip())
                for row in matches
            ):
                row = matches[0]
                received_at = time.time()
                provider_at = _epoch_seconds(row.get("providerQuoteTime"))
                return {
                    "contract_symbol": str(row.get("contractSymbol") or ""),
                    "underlying": ticker.upper(),
                    "option_type": option_type,
                    "strike": float(strike),
                    "expiration": expiration,
                    "multiplier": int(_finite(row.get("multiplier")) or 0),
                    "bid": _finite(row.get("bid")),
                    "ask": _finite(row.get("ask")),
                    "underlying_price": _finite(chain.underlying_price),
                    "volume": _finite(row.get("volume")),
                    "open_interest": _finite(row.get("openInterest")),
                    "provider_timestamp": provider_at,
                    "received_timestamp": received_at,
                    "market_session": _regular_session(provider_at),
                    "quote_source": "schwab",
                    "capture_origin": "live_schwab_api",
                    "is_delayed": bool(chain.is_delayed),
                    "non_standard": bool(row.get("nonStandard", False)),
                    "deliverable_note": str(row.get("deliverableNote") or ""),
                    "special_outcome_status": "adjusted_contract",
                    "special_outcome_reason": "nonstandard_contract_or_deliverable",
                }
            return None
        row = standard[0]
        received_at = time.time()
        provider_at = _epoch_seconds(row.get("providerQuoteTime"))
        underlying_price = _finite(chain.underlying_price)
        in_the_money = (
            underlying_price is not None
            and (
                (option_type == "call" and underlying_price > float(strike))
                or (option_type == "put" and underlying_price < float(strike))
            )
        )
        expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        received_date = datetime.fromtimestamp(
            received_at, ZoneInfo("America/New_York")
        ).date()
        return {
            "contract_symbol": str(row.get("contractSymbol") or ""),
            "underlying": ticker.upper(),
            "option_type": option_type,
            "strike": float(strike),
            "expiration": expiration,
            "multiplier": int(_finite(row.get("multiplier")) or 0),
            "bid": _finite(row.get("bid")),
            "ask": _finite(row.get("ask")),
            "underlying_price": underlying_price,
            "volume": _finite(row.get("volume")),
            "open_interest": _finite(row.get("openInterest")),
            "provider_timestamp": provider_at,
            "received_timestamp": received_at,
            "market_session": _regular_session(provider_at),
            "quote_source": "schwab",
            "capture_origin": "live_schwab_api",
            "is_delayed": bool(chain.is_delayed),
            "non_standard": bool(row.get("nonStandard", False)),
            "deliverable_note": str(row.get("deliverableNote") or ""),
            "days_to_expiration": (expiration_date - received_date).days,
            "in_the_money": bool(in_the_money),
        }

    async def share_quote(self, *, ticker: str) -> dict | None:
        quote, history = await asyncio.gather(
            asyncio.to_thread(schwab_client.get_quote, ticker),
            asyncio.to_thread(
                schwab_client.get_price_history,
                ticker,
                period="1mo",
                interval="1d",
            ),
        )
        if not quote:
            return None
        average_dollar_volume = None
        if history is not None and not history.empty:
            try:
                average_dollar_volume = float(
                    (history["Close"] * history["Volume"]).tail(20).mean()
                )
            except (KeyError, TypeError, ValueError):
                average_dollar_volume = None
        received_at = time.time()
        provider_at = _epoch_seconds(quote.get("quote_time"))
        return {
            "bid": _finite(quote.get("bid")),
            "ask": _finite(quote.get("ask")),
            "underlying_price": _finite(quote.get("c")),
            "volume": _finite(quote.get("v")),
            "average_daily_dollar_volume": average_dollar_volume,
            "open_interest": None,
            "provider_timestamp": provider_at,
            "received_timestamp": received_at,
            "market_session": _regular_session(provider_at),
            "quote_source": "schwab",
            "capture_origin": "live_schwab_api",
            "is_delayed": False,
            "halt_status": str(quote.get("halt_status") or "unknown").lower(),
            "open_price": _finite(quote.get("o")),
            "previous_close": _finite(quote.get("pc")),
        }

    async def share_entry_quote(
        self, *, ticker: str, confirmed_delivery_at: float,
    ) -> None:
        """Schwab OHLCV bars do not expose exact one-minute traded-value VWAP."""
        return None


def _plan_values(plan: dict) -> dict:
    payload = dict(plan.get("plan") or {})
    payload.pop("event_id", None)
    payload.pop("created_at", None)
    payload.pop("_return_row", None)
    payload.update({
        key: plan[key]
        for key in (
            "trade_id", "candidate_id", "decision_id", "outcome_id",
            "delivery_id", "rule_set_id", "instrument_type", "ticker",
            "direction", "quantity", "contract_count", "fee_rule_version",
            "result_rule_version",
        )
        if key in plan
    })
    return payload


async def _append_plan(plan: dict, *, status: str, reason: str = "", **changes) -> None:
    values = _plan_values(plan)
    values.update(changes)
    values.update(
        status=status,
        reason=reason,
        classification=(
            "performance_eligible" if status == "eligible" else status
        ),
    )
    await tracking.record_trade_plan(**values)


def _observation_values(
    trade_id: str, quote: dict, *, purpose: str, rules: dict,
    contract_selection_id: str | None = None,
    confirmed_delivery_at: float | None = None,
) -> dict:
    values = dict(quote)
    values.update(
        trade_id=trade_id,
        contract_selection_id=contract_selection_id,
        purpose=purpose,
        status="observed",
        observed_at=quote.get("received_timestamp") or time.time(),
        result_rule_version=rules["result_rule_version"],
    )
    if confirmed_delivery_at is not None and quote.get("received_timestamp") is not None:
        values["delivery_to_quote_seconds"] = (
            float(quote["received_timestamp"]) - float(confirmed_delivery_at)
        )
    if confirmed_delivery_at is not None:
        values["selection_to_delivery_seconds"] = (
            float(confirmed_delivery_at)
            - float(quote.get("provider_timestamp") or confirmed_delivery_at)
        )
    return values


def _special_status_from_quote(
    instrument_type: str, quote: dict, rules: dict | None = None,
) -> tuple[str, str]:
    rules = rules or _frozen_rules()
    status = str(quote.get("special_outcome_status") or "").strip().lower()
    reason = str(quote.get("special_outcome_reason") or "").strip()
    if instrument_type == "option" and status == "early_assignment_risk":
        return "", ""
    if not status and instrument_type == "share":
        halt_status = str(quote.get("halt_status") or "").strip().lower()
        if halt_status and halt_status not in {"normal", "not_halted"}:
            status = "halted"
            reason = f"halt_status_{halt_status}"
    return status, reason or status


def _special_observation_values(
    plan: dict, quote: dict, *, purpose: str, rules: dict,
    contract_selection_id: str | None = None,
    status_override: str = "",
) -> dict:
    status = status_override or _special_status_from_quote(
        plan["instrument_type"], quote, rules,
    )[0]
    values = dict(quote)
    values.update(
        trade_id=plan["trade_id"],
        contract_selection_id=contract_selection_id,
        purpose=purpose,
        status="observed",
        observed_at=quote.get("received_timestamp") or time.time(),
        usable=False,
        unusable_reason=status,
        result_rule_version=rules["result_rule_version"],
    )
    return values


async def _store_special_quote(
    plan: dict, quote: dict, *, purpose: str, rules: dict,
    contract_selection_id: str | None = None,
    status_override: str = "",
) -> str:
    return await tracking.record_market_observation(**_special_observation_values(
        plan,
        quote,
        purpose=purpose,
        rules=rules,
        contract_selection_id=contract_selection_id,
        status_override=status_override,
    ))


async def _record_missing(
    plan: dict, *, purpose: str, reason: str, contract_selection_id: str | None = None,
) -> str:
    rules = await _rules_for_plan(plan)
    return await tracking.record_market_observation(
        trade_id=plan["trade_id"],
        contract_selection_id=contract_selection_id,
        purpose=purpose,
        status="missing_data",
        missing_data_reason=reason,
        observed_at=time.time(),
        quote_source="schwab",
        result_rule_version=rules["result_rule_version"],
    )


async def _recover_frozen_entry(plan: dict, entry: dict) -> dict:
    """Finish plan/result facts if a restart followed the immutable entry write."""
    if plan["status"] == "research_only":
        return entry
    rules = await _rules_for_plan(plan)
    data = dict(entry.get("observation") or {})
    selection = await tracking.get_contract_selection(plan["trade_id"])
    executable = float(data["executable_price"])
    spread = float(data["ask"]) - float(data["bid"])
    if plan["instrument_type"] == "option":
        if selection is None:
            raise ValueError("option entry requires exact contract selection")
        stop = executable * (1.0 - rules["option_stop_loss_pct"] / 100.0)
        target = executable * (1.0 + rules["option_target_gain_pct"] / 100.0)
        planned_risk = (
            (executable - stop + spread) * int(selection["multiplier"])
            + 2 * rules["option_fee"]
        )
    elif plan["direction"] == "long":
        stop = executable * (1.0 - rules["share_stop_loss_pct"] / 100.0)
        target = executable * (1.0 + rules["share_target_gain_pct"] / 100.0)
        planned_risk = abs(executable - stop) + spread
    else:
        stop = executable * (1.0 + rules["share_stop_loss_pct"] / 100.0)
        target = executable * (1.0 - rules["share_target_gain_pct"] / 100.0)
        planned_risk = abs(executable - stop) + spread
    if plan["status"] != "eligible" or plan.get("planned_risk_micros") is None:
        await _append_plan(
            plan,
            status="eligible",
            stop_price=stop,
            target_price=target,
            planned_risk_dollars=planned_risk,
            entry_observation_id=entry["observation_id"],
            contract_selection_id=(selection["selection_id"] if selection else None),
            entry_received_at=data["received_timestamp"],
            exit_due_at=data["received_timestamp"] + rules["primary_horizon"],
        )
        plan = await tracking.get_trade_plan(plan["trade_id"])
    chain = await tracking.get_trade_tracking_chain(plan["trade_id"])
    if not chain["results"]:
        await tracking.record_trade_result(
            trade_id=plan["trade_id"],
            outcome_id=plan["outcome_id"],
            contract_selection_id=(selection["selection_id"] if selection else None),
            entry_observation_id=entry["observation_id"],
            status="pending",
            is_primary=True,
            planned_risk_dollars=planned_risk,
            fee_rule_version=rules["fee_rule_version"],
            result_rule_version=rules["result_rule_version"],
            entry_quote=data,
            contract_multiplier=(selection["multiplier"] if selection else None),
            contract_count=int(plan.get("contract_count") or 1),
            quantity=int(plan.get("quantity") or 1),
        )
    return entry


async def _call_supplied_provider(provider: Any, *, trade_id: str, purpose: str) -> list[dict]:
    try:
        result = await provider(trade_id=trade_id, purpose=purpose)
    except TypeError:
        result = await provider()
    if result is None:
        return []
    return list(result) if isinstance(result, (list, tuple)) else [dict(result)]


async def _freeze_supplied_entry(plan: dict, provider: Any) -> dict | None:
    rules = await _rules_for_plan(plan)
    values = _plan_values(plan)
    delivered_at = float(values["confirmed_delivery_at"])
    selection = await tracking.get_contract_selection(plan["trade_id"])
    selection_observations = await tracking.list_trade_observations(
        plan["trade_id"], "selection",
    )
    selection_delay = (
        selection_observations[0].get("selection_to_delivery_seconds")
        if selection_observations else None
    )
    for quote in await _call_supplied_provider(
        provider, trade_id=plan["trade_id"], purpose="entry",
    ):
        if plan["instrument_type"] == "option":
            entry_quote = tracking.assess_option_quote(
                quote,
                purpose="entry",
                confirmed_delivery_at=delivered_at,
                max_age_seconds=rules["max_quote_age"],
                max_delivery_delay_seconds=rules["max_entry_delay"],
                min_midpoint=rules["min_midpoint"],
                max_spread_pct=rules["max_spread_pct"],
                min_open_interest=rules["min_open_interest"],
                result_rule_version=rules["result_rule_version"],
            )
        else:
            entry_quote = tracking.assess_share_quote(
                quote,
                direction=plan["direction"],
                purpose="entry",
                confirmed_delivery_at=delivered_at,
                max_age_seconds=rules["max_quote_age"],
                max_delivery_delay_seconds=rules["max_entry_delay"],
                slippage_bps=rules["share_slippage_bps"],
                result_rule_version=rules["result_rule_version"],
                min_price=rules["min_share_price"],
                max_spread_pct=rules["max_share_spread_pct"],
                min_average_daily_dollar_volume=(
                    rules["min_share_average_daily_dollar_volume"]
                ),
                require_normal_halt=True,
            )
        observation_values = _observation_values(
            plan["trade_id"], entry_quote, purpose="entry", rules=rules,
            contract_selection_id=(selection["selection_id"] if selection else None),
            confirmed_delivery_at=delivered_at,
        )
        if selection_delay is not None:
            observation_values["selection_to_delivery_seconds"] = selection_delay
        observation_id = await tracking.record_market_observation(**observation_values)
        if not entry_quote["usable"]:
            continue
        if plan["status"] == "research_only":
            return await tracking.get_first_usable_observation(plan["trade_id"], "entry")
        entry = float(entry_quote["executable_price"])
        spread = float(entry_quote["ask"]) - float(entry_quote["bid"])
        if plan["instrument_type"] == "option":
            if selection is None:
                raise ValueError("option entry requires exact contract selection")
            stop = entry * (1.0 - rules["option_stop_loss_pct"] / 100.0)
            target = entry * (1.0 + rules["option_target_gain_pct"] / 100.0)
            planned_risk = (
                (entry - stop + spread) * int(selection["multiplier"])
                + 2 * rules["option_fee"]
            )
        elif plan["direction"] == "long":
            stop = entry * (1.0 - rules["share_stop_loss_pct"] / 100.0)
            target = entry * (1.0 + rules["share_target_gain_pct"] / 100.0)
            planned_risk = abs(entry - stop) + spread
        else:
            stop = entry * (1.0 + rules["share_stop_loss_pct"] / 100.0)
            target = entry * (1.0 - rules["share_target_gain_pct"] / 100.0)
            planned_risk = abs(entry - stop) + spread
        if (
            plan["status"] != "eligible"
            or plan.get("stop_price_micros") is None
            or not (plan.get("plan") or {}).get("exit_due_at")
        ):
            await _append_plan(
                plan,
                status="eligible",
                stop_price=stop,
                target_price=target,
                planned_risk_dollars=planned_risk,
                entry_observation_id=observation_id,
                contract_selection_id=(selection["selection_id"] if selection else None),
                entry_received_at=entry_quote["received_timestamp"],
                exit_due_at=entry_quote["received_timestamp"] + rules["primary_horizon"],
            )
        await tracking.record_trade_result(
            trade_id=plan["trade_id"],
            outcome_id=plan["outcome_id"],
            contract_selection_id=(selection["selection_id"] if selection else None),
            entry_observation_id=observation_id,
            status="pending",
            is_primary=True,
            planned_risk_dollars=planned_risk,
            fee_rule_version=rules["fee_rule_version"],
            result_rule_version=rules["result_rule_version"],
            entry_quote=entry_quote,
            contract_multiplier=(selection["multiplier"] if selection else None),
            contract_count=int(plan.get("contract_count") or 1),
            quantity=int(plan.get("quantity") or 1),
        )
        return await tracking.get_first_usable_observation(plan["trade_id"], "entry")
    return None


async def capture_trade_entry(
    trade_id: str, *, quote_provider: Any | None = None,
) -> dict | None:
    """Record one exact quote attempt and freeze the first usable entry."""
    if not quote_collection_enabled():
        return None
    plan = await tracking.get_trade_plan(trade_id)
    if plan is None:
        raise ValueError(f"unknown Batch 2 trade: {trade_id}")
    existing = await tracking.get_first_usable_observation(trade_id, "entry")
    if existing is not None:
        return await _recover_frozen_entry(plan, existing)
    values = _plan_values(plan)
    rules = await _rules_for_plan(plan)
    provider = quote_provider or SchwabQuoteProvider()
    delivered_at = float(values["confirmed_delivery_at"])

    if quote_provider is not None and callable(quote_provider):
        return await _freeze_supplied_entry(plan, quote_provider)

    try:
        if plan["instrument_type"] == "option":
            options = dict(values.get("options") or {})
            stored_selection = await tracking.get_contract_selection(trade_id)
            quote = await provider.option_contract(
                ticker=plan["ticker"],
                option_type=str(options.get("option_type") or "").lower(),
                strike=float(options["strike"]),
                expiration=str(options["expiry"]),
                contract_symbol=(
                    stored_selection["contract_symbol"] if stored_selection else None
                ),
            )
            if quote is None:
                await _record_missing(plan, purpose="selection", reason="exact_contract_not_found")
                return None
            if not _quote_timestamps_valid(quote):
                await _record_missing(
                    plan, purpose="selection", reason="invalid_provider_quote_timestamp",
                )
                await _append_plan(
                    plan, status="ineligible", reason="invalid_provider_quote_timestamp",
                )
                return None
            contract = {
                **quote,
                "action": str(options.get("action") or "").lower(),
                "strategy": str(options.get("strategy") or "").lower(),
                "leg_count": options.get("leg_count"),
                "quote_source": quote.get("quote_source") or "schwab",
                "selection_rule_version": rules["selection_rule_version"],
                "scorer_version": values.get("scorer_version") or rules["scorer_version"],
            }
            try:
                tracking.validate_option_contract(contract)
                selection_id = (
                    stored_selection["selection_id"]
                    if stored_selection
                    else tracking.build_contract_selection_id(
                        trade_id=trade_id, contract=contract,
                    )
                )
            except ValueError:
                await _record_missing(
                    plan, purpose="selection", reason="missing_exact_contract_fields",
                )
                await _append_plan(
                    plan, status="ineligible", reason="missing_exact_contract_fields",
                )
                return None
            special_status, special_reason = _special_status_from_quote(
                plan["instrument_type"], quote, rules
            )
            if special_status:
                special_result = tracking.build_special_outcome(
                    trade_id=trade_id,
                    status=special_status,
                    reason=special_reason,
                    observed_at=float(quote["received_timestamp"]),
                    result_rule_version=rules["result_rule_version"],
                )
                special_result.update(
                    outcome_id=plan["outcome_id"],
                    contract_selection_id=selection_id,
                    is_primary=True,
                    fee_rule_version=rules["fee_rule_version"],
                )
                final_plan = _plan_values(plan)
                final_plan.update(
                    status="ineligible",
                    reason=special_reason,
                    classification="ineligible",
                )
                await tracking.write_special_trade_bundle(
                    contract_selection=(
                        {
                            "contract": contract,
                            "status": "selected",
                            "selected_at": quote["received_timestamp"],
                        }
                        if stored_selection is None else None
                    ),
                    observation=_special_observation_values(
                        plan,
                        quote,
                        purpose="selection",
                        rules=rules,
                        contract_selection_id=selection_id,
                    ),
                    result=special_result,
                    plan=final_plan,
                )
                return None
            selection_quote = tracking.classify_option_quote(
                quote, purpose="selection", max_age_seconds=rules["max_quote_age"],
                result_rule_version=rules["result_rule_version"],
            )
            selection_observation = _observation_values(
                trade_id, selection_quote, purpose="selection", rules=rules,
                contract_selection_id=selection_id,
                confirmed_delivery_at=delivered_at,
            )
            entry_quote = tracking.assess_option_quote(
                quote,
                purpose="entry",
                confirmed_delivery_at=delivered_at,
                max_age_seconds=rules["max_quote_age"],
                max_delivery_delay_seconds=rules["max_entry_delay"],
                min_midpoint=rules["min_midpoint"],
                max_spread_pct=rules["max_spread_pct"],
                min_open_interest=rules["min_open_interest"],
                result_rule_version=rules["result_rule_version"],
            )
            entry_observation = _observation_values(
                trade_id, entry_quote, purpose="entry", rules=rules,
                contract_selection_id=selection_id,
                confirmed_delivery_at=delivered_at,
            )
            if not entry_quote["usable"]:
                ids = await tracking.write_trade_entry_bundle(
                    contract_selection=(
                        {
                            "contract": contract,
                            "status": "selected",
                            "selected_at": quote["received_timestamp"],
                        }
                        if stored_selection is None else None
                    ),
                    selection_observation=(
                        selection_observation if stored_selection is None else None
                    ),
                    entry_observation=entry_observation,
                )
                observation_id = ids["entry_observation_id"]
                return {**entry_quote, "observation_id": observation_id}
            if plan["status"] == "research_only":
                ids = await tracking.write_trade_entry_bundle(
                    contract_selection=(
                        {
                            "contract": contract,
                            "status": "selected",
                            "selected_at": quote["received_timestamp"],
                        }
                        if stored_selection is None else None
                    ),
                    selection_observation=(
                        selection_observation if stored_selection is None else None
                    ),
                    entry_observation=entry_observation,
                )
                observation_id = ids["entry_observation_id"]
                return {**entry_quote, "observation_id": observation_id}
            entry = float(entry_quote["executable_price"])
            stop = entry * (1.0 - rules["option_stop_loss_pct"] / 100.0)
            target = entry * (1.0 + rules["option_target_gain_pct"] / 100.0)
            spread = float(entry_quote["ask"]) - float(entry_quote["bid"])
            planned_risk = (
                (entry - stop + spread)
                * int(
                    stored_selection["multiplier"]
                    if stored_selection else contract["multiplier"]
                )
                + 2 * rules["option_fee"]
            )
            eligible_plan = _plan_values(plan)
            eligible_plan.update(
                status="eligible", reason="",
                classification="performance_eligible",
                stop_price=stop, target_price=target,
                planned_risk_dollars=planned_risk,
                contract_selection_id=selection_id,
                entry_received_at=entry_quote["received_timestamp"],
                exit_due_at=entry_quote["received_timestamp"] + rules["primary_horizon"],
            )
            pending_result = {
                "trade_id": trade_id,
                "outcome_id": plan["outcome_id"],
                "contract_selection_id": selection_id,
                "status": "pending",
                "is_primary": True,
                "planned_risk_dollars": planned_risk,
                "fee_rule_version": rules["fee_rule_version"],
                "result_rule_version": rules["result_rule_version"],
                "entry_quote": entry_quote,
                "contract_multiplier": int(
                    stored_selection["multiplier"]
                    if stored_selection else contract["multiplier"]
                ),
                "contract_count": 1,
            }
            ids = await tracking.write_trade_entry_bundle(
                contract_selection=(
                    {
                        "contract": contract,
                        "status": "selected",
                        "selected_at": quote["received_timestamp"],
                    }
                    if stored_selection is None else None
                ),
                selection_observation=(
                    selection_observation if stored_selection is None else None
                ),
                entry_observation=entry_observation,
                plan=eligible_plan,
                result=pending_result,
            )
            observation_id = ids["entry_observation_id"]
            return {**entry_quote, "observation_id": observation_id}

        if hasattr(provider, "share_entry_quote"):
            quote = await provider.share_entry_quote(
                ticker=plan["ticker"], confirmed_delivery_at=delivered_at,
            )
            if quote is None:
                await _record_missing(
                    plan,
                    purpose="entry",
                    reason="first_complete_minute_vwap_unavailable_current_source",
                )
                await _append_plan(
                    plan,
                    status="research_only",
                    reason="first_complete_minute_vwap_unavailable_current_source",
                )
                return None
        else:
            quote = await provider.share_quote(ticker=plan["ticker"])
        if quote is None:
            await _record_missing(plan, purpose="entry", reason="share_quote_missing")
            return None
        if not _quote_timestamps_valid(quote):
            await _record_missing(
                plan, purpose="entry", reason="invalid_provider_quote_timestamp",
            )
            await _append_plan(
                plan, status="ineligible", reason="invalid_provider_quote_timestamp",
            )
            return None
        special_status, special_reason = _special_status_from_quote(
            plan["instrument_type"], quote, rules
        )
        if special_status:
            observation_id = await _store_special_quote(
                plan, quote, purpose="entry", rules=rules,
            )
            await _record_special_outcome(
                plan, None, {"observation_id": observation_id}, rules,
                status=special_status,
                reason=special_reason,
                observed_at=float(quote.get("received_timestamp") or time.time()),
                evidence_observation_id=observation_id,
            )
            await _append_plan(plan, status="ineligible", reason=special_reason)
            return None
        entry_quote = tracking.assess_share_quote(
            quote,
            direction=plan["direction"],
            purpose="entry",
            confirmed_delivery_at=delivered_at,
            max_age_seconds=rules["max_quote_age"],
            max_delivery_delay_seconds=rules["max_entry_delay"],
            slippage_bps=rules["share_slippage_bps"],
            result_rule_version=rules["result_rule_version"],
            min_price=rules["min_share_price"],
            max_spread_pct=rules["max_share_spread_pct"],
            min_average_daily_dollar_volume=(
                rules["min_share_average_daily_dollar_volume"]
            ),
            require_normal_halt=True,
        )
        entry_observation = _observation_values(
            trade_id, entry_quote, purpose="entry", rules=rules,
            confirmed_delivery_at=delivered_at,
        )
        if not entry_quote["usable"] or plan["status"] == "research_only":
            observation_id = await tracking.record_market_observation(
                **entry_observation
            )
            return {**entry_quote, "observation_id": observation_id}
        entry = float(entry_quote["executable_price"])
        if plan["direction"] == "long":
            stop = entry * (1.0 - rules["share_stop_loss_pct"] / 100.0)
            target = entry * (1.0 + rules["share_target_gain_pct"] / 100.0)
        else:
            stop = entry * (1.0 + rules["share_stop_loss_pct"] / 100.0)
            target = entry * (1.0 - rules["share_target_gain_pct"] / 100.0)
        spread = float(entry_quote["ask"]) - float(entry_quote["bid"])
        planned_risk = abs(entry - stop) + spread
        eligible_plan = _plan_values(plan)
        eligible_plan.update(
            status="eligible", reason="", classification="performance_eligible",
            stop_price=stop, target_price=target,
            planned_risk_dollars=planned_risk,
            entry_received_at=entry_quote["received_timestamp"],
            exit_due_at=entry_quote["received_timestamp"] + rules["primary_horizon"],
        )
        ids = await tracking.write_trade_entry_bundle(
            entry_observation=entry_observation,
            plan=eligible_plan,
            result={
                "trade_id": trade_id,
                "outcome_id": plan["outcome_id"],
                "status": "pending",
                "is_primary": True,
                "planned_risk_dollars": planned_risk,
                "fee_rule_version": rules["fee_rule_version"],
                "result_rule_version": rules["result_rule_version"],
                "entry_quote": entry_quote,
                "quantity": 1,
            },
        )
        observation_id = ids["entry_observation_id"]
        return {**entry_quote, "observation_id": observation_id}
    except (KeyError, TypeError, ValueError, sqlite3.IntegrityError):
        raise
    except Exception as exc:
        await _record_missing(
            plan, purpose="entry", reason=f"provider_{type(exc).__name__.lower()}"
        )
        log.warning(
            "Batch 2 entry quote failed for $%s (%s)",
            plan["ticker"], type(exc).__name__,
        )
        return None


async def _open_trades() -> list[dict]:
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT p.*
           FROM measurement_trade_plan_events_v1 p
           WHERE p.rowid=(
               SELECT p2.rowid FROM measurement_trade_plan_events_v1 p2
               WHERE p2.trade_id=p.trade_id
               ORDER BY p2.rowid DESC LIMIT 1
           )
             AND p.status='eligible'
             AND EXISTS (
                 SELECT 1 FROM measurement_market_observations_v1 o
                 WHERE o.trade_id=p.trade_id AND o.purpose='entry' AND o.usable=1
             )
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_trade_result_events_v1 r
                 WHERE r.trade_id=p.trade_id AND r.is_primary=1
                   AND r.status IN (
                       'resolved', 'adjusted_contract', 'expired',
                       'early_assignment_risk', 'halted', 'gap', 'cannot_close'
                   )
             )"""
    )
    rows = []
    for row in await cursor.fetchall():
        item = dict(row)
        item["plan"] = __import__("json").loads(item["plan_json"])
        rows.append(item)
    return rows


def _exit_reason(plan: dict, values: dict, executable: float, now: float) -> str | None:
    stop = tracking.micros_to_dollars(plan.get("stop_price_micros"))
    target = tracking.micros_to_dollars(plan.get("target_price_micros"))
    due = float(values.get("exit_due_at") or 0)
    if plan["instrument_type"] == "option" or plan["direction"] == "long":
        stop_hit = stop is not None and executable <= stop
        target_hit = target is not None and executable >= target
    else:
        stop_hit = stop is not None and executable >= stop
        target_hit = target is not None and executable <= target
    if stop_hit:
        return "stop"
    if target_hit:
        return "target"
    if now >= due:
        return "primary_horizon"
    return None


def _stored_quote(observation: dict) -> dict:
    quote = dict(observation.get("observation") or {})
    for key, micros_key in (
        ("bid", "bid_micros"),
        ("ask", "ask_micros"),
        ("executable_price", "executable_price_micros"),
    ):
        if quote.get(key) is None and observation.get(micros_key) is not None:
            quote[key] = tracking.micros_to_dollars(observation[micros_key])
    quote.setdefault("usable", bool(observation.get("usable")))
    return quote


async def _resolved_result_values(
    plan: dict, entry: dict, selection: dict | None, exit_quote: dict,
    exit_observation_id: str, exit_reason: str, now: float, rules: dict,
) -> dict:
    entry_data = dict(entry.get("observation") or {})
    executable = float(exit_quote["executable_price"])
    if plan["instrument_type"] == "option":
        result = tracking.calculate_option_result(
            entry_quote=entry_data,
            exit_quote=exit_quote,
            contract_multiplier=selection["multiplier"],
            contract_count=int(plan.get("contract_count") or 1),
            fee_rule={
                "version": rules["fee_rule_version"],
                "per_contract_per_transaction": rules["option_fee"],
                "extra_fees": [],
            },
            result_rule_version=rules["result_rule_version"],
        )
    else:
        entry_price = float(entry_data["executable_price"])
        entry_reference = float(entry_data.get("reference_price", entry_price))
        exit_reference = float(exit_quote.get("reference_price", executable))
        result = tracking.calculate_share_result(
            direction=plan["direction"],
            entry_price=entry_price,
            exit_price=executable,
            quantity=int(plan["quantity"]),
            spread_dollars=(
                float(entry_data["ask"]) - float(entry_data["bid"])
                + float(exit_quote["ask"]) - float(exit_quote["bid"])
            ),
            commission_dollars=0.0,
            slippage_dollars=(
                abs(entry_price - entry_reference)
                + abs(executable - exit_reference)
            ),
            planned_risk_dollars=(
                tracking.micros_to_dollars(plan["planned_risk_micros"]) or 0
            ),
            fee_rule_version=rules["fee_rule_version"],
            result_rule_version=rules["result_rule_version"],
        )
    return {
        **result,
        "trade_id": plan["trade_id"],
        "outcome_id": plan["outcome_id"],
        "contract_selection_id": (
            selection["selection_id"] if selection else None
        ),
        "entry_observation_id": entry["observation_id"],
        "exit_observation_id": exit_observation_id,
        "status": "resolved",
        "is_primary": True,
        "resolved_at": now,
        "exit_reason": exit_reason,
        "fee_rule_version": rules["fee_rule_version"],
        "result_rule_version": rules["result_rule_version"],
    }


async def _record_special_outcome(
    plan: dict, selection: dict | None, entry: dict | None, rules: dict, *,
    status: str, reason: str, observed_at: float,
    evidence_observation_id: str | None = None,
    exit_observation_id: str | None = None,
) -> None:
    special = tracking.build_special_outcome(
        trade_id=plan["trade_id"],
        status=status,
        reason=reason,
        observed_at=observed_at,
        result_rule_version=rules["result_rule_version"],
    )
    await tracking.record_trade_result(
        **special,
        outcome_id=plan["outcome_id"],
        contract_selection_id=(selection["selection_id"] if selection else None),
        entry_observation_id=(
            entry["observation_id"] if entry else evidence_observation_id
        ),
        exit_observation_id=exit_observation_id,
        is_primary=True,
        fee_rule_version=rules["fee_rule_version"],
    )


def _overnight_share_gap(
    entry: dict, quote: dict, rules: dict,
) -> tuple[str, str] | None:
    entry_at = _epoch_seconds(
        entry.get("provider_timestamp")
        or (entry.get("observation") or {}).get("provider_timestamp")
    )
    quote_at = _epoch_seconds(quote.get("provider_timestamp"))
    if entry_at is None or quote_at is None:
        return None
    market_zone = ZoneInfo("America/New_York")
    if quote_at <= entry_at:
        return None
    if (
        datetime.fromtimestamp(entry_at, market_zone).date()
        >= datetime.fromtimestamp(quote_at, market_zone).date()
    ):
        return None
    open_price = _finite(quote.get("open_price"))
    previous_close = _finite(quote.get("previous_close"))
    if open_price is None or previous_close is None or previous_close <= 0:
        return None
    gap_pct = abs(open_price - previous_close) / previous_close * 100.0
    if gap_pct < float(rules["share_gap_special_pct"]):
        return None
    return "gap", f"overnight_open_gap_{gap_pct:.4f}_pct"


async def _resolve_one_exit(plan: dict, provider: Any, now: float) -> dict | None:
    rules = await _rules_for_plan(plan)
    values = _plan_values(plan)
    entry = await tracking.get_first_usable_observation(plan["trade_id"], "entry")
    if entry is None:
        return None
    selection = await tracking.get_contract_selection(plan["trade_id"])
    for saved in await tracking.list_trade_observations(plan["trade_id"], "exit"):
        saved_quote = _stored_quote(saved)
        executable = saved_quote.get("executable_price")
        zero_value = saved_quote.get("result_treatment") == "zero_value"
        if executable is None or (not saved_quote.get("usable") and not zero_value):
            continue
        saved_at = float(
            saved.get("received_timestamp") or saved.get("observed_at") or 0
        )
        reason = _exit_reason(plan, values, float(executable), saved_at)
        if reason is None:
            continue
        result_values = await _resolved_result_values(
            plan, entry, selection, saved_quote, saved["observation_id"],
            reason, saved_at, rules,
        )
        await tracking.record_trade_result(**result_values)
        chain = await tracking.get_trade_tracking_chain(plan["trade_id"])
        return next(
            (row for row in reversed(chain["results"]) if row["status"] == "resolved"),
            None,
        )
    if plan["instrument_type"] == "option" and selection is not None:
        expiration_close = datetime.combine(
            datetime.strptime(selection["expiration"], "%Y-%m-%d").date(),
            datetime_time(16, 0),
            tzinfo=ZoneInfo("America/New_York"),
        ).timestamp()
        if now >= expiration_close:
            await _record_special_outcome(
                plan, selection, entry, rules,
                status="expired", reason="contract_expired",
                observed_at=now,
            )
            return None
    if plan["instrument_type"] == "option":
        if selection is None:
            await _record_missing(plan, purpose="exit", reason="exact_contract_missing")
            return None
        if callable(provider):
            quotes = await _call_supplied_provider(
                provider, trade_id=plan["trade_id"], purpose="exit",
            )
            quote = quotes[0] if quotes else None
        else:
            quote = await provider.option_contract(
                ticker=plan["ticker"],
                option_type=selection["option_type"],
                strike=tracking.micros_to_dollars(selection["strike_micros"]),
                expiration=selection["expiration"],
                contract_symbol=selection["contract_symbol"],
            )
    else:
        if callable(provider):
            quotes = await _call_supplied_provider(
                provider, trade_id=plan["trade_id"], purpose="exit",
            )
            quote = quotes[0] if quotes else None
        else:
            quote = await provider.share_quote(ticker=plan["ticker"])
    if quote is None:
        missing_id = await _record_missing(
            plan, purpose="exit", reason="required_exit_quote_missing",
            contract_selection_id=(selection["selection_id"] if selection else None),
        )
        if now >= float(values.get("exit_due_at") or 0):
            await _record_special_outcome(
                plan, selection, entry, rules,
                status="cannot_close", reason="required_exit_quote_missing",
                observed_at=now,
                exit_observation_id=missing_id,
            )
        return None
    special_status, special_reason = _special_status_from_quote(
        plan["instrument_type"], quote, rules
    )
    if not special_status and plan["instrument_type"] == "share":
        overnight_gap = _overnight_share_gap(entry, quote, rules)
        if overnight_gap is not None:
            special_status, special_reason = overnight_gap
    if special_status:
        special_result = tracking.build_special_outcome(
            trade_id=plan["trade_id"],
            status=special_status,
            reason=special_reason,
            observed_at=float(quote.get("received_timestamp") or now),
            result_rule_version=rules["result_rule_version"],
        )
        special_result.update(
            outcome_id=plan["outcome_id"],
            contract_selection_id=(selection["selection_id"] if selection else None),
            entry_observation_id=entry["observation_id"],
            is_primary=True,
            fee_rule_version=rules["fee_rule_version"],
        )
        final_plan = _plan_values(plan)
        final_plan.update(
            status="ineligible",
            reason=special_reason,
            classification="ineligible",
        )
        await tracking.write_special_trade_bundle(
            contract_selection=None,
            observation=_special_observation_values(
                plan,
                quote,
                purpose="exit",
                rules=rules,
                contract_selection_id=(
                    selection["selection_id"] if selection else None
                ),
                status_override=special_status,
            ),
            result=special_result,
            plan=final_plan,
        )
        return None
    if plan["instrument_type"] == "option":
        exit_quote = tracking.classify_option_quote(
            quote,
            purpose="exit",
            max_age_seconds=rules["max_quote_age"],
            zero_bid_rule="zero_value",
            result_rule_version=rules["result_rule_version"],
        )
        if quote.get("market_session") != "regular" and not exit_quote["unusable_reason"]:
            exit_quote.update(usable=False, unusable_reason="outside_regular_session")
        if quote.get("is_delayed") and not exit_quote["unusable_reason"]:
            exit_quote.update(usable=False, unusable_reason="delayed")
    else:
        exit_quote = tracking.assess_share_quote(
            quote,
            direction=plan["direction"],
            purpose="exit",
            confirmed_delivery_at=None,
            max_age_seconds=rules["max_quote_age"],
            max_delivery_delay_seconds=rules["max_entry_delay"],
            slippage_bps=rules["share_slippage_bps"],
            result_rule_version=rules["result_rule_version"],
            min_price=rules["min_share_price"],
            max_spread_pct=rules["max_share_spread_pct"],
            min_average_daily_dollar_volume=(
                rules["min_share_average_daily_dollar_volume"]
            ),
            require_normal_halt=True,
        )
    observation_values = _observation_values(
        plan["trade_id"], exit_quote, purpose="exit", rules=rules,
        contract_selection_id=(selection["selection_id"] if selection else None),
    )
    executable = exit_quote.get("executable_price")
    zero_value = exit_quote.get("result_treatment") == "zero_value"
    if executable is None or (not exit_quote.get("usable") and not zero_value):
        await tracking.record_market_observation(**observation_values)
        return None
    executable = float(executable)
    quote_at = float(exit_quote.get("received_timestamp") or now)
    exit_reason = _exit_reason(plan, values, executable, quote_at)
    if exit_reason is None:
        await tracking.record_market_observation(**observation_values)
        return None
    exit_identity = (
        f"{plan['trade_id']}:{exit_quote.get('received_timestamp')}:{executable}"
    )
    exit_observation_id = observation_values.get("observation_id") or (
        f"exit_{hashlib.sha256(exit_identity.encode('utf-8')).hexdigest()}"
    )
    observation_values["observation_id"] = exit_observation_id
    result_values = await _resolved_result_values(
        plan, entry, selection, exit_quote, exit_observation_id,
        exit_reason, quote_at, rules,
    )
    await tracking.write_trade_exit_bundle(
        observation=observation_values, result=result_values,
    )
    chain = await tracking.get_trade_tracking_chain(plan["trade_id"])
    return next(
        (row for row in reversed(chain["results"]) if row["status"] == "resolved"),
        None,
    )


async def collect_due_exits(
    *, quote_provider: Any | None = None, now: float | None = None,
) -> list[dict]:
    """Observe open trades and resolve stops, targets, or the primary horizon."""
    if not exit_collection_enabled():
        return []
    provider = quote_provider or SchwabQuoteProvider()
    resolved = []
    for plan in await _open_trades():
        try:
            result = await _resolve_one_exit(plan, provider, float(now or time.time()))
            if result is not None:
                resolved.append(result)
        except Exception as exc:
            await _record_missing(
                plan, purpose="exit", reason=f"provider_{type(exc).__name__.lower()}"
            )
            log.warning(
                "Batch 2 exit quote failed for $%s (%s)",
                plan["ticker"], type(exc).__name__,
            )
    return resolved


async def _retry_entry(trade_id: str) -> None:
    attempts = int(_setting("entry_retry_attempts", 12))
    delay = float(_setting("entry_retry_seconds", 5))
    for attempt in range(attempts):
        result = await capture_trade_entry(trade_id)
        if result and result.get("usable"):
            return
        plan = await tracking.get_trade_plan(trade_id)
        if plan is None or plan["status"] != "pending":
            return
        rules = await _rules_for_plan(plan)
        delivered_at = float((plan.get("plan") or {}).get("confirmed_delivery_at") or 0)
        if time.time() - delivered_at >= rules["max_entry_delay"]:
            await _append_plan(plan, status="ineligible", reason="entry_window_expired")
            return
        if attempt + 1 < attempts:
            await asyncio.sleep(delay)


async def _recover_pending() -> list[str]:
    await _recover_confirmed_registrations()
    await _expire_pending_entries()
    conn = await db.get_db()
    cursor = await conn.execute(
        """WITH latest_plan AS (
               SELECT p.* FROM measurement_trade_plan_events_v1 p
               WHERE p.rowid=(
                   SELECT p2.rowid FROM measurement_trade_plan_events_v1 p2
                   WHERE p2.trade_id=p.trade_id
                   ORDER BY p2.rowid DESC LIMIT 1
               )
           )
           SELECT p.trade_id
           FROM latest_plan p
           JOIN measurement_trade_rule_sets_v1 r ON r.rule_set_id=p.rule_set_id
           WHERE p.status='pending'
             AND p.confirmed_delivery_at+r.max_delivery_entry_delay_seconds >= ?
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_market_observations_v1 o
                 WHERE o.trade_id=p.trade_id AND o.purpose='entry' AND o.usable=1
             )""",
        (time.time(),),
    )
    return [row["trade_id"] for row in await cursor.fetchall()]


async def _expire_pending_entries() -> None:
    conn = await db.get_db()
    now = time.time()
    cursor = await conn.execute(
        """WITH latest_plan AS (
               SELECT p.* FROM measurement_trade_plan_events_v1 p
               WHERE p.rowid=(
                   SELECT p2.rowid FROM measurement_trade_plan_events_v1 p2
                   WHERE p2.trade_id=p.trade_id
                   ORDER BY p2.rowid DESC LIMIT 1
               )
           )
           SELECT p.* FROM latest_plan p
           JOIN measurement_trade_rule_sets_v1 r ON r.rule_set_id=p.rule_set_id
           WHERE p.status='pending'
             AND p.confirmed_delivery_at+r.max_delivery_entry_delay_seconds<?
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_market_observations_v1 o
                 WHERE o.trade_id=p.trade_id AND o.purpose='entry' AND o.usable=1
             )""",
        (now,),
    )
    for row in await cursor.fetchall():
        plan = tracking._decode_row(row)
        await _record_missing(
            plan, purpose="entry", reason="entry_window_expired"
        )
        await _append_plan(
            plan, status="ineligible", reason="entry_window_expired"
        )


async def _recover_confirmed_registrations() -> list[str]:
    """Promote only frozen registrations whose exact delivery was confirmed."""
    await recover_delivery_journal()
    conn = await db.get_db()
    cursor = await conn.execute(
        """SELECT p.*, d.confirmed_at
           FROM measurement_trade_plan_events_v1 p
           JOIN measurement_delivery_events_v1 d
             ON d.delivery_id=p.delivery_id
            AND d.decision_id=p.decision_id
            AND d.status='confirmed_delivered'
           WHERE p.status='registered'
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_trade_plan_events_v1 p2
                 WHERE p2.trade_id=p.trade_id AND p2.status<>'registered'
             )
           ORDER BY d.confirmed_at""",
    )
    recovered = []
    for row in await cursor.fetchall():
        registered = tracking._decode_row(row)
        frozen = _plan_values(registered)
        status = frozen.pop("intended_status", "pending")
        reason = frozen.pop("intended_reason", "")
        frozen.update(
            event_id=_confirmation_event_id(
                registered["delivery_id"], row["confirmed_at"]
            ),
            status=status,
            reason=reason,
            classification=(
                "research_only" if status == "research_only"
                else "performance_eligible" if status == "eligible"
                else "pending"
            ),
            confirmed_delivery_at=row["confirmed_at"],
            created_at=row["confirmed_at"],
        )
        await tracking.record_trade_plan(**frozen)
        recovered.append(registered["trade_id"])
    return recovered


async def recover_delivery_journal() -> int:
    """Retry durable post-send confirmations until both ledgers are complete."""
    latest_journal: dict[str, dict] = {}
    for event in _journal_events():
        delivery_id = str(event.get("delivery_id") or "")
        if delivery_id:
            latest_journal[delivery_id] = event
    recovered = 0
    for event in latest_journal.values():
        if event.get("event") != "confirmed":
            continue
        try:
            await confirm_delivery_registration(
                delivery_id=event["delivery_id"],
                decision_id=event["decision_id"],
                external_message_id=event["external_message_id"],
                confirmed_delivery_at=float(event["confirmed_delivery_at"]),
                registration=event.get("registration") or None,
            )
            recovered += 1
        except Exception as exc:
            log.warning(
                "Batch 2 delivery-journal replay failed (%s)",
                type(exc).__name__,
            )
    return recovered


async def run(
    stop_event: asyncio.Event | None = None, *, collect_enabled: bool | None = None,
    quote_provider: Any | None = None,
    confirmed_deliveries: list[dict] | None = None,
) -> dict | None:
    """Run post-delivery entry retries and periodic exit observations."""
    if confirmed_deliveries is not None:
        outputs = [item.get("alert_output") for item in confirmed_deliveries]
        if collect_enabled is False:
            return {"alert_outputs": outputs, "trades": []}
        trades = []
        for delivery in confirmed_deliveries:
            registered = await register_confirmed_delivery(**delivery)
            if registered is None:
                continue
            trades.append(registered)
            await capture_trade_entry(
                registered["trade_id"], quote_provider=quote_provider,
            )
        return {"alert_outputs": outputs, "trades": trades}
    if stop_event is None:
        raise ValueError("stop_event is required for the live Batch 2 collector")
    global _entry_queue
    _entry_queue = asyncio.Queue()
    try:
        if quote_collection_enabled():
            for trade_id in await _recover_pending():
                _entry_queue.put_nowait(trade_id)
        next_exit = 0.0
        next_recovery = 0.0
        while not stop_event.is_set():
            now = time.monotonic()
            if collection_enabled() and now >= next_recovery:
                await recover_delivery_journal()
                next_recovery = now + 60.0
            if exit_collection_enabled() and now >= next_exit:
                await collect_due_exits()
                next_exit = now + 60.0
            try:
                trade_id = await asyncio.wait_for(_entry_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            task = asyncio.create_task(_retry_entry(trade_id), name=f"batch2-entry-{trade_id}")
            _entry_tasks.add(task)
            task.add_done_callback(_finish_entry_task)
    finally:
        _entry_queue = None
        for task in list(_entry_tasks):
            task.cancel()
        if _entry_tasks:
            await asyncio.gather(*_entry_tasks, return_exceptions=True)
        _entry_tasks.clear()
