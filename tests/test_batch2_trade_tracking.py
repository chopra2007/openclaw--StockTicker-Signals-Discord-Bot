"""Hostile contract and storage tests for Batch 2 exact trade tracking."""

import sqlite3
import time
import pytest

from consensus_engine import config as cfg, db, measurement
from consensus_engine import trade_tracking as tracking
from scripts.check_batch2_trade_gate import evaluate_gate


@pytest.fixture
async def tracking_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "batch2.db")}
    await db.init_db()
    yield await db.get_db()
    await db.close_db()


async def _count(conn, table):
    cursor = await conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
    return (await cursor.fetchone())["count"]


async def _batch1_links(*, ticker="NVDA", confirmed=True, suffix="a"):
    candidate_id = await measurement.record_candidate(
        candidate_id=f"candidate-{suffix}", ticker=ticker, direction="long",
        analyst="alpha", created_at=1_786_562_900.0,
    )
    decision_id = await measurement.transition_decision(
        event_id=f"decision-event-{suffix}", decision_id=f"decision-{suffix}",
        candidate_id=candidate_id, status="scored", owner_visible_score=81,
        created_at=1_786_562_910.0,
    )
    delivery_id = await measurement.record_delivery(
        event_id=f"delivery-event-{suffix}", delivery_id=f"delivery-{suffix}",
        decision_id=decision_id, attempt_id=f"attempt-{suffix}",
        status="confirmed_delivered" if confirmed else "send_started",
        confirmed_at=1_786_563_000.0 if confirmed else None,
        created_at=1_786_562_990.0,
    )
    outcome_id = await measurement.record_outcome(
        event_id=f"outcome-event-{suffix}", outcome_id=f"outcome-{suffix}",
        decision_id=decision_id, direction="long", horizon="primary",
        status="pending", created_at=1_786_562_990.0,
    )
    return {
        "candidate_id": candidate_id,
        "decision_id": decision_id,
        "delivery_id": delivery_id,
        "outcome_id": outcome_id,
    }


def _rule_set(**overrides):
    value = {
        "rule_set_id": "rules-a",
        "rule_version": "batch2-rules-v1",
        "fee_per_contract_per_transaction": 0.45,
        "max_quote_age_seconds": 30,
        "max_delivery_entry_delay_seconds": 60,
        "liquidity_rule": {
            "min_midpoint": 0.20,
            "max_spread_pct": 20,
            "min_open_interest": 100,
        },
        "exit_rule": {"primary_horizon_seconds": 86_400},
        "share_rule": {"short_requires_borrow_facts": True},
        "created_at": 1_786_562_800.0,
    }
    value.update(overrides)
    return value


def _plan(links, **overrides):
    value = {
        **links,
        "event_id": "plan-event-a",
        "trade_id": "trade-a",
        "rule_set_id": "rules-a",
        "instrument_type": "option",
        "ticker": "NVDA",
        "direction": "long",
        "status": "eligible",
        "classification": "performance_eligible",
        "confirmed_delivery_at": 1_786_563_000.0,
        "primary_horizon_seconds": 86_400,
        "reason": "",
        "scorer_version": "consensus-v1",
        "selection_rule_version": "batch2-selection-v1",
        "quantity": 1,
        "contract_count": 1,
        "entry_rule": "first_usable_post_delivery_ask",
        "exit_rule": "primary_horizon_bid",
        "fee_rule_version": "owner-contract-fee-v1",
        "result_rule_version": "options-result-v1",
        "created_at": 1_786_562_995.0,
    }
    value.update(overrides)
    return value


def _selection(**overrides):
    value = {
        "event_id": "selection-event-a",
        "selection_id": "selection-a",
        "status": "selected",
        "contract": _contract(strategy="single_leg"),
        "selected_at": 1_786_562_950.0,
    }
    value.update(overrides)
    return value


def _observation(**overrides):
    value = {
        "observation_id": "observation-a",
        "contract_selection_id": "selection-a",
        "purpose": "entry",
        "status": "observed",
        "provider_timestamp": 1_786_563_001.0,
        "received_timestamp": 1_786_563_005.0,
        "observed_at": 1_786_563_005.0,
        "quote_age_seconds": 4.0,
        "bid": 2.00,
        "ask": 2.10,
        "underlying_price": 151.25,
        "executable_price": 2.10,
        "selection_to_delivery_seconds": 50.0,
        "delivery_to_quote_seconds": 5.0,
        "midpoint": 2.05,
        "spread": 0.10,
        "spread_pct": 4.878,
        "volume": 120,
        "open_interest": 800,
        "is_delayed": False,
        "halt_status": "not_halted",
        "usable": True,
        "market_session": "regular",
        "quote_source": "structured-test-source",
        "result_rule_version": "options-result-v1",
    }
    value.update(overrides)
    return value


def _contract(**overrides):
    value = {
        "contract_symbol": "NVDA260821C00150000",
        "underlying": "NVDA",
        "option_type": "call",
        "action": "buy_to_open",
        "strategy": "single_leg",
        "leg_count": 1,
        "strike": 150.0,
        "expiration": "2026-08-21",
        "multiplier": 100,
        "quote_source": "structured-test-source",
        "selection_rule_version": "batch2-selection-v1",
        "scorer_version": "consensus-v1",
    }
    value.update(overrides)
    return value


def _quote(**overrides):
    value = {
        "provider_timestamp": 1_786_563_000.0,
        "received_timestamp": 1_786_563_005.0,
        "quote_age_seconds": 5.0,
        "bid": 2.00,
        "ask": 2.10,
        "underlying_price": 151.25,
        "market_session": "regular",
        "quote_source": "structured-test-source",
        "volume": 120,
        "open_interest": 800,
    }
    value.update(overrides)
    return value


def _fee_rule(**overrides):
    value = {
        "version": "owner-contract-fee-v1",
        "per_contract_per_transaction": 0.45,
        "extra_fees": [],
    }
    value.update(overrides)
    return value


def _share_plan(**overrides):
    value = {
        "ticker": "NVDA",
        "direction": "long",
        "entry_time": 1_786_563_000.0,
        "entry_price": 150.00,
        "exit_time": 1_786_649_400.0,
        "exit_price": 153.00,
        "spread_dollars": 0.04,
        "commission_dollars": 0.00,
        "slippage_dollars": 0.06,
        "stop_price": 147.00,
        "target_price": 156.00,
        "path_status": "target_first",
        "halt_status": "not_halted",
        "missing_data_reason": "",
        "quantity": 10,
        "fee_rule_version": "shares-fees-v1",
        "result_rule_version": "shares-result-v1",
    }
    value.update(overrides)
    return value


def test_options_trade_rejects_missing_exact_contract_symbol():
    with pytest.raises(ValueError, match="contract symbol"):
        tracking.validate_option_contract(_contract(contract_symbol=""))


def test_options_trade_persists_complete_contract_identity():
    contract = _contract()

    validated = tracking.validate_option_contract(contract)

    assert validated == contract


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_buy_to_open_call_and_put_are_performance_eligible(option_type):
    result = tracking.assess_option_strategy(
        _contract(option_type=option_type, action="buy_to_open")
    )

    assert result == {"eligible": True, "classification": "performance_eligible"}


@pytest.mark.parametrize(
    "action,strategy",
    [
        ("sell_to_open", "single_leg"),
        ("buy_to_open", "vertical_spread"),
        ("buy_to_open", "multi_leg"),
    ],
)
def test_unsupported_option_strategy_is_research_only(action, strategy):
    result = tracking.assess_option_strategy(
        _contract(action=action, strategy=strategy)
    )

    assert result["eligible"] is False
    assert result["classification"] == "research_only"


def test_unknown_option_strategy_is_research_only():
    contract = _contract()
    contract.pop("strategy")
    contract.pop("leg_count")

    result = tracking.assess_option_strategy(contract)

    assert result["eligible"] is False
    assert result["classification"] == "research_only"
    assert result["reason"] == "unsupported_strategy"


def test_quote_persists_provider_and_receipt_timestamps():
    quote = _quote()

    result = tracking.classify_option_quote(
        quote, purpose="entry", max_age_seconds=60
    )

    assert result["provider_timestamp"] == quote["provider_timestamp"]
    assert result["received_timestamp"] == quote["received_timestamp"]
    assert result["quote_age_seconds"] == 5.0
    assert result["quote_source"] == "structured-test-source"
    assert result["market_session"] == "regular"


def test_quote_status_keeps_stale_reason_visible():
    result = tracking.classify_option_quote(
        _quote(quote_age_seconds=61.0), purpose="entry", max_age_seconds=60
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == "stale"


def test_quote_with_provider_time_after_receipt_is_unusable():
    result = tracking.classify_option_quote(
        _quote(provider_timestamp=200.0, received_timestamp=100.0),
        purpose="entry",
        max_age_seconds=30,
        result_rule_version="options-result-v1",
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == "provider_after_receipt"


def test_quote_status_keeps_crossed_reason_visible():
    result = tracking.classify_option_quote(
        _quote(bid=2.20, ask=2.10), purpose="entry", max_age_seconds=60
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == "crossed"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"market_session": "closed"}, "outside_regular_session"),
        ({"is_delayed": True}, "delayed"),
        ({"provider_timestamp": 1_786_562_999.0}, "pre_delivery"),
        ({"provider_timestamp": 1_786_563_056.0,
          "received_timestamp": 1_786_563_061.0}, "entry_delay_exceeded"),
        ({"bid": 0.05, "ask": 0.15}, "low_midpoint"),
        ({"bid": 1.00, "ask": 1.30}, "wide_spread"),
        ({"open_interest": 99}, "low_open_interest"),
    ],
)
def test_frozen_option_quote_rules_keep_ineligible_reason_visible(changes, reason):
    result = tracking.assess_option_quote(
        _quote(**changes), purpose="entry",
        confirmed_delivery_at=1_786_563_000.0,
        max_age_seconds=30, max_delivery_delay_seconds=60,
        min_midpoint=0.20, max_spread_pct=20, min_open_interest=100,
        result_rule_version="options-result-v1",
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == reason


@pytest.mark.parametrize(
    "missing_side,changes",
    [("bid", {"bid": None}), ("ask", {"ask": None})],
)
def test_quote_status_keeps_missing_side_reason_visible(missing_side, changes):
    result = tracking.classify_option_quote(
        _quote(**changes), purpose="entry", max_age_seconds=60
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == f"missing_{missing_side}"


def test_zero_bid_exit_remains_visible_under_frozen_rule():
    result = tracking.classify_option_quote(
        _quote(bid=0.0),
        purpose="exit",
        max_age_seconds=60,
        zero_bid_rule="zero_value",
        result_rule_version="options-result-v1",
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == "zero_bid"
    assert result["result_treatment"] == "zero_value"
    assert result["executable_price"] == 0.0
    assert result["result_rule_version"] == "options-result-v1"


def test_missing_required_quote_is_counted_as_missing_data():
    result = tracking.missing_quote_observation(
        trade_id="trade-1",
        purpose="exit",
        reason="provider_returned_no_contract",
        observed_at=1_786_563_010.0,
        result_rule_version="options-result-v1",
    )

    assert result["status"] == "missing_data"
    assert result["missing_data_reason"] == "provider_returned_no_contract"
    assert result["observed_at"] == 1_786_563_010.0


def test_one_contract_round_trip_charges_exactly_90_cents():
    result = tracking.calculate_option_result(
        entry_quote=_quote(bid=1.90, ask=2.00),
        exit_quote=_quote(bid=2.50, ask=2.60),
        contract_multiplier=100,
        contract_count=1,
        fee_rule=_fee_rule(),
        result_rule_version="options-result-v1",
    )

    assert result["buy_contract_fee"] == pytest.approx(0.45)
    assert result["sell_contract_fee"] == pytest.approx(0.45)
    assert result["contract_fees_total"] == pytest.approx(0.90)


def test_option_result_applies_multiplier_and_contract_count():
    result = tracking.calculate_option_result(
        entry_quote=_quote(bid=1.90, ask=2.00),
        exit_quote=_quote(bid=2.50, ask=2.60),
        contract_multiplier=100,
        contract_count=2,
        fee_rule=_fee_rule(),
        result_rule_version="options-result-v1",
    )

    assert result["gross_dollars"] == pytest.approx(100.00)
    assert result["contract_fees_total"] == pytest.approx(1.80)
    assert result["net_dollars"] == pytest.approx(98.20)


def test_spread_is_reported_separately_from_formal_fees():
    result = tracking.calculate_option_result(
        entry_quote=_quote(bid=1.90, ask=2.00),
        exit_quote=_quote(bid=2.50, ask=2.60),
        contract_multiplier=100,
        contract_count=1,
        fee_rule=_fee_rule(),
        result_rule_version="options-result-v1",
    )

    assert result["entry_spread_dollars"] == pytest.approx(0.10)
    assert result["exit_spread_dollars"] == pytest.approx(0.10)
    assert result["contract_fees_total"] == pytest.approx(0.90)
    assert result["extra_fees_total"] == pytest.approx(0.00)


def test_extra_fee_requires_a_nonempty_confirmed_charge_name():
    with pytest.raises(ValueError, match="fee name"):
        tracking.calculate_option_result(
            entry_quote=_quote(bid=1.90, ask=2.00),
            exit_quote=_quote(bid=2.50, ask=2.60),
            contract_multiplier=100,
            contract_count=1,
            fee_rule=_fee_rule(extra_fees=[{"amount": 0.02}]),
            result_rule_version="options-result-v1",
        )


def test_stored_option_result_reproduces_without_current_config():
    stored = tracking.calculate_option_result(
        entry_quote=_quote(bid=1.90, ask=2.00),
        exit_quote=_quote(bid=2.50, ask=2.60),
        contract_multiplier=100,
        contract_count=1,
        fee_rule=_fee_rule(),
        result_rule_version="options-result-v1",
    )

    reproduced = tracking.reproduce_option_result(stored)

    assert reproduced["gross_dollars"] == stored["gross_dollars"]
    assert reproduced["contract_fees_total"] == stored["contract_fees_total"]
    assert reproduced["net_dollars"] == stored["net_dollars"]


def test_share_long_is_eligible_with_complete_point_in_time_fields():
    result = tracking.assess_share_eligibility(_share_plan())

    assert result["eligible"] is True
    assert result["classification"] == "performance_eligible"
    assert result["planned_risk_dollars"] == pytest.approx(30.40)


def test_share_short_without_borrow_facts_is_research_only():
    result = tracking.assess_share_eligibility(_share_plan(direction="short"))

    assert result["eligible"] is False
    assert result["classification"] == "research_only"
    assert result["reason"] == "missing_short_borrow_facts"


def test_share_short_with_complete_borrow_facts_is_eligible():
    result = tracking.assess_share_eligibility(
        _share_plan(
            direction="short",
            stop_price=153.00,
            target_price=144.00,
            borrow_available=True,
            borrow_checked_at=1_786_562_990.0,
            borrow_cost_dollars=0.25,
            dividends_dollars=0.00,
            corporate_action_status="none",
        )
    )

    assert result["eligible"] is True
    assert result["classification"] == "performance_eligible"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"bid": 1.90, "ask": 2.00}, "share_price_too_low"),
        ({"bid": 100.00, "ask": 100.60}, "share_spread_too_wide"),
        ({"average_daily_dollar_volume": None}, "missing_average_dollar_volume"),
        ({"average_daily_dollar_volume": 9_999_999}, "low_average_dollar_volume"),
        ({"halt_status": "halted"}, "halt_status_unusable"),
    ],
)
def test_frozen_share_liquidity_rules_keep_reason_visible(changes, reason):
    quote_values = dict(
        bid=100.00,
        ask=100.20,
        average_daily_dollar_volume=20_000_000,
        halt_status="normal",
    )
    quote_values.update(changes)
    quote = _quote(**quote_values)

    result = tracking.assess_share_quote(
        quote,
        direction="long",
        purpose="entry",
        confirmed_delivery_at=1_786_563_000.0,
        max_age_seconds=30,
        max_delivery_delay_seconds=60,
        slippage_bps=10,
        result_rule_version="shares-result-v1",
        min_price=2,
        max_spread_pct=0.5,
        min_average_daily_dollar_volume=10_000_000,
        require_normal_halt=True,
    )

    assert result["usable"] is False
    assert result["unusable_reason"] == reason


@pytest.mark.parametrize(
    "status",
    [
        "adjusted_contract",
        "expired",
        "early_assignment_risk",
        "halted",
        "gap",
        "cannot_close",
    ],
)
def test_versioned_special_outcome_remains_explicit(status):
    result = tracking.build_special_outcome(
        trade_id="trade-1",
        status=status,
        reason=f"test_{status}",
        observed_at=1_786_563_010.0,
        result_rule_version="options-result-v1",
    )

    assert result["status"] == status
    assert result["reason"] == f"test_{status}"
    assert result["result_rule_version"] == "options-result-v1"


@pytest.mark.asyncio
async def test_storage_retries_keep_stable_entity_ids_without_duplicate_facts(tracking_db):
    links = await _batch1_links()
    values = _rule_set()

    first = await tracking.record_trade_rule_set(**values)
    second = await tracking.record_trade_rule_set(**values)

    assert first == second == "rules-a"
    assert await _count(tracking_db, "measurement_trade_rule_sets_v1") == 1

    await tracking.record_trade_plan(**_plan(links))
    await tracking.record_trade_plan(**_plan(links))
    assert await _count(tracking_db, "measurement_trade_plan_events_v1") == 1


@pytest.mark.asyncio
async def test_same_trade_can_have_unique_append_only_plan_event_history(tracking_db):
    links = await _batch1_links()
    await tracking.record_trade_rule_set(**_rule_set())
    await tracking.record_trade_plan(**_plan(links))

    await tracking.record_trade_plan(
        **_plan(
            links,
            event_id="plan-event-b",
            status="research_only",
            classification="research_only",
            reason="liquidity_gate_failed",
            created_at=1_786_563_010.0,
        )
    )

    cursor = await tracking_db.execute(
        "SELECT event_id, trade_id, status FROM measurement_trade_plan_events_v1 "
        "ORDER BY created_at"
    )
    rows = [dict(row) for row in await cursor.fetchall()]
    assert rows == [
        {"event_id": "plan-event-a", "trade_id": "trade-a", "status": "eligible"},
        {"event_id": "plan-event-b", "trade_id": "trade-a", "status": "research_only"},
    ]


@pytest.mark.asyncio
async def test_trade_plan_requires_linked_confirmed_delivery(tracking_db):
    links = await _batch1_links(confirmed=False)
    await tracking.record_trade_rule_set(**_rule_set())

    with pytest.raises(sqlite3.IntegrityError, match="confirmed delivery"):
        await tracking.record_trade_plan(**_plan(links))


@pytest.mark.asyncio
async def test_rule_set_stores_450000_microdollar_contract_fee(tracking_db):
    await tracking.record_trade_rule_set(**_rule_set())

    cursor = await tracking_db.execute(
        "SELECT fee_per_contract_transaction_micros "
        "FROM measurement_trade_rule_sets_v1 WHERE rule_set_id='rules-a'"
    )
    assert (await cursor.fetchone())["fee_per_contract_transaction_micros"] == 450_000


@pytest.mark.asyncio
async def test_trade_plan_has_explicit_frozen_gate_columns(tracking_db):
    cursor = await tracking_db.execute("PRAGMA table_info(measurement_trade_plan_events_v1)")
    columns = {row["name"] for row in await cursor.fetchall()}

    assert {
        "confirmed_delivery_at",
        "primary_horizon_seconds",
        "reason",
        "scorer_version",
        "selection_rule_version",
        "fee_rule_version",
        "result_rule_version",
    } <= columns


@pytest.mark.parametrize(
    "table,id_column",
    [
        ("measurement_trade_rule_sets_v1", "rule_set_id"),
        ("measurement_trade_plan_events_v1", "event_id"),
        ("measurement_contract_selection_events_v1", "event_id"),
        ("measurement_market_observations_v1", "observation_id"),
        ("measurement_trade_result_events_v1", "event_id"),
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
@pytest.mark.asyncio
async def test_batch2_fact_tables_reject_update_and_delete(
    tracking_db, table, id_column, operation
):
    links = await _batch1_links()
    ids = await tracking.write_initial_trade_tracking_bundle(
        rule_set=_rule_set(),
        plan=_plan(links),
        contract_selection=_selection(),
        observation=_observation(),
        result={
            "event_id": "result-event-a",
            "result_id": "result-a",
            "status": "pending",
            "is_primary": True,
            "fee_rule_version": "owner-contract-fee-v1",
            "result_rule_version": "options-result-v1",
            "created_at": 1_786_563_005.0,
        },
    )
    row_ids = {
        "measurement_trade_rule_sets_v1": ids["rule_set_id"],
        "measurement_trade_plan_events_v1": ids["plan_event_id"],
        "measurement_contract_selection_events_v1": ids["selection_event_id"],
        "measurement_market_observations_v1": ids["observation_id"],
        "measurement_trade_result_events_v1": ids["result_event_id"],
    }
    sql = (
        f"UPDATE {table} SET {id_column}={id_column} WHERE {id_column}=?"
        if operation == "UPDATE"
        else f"DELETE FROM {table} WHERE {id_column}=?"
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only table"):
        await tracking_db.execute(sql, (row_ids[table],))


@pytest.mark.asyncio
async def test_result_rejects_contract_or_quote_link_from_another_trade(tracking_db):
    links_a = await _batch1_links(suffix="a")
    links_b = await _batch1_links(ticker="AMD", suffix="b")
    await tracking.record_trade_rule_set(**_rule_set())
    await tracking.record_trade_plan(**_plan(links_a))
    await tracking.record_contract_selection(trade_id="trade-a", **_selection())
    await tracking.record_market_observation(trade_id="trade-a", **_observation())
    await tracking.record_trade_plan(
        **_plan(
            links_b,
            event_id="plan-event-b",
            trade_id="trade-b",
            ticker="AMD",
            created_at=1_786_562_996.0,
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError, match="belong to trade|use result contract",
    ):
        await tracking.record_trade_result(
            event_id="result-event-b",
            result_id="result-b",
            trade_id="trade-b",
            contract_selection_id="selection-a",
            entry_observation_id="observation-a",
            exit_observation_id="observation-a",
            status="resolved",
            is_primary=True,
            fee_rule_version="owner-contract-fee-v1",
            result_rule_version="options-result-v1",
            resolved_at=1_786_563_020.0,
            created_at=1_786_563_020.0,
        )


@pytest.mark.asyncio
async def test_trade_allows_only_one_usable_entry_observation(tracking_db):
    links = await _batch1_links()
    await tracking.write_initial_trade_tracking_bundle(
        rule_set=_rule_set(), plan=_plan(links),
        contract_selection=_selection(), observation=_observation(),
    )

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        await tracking.record_market_observation(
            trade_id="trade-a",
            **_observation(
                observation_id="observation-b",
                provider_timestamp=1_786_563_006.0,
                received_timestamp=1_786_563_010.0,
                observed_at=1_786_563_010.0,
            ),
        )


@pytest.mark.asyncio
async def test_storage_rejects_provider_time_after_receipt(tracking_db):
    links = await _batch1_links(suffix="future-provider")
    await tracking.write_initial_trade_tracking_bundle(
        rule_set=_rule_set(rule_set_id="rules-future-provider"),
        plan=_plan(
            links,
            event_id="plan-future-provider",
            trade_id="trade-future-provider",
            rule_set_id="rules-future-provider",
        ),
        contract_selection=_selection(
            event_id="selection-future-provider",
            selection_id="selection-future-provider",
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        await tracking.record_market_observation(
            trade_id="trade-future-provider",
            **_observation(
                observation_id="observation-future-provider",
                contract_selection_id="selection-future-provider",
                    provider_timestamp=200.0,
                    received_timestamp=100.0,
                    observed_at=100.0,
                    purpose="selection",
                    usable=False,
                ),
            )


@pytest.mark.asyncio
async def test_trade_allows_only_one_resolved_primary_result(tracking_db):
    links = await _batch1_links()
    await tracking.write_initial_trade_tracking_bundle(
        rule_set=_rule_set(), plan=_plan(links), contract_selection=_selection(),
    )
    await tracking.record_market_observation(
        trade_id="trade-a", **_observation(observation_id="entry-a")
    )
    await tracking.record_market_observation(
        trade_id="trade-a",
        **_observation(
            observation_id="exit-a", purpose="exit", usable=True,
            provider_timestamp=1_786_649_400.0,
            received_timestamp=1_786_649_405.0,
            observed_at=1_786_649_405.0,
            executable_price=2.50,
        ),
    )
    common = {
        "trade_id": "trade-a",
        "contract_selection_id": "selection-a",
        "entry_observation_id": "entry-a",
        "exit_observation_id": "exit-a",
        "status": "resolved",
        "is_primary": True,
        "fee_rule_version": "owner-contract-fee-v1",
        "result_rule_version": "options-result-v1",
        "resolved_at": 1_786_649_410.0,
    }
    await tracking.record_trade_result(
        **common, event_id="result-event-a", result_id="result-a",
        created_at=1_786_649_410.0,
    )

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        await tracking.record_trade_result(
            **common, event_id="result-event-b", result_id="result-b",
            created_at=1_786_649_411.0,
        )


@pytest.mark.asyncio
async def test_special_option_result_requires_exact_contract_selection(tracking_db):
    links = await _batch1_links(suffix="special-contract")
    await tracking.record_trade_rule_set(
        **_rule_set(rule_set_id="rules-special-contract")
    )
    await tracking.record_trade_plan(
        **_plan(
            links,
            event_id="plan-special-contract",
            trade_id="trade-special-contract",
            rule_set_id="rules-special-contract",
            status="pending",
            classification="pending",
        )
    )

    with pytest.raises(sqlite3.IntegrityError, match="exact contract"):
        await tracking.record_trade_result(
            event_id="result-special-without-contract",
            result_id="result-special-without-contract",
            trade_id="trade-special-contract",
            outcome_id=links["outcome_id"],
            status="adjusted_contract",
            reason="nonstandard_contract_or_deliverable",
            observed_at=1_786_563_010.0,
            is_primary=True,
            fee_rule_version="owner-contract-fee-v1",
            result_rule_version="options-result-v1",
        )


@pytest.mark.asyncio
async def test_forced_final_write_failure_leaves_no_partial_batch2_bundle(tracking_db):
    links = await _batch1_links()
    await tracking_db.execute(
        """CREATE TRIGGER fail_batch2_final_result
           BEFORE INSERT ON measurement_trade_result_events_v1
           BEGIN SELECT RAISE(FAIL, 'forced Batch 2 result failure'); END"""
    )
    await tracking_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced Batch 2 result failure"):
        await tracking.write_initial_trade_tracking_bundle(
            rule_set=_rule_set(),
            plan=_plan(links),
            contract_selection=_selection(),
            observation=_observation(),
            result={
                "event_id": "result-event-a",
                "result_id": "result-a",
                "status": "pending",
                "is_primary": True,
                "fee_rule_version": "owner-contract-fee-v1",
                "result_rule_version": "options-result-v1",
                "created_at": 1_786_563_005.0,
            },
        )

    for table in (
        "measurement_trade_rule_sets_v1",
        "measurement_trade_plan_events_v1",
        "measurement_contract_selection_events_v1",
        "measurement_market_observations_v1",
        "measurement_trade_result_events_v1",
    ):
        assert await _count(tracking_db, table) == 0, table
    assert await _count(tracking_db, "measurement_delivery_events_v1") == 1


@pytest.mark.asyncio
async def test_gate_requires_linked_usable_timestamped_exit_and_reproduces_share_math(
    tracking_db,
):
    links = await _batch1_links()
    delivered = 1_786_563_000.0
    await tracking.record_trade_rule_set(**_rule_set())
    await tracking.record_trade_plan(
        **_plan(
            links,
            instrument_type="share",
            contract_count=None,
            confirmed_delivery_at=delivered,
            stop_price=147.0,
            target_price=156.0,
            planned_risk_dollars=30.40,
        )
    )
    await tracking.record_market_observation(
        trade_id="trade-a",
        **_observation(
            contract_selection_id=None,
            purpose="entry",
            executable_price=151.0,
        ),
    )
    await tracking_db.execute(
        """INSERT INTO measurement_trade_result_events_v1
           (event_id, result_id, trade_id, status, is_primary,
            outcome_id,
            gross_micros, net_micros, planned_risk_micros,
            fee_rule_version, result_rule_version, resolved_at, created_at,
            result_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "result-event-a", "result-a", "trade-a", "resolved", 1,
            links["outcome_id"],
            3_000_000, 99, 30_400_000,
            "shares-fees-v1", "shares-result-v1",
            delivered + 86_410, delivered + 86_410, "{}",
        ),
    )
    await tracking_db.commit()

    result = evaluate_gate(
        tracking_db._conn,
        delivered - 60,
        max(time.time(), delivered + 172_800),
    )

    assert result["status"] == "WAIT"
    assert result["missing_usable_exit"] == 1
    assert result["share_reproduction_failures"] == 1


@pytest.mark.asyncio
async def test_gate_blocks_overdue_eligible_trade_and_mismatched_linked_prices(
    tracking_db,
):
    delivered = 1_786_563_000.0
    await tracking.record_trade_rule_set(**_rule_set())
    overdue_links = await _batch1_links(suffix="overdue")
    await tracking.record_trade_plan(
        **_plan(
            overdue_links,
            event_id="plan-overdue",
            trade_id="trade-overdue",
            instrument_type="share",
            contract_count=None,
            confirmed_delivery_at=delivered,
            stop_price=147.0,
            target_price=156.0,
            planned_risk_dollars=30.40,
            exit_due_at=delivered + 60,
        )
    )
    await tracking.record_market_observation(
        trade_id="trade-overdue",
        **_observation(
            observation_id="entry-overdue",
            contract_selection_id=None,
            executable_price=151.0,
        ),
    )

    mismatch_links = await _batch1_links(suffix="mismatch")
    await tracking.record_trade_plan(
        **_plan(
            mismatch_links,
            event_id="plan-mismatch",
            trade_id="trade-mismatch",
            instrument_type="share",
            contract_count=None,
            confirmed_delivery_at=delivered,
            stop_price=147.0,
            target_price=156.0,
            planned_risk_dollars=30.40,
            exit_due_at=delivered + 60,
        )
    )
    await tracking.record_market_observation(
        trade_id="trade-mismatch",
        **_observation(
            observation_id="entry-mismatch",
            contract_selection_id=None,
            executable_price=151.0,
        ),
    )
    await tracking.record_market_observation(
        trade_id="trade-mismatch",
        **_observation(
            observation_id="exit-mismatch",
            contract_selection_id=None,
            purpose="exit",
            provider_timestamp=delivered + 70,
            received_timestamp=delivered + 71,
            observed_at=delivered + 71,
            executable_price=153.0,
        ),
    )
    await tracking.record_trade_result(
        event_id="result-mismatch",
        result_id="result-mismatch",
        trade_id="trade-mismatch",
        outcome_id=mismatch_links["outcome_id"],
        entry_observation_id="entry-mismatch",
        exit_observation_id="exit-mismatch",
        status="resolved",
        is_primary=True,
        entry_price=999.0,
        exit_price=998.0,
        gross_dollars=-1.0,
        net_dollars=-1.0,
        planned_risk_dollars=30.40,
        spread_dollars=0.20,
        commission_dollars=0.0,
        slippage_dollars=0.0,
        fee_rule_version="shares-fees-v1",
        result_rule_version="shares-result-v1",
        resolved_at=delivered + 72,
        created_at=delivered + 72,
    )

    result = evaluate_gate(
        tracking_db._conn,
        delivered - 60,
        max(time.time(), delivered + 172_800),
    )

    assert result["status"] == "WAIT"
    assert result["overdue_unresolved"] >= 1
    assert result["result_observation_errors"] >= 1


@pytest.mark.asyncio
async def test_gate_rejects_result_time_before_its_linked_exit(tracking_db):
    delivered = 1_786_563_000.0
    links = await _batch1_links(suffix="result-time")
    await tracking.record_trade_rule_set(**_rule_set(rule_set_id="rules-result-time"))
    await tracking.record_trade_plan(
        **_plan(
            links,
            event_id="plan-result-time",
            trade_id="trade-result-time",
            rule_set_id="rules-result-time",
            instrument_type="share",
            contract_count=None,
            confirmed_delivery_at=delivered,
            stop_price=147.0,
            target_price=156.0,
            planned_risk_dollars=30.40,
            exit_due_at=delivered + 60,
        )
    )
    await tracking.record_market_observation(
        trade_id="trade-result-time",
        **_observation(
            observation_id="entry-result-time",
            contract_selection_id=None,
            provider_timestamp=delivered + 1,
            received_timestamp=delivered + 2,
            observed_at=delivered + 2,
            executable_price=151.0,
        ),
    )
    await tracking.record_market_observation(
        trade_id="trade-result-time",
        **_observation(
            observation_id="exit-result-time",
            contract_selection_id=None,
            purpose="exit",
            provider_timestamp=delivered + 69,
            received_timestamp=delivered + 70,
            observed_at=delivered + 70,
            executable_price=153.0,
        ),
    )
    await tracking.record_trade_result(
        event_id="result-event-result-time",
        result_id="result-result-time",
        trade_id="trade-result-time",
        outcome_id=links["outcome_id"],
        entry_observation_id="entry-result-time",
        exit_observation_id="exit-result-time",
        status="resolved",
        is_primary=True,
        entry_price=151.0,
        exit_price=153.0,
        gross_dollars=2.0,
        net_dollars=2.0,
        planned_risk_dollars=30.40,
        spread_dollars=0.20,
        commission_dollars=0.0,
        slippage_dollars=0.0,
        fee_rule_version="shares-fees-v1",
        result_rule_version="shares-result-v1",
        resolved_at=delivered + 60,
        created_at=delivered + 60,
    )

    result = evaluate_gate(
        tracking_db._conn,
        delivered - 60,
        max(time.time(), delivered + 172_800),
    )

    assert result["status"] == "WAIT"
    assert result["result_observation_errors"] >= 1
