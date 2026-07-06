"""Tests for the #63 merged detailed card.

The user REJECTED the earlier stripped-down "decision-first" card and instead
kept the FULL detailed follow-up, with two additions behind ONE flag
(alerts.merged_detail_card.enabled, default ON in prod, forced OFF in tests via
conftest):

  1. A "📐 Trade Levels" field on the detailed card (ATR-derived stop/target).
  2. Merge the instant ping INTO the one self-editing detailed card, preserving
     the analyst identity, the tweet text, and the TweetShift source link.

Flag OFF (conftest default) → every existing render is byte-identical; these
tests flip the flag ON explicitly (like tests/test_i13_apewisdom_zscore.py).
"""
from consensus_engine import config as cfg
from consensus_engine.models import (
    CrossReferenceResult, ScoreBreakdown, TechnicalResult,
    ParsedTweet, TweetType, Direction, Conviction,
)
from consensus_engine.alerts.discord import (
    format_detail_followup, format_instant_ping, format_merged_card,
)


def _flag_on(monkeypatch):
    """Force alerts.merged_detail_card.enabled ON; all other flags stay default."""
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: True if k == "alerts.merged_detail_card.enabled"
        else real_get(k, d),
    )


def _xref_with_atr():
    """A cross-reference result whose technical snapshot carries a real ATR stop."""
    breakdown = ScoreBreakdown(base=30, news_catalyst=15)
    tech = TechnicalResult(ticker="NVDA", filters=[], price=200.0, atr14=5.0)
    return CrossReferenceResult(
        ticker="NVDA", breakdown=breakdown,
        catalyst_summary="PT raised", catalyst_type="Analyst Upgrade",
        technical=tech, other_analysts=[], social_summary="", llm_reasoning="",
    )


def _tweet():
    return ParsedTweet(
        tweet_url="https://twitter.com/bigshort/status/123",
        analyst="bigshort",
        raw_text="NVDA breaking out, PT to 250, long calls here",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA long",
        display_name="Big Short",
        discord_source_link="https://discord.com/channels/1/2/3",
    )


# --- Flag OFF (conftest default) — byte-identical legacy render ----------------

def test_flag_off_no_trade_levels_field():
    """Flag OFF: the detailed follow-up has NO '📐 Trade Levels' field."""
    embed = format_detail_followup(_xref_with_atr())
    assert not any(f["name"] == "📐 Trade Levels" for f in embed["fields"])


def test_flag_off_instant_ping_score_unchanged():
    """Flag OFF: the instant ping Score field still shows the pending-cross-ref text."""
    embed = format_instant_ping(_tweet())
    score = next(f for f in embed["fields"] if f["name"] == "Score")
    assert "cross-references pending" in score["value"]


# --- Flag ON — the two additions + neutralized ping score ----------------------

def test_flag_on_trade_levels_field_present(monkeypatch):
    """Flag ON + atr14>0: the detailed follow-up gains a '📐 Trade Levels' field
    containing a Stop."""
    _flag_on(monkeypatch)
    embed = format_detail_followup(_xref_with_atr(), direction=Direction.LONG)
    tl = next((f for f in embed["fields"] if f["name"] == "📐 Trade Levels"), None)
    assert tl is not None
    assert "Stop" in tl["value"]


def test_flag_on_instant_ping_score_neutralized(monkeypatch):
    """Flag ON: the instant ping Score field carries no number (no premature
    '25 vs 83' contradiction before the in-place edit lands)."""
    _flag_on(monkeypatch)
    embed = format_instant_ping(_tweet())
    score = next(f for f in embed["fields"] if f["name"] == "Score")
    assert score["value"] == "⏳ cross-referencing sources…"


def test_merged_card_preserves_tweet_and_source(monkeypatch):
    """format_merged_card carries the analyst identity, the tweet text, and the
    TweetShift source link onto the detailed card."""
    _flag_on(monkeypatch)
    tweet = _tweet()
    embed = format_merged_card(_xref_with_atr(), tweet)
    assert tweet.raw_text[:20] in embed["description"]
    assert embed["author"]["name"] == "Big Short"
    source = next((f for f in embed["fields"] if f["name"] == "Source"), None)
    assert source is not None
    assert tweet.discord_source_link in source["value"]
