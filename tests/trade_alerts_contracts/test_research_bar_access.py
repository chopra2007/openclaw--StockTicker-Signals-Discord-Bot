"""M9.1D D-110 research-bar accessor: PROVISIONAL bars usable, live contract untouched."""

from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine.historical_bars import (
    HistoryConventions, HistoryRequest, SchwabBarContext, normalize_schwab_history,
)
from consensus_engine.research_bar_access import research_coverage_at
from consensus_engine.scanners import schwab_client
from consensus_engine.trade_alerts_models import RecordError, SourceMetadata


PACIFIC = ZoneInfo("America/Los_Angeles")


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


def batch(req=None, *, is_final=True, missing_last=False):
    req = req or request()
    intervals = req.expected_intervals()
    candles, contexts = [], []
    for number, interval in enumerate(intervals):
        if missing_last and number == len(intervals) - 1:
            continue
        candles.append(dict(datetime=int(interval.start.timestamp() * 1000), open=100.0,
                            high=101.0 + number, low=99.0, close=100.5, volume=10 + number))
        contexts.append(SchwabBarContext(
            record_id=f"history-{number}", start=interval.start, end=interval.end, is_final=is_final,
            metadata=SourceMetadata(
                instrument_id=req.symbol, source="SCHWAB", source_time=interval.start,
                received_time=interval.end, available_time=interval.end,
                normalized_time=at("13:30:00", interval.session), session=interval.session,
                instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY", quality="VALID",
            ),
        ))
    raw = {"symbol": schwab_client.to_schwab_symbol(req.symbol), "candles": candles, "empty": not candles}
    return normalize_schwab_history(raw, request=req, contexts=tuple(contexts), conventions=conventions())


def test_provisional_bars_are_excluded_from_the_live_final_view():
    result = batch(is_final=False)
    live = result.coverage_at(at("06:35:00"))
    assert not live.complete
    assert live.final_bars == ()
    assert [item.status for item in live.intervals] == ["PROVISIONAL"] * 5


def test_research_view_admits_provisional_bars_the_live_view_rejects():
    result = batch(is_final=False)
    research = research_coverage_at(result, at("06:35:00"))
    assert len(research.bars) == 5
    assert research.provisional_count == 5
    assert research.final_count == 0
    assert research.no_trade_count == 0
    assert research.other_count == 0
    assert research.total_usable == 5
    # The underlying live coverage object is exactly the untouched HistoryBatch view.
    assert research.coverage.as_dict() == result.coverage_at(at("06:35:00")).as_dict()


def test_research_view_matches_final_bars_when_finality_is_established():
    result = batch(is_final=True)
    research = research_coverage_at(result, at("06:35:00"))
    live = result.coverage_at(at("06:35:00"))
    assert research.bars == live.final_bars
    assert research.final_count == 5
    assert research.provisional_count == 0


def test_research_view_still_excludes_missing_and_not_ended_intervals():
    result = batch(is_final=False, missing_last=True)
    research = research_coverage_at(result, at("06:35:00"))
    assert len(research.bars) == 4
    assert research.provisional_count == 4
    assert research.other_count == 1
    not_ended = research_coverage_at(result, at("06:33:00"))
    assert not_ended.other_count == 2
    assert not_ended.provisional_count == 3


def test_label_names_the_d110_decision_and_interval_counts():
    result = batch(is_final=False)
    research = research_coverage_at(result, at("06:35:00"))
    label = research.label()
    assert label["decision"] == "D-110"
    assert label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert label["provisional_intervals"] == 5
    assert label["total_usable_intervals"] == 5
    assert "corrections and finality" in label["gap_field"]


def test_research_coverage_rejects_a_non_history_batch():
    with pytest.raises(RecordError):
        research_coverage_at("not-a-batch", at("06:35:00"))
