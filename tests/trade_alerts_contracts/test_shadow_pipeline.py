"""M9.3 shadow-mode pilot contracts.

Every fixture reused here is the same synthetic supplied fixture the M6.4,
M7.5 and M8.6 replay contracts already use and already passed; this file adds
no new strategy rule, threshold or historical claim. A passing pilot proves the
offline mechanics only: safe recording, input continuity and one shared-session
run of the initial pipeline across all four first playbooks.
"""

from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.full_chain_storage import StoragePolicy
from consensus_engine.historical_replay import RecordingReplaySink
from consensus_engine.or_failure_handoff import mirror_direction
from consensus_engine.orb5_replay import STRATEGY_ID as ORB5_ID
from consensus_engine.hod_comp_rs_replay import STRATEGY_ID as HOD_ID
from consensus_engine.or_failure_rev_replay import STRATEGY_ID as REV_ID
from consensus_engine.first_pullback_vwap_replay import STRATEGY_ID as PULLBACK_ID
from consensus_engine.request_queue import QueuePolicy
from consensus_engine.shadow_pipeline import (
    REQUIRED_STRATEGY_IDS, SHADOW_MODE_VERSION, SHARED_DATA_MODE, ContinuityGap,
    ContinuityReport, ProviderBudget, ShadowModeBudgets, check_input_continuity,
    default_shadow_mode_budgets, provider_budget_from_ledger, run_shadow_mode_pilot,
)
from consensus_engine.state_transitions import StateTransitionEngine
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore

import test_first_pullback_vwap_replay as pullback
import test_hod_comp_rs_replay as hod
import test_or_failure_rev_replay as rev
import test_orb5_replay as orb5


LEDGER = {
    "authority_usd": 60.0,
    "jobs": [
        {"actual_cost_usd": 20.6736, "downloaded": True},
        {"actual_cost_usd": 0.676, "downloaded": True},
        {"actual_cost_usd": 1.1206, "downloaded": True},
        {"actual_cost_usd": 999.0, "downloaded": False},
    ],
}


def budgets():
    return default_shadow_mode_budgets(LEDGER)


def scenario():
    """One shared 2026-07-06 session's supplied evaluation set for all four
    first playbooks, built only from each playbook's own already-passed
    synthetic fixture (`plan("clean")`/`plan("triggered")`)."""
    orb5_direction, orb5_steps, orb5_contexts = orb5.plan("clean")
    hod_direction, hod_steps, hod_contexts = hod.plan("clean")
    rev_break_direction, rev_steps, rev_contexts = rev.plan("triggered")
    pullback_direction, pullback_steps, pullback_contexts = pullback.plan("triggered")
    rev_direction = mirror_direction(rev_break_direction)
    specs = {
        ORB5_ID: orb5.spec(), HOD_ID: hod.spec(),
        REV_ID: rev.spec(), PULLBACK_ID: pullback.spec(),
    }
    strategies = {
        ORB5_ID: orb5.strategy(orb5_direction, steps=orb5_steps),
        HOD_ID: hod.strategy(hod_direction, steps=hod_steps),
        REV_ID: rev.strategy(rev_break_direction, steps=rev_steps),
        PULLBACK_ID: pullback.strategy(pullback_direction, steps=pullback_steps),
    }
    contexts_by_strategy = {
        ORB5_ID: orb5_contexts, HOD_ID: hod_contexts,
        REV_ID: rev_contexts, PULLBACK_ID: pullback_contexts,
    }
    scopes = {
        ORB5_ID: orb5.scope(orb5_direction), HOD_ID: hod.scope(hod_direction),
        REV_ID: rev.scope(rev_direction), PULLBACK_ID: pullback.scope(pullback_direction),
    }
    return specs, strategies, contexts_by_strategy, scopes


async def run_pilot(*, database=None, contexts_by_strategy=None, sink_factory=RecordingReplaySink):
    if database is not None:
        await db.close_db()
        db.DB_PATH = str(database)
    connection = await db.init_db()
    specs, strategies, built_contexts, scopes = scenario()
    contexts = contexts_by_strategy if contexts_by_strategy is not None else built_contexts
    store = ResearchEventStore(connection)
    transitions = {sid: StateTransitionEngine(scopes[sid], SQLiteTransitionStore(connection))
                   for sid in REQUIRED_STRATEGY_IDS}
    return await run_shadow_mode_pilot(
        specs=specs, strategies=strategies, transitions=transitions, store=store,
        contexts_by_strategy=contexts, budgets=budgets(), max_gap=timedelta(minutes=30),
        sink_factory=sink_factory)


# --- the pilot runs the initial pipeline -------------------------------------


async def test_the_pilot_runs_all_four_first_playbooks_through_one_shared_session():
    report = await run_pilot()
    assert report.session == "2026-07-06"
    assert {row.strategy_id for row in report.runs} == set(REQUIRED_STRATEGY_IDS)
    assert all(row.data_mode == SHARED_DATA_MODE for row in report.runs)
    assert report.continuity.ok
    for row in report.runs:
        assert len(row.result.observations) > 0
    as_dict = report.as_dict()
    assert as_dict["alert_sink"] == "recording" and as_dict["replay_sink"] == "RecordingReplaySink"
    assert as_dict["shadow_mode_version"] == SHADOW_MODE_VERSION


async def test_the_pilot_checks_continuity_across_every_supplied_context():
    report = await run_pilot()
    total = sum(len(row.result.observations) for row in report.runs)
    assert report.continuity.checked_count == total == 3 + 4 + 1 + 1


async def test_the_pilot_reports_the_recorded_m0_2k_budgets():
    report = await run_pilot()
    rendered = report.as_dict()["budgets"]
    assert rendered["queue_policy"] == {
        "enabled": False, "account_ceiling": 110, "ceiling_window_seconds": 60,
        "maximum_length": 256,
    }
    assert rendered["storage_policy"]["fixed_reserve_bytes"] == 12_000_000_000
    assert rendered["storage_policy"]["peak_memory_bytes"] == 1_500_000_000
    assert rendered["provider"] == {
        "authority_usd": 60.0, "spent_usd": 22.4702, "remaining_usd": 37.5298,
    }


# --- safe recording: no other sink can be substituted ------------------------


async def test_the_pilot_refuses_a_sink_other_than_the_recording_sink():
    class _FakeSink:
        async def record(self, observation):  # pragma: no cover - never reached
            raise AssertionError("a fake sink must never receive an observation")

    with pytest.raises(RecordError, match="recording-only sink"):
        await run_pilot(sink_factory=_FakeSink)


async def test_the_pilot_refuses_disabled_or_live_budget_policies():
    with pytest.raises(RecordError, match="disabled"):
        ShadowModeBudgets(QueuePolicy(enabled=True), StoragePolicy(), ProviderBudget(60.0, 0.0))
    with pytest.raises(RecordError, match="disabled"):
        ShadowModeBudgets(QueuePolicy(), StoragePolicy(enabled=True), ProviderBudget(60.0, 0.0))


# --- input continuity is fail-closed -----------------------------------------


async def test_the_pilot_refuses_to_run_anything_on_a_discontinuous_stream():
    specs, strategies, contexts, scopes = scenario()
    far_future = orb5.context_at("LONG", orb5.TRIGGER + timedelta(hours=5))
    broken = dict(contexts)
    broken[ORB5_ID] = contexts[ORB5_ID] + (far_future,)
    calls = []

    def counting_sink():
        calls.append(1)
        return RecordingReplaySink()

    with pytest.raises(RecordError, match="discontinuous"):
        await run_pilot(contexts_by_strategy=broken, sink_factory=counting_sink)
    assert calls == []


def test_check_input_continuity_reports_the_gap_it_found():
    _, _, contexts, _ = scenario()
    far_future = orb5.context_at("LONG", orb5.TRIGGER + timedelta(hours=5))
    broken = dict(contexts)
    broken[ORB5_ID] = contexts[ORB5_ID] + (far_future,)
    report = check_input_continuity(broken, max_gap=timedelta(minutes=30))
    assert report.ok is False
    assert report.gaps == (ContinuityGap(ORB5_ID, report.gaps[0].gap_seconds),)
    assert report.gaps[0].gap_seconds > timedelta(hours=4).total_seconds()


def test_check_input_continuity_refuses_a_record_id_reused_across_strategies():
    _, _, contexts, _ = scenario()
    collided = dict(contexts)
    collided[PULLBACK_ID] = contexts[REV_ID]
    with pytest.raises(RecordError, match="reused across strategies"):
        check_input_continuity(collided, max_gap=timedelta(minutes=30))


def test_check_input_continuity_requires_exactly_the_four_first_playbooks():
    _, _, contexts, _ = scenario()
    assert check_input_continuity(contexts, max_gap=timedelta(minutes=30)).ok
    with pytest.raises(RecordError, match="exactly the four first playbooks"):
        check_input_continuity({ORB5_ID: contexts[ORB5_ID]}, max_gap=timedelta(minutes=30))


@pytest.mark.parametrize("bad_gap", (timedelta(0), timedelta(seconds=-1), "PT30M"))
def test_check_input_continuity_requires_one_explicit_positive_gap(bad_gap):
    _, _, contexts, _ = scenario()
    with pytest.raises(RecordError, match="explicit positive max_gap"):
        check_input_continuity(contexts, max_gap=bad_gap)


# --- provider budget arithmetic is pure and bounded --------------------------


def test_provider_budget_from_ledger_sums_only_downloaded_jobs():
    budget = provider_budget_from_ledger(LEDGER)
    assert budget.authority_usd == 60.0
    assert budget.spent_usd == pytest.approx(22.4702)
    assert budget.remaining_usd == pytest.approx(37.5298)


def test_provider_budget_refuses_spend_beyond_its_authority():
    with pytest.raises(RecordError, match="exceeds its recorded authority"):
        ProviderBudget(10.0, 10.01)


def test_default_shadow_mode_budgets_reuses_the_frozen_defaults_unchanged():
    result = default_shadow_mode_budgets(LEDGER)
    assert result.queue_policy == QueuePolicy()
    assert result.storage_policy == StoragePolicy()


# --- repeatability: the same shared session replays byte-identically --------


async def test_the_same_shared_session_replays_byte_identically(tmp_path):
    first = await run_pilot(database=tmp_path / "shadow-first.db")
    second = await run_pilot(database=tmp_path / "shadow-second.db")
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


async def test_the_shared_session_records_one_deterministic_pilot_proof(tmp_path):
    report = await run_pilot(database=tmp_path / "shadow-proof.db")
    proof = {
        "synthetic_only": True, "shadow_mode_version": SHADOW_MODE_VERSION,
        "fingerprint": report.fingerprint,
        "strategy_ids": sorted(row.strategy_id for row in report.runs),
        "observation_counts": {row.strategy_id: len(row.result.observations)
                               for row in report.runs},
        "continuity_ok": report.continuity.ok,
    }
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    (Path(os.environ["TMPDIR"]) / "m9_3_shadow_pilot.json").write_text(rendered + "\n")
