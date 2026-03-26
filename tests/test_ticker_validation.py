"""Tests for ticker validation and noise filtering."""
import pytest
from consensus_engine.utils.tickers import extract_tickers, is_valid_ticker, BLACKLIST


def test_common_words_blacklisted():
    """Words from the log noise should all be blacklisted."""
    noise_tickers = [
        "AAA", "BBC", "CIA", "CO", "CD", "BE", "BK", "CF", "BDC",
        "BNO", "AL", "AM", "ATR", "BA", "BATL", "CC", "CL",
        "CORN", "CAN", "CBOE",
    ]
    for t in noise_tickers:
        assert t in BLACKLIST, f"{t} should be blacklisted"


def test_real_tickers_not_blacklisted():
    """Real traded tickers should NOT be in the blacklist."""
    real_tickers = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOGL", "AMZN", "META"]
    for t in real_tickers:
        assert t not in BLACKLIST, f"{t} should NOT be blacklisted"


def test_extract_tickers_filters_noise():
    """Extract should not return known noise words."""
    text = "The BBC reported that AM trading was BE quiet. Also CIA filed a CO report."
    tickers = extract_tickers(text)
    assert "BBC" not in tickers
    assert "AM" not in tickers
    assert "BE" not in tickers
    assert "CIA" not in tickers
    assert "CO" not in tickers


def test_extract_tickers_finds_real():
    text = "$NVDA breaking out, $TSLA also running"
    tickers = extract_tickers(text)
    assert "NVDA" in tickers
    assert "TSLA" in tickers


@pytest.mark.asyncio
async def test_validate_ticker_market_cap(tmp_path):
    """Market cap filter should reject tiny/nonexistent tickers."""
    from consensus_engine.utils.tickers import validate_ticker_market_cap
    from consensus_engine import db, config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2}
    await db.init_db()

    await db.cache_ticker_metadata("NVDA", "NVIDIA", 2.8e12, "NASDAQ")
    result = await validate_ticker_market_cap("NVDA")
    assert result is True

    await db.cache_ticker_metadata("TINY", "Tiny Corp", 50e6, "OTC")
    result = await validate_ticker_market_cap("TINY")
    assert result is False

    await db.close_db()
