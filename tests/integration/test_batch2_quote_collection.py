"""Hostile integration tests for Batch 2 shadow quote collection."""

import asyncio
import sqlite3
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from consensus_engine import config as cfg, db, measurement, trade_collector
from consensus_engine import trade_tracking as tracking
from consensus_engine.models import Conviction, Direction, ParsedTweet, TweetType
from scripts.check_batch2_trade_gate import evaluate_gate


@pytest.fixture
async def collector_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "collector.db")}
    cfg._config["measurement"] = {
        "batch1": {"collect_enabled": True, "reader_enabled": False},
        "batch2": {
            "collect_enabled": True,
            "collect_quotes_enabled": True,
            "reader_enabled": False,
        },
    }
    await db.init_db()
    yield await db.get_db()
    await db.close_db()


async def _count(conn, table):
    cursor = await conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
    return (await cursor.fetchone())["count"]


async def _links(*, direction="long", suffix="a", confirmed=True):
    candidate_id = await measurement.record_candidate(
        candidate_id=f"candidate-{suffix}", ticker="NVDA", direction=direction,
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
        decision_id=decision_id, direction=direction, horizon="primary",
        status="pending", created_at=1_786_562_990.0,
    )
    return {
        "candidate_id": candidate_id,
        "decision_id": decision_id,
        "delivery_id": delivery_id,
        "outcome_id": outcome_id,
    }


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


def _quote(provider_at, received_at, **overrides):
    value = {
        "provider_timestamp": provider_at,
        "received_timestamp": received_at,
        "bid": 2.00,
        "ask": 2.10,
        "underlying_price": 151.25,
        "market_session": "regular",
        "quote_source": "structured-test-source",
        "volume": 120,
        "open_interest": 800,
        "is_delayed": False,
    }
    value.update(overrides)
    return value


def _rules():
    return {
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


async def _register(alert_output="unchanged visible alert"):
    links = await _links()
    return await trade_collector.register_confirmed_delivery(
        **links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        contract=_contract(),
        selection_quote=_quote(1_786_562_950.0, 1_786_562_955.0),
        rule_set=_rules(),
        primary_horizon_seconds=86_400,
        alert_output=alert_output,
    )


@pytest.mark.asyncio
async def test_pre_delivery_selection_quote_is_not_an_entry(collector_db):
    registered = await _register()

    observations = await tracking.list_trade_observations(registered["trade_id"])

    assert [row["purpose"] for row in observations] == ["selection"]
    assert await tracking.get_first_usable_observation(
        registered["trade_id"], "entry"
    ) is None


@pytest.mark.asyncio
async def test_first_usable_post_delivery_quote_becomes_entry(collector_db):
    registered = await _register()
    provider = AsyncMock(
        return_value=[
            _quote(1_786_562_999.0, 1_786_563_001.0),
            _quote(1_786_563_001.0, 1_786_563_040.0),
            _quote(1_786_563_004.0, 1_786_563_005.0),
        ]
    )

    entry = await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=provider
    )

    assert entry["provider_timestamp"] == 1_786_563_004.0
    assert entry["received_timestamp"] == 1_786_563_005.0
    assert entry["executable_price_micros"] == 2_100_000
    assert entry["usable"] == 1


@pytest.mark.asyncio
async def test_later_quote_cannot_overwrite_frozen_entry(collector_db):
    registered = await _register()
    first_provider = AsyncMock(
        return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
    )
    later_provider = AsyncMock(
        return_value=[_quote(1_786_563_009.0, 1_786_563_010.0, ask=2.50)]
    )
    first = await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=first_provider
    )

    again = await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=later_provider
    )

    assert again["observation_id"] == first["observation_id"]
    stored = await tracking.get_first_usable_observation(
        registered["trade_id"], "entry"
    )
    assert stored["executable_price_micros"] == 2_100_000


@pytest.mark.asyncio
async def test_restart_after_entry_write_finishes_pending_result(collector_db):
    registered = await _register()
    await tracking.record_market_observation(
        trade_id=registered["trade_id"],
        contract_selection_id=registered["selection_id"],
        purpose="entry",
        status="observed",
        provider_timestamp=1_786_563_004.0,
        received_timestamp=1_786_563_005.0,
        observed_at=1_786_563_005.0,
        quote_age_seconds=1.0,
        bid=2.00,
        ask=2.10,
        executable_price=2.10,
        usable=True,
        market_session="regular",
        quote_source="structured-test-source",
        result_rule_version="options-result-v1",
    )
    provider = AsyncMock(return_value=[])

    entry = await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=provider,
    )

    provider.assert_not_awaited()
    assert entry["executable_price_micros"] == 2_100_000
    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    assert chain["plan"]["status"] == "eligible"
    assert [row["status"] for row in chain["results"]] == ["pending"]
    assert chain["results"][0]["outcome_id"] == "outcome-a"


@pytest.mark.asyncio
async def test_selection_delivery_and_entry_delays_are_saved(collector_db):
    registered = await _register()
    provider = AsyncMock(
        return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
    )

    entry = await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=provider
    )

    assert entry["selection_to_delivery_seconds"] == pytest.approx(50.0)
    assert entry["delivery_to_quote_seconds"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_collect_due_exits_links_exit_and_resolves_primary_result(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    plan = await tracking.get_trade_plan(registered["trade_id"])
    await trade_collector._append_plan(
        plan,
        status="eligible",
        stop_price=1.575,
        target_price=3.15,
        planned_risk_dollars=61.90,
        exit_due_at=1_786_649_405.0,
    )
    provider = AsyncMock(
        return_value=[_quote(1_786_649_400.0, 1_786_649_405.0, bid=2.50, ask=2.60)]
    )

    results = await trade_collector.collect_due_exits(
        now=1_786_649_410.0, quote_provider=provider
    )

    assert len(results) == 1
    assert results[0]["trade_id"] == registered["trade_id"]
    assert results[0]["status"] == "resolved"
    assert results[0]["is_primary"] == 1


@pytest.mark.asyncio
async def test_quote_collection_off_calls_no_provider_and_writes_no_batch2_rows(
    collector_db,
):
    provider = AsyncMock(return_value=[])

    result = await trade_collector.run(
        collect_enabled=False,
        quote_provider=provider,
        confirmed_deliveries=[{
            "ticker": "NVDA",
            "alert_output": "unchanged visible alert",
        }],
    )

    provider.assert_not_awaited()
    assert result["alert_outputs"] == ["unchanged visible alert"]
    for table in (
        "measurement_trade_rule_sets_v1",
        "measurement_trade_plan_events_v1",
        "measurement_contract_selection_events_v1",
        "measurement_market_observations_v1",
        "measurement_trade_result_events_v1",
    ):
        assert await _count(collector_db, table) == 0, table


@pytest.mark.asyncio
async def test_collection_off_does_not_replay_delivery_journal(collector_db):
    cfg._config["measurement"]["batch2"]["collect_enabled"] = False
    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0)
        stop.set()

    stopper = asyncio.create_task(_stop_soon())
    with patch.object(
        trade_collector, "recover_delivery_journal", new_callable=AsyncMock,
    ) as recover:
        await trade_collector.run(stop)
    await stopper

    recover.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_collection_on_writes_shadow_facts_without_changing_alert_output(
    collector_db,
):
    alert_output = "unchanged visible alert"
    links = await _links()
    delivery = {
        **links,
        "confirmed_delivery_at": 1_786_563_000.0,
        "ticker": "NVDA",
        "direction": "long",
        "contract": _contract(),
        "selection_quote": _quote(1_786_562_950.0, 1_786_562_955.0),
        "rule_set": _rules(),
        "primary_horizon_seconds": 86_400,
        "alert_output": alert_output,
    }
    provider = AsyncMock(
        return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
    )

    result = await trade_collector.run(
        collect_enabled=True,
        quote_provider=provider,
        confirmed_deliveries=[delivery],
    )

    assert result["alert_outputs"] == [alert_output]
    assert await _count(collector_db, "measurement_trade_plan_events_v1") == 2
    plan = await tracking.get_trade_plan(result["trades"][0]["trade_id"])
    assert plan["status"] == "eligible"
    assert await _count(collector_db, "measurement_contract_selection_events_v1") == 1
    assert await _count(collector_db, "measurement_market_observations_v1") == 2


@pytest.mark.asyncio
async def test_buy_to_open_put_uses_long_premium_stop_and_target_direction(collector_db):
    put_plan = {
        "instrument_type": "option",
        "direction": "short",
        "stop_price_micros": tracking.dollars_to_micros(1.575),
        "target_price_micros": tracking.dollars_to_micros(3.15),
    }
    before_horizon = {"exit_due_at": 1_786_649_405.0}

    assert trade_collector._exit_reason(
        put_plan, before_horizon, 3.20, 1_786_563_011.0
    ) == "target"
    assert trade_collector._exit_reason(
        put_plan, before_horizon, 1.50, 1_786_563_011.0
    ) == "stop"


def test_live_option_classification_requires_known_single_leg_strategy():
    base = {
        "present": True,
        "strike": 150.0,
        "expiry": "2026-08-21",
        "option_type": "call",
        "action": "buy_to_open",
    }

    assert trade_collector._initial_classification("long", base) == (
        "research_only", "unsupported_or_unknown_strategy",
    )
    assert trade_collector._initial_classification(
        "long", {**base, "strategy": "vertical_spread", "leg_count": 2},
    ) == ("research_only", "unsupported_or_unknown_strategy")
    assert trade_collector._initial_classification(
        "long", {**base, "strategy": "single_leg", "leg_count": 1},
    ) == ("pending", "")


def test_overnight_gap_requires_quote_after_entry():
    entry = {
        "provider_timestamp": 200_000.0,
        "observation": {"provider_timestamp": 200_000.0},
    }
    older_quote = {
        "provider_timestamp": 100_000.0,
        "open_price": 105.0,
        "previous_close": 100.0,
    }

    assert trade_collector._overnight_share_gap(
        entry, older_quote, {"share_gap_special_pct": 2},
    ) is None


@pytest.mark.asyncio
async def test_live_schwab_share_entry_is_research_only_without_exact_minute_vwap(
    collector_db,
):
    links = await _links(suffix="share-vwap")
    registered = await trade_collector.register_confirmed_delivery(
        **links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        _queue_entry=False,
    )

    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=trade_collector.SchwabQuoteProvider(),
    )

    plan = await tracking.get_trade_plan(registered["trade_id"])
    assert plan["status"] == "research_only"
    assert plan["reason"] == "first_complete_minute_vwap_unavailable_current_source"
    observations = await tracking.list_trade_observations(registered["trade_id"])
    assert observations[-1]["missing_data_reason"] == plan["reason"]


@pytest.mark.asyncio
async def test_schwab_share_quote_does_not_use_trade_time_as_quote_time():
    provider = trade_collector.SchwabQuoteProvider()
    quote = {
        "bid": 150.0,
        "ask": 150.1,
        "c": 150.05,
        "t": 1_787_000_000,
        "quote_time": 0,
    }
    with patch.object(
        trade_collector.schwab_client, "get_quote", return_value=quote,
    ), patch.object(
        trade_collector.schwab_client, "get_price_history", return_value=None,
    ):
        result = await provider.share_quote(ticker="NVDA")

    assert result["provider_timestamp"] is None


@pytest.mark.asyncio
async def test_restart_promotes_only_frozen_registration_and_keeps_unregistered_missing(
    collector_db,
):
    registered_links = await _links(direction="short", confirmed=False, suffix="registered")
    registration = await trade_collector.prepare_delivery_registration(
        **registered_links,
        ticker="NVDA",
        direction="short",
        options={
            "present": True,
            "strike": 150.0,
            "expiry": "2030-08-21",
            "option_type": "put",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        primary_horizon_seconds=86_400,
    )
    frozen = await tracking.get_trade_plan(registration["trade_id"])
    assert frozen["status"] == "registered"
    assert frozen["instrument_type"] == "option"
    assert frozen["plan"]["options"]["option_type"] == "put"
    assert frozen["plan"]["options"]["action"] == "buy_to_open"
    confirmed_at = float(frozen["created_at"]) + 1.0
    await measurement.record_delivery(
        event_id="delivery-confirmed-registered",
        delivery_id=registered_links["delivery_id"],
        decision_id=registered_links["decision_id"],
        attempt_id=registered_links["delivery_id"],
        status="confirmed_delivered",
        confirmed_at=confirmed_at,
        external_message_id="message-test",
        created_at=confirmed_at,
    )
    unregistered_links = await _links(suffix="unregistered")

    recovered = await trade_collector._recover_confirmed_registrations()

    promoted = await tracking.get_trade_plan(registration["trade_id"])
    assert registration["trade_id"] in recovered
    assert promoted["status"] == "pending"
    assert promoted["instrument_type"] == "option"
    assert promoted["plan"]["options"]["option_type"] == "put"
    cursor = await collector_db.execute(
        "SELECT COUNT(*) AS count FROM measurement_trade_plan_events_v1 "
        "WHERE delivery_id=?",
        (unregistered_links["delivery_id"],),
    )
    assert (await cursor.fetchone())["count"] == 0
    gate = evaluate_gate(
        collector_db._conn,
        1_786_562_900.0,
        max(time.time(), confirmed_at + 172_800.0),
    )
    assert gate["missing_plan"] == 1


@pytest.mark.asyncio
async def test_atomic_confirm_failure_leaves_no_confirmed_delivery_or_plan(collector_db):
    links = await _links(direction="short", confirmed=False)
    registration = await trade_collector.prepare_delivery_registration(
        **links,
        ticker="NVDA",
        direction="short",
        options={
            "present": True,
            "strike": 150.0,
            "expiry": "2030-08-21",
            "option_type": "put",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        primary_horizon_seconds=86_400,
    )
    await collector_db.execute(
        """CREATE TRIGGER fail_batch2_confirmed_plan
           BEFORE INSERT ON measurement_trade_plan_events_v1
           WHEN NEW.status <> 'registered'
           BEGIN SELECT RAISE(FAIL, 'forced confirmed plan failure'); END"""
    )
    await collector_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced confirmed plan failure"):
        await trade_collector.confirm_delivery_registration(
            delivery_id=links["delivery_id"],
            decision_id=links["decision_id"],
            external_message_id="message-test",
            confirmed_delivery_at=1_786_563_000.0,
        )

    cursor = await collector_db.execute(
        "SELECT COUNT(*) AS count FROM measurement_delivery_events_v1 "
        "WHERE delivery_id=? AND status='confirmed_delivered'",
        (links["delivery_id"],),
    )
    assert (await cursor.fetchone())["count"] == 0
    cursor = await collector_db.execute(
        "SELECT COUNT(*) AS count FROM measurement_trade_plan_events_v1 "
        "WHERE trade_id=? AND status<>'registered'",
        (registration["trade_id"],),
    )
    assert (await cursor.fetchone())["count"] == 0


@pytest.mark.asyncio
async def test_restart_resolves_from_earliest_stored_qualifying_exit(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    common = {
        "trade_id": registered["trade_id"],
        "contract_selection_id": registered["selection_id"],
        "purpose": "exit",
        "status": "observed",
        "quote_age_seconds": 1.0,
        "bid": 3.20,
        "ask": 3.30,
        "underlying_price": 151.25,
        "executable_price": 3.20,
        "usable": True,
        "market_session": "regular",
        "quote_source": "structured-test-source",
        "result_rule_version": "options-result-v1",
    }
    await tracking.record_market_observation(
        **common,
        observation_id="exit-later",
        provider_timestamp=1_786_563_019.0,
        received_timestamp=1_786_563_020.0,
        observed_at=1_786_563_020.0,
    )
    await tracking.record_market_observation(
        **common,
        observation_id="exit-earliest",
        provider_timestamp=1_786_563_009.0,
        received_timestamp=1_786_563_010.0,
        observed_at=1_786_563_010.0,
    )
    provider = AsyncMock(return_value=[])

    results = await trade_collector.collect_due_exits(
        now=1_786_563_021.0, quote_provider=provider
    )

    provider.assert_not_awaited()
    assert len(results) == 1
    assert results[0]["exit_observation_id"] == "exit-earliest"


@pytest.mark.asyncio
async def test_live_collector_persists_versioned_special_outcome(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    provider = AsyncMock(
        return_value=[
            _quote(
                1_786_649_400.0,
                1_786_649_405.0,
                bid=None,
                ask=None,
                special_outcome_status="adjusted_contract",
                special_outcome_reason="provider_reports_nonstandard_deliverable",
            )
        ]
    )

    await trade_collector.collect_due_exits(
        now=1_786_649_410.0, quote_provider=provider
    )

    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    special = [row for row in chain["results"] if row["status"] == "adjusted_contract"]
    assert len(special) == 1
    assert special[0]["result_rule_version"] == chain["plan"]["result_rule_version"]
    assert special[0]["result_rule_version"]
    assert special[0]["result"]["reason"] == "provider_reports_nonstandard_deliverable"
    assert special[0]["exit_observation_id"]
    evidence = next(
        row for row in chain["observations"]
        if row["observation_id"] == special[0]["exit_observation_id"]
    )
    assert evidence["contract_selection_id"] == special[0]["contract_selection_id"]


@pytest.mark.asyncio
async def test_adjusted_option_outcome_keeps_exact_contract_identity(collector_db):
    links = await _links(suffix="adjusted-entry")
    registered = await trade_collector.register_confirmed_delivery(
        **links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        options={
            "present": True,
            "strike": 150.0,
            "expiry": "2026-08-21",
            "option_type": "call",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        _queue_entry=False,
    )

    class AdjustedProvider:
        option_contract = AsyncMock(return_value=_quote(
            1_786_563_004.0,
            1_786_563_005.0,
            contract_symbol="NVDA260821C00150000",
            underlying="NVDA",
            option_type="call",
            strike=150.0,
            expiration="2026-08-21",
            multiplier=100,
            special_outcome_status="adjusted_contract",
            special_outcome_reason="nonstandard_contract_or_deliverable",
        ))

    await trade_collector.capture_trade_entry(
        registered["trade_id"], quote_provider=AdjustedProvider(),
    )

    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    assert len(chain["contracts"]) == 1
    special = [row for row in chain["results"] if row["status"] == "adjusted_contract"]
    assert len(special) == 1
    assert (
        special[0]["contract_selection_id"]
        == chain["contracts"][0]["selection_id"]
    )
    evidence = next(
        row for row in chain["observations"]
        if row["observation_id"] == special[0]["entry_observation_id"]
    )
    assert evidence["contract_selection_id"] == special[0]["contract_selection_id"]


@pytest.mark.asyncio
async def test_live_option_entry_bundle_rolls_back_all_new_entry_facts(collector_db):
    links = await _links(suffix="entry-atomic")
    registered = await trade_collector.register_confirmed_delivery(
        **links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        options={
            "present": True,
            "strike": 150.0,
            "expiry": "2026-08-21",
            "option_type": "call",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        _queue_entry=False,
    )
    quote = _quote(
        1_786_563_004.0,
        1_786_563_005.0,
        contract_symbol="NVDA260821C00150000",
        underlying="NVDA",
        option_type="call",
        strike=150.0,
        expiration="2026-08-21",
        multiplier=100,
        quote_source="schwab",
    )

    class Provider:
        option_contract = AsyncMock(return_value=quote)

    await collector_db.execute(
        """CREATE TRIGGER fail_atomic_live_entry_result
           BEFORE INSERT ON measurement_trade_result_events_v1
           WHEN NEW.status='pending'
           BEGIN SELECT RAISE(FAIL, 'forced live entry result failure'); END"""
    )
    await collector_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced live entry result failure"):
        await trade_collector.capture_trade_entry(
            registered["trade_id"], quote_provider=Provider(),
        )

    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    assert chain["contracts"] == []
    assert chain["observations"] == []
    assert chain["results"] == []
    assert chain["plan"]["status"] == "pending"


@pytest.mark.asyncio
async def test_batch2_registration_failure_does_not_suppress_visible_tweet_send(
    collector_db,
):
    from consensus_engine import main as main_mod

    tweet = ParsedTweet(
        tweet_url="https://example.test/tweet/batch2-prewrite",
        analyst="testanalyst",
        raw_text="$NVDA long setup",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA long setup",
    )

    def _close_background(coro, **_kwargs):
        coro.close()
        return MagicMock()

    with patch.object(main_mod, "parse_tweet", new_callable=AsyncMock, return_value=tweet), \
         patch.object(main_mod, "validate_ticker_market_cap", new_callable=AsyncMock, return_value=True), \
         patch.object(main_mod, "_passes_quality_gate", return_value=True), \
         patch.object(main_mod.db, "check_alert_cooldown", new_callable=AsyncMock, return_value=True), \
         patch.object(main_mod, "_fetch_price", new_callable=AsyncMock, return_value=151.0), \
         patch.object(main_mod.trade_collector, "prepare_delivery_registration", new_callable=AsyncMock, side_effect=sqlite3.IntegrityError("forced Batch 2 pre-write failure")) as prepare, \
         patch.object(main_mod.trade_collector, "confirm_delivery_registration", new_callable=AsyncMock, side_effect=sqlite3.IntegrityError("forced Batch 2 confirmation failure")) as confirm, \
         patch.object(main_mod, "send_instant_ping", new_callable=AsyncMock, return_value="visible-message") as send, \
         patch.object(main_mod.asyncio, "create_task", side_effect=_close_background):
        await main_mod.process_tweet({
            "url": tweet.tweet_url,
            "analyst": tweet.analyst,
            "text": tweet.raw_text,
        })

    send.assert_awaited_once()
    prepare.assert_not_awaited()
    assert confirm.await_count == 3
    message = await db.get_alert_message(1)
    assert message["instant_msg_id"] == "visible-message"
    cursor = await collector_db.execute(
        "SELECT COUNT(*) AS count FROM measurement_delivery_events_v1 "
        "WHERE status='confirmed_delivered'",
    )
    assert (await cursor.fetchone())["count"] == 1


@pytest.mark.asyncio
async def test_post_send_confirmation_journal_replays_after_restart(collector_db):
    links = await _links(direction="short", confirmed=False)
    registration = await trade_collector.prepare_delivery_registration(
        **links,
        ticker="NVDA",
        direction="short",
        options={
            "present": True,
            "strike": 150.0,
            "expiry": "2030-08-21",
            "option_type": "put",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        primary_horizon_seconds=86_400,
    )
    await collector_db.execute(
        """CREATE TRIGGER fail_first_confirmation
           BEFORE INSERT ON measurement_trade_plan_events_v1
           WHEN NEW.status <> 'registered'
           BEGIN SELECT RAISE(FAIL, 'simulated crash after visible send'); END"""
    )
    await collector_db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="simulated crash"):
        await trade_collector.confirm_delivery_registration(
            delivery_id=links["delivery_id"],
            decision_id=links["decision_id"],
            external_message_id="visible-message",
            confirmed_delivery_at=time.time() + 1,
        )
    await collector_db.execute("DROP TRIGGER fail_first_confirmation")
    await collector_db.commit()

    await trade_collector._recover_confirmed_registrations()

    plan = await tracking.get_trade_plan(registration["trade_id"])
    assert plan["status"] == "pending"
    cursor = await collector_db.execute(
        "SELECT external_message_id FROM measurement_delivery_events_v1 "
        "WHERE delivery_id=? AND status='confirmed_delivered'",
        (links["delivery_id"],),
    )
    assert (await cursor.fetchone())["external_message_id"] == "visible-message"


@pytest.mark.asyncio
async def test_first_confirmation_journal_failure_is_recoverable_after_restart(
    collector_db,
):
    links = await _links(direction="short", confirmed=False, suffix="journal-first")
    registration = {
        **links,
        "ticker": "NVDA",
        "direction": "short",
        "options": {
            "present": True,
            "strike": 150.0,
            "expiry": "2030-08-21",
            "option_type": "put",
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
        },
        "primary_horizon_seconds": 86_400,
    }
    await collector_db.execute(
        """CREATE TRIGGER fail_confirmation_until_restart
           BEFORE INSERT ON measurement_trade_plan_events_v1
           WHEN NEW.status <> 'registered'
           BEGIN SELECT RAISE(FAIL, 'simulated post-send crash'); END"""
    )
    await collector_db.commit()
    real_append = trade_collector._journal_append
    calls = 0

    def fail_first_append(event):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated first journal failure")
        real_append(event)

    confirmed_at = 1_786_563_000.0
    with patch.object(trade_collector, "_journal_append", side_effect=fail_first_append):
        for _attempt in range(2):
            with pytest.raises(sqlite3.IntegrityError, match="simulated post-send crash"):
                await trade_collector.confirm_delivery_registration(
                    delivery_id=links["delivery_id"],
                    decision_id=links["decision_id"],
                    external_message_id="visible-message",
                    confirmed_delivery_at=confirmed_at,
                    registration=registration,
                )
    await collector_db.execute("DROP TRIGGER fail_confirmation_until_restart")
    await collector_db.commit()
    cfg._config["measurement"]["batch2"].update({
        "rule_version": "changed-after-visible-send",
        "result_rule_version": "changed-result-version",
        "max_quote_age_seconds": 999,
        "option_stop_loss_pct": 90,
        "option_target_gain_pct": 900,
        "share_stop_loss_pct": 91,
        "share_target_gain_pct": 901,
        "share_slippage_bps": 999,
    })

    await trade_collector.recover_delivery_journal()

    trade_id = tracking.build_trade_id(
        candidate_id=links["candidate_id"],
        instrument_type="option",
        direction="short",
        rule_version="batch2-v1",
    )
    plan = await tracking.get_trade_plan(trade_id)
    assert plan["status"] == "pending"
    assert plan["plan"]["options"]["option_type"] == "put"
    assert plan["plan"]["frozen_rules"]["rule_version"] == "batch2-v1"
    assert plan["result_rule_version"] == "batch2-result-v1"
    rule_set = await tracking.get_trade_rule_set(plan["rule_set_id"])
    assert rule_set["rule_version"] == "batch2-v1"
    assert rule_set["max_quote_age_seconds"] == 30
    frozen = await trade_collector._rules_for_plan(plan)
    assert frozen["option_stop_loss_pct"] == 25
    assert frozen["option_target_gain_pct"] == 50
    assert frozen["share_stop_loss_pct"] == 2
    assert frozen["share_target_gain_pct"] == 4
    assert frozen["share_slippage_bps"] == 10
    cursor = await collector_db.execute(
        "SELECT external_message_id FROM measurement_delivery_events_v1 "
        "WHERE delivery_id=? AND status='confirmed_delivered'",
        (links["delivery_id"],),
    )
    assert (await cursor.fetchone())["external_message_id"] == "visible-message"


@pytest.mark.asyncio
async def test_saved_pre_horizon_exit_is_not_promoted_after_late_restart(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    plan = await tracking.get_trade_plan(registered["trade_id"])
    await trade_collector._append_plan(
        plan,
        status="eligible",
        stop_price=1.575,
        target_price=3.15,
        planned_risk_dollars=61.90,
        exit_due_at=1_786_649_405.0,
    )
    await tracking.record_market_observation(
        trade_id=registered["trade_id"],
        contract_selection_id=registered["selection_id"],
        observation_id="pre-horizon-exit",
        purpose="exit",
        status="observed",
        provider_timestamp=1_786_563_009.0,
        received_timestamp=1_786_563_010.0,
        observed_at=1_786_563_010.0,
        quote_age_seconds=1.0,
        bid=2.20,
        ask=2.30,
        executable_price=2.20,
        usable=True,
        market_session="regular",
        quote_source="structured-test-source",
        result_rule_version="options-result-v1",
    )

    await trade_collector.collect_due_exits(
        now=1_786_649_410.0, quote_provider=AsyncMock(return_value=[])
    )

    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    assert not any(
        row["status"] == "resolved"
        and row["exit_observation_id"] == "pre-horizon-exit"
        for row in chain["results"]
    )


@pytest.mark.asyncio
async def test_fresh_result_time_equals_linked_exit_quote_time(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    plan = await tracking.get_trade_plan(registered["trade_id"])
    quote_received_at = 1_786_563_020.0

    result = await trade_collector._resolve_one_exit(
        plan,
        AsyncMock(return_value=[_quote(
            1_786_563_019.0, quote_received_at, bid=3.20, ask=3.30,
        )]),
        1_786_563_010.0,
    )

    assert result["resolved_at"] == quote_received_at
    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    exit_row = next(
        row for row in chain["observations"]
        if row["observation_id"] == result["exit_observation_id"]
    )
    assert exit_row["received_timestamp"] == result["resolved_at"]


@pytest.mark.asyncio
async def test_saved_qualifying_exit_wins_before_expiry_status(collector_db):
    registered = await _register()
    await trade_collector.capture_trade_entry(
        registered["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    await tracking.record_market_observation(
        trade_id=registered["trade_id"],
        contract_selection_id=registered["selection_id"],
        observation_id="qualifying-before-expiry",
        purpose="exit",
        status="observed",
        provider_timestamp=1_786_563_009.0,
        received_timestamp=1_786_563_010.0,
        observed_at=1_786_563_010.0,
        quote_age_seconds=1.0,
        bid=3.20,
        ask=3.30,
        executable_price=3.20,
        usable=True,
        market_session="regular",
        quote_source="structured-test-source",
        result_rule_version="options-result-v1",
    )
    after_expiry = datetime(
        2026, 8, 22, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles")
    ).timestamp()
    provider = AsyncMock(return_value=[])

    results = await trade_collector.collect_due_exits(
        now=after_expiry, quote_provider=provider
    )

    provider.assert_not_awaited()
    assert results[0]["status"] == "resolved"
    assert results[0]["exit_observation_id"] == "qualifying-before-expiry"
    chain = await tracking.get_trade_tracking_chain(registered["trade_id"])
    assert not any(row["status"] == "expired" for row in chain["results"])


@pytest.mark.asyncio
async def test_raw_schwab_facts_create_overnight_share_gap_but_not_bto_assignment(
    collector_db,
):
    share_links = await _links(suffix="share")
    share = await trade_collector.register_confirmed_delivery(
        **share_links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        primary_horizon_seconds=86_400,
    )
    await trade_collector.capture_trade_entry(
        share["trade_id"],
        quote_provider=AsyncMock(return_value=[_quote(
            1_786_563_004.0, 1_786_563_005.0,
            bid=150.95,
            ask=151.05,
            underlying_price=151.0,
            average_daily_dollar_volume=50_000_000,
            halt_status="normal",
        )]),
    )
    await trade_collector.collect_due_exits(
        now=1_786_649_410.0,
        quote_provider=AsyncMock(return_value=[_quote(
            1_786_649_400.0, 1_786_649_405.0,
            bid=154.95,
            ask=155.05,
            underlying_price=155.0,
            open_price=155.0,
            previous_close=150.0,
            average_daily_dollar_volume=50_000_000,
            halt_status="normal",
        )]),
    )
    share_chain = await tracking.get_trade_tracking_chain(share["trade_id"])
    assert any(row["status"] == "gap" for row in share_chain["results"])

    option_links = await _links(suffix="option")
    option = await trade_collector.register_confirmed_delivery(
        **option_links,
        confirmed_delivery_at=1_786_563_000.0,
        ticker="NVDA",
        direction="long",
        contract=_contract(),
        selection_quote=_quote(1_786_562_950.0, 1_786_562_955.0),
        rule_set={**_rules(), "rule_set_id": "rules-option", "rule_version": "batch2-rules-option"},
        primary_horizon_seconds=86_400,
    )
    await trade_collector.capture_trade_entry(
        option["trade_id"],
        quote_provider=AsyncMock(
            return_value=[_quote(1_786_563_004.0, 1_786_563_005.0)]
        ),
    )
    await trade_collector.collect_due_exits(
        now=1_786_649_410.0,
        quote_provider=AsyncMock(return_value=[_quote(
            1_786_649_400.0, 1_786_649_405.0,
            in_the_money=True,
            days_to_expiration=1,
        )]),
    )
    option_chain = await tracking.get_trade_tracking_chain(option["trade_id"])
    assert not any(
        row["status"] == "early_assignment_risk"
        for row in option_chain["results"]
    )
    assert any(row["status"] == "resolved" for row in option_chain["results"])
