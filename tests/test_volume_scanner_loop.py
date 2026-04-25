"""Tests for Q5: volume_scanner wired into main loop.

Spec: roadmap Q5 — `scanners/volume_scanner.py` exists but was never called from
the main loop. Wire-up adds a periodic background task that ingests breakouts
as `TickerSignal`s with `SourceType.VOLUME_BREAKOUT`.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.models import SourceType
from consensus_engine.scanners.volume_scanner import BreakoutResult


def test_source_type_volume_breakout_exists():
    """SourceType enum must include VOLUME_BREAKOUT."""
    assert SourceType.VOLUME_BREAKOUT.value == "volume_breakout"


@pytest.mark.asyncio
async def test_volume_scanner_loop_ingests_breakouts():
    """Loop should call scan_volume_breakouts and insert each result as a TickerSignal."""
    from consensus_engine import main as engine_main

    breakouts = [
        BreakoutResult(
            ticker="NVDA", current_price=110.0, prev_close=100.0,
            price_change_pct=10.0, volume=500000, avg_volume=50000, rvol=10.0,
        ),
        BreakoutResult(
            ticker="AMD", current_price=200.0, prev_close=190.0,
            price_change_pct=5.26, volume=300000, avg_volume=40000, rvol=7.5,
        ),
    ]

    inserted = []

    async def fake_insert(signal):
        inserted.append(signal)

    stop_event = asyncio.Event()
    with patch(
        "consensus_engine.main.scan_volume_breakouts",
        new_callable=AsyncMock,
        return_value=breakouts,
    ), patch("consensus_engine.main.db.insert_signal", side_effect=fake_insert), \
         patch("consensus_engine.main.cfg.get") as mock_cfg:
        mock_cfg.side_effect = lambda key, default=None: {
            "volume_scanner.enabled": True,
            "volume_scanner.scan_interval": 0.05,
        }.get(key, default)

        async def runner():
            await asyncio.sleep(0.15)
            stop_event.set()

        await asyncio.gather(
            engine_main.volume_scanner_loop(stop_event),
            runner(),
        )

    assert len(inserted) >= 2
    nvda = next((s for s in inserted if s.ticker == "NVDA"), None)
    assert nvda is not None
    assert nvda.source_type == SourceType.VOLUME_BREAKOUT
    assert "10.0x" in nvda.source_detail or "RVOL" in nvda.source_detail


@pytest.mark.asyncio
async def test_volume_scanner_loop_disabled_returns_immediately():
    """If volume_scanner.enabled=False, loop must exit without scanning."""
    from consensus_engine import main as engine_main

    stop_event = asyncio.Event()
    with patch(
        "consensus_engine.main.scan_volume_breakouts",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_scan, patch("consensus_engine.main.cfg.get") as mock_cfg:
        mock_cfg.side_effect = lambda key, default=None: {
            "volume_scanner.enabled": False,
        }.get(key, default)

        await asyncio.wait_for(
            engine_main.volume_scanner_loop(stop_event), timeout=0.5,
        )
        mock_scan.assert_not_called()
