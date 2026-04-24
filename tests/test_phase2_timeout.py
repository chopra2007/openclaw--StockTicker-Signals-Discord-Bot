"""Tests for Q2a: phase-2 timeout + explicit skip message.

RED at Commit A — turns GREEN when Commit D lands.

Covers:
- xref timeout → Phase-1 message edited with 'Phase 2 skipped — timeout'
- precision task is NOT cancelled when xref times out
- classification == IGNORE → Phase-1 message edited with 'Phase 2 skipped — low precision'
- normal path still updates followup_msg_id in alert_messages
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    from consensus_engine import db
    db_path = str(tmp_path / "test.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    conn = await db.init_db()
    yield conn
    await db.close_db()


def _make_tweet(ticker: str = "NVDA", analyst: str = "TeresaTrades", score: int = 25):
    t = MagicMock()
    t.analyst = analyst
    t.base_score = score
    t.tickers = [ticker]
    return t


def _make_xref_result(ticker: str = "NVDA", final_score: float = 50.0):
    xr = MagicMock()
    xr.final_score = final_score
    xr.catalyst_summary = "test catalyst"
    xr.catalyst_type = "earnings"
    xr.other_analysts = []
    xr.technical = None
    xr.breakdown = MagicMock()
    xr.breakdown.__iter__ = MagicMock(return_value=iter([]))
    xr.contradiction_index = 0.1
    return xr


# ---------------------------------------------------------------------------
# Timeout path (RED until Commit D)
# ---------------------------------------------------------------------------

async def test_xref_timeout_edits_phase1_message_with_skip_timeout(test_db):
    """When xref_task takes longer than cross_reference_timeout, the Phase-1 Discord
    message is edited with 'Phase 2 skipped — timeout'.

    RED until Commit D wraps xref_task in asyncio.wait_for and adds the edit call.
    """
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine import db

    alert_msg_id = await db.insert_alert_message(
        ticker="NVDA", analyst="TeresaTrades",
        instant_msg_id="msg_t001", base_score=25,
    )
    alert_row_id = await db.insert_alert(
        ticker="NVDA", confidence=25.0, catalyst="", catalyst_type="",
        consensus_json="{}", technical_json="{}", analysts_json="[]", price=100.0,
    )

    async def slow_xref(ticker, tweet):
        # Exceeds test timeout of 0.05s; fast enough not to stall suite
        await asyncio.sleep(0.5)
        return _make_xref_result()

    async def fast_precision(ticker, base_score=0, budget=None):
        return {"classification": None, "skipped": False, "total_score": 50}

    edit_calls: list = []

    async def capture_edit(msg_id, content, **kw):
        edit_calls.append((msg_id, content))

    tweet = _make_tweet()

    # Set a short timeout so the test is fast
    cfg._config.setdefault("intervals", {})["cross_reference_timeout"] = 0.05

    with patch("consensus_engine.main.cross_reference", side_effect=slow_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=fast_precision), \
         patch("consensus_engine.main.edit_instant_ping", capture_edit, create=True):

        await _run_cross_reference_and_followup(
            "NVDA", tweet, "msg_t001", alert_msg_id, alert_row_id
        )

    timeout_edits = [
        c for c in edit_calls
        if "Phase 2 skipped" in str(c[1]) and "timeout" in str(c[1]).lower()
    ]
    assert timeout_edits, (
        f"Expected Discord edit containing 'Phase 2 skipped — timeout', "
        f"got edit_calls={edit_calls!r} — RED until Commit D adds asyncio.wait_for"
    )


async def test_precision_task_completes_even_when_xref_times_out(test_db):
    """Precision engine result is captured even when xref times out.

    This verifies the xref timeout does NOT cancel the precision task
    (they must run concurrently, not in a single gather).

    RED until Commit D separates xref from the gather-based precision path.
    """
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine import db

    alert_msg_id = await db.insert_alert_message(
        ticker="NVDA", analyst="kpak82",
        instant_msg_id="msg_t002", base_score=25,
    )
    alert_row_id = await db.insert_alert(
        ticker="NVDA", confidence=25.0, catalyst="", catalyst_type="",
        consensus_json="{}", technical_json="{}", analysts_json="[]", price=100.0,
    )

    precision_captured: list = []

    async def slow_xref(ticker, tweet):
        await asyncio.sleep(0.5)
        return _make_xref_result()

    async def fast_precision(ticker, base_score=0, budget=None):
        result = {"classification": None, "skipped": False, "total_score": 50, "_ran": True}
        precision_captured.append(result)
        return result

    tweet = _make_tweet(analyst="kpak82", ticker="NVDA")

    cfg._config.setdefault("intervals", {})["cross_reference_timeout"] = 0.05

    with patch("consensus_engine.main.cross_reference", side_effect=slow_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=fast_precision), \
         patch("consensus_engine.main.edit_instant_ping", AsyncMock(), create=True), \
         patch("consensus_engine.main.send_detail_followup", AsyncMock(return_value="fp_999")):

        await _run_cross_reference_and_followup(
            "NVDA", tweet, "msg_t002", alert_msg_id, alert_row_id
        )

    assert precision_captured, (
        "Precision task must complete even when xref times out — "
        "RED until Commit D decouples xref from asyncio.gather"
    )


# ---------------------------------------------------------------------------
# Low-precision path (RED until Commit D)
# ---------------------------------------------------------------------------

async def test_low_precision_classification_edits_skip_low_precision_message(test_db):
    """When precision engine returns classification == IGNORE, the Phase-1 Discord
    message is edited with 'Phase 2 skipped — low precision'.

    RED until Commit D adds the explicit low-precision skip-message edit.
    """
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine.engine import SignalClass
    from consensus_engine import db

    alert_msg_id = await db.insert_alert_message(
        ticker="TSLA", analyst="CheddarFlow",
        instant_msg_id="msg_t003", base_score=20,
    )
    alert_row_id = await db.insert_alert(
        ticker="TSLA", confidence=20.0, catalyst="", catalyst_type="",
        consensus_json="{}", technical_json="{}", analysts_json="[]", price=200.0,
    )

    async def instant_xref(ticker, tweet):
        return _make_xref_result(ticker="TSLA", final_score=30.0)

    async def low_precision(ticker, base_score=0, budget=None):
        return {"classification": SignalClass.IGNORE, "skipped": False, "total_score": 20}

    edit_calls: list = []

    async def capture_edit(msg_id, content, **kw):
        edit_calls.append((msg_id, content))

    tweet = _make_tweet(ticker="TSLA", analyst="CheddarFlow", score=20)

    with patch("consensus_engine.main.cross_reference", side_effect=instant_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=low_precision), \
         patch("consensus_engine.main.edit_instant_ping", capture_edit, create=True):

        await _run_cross_reference_and_followup(
            "TSLA", tweet, "msg_t003", alert_msg_id, alert_row_id
        )

    low_prec_edits = [
        c for c in edit_calls
        if "Phase 2 skipped" in str(c[1]) and "low precision" in str(c[1]).lower()
    ]
    assert low_prec_edits, (
        f"Expected edit with 'Phase 2 skipped — low precision', "
        f"got={edit_calls!r} — RED until Commit D adds skip-message edit"
    )


# ---------------------------------------------------------------------------
# Normal path (baseline: already green, confirms no regression)
# ---------------------------------------------------------------------------

async def test_normal_path_updates_followup_msg_id_in_alert_messages(test_db):
    """When xref + precision succeed on the happy path, followup_msg_id is set."""
    from consensus_engine.main import _run_cross_reference_and_followup
    from consensus_engine.engine import SignalClass
    from consensus_engine import db

    alert_msg_id = await db.insert_alert_message(
        ticker="AAPL", analyst="FlowAlerts",
        instant_msg_id="msg_t004", base_score=80,
    )
    alert_row_id = await db.insert_alert(
        ticker="AAPL", confidence=80.0, catalyst="earnings", catalyst_type="earnings",
        consensus_json="{}", technical_json="{}", analysts_json="[]", price=180.0,
    )

    async def fast_xref(ticker, tweet):
        return _make_xref_result(ticker="AAPL", final_score=85.0)

    async def strong_precision(ticker, base_score=0, budget=None):
        return {
            "classification": SignalClass.STRONG_ALERT,
            "skipped": False,
            "total_score": 85,
        }

    tweet = _make_tweet(ticker="AAPL", analyst="FlowAlerts", score=80)

    with patch("consensus_engine.main.cross_reference", side_effect=fast_xref), \
         patch("consensus_engine.main.analyze_signal", side_effect=strong_precision), \
         patch("consensus_engine.main.send_detail_followup", AsyncMock(return_value="followup_777")):

        await _run_cross_reference_and_followup(
            "AAPL", tweet, "msg_t004", alert_msg_id, alert_row_id
        )

    row = await db.get_alert_message(alert_msg_id)
    assert row["followup_msg_id"] == "followup_777"
