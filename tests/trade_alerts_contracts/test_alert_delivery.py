"""Complete frozen alerts, recording isolation and supplied transport failures."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.alert_delivery import (
    DeliveryPersistenceError, DiscordSink, RenderedAlert, SendReceipt,
    deliver_candidate,
)
from consensus_engine.alerts.discord import send_trade_alert_payload
from consensus_engine.candidate_assembly import assemble_candidate
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.trade_alerts_config import TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, ConfluenceLink, DeliveryRecord, FeatureSnapshot, OptionRecommendation,
    RecordError, SessionRecord,
)
from test_adapters_delivery import _Response, _Session
from test_candidate_assembly import facts
from test_confidence import request
from test_opening_range_features import history
from test_strategy_interface import START


def candidate(direction="LONG", alert_type="ACTIONABLE", **changes):
    fields = facts(direction, alert_type, **changes)
    assembled = assemble_candidate(**fields)
    assert assembled.status == "READY"
    return assembled.candidate, fields["context"].session


class Clock:
    def __init__(self, at=START):
        self.at = at
        self.sleeps = []

    def __call__(self):
        return self.at

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.at += timedelta(seconds=seconds)


class Store:
    """Test-only atomic intent recorder; no durable-store claim."""

    def __init__(self, fail=None):
        self.intents = []
        self.results = []
        self.fail = fail

    async def intent(self, value):
        if self.fail == "intent" or any(item.record.record_id == value.record.record_id for item in self.intents):
            raise RuntimeError("synthetic storage failure or unresolved prior intent")
        self.intents.append(value)

    async def result(self, value):
        if self.fail == "started" or (self.fail == "result" and value.reason != "SINK_STARTED"):
            raise RuntimeError("synthetic storage failure")
        self.results.append(value)


def sender(transport, clock, max_attempts=3):
    async def send(rendered):
        return await send_trade_alert_payload(
            rendered, post=lambda **kwargs: transport.post("https://synthetic.invalid", **kwargs),
            clock=clock, sleep=clock.sleep, max_attempts=max_attempts)
    return send


def bound_assembly(row, session):
    supplied = request(direction=row.direction)
    supplied = replace(supplied, context=replace(supplied.context, session=session))
    original = assemble_candidate(**facts(row.direction, row.alert_type, supplied))
    return replace(original, candidate=row)


PRIMARY_CHANGES = (
    "strategy", "version", "symbol", "instrument_type", "missing_feature",
    "missing_primary_link", "missing_confidence_link", "unknown_input",
    "reused_input_id", "creation_time", "delivery_status", "confidence_result",
)


def altered_primary(assembly, change):
    row = assembly.candidate
    changes = {
        "strategy": {"strategy_id": "HOD_COMP_RS"},
        "version": {"strategy_version": "OTHER_VERSION"},
        "symbol": {"metadata": replace(row.metadata, instrument_id="OTHER")},
        "instrument_type": {"metadata": replace(row.metadata, instrument_type="ETF")},
        "missing_feature": {"feature_snapshot_id": "absent-feature"},
        "missing_primary_link": {"input_record_ids": tuple(
            item for item in row.input_record_ids if item != row.feature_snapshot_id)},
        "missing_confidence_link": {"input_record_ids": (row.feature_snapshot_id,)},
        "unknown_input": {"input_record_ids": (*row.input_record_ids, "absent-input")},
        "reused_input_id": {"record_id": row.feature_snapshot_id},
        "creation_time": {"created_at": row.created_at + timedelta(microseconds=1)},
        "delivery_status": {"delivery_status": "CONFIRMED_DELIVERED"},
    }
    if change == "confidence_result":
        return replace(assembly, confidence_result=replace(
            assembly.confidence_result, reasons=("ALTERED_RESULT",)))
    return replace(assembly, candidate=replace(row, **changes[change]))


async def deliver(row, session, store, **kwargs):
    assembly = kwargs.pop("assembly", bound_assembly(row, session))
    return await deliver_candidate(row, session=session, assembly=assembly, record_id="m46-delivery", at=START,
                                   save_intent=store.intent, save_result=store.result, **kwargs)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("alert_type", ("HEADS_UP", "ACTIONABLE"))
def test_render_exact_facts_and_complete_plain_fallback(direction, alert_type):
    row, _ = candidate(direction, alert_type)
    saved = row.to_json()
    output = RenderedAlert(row)
    assert output.payload()["embeds"][0]["description"] == output.payload(plain=True)["content"]
    assert f"{'HEADS-UP' if alert_type == 'HEADS_UP' else 'ACTIONABLE'} | SYNTH | {direction}" in output.text
    assert "Trigger: 100 | Alert price: 100" in output.text
    assert f"Stop: {99 if direction == 'LONG' else 101} | Risk per share: 1" in output.text
    assert f"T1: {102 if direction == 'LONG' else 98} (2R)" in output.text
    for text in ("Quality: 66.0/100", "not a win probability", "Setup 80", "Context 60", "Execution 40",
                 "Human checks: Review supplied structure", "Created:", "Expires:", "PDT",
                 "Soft invalidation:", "Options: Unavailable", "Data: VALID"):
        assert text in output.text
    for plain in (False, True):
        assert output.payload(plain=plain)["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert row.to_json() == saved
    assert RenderedAlert(AlertCandidate.from_json(saved)).text == output.text


def test_unknown_heads_up_prices_are_visible_and_zero_score_is_not_missing():
    row, _ = candidate(alert_type="HEADS_UP", risk=None, targets=(), trigger_price=None,
                       alert_price=None, mechanically_valid=False)
    output = RenderedAlert(row)
    assert "Stop: Unavailable" in output.text and "Targets: Unavailable" in output.text
    assert "Stock setup: Not confirmed" in output.text
    zero = replace(row, confidence=replace(row.confidence, final_score=0))
    assert "Quality: 0/100" in RenderedAlert(zero).text


@pytest.mark.parametrize("value", (None, {}, "bad candidate"))
def test_malformed_candidate_fails_before_rendering(value):
    with pytest.raises(RecordError):
        RenderedAlert(value)


@pytest.mark.parametrize("field", ("human_checks", "soft_invalidation", "target", "symbol"))
def test_oversized_required_text_is_rejected_without_trimming(field):
    row, _ = candidate()
    if field == "target":
        row = replace(row, targets=(replace(row.targets[0], name="x" * 2100),))
    elif field == "symbol":
        row = replace(row, metadata=replace(row.metadata, instrument_id="x" * 2100))
    else:
        row = replace(row, **{field: ("x" * 2100,) if field == "human_checks" else "x" * 2100})
    with pytest.raises(RecordError, match="single-message limit"):
        RenderedAlert(row)


def test_escaping_covers_markup_mentions_and_injected_lines():
    row, _ = candidate(human_checks=("@everyone <@user> **BUY**\nStop: 1 [click](url)",))
    text = RenderedAlert(row).text
    assert "@everyone" not in text and "<@user>" not in text
    assert "**BUY**" not in text and "\nStop: 1" not in text
    assert "\\*\\*BUY\\*\\*" in text
    assert "Stop: 99" in text


@pytest.mark.parametrize("status", ("UNAVAILABLE", "POOR"))
def test_separate_option_failure_keeps_stock_validity_and_all_geometry(status):
    row, _ = candidate()
    option = OptionRecommendation(record_id="m46-option", candidate_id=row.record_id,
                                  ranked_at=START, status=status, reasons=("No supplied option data",))
    output = RenderedAlert(row, option)
    assert "Stock setup: Valid" in output.text and "Stop: 99" in output.text
    assert ("Options: Unavailable" if status == "UNAVAILABLE" else "Options quality: Poor") in output.text
    assert row == output.candidate and row.delivery_status == "PENDING"


def test_option_link_and_time_must_match_original_candidate():
    row, _ = candidate()
    option = OptionRecommendation(record_id="m46-option", candidate_id="other", ranked_at=START,
                                  reasons=("Unavailable",))
    with pytest.raises(RecordError):
        RenderedAlert(row, option)
    with pytest.raises(RecordError):
        RenderedAlert(row, replace(option, candidate_id=row.record_id, ranked_at=START - timedelta(seconds=1)))


def test_visible_dates_use_pacific_in_both_seasons():
    row, _ = candidate()
    winter = datetime(2026, 12, 1, 6, 35, tzinfo=ZoneInfo("America/Los_Angeles"))
    row = replace(row, created_at=winter, expires_at=winter + timedelta(seconds=1))
    assert "2026-12-01 06:35:00 AM PST" in RenderedAlert(row).text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("replay", "shadow"))
async def test_default_recording_ignores_discord_setting_and_cannot_confirm_remote_delivery(mode):
    row, original_session = candidate()
    settings = TradeAlertsConfig({"alerts": {"sink": "discord"}})
    session = SessionRecord.from_config(record_id=original_session.record_id, session=original_session.session,
                                        started_at=original_session.started_at, config=settings)
    row = replace(row, config_hash=session.config_hash, config_version=session.config_version)
    store = Store()
    result = await deliver(row, session, store, mode=mode)
    assert result.record.sink == "recording" and result.reason == "RECORDING_ONLY"
    assert result.record.status == "REJECTED_BEFORE_SEND" and result.attempts == 0
    assert result.record.message_reference is None and store.intents[0].rendered.candidate == row
    assert store.results[-1] == result
    assert DeliveryRecord.from_json(result.record.to_json()) == result.record
    assert row.delivery_status == "PENDING"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("replay", "shadow", "live"))
async def test_remote_sink_cannot_enter_replay_shadow_or_live(mode):
    row, session = candidate()
    send = AsyncMock()
    store = Store()
    with pytest.raises(RecordError):
        await deliver(row, session, store, mode=mode, sink=DiscordSink(send))
    send.assert_not_awaited()
    assert store.intents == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", ("intent", "started"))
async def test_failed_fact_or_start_storage_sends_nothing(fail):
    row, session = candidate()
    send = AsyncMock()
    store = Store(fail)
    with pytest.raises(RuntimeError):
        await deliver(row, session, store, mode="offline_test", sink=DiscordSink(send))
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("delta,expired", ((-1, False), (0, True), (1, True)))
async def test_expiry_before_at_after_is_checked_without_mutating_original(delta, expired):
    row, session = candidate()
    store = Store()
    result = await deliver_candidate(
        row, session=session, assembly=bound_assembly(row, session), record_id="expiry", at=row.expires_at + timedelta(microseconds=delta),
        save_intent=store.intent, save_result=store.result)
    assert result.reason == ("EXPIRED" if expired else "RECORDING_ONLY")
    assert result.attempts == 0 and row.delivery_status == "PENDING"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", (None, "last-successful-chunk", {"id": "partial"}))
async def test_legacy_partial_or_none_is_unknown_not_whole_message_confirmation(raw):
    row, session = candidate()
    store = Store()
    result = await deliver(row, session, store, mode="offline_test", sink=DiscordSink(AsyncMock(return_value=raw)))
    assert result.record.status == "UNKNOWN" and result.record.message_reference is None
    assert result.reason == "UNSTRUCTURED_RECEIPT" and result.attempts == 1


@pytest.mark.asyncio
async def test_failed_receipt_storage_preserves_confirmation_for_reconciliation_and_refuses_retry():
    row, session = candidate()
    original = row.to_json()
    store = Store("result")
    send = AsyncMock(return_value=SendReceipt("CONFIRMED_DELIVERED", "MESSAGE_CONFIRMED", START, 1, "fake-message"))
    with pytest.raises(DeliveryPersistenceError) as error:
        await deliver(row, session, store, mode="offline_test", sink=DiscordSink(send))
    assert error.value.result.record.message_reference == "fake-message"
    assert store.results[0].record.status == "SEND_STARTED"
    assert len(store.intents) == 1
    store.fail = None
    with pytest.raises(RuntimeError):
        await deliver(row, session, store, mode="offline_test", sink=DiscordSink(send))
    assert send.await_count == 1 and row.to_json() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", ((200, "CONFIRMED_DELIVERED"), (201, "CONFIRMED_DELIVERED"),
                                            (204, "UNKNOWN"), (403, "FAILED"), (500, "UNKNOWN")))
async def test_additive_sender_classifies_one_whole_payload(status, expected):
    row, _ = candidate()
    clock = Clock()
    transport = _Session([_Response(status=status)])
    result = await sender(transport, clock)(RenderedAlert(row))
    assert result.status == expected and result.attempts == 1
    assert len(transport.posts) == 1 and clock.sleeps == []
    assert transport.posts[0][2]["allowed_mentions"] == {"parse": [], "replied_user": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ({}, {"id": None}, {"id": ""}, {"id": 123}, [], "bad"))
async def test_success_without_usable_message_reference_is_unknown(body):
    row, _ = candidate()
    result = await sender(_Session([_Response(body=body)]), Clock())(RenderedAlert(row))
    assert result.status == "UNKNOWN" and result.reason == "MISSING_MESSAGE_REFERENCE"
    assert result.message_reference is None


@pytest.mark.asyncio
async def test_rich_rejection_falls_back_with_every_original_fact():
    row, _ = candidate()
    output = RenderedAlert(row)
    transport = _Session([_Response(status=400), _Response()])
    result = await sender(transport, Clock())(output)
    assert result.status == "CONFIRMED_DELIVERED" and result.attempts == 2
    assert transport.posts[0][2]["embeds"][0]["description"] == transport.posts[1][2]["content"] == output.text
    assert "Stop: 99" in transport.posts[1][2]["content"] and "T1: 102" in transport.posts[1][2]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("final_status,expected", ((400, "FAILED"), (500, "UNKNOWN")))
async def test_failed_complete_fallback_has_no_extra_notice_or_blind_retry(final_status, expected):
    row, _ = candidate()
    transport = _Session([_Response(status=400), _Response(status=final_status)])
    result = await sender(transport, Clock())(RenderedAlert(row))
    assert result.status == expected and len(transport.posts) == 2
    assert result.message_reference is None


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ("body", "header", "both"))
async def test_throttled_retry_uses_supplied_provider_delay(source):
    row, _ = candidate(expires_at=START + timedelta(seconds=5))
    rate = _Response(status=429, body={"retry_after": 0.25} if source != "header" else {})
    if source != "body":
        rate.headers["Retry-After"] = "0.5"
    clock = Clock()
    transport = _Session([rate, _Response()])
    result = await sender(transport, clock)(RenderedAlert(row))
    assert result.status == "CONFIRMED_DELIVERED" and result.attempts == 2
    assert clock.sleeps == ([0.25] if source == "body" else [0.5])


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", (None, "bad", -1, float("inf"), float("nan"), True))
async def test_missing_or_invalid_delay_never_invents_a_retry(delay):
    row, _ = candidate()
    transport = _Session([_Response(status=429, body={"retry_after": delay})])
    clock = Clock()
    result = await sender(transport, clock)(RenderedAlert(row))
    assert result.status == "FAILED" and result.reason == "RETRY_DELAY_UNAVAILABLE"
    assert len(transport.posts) == 1 and clock.sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", (1, 2))
async def test_retry_at_or_beyond_expiry_does_not_wait_or_send(delay):
    row, _ = candidate()
    clock = Clock()
    transport = _Session([_Response(status=429, body={"retry_after": delay})])
    result = await sender(transport, clock)(RenderedAlert(row))
    assert result.reason == "RETRY_WOULD_EXPIRE" and len(transport.posts) == 1
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_repeated_throttling_stops_at_explicit_attempt_bound():
    row, _ = candidate()
    transport = _Session([_Response(status=429, body={"retry_after": 0}) for _ in range(2)])
    result = await sender(transport, Clock(), 2)(RenderedAlert(row))
    assert result.status == "FAILED" and result.reason == "ATTEMPTS_EXHAUSTED"
    assert result.attempts == len(transport.posts) == 2


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_error_text_is_never_copied(caplog):
    row, session = candidate()
    class Broken:
        def post(self, *args, **kwargs):
            raise TimeoutError("SYNTHETIC_PRIVATE_EXCEPTION_TEXT")
    clock = Clock()
    result = await deliver(row, session, Store(), mode="offline_test",
                           sink=DiscordSink(sender(Broken(), clock)))
    assert result.record.status == "UNKNOWN" and result.reason == "TRANSPORT_EXCEPTION"
    assert "SYNTHETIC_PRIVATE_EXCEPTION_TEXT" not in result.to_json() + caplog.text
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_expiry_during_storage_prevents_transport_call():
    row, session = candidate()
    store = Store()
    clock = Clock(row.expires_at)
    transport = _Session([])
    result = await deliver(row, session, store, mode="offline_test", sink=DiscordSink(sender(transport, clock)))
    assert result.reason == "EXPIRED" and result.attempts == 0 and transport.posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_bars_to_candidates_to_recording_and_fake_delivery_end_to_end(direction):
    source = history(changed=lambda bars: [Bar.from_json(row.to_json()) for row in bars])
    opening = build_opening_range_snapshot(record_id="m46-opening", evaluated_at=START,
                                           symbol="SYNTH", instrument_type="EQUITY", minute_history=source)
    opening = FeatureSnapshot.from_json(opening.to_json())
    assert {item.name: item.value for item in opening.features}["OPENING_RANGE_WIDTH_5M_V1"] == 10
    supplied = request(direction=direction, parents=(opening.record_id,))
    supplied = replace(supplied, context=replace(supplied.context, features=(*supplied.context.features, opening)))
    outputs = []
    for alert_type in ("HEADS_UP", "ACTIONABLE"):
        linked = assemble_candidate(**facts(
            direction, alert_type, supplied, record_id=f"m46-{direction}-{alert_type}-linked"
        )).candidate
        other_direction = "SHORT" if direction == "LONG" else "LONG"
        unlinked = assemble_candidate(**facts(
            other_direction, alert_type, record_id=f"m46-{direction}-{alert_type}-unlinked"
        )).candidate
        link = ConfluenceLink(linked.strategy_id, linked.record_id)
        fields = facts(direction, alert_type, supplied, confluence=(link,),
                       feature_snapshot_id=opening.record_id,
                       component_candidates=(unlinked, linked))
        assembly = assemble_candidate(**fields)
        row = AlertCandidate.from_json(assembly.candidate.to_json())
        before = row.to_json()
        assert row.confidence.final_score == 66 and row.risk.risk_per_share == 1
        option = OptionRecommendation(record_id="m46-options", candidate_id=row.record_id,
                                      ranked_at=START, reasons=("Synthetic options outage",))
        recorded = await deliver(row, supplied.context.session, Store(), options=option, assembly=assembly)
        assert recorded.reason == "RECORDING_ONLY" and recorded.attempts == 0
        transport = _Session([_Response(status=400), _Response(body={"id": "synthetic-confirmation"})])
        saved = Store()
        sent = await deliver(row, supplied.context.session, saved, options=option, assembly=assembly, mode="offline_test",
                             sink=DiscordSink(sender(transport, Clock())))
        assert len(saved.intents) == 1 and len(saved.results) == 2
        assert saved.intents[0].assembly.to_json() == assembly.to_json()
        assert saved.intents[0].assembly.component_candidates == (unlinked, linked)
        assert saved.intents[0].assembly.candidate.confluence == (link,)
        assert saved.results[0].record.status == "SEND_STARTED"
        assert sent.record.status == "CONFIRMED_DELIVERED" and sent.attempts == 2
        assert transport.posts[1][2]["content"] == recorded.rendered.text == sent.rendered.text
        assert "Stock setup: Valid" in sent.rendered.text and "Options: Unavailable" in sent.rendered.text
        assert DeliveryRecord.from_json(sent.record.to_json()) == sent.record
        unknown = await deliver(row, supplied.context.session, Store(), assembly=assembly, mode="offline_test",
                                sink=DiscordSink(AsyncMock(return_value="prior-chunk-only")))
        assert unknown.record.status == "UNKNOWN"
        expired_store = Store()
        expired = await deliver_candidate(row, session=supplied.context.session, assembly=assembly, record_id="expired",
                                          at=row.expires_at, save_intent=expired_store.intent,
                                          save_result=expired_store.result)
        assert expired.reason == "EXPIRED" and expired.attempts == 0
        rejected_primary = []
        for change in PRIMARY_CHANGES:
            altered = altered_primary(assembly, change)
            rejected_store = Store()
            rejected_send = AsyncMock()
            with pytest.raises(RecordError):
                await deliver_candidate(
                    altered.candidate, session=supplied.context.session, assembly=altered,
                    record_id="rejected-primary", at=START + timedelta(microseconds=1),
                    save_intent=rejected_store.intent, save_result=rejected_store.result,
                    mode="offline_test", sink=DiscordSink(rejected_send),
                )
            assert rejected_store.intents == [] and rejected_store.results == []
            rejected_send.assert_not_awaited()
            rejected_primary.append({"change": change, "stored": 0, "sent": 0})
        assert row.to_json() == before
        outputs.append({"rejected_primary": rejected_primary, "recording": recorded.as_dict(), "confirmed_fake": sent.as_dict(),
                        "unknown": unknown.as_dict(), "expired": expired.as_dict(),
                        "saved_component_ids": [item.record_id for item in
                                                saved.intents[0].assembly.component_candidates],
                        "saved_confluence_ids": [item.candidate_id for item in
                                                 saved.intents[0].assembly.candidate.confluence],
                        "original_unchanged": True})
    proof = {"synthetic_only": True, "direction": direction, "opening": opening.as_dict(),
             "input_count": len(source.bars), "input_sha256": hashlib.sha256(
                 "".join(row.to_json() for row in source.bars).encode()).hexdigest(), "outputs": outputs}
    text = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(text.encode()) < 100000
    Path(f"/tmp/m46-alert-delivery-{direction.lower()}-proof.json").write_text(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ("session", "configuration", "future_options", "before_creation", "same_id"))
async def test_inconsistent_delivery_links_and_times_fail_before_persistence(change):
    row, session = candidate()
    store = Store()
    values = {"session": session, "assembly": bound_assembly(row, session), "record_id": "m46-check", "at": START,
              "save_intent": store.intent, "save_result": store.result}
    if change == "session":
        row = replace(row, session_record_id="other")
    elif change == "configuration":
        row = replace(row, config_hash="0" * 64)
    elif change == "future_options":
        values["options"] = OptionRecommendation(record_id="option", candidate_id=row.record_id,
                                                  ranked_at=START + timedelta(microseconds=1),
                                                  reasons=("Unavailable",))
    elif change == "before_creation":
        values["at"] = START - timedelta(microseconds=1)
    else:
        values["record_id"] = row.record_id
    with pytest.raises((RecordError, ValueError)):
        await deliver_candidate(row, **values)
    assert store.intents == [] and store.results == []


@pytest.mark.asyncio
async def test_invalid_actionable_is_recorded_but_never_sent():
    row, session = candidate()
    row = replace(row, mechanically_valid=False)
    send = AsyncMock()
    store = Store()
    result = await deliver(row, session, store, mode="offline_test", sink=DiscordSink(send))
    assert result.reason == "INVALID_SETUP" and len(store.intents) == 1
    send.assert_not_awaited()


def test_render_and_receipt_records_are_immutable_and_payloads_are_detached():
    row, _ = candidate()
    output = RenderedAlert(row)
    text = output.text
    payload = output.payload()
    payload["embeds"][0]["description"] = "changed"
    payload["allowed_mentions"]["parse"].append("everyone")
    assert output.text == text and output.payload()["allowed_mentions"]["parse"] == []
    with pytest.raises(FrozenInstanceError):
        output.candidate = None
    with pytest.raises(RecordError):
        SendReceipt("CONFIRMED_DELIVERED", "MESSAGE_CONFIRMED", START, 1)
    with pytest.raises(RecordError):
        SendReceipt("UNKNOWN", "UNCONFIRMED_RESPONSE", START, 1, "partial")


@pytest.mark.asyncio
async def test_retry_sleep_cannot_send_after_expiry_or_before_provider_delay():
    row, _ = candidate()
    for advance, reason in ((0, "RETRY_DELAY_NOT_ELAPSED"), (2, "EXPIRED")):
        clock = Clock()
        async def fake_sleep(_):
            clock.at += timedelta(seconds=advance)
        clock.sleep = fake_sleep
        transport = _Session([_Response(status=429, body={"retry_after": 0.25})])
        result = await sender(transport, clock)(RenderedAlert(row))
        assert result.reason == reason and len(transport.posts) == 1


@pytest.mark.asyncio
async def test_expiry_between_rich_rejection_and_fallback_never_sends_fallback():
    row, _ = candidate()
    clock = Clock()
    class LateRejection(_Response):
        async def __aexit__(self, *args):
            clock.at = row.expires_at
    transport = _Session([LateRejection(status=400)])
    result = await sender(transport, clock)(RenderedAlert(row))
    assert result.reason == "EXPIRED" and len(transport.posts) == 1


@pytest.mark.asyncio
async def test_body_read_failure_is_unknown_but_valid_rate_header_remains_usable():
    row, _ = candidate()
    class BadBody(_Response):
        async def json(self):
            raise ValueError("synthetic unreadable body")
    result = await sender(_Session([BadBody()]), Clock())(RenderedAlert(row))
    assert result.status == "UNKNOWN" and result.attempts == 1
    rate = BadBody(status=429)
    rate.headers["Retry-After"] = "0.25"
    result = await sender(_Session([rate, _Response()]), Clock())(RenderedAlert(row))
    assert result.status == "CONFIRMED_DELIVERED" and result.attempts == 2


@pytest.mark.asyncio
async def test_real_temporary_transaction_failure_sends_nothing_and_rolls_back():
    import sqlite3
    from consensus_engine import db
    row, session = candidate()
    connection = await db.init_db()
    await connection.execute("CREATE TABLE m46_fixture_facts (body TEXT NOT NULL)")
    await connection.commit()
    async def fail_transaction(intent):
        await connection.execute_transaction([
            ("INSERT INTO m46_fixture_facts VALUES (?)", (intent.rendered.candidate.to_json(),)),
            ("INSERT INTO m46_deliberately_missing_table VALUES (?)", (intent.record.to_json(),)),
        ])
    send = AsyncMock()
    with pytest.raises(sqlite3.OperationalError):
        await deliver_candidate(row, session=session, assembly=bound_assembly(row, session), record_id="rollback", at=START,
                                save_intent=fail_transaction, save_result=AsyncMock(),
                                mode="offline_test", sink=DiscordSink(send))
    send.assert_not_awaited()
    assert (await (await connection.execute("SELECT COUNT(*) FROM m46_fixture_facts")).fetchone())[0] == 0


@pytest.mark.asyncio
async def test_cancelled_send_keeps_started_record_without_automatic_resend():
    import asyncio
    row, session = candidate()
    store = Store()
    async def cancelled(_):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await deliver(row, session, store, mode="offline_test", sink=DiscordSink(cancelled))
    assert len(store.intents) == 1 and len(store.results) == 1
    assert store.results[0].record.status == "SEND_STARTED"
    with pytest.raises(RuntimeError):
        await deliver(row, session, store, mode="offline_test", sink=DiscordSink(cancelled))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("absent", "candidate", "confidence", "context"))
async def test_complete_assembly_attribution_is_required_before_persistence(missing):
    row, session = candidate()
    assembly = bound_assembly(row, session)
    if missing == "absent":
        assembly = None
    elif missing == "candidate":
        assembly = replace(assembly, candidate=replace(row, structure_id="different"))
    elif missing == "confidence":
        assembly = replace(assembly, confidence_result=None)
    else:
        assembly = replace(assembly, context=replace(assembly.context, features=()))
    store = Store()
    send = AsyncMock()
    with pytest.raises(RecordError):
        await deliver(row, session, store, assembly=assembly, mode="offline_test", sink=DiscordSink(send))
    assert store.intents == []
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("alert_type", ("HEADS_UP", "ACTIONABLE"))
@pytest.mark.parametrize("change", PRIMARY_CHANGES)
async def test_primary_attribution_is_rechecked_before_any_storage_or_transport(direction, alert_type, change):
    supplied = request(direction=direction)
    primary = replace(supplied.context.features[0], record_id="m46-primary-feature")
    supplied = replace(supplied, context=replace(
        supplied.context, features=(*supplied.context.features, primary)))
    original = assemble_candidate(**facts(
        direction, alert_type, supplied, feature_snapshot_id=primary.record_id))
    assembly = altered_primary(original, change)
    assert assembly != original
    session = supplied.context.session
    save_intent, save_result, send = AsyncMock(), AsyncMock(), AsyncMock()
    with pytest.raises(RecordError):
        await deliver_candidate(
            assembly.candidate, session=session, assembly=assembly, record_id="rejected-primary",
            at=START + timedelta(microseconds=1), save_intent=save_intent,
            save_result=save_result, mode="offline_test", sink=DiscordSink(send),
        )
    save_intent.assert_not_awaited()
    save_result.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ("missing", "wrong_strategy", "opposite", "wrong_config"))
async def test_component_links_are_rechecked_before_persistence(change):
    row, session = candidate()
    component = assemble_candidate(**facts(record_id="m46-component")).candidate
    link = ConfluenceLink(component.strategy_id, component.record_id)
    assembly = bound_assembly(replace(row, confluence=(link,)), session)
    assembly = replace(assembly, component_candidates=(component,))
    if change == "missing":
        assembly = replace(assembly, component_candidates=())
    elif change == "wrong_strategy":
        assembly = replace(assembly, component_candidates=(replace(component, strategy_id="HOD_COMP_RS"),))
    elif change == "opposite":
        assembly = replace(assembly, component_candidates=(
            assemble_candidate(**facts("SHORT", record_id=component.record_id)).candidate,
        ))
    else:
        assembly = replace(assembly, component_candidates=(replace(component, config_hash="0" * 64),))
    store = Store()
    send = AsyncMock()
    with pytest.raises(RecordError):
        await deliver(assembly.candidate, session, store, assembly=assembly,
                      mode="offline_test", sink=DiscordSink(send))
    assert store.intents == []
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_linked_and_unlinked_components_are_preserved_in_delivery_intent():
    row, session = candidate()
    linked = assemble_candidate(**facts(record_id="m46-linked-component")).candidate
    unlinked = assemble_candidate(**facts("SHORT", record_id="m46-unlinked-component")).candidate
    link = ConfluenceLink(linked.strategy_id, linked.record_id)
    assembly = bound_assembly(replace(row, confluence=(link,)), session)
    assembly = replace(assembly, component_candidates=(unlinked, linked))
    store = Store()
    result = await deliver(assembly.candidate, session, store, assembly=assembly)
    assert result.reason == "RECORDING_ONLY"
    assert store.intents[0].assembly.component_candidates == (unlinked, linked)
    assert store.intents[0].assembly.candidate.confluence == (link,)
