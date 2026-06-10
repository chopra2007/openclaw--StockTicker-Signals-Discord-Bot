"""Tests for I14-widening: graduated panic STRONG-cutoff widening."""
import pytest
from unittest.mock import patch
from consensus_engine.analysis.regime import _apply_graduated_widening


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_on(**overrides):
    """Return a cfg.get side_effect that enables the flag and applies overrides."""
    defaults = {
        "features.regime_widening_graduated.enabled": True,
        "features.regime_widening_graduated.max_shift": 15,
        "features.regime_widening_graduated.cutoff_ceiling": 90,
        "features.regime_widening_graduated.slope": 2.5,
        "features.regime_classifier.panic_z": 1.5,
        "features.regime_classifier.regime_shifts": {"calm": -5, "elevated": 5, "panic": 10},
        "precision_engine.thresholds.high_confidence": 80,
    }
    defaults.update(overrides)

    def _get(key, default=None):
        return defaults.get(key, default)

    return _get


def _cfg_off():
    """Return a cfg.get side_effect with flag disabled."""
    return _cfg_on(**{"features.regime_widening_graduated.enabled": False})


# ---------------------------------------------------------------------------
# Flag-ON tests
# ---------------------------------------------------------------------------

class TestFlagOn:
    def test_z_at_panic_z_returns_base_panic_shift(self):
        """z_smooth == panic_z (1.5) -> shift == base panic shift (10), no extra."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_on()):
            # slope * 0 = 0, so result is base_panic_shift
            result = _apply_graduated_widening("panic", 1.5, 10)
        assert result == 10

    def test_z_well_above_panic_z_clamps_at_max_shift(self):
        """z_smooth very high -> shift clamps at max_shift (15) when ceiling allows it.

        Use base_high=60 so ceiling_cap = 90-60 = 30, which does not bind before max_shift=15.
        raw = 10 + 2.5*(10-1.5) = 31.25 -> cap1: min(31.25, 15) = 15 -> cap2: min(15, 30) = 15.
        """
        cfg_override = _cfg_on(**{"precision_engine.thresholds.high_confidence": 60})
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=cfg_override):
            result = _apply_graduated_widening("panic", 10.0, 10)
        assert result == 15

    def test_shift_plus_base_high_clamps_at_cutoff_ceiling(self):
        """shift + base_high must not exceed cutoff_ceiling (90).

        ceiling_cap = 90 - 80 = 10.  Even if max_shift allows 15, ceiling wins.
        Set max_shift=15, base_high=80, cutoff_ceiling=90 -> ceiling_cap=10.
        At z=1.5 + slope=2.5 with a high z_smooth=5.0 -> raw would be >10, clamped to 10.
        """
        cfg_override = _cfg_on(
            **{
                "features.regime_widening_graduated.max_shift": 15,
                "features.regime_widening_graduated.cutoff_ceiling": 90,
                "precision_engine.thresholds.high_confidence": 80,
            }
        )
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=cfg_override):
            # raw = 10 + 2.5*(5.0-1.5) = 10 + 8.75 = 18.75
            # cap1: min(18.75, 15) = 15
            # cap2: min(15, 90-80=10) = 10
            result = _apply_graduated_widening("panic", 5.0, 10)
        assert result == 10

    def test_calm_label_unchanged(self):
        """calm label -> base_shift returned unchanged (no graduated logic)."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_on()):
            result = _apply_graduated_widening("calm", -1.5, -5)
        assert result == -5

    def test_elevated_label_unchanged(self):
        """elevated label -> base_shift returned unchanged."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_on()):
            result = _apply_graduated_widening("elevated", 0.8, 5)
        assert result == 5

    def test_panic_moderate_z_between_base_and_max(self):
        """Moderate panic z produces a graduated shift between base and max."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_on()):
            # z_smooth = 2.5, panic_z = 1.5
            # raw = 10 + 2.5*(2.5-1.5) = 10 + 2.5 = 12.5 -> int(12.5) = 12
            # cap1: min(12.5, 15) = 12.5
            # cap2: min(12.5, 90-80=10) = 10  -> ceiling_cap wins
            # ceiling_cap = 90 - 80 = 10
            result = _apply_graduated_widening("panic", 2.5, 10)
        # raw=12.5, cap1=12.5, cap2=ceiling(10) -> 10
        assert result == 10

    def test_panic_z_just_above_threshold_without_ceiling_binding(self):
        """With a lower high threshold, ceiling doesn't bind and graduated shift applies."""
        cfg_override = _cfg_on(
            **{
                "precision_engine.thresholds.high_confidence": 70,
                "features.regime_widening_graduated.cutoff_ceiling": 90,
                "features.regime_widening_graduated.max_shift": 15,
            }
        )
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=cfg_override):
            # z_smooth=2.5, panic_z=1.5 -> raw=10+2.5=12.5
            # cap1: min(12.5, 15) = 12.5
            # cap2: min(12.5, 90-70=20) = 12  (int truncation)
            result = _apply_graduated_widening("panic", 2.5, 10)
        assert result == 12


# ---------------------------------------------------------------------------
# Flag-OFF tests
# ---------------------------------------------------------------------------

class TestFlagOff:
    def test_panic_returns_static_map_value(self):
        """Flag OFF: panic label returns base_shift unchanged."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_off()):
            result = _apply_graduated_widening("panic", 10.0, 10)
        assert result == 10

    def test_calm_returns_static_map_value(self):
        """Flag OFF: calm label returns base_shift unchanged."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_off()):
            result = _apply_graduated_widening("calm", -2.0, -5)
        assert result == -5

    def test_elevated_returns_static_map_value(self):
        """Flag OFF: elevated label returns base_shift unchanged."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_off()):
            result = _apply_graduated_widening("elevated", 0.7, 5)
        assert result == 5

    def test_panic_z_above_threshold_flag_off_no_graduation(self):
        """Flag OFF: extreme z panic still returns flat base shift."""
        with patch("consensus_engine.analysis.regime.cfg.get", side_effect=_cfg_off()):
            result = _apply_graduated_widening("panic", 5.0, 10)
        assert result == 10
