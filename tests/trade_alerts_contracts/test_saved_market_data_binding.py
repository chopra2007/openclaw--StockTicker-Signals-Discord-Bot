"""M9.1EQ audited saved-bar input binding contracts."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.saved_market_data_audit import AUDIT_VERSION, GAP_DEPENDENT_RULES
from consensus_engine.saved_market_data_binding import (
    ADAPTER_RUN_VERSION, ENABLED_IF_COMPLETE, OFF_UNTESTED, bind_saved_bar_inputs,
)
from consensus_engine.retained_adapter_run import ADAPTER_RUN_VERSION as RUNNER_VERSION


def _audit():
    return {
        "version": AUDIT_VERSION,
        "mode": "READ_ONLY_OFFLINE_INVENTORY",
        "network_used": False,
        "spend_usd": 0,
        "held_out_evaluation_run": False,
        "field_support": {
            "bar_native_ohlcv": "OBSERVED",
            "event_time": "MINUTE_START_FROM_SAVED_DATE_AND_MINUTE",
            "bid_ask": "ABSENT",
            "finality": "UNKNOWN",
            "adjustment_provenance": "NOT_PROVEN_BY_SAVED_PARQUET",
        },
        "gaps": {name: {"status": "GAP", "dependent_rules": "OFF_UNTESTED"}
                 for name in GAP_DEPENDENT_RULES},
        "files": [
            {"path": "/saved/equs.parquet", "sha256": "a" * 64},
            {"path": "/saved/pillar.parquet", "sha256": "b" * 64},
        ],
    }


def test_matrix_binds_only_observed_bar_inputs_and_keeps_gaps_off():
    result = bind_saved_bar_inputs(_audit())
    enabled = {(row["playbook"], row["input"]): row for row in result["enabled_inputs"]}
    disabled = {(row["playbook"], row["input"]): row for row in result["disabled_inputs"]}

    assert enabled[("CRVOL_ORB5", "opening_range_5m")]["status"] == ENABLED_IF_COMPLETE
    assert enabled[("HOD_COMP_RS", "rs_15m")]["required_observed_fields"] == [
        "open", "close", "event_time", "benchmark_bars"]
    assert enabled[("OR_FAILURE_REV", "tape_and_close")]["status"] == ENABLED_IF_COMPLETE
    assert enabled[("FIRST_PULLBACK_VWAP", "vwap_level")]["status"] == ENABLED_IF_COMPLETE
    assert disabled[("HOD_COMP_RS", "daily_atr_pct")]["status"] == OFF_UNTESTED
    assert disabled[("FIRST_PULLBACK_VWAP", "quote_decision")]["reason"] == \
        "HISTORICAL_BID_ASK_ABSENT"
    assert disabled[("CRVOL_ORB5", "bar_finality")]["reason"] == "FINALITY_UNKNOWN"
    assert result["held_out_evaluation"]["status"] == "CLOSED"
    assert not result["promotion_or_live_release"]
    assert result["adapter_run_version"] == ADAPTER_RUN_VERSION == RUNNER_VERSION


@pytest.mark.parametrize("field,value", [
    ("bid_ask", "OBSERVED"),
    ("finality", "FINAL"),
    ("adjustment_provenance", "PROVEN"),
])
def test_unknown_or_absent_source_facts_cannot_be_upgraded(field, value):
    audit = deepcopy(_audit())
    audit["field_support"][field] = value
    with pytest.raises(ValueError):
        bind_saved_bar_inputs(audit)


def test_recorded_binding_is_deterministic_and_keeps_held_out_closed(tmp_path):
    first = bind_saved_bar_inputs(_audit())
    second = bind_saved_bar_inputs(_audit())
    assert first == second
    rendered = json.dumps(first, indent=2, sort_keys=True) + "\n"
    output = Path(os.environ["TMPDIR"], "m91eq-audited-input-binding.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text())["held_out_evaluation"]["status"] == "CLOSED"
