"""Definition tests for the TODO #106 context layer.

Hand-built numbers only.  Checks that the frozen definitions in
`mechanical-definitions.md` are what the code actually computes.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/research"))

import pdtm_context as C  # noqa: E402
import pdtm_controls as CT  # noqa: E402


def test_bin_width_is_ten_basis_points_with_a_one_cent_floor():
    assert C.bin_width(np.array([1000.0]))[0] == pytest.approx(1.00)
    assert C.bin_width(np.array([100.0]))[0] == pytest.approx(0.10)
    # 25.00 x 10bps = 0.025, which numpy rounds to even -> 0.02
    assert C.bin_width(np.array([25.0]))[0] == pytest.approx(0.02)
    assert C.bin_width(np.array([5.0]))[0] == pytest.approx(0.01)   # floor


def test_volume_is_spread_evenly_across_every_bin_the_bar_touches():
    prof = C._profile_one(np.array([100.00]), np.array([100.10]),
                          np.array([1100.0]), 100.00, 0.01, 11)
    assert prof.sum() == pytest.approx(1100.0)
    assert np.allclose(prof, 100.0)          # 11 bins, 100 shares each


def test_a_single_price_bar_lands_in_exactly_one_bin():
    prof = C._profile_one(np.array([100.05]), np.array([100.05]),
                          np.array([500.0]), 100.00, 0.01, 11)
    assert prof.sum() == pytest.approx(500.0)
    assert prof[5] == pytest.approx(500.0)


def test_a_bar_with_no_volume_contributes_nothing():
    prof = C._profile_one(np.array([100.0]), np.array([100.1]),
                          np.array([0.0]), 100.0, 0.01, 11)
    assert prof.sum() == 0.0


def test_the_busiest_price_is_the_busiest_bin():
    prof = np.array([10.0, 10.0, 90.0, 10.0, 10.0])
    poc, vah, val = C.value_area(prof, 100.0, 0.01)
    assert poc == pytest.approx(100.025)     # centre of bin 2


def test_the_value_area_holds_at_least_seventy_percent_of_the_session():
    prof = np.array([5.0, 20.0, 50.0, 20.0, 5.0])   # total 100
    poc, vah, val = C.value_area(prof, 100.0, 0.10)
    lo = int(round((val - 100.0) / 0.10))
    hi = int(round((vah - 100.0) / 0.10)) - 1
    assert prof[lo:hi + 1].sum() >= 70.0


def test_an_empty_profile_returns_nothing_rather_than_guessing():
    poc, vah, val = C.value_area(np.zeros(5), 100.0, 0.01)
    assert np.isnan(poc) and np.isnan(vah) and np.isnan(val)


def test_the_placebo_mirror_keeps_the_same_risk_and_reward_distances():
    s = pd.DataFrame([dict(row=0, symbol="X", date="d", sector="S", method="M",
                           side=1, confirm_min=20, stop=99.0, target=101.5,
                           risk_frac=0.01)])
    f = CT.flip_sides(s)
    assert f.side.iloc[0] == -1
    assert f.stop.iloc[0] == pytest.approx(101.0)     # ref 100 + 1.0
    assert f.target.iloc[0] == pytest.approx(98.5)    # ref 100 - 1.5


def test_a_coin_flip_placebo_reports_where_the_real_rule_sits():
    real = np.full(200, 0.01)
    flipped = np.full(200, -0.01)
    out = CT.placebo_distribution(real, flipped)
    assert out["real_mean"] == pytest.approx(0.01)
    assert out["share_of_coin_flips_beating_the_rule"] == 0.0
    assert -0.005 < out["placebo_mean"] < 0.005
