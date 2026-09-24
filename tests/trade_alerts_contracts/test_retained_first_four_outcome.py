"""M9.1EB filled-candidate-only offline outcome connection."""

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.orb5_trade_walk import (
    Orb5Geometry, Orb5QuoteFilledRecord, Orb5TradeRecord,
)
from consensus_engine.orb5_trigger import FrozenCandidate
from consensus_engine.playbook_outcome_evaluator import PlaybookOutcomeEvaluation
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_fill import run_retained_first_four_fills
from consensus_engine.retained_first_four_outcome import (
    RUN_VERSION, run_retained_first_four_outcomes,
)
from consensus_engine.trade_alerts_models import OutcomeRecord, RecordError
from test_retained_first_four_fill import _fill_ready_binding, _policy


def _shared(row):
    fill = row.fill
    outcome = OutcomeRecord(
        record_id=f"outcome:{row.decision.playbook}",
        candidate_id=f"candidate:{row.decision.playbook}",
        evaluated_at=fill.window_end + timedelta(hours=7),
        horizon="SESSION_CLOSE",
        coverage_status="UNRESOLVED",
        policy_version="M91C_SHARED_D106_D107_OUTCOME_V1",
        alert_price=None,
        modeled_entry_price=fill.modeled_price,
        result="UNKNOWN",
        data_quality="UNAVAILABLE",
        input_record_ids=fill.input_record_ids,
    )
    return PlaybookOutcomeEvaluation(
        outcome, "NO_PATH_AFTER_FILL", fill, 1.0, False, (), None,
    )


def _orb5(row):
    fill = row.fill
    geometry = Orb5Geometry(row.decision.direction, fill.modeled_price, 90.0, 10.0,
                            (("EXIT_FIXED_2R_V2", 120.0),))
    high, low, buffer = 110.0, 90.0, 1.0
    candidate = FrozenCandidate(
        row.decision.alerted_at, row.decision.direction, "TAPE", 1, high, low,
        1.0, buffer, high + buffer if row.decision.direction == "LONG" else low - buffer,
        "synthetic-anchor", row.decision.input_record_ids,
    )
    record = Orb5TradeRecord(
        "UNRESOLVED", row.decision.direction, "EXIT_FIXED_2R_V2", None,
        "NO_EXIT_BY_SESSION_CLOSE", candidate, geometry, None,
        "D106_D107_QUOTE_FILL", {}, None,
    )
    return Orb5QuoteFilledRecord(
        "UNRESOLVED", "NO_EXIT_BY_SESSION_CLOSE", fill, record,
        {"entry_side_cost": "SPREAD_SLIPPAGE_COMMISSION", "off": [],
         "label": "OFF_GATES_UNTESTED_D104"},
    )


def _resolvers(calls):
    def resolve(row):
        calls.append(row.decision.playbook)
        return _orb5(row) if row.decision.playbook == "CRVOL_ORB5" else _shared(row)
    return {playbook: resolve for playbook in PLAYBOOKS}


def _filled(monkeypatch, *, keep_second=True):
    binding, trades, quotes = _fill_ready_binding(monkeypatch)
    if not keep_second:
        trades, quotes = trades[:1], quotes[:1]
    return run_retained_first_four_fills(
        binding, trades=trades, quotes=quotes, policy=_policy(),
    )


def test_only_filled_candidates_reach_the_accepted_outcome_boundary(monkeypatch):
    calls = []
    result = run_retained_first_four_outcomes(
        _filled(monkeypatch), resolvers=_resolvers(calls),
    )

    assert result.version == RUN_VERSION
    assert calls == ["CRVOL_ORB5", "OR_FAILURE_REV"]
    assert result.filled_candidate_count == result.outcome_count == 2
    assert result.resolved_return_count == result.unfilled_excluded_count == 0
    assert result.no_event_excluded_count == 2
    assert result.unavailable_excluded_count == 0
    assert {type(row.outcome) for row in result.rows} == {
        Orb5QuoteFilledRecord, PlaybookOutcomeEvaluation,
    }
    assert not any((result.result_shard_released, result.held_out_opened,
                    result.alert_released, result.live_action))


def test_unfilled_candidate_is_excluded_without_calling_a_resolver(monkeypatch):
    calls = []
    result = run_retained_first_four_outcomes(
        _filled(monkeypatch, keep_second=False), resolvers=_resolvers(calls),
    )
    assert calls == ["CRVOL_ORB5"]
    assert result.filled_candidate_count == result.outcome_count == 1
    assert result.unfilled_excluded_count == 1


def test_rejects_wrong_outcome_type_changed_fill_or_opened_input(monkeypatch):
    filled = _filled(monkeypatch)
    calls = []
    wrong = _resolvers(calls)
    wrong["CRVOL_ORB5"] = _shared
    with pytest.raises(RecordError, match="accepted offline outcome type"):
        run_retained_first_four_outcomes(filled, resolvers=wrong)

    changed = _resolvers([])
    changed["OR_FAILURE_REV"] = lambda row: replace(
        _shared(row), fill=replace(row.fill, modeled_price=row.fill.modeled_price + 1.0))
    with pytest.raises(RecordError, match="exact accepted fill"):
        run_retained_first_four_outcomes(filled, resolvers=changed)

    with pytest.raises(RecordError, match="later release"):
        run_retained_first_four_outcomes(
            replace(filled, result_shard_released=True), resolvers=_resolvers([]),
        )


def test_rejects_orb5_candidate_input_outside_retained_session(monkeypatch):
    filled = _filled(monkeypatch)
    resolvers = _resolvers([])

    def foreign_candidate(row):
        outcome = _orb5(row)
        candidate = outcome.record.candidate
        foreign_id = "foreign-session:candidate-input"
        assert foreign_id not in row.decision.retained_source_record_ids
        assert set(outcome.fill.input_record_ids).issubset(
            row.decision.retained_source_record_ids)
        changed = replace(outcome, record=replace(
            outcome.record, candidate=replace(
                candidate, input_record_ids=candidate.input_record_ids + (foreign_id,))))
        assert changed.fill == row.fill
        return changed

    resolvers["CRVOL_ORB5"] = foreign_candidate
    with pytest.raises(RecordError, match="outside the retained candidate session"):
        run_retained_first_four_outcomes(filled, resolvers=resolvers)


def test_recorded_outcome_connection_is_deterministic_and_keeps_release_off(monkeypatch):
    result = run_retained_first_four_outcomes(
        _filled(monkeypatch), resolvers=_resolvers([]),
    )
    payload = result.as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "outcome_run_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "only_filled_candidates_entered_outcome": all(
            row.fill_row.fill.status == "FILLED" for row in result.rows),
        "gap_dependent_rules": "OFF_UNTESTED",
        "result_shard_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91eb-retained-first-four-outcome.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
