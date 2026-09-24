"""M9.1AZ: preregistered decision moments over retained batches (offline, synthetic)."""

from datetime import datetime, timezone
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_decision_moments import (
    PLAYBOOKS, decision_moments, plan_decision_moments,
)
from consensus_engine.retained_history_batches import RetainedHistoryBatches, SessionHistory
from consensus_engine.trade_alerts_models import RecordError


def test_full_day_grid_is_five_minutes_from_0935_to_1555_new_york():
    moments = decision_moments("2026-08-21")
    assert len(moments) == 77
    assert moments[0] == datetime(2026, 8, 21, 13, 35, tzinfo=timezone.utc)
    assert moments[-1] == datetime(2026, 8, 21, 19, 55, tzinfo=timezone.utc)
    assert decision_moments("2026-08-21") == moments


def test_non_session_and_bad_dates_are_rejected():
    for bad in ("2026-08-22", "not-a-date"):
        with pytest.raises(RecordError):
            decision_moments(bad)


def test_plan_covers_each_playbook_with_atr_unset_and_rejects_bad_playbooks():
    history = SessionHistory("SPY", "2026-08-21", batch=None, prior_batch=None)
    batches = RetainedHistoryBatches((history,), (), ())
    plan = plan_decision_moments(batches)
    assert [p.playbook for p in plan] == list(PLAYBOOKS)
    assert all(p.atr_1m is None and len(p.moments) == 77 for p in plan)
    orb_only = plan_decision_moments(batches, playbooks=("CRVOL_ORB5",))
    assert len(orb_only) == 1 and orb_only[0].playbook == "CRVOL_ORB5"
    for bad in ((), ("HOD_COMP_RS", "HOD_COMP_RS"), ("UNKNOWN",)):
        with pytest.raises(RecordError):
            plan_decision_moments(batches, playbooks=bad)
