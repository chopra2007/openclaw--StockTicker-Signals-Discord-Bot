"""M9.1DA retained alert-time candidate-event connection contracts."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_candidate_events import (
    CandidateEventDecision, build_retained_candidate_events,
)
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.retained_history_batches import RetainedHistoryBatches
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_quote_trade_reader import iter_quote_trade_records
from consensus_engine.search_run_config import TRAINING_TICKERS
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata


UTC = timezone.utc
SESSION = "2026-01-05"
OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
MOMENT = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
HASH = "b" * 64
CONVENTIONS = HistoryConventions(
    timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="UNKNOWN", publication="SYNTHETIC_TEST", evidence_reference="synthetic-test",
)


@dataclass(frozen=True)
class TradeRow:
    instrument_id: int = 1
    ts_event: int = int(MOMENT.timestamp() * 1_000_000_000)
    ts_recv: int = ts_event + 1
    publisher_id: int = 7
    sequence: int = 1
    action: str = "T"
    side: str = "B"
    price: int = 100_000_000_000
    size: int = 100


@dataclass(frozen=True)
class BboRow:
    instrument_id: int = 1
    ts_event: int = int(MOMENT.timestamp() * 1_000_000_000)
    ts_recv: int = ts_event + 1
    publisher_id: int = 7
    sequence: int = 2
    side: str = "N"
    bid_px_00: int = 99_900_000_000
    ask_px_00: int = 100_100_000_000
    bid_sz_00: int = 100
    ask_sz_00: int = 100


def _bar(ticker):
    metadata = SourceMetadata(
        instrument_id=ticker, instrument_type="ETF" if ticker in {"SPY", "QQQ", "XLV", "USO"} else "EQUITY",
        source="EQUS.MINI", source_time=OPEN, received_time=OPEN,
        available_time=OPEN, normalized_time=OPEN, session=SESSION,
    )
    return Bar(
        record_id=f"bar:{ticker}", metadata=metadata, start_time=OPEN,
        end_time=OPEN.replace(minute=31), is_final=False,
        open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0,
        adjustment_basis="SYNTHETIC_TEST", price_convention="USD_PER_SHARE",
        volume_convention="SHARES",
    )


def _retained(tickers=TRAINING_TICKERS):
    histories = []
    for ticker in tickers:
        request = HistoryRequest(ticker, OPEN, datetime(2026, 1, 5, 21, tzinfo=UTC))
        histories.append(SimpleNamespace(
            ticker=ticker, session=SESSION,
            batch=HistoryBatch(request, "EQUS.MINI", CONVENTIONS, (_bar(ticker),)),
        ))
    return RetainedHistoryBatches(tuple(histories), (), ())


def _market():
    common = dict(
        dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols={1: "NVDA"}, condition_by_date={SESSION: "available"},
    )
    return (
        *iter_quote_trade_records([TradeRow()], schema="trades", **common),
        *iter_quote_trade_records([BboRow()], schema="bbo-1m", **common),
    )


def _producers(candidate_playbook="CRVOL_ORB5"):
    def producer(value):
        if value.playbook == candidate_playbook and value.ticker == "NVDA":
            return (CandidateEventDecision(
                "CANDIDATE", "ACCEPTED_PRODUCER_V1", "TRIGGERED", MOMENT, "LONG",
                ("bar:NVDA",) + tuple(row.record_id for row in value.trades + value.quotes),
            ),)
        status = "UNAVAILABLE" if not value.trades or not value.quotes else "NO_EVENT"
        return (CandidateEventDecision(status, "ACCEPTED_PRODUCER_V1", "NO_TRIGGER"),)
    return {name: producer for name in (
        "CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")}


def test_connects_each_first_four_producer_to_exact_session_inputs():
    rows = build_retained_candidate_events(_retained(), _market(), producers=_producers())
    assert len(rows) == 4 * len(TRAINING_TICKERS)
    event = next(row for row in rows if row.status == "CANDIDATE")
    assert (event.playbook, event.ticker, event.session) == ("CRVOL_ORB5", "NVDA", SESSION)
    assert event.alerted_at == MOMENT
    assert event.direction == "LONG"
    assert event.input_record_ids[0] == "bar:NVDA"
    assert len(event.retained_source_record_ids) == 3
    assert event.disabled_rules == (
        "ORIGINAL_AVAILABILITY_GAP", "CORRECTIONS_FINALITY_GAP",
        "POINT_IN_TIME_MEMBERSHIP_GAP",
    )
    assert all(row.status == "UNAVAILABLE" for row in rows if row.ticker != "NVDA")


@pytest.mark.parametrize("case", ("held_out", "outside_time", "foreign_id", "missing_producer", "duplicate"))
def test_refuses_scope_time_identity_or_producer_drift(case):
    retained = _retained()
    producers = _producers()
    if case == "held_out":
        retained = _retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    elif case == "missing_producer":
        producers.pop("CRVOL_ORB5")
    else:
        def bad(value):
            if value.ticker != "NVDA":
                return (CandidateEventDecision("UNAVAILABLE", "V1", "MISSING_INPUTS"),)
            if case == "outside_time":
                row = CandidateEventDecision("CANDIDATE", "V1", "BAD", OPEN, "LONG", ("bar:NVDA",))
            elif case == "foreign_id":
                row = CandidateEventDecision("CANDIDATE", "V1", "BAD", MOMENT, "LONG", ("held-out",))
            else:
                row = CandidateEventDecision("NO_EVENT", "V1", "NONE")
                return (row, row)
            return (row,)
        producers["CRVOL_ORB5"] = bad
    with pytest.raises(RecordError):
        build_retained_candidate_events(retained, _market(), producers=producers)


def test_missing_quote_trade_records_stay_unavailable_not_filled():
    rows = build_retained_candidate_events(_retained(), (), producers=_producers("NONE"))
    assert rows
    assert {row.status for row in rows} == {"UNAVAILABLE"}
    assert all(row.alerted_at is None and row.direction is None for row in rows)
    assert all(len(row.retained_source_record_ids) == 1 for row in rows)


@pytest.mark.parametrize("missing", ("trades", "bbo-1m", "both"))
@pytest.mark.parametrize("status", ("NO_EVENT", "CANDIDATE"))
@pytest.mark.parametrize("playbook", PLAYBOOKS)
def test_refuses_producer_success_when_retained_market_records_are_missing(missing, status, playbook):
    market = tuple(row for row in _market() if missing != "both" and row.schema != missing)
    producers = _producers("NONE")

    def incorrect(value):
        if value.ticker != "NVDA":
            return (CandidateEventDecision("UNAVAILABLE", "V1", "MISSING_INPUTS"),)
        assert bool(value.trades) == (missing == "bbo-1m")
        assert bool(value.quotes) == (missing == "trades")
        if status == "CANDIDATE":
            return (CandidateEventDecision(
                status, "V1", "INCORRECT_TRIGGER", MOMENT, "LONG", ("bar:NVDA",),
            ),)
        return (CandidateEventDecision(status, "V1", "INCORRECT_NO_EVENT"),)

    producers[playbook] = incorrect
    with pytest.raises(RecordError, match="missing retained trades or quotes require UNAVAILABLE"):
        build_retained_candidate_events(_retained(), market, producers=producers)


@pytest.mark.parametrize("missing", ("trades", "bbo-1m", "both"))
def test_explicit_unavailable_preserves_only_remaining_retained_identities(missing):
    market = tuple(row for row in _market() if missing != "both" and row.schema != missing)
    rows = build_retained_candidate_events(_retained(), market, producers=_producers("NONE"))
    assert {row.status for row in rows} == {"UNAVAILABLE"}
    assert all(row.alerted_at is None and row.direction is None for row in rows)
    for row in rows:
        expected = (f"bar:{row.ticker}",)
        if row.ticker == "NVDA":
            expected += tuple(record.quote.record_id for record in market)
        assert row.retained_source_record_ids == expected


def test_recorded_candidate_event_proof_is_deterministic():
    rows = build_retained_candidate_events(_retained(), _market(), producers=_producers())
    proof = {
        "held_out_opened": False,
        "fills_or_returns_calculated": False,
        "gap_dependent_rules": "OFF_UNTESTED",
        "events": [row.as_dict() for row in rows],
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91da-retained-candidate-events-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
