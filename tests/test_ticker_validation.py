"""Tests for ticker validation and noise filtering."""
import pytest
from consensus_engine.utils.tickers import (
    BLACKLIST, extract_tickers, is_valid_ticker, is_valid_ticker_format,
)


# ---------------------------------------------------------------------------
# is_valid_ticker_format — used by explicit user commands (!all, !scan, etc.)
# Skips the BLACKLIST so users can ask about ETFs like SPY/QQQ that the
# strict extraction filter intentionally suppresses.
# ---------------------------------------------------------------------------


def test_format_accepts_blacklisted_tickers_users_might_command():
    """User explicitly types '!all SPY' — accept it. The BLACKLIST is for
    text-extraction false-positive suppression, not for command rejection."""
    assert is_valid_ticker_format("SPY") is True
    assert is_valid_ticker_format("QQQ") is True
    # And strict is_valid_ticker still rejects them — extraction semantics unchanged
    assert is_valid_ticker("SPY") is False
    assert is_valid_ticker("QQQ") is False


def test_format_rejects_bad_format():
    """Format-only check still rejects: empty, lowercase, mixed case,
    digits, too short (none — empty), too long, non-alpha."""
    assert is_valid_ticker_format("") is False
    assert is_valid_ticker_format("nvda") is False     # lowercase
    assert is_valid_ticker_format("Nvda") is False     # mixed case
    assert is_valid_ticker_format("NVDA1") is False    # contains digit
    assert is_valid_ticker_format("TOOLONG") is False  # 7 chars > 5
    assert is_valid_ticker_format("AB-C") is False     # hyphen


def test_format_accepts_normal_tickers():
    assert is_valid_ticker_format("NVDA") is True
    assert is_valid_ticker_format("TSLA") is True
    assert is_valid_ticker_format("F") is True       # single-letter ticker
    assert is_valid_ticker_format("GOOGL") is True   # 5 chars (max)



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


def test_technical_indicators_blacklisted():
    """Technical indicator names should be blacklisted to prevent false alerts."""
    indicators = ["RSI", "EMA", "MACD", "VWAP", "SMA", "RVOL", "ADX", "MFI", "OBV", "CCI", "DMI", "DOJI", "BOLL"]
    for t in indicators:
        assert t in BLACKLIST, f"Indicator {t} should be blacklisted"


def test_extract_tickers_ignores_indicators():
    """Indicator names in text should not be extracted as tickers."""
    assert extract_tickers("RSI oversold on NVDA") == {"NVDA"}
    assert extract_tickers("MACD crossover on AAPL") == {"AAPL"}
    assert extract_tickers("EMA death cross on TSLA") == {"TSLA"}
    assert extract_tickers("VWAP reclaim") == set()


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


@pytest.mark.asyncio
async def test_has_market_cap_calls_validator(tmp_path):
    """Regression: _has_market_cap had a typo'd import that silently fail-opened
    every ticker. This test ensures the import chain reaches the real validator."""
    from consensus_engine.scanners.social import _has_market_cap
    from consensus_engine import db, config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2}
    await db.init_db()

    await db.cache_ticker_metadata("BIG", "Big Corp", 5e11, "NASDAQ")
    assert await _has_market_cap("BIG") is True

    await db.cache_ticker_metadata("SML", "Small Co", 1e6, "OTC")
    assert await _has_market_cap("SML") is False

    await db.close_db()
