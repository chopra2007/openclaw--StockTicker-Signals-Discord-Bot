"""M9.1DB retained first-two request and producer contracts."""

import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.hod_comp_rs_replay import HodCompRsReplayStep
from consensus_engine.orb5_replay import Orb5ReplayStep
from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_decision_moments import plan_decision_moments
from consensus_engine.retained_first_two_producers import (
    MISSING_REQUIRED_INPUTS,
    RUN_VERSION,
    build_retained_first_two_request,
    retained_first_two_producers,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_candidate_events import _market, _retained


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
    "playbook,step_type",
    (("CRVOL_ORB5", Orb5ReplayStep), ("HOD_COMP_RS", HodCompRsReplayStep)),
)
def test_builds_every_frozen_moment_as_its_canonical_replay_step(playbook, step_type):
    value = _input(playbook)
    built = build_retained_first_two_request(value)
    assert built.playbook == playbook
    assert len(built.steps) == len(value.decision_moments)
    assert all(isinstance(row, step_type) for row in built.steps)
    assert tuple(row.evaluated_at for row in built.steps) == value.decision_moments
    assert built.retained_source_record_ids == value.source_record_ids
    assert built.missing_required_inputs == MISSING_REQUIRED_INPUTS
    assert tuple(row.evaluated_at for row in built.offline_inputs) == value.decision_moments
    assert tuple(row.status for row in built.offline_inputs) == tuple(row.status for row in built.steps)
    assert all(row.status.halted is None for row in built.steps)
    assert all(row.status.macro_blackout_active is None for row in built.steps)
    assert all(row.status.catalyst_coverage == "UNKNOWN" for row in built.steps)


@pytest.mark.parametrize("playbook", ("CRVOL_ORB5", "HOD_COMP_RS"))
def test_concrete_producer_returns_explicit_unavailable_not_no_event(playbook):
    value = _input(playbook)
    decision = retained_first_two_producers()[playbook](value)
    assert len(decision) == 1
    assert decision[0].status == "UNAVAILABLE"
    assert decision[0].producer_version == RUN_VERSION
    assert decision[0].alerted_at is None
    assert decision[0].direction is None
    assert decision[0].reason.split("|") == list(MISSING_REQUIRED_INPUTS)


def test_refuses_a_playbook_outside_this_bounded_half():
    value = _input("CRVOL_ORB5")
    wrong = CandidateEventInput(
        "OR_FAILURE_REV", value.ticker, value.session, value.decision_moments,
        value.history, value.trades, value.quotes, value.source_record_ids,
    )
    with pytest.raises(RecordError, match="supports only"):
        build_retained_first_two_request(wrong)


def test_missing_retained_quote_or_trade_is_named_without_filling():
    value = _input("CRVOL_ORB5")
    missing = CandidateEventInput(
        value.playbook, value.ticker, value.session, value.decision_moments,
        value.history, (), (), (value.source_record_ids[0],),
    )
    decision = retained_first_two_producers()[value.playbook](missing)[0]
    assert decision.status == "UNAVAILABLE"
    assert decision.reason.endswith("RETAINED_TRADES_UNAVAILABLE|RETAINED_QUOTES_UNAVAILABLE")


def test_recorded_first_two_request_proof_is_deterministic():
    proof = {}
    for playbook in ("CRVOL_ORB5", "HOD_COMP_RS"):
        built = build_retained_first_two_request(_input(playbook))
        proof[playbook] = {
            "version": built.version,
            "step_type": type(built.steps[0]).__name__,
            "moments": [row.evaluated_at.isoformat() for row in built.steps],
            "retained_source_record_ids": list(built.retained_source_record_ids),
            "missing_required_inputs": list(built.missing_required_inputs),
            "offline_inputs": [row.as_dict() for row in built.offline_inputs],
            "decision": retained_first_two_producers()[playbook](_input(playbook))[0].reason,
        }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91db-retained-first-two-producers-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
