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
        mock_asyncio.create_task = MagicMock()
        await route_command("scan", ["NVDA"], "chan123", "msg123")
        # Should send initial "Scanning..." reply
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]
        assert "NVDA" in content or "Scanning" in content
        # Should fire a background task
        mock_asyncio.create_task.assert_called_once()


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
