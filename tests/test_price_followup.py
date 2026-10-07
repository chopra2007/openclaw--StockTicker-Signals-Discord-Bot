"""Tests for price follow-up tracking."""

import time
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine import db


@pytest.fixture(autouse=True)
async def setup_db(tmp_path,monkeypatch):
    # Session-sensitive selection must not depend on when the test is run.
    now=datetime(2026,10,7,12,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    monkeypatch.setattr(time,'time',lambda:now)
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    await db.init_db()
    yield
    await db.close_db()


async def _insert_alert(ticker: str, price: float, age_seconds: float):
    """Insert an alert with a specific age."""
    conn = await db.get_db()
    alerted_at = time.time() - age_seconds
    await conn.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type, consensus_breakdown,
            technical_data, analyst_mentions, alerted_at, price_at_alert)
           VALUES (?, ?, '', '', '{}', '{}', '[]', ?, ?)""",
        (ticker, 50.0, alerted_at, price),
    )
    await conn.commit()


@pytest.mark.asyncio
async def test_get_alerts_needing_1h_update():
    """Unfilled regular-session hours remain repairable within minute coverage."""
    await _insert_alert("AAPL", 150.0, 4000)   # ~1.1 hours old — should match
    await _insert_alert("TSLA", 200.0, 300)     # 5 min old — too young
    await _insert_alert("NVDA", 500.0, 10000)   # Missed original spot window; historical minute is available.
    await _insert_alert("CLOSED", 10.0, 22*3600) # Yesterday after hours.
    await _insert_alert("OLD", 10.0, 31*86400+4000) # Outside bounded minute coverage.

    alerts = await db.get_alerts_needing_price_update("price_1h_later")
    tickers = [a["ticker"] for a in alerts]
    assert "AAPL" in tickers
    assert "TSLA" not in tickers
    assert "NVDA" in tickers
    assert "CLOSED" not in tickers
    assert "OLD" not in tickers


@pytest.mark.asyncio
async def test_get_alerts_needing_24h_update():
    """Alerts 24-48 hours old with NULL price_24h_later should be returned."""
    await _insert_alert("MSFT", 400.0, 90000)   # ~25 hours old — should match
    await _insert_alert("GOOG", 170.0, 3600)    # 1 hour old — too young
    await _insert_alert("META", 500.0, 200000)  # ~55 hours old — too old

    alerts = await db.get_alerts_needing_price_update("price_24h_later")
    tickers = [a["ticker"] for a in alerts]
    assert "MSFT" in tickers
    assert "GOOG" not in tickers
    assert "META" not in tickers


@pytest.mark.asyncio
async def test_update_alert_price():
    """Should update the price field on an alert."""
    await _insert_alert("AAPL", 150.0, 4000)

    alerts = await db.get_alerts_needing_price_update("price_1h_later")
    assert len(alerts) == 1

    await db.update_alert_price(alerts[0]["id"], "price_1h_later", 155.0)

    # Should no longer appear as needing update
    alerts_after = await db.get_alerts_needing_price_update("price_1h_later")
    assert len(alerts_after) == 0

    # Verify the value was stored
    conn = await db.get_db()
    cursor = await conn.execute("SELECT price_1h_later FROM alert_history WHERE id = ?", (alerts[0]["id"],))
    row = await cursor.fetchone()
    assert row["price_1h_later"] == 155.0


@pytest.mark.asyncio
async def test_invalid_field_rejected():
    """Invalid field names should be rejected."""
    alerts = await db.get_alerts_needing_price_update("invalid_field")
    assert alerts == []
    # Should not raise
    await db.update_alert_price(1, "invalid_field", 100.0)
