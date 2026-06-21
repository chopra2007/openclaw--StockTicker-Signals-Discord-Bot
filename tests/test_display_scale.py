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
