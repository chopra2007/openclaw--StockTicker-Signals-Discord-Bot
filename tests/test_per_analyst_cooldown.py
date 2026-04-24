"""Tests for M3: per-analyst cooldown rewrite.

RED at Commit A — turns GREEN when Commit E lands.

Covers:
- check_alert_cooldown(ticker, analyst, base_score) independent across analysts
- same analyst within floor_minutes is blocked
- fallback to ticker-level 6h when per_analyst_cooldown.enabled=false
- HIGH-conviction (base_score >= high_conviction_threshold) bypasses cooldown
- floor_minutes ceiling blocks even 100%-precision analysts from firing twice inside the floor
"""
import time
import pytest

from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    conn = await db.init_db()
    yield conn
    await db.close_db()


async def _insert_alert(ticker: str, analyst: str, age_seconds: int = 0):
    """Insert a fake alert_history row for (ticker, analyst) n seconds ago."""
    conn = await db.get_db()
    alerted_at = time.time() - age_seconds
    await conn.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type,
            consensus_breakdown, technical_data, analyst_mentions,
            alerted_at, price_at_alert)
           VALUES (?, 50.0, '', '', '{}', '{}', ?, ?, 100.0)""",
        (ticker, f'["{analyst}"]', alerted_at),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Per-analyst independence (RED until Commit E)
# ---------------------------------------------------------------------------

async def test_cooldown_passes_for_different_analyst_on_same_ticker(test_db):
    """TeresaTrades/NVDA is NOT in cooldown even when kpak82/NVDA alerted 2h ago.

    RED until Commit E rewrites check_alert_cooldown to accept (ticker, analyst, base_score).
    Current signature is (ticker,) only — this test raises TypeError.
    """
    await _insert_alert("NVDA", "kpak82", age_seconds=7200)

    # New signature — raises TypeError until Commit E changes db.check_alert_cooldown.
    result = await db.check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=25)
    assert result is True


async def test_cooldown_blocks_same_analyst_within_floor_minutes(test_db):
    """Same analyst/ticker within floor_minutes (30 min default) is blocked.

    RED until Commit E adds per-analyst floor enforcement.
    """
    cfg._config.setdefault("alerts", {}).setdefault("per_analyst_cooldown", {}).update(
        {"enabled": True, "floor_minutes": 30}
    )

    await _insert_alert("NVDA", "TeresaTrades", age_seconds=300)  # 5 min ago

    result = await db.check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=25)
    assert result is False, "same analyst within 30-min floor must be blocked"


# ---------------------------------------------------------------------------
# Fallback to ticker-level when disabled (RED until Commit E)
# ---------------------------------------------------------------------------

async def test_cooldown_falls_back_to_ticker_level_6h_when_disabled(test_db):
    """When per_analyst_cooldown.enabled=false, any analyst on a recent ticker is blocked.

    RED until Commit E adds the enabled-flag path.
    """
    cfg._config.setdefault("alerts", {}).setdefault("per_analyst_cooldown", {})["enabled"] = False

    # kpak82/NVDA alerted 2h ago — inside the 6h blanket window
    await _insert_alert("NVDA", "kpak82", age_seconds=7200)

    # Different analyst, but ticker-level 6h cooldown should block
    result = await db.check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=25)
    assert result is False, "ticker-level 6h fallback must block any analyst on NVDA"


# ---------------------------------------------------------------------------
# HIGH-conviction bypass (RED until Commit E)
# ---------------------------------------------------------------------------

async def test_high_conviction_base_score_bypasses_cooldown(test_db):
    """base_score >= high_conviction_threshold bypasses cooldown entirely.

    RED until Commit E adds the high_conviction_bypass path.
    """
    cfg._config.setdefault("alerts", {}).setdefault("per_analyst_cooldown", {}).update(
        {"enabled": True, "high_conviction_bypass": True}
    )
    cfg._config.setdefault("precision_engine", {}).setdefault("thresholds", {})[
        "high_conviction_threshold"
    ] = 30

    # TeresaTrades alerted 5 min ago — normally in floor cooldown
    await _insert_alert("NVDA", "TeresaTrades", age_seconds=300)

    # HIGH-conviction score (>=30) must skip cooldown entirely
    result = await db.check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=30)
    assert result is True, "HIGH-conviction base_score must bypass per-analyst cooldown"


# ---------------------------------------------------------------------------
# floor_minutes ceiling (RED until Commit E)
# ---------------------------------------------------------------------------

async def test_floor_minutes_blocks_even_100pct_precision_analyst(test_db):
    """Even a 100%-precision analyst is blocked if last alert was < floor_minutes ago.

    RED until Commit E enforces per_analyst_floor_minutes regardless of precision.
    """
    cfg._config.setdefault("alerts", {}).setdefault("per_analyst_cooldown", {}).update(
        {"enabled": True, "floor_minutes": 30}
    )

    # Insert 100% precision record for TeresaTrades
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO source_performance
           (entity_id, horizon, rolling_accuracy, sample_count, updated_at)
           VALUES ('TeresaTrades', '1h', 1.0, 100, unixepoch())"""
    )
    await conn.commit()

    # Alert 10 min ago — within the 30-min floor
    await _insert_alert("NVDA", "TeresaTrades", age_seconds=600)

    result = await db.check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=25)
    assert result is False, (
        "100%-precision analyst must still be blocked by floor_minutes ceiling"
    )
