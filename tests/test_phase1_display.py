"""Phase-1 display features (signal-features-2026-06-09) — flag-ON dedicated tests.

Each test forces its OWN flag in-body (the conftest autouse fixture forces the
same flags OFF for the rest of the suite; the in-body patch wins for that key).

Covers:
  - I9  : raising alerts.min_base_score_for_alert suppresses a tweet that
          passes at the default 20.
  - I4-display-honesty: a budget-depressed run renders "confidence degraded:
          budget" and never the higher additive number; flag-OFF is byte-identical.
  - I14-display: cold-start regime renders "regime: warming up".
"""
import pytest

import consensus_engine.config as cfg
from consensus_engine.main import _passes_quality_gate
from consensus_engine.models import (
    ParsedTweet, TweetType, Direction, Conviction,
    CrossReferenceResult, ScoreBreakdown,
)
from consensus_engine.engine import SignalClass
from consensus_engine.analysis.regime import RegimeContext
from consensus_engine.alerts.discord import format_detail_followup


def _force(monkeypatch, overrides: dict):
    """Force specific config keys in-body; delegate everything else to the real get."""
    real = cfg.get

    def _patched(key, default=None):
        if key in overrides:
            return overrides[key]
        return real(key, default)

    monkeypatch.setattr(cfg, "get", _patched)


def _make_parsed(direction=Direction.LONG, conviction=Conviction.MEDIUM):
    return ParsedTweet(
        tweet_url="https://x.com/test/123",
        analyst="test_analyst",
        raw_text="Buying NVDA here, looks like a great multi-week setup",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=direction,
        options=None,
        conviction=conviction,
        summary="test",
    )


# ---------------------------------------------------------------------------
# I9 — alerts.min_base_score_for_alert is now a live knob
# ---------------------------------------------------------------------------

def test_i9_raised_knob_suppresses(monkeypatch):
    """A MEDIUM/LONG tweet (effective score 25) passes at the default 20 but is
    suppressed once the knob is raised above its score."""
    tweet = _make_parsed(direction=Direction.LONG, conviction=Conviction.MEDIUM)
    assert tweet.base_score == 25

    # default knob (20): passes
    _force(monkeypatch, {"alerts.min_base_score_for_alert": 20})
    assert _passes_quality_gate(tweet, "NVDA") is True

    # raised knob (26 > 25): suppressed
    _force(monkeypatch, {"alerts.min_base_score_for_alert": 26})
    assert _passes_quality_gate(tweet, "NVDA") is False


def test_i9_neutral_discount_still_explicit(monkeypatch):
    """The −5 neutral discount stays explicit: a MEDIUM/NEUTRAL tweet (25−5=20)
    passes at 20 but is suppressed at 25."""
    tweet = _make_parsed(direction=Direction.NEUTRAL, conviction=Conviction.MEDIUM)
    _force(monkeypatch, {"alerts.min_base_score_for_alert": 20})
    assert _passes_quality_gate(tweet, "NVDA") is True
    _force(monkeypatch, {"alerts.min_base_score_for_alert": 25})
    assert _passes_quality_gate(tweet, "NVDA") is False


# ---------------------------------------------------------------------------
# I4-display-honesty
# ---------------------------------------------------------------------------

def _xref():
    # raw additive total = 30+40+15+10+10 = 105 (inflated vs the gated precision number)
    breakdown = ScoreBreakdown(
        base=30, additional_analysts=40, news_catalyst=15,
        social_apewisdom=10, social_stocktwits=10,
    )
    return CrossReferenceResult(
        ticker="NVDA", breakdown=breakdown,
        catalyst_summary="", catalyst_type="",
    )


def test_i4_display_off_is_byte_identical():
    """Flag OFF (conftest force-off) → legacy headline shows the raw additive
    sum and no degraded annotation."""
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 58,
        "market_ok": True,
        "has_mainstream": True,
        "regime": None,
        "skipped_sources": ["serpapi_queries"],
    }
    embed = format_detail_followup(xref, precision)
    assert "Score: 105" in embed["title"]
    assert "confidence degraded" not in embed["title"]
    assert "confidence degraded" not in str(embed["fields"])


def test_i4_display_budget_depressed_renders_degraded(monkeypatch):
    """Flag ON + a skipped paid source → render the gated number and an explicit
    'confidence degraded: budget' state, never the higher additive number."""
    _force(monkeypatch, {"features.score_display_honesty.enabled": True})
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 58,
        "market_ok": True,
        "has_mainstream": True,
        "regime": None,
        "skipped_sources": ["serpapi_queries"],  # budget-depressed
    }
    embed = format_detail_followup(xref, precision)
    # gated number (58), never the inflated 105
    assert "Score: 58" in embed["title"]
    assert "105" not in embed["title"]
    # explicit degraded state
    assert "confidence degraded: budget" in embed["title"]
    assert "confidence degraded: budget" in str(embed["fields"])


def test_i4_display_no_strong_with_sub_medium(monkeypatch):
    """Flag ON: a STRONG class never renders a sub-medium (65) number — the
    displayed number is floored to the medium threshold so it can't contradict
    the class."""
    _force(monkeypatch, {"features.score_display_honesty.enabled": True})
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.STRONG_ALERT,
        "total_score": 58,  # would be a "STRONG, 58" contradiction
        "market_ok": True,
        "has_mainstream": True,
        "regime": None,
        "skipped_sources": [],  # not budget-depressed
    }
    embed = format_detail_followup(xref, precision)
    assert "Score: 65" in embed["title"]
    assert "Score: 58" not in embed["title"]
    assert "confidence degraded" not in embed["title"]


# ---------------------------------------------------------------------------
# I14-display — regime risk-context line
# ---------------------------------------------------------------------------

def test_i14_display_off_no_regime_field():
    """Flag OFF (conftest force-off) → no Regime field added."""
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 58,
        "market_ok": True,
        "has_mainstream": True,
        "regime": RegimeContext(
            label="elevated", z_score=0.8, threshold_shift=5,
            cold_start=False, as_of_date="2026-06-09",
        ),
        "skipped_sources": [],
    }
    embed = format_detail_followup(xref, precision)
    names = [f["name"] for f in embed["fields"]]
    assert "Regime" not in names


def test_i14_display_cold_start_warming_up(monkeypatch):
    """Flag ON + cold-start regime → 'regime: warming up' (no implied protection)."""
    _force(monkeypatch, {"features.regime_context_line.enabled": True})
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 58,
        "market_ok": True,
        "has_mainstream": True,
        "regime": RegimeContext(
            label="normal", z_score=0.0, threshold_shift=0,
            cold_start=True, as_of_date="",
        ),
        "skipped_sources": [],
    }
    embed = format_detail_followup(xref, precision)
    regime_field = next(f for f in embed["fields"] if f["name"] == "Regime")
    assert "warming up" in regime_field["value"]
    assert "elevated" not in regime_field["value"]


def test_i14_display_elevated_renders_label_no_z(monkeypatch):
    """Flag ON + a real regime → '🟡 Market stress: 60/100 (elevated)'.

    #46: the line is reframed onto a 0-100 'market stress' scale. The native
    z-score was trimmed (2026-06-26, user request) — it's unreadable at a glance
    and the 0-100 stress number already conveys it. Label kept, z removed.
    """
    _force(monkeypatch, {"features.regime_context_line.enabled": True})
    xref = _xref()
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 58,
        "market_ok": True,
        "has_mainstream": True,
        "regime": RegimeContext(
            label="elevated", z_score=0.8, threshold_shift=5,
            cold_start=False, as_of_date="2026-06-09",
        ),
        "skipped_sources": [],
    }
    embed = format_detail_followup(xref, precision)
    regime_field = next(f for f in embed["fields"] if f["name"] == "Regime")
    assert "elevated" in regime_field["value"]
    assert "z=" not in regime_field["value"]   # z trimmed 2026-06-26 (user request)
    # #46: reframed onto the unified 0-100 market-stress scale.
    assert "Market stress" in regime_field["value"]
    assert "/100" in regime_field["value"]
