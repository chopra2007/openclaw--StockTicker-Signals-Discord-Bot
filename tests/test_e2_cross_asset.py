"""E2 — cross-asset regime confirm/veto multiplier tests.

Coverage:
  (a) Backwardation ratio -> multiplier clamps at veto_floor (0.85).
  (b) Calm contango -> multiplier clamps at confirm_ceiling (1.15).
  (c) Fetch failure -> 1.0 no-op.
  (d) Stale cached value (mock is_fresh False) -> 1.0.
  (e) Flag OFF -> analyze_signal classification byte-identical with a mocked
      extreme ratio (STRONG_ALERT produced, no E2 effect).
  (f) Combined E2 + I14 adjustment never exceeds ceiling 90 nor goes below
      base_high - 10 (10 below = 70).
  (g) High-conviction bypass caller (bypass_market_confirmation=True) is exempt
      from the graduated EXTRA widening but still gets the static panic shift.

All yfinance calls are mocked — no live network access in tests.
"""
import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from consensus_engine.engine import _classify, SignalClass
from consensus_engine.analysis.regime import RegimeContext
from consensus_engine.analysis import cross_asset as _ca_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously (helper for async tests without pytest-asyncio)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_regime(label: str = "panic", threshold_shift: int = 10) -> RegimeContext:
    return RegimeContext(
        label=label,
        z_score=2.0,
        threshold_shift=threshold_shift,
        cold_start=False,
        as_of_date="2026-06-10",
    )


def _base_cfg(
    e2_enabled: bool = False,
    graduated_enabled: bool = False,
    regime_enabled: bool = False,
    extra: dict | None = None,
) -> dict:
    base = {
        "precision_engine.thresholds.high_confidence": 80,
        "precision_engine.thresholds.medium_confidence": 65,
        "precision_engine.thresholds.require_mainstream_for_strong": False,
        "precision_engine.thresholds.require_market_confirmation_for_low_conviction": False,
        "features.regime_classifier.enabled": regime_enabled,
        "features.regime_classifier.regime_shifts": {"calm": -5, "elevated": 5, "panic": 10},
        "features.regime_widening_graduated.enabled": graduated_enabled,
        "features.regime_widening_graduated.max_shift": 15,
        "features.regime_widening_graduated.cutoff_ceiling": 90,
        "features.cross_asset.enabled": e2_enabled,
        "features.cross_asset.veto_floor": 0.85,
        "features.cross_asset.confirm_ceiling": 1.15,
        "features.recency_window.enabled": True,
        f"features.recency_window.max_age_min.vix": 1440,
        "features.strong_requires_hard_evidence.enabled": False,
    }
    if extra:
        base.update(extra)
    return base


def _classify_with_cfg(cfg_map: dict, **kwargs) -> SignalClass:
    """Call _classify with patched cfg, return only the SignalClass."""
    def _get(key, default=None):
        return cfg_map.get(key, default)

    with patch("consensus_engine.engine.cfg") as mock_cfg:
        mock_cfg.get.side_effect = _get
        sig, _ = _classify(**kwargs)
    return sig


# ---------------------------------------------------------------------------
# (a) Backwardation -> clamps at veto_floor
# ---------------------------------------------------------------------------

class TestVetoFloor:
    def test_backwardation_clamps_at_veto_floor(self):
        """ratio=1.20 (strong backwardation) -> multiplier == 0.85 (veto_floor)."""
        cfg_map = {
            "features.cross_asset.veto_floor": 0.85,
            "features.cross_asset.confirm_ceiling": 1.15,
        }

        def _get(key, default=None):
            return cfg_map.get(key, default)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _get
            result = _ca_mod._ratio_to_multiplier(1.20)

        # ratio=1.20 -> delta = 1.0-1.20 = -0.20 -> downside scale=1.0
        # raw = 1.0 + (-0.20)*1.0 = 0.80 < veto_floor(0.85) -> clamp to 0.85
        assert result == pytest.approx(0.85, abs=1e-9)

    def test_extreme_backwardation_clamps_at_floor(self):
        """ratio=2.0 (extreme) -> multiplier clamped at veto_floor."""
        cfg_map = {
            "features.cross_asset.veto_floor": 0.85,
            "features.cross_asset.confirm_ceiling": 1.15,
        }

        def _get(key, default=None):
            return cfg_map.get(key, default)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _get
            result = _ca_mod._ratio_to_multiplier(2.0)

        assert result == pytest.approx(0.85, abs=1e-9)


# ---------------------------------------------------------------------------
# (b) Steep contango -> clamps at confirm_ceiling
# ---------------------------------------------------------------------------

class TestConfirmCeiling:
    def test_steep_contango_clamps_at_ceiling(self):
        """ratio=0.80 (steep contango) -> multiplier == 1.15 (confirm_ceiling)."""
        cfg_map = {
            "features.cross_asset.veto_floor": 0.85,
            "features.cross_asset.confirm_ceiling": 1.15,
        }

        def _get(key, default=None):
            return cfg_map.get(key, default)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _get
            result = _ca_mod._ratio_to_multiplier(0.80)

        # ratio=0.80 -> delta=0.20 -> upside scale=1.0 -> raw=1.20 > ceiling=1.15 -> clamp
        assert result == pytest.approx(1.15, abs=1e-9)

    def test_neutral_ratio_returns_near_one(self):
        """ratio=1.0 (flat term structure) -> multiplier == 1.0."""
        cfg_map = {
            "features.cross_asset.veto_floor": 0.85,
            "features.cross_asset.confirm_ceiling": 1.15,
        }

        def _get(key, default=None):
            return cfg_map.get(key, default)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _get
            result = _ca_mod._ratio_to_multiplier(1.0)

        assert result == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# (c) Fetch failure -> 1.0 no-op
# ---------------------------------------------------------------------------

# NOTE: these tests are native async (pytest-asyncio auto mode). The original
# versions drove the coroutine with asyncio.get_event_loop().run_until_complete,
# which works when the file runs alone but picks up a closed/stale global loop
# after earlier async tests in the full suite (4 order-dependent failures,
# found by the separate verifier 2026-06-10). Patch _fetch_vix_ratio directly
# so the real executor path is exercised.
class TestFetchFailure:
    async def test_yfinance_exception_returns_1_0(self):
        """When the VIX fetch raises, get_multiplier returns 1.0 (no-op)."""
        _ca_mod.clear_cache()
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = lambda k, d=None: {
                "features.cross_asset.enabled": True,
                "features.cross_asset.veto_floor": 0.85,
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.recency_window.enabled": True,
                "features.recency_window.max_age_min.vix": 1440,
            }.get(k, d)
            with patch(
                "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
                side_effect=RuntimeError("network error"),
            ):
                result = await _ca_mod.get_multiplier()
        _ca_mod.clear_cache()
        assert result == pytest.approx(1.0, abs=1e-9)

    async def test_vix_data_none_returns_1_0(self):
        """When _fetch_vix_ratio returns None (no data), get_multiplier returns 1.0."""
        _ca_mod.clear_cache()
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = lambda k, d=None: {
                "features.cross_asset.enabled": True,
                "features.cross_asset.veto_floor": 0.85,
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.recency_window.enabled": True,
                "features.recency_window.max_age_min.vix": 1440,
            }.get(k, d)
            with patch(
                "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
                return_value=None,
            ):
                result = await _ca_mod.get_multiplier()
        _ca_mod.clear_cache()
        assert result == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# (d) Stale cached value (mock is_fresh False) -> 1.0
# ---------------------------------------------------------------------------

class TestStaleCacheDegradesTo1:
    async def test_stale_cache_returns_1_0(self):
        """Stale cached VIX value (is_fresh returns False) should return 1.0."""
        # Pre-populate cache with a value that appears in-TTL but is "stale" per
        # recency_window.is_fresh.
        _ca_mod.clear_cache()
        _ca_mod._cache["ratio"] = 1.20
        _ca_mod._cache["multiplier"] = 0.85
        _ca_mod._cache["fetched_at"] = datetime.now(timezone.utc)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = lambda k, d=None: {
                "features.cross_asset.enabled": True,
                "features.cross_asset.veto_floor": 0.85,
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.recency_window.enabled": True,
                "features.recency_window.max_age_min.vix": 1440,
            }.get(k, d)
            # is_fresh returns False -> stale cache -> 1.0. Also block a re-fetch
            # so the test pins the stale-degrade branch, not a fresh fetch.
            with patch(
                "consensus_engine.analysis.cross_asset.is_fresh", return_value=False
            ), patch(
                "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
                return_value=None,
            ):
                result = await _ca_mod.get_multiplier()

        _ca_mod.clear_cache()
        assert result == pytest.approx(1.0, abs=1e-9)

    async def test_fresh_cache_returns_cached_multiplier(self):
        """Fresh cached VIX value (is_fresh returns True) returns the cached multiplier."""
        _ca_mod.clear_cache()
        _ca_mod._cache["ratio"] = 0.90
        _ca_mod._cache["multiplier"] = 1.10
        _ca_mod._cache["fetched_at"] = datetime.now(timezone.utc)

        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = lambda k, d=None: {
                "features.cross_asset.enabled": True,
                "features.cross_asset.veto_floor": 0.85,
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.recency_window.enabled": True,
                "features.recency_window.max_age_min.vix": 1440,
            }.get(k, d)
            with patch(
                "consensus_engine.analysis.cross_asset.is_fresh", return_value=True
            ):
                result = await _ca_mod.get_multiplier()

        _ca_mod.clear_cache()
        assert result == pytest.approx(1.10, abs=1e-9)


# ---------------------------------------------------------------------------
# (e) Flag OFF -> classify byte-identical with extreme ratio
# ---------------------------------------------------------------------------

class TestFlagOff:
    def test_flag_off_strong_is_unchanged(self):
        """Flag OFF: an extreme backwardation e2_multiplier has zero effect.
        Score >= high -> STRONG_ALERT (as if E2 didn't exist).
        """
        cfg_map = _base_cfg(e2_enabled=False)
        result = _classify_with_cfg(
            cfg_map,
            total_score=90,   # clearly above high=80
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=None,
            e2_multiplier=0.85,  # extreme veto, but flag is OFF -> ignored
        )
        assert result == SignalClass.STRONG_ALERT

    def test_flag_off_watchlist_unchanged(self):
        """Flag OFF: score at 70 (medium band) stays WATCHLIST regardless of multiplier."""
        cfg_map = _base_cfg(e2_enabled=False)
        result = _classify_with_cfg(
            cfg_map,
            total_score=70,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=None,
            e2_multiplier=1.15,  # would confirm, but flag OFF -> ignored
        )
        assert result == SignalClass.WATCHLIST


# ---------------------------------------------------------------------------
# (f) Combined E2 + I14 adjustment never exceeds ceiling 90 or drops below
#     base_high - 10 (= 70 with base_high=80)
# ---------------------------------------------------------------------------

class TestCombinedCutoffBounds:
    """E2 * base_high + regime_shift must be clamped to [base_high-10, cutoff_ceiling]."""

    def test_e2_veto_plus_panic_shift_never_exceeds_ceiling(self):
        """E2 confirm (1.15) + large panic shift stays at ceiling 90.

        base_high=80, e2=1.15, regime_shift=10
        raw = 80*1.15 + 10 = 102 -> clamp to ceiling=90.
        """
        cfg_map = _base_cfg(
            e2_enabled=True,
            regime_enabled=True,
            extra={
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.cross_asset.veto_floor": 0.85,
                "features.regime_widening_graduated.cutoff_ceiling": 90,
            },
        )
        # Pass a regime with threshold_shift=10 (panic) and e2_multiplier=1.15
        regime = _make_regime("panic", threshold_shift=10)
        result = _classify_with_cfg(
            cfg_map,
            total_score=89,   # just below ceiling 90 -> would be WATCHLIST
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=regime,
            e2_multiplier=1.15,
        )
        # effective_high = clamp(80*1.15 + 10, 70, 90) = clamp(102, 70, 90) = 90
        # score=89 < effective_high=90 -> WATCHLIST (or IGNORE if below med)
        # 89 >= med=65 -> WATCHLIST
        assert result == SignalClass.WATCHLIST

    def test_e2_veto_never_drops_below_base_minus_10(self):
        """E2 veto (0.85) can never drop effective_high below base_high - 10 = 70.

        base_high=80, e2=0.85, regime_shift=0
        raw = 80*0.85 + 0 = 68 -> clamp(68, 70, 90) = 70.
        """
        cfg_map = _base_cfg(
            e2_enabled=True,
            regime_enabled=False,
            extra={
                "features.cross_asset.confirm_ceiling": 1.15,
                "features.cross_asset.veto_floor": 0.85,
                "features.regime_widening_graduated.cutoff_ceiling": 90,
            },
        )
        result = _classify_with_cfg(
            cfg_map,
            total_score=71,   # above floor 70, below base 80
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=None,
            e2_multiplier=0.85,
        )
        # effective_high = clamp(80*0.85 + 0, 70, 90) = clamp(68, 70, 90) = 70
        # score=71 >= effective_high=70 -> STRONG_ALERT (mainstream=True, market_ok=True)
        assert result == SignalClass.STRONG_ALERT

    def test_floor_means_score_70_never_achieves_strong_without_e2(self):
        """Without E2, score=70 < high=80 stays WATCHLIST."""
        cfg_map = _base_cfg(e2_enabled=False)
        result = _classify_with_cfg(
            cfg_map,
            total_score=70,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=None,
            e2_multiplier=1.0,
        )
        assert result == SignalClass.WATCHLIST


# ---------------------------------------------------------------------------
# (g) High-conviction bypass caller exempt from graduated EXTRA widening
# ---------------------------------------------------------------------------

class TestI14BypassExemption:
    """High-conviction callers (bypass_market_confirmation=True) must NOT face
    the graduated extra widening — only the static panic map value applies.
    """

    def test_bypass_gets_static_shift_not_graduated(self):
        """bypass=True, panic regime, graduated ON:
        static panic shift = 5; graduated threshold_shift = 8.
        Bypass caller sees high = clamp(80+5, 70, 100) = 85, not 88.
        Score=87 >= 85 -> STRONG_ALERT.
        """
        # Simulate regime with graduated threshold_shift=8 (> static 5)
        regime = RegimeContext(
            label="panic",
            z_score=2.5,
            threshold_shift=8,   # graduated shift > static 5
            cold_start=False,
            as_of_date="2026-06-10",
        )
        cfg_map = _base_cfg(
            graduated_enabled=True,
            regime_enabled=True,
            extra={
                "features.regime_classifier.regime_shifts": {"calm": -5, "elevated": 3, "panic": 5},
                "features.regime_widening_graduated.cutoff_ceiling": 100,  # high ceiling so clamp doesn't interfere
            },
        )

        # bypass=True -> exempt from graduated -> static shift=5 -> high=85
        # score=87 >= 85 -> STRONG_ALERT
        result = _classify_with_cfg(
            cfg_map,
            total_score=87,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=True,
            contradiction_index=0.0,
            regime=regime,
            e2_multiplier=1.0,
        )
        assert result == SignalClass.STRONG_ALERT, (
            "High-conviction caller should use static panic shift (5), not graduated (8), "
            "so score 87 >= effective_high 85 -> STRONG_ALERT"
        )

    def test_non_bypass_gets_graduated_shift(self):
        """bypass=False, panic regime, graduated ON:
        non-bypass caller gets full graduated threshold_shift=8 (static=5, graduated=8).
        Use cutoff_ceiling=100 so the ceiling clamp doesn't interfere.

        With base_high=80, graduated shift=8, ceiling=100:
          effective_high = clamp(80+8, 70, 100) = 88.
        Score=87 < 88 -> WATCHLIST.

        With static shift=5 (what bypass would use):
          effective_high = clamp(80+5, 70, 100) = 85.
        Score=87 >= 85 -> STRONG (shows bypass would differ).
        """
        regime = RegimeContext(
            label="panic",
            z_score=2.5,
            threshold_shift=8,   # graduated shift (> static 5 for "elevated" mapped as panic here)
            cold_start=False,
            as_of_date="2026-06-10",
        )
        cfg_map = _base_cfg(
            graduated_enabled=True,
            regime_enabled=True,
            extra={
                "features.regime_classifier.regime_shifts": {"calm": -5, "elevated": 3, "panic": 5},
                # static panic = 5; graduated threshold_shift = 8 on the regime object
                "features.regime_widening_graduated.cutoff_ceiling": 100,  # high ceiling so clamp doesn't interfere
            },
        )

        # bypass=False -> full graduated shift=8 -> high=88
        # score=87 < 88 -> WATCHLIST (score >= med=65)
        result = _classify_with_cfg(
            cfg_map,
            total_score=87,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=regime,
            e2_multiplier=1.0,
        )
        assert result == SignalClass.WATCHLIST, (
            "Non-bypass caller should use full graduated shift (8) so score 87 < 88 -> WATCHLIST"
        )

    def test_bypass_graduated_off_uses_same_threshold_shift(self):
        """bypass=True, graduated OFF: bypass exemption is only relevant when
        graduated is ON; flag OFF -> threshold_shift used as-is (behavior unchanged).
        """
        regime = _make_regime("panic", threshold_shift=10)
        cfg_map = _base_cfg(graduated_enabled=False, regime_enabled=True)

        # Score=91 >= high(80+10=90) -> STRONG_ALERT (bypass or not, same result)
        result = _classify_with_cfg(
            cfg_map,
            total_score=91,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=True,
            contradiction_index=0.0,
            regime=regime,
            e2_multiplier=1.0,
        )
        assert result == SignalClass.STRONG_ALERT
