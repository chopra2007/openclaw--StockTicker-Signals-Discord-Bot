"""E2 — FRED HY credit-spread leg tests (built 2026-06-15).

Coverage:
  (a) Credit-calibrated _ratio_to_multiplier(reference_swing=0.40): widening->floor,
      tightening->ceiling, flat->1.0, mild stays inside the band.
  (b) _fetch_credit_ratio: missing FRED_API_KEY -> None; parses a mocked FRED
      JSON response into current/baseline ratio.
  (c) _obs_recent_enough: today fresh, old stale, garbage stale.
  (d) get_multiplier combine: average of the two legs, re-clamped.
  (e) Unavailable-leg handling: a None leg is dropped, never averaged in as 1.0,
      so it can't dilute the live leg. Both None -> 1.0. Master off -> 1.0.
  (f) fred_leg OFF -> VIX-only path, credit fetch never called.

All network/yfinance/FRED calls are mocked — no live access in tests.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from consensus_engine.analysis import cross_asset as _ca_mod


def _cfg(**over):
    base = {
        "features.cross_asset.enabled": True,
        "features.cross_asset.fred_leg_enabled": True,
        "features.cross_asset.fred_reference_swing": 0.40,
        "features.cross_asset.veto_floor": 0.85,
        "features.cross_asset.confirm_ceiling": 1.15,
        "features.recency_window.enabled": True,
        "features.recency_window.max_age_min.vix": 1440,
        "features.recency_window.max_age_min.fred": 1440,
    }
    base.update(over)
    return lambda k, d=None: base.get(k, d)


# ---------------------------------------------------------------------------
# (a) Credit-calibrated mapping (gentler reference_swing)
# ---------------------------------------------------------------------------

class TestCreditMapping:
    def _map(self, ratio):
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _cfg()
            return _ca_mod._ratio_to_multiplier(ratio, reference_swing=0.40)

    def test_full_widening_clamps_to_floor(self):
        # ratio 1.40 (+40% vs baseline): raw = 1 + (-0.40)*(0.15/0.40) = 0.85 -> floor
        assert self._map(1.40) == pytest.approx(0.85, abs=1e-9)

    def test_full_tightening_clamps_to_ceiling(self):
        # ratio 0.60 (-40%): raw = 1 + (0.40)*(0.15/0.40) = 1.15 -> ceiling
        assert self._map(0.60) == pytest.approx(1.15, abs=1e-9)

    def test_flat_is_one(self):
        assert self._map(1.0) == pytest.approx(1.0, abs=1e-9)

    def test_mild_widening_stays_inside_band(self):
        # ratio 1.20 (+20%): raw = 1 + (-0.20)*0.375 = 0.925 (a real, un-clamped veto)
        assert self._map(1.20) == pytest.approx(0.925, abs=1e-9)

    def test_credit_swing_is_gentler_than_vix(self):
        # The SAME +20% move is a full veto on the VIX swing (0.15) but only mild on credit (0.40).
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _cfg()
            vix_like = _ca_mod._ratio_to_multiplier(1.20, reference_swing=0.15)
            credit_like = _ca_mod._ratio_to_multiplier(1.20, reference_swing=0.40)
        assert vix_like == pytest.approx(0.85, abs=1e-9)   # saturates
        assert credit_like > vix_like                       # gentler


# ---------------------------------------------------------------------------
# (b) _fetch_credit_ratio
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def read(self):
        return json.dumps(self._p).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class TestFetchCreditRatio:
    def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert _ca_mod._fetch_credit_ratio() is None

    def test_parses_ratio_from_fred_json(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        today = date.today().isoformat()
        # latest=3.0 today; 64 baseline obs at 2.0 -> trailing-60 baseline=2.0 -> ratio=1.5
        obs = [{"date": today, "value": "3.0"}]
        obs += [{"date": today, "value": "2.0"} for _ in range(64)]
        payload = {"observations": obs}
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp(payload)):
            ratio = _ca_mod._fetch_credit_ratio()
        assert ratio == pytest.approx(1.5, abs=1e-9)

    def test_too_little_history_returns_none(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        today = date.today().isoformat()
        payload = {"observations": [{"date": today, "value": "3.0"}] * 5}  # < min+1
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp(payload)):
            assert _ca_mod._fetch_credit_ratio() is None

    def test_stale_series_returns_none(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        old = (date.today() - timedelta(days=30)).isoformat()
        obs = [{"date": old, "value": "3.0"}] + [{"date": old, "value": "2.0"} for _ in range(64)]
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp({"observations": obs})):
            assert _ca_mod._fetch_credit_ratio() is None

    def test_skips_missing_value_markers(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        today = date.today().isoformat()
        obs = [{"date": today, "value": "."}, {"date": today, "value": "3.0"}]
        obs += [{"date": today, "value": "2.0"} for _ in range(64)]
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp({"observations": obs})):
            ratio = _ca_mod._fetch_credit_ratio()
        # the "." row is dropped, so latest valid = 3.0, baseline = 2.0 -> 1.5
        assert ratio == pytest.approx(1.5, abs=1e-9)


# ---------------------------------------------------------------------------
# (c) _obs_recent_enough
# ---------------------------------------------------------------------------

class TestObsRecency:
    def test_today_is_fresh(self):
        assert _ca_mod._obs_recent_enough(date.today().isoformat()) is True

    def test_within_lag_is_fresh(self):
        assert _ca_mod._obs_recent_enough((date.today() - timedelta(days=3)).isoformat()) is True

    def test_old_is_stale(self):
        assert _ca_mod._obs_recent_enough((date.today() - timedelta(days=30)).isoformat()) is False

    def test_garbage_is_stale(self):
        assert _ca_mod._obs_recent_enough("not-a-date") is False


# ---------------------------------------------------------------------------
# (d) + (e) get_multiplier combine + unavailable-leg handling
# ---------------------------------------------------------------------------

class TestCombine:
    async def _run(self, vix, credit, **cfg_over):
        _ca_mod.clear_cache()
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _cfg(**cfg_over)
            with patch("consensus_engine.analysis.cross_asset._get_vix_multiplier",
                       new=AsyncMock(return_value=vix)), \
                 patch("consensus_engine.analysis.cross_asset._get_credit_multiplier",
                       new=AsyncMock(return_value=credit)):
                return await _ca_mod.get_multiplier()

    async def test_average_of_two_legs(self):
        # vix 0.85 (veto) + credit 1.15 (confirm) -> avg 1.0
        assert await self._run(0.85, 1.15) == pytest.approx(1.0, abs=1e-9)

    async def test_both_stress_clamps_to_floor(self):
        # avg(0.80, 0.84) = 0.82 -> clamp to floor 0.85
        assert await self._run(0.80, 0.84) == pytest.approx(0.85, abs=1e-9)

    async def test_mild_both_sides(self):
        assert await self._run(0.90, 0.96) == pytest.approx(0.93, abs=1e-9)

    async def test_credit_unavailable_falls_back_to_vix(self):
        # credit None must NOT dilute the live VIX veto toward 1.0
        assert await self._run(0.85, None) == pytest.approx(0.85, abs=1e-9)

    async def test_vix_unavailable_falls_back_to_credit(self):
        assert await self._run(None, 0.90) == pytest.approx(0.90, abs=1e-9)

    async def test_both_unavailable_returns_one(self):
        assert await self._run(None, None) == pytest.approx(1.0, abs=1e-9)

    async def test_master_off_returns_one(self):
        # master flag off -> short-circuit 1.0 even with extreme legs
        assert await self._run(0.85, 0.85, **{"features.cross_asset.enabled": False}) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# (f) fred_leg OFF -> VIX-only, credit fetch never called
# ---------------------------------------------------------------------------

class TestFredLegOff:
    async def test_fred_off_uses_vix_only_and_skips_credit(self):
        _ca_mod.clear_cache()
        credit_mock = AsyncMock(return_value=0.85)
        with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
            mock_cfg.get.side_effect = _cfg(**{"features.cross_asset.fred_leg_enabled": False})
            with patch("consensus_engine.analysis.cross_asset._get_vix_multiplier",
                       new=AsyncMock(return_value=1.10)), \
                 patch("consensus_engine.analysis.cross_asset._get_credit_multiplier",
                       new=credit_mock):
                result = await _ca_mod.get_multiplier()
        assert result == pytest.approx(1.10, abs=1e-9)
        credit_mock.assert_not_called()
