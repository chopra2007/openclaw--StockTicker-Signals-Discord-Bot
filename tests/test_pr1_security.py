"""PR1 security infrastructure tests.

Covers:
  - _safe_send_kwargs adds allowed_mentions={"parse":[]} by default
  - _safe_send_kwargs preserves a caller-supplied allowed_mentions
  - rate_limiter has an "openrouter" bucket pinned to 60/min (1.0s interval)
  - route_command rejects invalid ticker BEFORE dispatching the handler
  - route_command accepts a valid ticker and dispatches to the handler
"""
import pytest
from unittest.mock import AsyncMock, patch


def test_safe_send_kwargs_adds_allowed_mentions():
    from consensus_engine.alerts.discord import _safe_send_kwargs
    out = _safe_send_kwargs({"content": "hello"})
    assert out["allowed_mentions"] == {"parse": []}
    assert out["content"] == "hello"


def test_safe_send_kwargs_preserves_existing():
    """If caller already set allowed_mentions, helper must not overwrite it."""
    from consensus_engine.alerts.discord import _safe_send_kwargs
    custom = {"parse": ["users"], "users": ["12345"]}
    out = _safe_send_kwargs({"content": "ping", "allowed_mentions": custom})
    assert out["allowed_mentions"] == custom


def test_openrouter_rate_limit_present():
    """rate_limiter must expose an openrouter bucket at 1.0s (60/min)."""
    from consensus_engine.utils.rate_limiter import rate_limiter
    assert "openrouter" in rate_limiter._min_intervals
    assert rate_limiter._min_intervals["openrouter"] == 1.0


@pytest.mark.asyncio
async def test_route_command_rejects_invalid_ticker():
    """route_command must reject INVALID!@# without dispatching _handle_scan."""
    from consensus_engine.alerts import commands
    with patch.object(commands, "send_command_reply", new_callable=AsyncMock) as mock_reply, \
         patch.object(commands, "_handle_scan", new_callable=AsyncMock) as mock_handle:
        await commands.route_command("scan", ["INVALID!@#"], "chan", "msg")
        mock_handle.assert_not_called()
        mock_reply.assert_called_once()
        body = mock_reply.call_args[0][2]
        assert "Invalid ticker" in body


@pytest.mark.asyncio
async def test_route_command_accepts_valid_ticker():
    """route_command must dispatch _handle_scan for a clean NVDA arg."""
    from consensus_engine.alerts import commands
    with patch.object(commands, "send_command_reply", new_callable=AsyncMock), \
         patch.object(commands, "_handle_scan", new_callable=AsyncMock) as mock_handle:
        await commands.route_command("scan", ["NVDA"], "chan", "msg")
        mock_handle.assert_called_once()
        # _handle_scan(ticker, channel_id, message_id)
        assert mock_handle.call_args[0][0] == "NVDA"
