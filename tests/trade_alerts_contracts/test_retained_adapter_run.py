"""M9.1BA: adapter run over planned decision moments (offline, synthetic)."""

from datetime import datetime, timezone
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_adapter_run import NOT_CALLED, run_adapters
from consensus_engine.retained_decision_moments import DecisionPlanItem
from consensus_engine.retained_history_batches import SessionHistory
from consensus_engine.trade_alerts_models import RecordError

MOMENTS = (datetime(2026, 8, 21, 13, 35, tzinfo=timezone.utc),
           datetime(2026, 8, 21, 13, 40, tzinfo=timezone.utc))


def _item(playbook):
    history = SessionHistory("XYZ", "2026-08-21", batch=None, prior_batch=None)
    return DecisionPlanItem(playbook, "XYZ", "2026-08-21", MOMENTS, history)


def test_absent_batch_counts_every_moment_not_ready_with_a_reason():
    result = run_adapters((_item("OR_FAILURE_REV"), _item("FIRST_PULLBACK_VWAP")),
                          instrument_types={"XYZ": "EQUITY"})
    assert result.moments_called == 4
    assert result.ready == ()
    assert sum(row[-1] for row in result.not_ready) == 6  # 2 + 2 + 2 inputs
    assert all(row[2] for row in result.not_ready)
    assert run_adapters((_item("OR_FAILURE_REV"),), instrument_types={"XYZ": "EQUITY"}) == \
        run_adapters((_item("OR_FAILURE_REV"),), instrument_types={"XYZ": "EQUITY"})


def test_gaps_are_listed_and_missing_instrument_type_is_rejected():
    result = run_adapters((), instrument_types={})
    assert result.not_called == NOT_CALLED and "atr_1m" in NOT_CALLED
    with pytest.raises(RecordError):
        run_adapters((_item("OR_FAILURE_REV"),), instrument_types={})
