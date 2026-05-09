"""PR5 — youtube_levels parser sanity at insert + select-time filter.

Investigation R2 found NVDA `youtube_levels` rows like $90,451 and $904.51
for a stock trading near $200. The setup-tier alert path already runs
`check_price_plausible` (youtube.py:482-513) and mutates in-memory level
objects, but those mutations don't reach the DB row that was already
inserted. Result: !all's anchor pipeline picks up the corrupt rows and
emits junk SL/TP levels.

PR5 adds the same check at insert time and a SELECT-time filter so future
queries skip suppressed rows.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from types import SimpleNamespace

import pytest

from consensus_engine import config as cfg, db
from consensus_engine.scanners import youtube as yt_scan


@pytest.mark.asyncio
async def test_implausible_price_suppressed_at_insert():
    """Levels with implausible prices vs live quote are marked suppressed=1."""
    levels = [
        SimpleNamespace(ticker="NVDA", price=90451.0, suppressed=0, suppression_reason=None),
        SimpleNamespace(ticker="NVDA", price=210.0,    suppressed=0, suppression_reason=None),
        SimpleNamespace(ticker="NVDA", price=0.50,     suppressed=0, suppression_reason=None),
    ]

    async def fake_live_price(_ticker: str) -> float | None:
        return 200.0  # actual NVDA price band

    await yt_scan._apply_price_sanity_to_levels(
        levels, get_live_price=fake_live_price,
    )

    assert levels[0].suppressed == 1
    assert levels[0].suppression_reason == "price_sanity"
    assert levels[1].suppressed == 0  # $210 vs $200 = within band
    assert levels[1].suppression_reason is None
    # $0.50 vs $200 = 0.25% — way outside any plausible split ratio.
    assert levels[2].suppressed == 1
    assert levels[2].suppression_reason == "price_sanity"


@pytest.mark.asyncio
async def test_existing_suppressed_levels_left_alone():
    """A level already marked suppressed (off-allowlist) is not overwritten."""
    levels = [
        SimpleNamespace(ticker="NVDA", price=90451.0,
                        suppressed=1, suppression_reason="off_allowlist"),
    ]

    async def fake_live_price(_ticker: str) -> float | None:
        return 200.0

    await yt_scan._apply_price_sanity_to_levels(
        levels, get_live_price=fake_live_price,
    )

    assert levels[0].suppressed == 1
    assert levels[0].suppression_reason == "off_allowlist"  # unchanged


@pytest.mark.asyncio
async def test_get_youtube_levels_excludes_suppressed(tmp_path, monkeypatch):
    """SELECT-side filter: get_youtube_levels_for_ticker skips suppressed rows."""
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "yt.db")}
    await db.init_db()
    try:
        # Insert two NVDA levels: one bad (suppressed), one good (not suppressed).
        await db.insert_youtube_level(
            video_id="v_bad", ticker="NVDA", level_type="resistance",
            price=90451.0, channel_name="Bad Parse", published_at="2026-05-01",
            suppressed=1, suppression_reason="price_sanity",
        )
        await db.insert_youtube_level(
            video_id="v_good", ticker="NVDA", level_type="resistance",
            price=210.0, channel_name="Real", published_at="2026-05-08",
            suppressed=0, suppression_reason=None,
        )

        rows = await db.get_youtube_levels_for_ticker("NVDA", days=30)
        prices = sorted(r["price"] for r in rows)
        assert prices == [210.0], (
            f"expected only the unsuppressed $210 row, got {prices}"
        )
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_get_youtube_levels_handles_null_suppressed(tmp_path):
    """Legacy rows pre-PR5 may have suppressed=NULL; still returned."""
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "yt2.db")}
    await db.init_db()
    try:
        # Direct write so we can set suppressed=NULL (insert helper defaults to 0).
        conn = await db.get_db()
        await conn.execute(
            """INSERT INTO youtube_levels
               (video_id, ticker, level_type, price, extracted_at, suppressed)
               VALUES (?, ?, ?, ?, ?, NULL)""",
            ("v_legacy", "AAPL", "support", 175.0, time.time()),
        )
        await conn.commit()

        rows = await db.get_youtube_levels_for_ticker("AAPL", days=30)
        assert len(rows) == 1
        assert rows[0]["price"] == 175.0
    finally:
        await db.close_db()
