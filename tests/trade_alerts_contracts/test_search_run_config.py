"""M9.1V part 1 contracts for the frozen stage-1/stage-2 search catalog."""

import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS,
    PLAYBOOKS,
    STAGE1_CANDIDATES,
    STAGE1_GRID_SIZES,
    STAGE2_CANDIDATES,
    TRAINING_TICKERS,
    Candidate,
    TrainingMeasurement,
    rank_training_candidates,
)
from consensus_engine.trade_alerts_models import RecordError


def test_training_and_held_out_split_matches_d107():
    assert TRAINING_TICKERS == ("NVDA", "MSFT", "AAPL", "TSLA", "LLY", "SPY", "QQQ", "XLV", "USO")
    assert HELD_OUT_TICKERS == ("GOOGL", "AMZN", "META", "AVGO", "BRK.B", "IWM", "GLD", "VXX")
    assert len(TRAINING_TICKERS) == 9
    assert len(HELD_OUT_TICKERS) == 8
    assert set(TRAINING_TICKERS).isdisjoint(HELD_OUT_TICKERS)


def test_playbook_names_match_frozen_four():
    assert PLAYBOOKS == ("CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")


@pytest.mark.parametrize(
    "playbook,expected_size",
    [
        ("CRVOL_ORB5", 18),
        ("HOD_COMP_RS", 4),
        ("OR_FAILURE_REV", 2),
        ("FIRST_PULLBACK_VWAP", 4),
    ],
)
def test_stage1_grid_sizes_match_preregistration(playbook, expected_size):
    assert len(STAGE1_CANDIDATES[playbook]) == expected_size
    assert STAGE1_GRID_SIZES[playbook] == expected_size


def test_stage1_candidate_ids_are_unique_within_each_playbook():
    for playbook, candidates in STAGE1_CANDIDATES.items():
        ids = [c.candidate_id for c in candidates]
        assert len(ids) == len(set(ids)), playbook


def test_stage1_candidates_include_current_defaults():
    orb5_ids = {c.candidate_id for c in STAGE1_CANDIDATES["CRVOL_ORB5"]}
    assert "OR5|RVOL_2_0|ACC_10S_070" in orb5_ids
    hodcomp_ids = {c.candidate_id for c in STAGE1_CANDIDATES["HOD_COMP_RS"]}
    assert "COMP_ON_060|RS_MANDATORY" in hodcomp_ids
    orfail_ids = {c.candidate_id for c in STAGE1_CANDIDATES["OR_FAILURE_REV"]}
    assert "CONFIRMED" in orfail_ids
    pullback_ids = {c.candidate_id for c in STAGE1_CANDIDATES["FIRST_PULLBACK_VWAP"]}
    assert "VWAP_MANDATORY|AVWAP_OFF" in pullback_ids


def test_stage1_table_order_is_fixed_and_zero_based_per_playbook():
    for candidates in STAGE1_CANDIDATES.values():
        orders = [c.table_order for c in candidates]
        assert orders == list(range(len(candidates)))


def test_stage2_candidates_match_the_five_preregistered_combinations():
    assert [c.candidate_id for c in STAGE2_CANDIDATES] == [
        "SOLO_ORB5", "SOLO_HODCOMP", "SOLO_ORFAIL", "SOLO_PULLBACK", "ALL_FOUR",
    ]
    all_four = STAGE2_CANDIDATES[-1]
    assert dict(all_four.settings)["playbooks"] == PLAYBOOKS
    solo_orb5 = STAGE2_CANDIDATES[0]
    assert dict(solo_orb5.settings)["playbooks"] == ("CRVOL_ORB5",)


def test_rank_training_candidates_rejects_empty_sequence():
    with pytest.raises(RecordError):
        rank_training_candidates([])


def _measurement(candidate_id, order, profit, win_rate=0.5, drawdown=2.0):
    return TrainingMeasurement(
        candidate=Candidate(candidate_id=candidate_id, settings=(), table_order=order),
        mean_profit_r=profit,
        weekly_win_rate=win_rate,
        drawdown_recovery_weeks=drawdown,
    )


def test_rank_training_candidates_picks_highest_mean_profit():
    winner = rank_training_candidates([
        _measurement("A", 0, profit=0.10),
        _measurement("B", 1, profit=0.25),
        _measurement("C", 2, profit=0.05),
    ])
    assert winner.candidate.candidate_id == "B"


def test_rank_training_candidates_breaks_profit_tie_on_weekly_win_rate():
    winner = rank_training_candidates([
        _measurement("A", 0, profit=0.10, win_rate=0.55),
        _measurement("B", 1, profit=0.10, win_rate=0.70),
    ])
    assert winner.candidate.candidate_id == "B"


def test_rank_training_candidates_breaks_double_tie_on_lowest_drawdown():
    winner = rank_training_candidates([
        _measurement("A", 0, profit=0.10, win_rate=0.60, drawdown=3.0),
        _measurement("B", 1, profit=0.10, win_rate=0.60, drawdown=1.5),
    ])
    assert winner.candidate.candidate_id == "B"


def test_rank_training_candidates_breaks_triple_tie_on_lowest_table_order():
    winner = rank_training_candidates([
        _measurement("A", 2, profit=0.10, win_rate=0.60, drawdown=2.0),
        _measurement("B", 0, profit=0.10, win_rate=0.60, drawdown=2.0),
        _measurement("C", 1, profit=0.10, win_rate=0.60, drawdown=2.0),
    ])
    assert winner.candidate.candidate_id == "B"


def test_rank_training_candidates_single_measurement_wins_trivially():
    only = _measurement("SOLO", 0, profit=-0.5, win_rate=0.1, drawdown=99.0)
    winner = rank_training_candidates([only])
    assert winner.candidate.candidate_id == "SOLO"
