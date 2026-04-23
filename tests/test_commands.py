"""Tests for Discord command routing."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_route_help_command():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("help", [], "chan123", "msg123")
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]  # third positional arg is content
        assert "!scan" in content
        assert "!status" in content


@pytest.mark.asyncio
async def test_route_unknown_command():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("foobar", [], "chan123", "msg123")
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]
        assert "Unknown command" in content


@pytest.mark.asyncio
async def test_parse_command_from_message():
    from consensus_engine.alerts.commands import parse_command
    cmd, args = parse_command("!scan NVDA")
    assert cmd == "scan"
    assert args == ["NVDA"]

    cmd2, args2 = parse_command("!help")
    assert cmd2 == "help"
    assert args2 == []

    # Non-command returns None
    result = parse_command("just a regular message")
    assert result is None


@pytest.mark.asyncio
async def test_route_scan_requires_ticker():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("scan", [], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "Usage" in content or "ticker" in content.lower()


@pytest.mark.asyncio
async def test_route_scan_with_ticker_dispatches_task():
    """!scan NVDA fires a background task and sends initial reply."""
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.asyncio") as mock_asyncio:
        captured = []
        def _capture_task(coro):
            captured.append(coro)
            return MagicMock()
        mock_asyncio.create_task = _capture_task
        await route_command("scan", ["NVDA"], "chan123", "msg123")
        # Should send initial "Scanning..." reply
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]
        assert "NVDA" in content or "Scanning" in content
        # Should fire a background task
        assert len(captured) == 1
        # Close the coroutine to avoid ResourceWarning
        captured[0].close()


@pytest.mark.asyncio
async def test_handle_trend_success_sends_confirmation():
    """!trend sends confirmation reply on success."""
    from consensus_engine.alerts.commands import route_command
    mock_trending = [{"ticker": "NVDA", "mentions": 10, "unique_authors": 5, "momentum": 2.0}]
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.crawl_and_get_trending", new_callable=AsyncMock, return_value=mock_trending) as mock_crawl, \
         patch("consensus_engine.alerts.commands.send_trend_digest", new_callable=AsyncMock) as mock_digest:
        await route_command("trend", [], "chan123", "msg123")
        # Should call crawl
        mock_crawl.assert_called_once()
        # Should post digest
        mock_digest.assert_called_once_with(mock_trending)
        # Should send confirmation reply (last call)
        calls = mock_send.call_args_list
        assert len(calls) == 2  # "Running..." + confirmation
        last_content = calls[-1][0][2]
        assert "posted" in last_content.lower() or "found" in last_content.lower()


@pytest.mark.asyncio
async def test_handle_trend_empty_sends_no_results():
    """!trend with no tickers sends appropriate message."""
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.crawl_and_get_trending", new_callable=AsyncMock, return_value=[]):
        await route_command("trend", [], "chan123", "msg123")
        # Last reply should mention no results
        last_content = mock_send.call_args_list[-1][0][2]
        assert "no trending" in last_content.lower() or "not found" in last_content.lower()


@pytest.mark.asyncio
async def test_route_market_view_requires_ticker():
    """!market-view with no args sends usage hint."""
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("market-view", [], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "Usage" in content or "TICKER" in content.upper()


@pytest.mark.asyncio
async def test_route_market_view_no_snapshot():
    """!market-view NVDA when no snapshots exist replies gracefully."""
    from consensus_engine.alerts.commands import route_command
    mock_db = MagicMock()
    mock_db.get_recent_decision_snapshots = AsyncMock(return_value=[])

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.db", mock_db):
        await route_command("market-view", ["NVDA"], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "NVDA" in content or "snapshot" in content.lower() or "scan" in content.lower()


@pytest.mark.asyncio
async def test_route_market_view_with_snapshot():
    """!market-view NVDA with a snapshot shows verdict and calibrated probability."""
    import time
    from consensus_engine.alerts.commands import route_command

    snapshot = {
        "decision": "ALERT",
        "final_score": 75.0,
        "contradiction_index": 0.1,
        "recorded_at": time.time() - 120,
    }
    mock_db = MagicMock()
    mock_db.get_recent_decision_snapshots = AsyncMock(return_value=[snapshot])

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.db", mock_db):
        await route_command("market-view", ["NVDA"], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "NVDA" in content
        assert "ALERT" in content or "75" in content


@pytest.mark.asyncio
async def test_route_levels_requires_ticker():
    """!levels with no args sends usage hint."""
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("levels", [], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "Usage" in content or "TICKER" in content.upper()


@pytest.mark.asyncio
async def test_route_levels_no_data():
    """!levels NVDA with no youtube_levels replies gracefully."""
    from consensus_engine.alerts.commands import route_command
    mock_db = MagicMock()
    mock_db.get_youtube_levels_for_ticker = AsyncMock(return_value=[])

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.db", mock_db):
        await route_command("levels", ["NVDA"], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "NVDA" in content or "level" in content.lower() or "found" in content.lower()


@pytest.mark.asyncio
async def test_route_levels_with_data():
    """!levels NVDA with data shows price levels with condition text."""
    from consensus_engine.alerts.commands import route_command

    levels = [
        {
            "level_type": "support",
            "price": 875.50,
            "confidence": 0.9,
            "condition_text": "holds above 875",
            "consequence_text": "rally to 920",
            "channel_name": "TraderChannel",
        },
        {
            "level_type": "resistance",
            "price": 920.00,
            "confidence": 0.7,
            "condition_text": "breaks above 920",
            "consequence_text": "squeeze to 950",
            "channel_name": "TraderChannel",
        },
    ]
    mock_db = MagicMock()
    mock_db.get_youtube_levels_for_ticker = AsyncMock(return_value=levels)

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.db", mock_db):
        await route_command("levels", ["NVDA"], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "875" in content
        assert "920" in content
        assert "holds above" in content.lower() or "875" in content


@pytest.mark.asyncio
async def test_format_youtube_option_summary_call():
    """_format_youtube_option_summary renders ticker, type, strike, expiry."""
    from consensus_engine.alerts.commands import _format_youtube_option_summary
    opt = {
        "ticker": "TSLA", "option_type": "call", "strike": 250.0,
        "expiry": "2026-05-16", "source": "flow_observation",
    }
    result = _format_youtube_option_summary(opt)
    assert "TSLA" in result
    assert "CALL" in result.upper()
    assert "250" in result


@pytest.mark.asyncio
async def test_format_youtube_setup_summary_basic():
    """_format_youtube_setup_summary renders ticker, entry, stop, target."""
    from consensus_engine.alerts.commands import _format_youtube_setup_summary
    import json
    setup = {
        "ticker": "NVDA", "entry_low": 800.0, "entry_high": 810.0,
        "stop_price": 790.0, "targets_json": json.dumps([850.0, 900.0]),
        "risk_reward": 3.0,
    }
    result = _format_youtube_setup_summary(setup)
    assert "NVDA" in result
    assert "800" in result
    assert "790" in result


def test_format_ts_helper():
    from consensus_engine.alerts.commands import _format_ts
    assert _format_ts(0) == "0:00"
    assert _format_ts(59) == "0:59"
    assert _format_ts(2142) == "35:42"
    assert _format_ts(3723) == "1:02:03"
    assert _format_ts(None) == ""


def test_format_verified_helper():
    from consensus_engine.alerts.commands import _format_verified
    assert _format_verified(1) == "✓"
    assert _format_verified(0) == "?"
    assert _format_verified(-1) == "⚠"
    assert _format_verified(None) == "?"


def test_format_youtube_setup_summary_with_timestamp_and_catalyst():
    from consensus_engine.alerts.commands import _format_youtube_setup_summary
    from consensus_engine.models import VideoTradeSetup
    s = VideoTradeSetup(
        ticker="MSFT", entry_low=400.0, entry_high=400.0, stop=389.0,
        targets=[420.0], timeframe="swing", setup_type="breakout",
        context="", source_snippet="", chunk_id=0, risk_reward=2.0,
        video_timestamp_sec=2142, catalyst_date="2026-04-29", catalyst_desc="earnings",
    )
    out = _format_youtube_setup_summary(s)
    assert "35:42" in out
    assert "2026-04-29" in out
    assert "earnings" in out


@pytest.mark.asyncio
async def test_yt_analyse_reply_two_stage_path(monkeypatch):
    """_yt_analyse_and_reply uses the evidence-first pipeline when use_two_stage=True."""
    from consensus_engine import config as cfg
    from consensus_engine.alerts.commands import _yt_analyse_and_reply
    from consensus_engine.analysis.video_classifier import ClassificationResult
    from consensus_engine.models import (
        EvidenceBundle, EvidenceSpan, CandidateSignal, CandidateLevel,
        CandidateCatalyst, Direction, Conviction, MacroThesis, RunTelemetry,
    )

    cfg.load_config()
    monkeypatch.setitem(cfg._config["youtube"], "use_two_stage", True)

    bundle = EvidenceBundle(
        video_id="vidY2", duration_sec=300, publish_ts="2026-04-17T12:00:00Z",
        segments=[{"ts_start_sec": 60, "title": "Intro"}],
        spans=[EvidenceSpan(ts_sec=120, quote="MSFT bullish", tickers=["MSFT"],
                            numbers=[400.0], dates_mentioned=["April 29"])],
    )
    result = ClassificationResult(
        signals=[CandidateSignal(
            ticker="MSFT", direction=Direction.LONG, conviction=Conviction.HIGH,
            mention_count=2, context="bullish", classifier_confidence=0.8,
            video_timestamp_sec=120,
        )],
        levels=[CandidateLevel(
            ticker="MSFT", level_type="support", price=400.0,
            context="support at 400", classifier_confidence=0.9,
            video_timestamp_sec=120,
        )],
        setups=[],
        catalyst_candidates=[],
        macro_thesis=MacroThesis(
            direction=Direction.LONG, themes=[], timeframe="short",
            summary="bull market", narrative="bullish on tech",
        ),
    )
    catalysts = [CandidateCatalyst(
        ticker="MSFT", catalyst_type="earnings", mentioned_date="April 29",
        resolved_date="2026-04-29", verified=1,
    )]

    mock_resp = MagicMock()
    mock_resp.status = 404
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_sess = MagicMock()
    mock_sess.get = MagicMock(return_value=mock_resp)
    mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_sess.__aexit__ = AsyncMock(return_value=False)

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("aiohttp.ClientSession", return_value=mock_sess), \
         patch("consensus_engine.utils.transcript_fetch.parse_video_id", return_value="vidY2"), \
         patch("consensus_engine.analysis.gemini_video_parser.extract_evidence_with_gemini",
               new=AsyncMock(return_value=(bundle, RunTelemetry(json_parse_ok=True, span_count=1)))), \
         patch("consensus_engine.analysis.video_classifier.classify_evidence", return_value=result), \
         patch("consensus_engine.analysis.catalyst_resolver.resolve_and_verify_catalysts",
               new=AsyncMock(return_value=catalysts)):
        await _yt_analyse_and_reply("https://youtu.be/vidY2", "chan1", "msg1")

    reply = mock_send.call_args_list[-1][0][2]
    assert "MSFT" in reply
    # Timestamped outline
    assert "[1:00] Intro" in reply
    # Macro thesis
    assert "BULLISH" in reply
    # Verified catalyst
    assert "2026-04-29" in reply and "✓" in reply
    # Level with mm:ss
    assert "SUPPORT MSFT" in reply
    assert "2:00" in reply


@pytest.mark.asyncio
async def test_yt_analyse_reply_includes_setups_and_options():
    """_yt_analyse_and_reply shows setups and options sections when parsed."""
    from consensus_engine.alerts.commands import _yt_analyse_and_reply
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction,
        VideoOptionIdea, VideoTradeSetup,
    )

    opt = VideoOptionIdea(
        ticker="TSLA", option_type="call", strike=250.0, expiry="2026-05-16",
        strategy="single", source="flow_observation", conviction="high",
        context="big sweep", source_snippet="250c", chunk_id=0,
    )
    setup = VideoTradeSetup(
        ticker="NVDA", entry_low=800.0, entry_high=810.0, stop=790.0,
        targets=[850.0], timeframe="swing", setup_type="breakout",
        context="breakout", source_snippet="buy 800-810", chunk_id=0,
    )
    mock_parsed = ParsedVideo(
        video_id="vidZ", channel_name="TestChan", raw_transcript="",
        tickers=[],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary="test macro"),
        overall_conviction=Conviction.MEDIUM,
        run_id=1, options=[opt], setups=[setup],
    )

    # Mock aiohttp.ClientSession so oEmbed doesn't make real HTTP calls
    mock_resp = MagicMock()
    mock_resp.status = 404  # force oEmbed fallback (title = video_id, channel = "unknown")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_sess = MagicMock()
    mock_sess.get = MagicMock(return_value=mock_resp)
    mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_sess.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.has_video_been_processed = AsyncMock(return_value=False)

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.alerts.commands.db", mock_db), \
         patch("aiohttp.ClientSession", return_value=mock_sess), \
         patch("consensus_engine.utils.transcript_fetch.parse_video_id", return_value="vidZ"), \
         patch("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade", new_callable=AsyncMock, return_value=("transcript text", "en", False)), \
         patch("consensus_engine.analysis.video_parser.parse_video_transcript", new_callable=AsyncMock, return_value=mock_parsed):
        await _yt_analyse_and_reply("https://youtu.be/vidZ", "chan1", "msg1")

    all_calls = "\n".join(str(c) for c in mock_send.call_args_list)
    assert "TSLA" in all_calls or "250" in all_calls
    assert "NVDA" in all_calls or "800" in all_calls
