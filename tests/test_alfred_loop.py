import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from consensus_engine.briefing import alfred


def test_in_post_window():
    assert alfred._in_post_window(datetime(2026, 4, 21, 8, 55, tzinfo=ZoneInfo("America/New_York")),
                                  ["08:50", "09:00"])
    assert not alfred._in_post_window(datetime(2026, 4, 21, 9, 30, tzinfo=ZoneInfo("America/New_York")),
                                      ["08:50", "09:00"])


async def test_loop_exits_when_disabled(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: False if k == "alfred.enabled" else default)
    stop = asyncio.Event()
    # Should return quickly without blocking
    await asyncio.wait_for(alfred.alfred_loop(stop), timeout=2.0)
