"""Integration tests for the measurable Batch 1 alert lifecycle."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg, db
from consensus_engine.measurement import (
    get_trade_chain,
    record_candidate,
    record_delivery,
    record_outcome,
    transition_decision,
    write_initial_trade_bundle,
)


@pytest.fixture
async def measurement_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "measurement.db")}
    await db.init_db()
    yield
    await db.close_db()


@pytest.mark.asyncio
async def test_pending_decision_exists_before_scoring_starts(measurement_db):
    candidate_id = await record_candidate(ticker="NVDA", direction="long", analyst="alpha")

    decision_id = await transition_decision(candidate_id=candidate_id, status="pending")

    chain = await get_trade_chain(candidate_id)
    assert chain["decisions"][0]["decision_id"] == decision_id
    assert chain["decisions"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_sent_alert_has_complete_link_chain(measurement_db):
    ids = await write_initial_trade_bundle(
        candidate={"ticker": "NVDA", "direction": "long", "analyst": "alpha"},
        decision={"status": "scored", "owner_visible_score": 81},
        alert={"status": "send_started", "displayed_score": 81},
        delivery={"status": "confirmed_delivered", "attempt_id": "attempt-1"},
        outcome={"direction": "long", "horizon": "5d", "status": "pending"},
    )

    chain = await get_trade_chain(ids["candidate_id"])
    assert chain["decisions"][0]["candidate_id"] == ids["candidate_id"]
    assert chain["alerts"][0]["decision_id"] == ids["decision_id"]
    assert chain["deliveries"][0]["decision_id"] == ids["decision_id"]
    assert chain["outcomes"][0]["decision_id"] == ids["decision_id"]


@pytest.mark.parametrize("status", ["timed_out", "failed"])
@pytest.mark.asyncio
async def test_unsuccessful_delivery_remains_visible_and_unconfirmed(measurement_db, status):
    candidate_id = await record_candidate(ticker="NVDA", direction="long")
    decision_id = await transition_decision(candidate_id=candidate_id, status="scored")

    delivery_id = await record_delivery(
        decision_id=decision_id,
        status=status,
        reason="synthetic delivery failure",
        attempt_id="attempt-1",
    )

    chain = await get_trade_chain(candidate_id)
    delivery = chain["deliveries"][0]
    assert delivery["delivery_id"] == delivery_id
    assert delivery["status"] == status
    assert delivery["reason"] == "synthetic delivery failure"
    assert delivery["confirmed_at"] is None


@pytest.mark.asyncio
async def test_displayed_score_equals_stored_evaluation_score(measurement_db):
    ids = await write_initial_trade_bundle(
        candidate={"ticker": "NVDA", "direction": "long"},
        decision={"status": "scored", "owner_visible_score": 81},
        alert={"status": "send_started", "displayed_score": 81},
    )

    chain = await get_trade_chain(ids["candidate_id"])
    assert chain["alerts"][0]["displayed_score"] == chain["decisions"][0]["owner_visible_score"]


@pytest.mark.asyncio
async def test_outcome_requires_same_direction_as_candidate(measurement_db):
    candidate_id = await record_candidate(ticker="NVDA", direction="short")
    decision_id = await transition_decision(candidate_id=candidate_id, status="scored")

    with pytest.raises(ValueError, match="direction"):
        await record_outcome(
            decision_id=decision_id,
            direction="long",
            horizon="5d",
            status="resolved",
            value=-0.1,
        )


@pytest.mark.parametrize("delivery_failure", ["none", "exception"])
@pytest.mark.asyncio
async def test_phase2_delivery_failure_is_failed_without_scored_or_displayed_state(
    measurement_db, delivery_failure
):
    from consensus_engine.engine import SignalClass
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine.models import CrossReferenceResult, Direction, ScoreBreakdown

    ids = await write_initial_trade_bundle(
        candidate={"ticker": "NVDA", "direction": "long", "analyst": "alpha"},
        decision={"status": "pending"},
    )
    legacy = await db.insert_alert_with_measurement(
        ticker="NVDA", confidence=40, catalyst="", catalyst_type="",
        consensus_json="{}", technical_json="{}", analysts_json='["alpha"]',
        price=100, decision_id=ids["decision_id"], direction="long", analyst="alpha",
    )
    alert_message_id = await db.insert_alert_message(
        ticker="NVDA", analyst="alpha", instant_msg_id="phase1", base_score=40
    )
    await record_delivery(
        decision_id=ids["decision_id"], delivery_id=legacy["delivery_id"],
        attempt_id=legacy["delivery_id"], status="confirmed_delivered",
        external_message_id="phase1",
    )
    xref = CrossReferenceResult(
        ticker="NVDA", breakdown=ScoreBreakdown(base=72),
        catalyst_summary="", catalyst_type="",
    )
    tweet = MagicMock(analyst="alpha", base_score=40, direction=Direction.LONG)
    cfg._config.setdefault("alerts", {}).setdefault("merged_detail_card", {})["enabled"] = False

    send_mock = (
        AsyncMock(side_effect=RuntimeError("synthetic phase2 send failure"))
        if delivery_failure == "exception" else AsyncMock(return_value=None)
    )
    with patch("consensus_engine.main.cross_reference", new=AsyncMock(return_value=xref)), \
         patch("consensus_engine.main.analyze_signal", new=AsyncMock(return_value={
             "classification": SignalClass.WATCHLIST, "skipped": False, "total_score": 72,
         })), \
         patch("consensus_engine.main.send_detail_followup", new=send_mock):
        await _run_cross_reference_and_followup(
            "NVDA", tweet, "phase1", alert_message_id, legacy["legacy_alert_id"],
            entry_price=100, measurement_candidate_id=ids["candidate_id"],
            measurement_decision_id=ids["decision_id"],
            measurement_alert_id=legacy["alert_id"],
        )

    chain = await get_trade_chain(ids["candidate_id"])
    message = await db.get_alert_message(alert_message_id)
    assert chain["decisions"][-1]["status"] == "failed"
    assert all(event["status"] != "scored" for event in chain["decisions"])
    assert all(event["status"] != "scored" for event in chain["alerts"])
    expected_reason = (
        "phase2_delivery_exception" if delivery_failure == "exception"
        else "phase2_delivery_failed"
    )
    assert chain["decisions"][-1]["reason"] == expected_reason
    assert chain["alerts"][-1]["reason"] == expected_reason
    assert chain["deliveries"][-1]["reason"] == expected_reason
    assert any(
        event["status"] == "confirmed_delivered" and event["external_message_id"] == "phase1"
        for event in chain["deliveries"]
    )
    assert message["followup_msg_id"] is None
    assert message["final_score"] == 0
