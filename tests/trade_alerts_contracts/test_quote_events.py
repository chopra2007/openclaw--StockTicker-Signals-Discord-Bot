"""M2.3 synthetic normalized Quote -> continuity/age -> recording contracts."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine.quote_events import QuoteEventPolicy, QuoteEventStream
from consensus_engine.scanners.schwab_normalization import normalize_schwab_quote
from consensus_engine.trade_alerts_models import Quote, RecordError, SourceMetadata
from consensus_engine.utils.time_context import format_pacific


PACIFIC = ZoneInfo("America/Los_Angeles")
START = datetime(2026, 6, 30, 6, 35, tzinfo=PACIFIC)


def at(seconds):
    return START + timedelta(seconds=seconds)


def policy(**changes):
    values = dict(version="M23_SYNTHETIC_ONLY", max_quote_age_seconds=3,
                  max_trade_age_seconds=5, max_observation_gap_seconds=6)
    values.update(changes)
    return QuoteEventPolicy(**values)


def stream(**changes):
    values = dict(source="SCHWAB", instrument_id="AAPL", instrument_type="EQUITY",
                  session="2026-06-30", data_mode="REST_FIXTURE", policy=policy())
    values.update(changes)
    return QuoteEventStream(**values)


def quote(name, seconds, *, trade_seconds=None, available_seconds=None, **changes):
    trade_seconds = seconds if trade_seconds is None else trade_seconds
    available_seconds = max(seconds, trade_seconds) if available_seconds is None else available_seconds
    result = normalize_schwab_quote(
        {"symbol": "AAPL", "quote": {
            "quoteTime": int(at(seconds).timestamp() * 1000),
            "tradeTime": int(at(trade_seconds).timestamp() * 1000),
            "bidPrice": 100.0, "askPrice": 100.2, "lastPrice": 100.1,
            "bidSize": 2, "askSize": 3, "lastSize": 1,
        }},
        record_id=name, raw_symbol="AAPL", status="VALID", delayed=False,
        metadata=SourceMetadata(
            source="SCHWAB", instrument_id="AAPL", instrument_type="EQUITY",
            session="2026-06-30", data_mode="REST_FIXTURE", quality="VALID",
            source_time=at(seconds), received_time=at(available_seconds),
            available_time=at(available_seconds), normalized_time=at(available_seconds + 100),
        ),
    )
    return replace(result, **changes)


def confirm(subject, current, seconds, **changes):
    state = subject.inspect(at(seconds))
    values = dict(at=at(seconds), epoch=state.epoch, record_id=current.record_id,
                  evidence_reference="M23_SYNTHETIC_CONTINUITY")
    values.update(changes)
    return subject.confirm_continuity(**values)


def primed(**changes):
    subject = stream(**changes)
    subject.connect(at(0))
    initial = quote("initial", 0)
    assert not subject.consume(initial, at=at(0)).usable
    assert confirm(subject, initial, 0).usable
    return subject


def test_normalized_events_failure_reconnect_recording_end_to_end():
    subject = stream()
    recorded = [subject.connect(at(0))]

    def consume(value, seconds):
        result = subject.consume(Quote.from_json(value.to_json()), at=at(seconds))
        recorded.append(result)
        return result

    initial = quote("q0", 0)
    consume(initial, 0)
    first_confirmation = confirm(subject, initial, 0)
    recorded.append(first_confirmation)
    q1 = quote("q1", 1)
    consume(q1, 1)
    redelivery = replace(q1, record_id="q1-repeat", metadata=replace(
        q1.metadata, received_time=at(2), available_time=at(2), normalized_time=at(200), sequence=99))
    repeated = consume(redelivery, 2)
    assert repeated.action == "DUPLICATE" and repeated.quote == q1
    recorded.append(subject.inspect(at(4)))
    recorded.append(subject.inspect(at(4.001)))
    assert recorded[-2].usable and "QUOTE_STALE" in recorded[-1].reasons
    consume(quote("q2", 5, trade_seconds=1), 5)
    consume(quote("q3", 5, trade_seconds=7), 7)
    late = consume(quote("late", 4, trade_seconds=8), 8)
    assert late.action == "OUT_OF_ORDER" and not late.usable
    recorded.append(subject.disconnect(at(9)))
    recorded.append(subject.connect(at(10)))
    consume(quote("q3-repeat", 5, trade_seconds=7), 10)
    q4 = quote("q4", 11)
    assert not consume(q4, 11).usable
    recorded.append(confirm(subject, q4, 11, epoch=first_confirmation.epoch))
    recorded.append(confirm(subject, q4, 11, evidence_reference=" unknown "))
    assert all(result.action == "CONTINUITY_REJECTED" for result in recorded[-2:])
    recorded.append(confirm(subject, q4, 11))
    assert recorded[-1].usable
    consume(quote("q5", 12), 12)
    recorded.append(subject.mark_gap(at(13)))
    q6 = quote("q6", 14)
    consume(q6, 14)
    recorded.append(confirm(subject, q6, 14))
    recorded.append(subject.inspect(at(21)))
    assert "OBSERVATION_GAP" in recorded[-1].reasons and not recorded[-1].usable
    delayed = quote("q7", 22, delayed=True, status="STALE")
    delayed = replace(delayed, metadata=replace(delayed.metadata, quality="STALE"))
    consume(delayed, 22)
    missing = quote("q8", 23, quote_time=None, trade_time=None, bid=None, ask=None,
                    last=None, status="MISSING", delayed=None)
    consume(missing, 23)
    assert "QUOTE_TIME_UNKNOWN" in recorded[-1].reasons
    q9 = quote("q9", 24)
    consume(q9, 24)
    recorded.append(confirm(subject, q9, 24))
    q10 = quote("q10", 25)
    consume(q10, 25)
    source_missing = replace(q10, record_id="q11-source-missing", metadata=replace(
        q10.metadata, source_time=None, received_time=at(26), available_time=at(26)))
    missing_result = consume(source_missing, 26)
    assert missing_result.quote == source_missing and not missing_result.usable
    assert "SOURCE_TIME_UNKNOWN" in missing_result.reasons
    recorded.append(confirm(subject, source_missing, 26))
    assert recorded[-1].action == "CONTINUITY_REJECTED"
    cache_repeat = consume(replace(q10, record_id="q10-cache"), 27)
    assert cache_repeat.action == "REPEATED_TIMESTAMPS"
    assert cache_repeat.quote == source_missing and not cache_repeat.usable
    wrong_session = replace(q10, record_id="q12-source-wrong-session", metadata=replace(
        q10.metadata, source_time=at(25) - timedelta(days=1),
        received_time=at(28), available_time=at(28)))
    wrong_result = consume(wrong_session, 28)
    assert wrong_result.quote == wrong_session and not wrong_result.usable
    assert "SOURCE_SESSION_MISMATCH" in wrong_result.reasons
    recorded.append(confirm(subject, wrong_session, 28))
    assert recorded[-1].action == "CONTINUITY_REJECTED"
    recovery = quote("q13-recovery", 29)
    assert not consume(recovery, 29).usable
    recorded.append(confirm(subject, recovery, 29))
    assert recorded[-1].usable
    q14 = quote("q14", 30)
    consume(q14, 30)
    old_source = replace(q14, record_id="q15-source-before-recovery", metadata=replace(
        q14.metadata, source_time=at(27), received_time=at(31), available_time=at(31)))
    old_result = consume(old_source, 31)
    assert old_result.quote == old_source and "SOURCE_BEFORE_RECOVERY" in old_result.reasons
    assert not old_result.usable and not old_result.forward_quote and not old_result.forward_trade
    recorded.append(confirm(subject, old_source, 31))
    assert recorded[-1].action == "CONTINUITY_REJECTED"
    future_source = quote("q16-source-after-availability", 32)
    future_source = replace(future_source, metadata=replace(
        future_source.metadata, source_time=at(33)))
    future_result = consume(future_source, 32)
    assert future_result.action == "INVALID_SOURCE_TIME" and future_result.quote == future_source
    assert "INVALID_SOURCE_TIME" in future_result.reasons and not future_result.usable
    recorded.append(subject.inspect(at(33)))
    assert recorded[-1].quote == future_source and "INVALID_SOURCE_TIME" in recorded[-1].reasons
    recorded.append(confirm(subject, future_source, 33))
    assert recorded[-1].action == "CONTINUITY_REJECTED"
    recovery = quote("q17-recovery", 34)
    assert not consume(recovery, 34).usable
    recorded.append(confirm(subject, recovery, 34))
    assert recorded[-1].usable
    consume(quote("q18", 35), 35)
    quote_ids = [item.input_record_id for item in recorded if item.forward_quote]
    trade_ids = [item.input_record_id for item in recorded if item.forward_trade]
    assert quote_ids == ["q1", "q2", "q5", "q10", "q14", "q18"]
    assert trade_ids == ["q1", "q3", "q5", "q10", "q14", "q18"]
    assert len(recorded) == 43
    assert repeated.quote.metadata.available_time == at(1)
    assert repeated.quote.metadata.normalized_time == at(101)
    proof = {
        "evidence": "SYNTHETIC_ONLY", "interface_version": "M23_V1",
        "policy_is_live_approval": False, "provider_coverage_proven": False,
        "forwarded_quote_ids": quote_ids, "forwarded_trade_snapshot_ids": trade_ids,
        "pacific_times": [format_pacific(item.evaluated_at) for item in recorded],
        "decisions": [json.loads(item.to_json()) for item in recorded],
    }
    Path("/tmp/m23-quote-events-proof.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")


@pytest.mark.parametrize("field", ["max_quote_age_seconds", "max_trade_age_seconds",
                                  "max_observation_gap_seconds"])
@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan"), "3"])
def test_policy_rejects_missing_numeric_meaning(field, value):
    with pytest.raises(RecordError):
        policy(**{field: value})


@pytest.mark.parametrize("value", [None, "", "  ", "unknown", " UnSpEcIfIeD "])
def test_policy_requires_known_version(value):
    with pytest.raises(RecordError):
        policy(version=value)


def test_no_policy_or_no_evidence_cannot_make_usable_data():
    subject = stream(policy=None)
    subject.connect(at(0))
    q = quote("q", 0)
    result = subject.consume(q, at=at(0))
    assert "MISSING_POLICY" in result.reasons
    assert confirm(subject, q, 0).action == "CONTINUITY_REJECTED"
    other = stream()
    other.connect(at(0))
    assert not other.consume(q, at=at(0)).usable
    assert not other.inspect(at(0)).usable


@pytest.mark.parametrize("value", [None, "", " ", "UNKNOWN", " unknown ", "UNSPECIFIED", " UnSpEcIfIeD "])
def test_unknown_continuity_reference_is_never_proof(value):
    subject = stream()
    subject.connect(at(0))
    q = quote("q", 0)
    subject.consume(q, at=at(0))
    result = confirm(subject, q, 0, evidence_reference=value)
    assert result.action == "CONTINUITY_REJECTED" and not result.usable


@pytest.mark.parametrize("seconds,quote_stale,trade_stale", [
    (3, False, False), (3.001, True, False), (5, True, False), (5.001, True, True),
])
def test_independent_ages_keep_inclusive_boundaries(seconds, quote_stale, trade_stale):
    result = primed().inspect(at(seconds))
    assert ("QUOTE_STALE" in result.reasons) is quote_stale
    assert ("TRADE_STALE" in result.reasons) is trade_stale
    assert result.quote_age_seconds == pytest.approx(seconds)
    assert result.trade_age_seconds == pytest.approx(seconds)
    assert not result.forward_quote and not result.forward_trade


@pytest.mark.parametrize("quote_seconds,trade_seconds,reason", [
    (0, 4, "QUOTE_STALE"), (6, 0, "TRADE_STALE"),
])
def test_new_sides_do_not_refresh_trade_or_new_trade_refresh_sides(quote_seconds, trade_seconds, reason):
    subject = primed()
    result = subject.consume(quote("mixed", quote_seconds, trade_seconds=trade_seconds),
                             at=at(max(quote_seconds, trade_seconds)))
    assert reason in result.reasons and not result.usable
    assert not result.forward_quote and not result.forward_trade


def test_duplicate_cache_reads_preserve_original_time_and_do_not_fill_gap():
    subject = primed()
    current = subject.inspect(at(0)).quote
    for seconds in (1, 2, 3, 4, 5, 6, 6.001):
        copy = replace(current, record_id=f"copy-{seconds}", metadata=replace(
            current.metadata, received_time=at(seconds), available_time=at(seconds),
            normalized_time=at(seconds + 100), sequence=100))
        result = subject.consume(copy, at=at(seconds))
        assert result.action == "DUPLICATE" and result.quote == current
        assert not result.forward_quote and not result.forward_trade
    assert result.continuity == "LOST" and "OBSERVATION_GAP" in result.reasons
    assert result.quote.metadata.available_time == at(0)


def test_missing_snapshot_cannot_be_healed_by_same_time_cache_repeat():
    subject = primed()
    original = subject.inspect(at(0)).quote
    missing = replace(original, record_id="missing", quote_time=None, trade_time=None,
                      bid=None, ask=None, last=None, status="MISSING")
    subject.consume(missing, at=at(1))
    result = subject.consume(replace(original, record_id="cache"), at=at(1))
    assert result.action == "REPEATED_TIMESTAMPS" and result.quote == missing
    assert not result.usable and not result.forward_quote and not result.forward_trade
    assert not confirm(subject, missing, 1).usable


@pytest.mark.parametrize("change,reason", [
    ({"delayed": True}, "DELAYED"), ({"delayed": None}, "DELAY_UNKNOWN"),
    ({"status": "CROSSED"}, "QUOTE_STATUS_CROSSED"), ({"bid": 0}, "MISSING_POSITIVE_SIDES"),
    ({"ask": None}, "MISSING_POSITIVE_SIDES"), ({"last": 0}, "MISSING_POSITIVE_LAST"),
    ({"quote_time": None}, "QUOTE_TIME_UNKNOWN"), ({"trade_time": None}, "TRADE_TIME_UNKNOWN"),
    ({"status": "STALE"}, "QUOTE_STATUS_STALE"),
])
def test_bad_snapshot_cannot_restore_continuity(change, reason):
    subject = primed()
    q = quote("bad", 1, **change)
    result = subject.consume(q, at=at(1))
    assert reason in result.reasons and not result.usable
    assert not confirm(subject, q, 1).usable


@pytest.mark.parametrize("quality", ["UNKNOWN", "UNAVAILABLE", "INVALID", "STALE", "DEGRADED_PROXY"])
def test_source_quality_is_never_upgraded(quality):
    subject = primed()
    q = quote("bad-source", 1)
    q = replace(q, metadata=replace(q.metadata, quality=quality))
    result = subject.consume(q, at=at(1))
    assert "SOURCE_QUALITY_" + quality in result.reasons
    assert not confirm(subject, q, 1).usable


def test_out_of_order_snapshot_never_blends_new_trade_into_old_sides():
    subject = primed()
    accepted = subject.consume(quote("new", 2), at=at(2))
    result = subject.consume(quote("late", 1, trade_seconds=3), at=at(3))
    assert result.action == "OUT_OF_ORDER" and result.quote == accepted.quote
    assert not result.usable and not result.forward_trade


@pytest.mark.parametrize("field,value", [("bid", 99), ("last", 101), ("last_size", 5), ("ask_size", 5)])
def test_same_time_changed_facts_are_conflicts_even_with_new_sequence(field, value):
    subject = primed()
    q = quote("conflict", 0, **{field: value})
    q = replace(q, metadata=replace(q.metadata, sequence=10))
    result = subject.consume(q, at=at(1))
    assert result.action == "CONFLICT" and not result.usable
    assert result.quote.record_id == "initial"


def test_reused_current_id_cannot_replace_frozen_facts():
    subject = primed()
    result = subject.consume(quote("initial", 1), at=at(1))
    assert result.action == "IDENTITY_CONFLICT" and not result.usable
    assert result.quote.quote_time == at(0)


def test_revision_is_retained_but_cannot_forward_or_confirm():
    subject = primed()
    original = subject.inspect(at(0))
    original_json = original.to_json()
    q = quote("corrected", 0, bid=99)
    q = replace(q, metadata=replace(q.metadata, revision=1))
    result = subject.consume(q, at=at(1))
    assert result.action == "REVISION" and result.quote.bid == 99
    assert not result.forward_quote and not result.forward_trade
    assert not confirm(subject, q, 1).usable
    assert original.to_json() == original_json


@pytest.mark.parametrize("field,value", [
    ("source", "OTHER"), ("instrument_id", "MSFT"), ("instrument_type", "ETF"),
    ("session", "2026-07-01"), ("data_mode", "UNKNOWN"),
])
def test_other_scope_cannot_replace_current_snapshot(field, value):
    subject = primed()
    q = quote("other", 1)
    q = replace(q, metadata=replace(q.metadata, **{field: value}))
    result = subject.consume(q, at=at(1))
    assert result.action == "SCOPE_MISMATCH" and result.quote.record_id == "initial"
    assert not result.forward_quote and not result.forward_trade


def test_future_available_input_does_not_leak_before_receipt():
    subject = primed()
    q = quote("future", 2, available_seconds=4)
    result = subject.consume(q, at=at(2))
    assert result.action == "NOT_AVAILABLE" and result.quote.record_id == "initial"
    assert not result.forward_quote and not result.forward_trade
    assert subject.consume(q, at=at(4)).action == "ACCEPTED"


def test_unknown_or_future_source_time_cannot_confirm():
    for source_time, reason in ((None, "SOURCE_TIME_UNKNOWN"), (at(5), "INVALID_SOURCE_TIME")):
        subject = primed()
        before = subject.inspect(at(0))
        before_json = before.to_json()
        q = quote("source-time", 1)
        q = replace(q, metadata=replace(q.metadata, source_time=source_time))
        result = subject.consume(q, at=at(1))
        assert result.quote == q and result.input_record_id == q.record_id
        assert result.quote.metadata.source_time == source_time
        assert reason in result.reasons and not result.usable
        assert result.continuity == "LOST" and result.epoch > before.epoch
        assert not result.forward_quote and not result.forward_trade
        assert confirm(subject, q, 1).action == "CONTINUITY_REJECTED"
        if source_time is not None:
            cached = subject.consume(replace(before.quote, record_id="old-cache"), at=at(1))
            assert cached.action == "REPEATED_TIMESTAMPS" and cached.quote == q
            assert reason in cached.reasons and not cached.usable
            assert not cached.forward_quote and not cached.forward_trade
        inspected = subject.inspect(at(5))
        assert inspected.quote == q and reason in inspected.reasons and not inspected.usable
        assert confirm(subject, q, 5).action == "CONTINUITY_REJECTED"
        assert not confirm(subject, before.quote, 5, epoch=before.epoch).usable
        if source_time is not None:
            assert result.action == "INVALID_SOURCE_TIME"
            cached = subject.consume(replace(q, record_id="future-cache"), at=at(5))
            assert cached.quote.metadata.source_time == source_time
            assert "INVALID_SOURCE_TIME" in cached.reasons and not cached.usable
            assert not cached.forward_quote and not cached.forward_trade
        fresh = quote("recovery", 6)
        recovered = subject.consume(fresh, at=at(6))
        assert not recovered.usable and not recovered.forward_quote and not recovered.forward_trade
        assert confirm(subject, fresh, 6).usable
        forwarded = subject.consume(quote("next", 7), at=at(7))
        assert forwarded.usable and forwarded.forward_quote and forwarded.forward_trade
        assert before.to_json() == before_json


@pytest.mark.parametrize("source_time,reason", [
    (None, "SOURCE_TIME_UNKNOWN"),
    (at(0) - timedelta(days=1), "SOURCE_SESSION_MISMATCH"),
    (at(-1), "SOURCE_BEFORE_RECOVERY"),
])
def test_repeated_timestamps_cannot_hide_invalid_source_time(source_time, reason):
    subject = primed()
    before = subject.inspect(at(0))
    original = before.quote
    original_json = before.to_json()
    bad = replace(original, record_id="bad-source-time", metadata=replace(
        original.metadata, source_time=source_time,
        received_time=at(1), available_time=at(1), normalized_time=at(101)))
    result = subject.consume(Quote.from_json(bad.to_json()), at=at(1))
    assert result.quote == bad and result.input_record_id == bad.record_id
    assert reason in result.reasons and not result.usable
    assert result.continuity == "LOST" and result.epoch > before.epoch
    assert not result.forward_quote and not result.forward_trade
    inspected = subject.inspect(at(1))
    assert inspected.quote == bad and reason in inspected.reasons and not inspected.usable
    rejected = confirm(subject, bad, 1)
    assert rejected.action == "CONTINUITY_REJECTED" and not rejected.usable
    repeated = subject.consume(replace(original, record_id="cache"), at=at(1))
    assert repeated.action == "REPEATED_TIMESTAMPS" and repeated.quote == bad
    assert reason in repeated.reasons and not repeated.usable
    assert not repeated.forward_quote and not repeated.forward_trade
    assert not confirm(subject, original, 1, epoch=before.epoch).usable
    fresh = quote("recovery", 2)
    recovered = subject.consume(fresh, at=at(2))
    assert not recovered.usable and not recovered.forward_quote and not recovered.forward_trade
    assert confirm(subject, fresh, 2).usable
    forwarded = subject.consume(quote("next", 3), at=at(3))
    assert forwarded.usable and forwarded.forward_quote and forwarded.forward_trade
    assert before.to_json() == original_json


def test_source_before_recovery_cannot_be_used_as_recovery_proof():
    subject = primed()
    subject.disconnect(at(1))
    subject.connect(at(2))
    q = quote("source-old", 3)
    q = replace(q, metadata=replace(q.metadata, source_time=at(0)))
    subject.consume(q, at=at(3))
    assert confirm(subject, q, 3).action == "CONTINUITY_REJECTED"


def test_disconnect_reconnect_and_wrong_checkpoint_need_new_proof():
    subject = primed()
    before = subject.inspect(at(0))
    subject.disconnect(at(1))
    q = quote("disconnected", 1)
    assert subject.consume(q, at=at(1)).action == "DISCONNECTED"
    subject.connect(at(2))
    assert not confirm(subject, before.quote, 2).usable
    fresh = quote("fresh", 3)
    assert not subject.consume(fresh, at=at(3)).usable
    assert not confirm(subject, fresh, 3, epoch=before.epoch).usable
    assert not confirm(subject, fresh, 3, record_id="wrong-record").usable
    assert not confirm(subject, fresh, 3, epoch=True).usable
    assert confirm(subject, fresh, 3).usable


def test_external_gap_rejects_prior_checkpoint_and_waits_for_new_data():
    subject = primed()
    initial = subject.inspect(at(0)).quote
    subject.mark_gap(at(1))
    assert not confirm(subject, initial, 1).usable
    fresh = quote("fresh", 2)
    assert not subject.consume(fresh, at=at(2)).usable
    result = confirm(subject, fresh, 2)
    assert result.usable and not result.forward_quote and not result.forward_trade


def test_same_time_reconnect_cannot_reuse_snapshot_from_before_disconnect():
    subject = primed()
    old = subject.inspect(at(0)).quote
    subject.disconnect(at(0))
    subject.connect(at(0))
    assert not confirm(subject, old, 0).usable
    repeat = subject.consume(replace(old, record_id="same-time-repeat"), at=at(0))
    assert repeat.action == "DUPLICATE"
    assert not confirm(subject, old, 0).usable
    fresh = quote("post-reconnect", 0.001)
    subject.consume(fresh, at=at(0.001))
    assert confirm(subject, fresh, 0.001).usable


def test_supplied_sequence_jump_does_not_invent_missing_messages():
    subject = primed()
    fresh = quote("sequence-jump", 1)
    fresh = replace(fresh, metadata=replace(fresh.metadata, sequence=999))
    result = subject.consume(fresh, at=at(1))
    assert result.usable and result.forward_quote and result.forward_trade
    assert result.quote.metadata.sequence == 999


@pytest.mark.parametrize("session", [None, "", "not-a-date", "2026-02-30", "20260630"])
def test_session_identity_must_be_an_iso_calendar_date(session):
    with pytest.raises(RecordError):
        stream(session=session)


def test_session_rollover_is_not_fresh_same_session_data():
    result = primed().inspect(at(24 * 60 * 60))
    assert "SESSION_MISMATCH" in result.reasons and not result.usable


@pytest.mark.parametrize("value", [START.replace(tzinfo=None), "2026-06-30T06:35:00", None])
def test_evaluation_requires_explicit_time_zone(value):
    with pytest.raises((RecordError, ValueError)):
        stream().connect(value)


def test_backwards_evaluation_rejected_and_results_are_immutable():
    subject = primed()
    result = subject.inspect(at(1))
    saved = result.to_json()
    with pytest.raises(RecordError):
        subject.inspect(at(0))
    with pytest.raises(FrozenInstanceError):
        result.epoch = 42
    detached = result.as_dict()
    detached["quote"]["bid"] = 1
    detached["policy"]["max_quote_age_seconds"] = 100
    subject.consume(quote("next", 2), at=at(2))
    assert result.to_json() == saved


def test_crossed_quote_fails_in_existing_normalizer_before_event_path():
    with pytest.raises(RecordError):
        normalize_schwab_quote(
            {"quote": {"bidPrice": 101, "askPrice": 100,
                       "quoteTime": int(at(0).timestamp() * 1000)}},
            record_id="crossed", raw_symbol="AAPL", metadata=quote("q", 0).metadata,
            status="VALID", delayed=False,
        )
