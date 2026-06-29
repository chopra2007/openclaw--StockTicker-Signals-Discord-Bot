"""#55 Build A — E2 cross_asset_shadow logger tests.

Covers:
  * insert_cross_asset_shadow writes one row per UTC day (idempotent same-day),
  * the cross_asset.get_multiplier shadow-only branch persists the SAME ratios /
    multipliers the '[E2 shadow]' log lines show, while still returning 1.0,
  * no null row is written when both legs are unavailable.

All yfinance calls are mocked — no live network access.
"""
from unittest.mock import patch

import pytest

from consensus_engine.analysis import cross_asset as ca


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


def _shadow_cfg(**extra):
    base = {
        "features.cross_asset.enabled": False,
        "features.cross_asset.shadow": True,
        "features.cross_asset.fred_leg_enabled": False,
        "features.cross_asset.veto_floor": 0.85,
        "features.cross_asset.confirm_ceiling": 1.15,
        "features.recency_window.enabled": True,
        "features.recency_window.max_age_min.vix": 1440,
        "features.recency_window.max_age_min.fred": 1440,
        "precision_engine.thresholds.high_confidence": 80,
    }
    base.update(extra)
    return base


async def test_insert_one_row_per_utc_day():
    import consensus_engine.db as db_module
    conn = await db_module.get_db()

    wrote1 = await db_module.insert_cross_asset_shadow(0.95, 1.05, 1.10, 0.90, 0.975)
    wrote2 = await db_module.insert_cross_asset_shadow(0.96, 1.04, 1.11, 0.91, 0.975)

    assert wrote1 is True
    assert wrote2 is False, "a second same-UTC-day call must be a no-op"

    cur = await conn.execute("SELECT COUNT(*) AS c FROM cross_asset_shadow")
    assert (await cur.fetchone())["c"] == 1


async def test_shadow_branch_persists_same_ratios_and_multipliers():
    import consensus_engine.db as db_module
    ca.clear_cache()
    cfg_map = _shadow_cfg()

    with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
        mock_cfg.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
        with patch(
            "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
            return_value=0.85,  # contango -> multiplier 1.15
        ):
            result = await ca.get_multiplier()
    ca.clear_cache()

    assert result == pytest.approx(1.0), "shadow mode still returns 1.0 (no live effect)"

    conn = await db_module.get_db()
    cur = await conn.execute(
        "SELECT vix_term_ratio, vix_term_multiplier, credit_oas_ratio, "
        "credit_oas_multiplier, combined_multiplier FROM cross_asset_shadow"
    )
    rows = await cur.fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["vix_term_ratio"] == pytest.approx(0.85)
    assert r["vix_term_multiplier"] == pytest.approx(1.15)
    assert r["combined_multiplier"] == pytest.approx(1.15)
    assert r["credit_oas_ratio"] is None
    assert r["credit_oas_multiplier"] is None


async def test_live_enabled_mode_also_persists():
    """#55: under the LIVE config (enabled=True, shadow=False) the daily ratios are
    STILL persisted. The FRED credit ratio is point-in-time and cannot be backfilled,
    so collection must happen in live mode too — not only in shadow mode. Live mode
    also APPLIES the multiplier (returns the combined value, not 1.0)."""
    import consensus_engine.db as db_module
    ca.clear_cache()
    cfg_map = _shadow_cfg(**{
        "features.cross_asset.enabled": True,
        "features.cross_asset.shadow": False,
    })

    with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
        mock_cfg.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
        with patch(
            "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
            return_value=0.85,  # contango -> multiplier 1.15
        ):
            result = await ca.get_multiplier()
    ca.clear_cache()

    assert result == pytest.approx(1.15), "live mode applies the multiplier (not 1.0)"

    conn = await db_module.get_db()
    cur = await conn.execute(
        "SELECT vix_term_ratio, combined_multiplier FROM cross_asset_shadow"
    )
    rows = await cur.fetchall()
    assert len(rows) == 1, "live mode must still record the daily row"
    assert rows[0]["vix_term_ratio"] == pytest.approx(0.85)
    assert rows[0]["combined_multiplier"] == pytest.approx(1.15)


async def test_no_null_row_when_both_legs_unavailable():
    import consensus_engine.db as db_module
    ca.clear_cache()
    cfg_map = _shadow_cfg()

    with patch("consensus_engine.analysis.cross_asset.cfg") as mock_cfg:
        mock_cfg.get.side_effect = lambda k, d=None: cfg_map.get(k, d)
        with patch(
            "consensus_engine.analysis.cross_asset._fetch_vix_ratio",
            return_value=None,  # no VIX data; fred leg disabled -> no legs
        ):
            result = await ca.get_multiplier()
    ca.clear_cache()

    assert result == pytest.approx(1.0)
    conn = await db_module.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM cross_asset_shadow")
    assert (await cur.fetchone())["c"] == 0, "no row when both legs are unavailable"
