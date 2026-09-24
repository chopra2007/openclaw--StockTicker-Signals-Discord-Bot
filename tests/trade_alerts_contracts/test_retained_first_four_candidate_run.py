"""M9.1DF concrete first-four retained candidate-event run contracts."""

import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_candidate_run import (
    RUN_VERSION,
    run_retained_first_four_candidates,
)
from consensus_engine.retained_first_two_producers import RUN_VERSION as FIRST_TWO_VERSION
from consensus_engine.retained_remaining_producers import RUN_VERSION as REMAINING_VERSION
from consensus_engine.search_run_config import TRAINING_TICKERS
from test_retained_candidate_events import _market, _retained


def test_runs_all_four_concrete_producers_over_only_the_training_nine():
    result = run_retained_first_four_candidates(_retained(), _market())

    assert result.version == RUN_VERSION
    assert len(result.events) == len(PLAYBOOKS) * len(TRAINING_TICKERS)
    assert {event.playbook for event in result.events} == set(PLAYBOOKS)
    assert {event.ticker for event in result.events} == set(TRAINING_TICKERS)
    assert {event.status for event in result.events} == {"UNAVAILABLE"}
    assert all(event.alerted_at is None and event.direction is None for event in result.events)
    assert all(event.disabled_rules == REQUIRED_DISABLED_RULES for event in result.events)

    for event in result.events:
        expected_version = FIRST_TWO_VERSION if event.playbook in PLAYBOOKS[:2] else REMAINING_VERSION
        assert event.producer_version == expected_version
        assert event.retained_source_record_ids[0] == f"bar:{event.ticker}"
        if event.ticker == "NVDA":
            assert event.retained_source_record_ids == (
                "bar:NVDA",
                *tuple(record.quote.record_id for record in _market()),
            )
        else:
            assert event.retained_source_record_ids == (f"bar:{event.ticker}",)


def test_parent_scan_reasons_survive_the_connected_candidate_run():
    result = run_retained_first_four_candidates(_retained(), _market())
    by_playbook = {
        event.playbook: event
        for event in result.events
        if event.ticker == "NVDA"
    }

    assert "OPENING_RANGE_PROVISIONAL" in by_playbook["OR_FAILURE_REV"].reason.split("|")
    assert by_playbook["FIRST_PULLBACK_VWAP"].reason.split("|") == [
        "ATR_1M_UNAVAILABLE",
        "DAILY_ATR_UNAVAILABLE",
        "VWAP_UNAVAILABLE",
        "QUOTE_DECISION_UNAVAILABLE",
        "CONFIDENCE_UNAVAILABLE",
    ]
    assert all(event.input_record_ids == () for event in by_playbook.values())


def test_recorded_first_four_candidate_run_is_deterministic():
    result = run_retained_first_four_candidates(_retained(), _market())
    proof = {
        "held_out_opened": False,
        "fills_or_returns_calculated": False,
        "supervised_package_calculated": False,
        "gap_dependent_rules": "OFF_UNTESTED",
        "run": result.as_dict(),
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91df-retained-first-four-candidate-run-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
