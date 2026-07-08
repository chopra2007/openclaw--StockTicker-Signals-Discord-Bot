"""r21 (macro-fred) — FRED NFCI shadow-isolated leg tests.

Coverage:
  (a) NFCI level -> multiplier mapping via _get_nfci_multiplier: level 0 -> neutral 1.0,
      positive (stress) -> veto side (<1.0), negative (calm) -> confirm side (>1.0),
      saturation at +/- reference_swing.
  (b) _fetch_nfci_index: missing FRED_API_KEY -> None; parses the latest level from a
      mocked FRED JSON; weekly-stale latest obs -> None; skips "." missing-value markers.
  (c) _nfci_obs_recent_enough: today / 8-day fresh (weekly tolerance), 30-day stale,
      garbage stale.
  (d) SHADOW ISOLATION (HARD RULE): with nfci_leg_enabled OFF, NFCI is computed + logged +
      persisted but NEVER enters `legs`, so get_multiplier's combined value + return are
      byte-identical to the VIX+credit-only path.
  (e) nfci_leg_enabled is the real switch: ON, NFCI enters the live combine.

All FRED/network calls are mocked — no live access in tests.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from consensus_engine.analysis import cross_asset as _ca

# The conftest autouse `_isolate_nfci_fred` fixture stubs _fetch_nfci_index to None
# (network guard) for the whole suite. Capture the REAL function at import time so the
# direct-fetch unit tests below exercise the actual FRED-parsing logic, not the stub.
_REAL_FETCH_NFCI = _ca._fetch_nfci_index


# ---------------------------------------------------------------------------
# fresh temp db (for the persistence / shadow-isolation assertions)
# ---------------------------------------------------------------------------

@pytest.fixture
async def fresh_db(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield db_module
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


def _cfg_map(**over):
    base = {
        "features.cross_asset.nfci_reference_swing": 1.0,
        "features.cross_asset.veto_floor": 0.85,
        "features.cross_asset.confirm_ceiling": 1.15,
        "features.recency_window.enabled": True,
        "features.recency_window.max_age_min.nfci": 1440,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# (a) level -> multiplier mapping through the real _get_nfci_multiplier
# ---------------------------------------------------------------------------

class TestNfciMapping:
    async def _mult(self, level, **over):
        _ca.clear_cache()
        cfg_map = _cfg_map(**over)
        with patch("consensus_engine.analysis.cross_asset.cfg") as mc:
            mc.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
            with patch("consensus_engine.analysis.cross_asset._fetch_nfci_index",
                       return_value=level):
                m = await _ca._get_nfci_multiplier()
        _ca.clear_cache()
        return m

    async def test_zero_is_neutral(self):
        # nfci = 0 -> ratio-equivalent 1.0 -> neutral 1.0
        assert await self._mult(0.0) == pytest.approx(1.0, abs=1e-9)

    async def test_full_stress_clamps_to_floor(self):
        # nfci = +1.0 (== reference_swing) -> full veto -> floor 0.85
        assert await self._mult(1.0) == pytest.approx(0.85, abs=1e-9)

    async def test_full_calm_clamps_to_ceiling(self):
        # nfci = -1.0 -> full confirm -> ceiling 1.15
        assert await self._mult(-1.0) == pytest.approx(1.15, abs=1e-9)

    async def test_mild_stress_stays_inside_band(self):
        # nfci = +0.5 -> raw = 1 - 0.5*0.15 = 0.925 (real, un-clamped veto)
        assert await self._mult(0.5) == pytest.approx(0.925, abs=1e-9)

    async def test_mild_calm_stays_inside_band(self):
        # nfci = -0.5 -> raw = 1 + 0.5*0.15 = 1.075
        assert await self._mult(-0.5) == pytest.approx(1.075, abs=1e-9)

    async def test_none_level_returns_none(self):
        # no NFCI data -> leg unavailable (None), never a stale/neutral placeholder
        assert await self._mult(None) is None


# ---------------------------------------------------------------------------
# (b) _fetch_nfci_index
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


class TestFetchNfciIndex:
    def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert _REAL_FETCH_NFCI() is None

    def test_parses_latest_level(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        today = date.today().isoformat()
        payload = {"observations": [
            {"date": today, "value": "-0.35"},
            {"date": today, "value": "-0.40"},
        ]}
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp(payload)):
            assert _REAL_FETCH_NFCI() == pytest.approx(-0.35, abs=1e-9)

    def test_weekly_stale_returns_none(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        old = (date.today() - timedelta(days=30)).isoformat()
        payload = {"observations": [{"date": old, "value": "-0.35"}]}
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp(payload)):
            assert _REAL_FETCH_NFCI() is None

    def test_skips_missing_value_markers(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        today = date.today().isoformat()
        payload = {"observations": [
            {"date": today, "value": "."},
            {"date": today, "value": "0.12"},
        ]}
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   return_value=_FakeResp(payload)):
            assert _REAL_FETCH_NFCI() == pytest.approx(0.12, abs=1e-9)

    def test_error_returns_none(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "dummy")
        with patch("consensus_engine.analysis.cross_asset.urllib.request.urlopen",
                   side_effect=RuntimeError("network down")):
            assert _REAL_FETCH_NFCI() is None


# ---------------------------------------------------------------------------
# (c) _nfci_obs_recent_enough (weekly tolerance)
# ---------------------------------------------------------------------------

class TestNfciObsRecency:
    def test_today_is_fresh(self):
        assert _ca._nfci_obs_recent_enough(date.today().isoformat()) is True

    def test_eight_days_is_fresh(self):
        # weekly cadence: an 8-day gap is inside the 10-day tolerance
        assert _ca._nfci_obs_recent_enough(
            (date.today() - timedelta(days=8)).isoformat()) is True

    def test_thirty_days_is_stale(self):
        assert _ca._nfci_obs_recent_enough(
            (date.today() - timedelta(days=30)).isoformat()) is False

    def test_garbage_is_stale(self):
        assert _ca._nfci_obs_recent_enough("not-a-date") is False


# ---------------------------------------------------------------------------
# (d) SHADOW ISOLATION — NFCI never enters `legs`; live path byte-identical
# ---------------------------------------------------------------------------

class TestShadowIsolation:
    def _cfg(self, **over):
        base = {
            "features.cross_asset.enabled": True,
            "features.cross_asset.shadow": False,
            "features.cross_asset.fred_leg_enabled": True,
            "features.cross_asset.nfci_leg_enabled": False,   # shadow-isolated
            "features.cross_asset.nfci_reference_swing": 1.0,
            "features.cross_asset.veto_floor": 0.85,
            "features.cross_asset.confirm_ceiling": 1.15,
            "features.recency_window.enabled": True,
            "features.recency_window.max_age_min.vix": 1440,
            "features.recency_window.max_age_min.fred": 1440,
            "features.recency_window.max_age_min.nfci": 1440,
            "precision_engine.thresholds.high_confidence": 80,
        }
        base.update(over)
        return base

    async def test_nfci_off_is_byte_identical_and_persisted(self, fresh_db):
        """HARD RULE #1: nfci_leg_enabled OFF. NFCI maps to an EXTREME 0.85 veto, yet the
        combined multiplier stays the VIX+credit value (1.15) bit-for-bit — NFCI is absent
        from `legs`. The nfci_index/nfci_multiplier columns are still persisted for the soak."""
        _ca.clear_cache()
        cfg_map = self._cfg()
        with patch("consensus_engine.analysis.cross_asset.cfg") as mc:
            mc.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
            with patch("consensus_engine.analysis.cross_asset._get_vix_multiplier",
                       new=AsyncMock(return_value=1.15)), \
                 patch("consensus_engine.analysis.cross_asset._get_credit_multiplier",
                       new=AsyncMock(return_value=1.15)), \
                 patch("consensus_engine.analysis.cross_asset._fetch_nfci_index",
                       return_value=1.0):  # -> nfci multiplier 0.85 (extreme veto)
                result = await _ca.get_multiplier()

        # If NFCI had leaked into `legs`, avg(1.15, 1.15, 0.85) = 1.05 — this proves it did not.
        assert result == pytest.approx(1.15, abs=1e-9)

        conn = await fresh_db.get_db()
        cur = await conn.execute(
            "SELECT combined_multiplier, nfci_index, nfci_multiplier FROM cross_asset_shadow"
        )
        rows = await cur.fetchall()
        _ca.clear_cache()
        assert len(rows) == 1
        assert rows[0]["combined_multiplier"] == pytest.approx(1.15, abs=1e-9)
        assert rows[0]["nfci_index"] == pytest.approx(1.0, abs=1e-9)
        assert rows[0]["nfci_multiplier"] == pytest.approx(0.85, abs=1e-9)

    async def test_flag_on_lets_nfci_enter_the_combine(self, fresh_db):
        """(e) The flag is a real switch: nfci_leg_enabled ON appends NFCI into `legs`,
        so combined = clamp(avg(1.15, 1.15, 0.85)) = 1.0166... This build ships it OFF."""
        _ca.clear_cache()
        cfg_map = self._cfg(**{"features.cross_asset.nfci_leg_enabled": True})
        with patch("consensus_engine.analysis.cross_asset.cfg") as mc:
            mc.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
            with patch("consensus_engine.analysis.cross_asset._get_vix_multiplier",
                       new=AsyncMock(return_value=1.15)), \
                 patch("consensus_engine.analysis.cross_asset._get_credit_multiplier",
                       new=AsyncMock(return_value=1.15)), \
                 patch("consensus_engine.analysis.cross_asset._fetch_nfci_index",
                       return_value=1.0):
                result = await _ca.get_multiplier()
        _ca.clear_cache()
        assert result == pytest.approx((1.15 + 1.15 + 0.85) / 3.0, abs=1e-9)
