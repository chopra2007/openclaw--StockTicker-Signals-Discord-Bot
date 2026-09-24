"""M9.1DC retained remaining-producer contracts."""

import json
from dataclasses import replace
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_decision_moments import plan_decision_moments
from consensus_engine.retained_remaining_producers import (
    OR_FAILURE_MISSING_INPUTS,
    RUN_VERSION,
    build_retained_remaining_request,
    retained_remaining_producers,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_candidate_events import _market, _retained
from test_retained_first_pullback_parent_scan import (
    _input as _impulse_input, _evidence, _with_bars,
)


def _input(playbook):
    retained = _retained()
    item = next(row for row in plan_decision_moments(retained)
                if row.playbook == playbook and row.ticker == "NVDA")
    records = _market()
    trades = tuple(row.quote for row in records if row.schema == "trades")
    quotes = tuple(row.quote for row in records if row.schema == "bbo-1m")
    source_ids = tuple(
        [bar.record_id for bar in item.history.batch.bars]
        + [row.record_id for row in trades + quotes]
    )
    return CandidateEventInput(
        playbook, item.ticker, item.session, item.moments, item.history,
        trades, quotes, source_ids,
    )


@pytest.mark.parametrize(
    "playbook,missing",
    (("OR_FAILURE_REV", OR_FAILURE_MISSING_INPUTS),
     ("FIRST_PULLBACK_VWAP", ("ATR_1M_UNAVAILABLE", "DAILY_ATR_UNAVAILABLE",
                              "VWAP_UNAVAILABLE", "QUOTE_DECISION_UNAVAILABLE",
                              "CONFIDENCE_UNAVAILABLE"))),
)
def test_preserves_scope_and_refuses_to_forge_mandatory_parent_steps(playbook, missing):
    value = _input(playbook)
    built = build_retained_remaining_request(value)
    assert built.playbook == playbook
    assert built.decision_moments == value.decision_moments
    assert built.retained_source_record_ids == value.source_record_ids
    expected = ((*missing, "OPENING_RANGE_PROVISIONAL") if playbook == "OR_FAILURE_REV" else
                missing)
    assert built.missing_required_inputs == expected
    assert tuple(row.evaluated_at for row in built.offline_inputs) == value.decision_moments
    assert built.handoff_requests == ()
    assert built.reversal_steps == ()
    assert built.pullback_steps == ()


@pytest.mark.parametrize(
    "playbook,missing",
    (("OR_FAILURE_REV", OR_FAILURE_MISSING_INPUTS),
     ("FIRST_PULLBACK_VWAP", ("ATR_1M_UNAVAILABLE", "DAILY_ATR_UNAVAILABLE",
                              "VWAP_UNAVAILABLE", "QUOTE_DECISION_UNAVAILABLE",
                              "CONFIDENCE_UNAVAILABLE"))),
)
def test_concrete_producer_returns_explicit_unavailable(playbook, missing):
    decision = retained_remaining_producers()[playbook](_input(playbook))[0]
    assert decision.status == "UNAVAILABLE"
    assert decision.producer_version == RUN_VERSION
    assert decision.alerted_at is None and decision.direction is None
    expected = ((*missing, "OPENING_RANGE_PROVISIONAL") if playbook == "OR_FAILURE_REV" else
                missing)
    assert decision.reason.split("|") == list(expected)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case,reason", (
    ("no_parent", "CONFIRMED_IMPULSE_UNAVAILABLE"),
    ("incomplete_window", "IMPULSE_WINDOW_MISSING"),
))
def test_supplied_impulse_evidence_preserves_only_exact_missing_reasons(direction, case, reason):
    value = _impulse_input(direction)
    facts = _evidence(value)
    if case == "no_parent":
        facts = (replace(facts[0], daily_atr=100.0),)
    else:
        value = _with_bars(value, value.history.batch.bars[1:])
    built = build_retained_remaining_request(value, impulse_evidence=facts)
    assert built.pullback_steps == ()
    assert built.retained_source_record_ids == value.source_record_ids
    assert built.missing_required_inputs == (
        reason, "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")


def test_refuses_a_playbook_outside_this_bounded_half():
    value = _input("OR_FAILURE_REV")
    wrong = CandidateEventInput(
        "CRVOL_ORB5", value.ticker, value.session, value.decision_moments,
        value.history, value.trades, value.quotes, value.source_record_ids,
    )
    with pytest.raises(RecordError, match="supports only"):
        build_retained_remaining_request(wrong)


def test_missing_retained_quote_or_trade_is_named_without_filling():
    value = _input("FIRST_PULLBACK_VWAP")
    missing = CandidateEventInput(
        value.playbook, value.ticker, value.session, value.decision_moments,
        value.history, (), (), (value.source_record_ids[0],),
    )
    decision = retained_remaining_producers()[value.playbook](missing)[0]
    assert decision.status == "UNAVAILABLE"
    assert decision.reason.endswith("RETAINED_TRADES_UNAVAILABLE|RETAINED_QUOTES_UNAVAILABLE")


def test_recorded_remaining_producer_proof_is_deterministic():
    proof = {}
    for playbook in ("OR_FAILURE_REV", "FIRST_PULLBACK_VWAP"):
        built = build_retained_remaining_request(_input(playbook))
        proof[playbook] = {
            "version": built.version,
            "moments": [row.isoformat() for row in built.decision_moments],
            "retained_source_record_ids": list(built.retained_source_record_ids),
            "missing_required_inputs": list(built.missing_required_inputs),
            "offline_inputs": [row.as_dict() for row in built.offline_inputs],
            "decision": retained_remaining_producers()[playbook](_input(playbook))[0].reason,
        }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dc-retained-remaining-producers-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
