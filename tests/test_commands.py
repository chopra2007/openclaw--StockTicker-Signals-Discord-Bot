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
