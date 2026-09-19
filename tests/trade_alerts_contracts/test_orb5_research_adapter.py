"""M9.1Y: `CRVOL_ORB5` bar-native inputs from real minute bars."""

from datetime import datetime, timedelta, timezone
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryConventions
from consensus_engine.orb5_research_adapter import (
    bar_tape_intensity, build_orb5_bar_observations, find_orb5_crossing, opening_range_from_bars,
)
from consensus_engine.orb5_trigger import TriggerPolicy
from consensus_engine.orb5_trade_walk import (
    bar_gate_coverage, build_orb5_geometry, build_orb5_trade_record, walk_orb5_trade,
)
from consensus_engine.search_run_bars import group_session_bars, history_batch_for
from consensus_engine.trade_alerts_models import RecordError

from dataclasses import dataclass

from consensus_engine.core17_bar_loader import iter_ohlcv_1m_records

START = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
TS_NS = int(START.timestamp()) * 1_000_000_000
MINUTE_NS = 60 * 1_000_000_000
HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"
CONVENTIONS = HistoryConventions(
    timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="UNKNOWN", publication="SYNTHETIC_TEST", evidence_reference="synthetic-test",
)


@dataclass(frozen=True)
class Row:
    instrument_id: int
    ts_event: int
    open: int = 100_000_000_000
    high: int = 102_000_000_000
    low: int = 99_000_000_000
    close: int = 101_000_000_000
    volume: int = 10
    publisher_id: int = 1


def _records(rows):
    return list(iter_ohlcv_1m_records(
        rows, dataset="EQUS.MINI", source_file_sha256=HASH, instrument_symbols={1: "SPY"},
        condition_by_date={"2026-08-21": "available"}, record_id_prefix="t"))


def _batch(rows, conventions=CONVENTIONS):
    grouped = group_session_bars(_records(rows), ["SPY"])
    return history_batch_for(grouped, "SPY", "2026-08-21", conventions)


def _five(highs=(102, 103, 102, 104, 102), skip=None):
    return [Row(1, TS_NS + i * MINUTE_NS, high=int(h * 1e9), low=int((99 - i % 2) * 1e9))
            for i, h in enumerate(highs) if i != skip]


def test_opening_range_is_high_and_low_of_all_five_minutes():
    result = opening_range_from_bars(
        symbol="SPY", instrument_type="ETF", minutes=5, minute_history=_batch(_five()))
    assert result.available and (result.high, result.low) == (104.0, 98.0)
    assert len(result.bar_record_ids) == 5
    assert result.label["provisional_intervals"] == 5


def test_missing_opening_minute_gives_no_range_not_a_partial_one():
    result = opening_range_from_bars(
        symbol="SPY", instrument_type="ETF", minutes=5, minute_history=_batch(_five(skip=2)))
    assert not result.available and result.high is None
    assert result.missing_reason == "OPENING_RANGE_BAR_NOT_READY"


def test_unknown_volume_units_and_stock_label_leave_range_unavailable():
    unknown = opening_range_from_bars(
        symbol="SPY", instrument_type="ETF", minutes=5,
        minute_history=_batch(_five(), HistoryConventions()))
    assert unknown.missing_reason is not None and not unknown.available
    stock = opening_range_from_bars(
        symbol="SPY", instrument_type="EQUITY", minutes=5, minute_history=_batch(_five()))
    assert stock.missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    with pytest.raises(RecordError):
        opening_range_from_bars(symbol="SPY", instrument_type="ETF", minutes=0,
                                minute_history=None)


def test_observations_reuse_latest_closed_bar_with_true_age():
    end = START + timedelta(minutes=5)
    instants = tuple(end + timedelta(seconds=15 * i) for i in range(3))
    rows, label = build_orb5_bar_observations(
        record_id_prefix="t", instants=instants, symbol="SPY", instrument_type="ETF",
        minute_history=_batch(_five()))
    assert [row.price for row in rows] == [101.0] * 3
    assert [row.age_seconds for row in rows] == [0.0, 15.0, 30.0]
    assert all(row.mode == "TAPE" and row.coverage_known for row in rows)
    assert label["provisional_intervals"] == 5
    assert len({row.record_id for row in rows}) == 3


def test_observation_before_any_bar_and_unknown_basis_are_missing_not_priced():
    early = (START + timedelta(seconds=30),)
    rows, _ = build_orb5_bar_observations(
        record_id_prefix="t", instants=early, symbol="SPY", instrument_type="ETF",
        minute_history=_batch(_five()))
    assert rows[0].price is None and rows[0].missing_reason == "NO_READY_BAR_BEFORE_INSTANT"
    rows, label = build_orb5_bar_observations(
        record_id_prefix="t", instants=early, symbol="SPY", instrument_type="ETF",
        minute_history=None)
    assert rows[0].price is None and label is None and not rows[0].coverage_known


def test_observation_inputs_are_validated():
    with pytest.raises(RecordError):
        build_orb5_bar_observations(record_id_prefix="t", instants=(), symbol="SPY",
                                    instrument_type="ETF", minute_history=None)
    with pytest.raises(RecordError):
        build_orb5_bar_observations(record_id_prefix="t", instants=(START, START),
                                    symbol="SPY", instrument_type="ETF", minute_history=None)


def test_tape_intensity_is_always_an_explicit_gap():
    result = bar_tape_intensity()
    assert result.ratio is None and not result.coverage_complete
    assert result.missing_reason == "NO_15S_TAPE_FROM_MINUTE_BARS"


def _stock_batch(rows):
    records = list(iter_ohlcv_1m_records(
        rows, dataset="EQUS.MINI", source_file_sha256=HASH, instrument_symbols={1: "SPY"},
        condition_by_date={"2026-08-21": "available"}, record_id_prefix="t",
        instrument_type="EQUITY"))
    return history_batch_for(group_session_bars(records, ["SPY"]), "SPY", "2026-08-21", CONVENTIONS)


def test_stock_file_label_lets_an_equity_opening_range_through():
    batch = _stock_batch(_five())
    assert {r.bar.metadata.instrument_type for r in _records(_five())} == {"ETF"}
    result = opening_range_from_bars(
        symbol="SPY", instrument_type="EQUITY", minutes=5, minute_history=batch)
    assert result.available and (result.high, result.low) == (104.0, 98.0)
    etf = opening_range_from_bars(
        symbol="SPY", instrument_type="ETF", minutes=5, minute_history=batch)
    assert etf.missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    rows, _ = build_orb5_bar_observations(
        record_id_prefix="t", instants=(START + timedelta(minutes=5),), symbol="SPY",
        instrument_type="EQUITY", minute_history=batch)
    assert rows[0].price == 101.0


def test_loader_refuses_an_unknown_instrument_label():
    with pytest.raises(RecordError):
        list(iter_ohlcv_1m_records(
            _five(), dataset="EQUS.MINI", source_file_sha256=HASH,
            instrument_symbols={1: "SPY"}, condition_by_date={"2026-08-21": "available"},
            record_id_prefix="t", instrument_type="FUTURE"))


POLICY = TriggerPolicy(
    version="t1", definition_reference="synthetic-test", mode="TAPE", buffer_floor=0.5,
    buffer_atr_multiple=0.0, window_open_seconds=120, window_close_seconds=300,
    sample_count=2, min_accepting_samples=1, sample_interval_seconds=60,
    max_observation_age_seconds=0.0, min_participation_ratio=1.0,
    min_projection_elapsed_seconds=0, max_attempts_per_direction=2, action_cooldown_seconds=0.0)


def _session(closes):
    """Five opening minutes (high 104, low 98) then one bar per given close."""
    rows = _five()
    for i, close in enumerate(closes):
        rows.append(Row(1, TS_NS + (5 + i) * MINUTE_NS, high=int((close + 1) * 1e9),
                        low=int((close - 1) * 1e9), open=int(close * 1e9), close=int(close * 1e9)))
    return rows


def _search(rows, **over):
    args = dict(policy=POLICY, direction="LONG", symbol="SPY", instrument_type="ETF",
                opening_range_minutes=5, search_minutes=4, latest_atr=1.0,
                minute_history=_batch(rows), record_id_prefix="t")
    args.update(over)
    return find_orb5_crossing(**args)


def test_first_fresh_crossing_is_frozen_with_its_buffered_boundary():
    result = _search(_session([101, 105, 106]))
    candidate = result.candidate
    assert result.missing_reason is None and candidate is not None
    assert candidate.boundary == 104.5 and candidate.buffer == 0.5
    assert candidate.crossed_at == START + timedelta(minutes=7)
    assert len(candidate.input_record_ids) == 2 and result.label is not None


def test_no_crossing_short_direction_and_gaps_give_no_candidate():
    assert _search(_session([101, 102, 103])).missing_reason == "NO_FRESH_CROSSING_IN_SEARCH_WINDOW"
    down = _search(_session([101, 96, 95]), direction="SHORT")
    assert down.candidate is not None and down.candidate.boundary == 97.5
    assert _search(_session([105]), latest_atr=None).missing_reason == "ATR_UNAVAILABLE"
    assert _search(_session([105]), minute_history=None).candidate is None
    assert _search(_five(skip=2)).missing_reason == "OPENING_RANGE_BAR_NOT_READY"
    with pytest.raises(RecordError):
        _search(_session([105]), search_minutes=0)


def _walk_setup(closes, direction="LONG", **over):
    rows = _session(closes)
    search = _search(rows, direction=direction, **over)
    return rows, search.candidate


def test_gate_coverage_runs_only_the_crossing_and_records_the_rest_off():
    coverage = bar_gate_coverage()
    assert coverage["on"] == ["BOUNDARY_CROSSING"]
    assert {row["gate"] for row in coverage["off"]} >= {
        "ACCEPTANCE", "PARTICIPATION", "LAST_TRADE_BEYOND_BOUNDARY", "ELIGIBILITY_ARMED"}


def test_geometry_uses_far_edge_stop_rounded_outward_and_fixed_targets():
    _, long_candidate = _walk_setup([101, 105, 106])
    geometry = build_orb5_geometry(long_candidate, entry_price=105.0, tick=0.01).geometry
    assert geometry.stop == 97.95 and geometry.risk == 7.05
    assert dict(geometry.targets) == {"EXIT_FIXED_2R_V2": 119.1, "EXIT_FIXED_3R_V2": 126.15}
    _, short_candidate = _walk_setup([101, 96, 95], "SHORT")
    short = build_orb5_geometry(short_candidate, entry_price=96.0, tick=0.01).geometry
    assert short.stop == 104.05 and round(short.risk, 2) == 8.05
    assert short.targets[0][1] < 96.0
    assert build_orb5_geometry(long_candidate, entry_price=105.0, tick=None).missing_reason == "TICK_UNKNOWN"
    assert build_orb5_geometry(long_candidate, entry_price=None, tick=0.01).missing_reason == "ENTRY_PRICE_UNAVAILABLE"
    assert build_orb5_geometry(long_candidate, entry_price=97.0, tick=0.01).missing_reason == "STOP_NOT_ADVERSE_TO_ENTRY"


def _quiet(minute, low=104.5, high=105.5, opened=105.0):
    return Row(1, TS_NS + minute * MINUTE_NS, open=int(opened * 1e9), high=int(high * 1e9),
               low=int(low * 1e9), close=int(opened * 1e9))


def test_walk_takes_target_stop_first_and_leaves_gaps_unresolved():
    rows, candidate = _walk_setup([101, 105, 106])
    entry_time = START + timedelta(minutes=8)
    geometry = build_orb5_geometry(candidate, entry_price=105.0, tick=0.01).geometry

    def go(special=None, exit_name="EXIT_FIXED_2R_V2", skip=None):
        special = special or {}
        data = list(rows) + [special.get(m, _quiet(m)) for m in range(8, 390) if m != skip]
        return walk_orb5_trade(geometry, exit_name=exit_name, entry_time=entry_time,
                               symbol="SPY", minute_history=_batch(data))

    assert go().reason == "NO_EXIT_BY_SESSION_CLOSE"
    won = go({10: _quiet(10, 104, 120)})
    assert (won.status, won.r_multiple) == ("TARGET", 2.0)
    both = go({10: _quiet(10, 97, 130)})
    assert both.status == "STOP" and both.r_multiple == -1.0
    gapped = go({10: _quiet(10, 90, 95, opened=95.0)})
    assert gapped.status == "STOP" and gapped.r_multiple < -1.0
    assert go({10: _quiet(10, 104, 127)}, "EXIT_FIXED_3R_V2").r_multiple == 3.0
    assert go(skip=9).reason == "COVERAGE_GAP_BEFORE_EXIT"
    with pytest.raises(RecordError):
        go(exit_name="EXIT_D090_STRUCTURE_V2")


def test_trade_record_wires_crossing_geometry_and_walk_into_one_r():
    rows = _session([101, 105, 106]) + [_quiet(m) for m in range(8, 390)]
    rows = [r for r in rows if r.ts_event != TS_NS + 10 * MINUTE_NS] + [_quiet(10, 104, 120)]
    args = dict(policy=POLICY, direction="LONG", exit_name="EXIT_FIXED_2R_V2", symbol="SPY",
                instrument_type="ETF", opening_range_minutes=5, search_minutes=4,
                latest_atr=1.0, tick=0.01, entry_price=105.0,
                entry_time=START + timedelta(minutes=8), entry_source="TEST_SUPPLIED",
                minute_history=_batch(rows), record_id_prefix="t")
    done = build_orb5_trade_record(**args)
    assert (done.status, done.r_multiple, done.resolved) == ("TARGET", 2.0, True)
    assert done.candidate.boundary == 104.5 and done.geometry.stop == 97.95
    assert done.entry_source == "TEST_SUPPLIED" and done.gate_coverage["on"] == ["BOUNDARY_CROSSING"]
    assert build_orb5_trade_record(**{**args, "latest_atr": None}).reason == "ATR_UNAVAILABLE"
    assert build_orb5_trade_record(**{**args, "latest_atr": None}).status == "NO_CANDIDATE"
    assert build_orb5_trade_record(**{**args, "tick": None}).status == "NO_GEOMETRY"
    assert build_orb5_trade_record(**{**args, "entry_time": None}).reason == "ENTRY_TIME_UNAVAILABLE"
    missing = build_orb5_trade_record(**{**args, "minute_history": None})
    assert missing.status == "NO_CANDIDATE" and not missing.resolved
    with pytest.raises(RecordError):
        build_orb5_trade_record(**{**args, "entry_time": START + timedelta(minutes=6)})
    with pytest.raises(RecordError):
        build_orb5_trade_record(**{**args, "entry_source": " "})


def test_grid_run_shares_bar_rule_per_opening_range_and_refuses_to_rank():
    from datetime import date
    from consensus_engine.orb5_grid_run import Orb5Session, run_orb5_grid

    rows = _session([101, 105, 106]) + [_quiet(m) for m in range(8, 390)]
    rows = [r for r in rows if r.ts_event != TS_NS + 10 * MINUTE_NS] + [_quiet(10, 104, 120)]
    entry = START + timedelta(minutes=8)
    session = Orb5Session(
        "SPY", date(2026, 8, 21), "ETF", 1.0, 0.01, {"LONG": 105.0, "SHORT": None},
        {"LONG": entry, "SHORT": None}, "TEST_SUPPLIED", _batch(rows))
    run = run_orb5_grid(policy=POLICY, exit_name="EXIT_FIXED_2R_V2", sessions=[session],
                        search_minutes=4, record_id_prefix="g")
    assert len(run.tallies) == 18 and [t.table_order for t in run.tallies] == list(range(18))
    assert sorted(len(g) for g in run.identical_groups) == [9, 9]
    five = [t for t in run.tallies if t.opening_range_minutes == 5]
    assert all(t.trades == 1 and t.mean_gross_r == 2.0 and t.weekly_gross_win_rate == 1.0 for t in five)
    assert all(t.axes_not_tested[0][0] == "D-044" for t in run.tallies)
    assert run.ranking_status == "NOT_RANKABLE" and len(run.ranking_blockers) == 3
    with pytest.raises(RecordError):
        run_orb5_grid(policy=POLICY, exit_name="EXIT_UNKNOWN", sessions=[session],
                      search_minutes=4, record_id_prefix="g")
    with pytest.raises(RecordError):
        run_orb5_grid(policy=POLICY, exit_name="EXIT_FIXED_2R_V2", sessions=[],
                      search_minutes=4, record_id_prefix="g")


def test_quote_filled_record_costs_the_entry_and_leaves_exit_cost_off():
    from consensus_engine.fill_cost_model import POLICY_VERSION, FillCostPolicy
    from consensus_engine.orb5_trade_walk import build_orb5_quote_filled_record
    from consensus_engine.trade_alerts_models import Quote, SourceMetadata

    rows = _session([101, 105, 106]) + [_quiet(m) for m in range(8, 390)]
    rows = [r for r in rows if r.ts_event != TS_NS + 10 * MINUTE_NS] + [_quiet(10, 104, 120)]
    crossed = START + timedelta(minutes=7)

    def meta():
        return SourceMetadata(
            instrument_id="SPY", instrument_type="ETF", source="SYNTHETIC", source_time=crossed,
            received_time=crossed, available_time=crossed + timedelta(minutes=5),
            normalized_time=crossed + timedelta(minutes=5), session="2026-08-21",
            data_mode="FIXTURE", quality="VALID")

    def trade(rid, sec, price):
        return Quote(record_id=rid, metadata=meta(), quote_time=None,
                     trade_time=crossed + timedelta(seconds=sec), bid=None, ask=None, last=price,
                     last_size=100, bid_size=None, ask_size=None, status="VALID")

    def quote(rid, sec, bid, ask):
        return Quote(record_id=rid, metadata=meta(), quote_time=crossed + timedelta(seconds=sec),
                     trade_time=None, bid=bid, ask=ask, last=None, last_size=None,
                     bid_size=100, ask_size=100, status="VALID")

    args = dict(policy=POLICY, fill_policy=FillCostPolicy(POLICY_VERSION, 0.0, 0.01),
                direction="LONG", exit_name="EXIT_FIXED_2R_V2", symbol="SPY",
                instrument_type="ETF", opening_range_minutes=5, search_minutes=4,
                latest_atr=1.0, tick=0.01, trades=[trade("p1", 5, 105.0), trade("p2", 9, 90.0)],
                quotes=[quote("q1", 1, 104.9, 105.1)], minute_history=_batch(rows),
                record_id_prefix="t")
    done = build_orb5_quote_filled_record(**args)
    assert done.fill.status == "FILLED" and round(done.fill.modeled_price, 2) == 105.11
    assert done.record.entry_source == "D106_D107_QUOTE_FILL"
    assert done.record.geometry.entry == done.fill.modeled_price
    assert done.record.geometry.risk > 7.05 and done.record.walk.r_multiple == 2.0
    assert done.resolved and done.cost_scope["off"][0]["gate"] == "EXIT_SIDE_COST"
    nothing = build_orb5_quote_filled_record(**{**args, "trades": []})
    assert (nothing.status, nothing.reason, nothing.resolved) == ("NO_FILL", "NO_TRADE_IN_WINDOW", False)
    noquote = build_orb5_quote_filled_record(**{**args, "quotes": []})
    assert noquote.reason == "NO_QUOTE_AT_FILL"
    assert build_orb5_quote_filled_record(**{**args, "latest_atr": None}).status == "NO_CANDIDATE"


def test_structure_exit_selects_d090_targets_and_walks_two_units():
    from consensus_engine.orb5_trade_walk import (
        build_orb5_structure_exit_record, select_orb5_structure_targets,
    )

    rows = _session([101, 105, 106])
    _, candidate = _walk_setup([101, 105, 106])
    geometry = build_orb5_geometry(candidate, entry_price=105.0, tick=0.01).geometry  # R = 7.05
    levels = [("PDH", 116.0), ("PMH", 116.0), ("OR_MEASURED_MOVE", 123.0), ("BEHIND", 100.0)]
    picked = select_orb5_structure_targets(geometry, levels, catalog_complete=True)
    assert (picked.status, picked.t1, picked.t2) == ("SELECTED", 116.0, 123.0)
    assert picked.labels[116.0] == ("PDH", "PMH")
    near = select_orb5_structure_targets(geometry, levels + [("NEAR", 112.0)], catalog_complete=True)
    assert near.status == "SUPPRESSED_NEAR_LEVEL" and near.t1 is None
    assert select_orb5_structure_targets(geometry, [("X", 110.0)], catalog_complete=True).status == "SUPPRESSED_NEAR_LEVEL"
    assert select_orb5_structure_targets(geometry, [("X", 100.0)], catalog_complete=True).status == "NO_T1"
    assert select_orb5_structure_targets(geometry, levels, catalog_complete=False).status == "CATALOG_INCOMPLETE"
    only_t1 = select_orb5_structure_targets(geometry, [("A", 116.0), ("B", 121.0)], catalog_complete=True)
    assert (only_t1.t1, only_t1.t2) == (116.0, None)

    def go(special=None, lv=levels, complete=True, skip=None, **over):
        special = special or {}
        data = list(rows) + [special.get(m, _quiet(m)) for m in range(8, 390) if m != skip]
        args = dict(policy=POLICY, direction="LONG", symbol="SPY", instrument_type="ETF",
                    opening_range_minutes=5, search_minutes=4, latest_atr=1.0, tick=0.01,
                    entry_price=105.0, entry_time=START + timedelta(minutes=8),
                    entry_source="TEST_SUPPLIED", levels=lv, catalog_complete=complete,
                    minute_history=_batch(data), record_id_prefix="t")
        return build_orb5_structure_exit_record(**{**args, **over})

    both = go({10: _quiet(10, 104, 124)})
    assert both.status == "TARGET" and [u[0] for u in both.unit_exits] == ["T1", "T2"]
    assert both.r_multiple == pytest.approx((11 + 18) / (2 * 7.05))
    later = go({10: _quiet(10, 104, 117), 20: _quiet(20, 104, 124)})
    assert later.status == "TARGET" and later.r_multiple == both.r_multiple
    after_stop = go({10: _quiet(10, 104, 117), 20: _quiet(20, 90, 106)})
    assert after_stop.status == "T1_THEN_STOP"
    assert after_stop.r_multiple == pytest.approx((11 + (97.95 - 105)) / (2 * 7.05))
    stopped = go({10: _quiet(10, 97, 130)})
    assert stopped.status == "STOP" and stopped.r_multiple == -1.0
    gapped = go({10: _quiet(10, 90, 95, opened=95.0)})
    assert gapped.status == "STOP" and gapped.r_multiple < -1.0
    horizon = go({10: _quiet(10, 104, 117)})
    assert horizon.status == "HORIZON" and horizon.unit_exits[1][0] == "HORIZON"
    assert horizon.r_multiple == pytest.approx((11 + 0) / (2 * 7.05))
    no_t2 = go({10: _quiet(10, 104, 117)}, lv=[("A", 116.0)])
    assert no_t2.status == "HORIZON" and no_t2.targets.t2 is None
    assert go().status == "HORIZON" and go().r_multiple == 0.0
    assert go(skip=200).status == "UNRESOLVED" and go(skip=200).reason == "COVERAGE_GAP_BEFORE_EXIT"
    assert go(skip=389).reason == "NO_HORIZON_CLOSE_BAR" or go(skip=389).reason == "COVERAGE_GAP_BEFORE_EXIT"
    incomplete = go(complete=False)
    assert incomplete.status == "UNRESOLVED" and incomplete.reason == "CATALOG_INCOMPLETE"
    assert go(lv=levels + [("NEAR", 112.0)]).status == "NO_TARGETS"
    assert go(tick=None).status == "NO_GEOMETRY" and go(latest_atr=None).status == "NO_CANDIDATE"
    assert go(entry_time=None).reason == "ENTRY_TIME_UNAVAILABLE"
    assert both.cost_scope["label"] == "OFF_GATES_UNTESTED_D104" and not go(complete=False).resolved
    with pytest.raises(RecordError):
        go(entry_time=START + timedelta(minutes=6))


def test_grid_run_uses_d090_structure_exit_and_keeps_incomplete_catalog_unresolved():
    from dataclasses import replace
    from datetime import date
    from consensus_engine.orb5_grid_run import Orb5Session, run_orb5_grid

    rows = _session([101, 105, 106]) + [_quiet(m) for m in range(8, 390)]
    rows = [r for r in rows if r.ts_event != TS_NS + 10 * MINUTE_NS] + [_quiet(10, 104, 124)]
    session = Orb5Session(
        "SPY", date(2026, 8, 21), "ETF", 1.0, 0.01, {"LONG": 105.0, "SHORT": None},
        {"LONG": START + timedelta(minutes=8), "SHORT": None}, "TEST_SUPPLIED", _batch(rows),
        levels=(("PDH", 116.0), ("OR_MEASURED_MOVE", 123.0)), catalog_complete=True)
    run = run_orb5_grid(policy=POLICY, exit_name="EXIT_D090_STRUCTURE_V2", sessions=[session],
                        search_minutes=4, record_id_prefix="g")
    assert run.exit_name == "EXIT_D090_STRUCTURE_V2" and len(run.tallies) == 18
    five = [t for t in run.tallies if t.opening_range_minutes == 5]
    assert all(t.trades == 1 and t.mean_gross_r == pytest.approx(29 / (2 * 7.05)) for t in five)
    assert all(t.weekly_gross_win_rate == 1.0 and t.weeks == 1 for t in five)
    assert run.ranking_status == "NOT_RANKABLE"
    bare = run_orb5_grid(policy=POLICY, exit_name="EXIT_D090_STRUCTURE_V2",
                         sessions=[replace(session, catalog_complete=False)],
                         search_minutes=4, record_id_prefix="g")
    five = [t for t in bare.tallies if t.opening_range_minutes == 5]
    assert all(t.trades == 0 and t.mean_gross_r is None for t in five)
    assert all(r.reason == "CATALOG_INCOMPLETE" for t in five for r in t.records if r.record.direction == "LONG")


def test_level_catalog_uses_supplied_features_and_stays_incomplete_without_the_rest():
    from consensus_engine.orb5_level_catalog import build_orb5_level_catalog
    from consensus_engine.orb5_research_adapter import Orb5OpeningRange
    from consensus_engine.orb5_trade_walk import select_orb5_structure_targets
    from consensus_engine.trade_alerts_models import FeatureSnapshot, FeatureValue, SourceMetadata

    meta = SourceMetadata(
        instrument_id="SPY", instrument_type="ETF", source="DERIVED_D090", source_time=START,
        received_time=START, available_time=START, normalized_time=START, session="2026-08-21",
        data_mode="BAR_HLC3_WITH_EXPLICIT_OPEN", quality="VALID")
    snap = FeatureSnapshot(
        record_id="s1", metadata=meta, evaluated_at=START, feature_version="V",
        features=(FeatureValue("PDH_V1", 110.0, "USD_PER_SHARE"),
                  FeatureValue("PDL_V1", 90.0, "USD_PER_SHARE"),
                  FeatureValue("PMH_V1", None, "USD_PER_SHARE", "INCOMPLETE_PREMARKET")))
    rng = Orb5OpeningRange(104.0, 100.0, 5, (), None, None)
    long = build_orb5_level_catalog(snap, rng, direction="LONG")
    short = build_orb5_level_catalog(snap, rng, direction="SHORT")
    assert dict(long.levels) == {"PDH": 110.0, "PDL": 90.0, "OR_MEASURED_MOVE": 108.0}
    assert dict(short.levels)["OR_MEASURED_MOVE"] == 96.0
    assert long.family_states["PMH"] == "UNKNOWN" and long.unknown_reasons["PMH"] == "INCOMPLETE_PREMARKET"
    assert long.family_states["PML"] == "UNKNOWN" and long.unknown_reasons["PML"] == "FEATURE_ABSENT"
    assert {"ATR_PROJECTION", "DAILY_SWING", "PRIOR_SESSION_BAR_PROFILE"} <= set(long.unknown_reasons)
    assert long.unknown_reasons["ATR_PROJECTION"] == "FEATURE_ABSENT"
    assert not long.complete
    with_atr = FeatureSnapshot(
        record_id="s2", metadata=meta, evaluated_at=START, feature_version="V",
        features=snap.features + (FeatureValue("PRIOR_REGULAR_CLOSE_V1", 100.0, "USD_PER_SHARE"),
                                  FeatureValue("DAILY_ATR_14_SMA_V1", 2.5, "USD_PER_SHARE")))
    atr_long = build_orb5_level_catalog(with_atr, rng, direction="LONG")
    assert atr_long.family_states["ATR_PROJECTION"] == "PRESENT"
    assert dict(atr_long.levels)["ATR_PROJECTION_UP"] == 102.5
    assert dict(atr_long.levels)["ATR_PROJECTION_DOWN"] == 97.5
    assert "ATR_PROJECTION" not in atr_long.unknown_reasons and not atr_long.complete
    no_atr = FeatureSnapshot(
        record_id="s3", metadata=meta, evaluated_at=START, feature_version="V",
        features=snap.features + (FeatureValue("PRIOR_REGULAR_CLOSE_V1", 100.0, "USD_PER_SHARE"),
                                  FeatureValue("DAILY_ATR_14_SMA_V1", None, "USD_PER_SHARE",
                                               "INCOMPLETE_15_SESSION_DAILY_WINDOW")))
    unknown = build_orb5_level_catalog(no_atr, rng, direction="SHORT")
    assert unknown.unknown_reasons["ATR_PROJECTION"] == "INCOMPLETE_15_SESSION_DAILY_WINDOW"
    assert not any(name.startswith("ATR_PROJECTION") for name, _ in unknown.levels)
    bare = build_orb5_level_catalog(snap, Orb5OpeningRange(None, None, 5, (), "GAP", None), direction="LONG")
    assert bare.unknown_reasons["OR_MEASURED_MOVE"] == "GAP" and len(bare.levels) == 2
    from consensus_engine.orb5_trade_walk import Orb5Geometry
    geometry = Orb5Geometry("LONG", 105.0, 99.0, 6.0, ())
    result = select_orb5_structure_targets(geometry, long.levels, catalog_complete=long.complete)
    assert result.status == "CATALOG_INCOMPLETE"
    with pytest.raises(RecordError):
        build_orb5_level_catalog(snap, rng, direction="UP")


def test_session_builder_keys_catalogs_by_direction_and_opening_range_without_lookahead():
    from consensus_engine.orb5_grid_run import run_orb5_grid
    from consensus_engine.orb5_session_builder import NOT_YET_COMPLETE, build_orb5_session

    rows = _five() + [_quiet(m) for m in range(5, 390)]
    common = dict(
        ticker="SPY", instrument_type="ETF", minute_history=_batch(rows), daily_history=None,
        latest_atr=1.0, tick=0.01, entry_price={"LONG": 105.0, "SHORT": None},
        entry_time={"LONG": START + timedelta(minutes=8), "SHORT": None},
        entry_source="TEST_SUPPLIED")
    session = build_orb5_session(evaluated_at=START + timedelta(minutes=6), **common)
    assert sorted(session.catalogs) == [("LONG", 5), ("LONG", 15), ("SHORT", 5), ("SHORT", 15)]
    long5, complete5 = session.catalogs[("LONG", 5)]
    assert dict(long5)["OR_MEASURED_MOVE"] == 110.0 and not complete5
    assert dict(session.catalogs[("SHORT", 5)][0])["OR_MEASURED_MOVE"] == 92.0
    assert "OR_MEASURED_MOVE" not in dict(session.catalogs[("LONG", 15)][0])
    assert not any(done for _, done in session.catalogs.values())
    early = build_orb5_session(evaluated_at=START + timedelta(minutes=4), **common)
    assert "OR_MEASURED_MOVE" not in dict(early.catalogs[("LONG", 5)][0])
    assert NOT_YET_COMPLETE == "OPENING_RANGE_NOT_COMPLETE_AT_EVALUATION"
    run = run_orb5_grid(policy=POLICY, exit_name="EXIT_D090_STRUCTURE_V2", sessions=[session],
                        search_minutes=4, record_id_prefix="b")
    assert all(t.trades == 0 for t in run.tallies)
    with pytest.raises(RecordError):
        build_orb5_session(evaluated_at=START, **{**common, "ticker": "QQQ"})


def test_training_sessions_skip_degraded_and_missing_days_and_fill_nothing_in():
    from consensus_engine.orb5_training_sessions import ENTRY_SOURCE, build_training_sessions

    rows = _five() + [_quiet(m) for m in range(5, 390)]
    grouped = group_session_bars(_records(rows), ["SPY"])
    result = build_training_sessions(
        grouped, pairs=[("SPY", "2026-08-21"), ("SPY", "2026-08-24")],
        conventions=CONVENTIONS, instrument_type="ETF", evaluation_minutes_after_open=20,
        atr_by_pair={("SPY", "2026-08-21"): 1.5}, tick_by_ticker={"SPY": 0.01})
    assert [s.ticker for s in result.sessions] == ["SPY"]
    session = result.sessions[0]
    assert (session.latest_atr, session.tick) == (1.5, 0.01)
    assert session.entry_price == {"LONG": None, "SHORT": None}
    assert session.entry_source == ENTRY_SOURCE
    assert sorted(session.catalogs) == [("LONG", 5), ("LONG", 15), ("SHORT", 5), ("SHORT", 15)]
    assert not any(done for _, done in session.catalogs.values())
    assert result.skipped == (("SPY", "2026-08-24", "NO_USABLE_BARS"),)
    assert result.without_prior_session == (("SPY", "2026-08-21"),)
    bad = group_session_bars(list(iter_ohlcv_1m_records(
        rows[:5], dataset="EQUS.MINI", source_file_sha256=HASH, instrument_symbols={1: "SPY"},
        condition_by_date={"2026-08-21": "degraded"}, record_id_prefix="t")), ["SPY"])
    skipped = build_training_sessions(
        bad, pairs=[("SPY", "2026-08-21")], conventions=CONVENTIONS, instrument_type="ETF",
        evaluation_minutes_after_open=20)
    assert skipped.sessions == () and skipped.skipped == (("SPY", "2026-08-21", "DEGRADED_SESSION"),)
    with pytest.raises(RecordError):
        build_training_sessions(grouped, pairs=[("SPY", "2026-08-21")], conventions=CONVENTIONS,
                                instrument_type="ETF", evaluation_minutes_after_open=10)
    with pytest.raises(RecordError):
        build_training_sessions(grouped, pairs=[("SPY", "2026-08-21")] * 2,
                                conventions=CONVENTIONS, instrument_type="ETF",
                                evaluation_minutes_after_open=20)


def test_retained_file_loader_opens_named_files_and_builds_sessions():
    from pathlib import Path
    from consensus_engine.orb5_retained_sessions import load_retained_training_sessions

    rows = _five() + [_quiet(m) for m in range(5, 390)]
    opened = []

    def opener(job_dir, name):
        opened.append((job_dir, name))
        return iter_ohlcv_1m_records(
            rows, dataset="EQUS.MINI", source_file_sha256=HASH, instrument_symbols={1: "SPY"},
            condition_by_date={"2026-08-21": "available"}, record_id_prefix=name)

    common = dict(conventions=CONVENTIONS, instrument_type="ETF", evaluation_minutes_after_open=20,
                  opener=opener)
    result = load_retained_training_sessions(
        Path("/synthetic"), ["a.dbn.zst"], pairs=[("SPY", "2026-08-21"), ("SPY", "2026-08-24")],
        **common)
    assert opened == [(Path("/synthetic"), "a.dbn.zst")]
    assert [s.ticker for s in result.sessions] == ["SPY"]
    assert result.skipped == (("SPY", "2026-08-24", "NO_USABLE_BARS"),)
    assert result.without_prior_session == (("SPY", "2026-08-21"),)
    for bad in ([], ["a.dbn.zst", "a.dbn.zst"]):
        with pytest.raises(RecordError):
            load_retained_training_sessions(
                Path("/synthetic"), bad, pairs=[("SPY", "2026-08-21")], **common)
    with pytest.raises(RecordError):
        load_retained_training_sessions(Path("/synthetic"), ["a.dbn.zst"], pairs=[], **common)
