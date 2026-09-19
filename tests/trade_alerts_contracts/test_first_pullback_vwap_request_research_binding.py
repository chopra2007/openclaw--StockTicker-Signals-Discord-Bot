"""M9.1O: binding the M9.1M measurement and M9.1N relative-strength reading
into a usable `FIRST_PULLBACK_VWAP` `PullbackRequest`.

`impulse_pullback_research_adapter.py`/M9.1M and
`first_pullback_vwap_research_adapter.py`/M9.1N each produce one real-bar
reading; neither module assembles a `PullbackRequest` itself, exactly like
`or_failure_handoff_research_adapter.py`/M9.1L leaves `HandoffRequest`
assembly to the caller. This module proves the two readings the request
needs so far actually fit `first_pullback_vwap.PullbackRequest`'s own
contract, and documents exactly what each does and does not bind to the live
gates: `impulse_pullback_research_adapter.py`'s own docstring deliberately
gives its snapshot a distinct `feature_version`/`data_mode` so `_measurement`
can never bind it by accident, so `MEASUREMENT_GATE` stays `UNKNOWN` with
`MEASUREMENT_VERSION_MISMATCH` here, exactly as designed -- that gate needs
its own live-shaped research snapshot, which is not this sub-step's scope.
`RelativeStrength` carries no version check in `_relative_strength`, so the
M9.1N reading binds and evaluates genuinely from real, `PROVISIONAL`-usable
bars through `RS_GATE`.

Every bar and threshold below is a synthetic fixture. A passing case proves
only these two offline contracts fit together; it establishes no provider
coverage, no adopted `FIRST_PULLBACK_VWAP` rule, no alert and no permission to
act. The VWAP context, the last-trade observation, the quote decision, the
structural stop/target and the M4.4 confidence still need their own real-bar
producers and stay open build-scope for a further M9.1 sub-step.
"""

from datetime import datetime
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.first_pullback_vwap import (
    MEASUREMENT_GATE, PullbackRequest, RS_GATE, evaluate_first_pullback_vwap,
)
from consensus_engine.trade_alerts_models import RecordError
from test_first_pullback_vwap import policy as vwap_policy
from test_first_pullback_vwap_research_adapter import (
    AT as RS_AT, BENCHMARK, LOOKBACK, built as built_rs, history as rs_history,
)
from test_impulse_pullback_research_adapter import (
    LONG as MEASURE_POLICY, at as measure_at, result as built_measurement,
)


PACIFIC = ZoneInfo("America/Los_Angeles")
SYMBOL = "SYNTH"
VERSION = "M91O_FIXTURE_ONLY_V1"
DEFINITION = "M91O_SUPPLIED_FIXTURE_DEFINITION"


def request(*, min_relative_strength=0.01, evaluated_at=RS_AT, measurement=None,
           relative_strength=None, **changes):
    values = dict(
        measurement=built_measurement().snapshot if measurement is None else measurement,
        measurement_policy=MEASURE_POLICY,
        policy=vwap_policy(min_relative_strength=min_relative_strength),
        evaluated_at=evaluated_at, symbol=SYMBOL, strategy_version=VERSION,
        definition_reference=DEFINITION, impulse_started_at=measure_at("06:30:00"),
        impulse_frozen_at=measure_at("06:35:00"), atr_1m=0.10,
        relative_strength=built_rs() if relative_strength is None else relative_strength,
    )
    values.update(changes)
    return PullbackRequest(**values)


def test_the_two_research_readings_construct_a_valid_pullback_request():
    built = request()
    assert isinstance(built, PullbackRequest)
    assert built.measurement.feature_version != "M83_IMPULSE_PULLBACK_V1"
    assert built.relative_strength.value == pytest.approx(0.012)


def test_the_research_measurement_never_binds_the_live_measurement_gate_by_design():
    """`impulse_pullback_research_adapter.py` deliberately keeps its own
    `feature_version`/`data_mode`, so this stays `UNKNOWN`, not a false `PASS`."""
    assessment = evaluate_first_pullback_vwap(request())
    gate = assessment.gate(MEASUREMENT_GATE)
    assert gate.status == "UNKNOWN"
    assert gate.reason == "MEASUREMENT_VERSION_MISMATCH"


def test_the_research_relative_strength_reading_passes_the_live_gate_from_real_bars():
    assessment = evaluate_first_pullback_vwap(request(min_relative_strength=0.01))
    gate = assessment.gate(RS_GATE)
    assert gate.status == "PASS"
    assert gate.observed == pytest.approx(0.012)


def test_the_same_reading_fails_the_live_gate_against_a_higher_supplied_minimum():
    assessment = evaluate_first_pullback_vwap(request(min_relative_strength=0.02))
    gate = assessment.gate(RS_GATE)
    assert gate.status == "FAIL"
    assert gate.reason == "RELATIVE_STRENGTH_NOT_BEYOND_SUPPLIED_MINIMUM"


def test_provisional_bars_bind_the_live_gate_exactly_like_final_ones():
    provisional = built_rs(minute=rs_history(is_final=False),
                           benchmark=rs_history(BENCHMARK, first=400.00, step=0.08,
                                                is_final=False))
    assessment = evaluate_first_pullback_vwap(
        request(min_relative_strength=0.01, relative_strength=provisional))
    assert assessment.gate(RS_GATE).status == "PASS"


def test_before_warm_up_the_live_gate_reads_the_researchs_own_named_reason():
    early = datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC)
    incomplete = built_rs(evaluated=early)
    assessment = evaluate_first_pullback_vwap(
        request(evaluated_at=early, relative_strength=incomplete))
    gate = assessment.gate(RS_GATE)
    assert gate.status == "UNKNOWN"
    assert gate.reason == "RS_WARMUP_INCOMPLETE"


def test_a_missing_benchmark_history_reads_as_coverage_incomplete_on_the_live_gate():
    incomplete = built_rs(benchmark_history=None)
    assessment = evaluate_first_pullback_vwap(request(relative_strength=incomplete))
    gate = assessment.gate(RS_GATE)
    assert gate.status == "UNKNOWN"
    assert gate.reason == "RELATIVE_STRENGTH_COVERAGE_INCOMPLETE"


def test_the_request_still_never_reaches_alert_triggered_without_the_remaining_inputs():
    """`VWAP`, the last trade, the quote, the structural geometry and confidence
    all stay unsupplied in this sub-step, so no combination here can trigger."""
    assessment = evaluate_first_pullback_vwap(request(min_relative_strength=0.01))
    assert assessment.state.state != "ALERT_TRIGGERED"
    reasons = {row.split(":", 1)[0] for row in assessment.reasons}
    assert MEASUREMENT_GATE in reasons
    assert RS_GATE not in reasons  # the one gate this sub-step actually passes


def test_the_measurement_and_relative_strength_must_still_be_their_own_canonical_records():
    with pytest.raises(RecordError):
        request(measurement="not-a-snapshot")
    with pytest.raises(RecordError):
        request(relative_strength="not-a-reading")
