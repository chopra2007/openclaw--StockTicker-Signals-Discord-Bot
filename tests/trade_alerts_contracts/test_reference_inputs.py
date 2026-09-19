"""M2.4 supplied references -> coverage -> recording, under offline protection."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from functools import lru_cache
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine.analysis import wolf_scope
from consensus_engine.historical_bars import (
    HistoryBatch, HistoryConventions, HistoryRequest, SchwabBarContext, normalize_schwab_history,
)
from consensus_engine.quote_events import QuoteEventPolicy, QuoteEventStream
from consensus_engine.reference_inputs import (
    ETF_REFERENCES, EXPECTED_REFERENCES, ReferenceScope, build_reference_snapshot,
)
from consensus_engine.scanners.schwab_normalization import normalize_schwab_quote
from consensus_engine.trade_alerts_models import Bar, Quote, RecordError, SourceMetadata
from consensus_engine.utils.time_context import format_pacific


PACIFIC = ZoneInfo("America/Los_Angeles")
START = datetime(2026, 6, 30, 6, 35, tzinfo=PACIFIC)
POLICY = QuoteEventPolicy("M24_SYNTHETIC_ONLY", 3, 5, 10)
SESSION = "2026-06-30"


def at(seconds=0):
    return START + timedelta(seconds=seconds)


def scope(symbol="SPY", **changes):
    values = dict(symbol=symbol, source="SCHWAB", quote_data_mode="SYNTHETIC_QUOTE",
                  history_data_mode="SYNTHETIC_HISTORY", quote_policy=POLICY,
                  history_request=HistoryRequest(symbol, at(-60), at()))
    values.update(changes)
    return ReferenceScope(**values)


def quote(symbol="SPY", seconds=0, **changes):
    result = normalize_schwab_quote(
        {"symbol": symbol, "quote": {"quoteTime": int(at(seconds).timestamp() * 1000),
         "tradeTime": int(at(seconds).timestamp() * 1000), "bidPrice": 100.0,
         "askPrice": 100.2, "lastPrice": 100.1, "bidSize": 2, "askSize": 3, "lastSize": 1}},
        record_id=f"{symbol}-q-{seconds}", raw_symbol=symbol, status="VALID", delayed=False,
        metadata=SourceMetadata(
            source="SCHWAB", instrument_id=symbol, instrument_type="ETF", session=SESSION,
            data_mode="SYNTHETIC_QUOTE", quality="VALID", source_time=at(seconds),
            received_time=at(seconds), available_time=at(seconds), normalized_time=at(seconds + 100)),
    )
    return Quote.from_json(replace(result, **changes).to_json())


def primed(symbol="SPY", policy=POLICY):
    stream = QuoteEventStream(source="SCHWAB", instrument_id=symbol, instrument_type="ETF",
                              session=SESSION, data_mode="SYNTHETIC_QUOTE", policy=policy)
    stream.connect(at())
    initial = quote(symbol)
    first = stream.consume(initial, at=at())
    result = stream.confirm_continuity(at=at(), epoch=first.epoch, record_id=initial.record_id,
                                      evidence_reference="M24_SYNTHETIC_CONTINUITY")
    assert result.usable
    return stream


@lru_cache(maxsize=32)
def history(symbol="SPY", delay=0):
    req = scope(symbol).history_request
    conventions = HistoryConventions(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="SYNTHETIC_TRADES", volume="SYNTHETIC_SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT", evidence_reference="M24_SYNTHETIC")
    context = SchwabBarContext(
        record_id=f"{symbol}-b", start=at(-60), end=at(), is_final=True,
        metadata=SourceMetadata(
            source="SCHWAB", instrument_id=symbol, instrument_type="ETF", session=SESSION,
            data_mode="SYNTHETIC_HISTORY", quality="VALID", source_time=at(-60),
            received_time=at(delay), available_time=at(delay), normalized_time=at(delay + 100)),
    )
    result = normalize_schwab_history(
        {"symbol": symbol, "candles": [{"datetime": int(at(-60).timestamp() * 1000),
         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10}]},
        request=req, contexts=(context,), conventions=conventions)
    return replace(result, bars=tuple(Bar.from_json(bar.to_json()) for bar in result.bars))


def snapshot(seconds=0, **changes):
    values = dict(evaluated_at=at(seconds), session=SESSION,
                  scopes=tuple(scope(symbol) for symbol in ETF_REFERENCES),
                  quote_decisions={}, histories={})
    values.update(changes)
    return build_reference_snapshot(**values)


def rows(value):
    return {row.symbol: row for row in value.references}


def test_supplied_reference_coverage_recording_end_to_end():
    streams = {symbol: primed(symbol) for symbol in ETF_REFERENCES if symbol not in ("QQQ", "XLV")}
    streams["XLE"].consume(quote("XLE", 1, delayed=True, status="STALE"), at=at(1))
    streams["XLP"].disconnect(at(1))
    histories = {symbol: history(symbol, delay=2 if symbol == "XLK" else 0)
                 for symbol in ETF_REFERENCES if symbol != "XLF"}
    first = snapshot(1, quote_decisions={symbol: stream.inspect(at(1)) for symbol, stream in streams.items()},
                     histories=histories, stock_symbols=("NVDA", "ZZZZ"))
    first_bytes = first.to_json()
    first_rows = rows(first)
    assert first.as_dict()["usable_quote_count"] == 9
    assert first.as_dict()["complete_history_count"] == 11
    assert first_rows["SPY"].quote_usable and first_rows["SPY"].history_complete
    assert first_rows["QQQ"].quote_decision is None and first_rows["QQQ"].history_complete
    assert "DELAYED" in first_rows["XLE"].quote_reasons
    assert "DISCONNECTED" in first_rows["XLP"].quote_reasons
    assert first_rows["XLK"].history.intervals[0].status == "MISSING"
    assert first_rows["XLF"].history.intervals[0].status == "MISSING"
    assert first_rows["VIX"].quote_reasons == ("UNSUPPORTED_INDEX_INPUT",)
    assert first.current_sector_mappings == (("NVDA", "XLK"), ("ZZZZ", None))
    second = snapshot(4, quote_decisions={symbol: stream.inspect(at(4)) for symbol, stream in streams.items()},
                      histories=histories, stock_symbols=("ZZZZ", "NVDA"))
    assert second.as_dict()["usable_quote_count"] == 0
    assert second.as_dict()["complete_history_count"] == 12
    assert rows(second)["XLK"].history_complete
    assert "QUOTE_STALE" in rows(second)["SPY"].quote_reasons
    assert first.to_json() == first_bytes
    # Identical inputs in another insertion order give identical recording bytes.
    repeated = snapshot(4, quote_decisions={symbol: streams[symbol].inspect(at(4))
                                           for symbol in reversed(tuple(streams))},
                        histories=dict(reversed(tuple(histories.items()))), stock_symbols=("NVDA", "ZZZZ"))
    assert repeated.to_json() == second.to_json()
    proof = {"evidence": "SYNTHETIC_ONLY", "snapshots": [first.as_dict(), second.as_dict()],
             "display_times": [format_pacific(at(1)), format_pacific(at(4))]}
    Path("/tmp/m24-reference-inputs-proof.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")


def test_each_expected_etf_is_independent_and_vix_is_not_counted():
    decisions = {symbol: primed(symbol).inspect(at()) for symbol in ETF_REFERENCES}
    histories = {symbol: history(symbol) for symbol in ETF_REFERENCES}
    full = snapshot(quote_decisions=decisions, histories=histories)
    assert tuple(rows(full)) == EXPECTED_REFERENCES
    assert len(ETF_REFERENCES) == 13
    assert full.as_dict()["usable_quote_count"] == full.as_dict()["complete_history_count"] == 13
    for symbol in ETF_REFERENCES:
        missing = snapshot(quote_decisions={key: value for key, value in decisions.items() if key != symbol},
                           histories={key: value for key, value in histories.items() if key != symbol})
        assert missing.as_dict()["usable_quote_count"] == missing.as_dict()["complete_history_count"] == 12
        assert not rows(missing)[symbol].quote_usable and not rows(missing)[symbol].history_complete


def test_no_inputs_never_invents_zero_prices_or_coverage():
    result = snapshot()
    assert result.as_dict()["usable_quote_count"] == result.as_dict()["complete_history_count"] == 0
    assert all(row.quote_decision is None for row in result.references)
    assert all(rows(result)[symbol].history.intervals[0].bar is None for symbol in ETF_REFERENCES)
    absent_scopes = snapshot(scopes=())
    assert rows(absent_scopes)["SPY"].quote_reasons == ("MISSING_REFERENCE_SCOPE",)


def test_vix_cannot_be_supplied_as_an_etf_or_substituted_with_a_proxy():
    vix_stream = primed("VIX")
    result = snapshot(quote_decisions={"VIX": vix_stream.inspect(at())}, histories={"VIX": history("SPY")})
    assert rows(result)["VIX"].quote_decision is None
    assert not rows(result)["VIX"].quote_usable and not rows(result)["VIX"].history_complete
    with pytest.raises(RecordError):
        scope("VIX")
    with pytest.raises(RecordError):
        snapshot(quote_decisions={"UVXY": primed().inspect(at())})


@pytest.mark.parametrize("field,value", [
    ("instrument_id", "QQQ"), ("source", "OTHER_SOURCE"), ("session", "2026-06-29"),
    ("instrument_type", "EQUITY"), ("data_mode", "OTHER_MODE"),
])
def test_wrong_quote_scope_cannot_fill_reference(field, value):
    decision = primed().inspect(at())
    bad = replace(decision, quote=replace(decision.quote, metadata=replace(decision.quote.metadata, **{field: value})))
    row = rows(snapshot(quote_decisions={"SPY": bad}))["SPY"]
    assert not row.quote_usable and row.quote_decision is None
    assert row.quote_reasons == ("QUOTE_SCOPE_MISMATCH",)


def test_future_decision_and_future_quote_are_absent_before_availability():
    decision = primed().inspect(at(1))
    row = rows(snapshot(quote_decisions={"SPY": decision}))["SPY"]
    assert row.quote_decision is None and row.quote_reasons == ("FUTURE_QUOTE_DECISION",)
    decision = replace(decision, evaluated_at=at(), quote=quote(seconds=1))
    row = rows(snapshot(quote_decisions={"SPY": decision}))["SPY"]
    assert row.quote_decision is None and row.quote_reasons == ("QUOTE_NOT_AVAILABLE",)


@pytest.mark.parametrize("component", ["quote_time", "trade_time"])
def test_future_component_cannot_enter_a_current_reference_decision(component):
    # Canonical records reject future component times before the event stream
    # can evaluate them. Later availability must instead wait for its own time.
    with pytest.raises(RecordError, match=component + " cannot follow available_time"):
        quote(**{component: at(1)})
    stream = primed()
    result = stream.consume(quote(seconds=1), at=at())
    assert result.action == "NOT_AVAILABLE"
    row = rows(snapshot(quote_decisions={"SPY": result}))["SPY"]
    assert row.quote_decision.quote.record_id == "SPY-q-0"
    assert row.quote_decision.quote.quote_time == at()
    assert row.quote_decision.quote.trade_time == at()


def test_omitted_history_request_does_not_invalidate_supplied_quote():
    row = rows(snapshot(scopes=(scope(history_request=None),),
                        quote_decisions={"SPY": primed().inspect(at())},
                        histories={"SPY": history()}))["SPY"]
    assert row.quote_usable
    assert not row.history_complete and row.history is None
    assert row.history_reasons == ("MISSING_HISTORY_REQUEST",)


def test_old_usable_decision_requires_current_age_and_continuity_check():
    stream = primed()
    old = stream.inspect(at())
    row = rows(snapshot(4, quote_decisions={"SPY": old}))["SPY"]
    assert not row.quote_usable and row.quote_decision == old
    assert "QUOTE_DECISION_TIME_MISMATCH" in row.quote_reasons
    row = rows(snapshot(4, quote_decisions={"SPY": stream.inspect(at(4))}))["SPY"]
    assert "QUOTE_STALE" in row.quote_reasons and not row.quote_usable


def test_fresh_sides_cannot_make_stale_last_trade_usable():
    stream = primed()
    stream.consume(quote(seconds=6, trade_time=at()), at=at(6))
    row = rows(snapshot(6, quote_decisions={"SPY": stream.inspect(at(6))}))["SPY"]
    assert row.quote_decision.quote_age_seconds == 0
    assert row.quote_decision.trade_age_seconds == 6
    assert "TRADE_STALE" in row.quote_reasons and not row.quote_usable


@pytest.mark.parametrize("quality", ["STALE", "UNAVAILABLE", "DEGRADED_PROXY", "INVALID", "UNKNOWN"])
def test_source_quality_is_preserved_per_reference(quality):
    stream = primed()
    bad = quote(seconds=1)
    stream.consume(replace(bad, metadata=replace(bad.metadata, quality=quality)), at=at(1))
    row = rows(snapshot(1, quote_decisions={"SPY": stream.inspect(at(1))}))["SPY"]
    assert not row.quote_usable and "SOURCE_QUALITY_" + quality in row.quote_reasons
    assert row.quote_decision.quote.metadata.quality == quality


def test_reconnect_requires_its_own_new_data_and_coverage_proof():
    spy, qqq = primed(), primed("QQQ")
    spy.disconnect(at(1))
    state = spy.connect(at(2))
    result = snapshot(2, quote_decisions={"SPY": state, "QQQ": qqq.inspect(at(2))})
    assert not rows(result)["SPY"].quote_usable and rows(result)["QQQ"].quote_usable
    fresh = quote(seconds=3)
    state = spy.consume(fresh, at=at(3))
    restored = spy.confirm_continuity(at=at(3), epoch=state.epoch, record_id=fresh.record_id,
                                      evidence_reference="M24_SYNTHETIC_RECOVERY")
    assert rows(snapshot(3, quote_decisions={"SPY": restored}))["SPY"].quote_usable
    assert not rows(result)["SPY"].quote_usable


@pytest.mark.parametrize("changed", [None, replace(POLICY, version="OTHER_SYNTHETIC_POLICY"),
                                    replace(POLICY, max_quote_age_seconds=4)])
def test_missing_or_different_supplied_policy_is_not_silently_used(changed):
    row = rows(snapshot(scopes=(scope(quote_policy=changed),),
                        quote_decisions={"SPY": primed().inspect(at())}))["SPY"]
    assert not row.quote_usable
    assert ("MISSING_QUOTE_POLICY" if changed is None else "QUOTE_POLICY_MISMATCH") in row.quote_reasons


@pytest.mark.parametrize("kind", ["symbol", "source", "request", "session", "mode", "type"])
def test_history_scope_and_coverage_cannot_be_borrowed(kind):
    batch = history()
    if kind == "symbol":
        batch = history("QQQ")
    elif kind == "source":
        batch = replace(batch, source="OTHER_SOURCE", bars=tuple(
            replace(bar, metadata=replace(bar.metadata, source="OTHER_SOURCE")) for bar in batch.bars))
    elif kind == "request":
        batch = replace(batch, request=replace(batch.request, start=at(-120)))
    else:
        change = {"session": {"session": "2026-06-29"}, "mode": {"data_mode": "OTHER_MODE"},
                  "type": {"instrument_type": "EQUITY"}}[kind]
        batch = replace(batch, bars=tuple(replace(bar, metadata=replace(bar.metadata, **change))
                                         for bar in batch.bars))
    row = rows(snapshot(histories={"SPY": batch}))["SPY"]
    assert not row.history_complete and row.history_reasons


def test_history_late_revision_does_not_change_old_view_and_unknown_conventions_block():
    batch = history()
    original = batch.bars[0]
    corrected = replace(original, record_id="SPY-corrected", high=102,
                        metadata=replace(original.metadata, revision=1, received_time=at(2), available_time=at(2)))
    batch = replace(batch, bars=(*batch.bars, corrected))
    before = snapshot(histories={"SPY": batch})
    after = snapshot(2, histories={"SPY": batch})
    assert rows(before)["SPY"].history.final_bars[0].high == 101
    assert rows(after)["SPY"].history.final_bars[0].high == 102
    unknown = replace(batch, conventions=replace(batch.conventions, evidence_reference=" unknown "))
    assert not rows(snapshot(histories={"SPY": unknown}))["SPY"].history_complete
    assert rows(before)["SPY"].history.final_bars[0].high == 101


def test_current_sector_mapping_stays_separate_from_historical_membership(monkeypatch):
    assert wolf_scope.stock_sector_etf("NVDA") == "XLK"
    first = snapshot(stock_symbols=("nvda", "ZZZZ"))
    assert first.current_sector_mappings == (("NVDA", "XLK"), ("ZZZZ", None))
    assert all(item["historical_membership"] == "UNAVAILABLE"
               for item in first.as_dict()["current_sector_mappings"])
    monkeypatch.setattr(wolf_scope, "_sector_map_cache", {"NVDA": "XLF"})
    later = snapshot(stock_symbols=("NVDA",))
    assert later.current_sector_mappings == (("NVDA", "XLF"),)
    assert first.current_sector_mappings[0] == ("NVDA", "XLK")


def test_snapshot_and_detached_serialization_are_immutable():
    decisions = {"SPY": primed().inspect(at())}
    histories = {"SPY": history()}
    result = snapshot(quote_decisions=decisions, histories=histories)
    saved = result.to_json()
    decisions.clear()
    histories.clear()
    detached = result.as_dict()
    detached["references"][0]["quote_decision"]["quote"]["bid"] = 0
    detached["references"][0]["history_conventions"]["price"] = "ALTERED"
    assert result.to_json() == saved
    with pytest.raises(FrozenInstanceError):
        result.session = "2026-07-01"


@pytest.mark.parametrize("changes", [
    {"source": "UNKNOWN"}, {"quote_data_mode": " unknown "}, {"history_data_mode": "UNSPECIFIED"},
    {"quote_policy": {}}, {"history_request": HistoryRequest("QQQ", at(-60), at())},
])
def test_scope_rejects_unknown_or_inconsistent_contract(changes):
    with pytest.raises(RecordError):
        scope(**changes)


@pytest.mark.parametrize("changes", [
    {"evaluated_at": START.replace(tzinfo=None)}, {"evaluated_at": "2026-06-30"},
    {"session": "2026-06-29"}, {"scopes": (scope(), scope())}, {"scopes": []},
    {"quote_decisions": {"SPY": {}}}, {"histories": {"SPY": {}}}, {"stock_symbols": ("",)},
])
def test_bad_snapshot_request_fails_without_inventing_inputs(changes):
    with pytest.raises(ValueError):
        snapshot(**changes)
