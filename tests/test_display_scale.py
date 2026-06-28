"""Unit tests for the unified display-scale helper (#46).

Every intensity/strength reading the user sees should read on one 0-100 scale
where higher = more of the named quantity. This helper is the single place that
maps the two genuinely-confusing native readings (regime z-score, contradiction
index) onto that scale. Pure functions, no side effects.
"""
import pytest

from consensus_engine.alerts.display_scale import (
    regime_stress,
    regime_emoji,
    disagreement,
    call_put_split,
)


# --- regime_stress: z-score -> 0-100 market stress -------------------------

def test_regime_stress_anchors():
    # calm cutoff, elevated cutoff, panic cutoff (user's hard anchor: panic 1.5 -> 85)
    assert regime_stress(-1.0) == 20
    assert regime_stress(0.5) == 50
    assert regime_stress(1.5) == 85


def test_regime_stress_normal_is_low():
    # A normal market (z~0) must NOT read as high stress.
    assert regime_stress(0.0) == 40


def test_regime_stress_clamped_both_ends():
    assert regime_stress(2.5) == 100
    assert regime_stress(5.0) == 100
    assert regime_stress(-3.0) == 0
    assert regime_stress(-10.0) == 0


def test_regime_stress_monotonic_increasing():
    prev = -1
    z = -3.0
    while z <= 3.0:
        cur = regime_stress(z)
        assert cur >= prev, f"non-monotonic at z={z}: {cur} < {prev}"
        prev = cur
        z += 0.1


# --- regime_emoji: driven by LABEL, never the magnitude --------------------

def test_regime_emoji_by_label():
    assert regime_emoji("calm") == "🟢"
    assert regime_emoji("normal") == "🟢"
    assert regime_emoji("elevated") == "🟡"
    assert regime_emoji("panic") == "🔴"


def test_regime_emoji_unknown_label_neutral():
    assert regime_emoji("whatever") == "⚪"
    assert regime_emoji("") == "⚪"


# --- disagreement: 0.0-1.0 contradiction index -> 0-100 --------------------

def test_disagreement_maps_proportionally():
    assert disagreement(0.0) == 0
    assert disagreement(0.45) == 45
    assert disagreement(0.5) == 50
    assert disagreement(1.0) == 100


def test_disagreement_clamped():
    assert disagreement(1.3) == 100
    assert disagreement(-0.2) == 0


# --- call_put_split: two raw counts -> 0-100 call/put % split (#53) ---------

def test_call_put_split_basic():
    # 27156 calls / 15322 puts -> 63.9% -> 64% / 36% (the GOOGL demo case).
    assert call_put_split(27156.0, 15322.0) == ("64", "36")


def test_call_put_split_even_shows_one_decimal():
    # A genuinely near-even split must not round into a fake exact 50/50.
    assert call_put_split(496.0, 504.0) == ("49.6", "50.4")


def test_call_put_split_exact_fifty_stays_whole():
    # A true 50/50 stays whole (no spurious decimal).
    assert call_put_split(100.0, 100.0) == ("50", "50")


def test_call_put_split_single_sided_calls():
    # All calls, no puts -> 100/0 (only correct because we pass counts, not a ratio).
    assert call_put_split(500.0, 0.0) == ("100", "0")


def test_call_put_split_single_sided_puts():
    assert call_put_split(0.0, 800.0) == ("0", "100")


def test_call_put_split_no_volume_returns_none():
    assert call_put_split(0.0, 0.0) is None


def test_call_put_split_nan_returns_none():
    nan = float("nan")
    assert call_put_split(nan, 100.0) is None
    assert call_put_split(nan, nan) is None
