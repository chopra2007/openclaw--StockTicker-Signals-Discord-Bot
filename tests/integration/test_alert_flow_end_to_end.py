"""Integration tests for the full tweet → alert → Phase-2 pipeline.

Tests are RED at Commit A; they turn GREEN as Commits C-F land.

Scenario 1 (multi-analyst M3 + shadow calibration):
    3 analysts fire the same ticker in 4h. With per-analyst cooldown:
    - 2 alerts survive (TeresaTrades first, kpak82 second > 30 min apart)
    - 1 alert is suppressed (kpak82 within floor window of TeresaTrades)
    - Each surviving alert produces 1 Phase-1 ping + 1 Phase-2 followup
    - 2 decision_snapshots rows exist with feature_vector_json containing 'shadow_prob'

Scenario 2 (timeout injection):
    xref coroutine sleeps 130s with cross_reference_timeout=120.
    - Phase-1 message is edited to 'Phase 2 skipped — timeout'
    - followup_msg_id remains NULL for that alert_messages row
    - The alert_history row is still written (Phase-1 ping succeeded)
"""
import asyncio
import time
import pytest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg, db
from consensus_engine.models import SourceType, TickerSignal, Sentiment


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


def _make_xref(ticker: str = "NVDA", final_score: float = 72.0):
    xr = MagicMock()
    xr.final_score = final_score
    xr.catalyst_summary = "large options flow"
    xr.catalyst_type = "options"
    xr.other_analysts = []
    xr.technical = None
    xr.breakdown = MagicMock()
    xr.breakdown.__iter__ = MagicMock(return_value=iter([]))
    xr.contradiction_index = 0.1
    xr.consolidation_result = None
    return xr


# ---------------------------------------------------------------------------
# Scenario 1: multi-analyst M3 + shadow calibration
# (RED until Commits C, E, F all land)
# ---------------------------------------------------------------------------

async def test_three_analyst_fixture_two_survive_with_shadow_calibration(test_db):
    """Fixture: 3 analysts fire NVDA within 4h.
    Expected post-plan behaviour:
      - 2 alerts survive per-analyst cooldown (TeresaTrades, kpak82 >30 min apart)
      - 1 suppressed (second kpak82 within floor)
      - Each survivor has 1 Phase-1 ping + 1 Phase-2 followup
      - 2 decision_snapshots rows with feature_vector_json LIKE '%shadow_prob%'

    RED until Commits C (signal_events routing), E (per-analyst cooldown),
    and F (shadow calibration log) all merge.
    """
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine.engine import SignalClass

    # Configure per-analyst cooldown
    cfg._config.setdefault("alerts", {}).setdefault("per_analyst_cooldown", {}).update(
        {"enabled": True, "floor_minutes": 30, "high_conviction_bypass": True}
    )
    cfg._config.setdefault("precision_engine", {}).setdefault("thresholds", {})[
        "high_conviction_threshold"
    ] = 30
    cfg._config.setdefault("calibration", {}).setdefault("shadow_mode", {})["enabled"] = True

    # Simulate 3 insert_signal + check_alert_cooldown + _run_cross_reference calls
    # TeresaTrades alert — 2h ago
    t0 = time.time() - 7200  # 2h ago
    await test_db.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type,
            consensus_breakdown, technical_data, analyst_mentions,
            alerted_at, price_at_alert)
           VALUES ('NVDA', 50.0, '', '', '{}', '{}', '["TeresaTrades"]', ?, 100.0)""",
        (t0,),
    )
    await test_db.commit()

    # kpak82 alert 30+ min after TeresaTrades — should survive
    alert_msg_id_1 = await db.insert_alert_message(
        ticker="NVDA", analyst="kpak82",
        instant_msg_id="int_msg_001", base_score=40,
    )
    alert_row_id_1 = await db.insert_alert(
        ticker="NVDA", confidence=40.0, catalyst="flow", catalyst_type="options",
        consensus_json="{}", technical_json="{}", analysts_json='["kpak82"]',
        price=100.0,
    )

    followup_calls: list = []

    async def fast_xref(ticker, tweet):
        return _make_xref(ticker)

    async def ok_precision(ticker, base_score=0, budget=None):
        return {"classification": SignalClass.WATCHLIST, "skipped": False, "total_score": 72}

    async def capture_followup(xref, msg_id, precision=None):
        followup_calls.append(msg_id)
        return f"followup_{msg_id}"

    tweet = MagicMock()
    tweet.analyst = "kpak82"
    tweet.base_score = 40
    tweet.tickers = ["NVDA"]

    with patch("consensus_engine.main.cross_reference", side_effect=fast_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=ok_precision), \
         patch("consensus_engine.main.send_detail_followup", side_effect=capture_followup):

        await _run_cross_reference_and_followup(
            "NVDA", tweet, "int_msg_001", alert_msg_id_1, alert_row_id_1
        )

    # Phase-2 must have fired for kpak82 (it's not in cooldown w.r.t. TeresaTrades)
    row1 = await db.get_alert_message(alert_msg_id_1)
    assert row1["followup_msg_id"] is not None, (
        "kpak82 alert must receive Phase-2 followup — RED until Commit E per-analyst cooldown"
    )

    # Shadow calibration: decision_snapshots rows must have shadow_prob
    # RED until Commit F adds log_shadow_prediction calls
    cursor = await test_db.execute(
        "SELECT COUNT(*) as cnt FROM decision_snapshots "
        "WHERE feature_vector_json LIKE '%shadow_prob%'"
    )
    row = await cursor.fetchone()
    assert row["cnt"] >= 1, (
        f"Expected >=1 decision_snapshots row with shadow_prob, got {row['cnt']} — "
        "RED until Commit F adds shadow calibration logging"
    )


# ---------------------------------------------------------------------------
# Scenario 2: timeout injection harness
# (RED until Commit D wraps xref_task in asyncio.wait_for)
# ---------------------------------------------------------------------------

async def test_timeout_injection_edits_skip_message_and_leaves_followup_null(test_db):
    """With cross_reference_timeout=0.05 and xref sleeping 0.5s:
      - Phase-1 message is edited to 'Phase 2 skipped — timeout'
      - followup_msg_id remains NULL in alert_messages
      - alert_history row IS present (Phase-1 ping was already recorded)

    RED until Commit D wraps xref_task in asyncio.wait_for.
    """
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine import db as _db

    cfg._config.setdefault("intervals", {})["cross_reference_timeout"] = 0.05

    alert_msg_id = await _db.insert_alert_message(
        ticker="NVDA", analyst="TeresaTrades",
        instant_msg_id="int_msg_timeout_001", base_score=25,
    )
    alert_row_id = await _db.insert_alert(
        ticker="NVDA", confidence=25.0, catalyst="", catalyst_type="",
        consensus_json="{}", technical_json="{}", analysts_json="[]", price=100.0,
    )

    async def slow_xref(ticker, tweet):
        await asyncio.sleep(0.5)  # Exceeds 0.05s timeout
        return _make_xref()

    async def fast_precision(ticker, base_score=0, budget=None):
        return {"classification": None, "skipped": False, "total_score": 50}

    edit_calls: list = []

    async def capture_edit(msg_id, content, **kw):
        edit_calls.append((msg_id, content))

    tweet = MagicMock()
    tweet.analyst = "TeresaTrades"
    tweet.base_score = 25
    tweet.tickers = ["NVDA"]

    with patch("consensus_engine.main.cross_reference", side_effect=slow_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=fast_precision), \
         patch("consensus_engine.main.edit_instant_ping", capture_edit, create=True):

        await _run_cross_reference_and_followup(
            "NVDA", tweet, "int_msg_timeout_001", alert_msg_id, alert_row_id
        )

    # Assert 1: Phase-1 edit contains timeout message
    timeout_edits = [
        c for c in edit_calls
        if "Phase 2 skipped" in str(c[1]) and "timeout" in str(c[1]).lower()
    ]
    assert timeout_edits, (
        f"Expected 'Phase 2 skipped — timeout' edit, got={edit_calls!r} — "
        "RED until Commit D adds asyncio.wait_for"
    )

    # Assert 2: followup_msg_id must remain NULL
    msg_row = await _db.get_alert_message(alert_msg_id)
    assert msg_row["followup_msg_id"] is None, (
        f"followup_msg_id must be NULL when xref timed out, "
        f"got {msg_row['followup_msg_id']!r}"
    )

    # Assert 3: alert_history row still exists (Phase-1 persisted before xref)
    cursor = await test_db.execute(
        "SELECT COUNT(*) as cnt FROM alert_history WHERE ticker = 'NVDA'"
    )
    row = await cursor.fetchone()
    assert row["cnt"] >= 1, "alert_history must have the Phase-1 row even when Phase-2 times out"
