"""Unit tests for the TODO #93 frozen features, clocks, joins, folds and costs.

Everything is built from small synthetic records, so these tests never touch
the paid data files.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import auction_pressure_build_dev as B  # noqa: E402
import auction_pressure_walkforward as W  # noqa: E402
from auction_pressure_common import (  # noqa: E402
    BASE_COST,
    MIN_ENTRY_A,
    MIN_ENTRY_B,
    MIN_EXIT30_A,
    MIN_EXIT30_B,
    MIN_EXIT_A,
    MIN_EXIT_B,
    MIN_FIRST_FIVE,
    MIN_OPEN,
    MIN_PRIOR_CLOSE,
    SNAPSHOT_ORDER,
    canonical,
)

SYMS = ["ZZA", "ZZB", "ZZC", "ZZD", "ZZE", "ZZF", "ZZG", "ZZH", "ZZI", "ZZJ",
        "ZZK", "ZZL"]
N_DATES = 130
TARGET_POS = 100


@pytest.fixture(scope="module", autouse=True)
def _prior_dir(tmp_path_factory):
    """`build_panel` reads two machine-only research files for the list of
    degraded auction dates and halted date/instrument pairs. Those files are
    git-ignored, so they are absent on GitHub CI. For this synthetic 2019 panel
    both lists are empty anyway, so point PRIOR_DIR at a temp directory holding
    minimal stand-ins with the same shape."""
    d = tmp_path_factory.mktemp("prior")
    (d / "phase1-gate.json").write_text(
        '{"degraded_dates_xnys": [], "degraded_dates_equs": []}')
    (d / "phase1b-raw-analysis.json").write_text(
        '{"imbalance": {"halted_pairs": []}}')
    prev = B.PRIOR_DIR
    B.PRIOR_DIR = d
    yield
    B.PRIOR_DIR = prev


# ---------------------------------------------------------------- clocks ----
def test_snapshot_cutoff_keeps_the_latest_message_at_or_before_each_cutoff():
    slots = [None] * 5
    stream = [
        (1, 9 * 3600 + 14 * 60 + 59, "before_0915"),
        (2, 9 * 3600 + 15 * 60, "at_0915"),
        (3, 9 * 3600 + 15 * 60 + 1, "after_0915"),
        (4, 9 * 3600 + 29 * 60 + 29, "before_092930"),
        (5, 9 * 3600 + 29 * 60 + 31, "after_092930"),
        (6, 9 * 3600 + 30 * 60, "at_0930"),
    ]
    for ts, sec, tag in stream:
        B.update_snapshots(slots, ts, sec, (ts, tag))
    got = [s[1] for s in slots]
    assert got == ["at_0915", "after_0915", "after_0915", "before_092930", "at_0930"]


def test_a_message_after_0930_is_never_used():
    slots = [None] * 5
    B.update_snapshots(slots, 1, 9 * 3600 + 30 * 60, (1, "at_0930"))
    B.update_snapshots(slots, 2, 9 * 3600 + 30 * 60 + 1, (2, "after_0930"))
    assert slots[-1][1] == "at_0930"


def test_frozen_bar_minutes_match_the_pacific_clock_in_the_plan():
    # bars are stamped at the start of the minute, so the bar ENDING at 6:40
    # a.m. Pacific (9:40 Eastern) is the record stamped 9:39.
    assert MIN_OPEN == 9 * 60 + 30
    assert MIN_FIRST_FIVE == 9 * 60 + 34
    assert MIN_ENTRY_B == 9 * 60 + 35 and MIN_EXIT_B == MIN_ENTRY_B + 60
    assert MIN_ENTRY_A == 9 * 60 + 39 and MIN_EXIT_A == MIN_ENTRY_A + 60
    assert MIN_EXIT30_A == MIN_ENTRY_A + 30 and MIN_EXIT30_B == MIN_ENTRY_B + 30
    assert MIN_PRIOR_CLOSE == 15 * 60 + 59
    assert MIN_ENTRY_B > MIN_OPEN and MIN_ENTRY_A > MIN_FIRST_FIVE


def test_lane_b_entry_is_before_lane_a_entry_but_after_the_open():
    assert MIN_OPEN < MIN_ENTRY_B < MIN_ENTRY_A


def test_canonical_symbol_joins_the_two_venues():
    assert canonical("BRK B") == canonical("BRK.B") == "BRK.B"


# ----------------------------------------------------------------- folds ----
@pytest.mark.parametrize("i,expected", [
    (0, 0), (249, 0), (250, 1), (369, 1), (370, 2), (489, 2),
    (490, 3), (609, 3), (610, 4), (729, 4),
])
def test_fold_boundaries(i, expected):
    assert B.fold_of_index(i) == expected


# -------------------------------------------------------- synthetic panel ----
def _dates():
    return [d.strftime("%Y-%m-%d")
            for d in pd.bdate_range("2019-01-02", periods=N_DATES)]


def _make_inputs():
    dates = _dates()
    target = dates[TARGET_POS]
    imb_rows, bar_rows = [], []
    for si, sym in enumerate(SYMS):
        inst = 900000 + si
        for di, date in enumerate(dates):
            wiggle = ((di * 7 + si * 3) % 11 - 5) / 100.0  # deterministic, small
            if sym == "ZZA" and date == target:
                vals = [0.5, 0.6, 0.7, 0.8, 0.4]
            else:
                vals = [0.1 + wiggle] * 5
            row = {"date": date, "symbol": sym, "xnys_inst": inst,
                   "closing_pressure": 0.2 + wiggle, "ts_close_auction": 1}
            for name, v in zip(SNAPSHOT_ORDER, vals):
                row[f"ts_{name}"] = 1
                row[f"p_{name}"] = v
                row[f"pq_{name}"] = 10_000.0
            imb_rows.append(row)

            base = 100.0 + si
            if sym == "ZZA" and date == target:
                px = {MIN_PRIOR_CLOSE: 100.0, MIN_OPEN: 101.0, MIN_FIRST_FIVE: 102.01,
                      MIN_ENTRY_B: 102.0, MIN_EXIT30_B: 102.5, MIN_EXIT_B: 103.02,
                      MIN_ENTRY_A: 103.0, MIN_EXIT30_A: 103.5, MIN_EXIT_A: 104.03}
            else:
                px = {m: base * (1 + wiggle / 10 + m / 100000.0)
                      for m in [MIN_PRIOR_CLOSE, MIN_OPEN, MIN_FIRST_FIVE, MIN_ENTRY_B,
                                MIN_EXIT30_B, MIN_EXIT_B, MIN_ENTRY_A, MIN_EXIT30_A,
                                MIN_EXIT_A]}
            for m, price in px.items():
                bar_rows.append({"date": date, "symbol": sym, "minute": m,
                                 "open": price, "high": price * 1.001,
                                 "low": price * 0.999, "close": price,
                                 "volume": 5000})
    # the prior session's 4:00 p.m. Eastern close is what `prior_close` must read
    prior = dates[TARGET_POS - 1]
    for row in bar_rows:
        if row["symbol"] == "ZZA" and row["date"] == prior and row["minute"] == MIN_PRIOR_CLOSE:
            row.update({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})

    imb = pd.DataFrame(imb_rows)
    for c in B.TS_COLS:
        imb[c] = imb[c].astype("Int64")
    bars = pd.DataFrame(bar_rows)
    bars["symbol"] = pd.Categorical(bars["symbol"])
    meta = {"m_trading_dates": dates}
    return imb, bars, meta, target


@pytest.fixture(scope="module")
def panel():
    imb, bars, meta, target = _make_inputs()
    df, info = B.build_panel(imb, bars, meta, which="dev")
    return df, info, target


def _target_row(panel):
    df, _, target = panel
    row = df[(df["symbol"] == "ZZA") & (df["date"] == target)]
    assert len(row) == 1
    return row.iloc[0]


def test_persistence_and_persistent(panel):
    r = _target_row(panel)
    assert r["persistence"] == 1.0
    assert bool(r["persistent"]) is True
    assert r["flip_count"] == 0


def test_growth_is_last_snapshot_minus_first(panel):
    r = _target_row(panel)
    assert r["growth"] == pytest.approx(0.4 - 0.5)


def test_cancellation_and_earlier_pressure_sign(panel):
    r = _target_row(panel)
    assert r["max_pre_pressure"] == pytest.approx(0.8)
    assert r["earlier_pressure_sign"] == 1.0
    assert r["cancellation"] == pytest.approx((0.8 - 0.4) / 0.8)
    assert bool(r["late_flip"]) is False


def test_opening_gap_and_first_five_return(panel):
    r = _target_row(panel)
    assert r["prior_close"] == pytest.approx(100.0)
    assert r["opening_price"] == pytest.approx(101.0)
    assert r["opening_gap"] == pytest.approx(0.01)
    assert r["first_five_return"] == pytest.approx((102.01 - 101.0) / 101.0)


def test_lane_entry_and_exit_prices_come_from_the_frozen_bars(panel):
    r = _target_row(panel)
    assert r["entry_a"] == pytest.approx(103.0)
    assert r["exit_a"] == pytest.approx(104.03)
    assert r["ret_a"] == pytest.approx((104.03 - 103.0) / 103.0)
    assert r["entry_b"] == pytest.approx(102.0)
    assert r["exit_b"] == pytest.approx(103.02)
    assert r["ret_b"] == pytest.approx((103.02 - 102.0) / 102.0)


def test_paired_size_is_relative_to_the_trailing_median(panel):
    r = _target_row(panel)
    assert r["paired_size"] == pytest.approx(1.0)


def test_prior_session_join_uses_the_previous_trading_date(panel):
    df, _, target = panel
    dates = sorted(df["date"].unique())
    i = dates.index(target)
    prev = dates[i - 1]
    r = _target_row(panel)
    prev_row = df[(df["symbol"] == "ZZA") & (df["date"] == prev)].iloc[0]
    assert r["prior_session_date"] == prev
    assert r["prior_closing_pressure"] == pytest.approx(prev_row["closing_pressure"])


def test_first_date_has_no_prior_session(panel):
    df, _, _ = panel
    first = sorted(df["date"].unique())[0]
    row = df[(df["symbol"] == "ZZA") & (df["date"] == first)].iloc[0]
    assert row["prior_session_date"] is None or pd.isna(row["prior_session_date"])
    assert pd.isna(row["prior_closing_pressure"])


def test_no_evaluation_date_enters_the_development_panel(panel):
    df, info, _ = panel
    assert info["development_dates"] == int(round(N_DATES * 0.8))
    assert df["date"].max() <= info["split_date"]


def test_calendar_group_is_mechanical(panel):
    df, _, _ = panel
    groups = set(df["calendar_group"])
    assert groups <= {"ordinary", "month_end", "quarter_end"}
    # the last trading date of each month must be flagged
    last = df.groupby(df["date"].str.slice(0, 7))["date"].max()
    flagged = set(df[df["calendar_group"] != "ordinary"]["date"])
    assert set(last) - {df["date"].max()} <= flagged | {df["date"].max()}


def test_low_volume_entry_minute_is_excluded():
    imb, bars, meta, target = _make_inputs()
    bars.loc[(bars["symbol"] == "ZZA") & (bars["date"] == target)
             & (bars["minute"] == MIN_ENTRY_A), "volume"] = 500
    df, _ = B.build_panel(imb, bars, meta, which="dev")
    row = df[(df["symbol"] == "ZZA") & (df["date"] == target)].iloc[0]
    assert row["lane_a_exclusion"] == "entry_volume_not_fillable"
    assert not row["lane_a_eligible"]


def test_missing_snapshot_excludes_lane_a_but_not_lane_b():
    imb, bars, meta, target = _make_inputs()
    m = (imb["symbol"] == "ZZA") & (imb["date"] == target)
    imb.loc[m, "p_0920"] = np.nan
    df, _ = B.build_panel(imb, bars, meta, which="dev")
    row = df[(df["symbol"] == "ZZA") & (df["date"] == target)].iloc[0]
    assert row["lane_a_exclusion"] == "missing_opening_snapshot"
    assert row["lane_b_exclusion"] == ""


# ----------------------------------------------- costs and duplicate merge ----
def _candidate_frame(rule_flags, directions, adj=0.0040):
    n = len(rule_flags)
    row = {
        "date": ["2024-05-01"] * n, "symbol": ["AAA"] * n,
        "signed_pressure": [1.0] * n, "prior_closing_pressure": [1.0] * n,
        "earlier_pressure_sign": [1.0] * n, "opening_gap": [0.01] * n,
        "first_five_return": [0.01] * n, "persistence": [1.0] * n,
        "cancellation": [0.0] * n, "paired_size": [1.0] * n, "flip_count": [0.0] * n,
        "growth": [0.0] * n, "late_flip": [False] * n, "calendar_group": ["ordinary"] * n,
        "adj_a": [adj] * n, "adj_b": [adj] * n, "adj30_a": [adj] * n, "adj30_b": [adj] * n,
        "up_a": [0.01] * n, "dn_a": [-0.01] * n, "up_b": [0.01] * n, "dn_b": [-0.01] * n,
        "n_rules": [sum(f.values()) for f in rule_flags],
    }
    df = pd.DataFrame(row)
    for rid in W.RULE_IDS:
        df[f"rule_{rid}"] = [f.get(rid, False) for f in rule_flags]
        df[f"dir_{rid}"] = [
            (directions[i].get(rid) if f.get(rid) else np.nan)
            for i, f in enumerate(rule_flags)
        ]
    return df


def test_cost_is_subtracted_from_the_direction_signed_market_adjusted_return():
    df = _candidate_frame([{"A3": True}], [{"A3": 1.0}], adj=0.0040)
    cand, dropped = W.merge_candidates(df)
    assert dropped == 0
    r = cand.iloc[0]
    assert r["gross"] == pytest.approx(0.0040)
    assert r["net"] == pytest.approx(0.0040 - BASE_COST)
    assert r["net_25bps"] == pytest.approx(0.0040 - 0.0025)
    assert r["net_10bps"] == pytest.approx(0.0040 - 0.0010)
    assert bool(r["win"]) is (0.0040 - BASE_COST > 0)


def test_a_short_candidate_wins_when_the_market_adjusted_return_is_negative():
    df = _candidate_frame([{"A1": True}], [{"A1": -1.0}], adj=-0.0040)
    cand, _ = W.merge_candidates(df)
    r = cand.iloc[0]
    assert r["direction"] == -1.0
    assert r["gross"] == pytest.approx(0.0040)
    assert bool(r["win"]) is True


def test_two_rules_agreeing_merge_into_one_candidate_keeping_both_ids():
    df = _candidate_frame([{"B1": True, "B3": False, "A3": True}],
                          [{"B1": 1.0, "A3": 1.0}])
    cand, dropped = W.merge_candidates(df)
    assert dropped == 0
    assert len(cand) == 1
    assert cand.iloc[0]["rule_ids"] == "A3,B1"
    # a lane A rule fired, so the later lane A clock is used
    assert cand.iloc[0]["lane"] == "a"


def test_two_rules_disagreeing_on_direction_are_dropped():
    df = _candidate_frame([{"A1": True, "A3": True}], [{"A1": -1.0, "A3": 1.0}])
    cand, dropped = W.merge_candidates(df)
    assert dropped == 1
    assert len(cand) == 0


def test_lane_b_candidates_never_carry_first_five_minute_data():
    df = _candidate_frame([{"B1": True}], [{"B1": 1.0}])
    cand, _ = W.merge_candidates(df)
    assert cand.iloc[0]["lane"] == "b"
    assert pd.isna(cand.iloc[0]["dir_first_five_return"])
