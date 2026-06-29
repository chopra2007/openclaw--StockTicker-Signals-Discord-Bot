"""#55 Build C — analyst track-record SHADOW producer tests.

Covers:
  * sign-adjusted grading (a BEARISH catalyst whose price FELL is a HIT),
  * per-(handle, horizon) aggregation for 1h and 24h,
  * multi-handle rows credit every handle,
  * skipping empty/[] analyst_mentions and rows missing a horizon price,
  * the CRITICAL SAFETY INVARIANT: the producer writes ONLY to
    source_performance_shadow and leaves the live source_performance EMPTY.
"""
import time

import pytest

from consensus_engine.analysis.source_performance import (
    BEARISH_CATALYSTS,
    compute_source_performance_shadow,
)


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


async def _insert_alert(conn, mentions, catalyst, entry, p1h, p24h):
    await conn.execute(
        """INSERT INTO alert_history
           (ticker, catalyst_type, analyst_mentions, alerted_at,
            price_at_alert, price_1h_later, price_24h_later)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("TST", catalyst, mentions, time.time(), entry, p1h, p24h),
    )


async def _seed(conn):
    # BearGuru: bearish catalyst, price FELL at both horizons -> HIT both.
    await _insert_alert(conn, '["BearGuru"]', "Analyst Downgrade", 100.0, 95.0, 90.0)
    # BullGuru row A: bullish catalyst, price ROSE -> HIT both.
    await _insert_alert(conn, '["BullGuru"]', "Analyst Upgrade", 100.0, 105.0, 110.0)
    # BullGuru row B: bullish/neutral catalyst, price FELL -> MISS both.
    await _insert_alert(conn, '["BullGuru"]', "Product Launch", 100.0, 95.0, 98.0)
    # Two handles in one row, bullish, price ROSE -> both HIT.
    await _insert_alert(conn, '["DuoA", "DuoB"]', "Partnership", 100.0, 101.0, 102.0)
    # Empty array -> skipped entirely.
    await _insert_alert(conn, "[]", "Analyst Upgrade", 100.0, 105.0, 110.0)
    # No horizon prices -> scanned but produces no graded rows.
    await _insert_alert(conn, '["NoOutcome"]', "Analyst Upgrade", 100.0, None, None)
    await conn.commit()


async def test_bearish_catalyst_price_fell_is_a_hit():
    """The sign-adjust proof: a bearish-catalyst alert whose price FELL is graded HIT."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await _seed(conn)

    await compute_source_performance_shadow()

    cur = await conn.execute(
        "SELECT rolling_accuracy, sample_count FROM source_performance_shadow "
        "WHERE entity_id='BearGuru' AND horizon='1h'"
    )
    row = await cur.fetchone()
    assert row is not None, "BearGuru should have a 1h shadow row"
    assert row["sample_count"] == 1
    assert row["rolling_accuracy"] == pytest.approx(1.0), (
        "Bearish catalyst (Analyst Downgrade) with a downward move must score a HIT"
    )
    # And confirm 'Analyst Downgrade' is actually in the bearish set.
    assert "Analyst Downgrade" in BEARISH_CATALYSTS


async def test_live_source_performance_stays_empty_invariant():
    """CRITICAL: the producer must NEVER write the live source_performance table."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await _seed(conn)

    await compute_source_performance_shadow()

    cur = await conn.execute("SELECT COUNT(*) AS c FROM source_performance")
    live = await cur.fetchone()
    assert live["c"] == 0, "source_performance MUST stay empty (live readers unchanged)"

    cur = await conn.execute("SELECT COUNT(*) AS c FROM source_performance_shadow")
    shadow = await cur.fetchone()
    assert shadow["c"] > 0, "source_performance_shadow must be populated"


async def test_aggregation_and_horizons():
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await _seed(conn)

    summary = await compute_source_performance_shadow()

    # BullGuru: 1 hit / 2 graded per horizon -> 0.5.
    for horizon in ("1h", "24h"):
        cur = await conn.execute(
            "SELECT rolling_accuracy, sample_count FROM source_performance_shadow "
            "WHERE entity_id='BullGuru' AND horizon=?",
            (horizon,),
        )
        row = await cur.fetchone()
        assert row["sample_count"] == 2
        assert row["rolling_accuracy"] == pytest.approx(0.5)

    # Both handles in a multi-handle row are credited.
    for handle in ("DuoA", "DuoB"):
        cur = await conn.execute(
            "SELECT rolling_accuracy, sample_count FROM source_performance_shadow "
            "WHERE entity_id=? AND horizon='1h'",
            (handle,),
        )
        row = await cur.fetchone()
        assert row is not None and row["sample_count"] == 1
        assert row["rolling_accuracy"] == pytest.approx(1.0)

    # Empty-array and no-outcome handles produce no graded rows.
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM source_performance_shadow WHERE entity_id='NoOutcome'"
    )
    assert (await cur.fetchone())["c"] == 0
    assert summary["by_horizon"]["1h"] >= 3


async def test_idempotent_rerun_replaces_not_duplicates():
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await _seed(conn)

    await compute_source_performance_shadow()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM source_performance_shadow")
    first = (await cur.fetchone())["c"]

    await compute_source_performance_shadow()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM source_performance_shadow")
    second = (await cur.fetchone())["c"]

    assert first == second, "Re-running must INSERT OR REPLACE, not accumulate rows"
