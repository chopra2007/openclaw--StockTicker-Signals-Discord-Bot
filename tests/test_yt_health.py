"""Tests for !yt-health and !yt-evidence observability commands (Phase P8)."""
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg, db


@pytest.fixture(autouse=True)
def _config():
    cfg.load_config()


@pytest.fixture
async def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_yt_health.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    await db.init_db()
    yield
    await db.close_db()


# --- !yt-health -------------------------------------------------------------


@pytest.mark.asyncio
async def test_yt_health_empty(tmp_db):
    """No runs in window → handler renders zeros without crashing."""
    from consensus_engine.alerts import commands as cmd
    sent = []
    async def fake_reply(channel_id, message_id, text):
        sent.append(text)
    with patch.object(cmd, "send_command_reply", side_effect=fake_reply):
        await cmd._handle_yt_health("c1", "m1")
    assert sent, "Expected a reply"
    reply = sent[0]
    assert "YouTube Pipeline Health" in reply
    assert "Videos analyzed: 0" in reply
    assert "Parse-ok: 0.0%" in reply


@pytest.mark.asyncio
async def test_yt_health_with_data(tmp_db):
    """Insert 3 synthetic runs, handler should report 3 and token sums."""
    conn = await db.get_db()
    now = time.time()
    # Three runs, two with parse_ok=1, one with parse_ok=0
    for i, (ok, in_tok, out_tok, lat, spans, dropped) in enumerate([
        (1, 1000,  200,  1500, 8,  2),
        (1, 1500,  300,  2000, 10, 1),
        (0, 500,   100,  900,  0,  5),
    ]):
        await conn.execute(
            """INSERT INTO youtube_analysis_runs
               (video_id, parser_version, status, started_at,
                input_tokens, output_tokens, latency_ms, json_parse_ok,
                span_count, filter_drop_count)
               VALUES (?, 'v2', 'complete', ?, ?, ?, ?, ?, ?, ?)""",
            (f"vid_{i}", now, in_tok, out_tok, lat, ok, spans, dropped),
        )
    # And a youtube_signals row for top-channels aggregation
    await conn.execute(
        """INSERT INTO youtube_signals
           (video_id, channel_name, ticker, direction, conviction,
            parsed_at, extracted_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("vid_0", "CheddarFlow", "MSFT", "long", "high", now, now),
    )
    await conn.commit()

    from consensus_engine.alerts import commands as cmd
    sent = []
    async def fake_reply(channel_id, message_id, text):
        sent.append(text)
    with patch.object(cmd, "send_command_reply", side_effect=fake_reply):
        await cmd._handle_yt_health("c1", "m1")
    reply = sent[0]
    assert "Videos analyzed: 3" in reply
    assert "Parse-ok: 66.7%" in reply
    # token totals: in=3000, out=600
    assert "in 3,000" in reply
    assert "out 600" in reply
    # suppression count
    assert "Candidates suppressed: 8" in reply
    # top channel
    assert "CheddarFlow (1)" in reply


# --- !yt-evidence -----------------------------------------------------------


@pytest.mark.asyncio
async def test_yt_evidence_lists_spans(tmp_db):
    """Insert spans, handler reply contains the quote."""
    run_id = await db.create_analysis_run("vidEV1", "v2")
    await db.insert_youtube_evidence_span(
        run_id=run_id, video_id="vidEV1", ts_sec=65,
        quote="MSFT earnings next Wednesday",
        tickers=["MSFT"], numbers=[], dates=["next Wednesday"],
    )
    await db.insert_youtube_evidence_span(
        run_id=run_id, video_id="vidEV1", ts_sec=125,
        quote="Support at 400 on the daily",
        tickers=["MSFT"], numbers=[400.0], dates=[],
    )

    from consensus_engine.alerts import commands as cmd
    sent = []
    async def fake_reply(channel_id, message_id, text):
        sent.append(text)
    with patch.object(cmd, "send_command_reply", side_effect=fake_reply):
        await cmd._handle_yt_evidence("vidEV1", "c1", "m1")
    reply = sent[0]
    assert "Evidence spans for `vidEV1`" in reply
    assert "MSFT earnings next Wednesday" in reply
    assert "Support at 400 on the daily" in reply
    # timestamps rendered mm:ss
    assert "01:05" in reply  # 65s
    assert "02:05" in reply  # 125s


@pytest.mark.asyncio
async def test_yt_evidence_empty(tmp_db):
    from consensus_engine.alerts import commands as cmd
    sent = []
    async def fake_reply(channel_id, message_id, text):
        sent.append(text)
    with patch.object(cmd, "send_command_reply", side_effect=fake_reply):
        await cmd._handle_yt_evidence("no_such_vid", "c1", "m1")
    assert "No evidence spans" in sent[0]


# --- dispatch wiring --------------------------------------------------------


@pytest.mark.asyncio
async def test_route_yt_health_dispatches(tmp_db):
    from consensus_engine.alerts import commands as cmd
    with patch.object(cmd, "_handle_yt_health", new=AsyncMock()) as h:
        await cmd.route_command("yt-health", [], "c1", "m1")
        h.assert_awaited_once_with("c1", "m1")


@pytest.mark.asyncio
async def test_route_yt_evidence_requires_video_id(tmp_db):
    from consensus_engine.alerts import commands as cmd
    sent = []
    async def fake_reply(channel_id, message_id, text):
        sent.append(text)
    with patch.object(cmd, "send_command_reply", side_effect=fake_reply):
        await cmd.route_command("yt-evidence", [], "c1", "m1")
    assert "Usage: `!yt-evidence" in sent[0]
