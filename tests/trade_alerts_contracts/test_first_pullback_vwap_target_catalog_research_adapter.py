"""M9.1R: `FIRST_PULLBACK_VWAP`'s structural target catalog, from real minute bars.

M0.3E section 7 builds the catalog from the frozen impulse extreme (a
caller-supplied fact, exactly like `pullback_extreme_price`), regular-session
HOD/LOD and prior-day high/low/close (all read here from real minute bars,
admitting `PROVISIONAL` through D-110 exactly like the M9.1K catalog's own
read), and known whole-dollar/half-dollar levels strictly between entry and
the furthest of those real levels. Keep only levels ahead in the trade
direction, merge exact prices while retaining every label, and sort by
directional distance; T1 is the nearest level at least 1.5R away and T2 the
nearest distinct later level from 2.5R through 4R.

Every bar below is a synthetic fixture. Passing a case proves only the
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
    RESEARCH_FIRST_PULLBACK_VWAP_TARGET_DEFINITION_REFERENCE,
    build_pullback_structural_from_research,
)
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.trade_alerts_models import Bar, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds

PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
PRIOR_DAY = "2026-07-02"


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91R_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", instrument_type="EQUITY",
            prefix="m91r"):
    high, low = max(opened, close) + 0.05, min(opened, close) - 0.05
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end, available_time=interval.end,
        normalized_time=interval.end, session=interval.session,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    return Bar(
        record_id=f"{prefix}-{symbol}-{number}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=True,
        open=opened, high=high, low=low, close=close, volume=1000 + number,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=False,
    )


def walk(first, step, count):
    values = [round(first + step * number, 2) for number in range(count + 1)]
    return list(zip(values, values[1:]))


def opened_at(day=DAY):
    return as_utc(session_bounds(datetime.fromisoformat(day).date())[0])


def history(symbol="SYNTH", *, day=DAY, prior_day=PRIOR_DAY, minutes=5, prior_price=100.20,
           path=None, changed=None, **request_changes):
    """A two-session `HistoryBatch`: a fully covered flat prior day, plus a
    sloped `minutes`-long window on `day` up to the caller's evaluated instant.
    """
    prior_open = as_utc(session_bounds(datetime.fromisoformat(prior_day).date())[0])
    day_open = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    path = path or walk(100.00, 0.10, minutes)
    values = dict(symbol=symbol, start=prior_open, end=day_open + timedelta(minutes=minutes))
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = []
    current_index = 0
    for number, interval in enumerate(request.expected_intervals()):
        if interval.session == prior_day:
            bars.append(make_bar(number, interval, prior_price, prior_price, symbol=symbol))
        else:
            opened, close = path[current_index]
            bars.append(make_bar(number, interval, opened, close, symbol=symbol))
            current_index += 1
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", conventions(), tuple(bars))


def structural(*, direction="LONG", entry_reference=100.00, pullback_extreme_price=99.90,
              frozen_atr=1.0, price_increment=0.01, symbol="SYNTH", instrument_type="EQUITY",
              impulse_extreme_price=101.00, minute_history=None, evaluated=None,
              available=None, **changes):
    values = dict(
        record_id_prefix="m91r-test", direction=direction,
        impulse_frozen_at=opened_at(), evaluated_at=evaluated or opened_at() + timedelta(minutes=5),
        available_at=available or evaluated or opened_at() + timedelta(minutes=5),
        entry_reference=entry_reference, pullback_extreme_price=pullback_extreme_price,
        frozen_atr=frozen_atr, price_increment=price_increment, symbol=symbol,
        instrument_type=instrument_type, impulse_extreme_price=impulse_extreme_price,
        minute_history=history() if minute_history is None else minute_history,
    )
    values.update(changes)
    return build_pullback_structural_from_research(**values)


# The default `history()` prior day is flat at 100.20 (high 100.25, low 100.15,
# close 100.20); the default current-day walk climbs 100.00 -> 100.50 over 5
# minutes (session high 100.55). With entry 100.00 and risk_per_share 0.15,
# the furthest ahead level is the caller-supplied impulse extreme (101.00), so
# the only whole/half-dollar level strictly between them is 100.50.


def test_t1_is_the_nearest_qualifying_real_level_prior_day_high():
    result = structural()
    targets = result.structural.targets
    assert [row.name for row in targets] == ["T1", "T2"]
    assert targets[0].price == pytest.approx(100.25)
    assert targets[0].r_multiple == pytest.approx((100.25 - 100.00) / 0.15)
    assert "PRIOR_DAY_HIGH" in targets[0].source
    assert result.structural.risk.hard_stop == pytest.approx(99.85)


def test_t2_is_the_nearest_qualifying_half_dollar_level():
    result = structural()
    targets = result.structural.targets
    assert targets[1].price == pytest.approx(100.50)
    assert targets[1].r_multiple == pytest.approx((100.50 - 100.00) / 0.15)
    assert "WHOLE_HALF_DOLLAR" in targets[1].source


def test_a_short_catalog_mirrors_the_same_merge_and_sort():
    result = structural(
        direction="SHORT", entry_reference=100.10, pullback_extreme_price=100.35,
        frozen_atr=1.0, price_increment=0.01, impulse_extreme_price=99.10,
        minute_history=history(prior_price=99.80, path=walk(100.10, -0.10, 5)))
    targets = result.structural.targets
    assert [row.name for row in targets] == ["T1", "T2"]
    assert targets[0].price == pytest.approx(99.55)
    assert "SESSION_LOW" in targets[0].source
    assert targets[1].price == pytest.approx(99.10)
    assert "IMPULSE_EXTREME" in targets[1].source
    assert result.structural.risk.hard_stop == pytest.approx(100.40)


def test_a_duplicate_price_merges_labels_into_one_target():
    result = structural(impulse_extreme_price=100.25)
    targets = result.structural.targets
    assert targets[0].price == pytest.approx(100.25)
    names = targets[0].source.split(":", 1)[1].split("+")
    assert set(names) == {"IMPULSE_EXTREME", "PRIOR_DAY_HIGH"}


def test_missing_impulse_extreme_price_leaves_targets_empty_but_stop_intact():
    result = structural(impulse_extreme_price=None)
    assert result.structural.risk is not None
    assert result.structural.risk.hard_stop == pytest.approx(99.85)
    assert result.structural.targets == ()
    assert result.structural.missing_reason is None
    assert result.label is None


def test_omitting_every_new_target_input_keeps_the_m9_1q_stop_only_contract():
    result = build_pullback_structural_from_research(
        record_id_prefix="m91r-test", direction="LONG", impulse_frozen_at=opened_at(),
        evaluated_at=opened_at() + timedelta(minutes=5),
        available_at=opened_at() + timedelta(minutes=5),
        entry_reference=100.00, pullback_extreme_price=99.90, frozen_atr=1.0,
        price_increment=0.01)
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is None


def test_an_incompatible_symbol_leaves_targets_empty_with_no_label():
    result = structural(symbol="OTHER")
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is None


def test_no_traded_session_bar_yet_leaves_the_catalog_incomplete():
    result = structural(evaluated=opened_at(), available=opened_at())
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is not None


def test_an_incomplete_prior_session_window_leaves_the_catalog_incomplete():
    def drop_one(bars):
        return [bar for bar in bars if bar.record_id != bars[0].record_id]
    result = structural(minute_history=history(changed=drop_one))
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is not None


def test_no_qualifying_t1_leaves_targets_empty_as_known_absence():
    result = structural(
        impulse_extreme_price=100.02,
        minute_history=history(prior_price=100.01, path=[(100.00, 100.00)] * 5))
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is not None


def test_the_produced_targets_stand_as_their_own_canonical_target_level_records():
    result = structural()
    for row in result.structural.targets:
        assert isinstance(row.price, float)
        assert isinstance(row.r_multiple, float)
        assert row.r_multiple > 0
        assert RESEARCH_FIRST_PULLBACK_VWAP_TARGET_DEFINITION_REFERENCE in row.source
    assert isinstance(result.structural, PullbackStructural)
    assert result.structural.definition_reference == (
        RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE)
