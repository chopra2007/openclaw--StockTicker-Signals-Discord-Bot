from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.alerts.discord import format_detail_followup, format_instant_ping
from consensus_engine.alerts.short_interest_display import (
    is_squeeze_candidate,
    render_squeeze_candidate,
)
from consensus_engine.models import (
    Conviction,
    CrossReferenceResult,
    Direction,
    ParsedTweet,
    ScoreBreakdown,
    TweetType,
)


NOW = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)
MAX_AGE = timedelta(days=30)


def _row(**overrides):
    row = {
        "ticker": "ABCD",
        "settlement_date": "2026-07-31",
        "short_interest": 112_000,
        "prev_short_interest": 100_000,
        "days_to_cover": 4.2,
        "pct_change": 12.0,
        "published_at": NOW.timestamp() - 86400,
    }
    row.update(overrides)
    return row


def _xref(row=None):
    return CrossReferenceResult(
        ticker="ABCD",
        breakdown=ScoreBreakdown(base=30),
        catalyst_summary="",
        catalyst_type="",
        short_interest_row=row,
    )


def test_eligibility_qualifies():
    assert is_squeeze_candidate(_row(), NOW, MAX_AGE, 3.0, True)


def test_eligibility_fails_days_to_cover():
    assert not is_squeeze_candidate(_row(days_to_cover=2.9), NOW, MAX_AGE, 3.0, True)


def test_eligibility_fails_not_rising():
    assert not is_squeeze_candidate(
        _row(short_interest=99_999), NOW, MAX_AGE, 3.0, True
    )


def test_eligibility_fails_missing_prior():
    assert not is_squeeze_candidate(
        _row(prev_short_interest=None), NOW, MAX_AGE, 3.0, True
    )


def test_eligibility_fails_stale_row():
    assert not is_squeeze_candidate(
        _row(published_at=(NOW - timedelta(days=31)).timestamp()),
        NOW, MAX_AGE, 3.0, True,
    )


def test_eligibility_fails_missing_row():
    assert not is_squeeze_candidate(None, NOW, MAX_AGE, 3.0, True)


def test_render_uses_only_numbers_and_date_from_row():
    line = render_squeeze_candidate(_row(), NOW, MAX_AGE, 3.0, True)
    assert line == (
        "🩳 Squeeze candidate — 4.2 days to cover (about four normal trading days "
        "for short-sellers to buy back), short interest up 12.0% from the prior report. "
        "Latest report: 2026-07-31."
    )


def test_flag_off_suppresses_qualifying_card(monkeypatch):
    real_get = cfg.get
    monkeypatch.setattr(
        cfg,
        "get",
        lambda key, default=None: False
        if key == "features.short_interest.squeeze_tag"
        else real_get(key, default),
    )
    embed = format_detail_followup(_xref(_row()))
    assert "Squeeze candidate" not in str(embed)


def test_nonqualifying_card_is_byte_identical_with_flag_on_or_off(monkeypatch):
    xref = _xref(_row(days_to_cover=2.0))
    real_get = cfg.get
    with patch("consensus_engine.alerts.discord.datetime") as clock:
        clock.now.return_value = NOW
        on = format_detail_followup(xref)
        monkeypatch.setattr(
            cfg,
            "get",
            lambda key, default=None: False
            if key == "features.short_interest.squeeze_tag"
            else real_get(key, default),
        )
        off = format_detail_followup(xref)
    assert on == off


def test_instant_ping_never_contains_squeeze_line():
    tweet = ParsedTweet(
        tweet_url="https://example.test/tweet",
        analyst="tester",
        raw_text="ABCD long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["ABCD"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="ABCD long",
    )
    assert "Squeeze candidate" not in str(format_instant_ping(tweet))
