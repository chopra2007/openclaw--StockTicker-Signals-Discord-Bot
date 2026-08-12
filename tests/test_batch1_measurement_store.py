"""Hostile storage tests for the Batch 1 measurement record."""

import sqlite3

import pytest

from consensus_engine import config as cfg, db
from consensus_engine.measurement import (
    append_correction,
    get_trade_chain,
    record_candidate,
    reconcile_dual_writes,
    transition_decision,
    write_initial_trade_bundle,
)


@pytest.fixture
async def measurement_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "measurement.db")}
    await db.init_db()
    yield await db.get_db()
    await db.close_db()


async def _count(conn, table):
    cursor = await conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
    return (await cursor.fetchone())["count"]


async def _insert_legacy_alert(conn, *, ticker="NVDA", alerted_at=100):
    cursor = await conn.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type, consensus_breakdown,
            technical_data, analyst_mentions, alerted_at, price_at_alert)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, 81, "earnings", "earnings", "{}", "{}", "[]", alerted_at, 100),
    )
    await conn.commit()
    return cursor.lastrowid


async def _scored_decision():
    candidate_id = await record_candidate(ticker="NVDA", direction="long", analyst="alpha")
    return await transition_decision(
        candidate_id=candidate_id, status="scored", owner_visible_score=81
    )


def _legacy_alert_values(decision_id, *, direction="long"):
    return {
        "ticker": "NVDA",
        "confidence": 81,
        "catalyst": "earnings",
        "catalyst_type": "earnings",
        "consensus_json": "{}",
        "technical_json": "{}",
        "analysts_json": '["alpha"]',
        "price": 100,
        "decision_id": decision_id,
        "direction": direction,
        "analyst": "alpha",
    }


@pytest.mark.asyncio
async def test_record_candidate_rejects_missing_direction(measurement_db):
    with pytest.raises(ValueError, match="direction"):
        await record_candidate(ticker="NVDA", direction="")


@pytest.mark.asyncio
async def test_forced_last_write_failure_leaves_no_partial_trade_bundle(measurement_db):
    await measurement_db.execute(
        """CREATE TRIGGER fail_batch1_outcome
           BEFORE INSERT ON measurement_outcome_events_v1
           BEGIN SELECT RAISE(FAIL, 'forced outcome failure'); END"""
    )
    await measurement_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced outcome failure"):
        await write_initial_trade_bundle(
            candidate={"ticker": "NVDA", "direction": "long", "analyst": "alpha"},
            decision={"status": "scored", "owner_visible_score": 81},
            alert={"status": "send_started", "displayed_score": 81},
            delivery={"status": "confirmed_delivered", "attempt_id": "attempt-1"},
            outcome={"direction": "long", "horizon": "5d", "status": "pending"},
        )

    for table in (
        "measurement_candidates_v1",
        "measurement_decision_events_v1",
        "measurement_alert_events_v1",
        "measurement_delivery_events_v1",
        "measurement_outcome_events_v1",
    ):
        assert await _count(measurement_db, table) == 0, table


@pytest.mark.asyncio
async def test_insert_alert_with_measurement_links_legacy_alert_id(measurement_db):
    decision_id = await _scored_decision()

    result = await db.insert_alert_with_measurement(**_legacy_alert_values(decision_id))

    cursor = await measurement_db.execute(
        "SELECT legacy_alert_id, displayed_score FROM measurement_alert_events_v1 WHERE alert_id = ?",
        (result["alert_id"],),
    )
    measurement_alert = dict(await cursor.fetchone())
    legacy_cursor = await measurement_db.execute(
        "SELECT confidence_score FROM alert_history WHERE id = ?", (result["legacy_alert_id"],)
    )
    assert measurement_alert["legacy_alert_id"] == result["legacy_alert_id"]
    assert measurement_alert["displayed_score"] == (await legacy_cursor.fetchone())["confidence_score"] == 81


@pytest.mark.asyncio
async def test_insert_alert_with_measurement_starts_linked_pending_outcome(measurement_db):
    decision_id = await _scored_decision()

    await db.insert_alert_with_measurement(**_legacy_alert_values(decision_id))

    cursor = await measurement_db.execute(
        "SELECT decision_id, status, value FROM measurement_outcome_events_v1"
    )
    outcome = dict(await cursor.fetchone())
    assert outcome == {"decision_id": decision_id, "status": "pending", "value": None}


@pytest.mark.asyncio
async def test_insert_alert_with_measurement_rolls_back_every_alert_row_on_delivery_failure(
    measurement_db,
):
    decision_id = await _scored_decision()
    await measurement_db.execute(
        """CREATE TRIGGER fail_final_batch1_delivery
           BEFORE INSERT ON measurement_delivery_events_v1
           WHEN NEW.status = 'send_started'
           BEGIN SELECT RAISE(FAIL, 'forced final delivery failure'); END"""
    )
    await measurement_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced final delivery failure"):
        await db.insert_alert_with_measurement(**_legacy_alert_values(decision_id))

    assert await _count(measurement_db, "alert_history") == 0
    assert await _count(measurement_db, "measurement_alert_events_v1") == 0
    assert await _count(measurement_db, "measurement_delivery_events_v1") == 0


@pytest.mark.asyncio
async def test_original_candidate_fact_cannot_be_overwritten(measurement_db):
    candidate_id = await record_candidate(
        ticker="NVDA", direction="long", analyst="alpha", candidate_id="candidate-fixed"
    )

    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        await record_candidate(
            ticker="NVDA", direction="short", analyst="alpha", candidate_id=candidate_id
        )

    cursor = await measurement_db.execute(
        "SELECT direction FROM measurement_candidates_v1 WHERE candidate_id = ?",
        (candidate_id,),
    )
    assert (await cursor.fetchone())["direction"] == "long"


@pytest.mark.parametrize("direction,exit_price,expected_hit", [
    ("short", 90, 1),
    ("short", 110, 0),
    ("long", 110, 1),
    ("long", 90, 0),
])
@pytest.mark.asyncio
async def test_linked_outcome_grades_move_for_stored_trade_direction(
    measurement_db, direction, exit_price, expected_hit
):
    candidate_id = await record_candidate(ticker="NVDA", direction=direction, analyst="alpha")
    decision_id = await transition_decision(
        candidate_id=candidate_id, status="scored", owner_visible_score=81
    )
    result = await db.insert_alert_with_measurement(
        **_legacy_alert_values(decision_id, direction=direction)
    )
    await db.insert_shadow_prediction(result["legacy_alert_id"], 0.81, "1h")

    await db.write_linked_alert_outcome(
        alert_id=result["legacy_alert_id"], field="price_1h_later",
        price=exit_price, horizon="1h",
    )

    cursor = await measurement_db.execute(
        "SELECT actual_hit FROM shadow_predictions WHERE alert_id = ? AND horizon = '1h'",
        (result["legacy_alert_id"],),
    )
    assert (await cursor.fetchone())["actual_hit"] == expected_hit


@pytest.mark.parametrize("writer", ["alert", "delivery", "outcome"])
@pytest.mark.asyncio
async def test_measurement_child_writer_rejects_unknown_decision_id(measurement_db, writer):
    from consensus_engine.measurement import record_alert, record_delivery, record_outcome

    calls = {
        "alert": lambda: record_alert(decision_id="missing", status="send_started"),
        "delivery": lambda: record_delivery(decision_id="missing", status="send_started"),
        "outcome": lambda: record_outcome(
            decision_id="missing", direction="long", horizon="1h", status="pending"
        ),
    }

    with pytest.raises(ValueError, match="decision"):
        await calls[writer]()


@pytest.mark.asyncio
async def test_append_correction_preserves_original_fact(measurement_db):
    candidate_id = await record_candidate(ticker="NVDA", direction="long", analyst="alpha")

    correction_id = await append_correction(
        entity_type="candidate",
        entity_id=candidate_id,
        prior_event_id=candidate_id,
        reason="source issued a correction",
        corrected_fields={"direction": "short"},
        actor_version="test-v1",
    )

    chain = await get_trade_chain(candidate_id)
    assert chain["candidate"]["direction"] == "long"
    assert chain["corrections"][0]["correction_id"] == correction_id
    assert chain["corrections"][0]["prior_event_id"] == candidate_id
    assert chain["corrections"][0]["corrected_fields"] == {"direction": "short"}


@pytest.mark.asyncio
async def test_reconcile_dual_writes_matches_linked_old_and_new_alert(measurement_db):
    legacy_alert_id = await _insert_legacy_alert(measurement_db)
    await write_initial_trade_bundle(
        candidate={"ticker": "NVDA", "direction": "long", "created_at": 100},
        decision={"status": "scored", "owner_visible_score": 81, "created_at": 100},
        alert={"status": "send_started", "displayed_score": 81,
               "legacy_alert_id": legacy_alert_id, "created_at": 100},
        delivery={"status": "confirmed_delivered", "attempt_id": "attempt-1",
                  "created_at": 100},
    )

    result = await reconcile_dual_writes(since=0, until=200)

    assert result["old_count"] == result["new_count"] == 1
    assert result["count_difference"] == 0
    assert result["matches"] is True
    assert result["mismatches"] == 0
    assert result["mismatch_details"] == []


@pytest.mark.asyncio
async def test_reconcile_dual_writes_names_new_side_when_old_alert_is_unlinked(measurement_db):
    await _insert_legacy_alert(measurement_db)

    result = await reconcile_dual_writes(since=0, until=200)

    assert result["old_count"] == 1
    assert result["new_count"] == 0
    assert result["count_difference"] == -1
    assert result["matches"] is False
    assert result["mismatches"] > 0
    assert result["mismatch_details"][0]["field"] == "alert_count"
    assert result["mismatch_details"][0]["missing_side"] == "new"


@pytest.mark.parametrize("status", ["rejected_before_send", "suppressed"])
@pytest.mark.asyncio
async def test_reconcile_counts_terminal_unsent_candidate_without_alert_gap(
    measurement_db, status
):
    candidate_id = await record_candidate(
        ticker="NVDA", direction="long", created_at=100
    )
    await transition_decision(
        candidate_id=candidate_id, status=status, reason="synthetic", created_at=100
    )

    result = await reconcile_dual_writes(since=0, until=200)

    assert result["old_count"] == result["new_count"] == 0
    assert result["count_difference"] == 0
    assert result["candidate_count"] == 1
    assert result["field_mismatches"]["candidates_missing_decision"] == 0
    assert result["field_mismatches"]["candidates_missing_terminal_status"] == 0
    assert result["lifecycle_counts"][status] == 1
    assert result["matches"] is True
