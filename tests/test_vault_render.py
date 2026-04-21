# tests/test_vault_render.py
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from consensus_engine.research import vault


def test_render_ticker_markdown_includes_sections_and_freshness():
    now = 1700000000.0
    sections = {
        "analyst": {"content": "bullish tone", "status": "ok", "last_good_at": now, "fetched_at": now},
        "sec": {"content": None, "last_good_content": "Q4 beat", "status": "failed",
                "last_good_at": now - 3600, "fetched_at": now},
        "news": {"content": "top stories", "status": "ok", "last_good_at": now, "fetched_at": now},
    }
    md = vault.render_ticker_markdown("NVDA", sections)
    assert md.startswith("# NVDA Research Note")
    assert "Analyst Signals" in md
    assert "bullish tone" in md
    # SEC falls back to last_good_content and marks stale
    assert "Q4 beat" in md
    assert "stale" in md.lower() or "last-good" in md.lower()
    assert "top stories" in md


async def test_write_ticker_vault_atomic_rename(tmp_path):
    sections = {
        "analyst": {"content": "x", "status": "ok", "last_good_at": 1.0, "fetched_at": 1.0},
    }
    await vault.write_ticker_vault("NVDA", sections, str(tmp_path))
    expected = tmp_path / "tickers" / "NVDA.md"
    assert expected.exists()
    content = expected.read_text()
    assert "NVDA" in content
    # No temp file left behind
    assert not (tmp_path / "tickers" / "NVDA.md.tmp").exists()
