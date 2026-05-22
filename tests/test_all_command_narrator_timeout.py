"""Synthesis LLM timeout floor + ceiling.

narrator._invoke_synthesis clamps the per-model synthesis timeout to
`max(15, min(90, deadline_seconds))` — a 15s floor so a tight remaining
budget never aborts the call outright, and a 90s ceiling because a
free-tier model needs ~70s for the real synthesis prompt (probed
2026-05-21: gpt-oss-120b = 70.7s on a 4.5K-token prompt).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts.all_command import narrator


@pytest.mark.parametrize("deadline_seconds", [5, 10, 30, 100])
def test_synthesize_timeout_floor_is_15s(deadline_seconds):
    """For any deadline_seconds, the synthesis call must get timeout >= 15s."""
    captured: dict = {}

    async def fake_call(*, role, messages, max_tokens, temperature, timeout,
                        chain=None):
        captured["timeout"] = timeout
        return ""

    with patch.object(narrator, "call_with_fallback", new=fake_call):
        asyncio.run(narrator._invoke_synthesis([{"role": "user", "content": "x"}], deadline_seconds))

    assert captured["timeout"] >= 15, (
        f"deadline={deadline_seconds}s -> timeout={captured['timeout']}s; "
        "must be >=15 so a tight remaining budget never aborts the call outright"
    )


def test_synthesize_timeout_ceiling_is_90s():
    """Even with a huge remaining deadline, timeout caps at 90s."""
    captured: dict = {}

    async def fake_call(*, role, messages, max_tokens, temperature, timeout,
                        chain=None):
        captured["timeout"] = timeout
        return ""

    with patch.object(narrator, "call_with_fallback", new=fake_call):
        asyncio.run(narrator._invoke_synthesis([{"role": "user", "content": "x"}], 200))

    assert captured["timeout"] <= 90, (
        f"deadline=200s -> timeout={captured['timeout']}s; "
        "must be <=90 so a single model can't hang the !all call indefinitely"
    )
