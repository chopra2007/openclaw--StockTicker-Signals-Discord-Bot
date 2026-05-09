"""PR1 — synthesis LLM timeout floor + ceiling.

v1 capped synthesis at `max(1, min(15, deadline))` (narrator.py:271). The
primary model needs ~78s in isolated tests (R8 measurement). v2 raises the
ceiling to 50s and the floor to 15s so a tight remaining budget never
aborts the call before the FALLBACK 1 model (ring-2.6-1t at ~14s) can
respond.
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

    async def fake_call(*, role, messages, max_tokens, temperature, timeout):
        captured["timeout"] = timeout
        return ""

    with patch.object(narrator, "call_with_fallback", new=fake_call):
        asyncio.run(narrator._invoke_synthesis([{"role": "user", "content": "x"}], deadline_seconds))

    assert captured["timeout"] >= 15, (
        f"deadline={deadline_seconds}s -> timeout={captured['timeout']}s; "
        "must be >=15 so ring-2.6-1t (14s in R8) can respond"
    )


def test_synthesize_timeout_ceiling_is_50s():
    """Even with a huge remaining deadline, timeout caps at 50s."""
    captured: dict = {}

    async def fake_call(*, role, messages, max_tokens, temperature, timeout):
        captured["timeout"] = timeout
        return ""

    with patch.object(narrator, "call_with_fallback", new=fake_call):
        asyncio.run(narrator._invoke_synthesis([{"role": "user", "content": "x"}], 200))

    assert captured["timeout"] <= 50, (
        f"deadline=200s -> timeout={captured['timeout']}s; "
        "must be <=50 to keep total !all wall-clock under 80s"
    )
