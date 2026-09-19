"""M9.1Q: `FIRST_PULLBACK_VWAP`'s structural stop, from caller-supplied facts.

`entry_reference` and `pullback_extreme_price` are supplied facts from their
own producers (the M0.3A entry search and the M8.3 measurement); this reuses
the M9.1K `extreme -/+ 0.05*ATR` arithmetic, rounded outward to the supplied
price increment, exactly as PLAYBOOKS section 6 states it. No bar is read to
compute the stop, so `label` is always `None` here; the target catalog stays
open build-scope for a further M9.1 sub-step. Passing a case proves only the
offline contract described in `first_pullback_vwap_research_adapter.py`: it
establishes no provider coverage, no adopted rule and no permission to act.
"""

from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.first_pullback_vwap import PullbackStructural
from consensus_engine.first_pullback_vwap_research_adapter import (
    RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE,
    RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN,
    build_pullback_structural_from_research,
)
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.utils.time_context import as_utc, session_bounds

PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"


def opened_at(day=DAY):
    return as_utc(session_bounds(datetime.fromisoformat(day).date())[0])


def structural(*, direction="LONG", frozen=None, evaluated=None, available=None,
              entry_reference=100.00, pullback_extreme_price=99.90, frozen_atr=1.0,
              price_increment=0.01, **changes):
    values = dict(
        record_id_prefix="m91q-test", direction=direction,
        impulse_frozen_at=frozen or opened_at(),
        evaluated_at=evaluated or opened_at() + timedelta(minutes=5),
        available_at=available or evaluated or opened_at() + timedelta(minutes=5),
        entry_reference=entry_reference, pullback_extreme_price=pullback_extreme_price,
        frozen_atr=frozen_atr, price_increment=price_increment,
    )
    values.update(changes)
    return build_pullback_structural_from_research(**values)


def test_a_long_pullback_stop_is_the_pullback_low_minus_the_atr_pad():
    result = structural()
    assert result.structural.risk.hard_stop == pytest.approx(99.85)
    assert result.structural.risk.entry_reference == 100.00
    assert result.structural.risk.risk_per_share == pytest.approx(0.15)
    assert result.structural.definition_reference == (
        RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE)
    assert result.structural.targets == ()
    assert result.structural.missing_reason is None
    assert result.label is None
    assert RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN in result.structural.record_ids[0]


def test_a_short_pullback_stop_is_the_pullback_high_plus_the_atr_pad():
    result = structural(direction="SHORT", pullback_extreme_price=100.35, entry_reference=100.10)
    assert result.structural.risk.hard_stop == pytest.approx(100.40)
    assert result.structural.risk.risk_per_share == pytest.approx(0.30)


def test_rounding_moves_the_stop_outward_up_for_short_down_for_long():
    long_result = structural(direction="LONG", pullback_extreme_price=99.93,
                             frozen_atr=1.0, price_increment=0.25, entry_reference=100.00)
    assert long_result.structural.risk.hard_stop == pytest.approx(99.75)
    short_result = structural(direction="SHORT", pullback_extreme_price=100.07,
                              frozen_atr=1.0, price_increment=0.25, entry_reference=100.00)
    assert short_result.structural.risk.hard_stop == pytest.approx(100.25)
    assert short_result.structural.risk.risk_per_share == pytest.approx(0.25)


def test_an_unavailable_pullback_extreme_leaves_risk_unavailable_by_name():
    result = structural(pullback_extreme_price=None)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "PULLBACK_EXTREME_UNAVAILABLE"
    assert result.structural.targets == ()
    assert result.label is None


def test_an_unknown_price_increment_leaves_risk_unavailable_not_approximated():
    result = structural(price_increment=None)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "PRICE_INCREMENT_UNKNOWN"
    assert result.label is None


def test_a_stop_on_the_wrong_side_of_entry_is_an_invalid_geometry_not_a_negative_risk():
    result = structural(direction="LONG", pullback_extreme_price=100.50,
                        entry_reference=100.00, frozen_atr=0.0)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "INVALID_STOP_GEOMETRY"


def test_the_record_id_prefix_and_direction_are_checked():
    with pytest.raises(RecordError):
        build_pullback_structural_from_research(
            record_id_prefix="", direction="LONG", impulse_frozen_at=opened_at(),
            evaluated_at=opened_at() + timedelta(minutes=5),
            available_at=opened_at() + timedelta(minutes=5),
            entry_reference=100.00, pullback_extreme_price=99.90, frozen_atr=1.0,
            price_increment=0.01)
    with pytest.raises(RecordError):
        build_pullback_structural_from_research(
            record_id_prefix="m91q-test", direction="UP", impulse_frozen_at=opened_at(),
            evaluated_at=opened_at() + timedelta(minutes=5),
            available_at=opened_at() + timedelta(minutes=5),
            entry_reference=100.00, pullback_extreme_price=99.90, frozen_atr=1.0,
            price_increment=0.01)


def test_the_structural_reading_carries_the_supplied_instants():
    frozen = opened_at()
    evaluated = opened_at() + timedelta(minutes=5)
    available = opened_at() + timedelta(minutes=6)
    result = structural(frozen=frozen, evaluated=evaluated, available=available)
    assert result.structural.impulse_frozen_at == frozen
    assert result.structural.evaluated_at == evaluated
    assert result.structural.available_at == available


def test_the_structural_reading_stands_as_its_own_canonical_record():
    result = structural()
    reconstructed = PullbackStructural(
        definition_reference=result.structural.definition_reference,
        direction=result.structural.direction,
        impulse_frozen_at=result.structural.impulse_frozen_at,
        evaluated_at=result.structural.evaluated_at,
        available_at=result.structural.available_at, risk=result.structural.risk,
        targets=result.structural.targets, missing_reason=result.structural.missing_reason,
        record_ids=result.structural.record_ids)
    assert reconstructed == result.structural
