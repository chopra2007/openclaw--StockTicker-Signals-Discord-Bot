"""trade-edge market-context layer — Phase-0 schema + config-flag tests.

Asserts the 5 new daily tables (final-plan.md §4) are created by the normal
init_db() path on a temp db, each with its expected columns, and that the new
features.* flags default OFF via config.get.
"""
import pytest
from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test_market_layer.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


# Expected table -> required columns (final-plan.md §4, verbatim column names).
EXPECTED = {
    "sector_rs_daily": {
        "date_utc", "etf", "rs_ratio", "rs_momentum", "quadrant",
        "inflection", "n_window", "k_window", "computed_at",
    },
    "factor_rs_daily": {
        "date_utc", "factor_etf", "rs_vs_spy", "rs_momentum",
        "leading", "accelerating", "computed_at",
    },
    "trend_daily": {
        "date_utc", "index_symbol", "close", "sma_200", "sma_50",
        "sma_50_slope", "tsmom_3m", "dist_200_z", "trend_state", "computed_at",
    },
    "macro_legs_daily": {
        "date_utc", "copper_gold_roc", "dxy_roc", "semis_rs", "cyc_def_div",
        "curve_t10y2y", "curve_t10y3m", "macro_multiplier", "legs_used_json",
        "computed_at",
    },
    "internal_breadth_daily": {
        "date_utc", "net_bull_bear", "n_bullish", "n_bearish",
        "osc_z", "n_signals", "computed_at",
    },
}


async def _columns(conn, table):
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {r[1] for r in rows}


@pytest.mark.parametrize("table", sorted(EXPECTED.keys()))
@pytest.mark.asyncio
async def test_market_layer_table_exists(test_db, table):
    cur = await test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    assert await cur.fetchone() is not None, f"{table} not created by init_db()"


@pytest.mark.parametrize("table", sorted(EXPECTED.keys()))
@pytest.mark.asyncio
async def test_market_layer_columns(test_db, table):
    cols = await _columns(test_db, table)
    missing = EXPECTED[table] - cols
    assert not missing, f"{table} missing columns: {missing}"


@pytest.mark.asyncio
async def test_schema_version_bumped(test_db):
    cur = await test_db.execute("SELECT MAX(version) FROM schema_version")
    (latest,) = await cur.fetchone()
    assert latest >= 21, f"schema_version not bumped to >=21 (got {latest})"


@pytest.mark.parametrize(
    "flag",
    [
        "features.sector_rotation.enabled",
        "features.factor_rotation.enabled",
        "features.trend_regime.enabled",
        "features.macro_legs.enabled",
        "features.internal_breadth.enabled",
        "features.market_command.enabled",
    ],
)
def test_new_flags_default_off(flag):
    assert cfg.get(flag, None) is False, f"{flag} must default OFF"


def test_market_data_keys_present():
    assert cfg.get("features.market_data.store_dir", None) == "data/market_store"
    assert cfg.get("features.market_data.fallback_provider", None) == "stooq"
    # recency caps for the new daily feeds
    for feed in ("sector_rs", "factor_rs", "trend", "macro_legs"):
        assert cfg.get(f"features.recency_window.max_age_min.{feed}", None) == 1440
