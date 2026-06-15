"""Tests for conversational ticker anchoring (TODO #35).

The chat lane must NOT reuse the scanner BLACKLIST (which blocks SPY/QQQ/GAP). It
anchors real companies, soft-anchors slang homographs (WEN), and skips grammar words
unless the user is explicit ($-prefixed).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine.utils import tickers

# canned "company database" — what Finnhub/cache would return
_COMPANIES = {
    "WEN": {"name": "Wendy's Co", "exchange": "NASDAQ", "market_cap": 2e9},
    "APP": {"name": "Applovin Corp", "exchange": "NASDAQ", "market_cap": 1e11},
    "GAP": {"name": "Gap Inc", "exchange": "NYSE", "market_cap": 8e9},
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE ARCA", "market_cap": 0},
    "QQQ": {"name": "Invesco QQQ Trust", "exchange": "NASDAQ", "market_cap": 0},
    "NVDA": {"name": "NVIDIA Corp", "exchange": "NASDAQ", "market_cap": 3e12},
    "ALL": {"name": "Allstate Corp", "exchange": "NYSE", "market_cap": 5e10},
    "IT": {"name": "Gartner Inc", "exchange": "NYSE", "market_cap": 4e10},
}


@pytest.fixture(autouse=True)
def _mock_resolution(monkeypatch):
    async def fake_meta(ticker, max_age_days=7):
        return _COMPANIES.get(ticker)
    async def fake_validate(ticker):
        return False  # never hit the network in tests
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "get_ticker_metadata", fake_meta, raising=False)
    monkeypatch.setattr(tickers, "validate_ticker_market_cap", fake_validate)


async def _syms(text):
    return {a["symbol"]: a for a in await tickers.resolve_chat_ticker_anchors(text)}


async def test_real_etfs_and_homograph_stocks_anchor():
    # SPY/QQQ/GAP/APP are blocked by the scanner blacklist but ARE valid chat questions
    got = await _syms("how's SPY and QQQ doing, and what about GAP and APP")
    assert {"SPY", "QQQ", "GAP", "APP"} <= set(got)
    assert all(not got[s]["soft"] for s in ("SPY", "QQQ", "GAP", "APP"))  # hard anchors


async def test_wen_soft_anchors_headline_case():
    # the #35 headline: "tell me about WEN" (no finance keyword) -> Wendy's, soft/advisory
    got = await _syms("tell me about WEN")
    assert "WEN" in got and got["WEN"]["soft"] and got["WEN"]["name"] == "Wendy's Co"


async def test_wen_soft_anchor_is_advisory_even_for_slang():
    # "WEN moon?" still anchors but SOFTLY (advisory) — the phrasing handles the crypto case
    got = await _syms("WEN moon")
    assert "WEN" in got and got["WEN"]["soft"]


async def test_tech_acronym_not_anchored_as_topic_word(monkeypatch):
    # "AI" is a topic word, not a ticker, in normal chat -> no anchor without $
    _COMPANIES["AI"] = {"name": "C3.ai Inc", "exchange": "NYSE", "market_cap": 3e9}
    got = await _syms("do you think AI will keep winning")
    assert "AI" not in got
    got2 = await _syms("what about $AI")     # explicit -> anchors
    assert "AI" in got2
    del _COMPANIES["AI"]


async def test_grammar_word_not_anchored_without_dollar():
    # "is that ALL" / "what about IT" must NOT become Allstate / Gartner
    got = await _syms("is that ALL, and what about IT")
    assert "ALL" not in got and "IT" not in got


async def test_grammar_word_anchored_with_dollar():
    got = await _syms("what's the latest on $ALL")
    assert "ALL" in got and got["ALL"]["name"] == "Allstate Corp"


async def test_unknown_token_not_anchored():
    got = await _syms("tell me about ZZZZ stock")   # resolves to no company
    assert "ZZZZ" not in got


async def test_cap_limits_anchor_count():
    anchors = await tickers.resolve_chat_ticker_anchors(
        "NVDA SPY QQQ GAP APP WEN $ALL", cap=3)
    assert len(anchors) == 3


def test_format_anchor_hard_vs_soft():
    out = tickers.format_ticker_anchor([
        {"symbol": "GAP", "name": "Gap Inc", "exchange": "NYSE", "soft": False},
        {"symbol": "WEN", "name": "Wendy's Co", "exchange": "NASDAQ", "soft": True},
    ])
    assert "GAP = Gap Inc, NYSE" in out
    assert "WEN = IF the user means a stock" in out and "Wendy's Co" in out


def test_format_anchor_empty():
    assert tickers.format_ticker_anchor([]) == ""
