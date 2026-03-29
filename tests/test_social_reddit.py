"""Tests for Reddit JSON API scanner."""
import pytest
from consensus_engine.scanners.social import _parse_reddit_json
from consensus_engine.models import SourceType


def test_parse_reddit_json_extracts_tickers():
    reddit_response = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "$NVDA is about to break out, loading calls",
                        "selftext": "massive volume on NVDA today",
                        "subreddit": "wallstreetbets",
                    }
                },
                {
                    "data": {
                        "title": "What do you think about the market?",
                        "selftext": "I'm not sure what to buy",
                        "subreddit": "wallstreetbets",
                    }
                },
                {
                    "data": {
                        "title": "$TSLA puts printing",
                        "selftext": "",
                        "subreddit": "wallstreetbets",
                    }
                },
            ]
        }
    }
    signals = _parse_reddit_json(reddit_response, "wallstreetbets")
    tickers = [s.ticker for s in signals]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert all(s.source_type == SourceType.REDDIT for s in signals)


def test_parse_reddit_json_empty():
    signals = _parse_reddit_json({"data": {"children": []}}, "test")
    assert signals == []


def test_parse_reddit_json_missing_data():
    signals = _parse_reddit_json({}, "test")
    assert signals == []
