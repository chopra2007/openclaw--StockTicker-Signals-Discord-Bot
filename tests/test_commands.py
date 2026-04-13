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
