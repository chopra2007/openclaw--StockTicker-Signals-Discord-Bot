"""M2.2 synthetic history coverage through the protected offline launcher."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine.historical_bars import (
    HistoryBatch, HistoryConventions, HistoryRequest, SchwabBarContext, normalize_schwab_history,
)
from consensus_engine.scanners import schwab_client
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata


PACIFIC = ZoneInfo("America/Los_Angeles")
MINUTE = timedelta(minutes=1)
SECOND = timedelta(seconds=1)


def at(clock, day="2026-06-30"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def request(**changes):
    values = dict(symbol="AAPL", start=at("06:30:00"), end=at("06:35:00"))
    values.update(changes)
    return HistoryRequest(**values)


def conventions(**changes):
    values = dict(timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
                  price="SYNTHETIC_TRADES", volume="SYNTHETIC_SHARES",
                  coverage_basis="SYNTHETIC_COMPLETE", finality="SYNTHETIC_FINAL_MESSAGE",
                  publication="SYNTHETIC_ORIGINAL_RECEIPT", evidence_reference="M22_SYNTHETIC_V1")
    values.update(changes)
    return HistoryConventions(**values)


def raw_and_contexts(req=None):
    req = req or request()
    candles, contexts = [], []
    for number, interval in enumerate(req.expected_intervals()):
        candles.append(dict(datetime=int(interval.start.timestamp() * 1000), open=100.0,
                            high=101.0 + number, low=99.0, close=100.5, volume=10 + number))
        contexts.append(SchwabBarContext(
            record_id=f"history-{number}", start=interval.start, end=interval.end, is_final=True,
            metadata=SourceMetadata(
                instrument_id=req.symbol, source="SCHWAB", source_time=interval.start,
                received_time=interval.end, available_time=interval.end,
                normalized_time=at("13:30:00", interval.session), session=interval.session,
                instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY", quality="VALID",
            ),
        ))
    return {"symbol": schwab_client.to_schwab_symbol(req.symbol), "candles": candles, "empty": not candles}, tuple(contexts)


def batch(req=None, conv=None):
    req = req or request()
    raw, contexts = raw_and_contexts(req)
    return normalize_schwab_history(raw, request=req, contexts=contexts, conventions=conv or conventions())


def statuses(coverage):
    return [item.status for item in coverage.intervals]


def test_request_raw_mapping_coverage_and_archive_end_to_end(monkeypatch):
    req = request()
    raw, contexts = raw_and_contexts(req)
    # The last opening minute is reported late; its original receipt must survive.
    late = at("06:35:02")
    contexts = (*contexts[:-1], replace(contexts[-1], metadata=replace(
        contexts[-1].metadata, received_time=late, available_time=late)))
    calls = []

    def transport(path, params):
        calls.append((path, deepcopy(params)))
        return deepcopy(raw)

    monkeypatch.setattr(schwab_client, "_get", transport)
    payload = schwab_client.get_price_history_payload(**req.provider_kwargs())
    result = normalize_schwab_history(payload, request=req, contexts=contexts, conventions=conventions())
    assert calls == [("/pricehistory", {
        "symbol": "AAPL", "frequencyType": "minute", "frequency": 1,
        "needExtendedHoursData": "false", "periodType": "day",
        "startDate": int(req.start.timestamp() * 1000), "endDate": int(req.end.timestamp() * 1000),
    })]
    before = result.coverage_at(at("06:34:59"))
    boundary = result.coverage_at(at("06:35:00"))
    ready = result.coverage_at(late)
    assert statuses(before) == ["FINAL"] * 4 + ["NOT_ENDED"]
    assert statuses(boundary) == ["FINAL"] * 4 + ["MISSING"]
    assert not before.complete and not boundary.complete
    assert ready.complete and len(ready.final_bars) == 5
    assert sum(bar.volume for bar in ready.final_bars) == 60
    assert ready.final_bars[-1].metadata.available_time == late
    assert ready.final_bars[-1].metadata.normalized_time == at("13:30:00")
    archive = json.loads(json.dumps(result.as_dict(), sort_keys=True))
    restored = HistoryBatch(req, "SCHWAB", conventions(), tuple(
        Bar.from_json(json.dumps(value)) for value in archive["bars"]))
    assert restored.coverage_at(late).as_dict() == ready.as_dict()
    proof = {"evidence": "SYNTHETIC_ONLY", "batch": archive, "before": before.as_dict(),
             "boundary": boundary.as_dict(), "ready": ready.as_dict()}
    Path("/tmp/m22-history-proof.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")


@pytest.mark.parametrize("day,count", [
    ("2026-06-30", 390), ("2026-11-27", 210), ("2026-07-03", 0), ("2026-07-04", 0),
])
def test_calendar_expected_minutes_use_real_sessions_and_early_close(day, count):
    req = request(start=at("00:00:00", day), end=at("23:59:00", day))
    intervals = req.expected_intervals()
    assert len(intervals) == count
    if count:
        assert intervals[0].start == at("06:30:00", day)
        assert intervals[-1].end == at("10:00:00" if count == 210 else "13:00:00", day)
    else:
        assert not HistoryBatch(req, "SCHWAB", conventions(), ()).coverage_at(req.end).complete


@pytest.mark.parametrize("day,hour", [("2026-03-06", 14), ("2026-03-09", 13),
                                      ("2026-10-30", 13), ("2026-11-02", 14)])
def test_request_crosses_seasonal_clock_change_without_fixed_offset(day, hour):
    intervals = request(start=at("06:30:00", day), end=at("06:35:00", day)).expected_intervals()
    assert len(intervals) == 5
    assert intervals[0].start.hour == hour and intervals[0].start.minute == 30


@pytest.mark.parametrize("scope,count", [("PREMARKET", 330), ("PREMARKET_AND_REGULAR", 720)])
def test_premarket_has_explicit_start_and_separate_requested_coverage(scope, count):
    req = request(start=at("00:00:00"), end=at("23:59:00"),
                  session_scope=scope, premarket_start=time(1, 0))
    assert len(req.expected_intervals()) == count
    assert req.expected_intervals()[0].start == at("01:00:00")
    assert req.provider_kwargs()["extended_hours"] is True
    assert req.as_dict()["premarket_start"] == "01:00:00"


def test_daily_means_regular_sessions_and_includes_missing_previous_session():
    req = request(start=at("00:00:00", "2026-11-25"), end=at("00:00:00", "2026-11-28"), interval="1d")
    intervals = req.expected_intervals()
    assert [item.session for item in intervals] == ["2026-11-25", "2026-11-27"]
    assert intervals[1].end == at("10:00:00", "2026-11-27")
    history = batch(req)
    assert history.coverage_at(req.end).complete
    missing = replace(history, bars=(history.bars[1],))
    assert statuses(missing.coverage_at(req.end)) == ["MISSING", "FINAL"]


def test_premarket_and_regular_request_does_not_claim_returned_premarket():
    req = request(start=at("06:28:00"), session_scope="PREMARKET_AND_REGULAR", premarket_start=time(1))
    regular = batch()
    history = HistoryBatch(req, "SCHWAB", conventions(session="PREMARKET_AND_REGULAR"), regular.bars)
    coverage = history.coverage_at(req.end)
    assert statuses(coverage) == ["MISSING", "MISSING"] + ["FINAL"] * 5
    assert not coverage.complete


def test_extended_response_keeps_postmarket_outside_requested_coverage():
    req = request(start=at("06:28:00"), end=at("23:59:00"),
                  session_scope="PREMARKET", premarket_start=time(1))
    raw, contexts = raw_and_contexts(req)
    extra = dict(raw["candles"][0], datetime=int(at("13:05:00").timestamp() * 1000))
    context = replace(contexts[0], record_id="postmarket", start=at("13:05:00"), end=at("13:06:00"),
                      metadata=replace(contexts[0].metadata, source_time=at("13:05:00"),
                      received_time=at("13:06:00"), available_time=at("13:06:00")))
    history = normalize_schwab_history(dict(raw, candles=[*raw["candles"], extra]), request=req,
        contexts=(*contexts, context), conventions=conventions(session="PREMARKET"))
    coverage = history.coverage_at(at("13:10:00"))
    assert coverage.complete and len(coverage.final_bars) == 2
    assert coverage.outside_scope_record_ids == ("postmarket",)
    assert coverage.unexpected_record_ids == () and len(history.bars) == 3


@pytest.mark.parametrize("change", [
    {"interval": "5m"}, {"session_scope": "AFTER_HOURS"},
    {"session_scope": "PREMARKET"}, {"premarket_start": time(1, 0, 1)},
    {"premarket_start": time(1, tzinfo=PACIFIC)}, {"start": at("06:30:01")},
    {"start": datetime(2026, 6, 30)}, {"start": "2026-06-30"},
    {"end": at("06:30:00")}, {"symbol": " "},
    {"interval": "1d"}, {"interval": "1d", "session_scope": "PREMARKET", "premarket_start": time(1)},
    {"session_scope": "PREMARKET", "premarket_start": time(7)},
])
def test_invalid_or_ambiguous_history_requests_fail(change):
    with pytest.raises(ValueError):
        request(**change)


def test_empty_response_is_missing_not_zero_volume():
    history = normalize_schwab_history({"symbol": "AAPL", "candles": [], "empty": True},
                                     request=request(), contexts=(), conventions=conventions())
    result = history.coverage_at(at("06:35:00"))
    assert statuses(result) == ["MISSING"] * 5
    assert result.final_bars == () and not result.complete
    assert history.bars == ()


def test_provisional_bar_and_final_revision_have_distinct_availability():
    history = batch()
    final = history.bars[-1]
    provisional = replace(final, record_id="forming", is_final=False, metadata=replace(
        final.metadata, received_time=at("06:34:30"), available_time=at("06:34:30")))
    final = replace(final, record_id="final", metadata=replace(final.metadata, revision=1,
                    received_time=at("06:35:02"), available_time=at("06:35:02")))
    history = replace(history, bars=(*history.bars[:-1], provisional, final))
    assert statuses(history.coverage_at(at("06:35:00")))[-1] == "PROVISIONAL"
    assert not history.coverage_at(at("06:35:00")).complete
    assert history.coverage_at(at("06:35:02")).complete


def test_later_revision_never_changes_earlier_available_view():
    original = batch()
    before = original.coverage_at(at("06:35:00")).as_dict()
    changed = replace(original.bars[0], record_id="correction", high=900.0, metadata=replace(
        original.bars[0].metadata, revision=1, received_time=at("06:40:00"), available_time=at("06:40:00")))
    revised = replace(original, bars=(*original.bars, changed))
    assert revised.coverage_at(at("06:35:00")).as_dict() == before
    assert revised.coverage_at(at("06:40:00")).final_bars[0].high == 900
    assert original.bars[0].high == 101
    assert len(revised.as_dict()["bars"]) == 6


def test_new_invalid_revision_does_not_fall_back_to_old_final_bar():
    history = batch()
    correction = replace(history.bars[0], record_id="invalid-correction", metadata=replace(
        history.bars[0].metadata, revision=1, quality="INVALID", available_time=at("06:40:00")))
    revised = replace(history, bars=(*history.bars, correction))
    assert revised.coverage_at(at("06:35:00")).complete
    assert statuses(revised.coverage_at(at("06:40:00")))[0] == "QUALITY_INVALID"
    assert not revised.coverage_at(at("06:40:00")).complete


def test_duplicates_and_out_of_order_delivery_are_stable():
    history = batch()
    duplicate = replace(history.bars[0], record_id="duplicate")
    disorder = replace(history, bars=tuple(reversed((*history.bars, duplicate))))
    result = disorder.coverage_at(at("06:35:00"))
    assert result.complete and len(result.final_bars) == 5
    assert result.intervals[0].duplicate_count == 1
    assert sum(bar.volume for bar in result.final_bars) == 60
    assert [bar.start_time for bar in result.final_bars] == sorted(bar.start_time for bar in result.final_bars)


def test_later_redelivery_of_old_revision_cannot_replace_newer_revision():
    history = batch()
    old = history.bars[0]
    new = replace(old, record_id="new-revision", high=120, metadata=replace(
        old.metadata, revision=1, available_time=at("06:40:00")))
    redelivered = replace(old, record_id="redelivered", metadata=replace(
        old.metadata, available_time=at("06:41:00"), received_time=at("06:41:00")))
    result = replace(history, bars=(*history.bars, new, redelivered)).coverage_at(at("06:41:00"))
    assert result.complete and result.final_bars[0].record_id == "new-revision"


def test_refetch_keeps_earliest_available_copy_without_refreshing_market_facts():
    history = batch()
    before = history.coverage_at(at("06:35:00"))
    repeat = replace(history.bars[0], record_id="refetch", metadata=replace(
        history.bars[0].metadata, received_time=at("06:40:00"), available_time=at("06:40:00"),
        normalized_time=at("14:00:00")))
    refetched = replace(history, bars=(repeat, *history.bars))
    assert refetched.coverage_at(at("06:35:00")) == before
    after = refetched.coverage_at(at("06:40:00"))
    assert after.complete and after.intervals[0].duplicate_count == 1
    assert after.final_bars == history.bars
    assert len(refetched.as_dict()["bars"]) == 6


def test_equal_revision_conflict_blocks_only_when_available():
    history = batch()
    conflict = replace(history.bars[0], record_id="conflict", high=120,
                       metadata=replace(history.bars[0].metadata, available_time=at("06:40:00")))
    changed = replace(history, bars=(*history.bars, conflict))
    assert changed.coverage_at(at("06:35:00")).complete
    assert statuses(changed.coverage_at(at("06:40:00")))[0] == "CONFLICT"


def test_no_trade_requires_explicit_canonical_certification_and_invents_no_prices():
    history = batch()
    no_trade = replace(history.bars[0], record_id="no-trade", open=None, high=None, low=None,
                       close=None, volume=0, certified_no_trade=True)
    result = replace(history, bars=(no_trade, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert result.complete and statuses(result)[0] == "NO_TRADE"
    assert result.final_bars[0].high is None and result.final_bars[0].volume == 0
    with pytest.raises(RecordError):
        replace(no_trade, metadata=replace(no_trade.metadata, quality="UNKNOWN"))


@pytest.mark.parametrize("quality", ["UNKNOWN", "STALE", "INVALID", "DEGRADED_PROXY"])
def test_nonvalid_quality_never_becomes_complete(quality):
    history = batch()
    bad = replace(history.bars[0], metadata=replace(history.bars[0].metadata, quality=quality))
    result = replace(history, bars=(bad, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert not result.complete and statuses(result)[0] == "QUALITY_" + quality


@pytest.mark.parametrize("change", [
    {"timestamp": "UNKNOWN"}, {"session": "UNKNOWN"}, {"session": "CALENDAR_DAY"},
    {"adjustment_basis": "UNKNOWN"}, {"price": "UNKNOWN"}, {"volume": "UNKNOWN"},
    {"coverage_basis": "UNKNOWN"}, {"evidence_reference": None},
    {"evidence_reference": "UNKNOWN"}, {"evidence_reference": "UNSPECIFIED"},
    {"evidence_reference": " unknown "}, {"evidence_reference": " UnSpEcIfIeD "},
    {"finality": "UNKNOWN"}, {"publication": "UNKNOWN"},
])
def test_unknown_source_semantics_preserve_prices_but_block_coverage(change):
    history = batch(conv=conventions(**change))
    result = history.coverage_at(at("06:35:00"))
    assert statuses(result) == ["UNKNOWN_CONVENTIONS"] * 5
    assert not result.complete and result.final_bars == ()
    assert result.intervals[0].bar.close == 100.5


@pytest.mark.parametrize("field,value,status", [
    ("adjustment_basis", "SYNTHETIC_SPLIT_ADJUSTED", "INCOMPATIBLE_CONVENTIONS"),
    ("price_convention", "DIFFERENT_PRICE_BASIS", "INCOMPATIBLE_CONVENTIONS"),
    ("volume_convention", "DIFFERENT_VENUE", "INCOMPATIBLE_CONVENTIONS"),
])
def test_mixed_price_volume_adjustments_fail_coverage(field, value, status):
    history = batch()
    changed = replace(history.bars[0], **{field: value})
    result = replace(history, bars=(changed, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert not result.complete and statuses(result)[0] == status


def test_mixed_data_modes_do_not_silently_pool_sources():
    history = batch()
    changed = replace(history.bars[0], metadata=replace(history.bars[0].metadata, data_mode="OTHER_MODE"))
    result = replace(history, bars=(changed, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert not result.complete and statuses(result) == ["INCOMPATIBLE_MODE"] * 5
    with pytest.raises(RecordError, match="source or symbol"):
        replace(history, bars=(replace(changed, metadata=replace(changed.metadata, source="OTHER")),))


def test_start_stamp_is_not_assumed_and_end_stamp_must_match():
    history = batch(conv=conventions(timestamp="EXPLICIT"))
    source = history.bars[0].start_time - timedelta(hours=1)
    changed = replace(history.bars[0], metadata=replace(history.bars[0].metadata, source_time=source))
    explicit = replace(history, bars=(changed, *history.bars[1:]))
    assert explicit.coverage_at(at("06:35:00")).complete
    end_stamped = replace(explicit, conventions=conventions(timestamp="END"))
    assert statuses(end_stamped.coverage_at(at("06:35:00")))[0] == "INCOMPATIBLE_TIMESTAMP"


@pytest.mark.parametrize("wrong", ["session", "interval"])
def test_unexpected_session_or_interval_is_visible_and_blocks_complete(wrong):
    history = batch()
    bar = history.bars[0]
    if wrong == "session":
        bar = replace(bar, metadata=replace(bar.metadata, session="2026-06-29"))
    else:
        bar = replace(bar, start_time=bar.start_time - SECOND)
    result = replace(history, bars=(bar, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert result.unexpected_record_ids == (bar.record_id,)
    assert statuses(result)[0] == "MISSING" and not result.complete


def test_future_unexpected_bar_does_not_change_earlier_coverage():
    history = batch()
    future = replace(history.bars[0], record_id="future-extra", start_time=at("06:36:00"),
                     end_time=at("06:37:00"), metadata=replace(history.bars[0].metadata,
                     source_time=at("06:36:00"), available_time=at("06:37:00")))
    assert replace(history, bars=(*history.bars, future)).coverage_at(at("06:35:00")) == history.coverage_at(at("06:35:00"))


@pytest.mark.parametrize("kind", ["missing_symbol", "wrong_symbol", "missing_candles", "bad_empty", "missing_context", "bad_candle"])
def test_incomplete_or_contradictory_response_rejected(kind):
    raw, contexts = raw_and_contexts()
    if kind == "missing_symbol":
        raw.pop("symbol")
    elif kind == "wrong_symbol":
        raw["symbol"] = "MSFT"
    elif kind == "missing_candles":
        raw.pop("candles")
    elif kind == "bad_empty":
        raw["empty"] = True
    elif kind == "missing_context":
        contexts = contexts[:-1]
    else:
        raw["candles"][0].pop("volume")
    with pytest.raises(RecordError):
        normalize_schwab_history(raw, request=request(), contexts=contexts, conventions=conventions())


def test_same_record_id_cannot_hide_changed_facts_and_inputs_are_immutable():
    history = batch()
    with pytest.raises(RecordError, match="identity"):
        replace(history, bars=(*history.bars, replace(history.bars[0], high=120)))
    with pytest.raises(FrozenInstanceError):
        history.source = "OTHER"
    exported = history.as_dict()
    exported["bars"][0]["high"] = 999
    assert history.bars[0].high == 101


def test_finality_and_source_time_cannot_precede_their_required_instants():
    raw, contexts = raw_and_contexts()
    too_early = replace(contexts[0], metadata=replace(contexts[0].metadata,
        received_time=contexts[0].start, available_time=contexts[0].start))
    with pytest.raises(RecordError, match="final bar"):
        normalize_schwab_history(raw, request=request(), contexts=(too_early, *contexts[1:]),
                                conventions=conventions())
    history = batch(conv=conventions(timestamp="EXPLICIT"))
    future_source = replace(history.bars[0], metadata=replace(
        history.bars[0].metadata, source_time=at("07:00:00")))
    with pytest.raises(RecordError, match="source time"):
        replace(history, bars=(future_source, *history.bars[1:]))


def test_unavailable_record_has_no_values_and_blocks_coverage():
    history = batch()
    unavailable = replace(history.bars[0], open=None, high=None, low=None, close=None, volume=None,
                          metadata=replace(history.bars[0].metadata, quality="UNAVAILABLE"))
    result = replace(history, bars=(unavailable, *history.bars[1:])).coverage_at(at("06:35:00"))
    assert not result.complete and statuses(result)[0] == "QUALITY_UNAVAILABLE"
    assert result.intervals[0].bar.volume is None


def test_raw_request_and_legacy_table_share_identical_parameters(monkeypatch):
    req = request(symbol="BRK.B")
    raw, _ = raw_and_contexts(req)
    calls = []

    def transport(path, params):
        calls.append((path, dict(params)))
        return deepcopy(raw)

    monkeypatch.setattr(schwab_client, "_get", transport)
    observed = schwab_client.get_price_history_payload(**req.provider_kwargs())
    legacy = schwab_client.get_price_history(**req.provider_kwargs())
    assert observed == raw and calls[0] == calls[1]
    assert list(legacy.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert legacy.index.name == "Date" and len(legacy) == 5
    assert legacy.iloc[0].to_dict() == {"Open": 100, "High": 101, "Low": 99, "Close": 100.5, "Volume": 10}


def test_raw_request_errors_propagate_without_fallback(monkeypatch):
    def failed(path, params):
        raise RuntimeError("synthetic request failure")

    monkeypatch.setattr(schwab_client, "_get", failed)
    with pytest.raises(RuntimeError, match="synthetic request failure"):
        schwab_client.get_price_history_payload(**request().provider_kwargs())


def test_legacy_empty_response_still_returns_none(monkeypatch):
    monkeypatch.setattr(schwab_client, "_get", lambda *args: {"symbol": "AAPL", "candles": []})
    assert schwab_client.get_price_history(**request().provider_kwargs()) is None


async def test_existing_share_reader_consumes_legacy_daily_table_with_fake_transport(monkeypatch):
    from consensus_engine import trade_collector

    raw, _ = raw_and_contexts()
    monkeypatch.setattr(schwab_client, "_get", lambda *args: deepcopy(raw))
    monkeypatch.setattr(schwab_client, "get_quote", lambda ticker: {
        "bid": 100, "ask": 101, "c": 100.5, "quote_time": 0, "t": int(at("06:35:00").timestamp()),
    })
    monkeypatch.setattr(trade_collector.time, "time", lambda: at("06:35:00").timestamp())
    result = await trade_collector.SchwabQuoteProvider().share_quote(ticker="AAPL")
    assert result["average_daily_dollar_volume"] == 1206
    assert result["provider_timestamp"] is None
    assert result["underlying_price"] == 100.5
