"""Tests for the deterministic earnings-date answer (consensus_engine/alerts/earnings_answer.py).

Covers the URI bug: an unconfirmed earnings date (analyst estimate only) must
produce a short, hedged, correct answer instead of a fabricated one.
"""

from datetime import date

import pytest

from consensus_engine.alerts import earnings_answer as ea


# --- intent detection -------------------------------------------------------

@pytest.mark.parametrize("text", [
    "when are earnings for URI?",
    "URI earnings date",
    "when does F report earnings",
    "next earnings for MRK",
    "when is TLRY's earnings report",
])
def test_is_earnings_date_query_positive(text):
    assert ea.is_earnings_date_query(text) is True


@pytest.mark.parametrize("text", [
    "what were MRK's last earnings",          # history, not date
    "how did TLRY earnings go",               # results, not date
    "what's the expected move for F earnings",  # !em territory
    "how much did URI earnings beat by",      # results
    "what's the weather in NYC",              # no earnings at all
    "",                                       # empty
])
def test_is_earnings_date_query_negative(text):
    assert ea.is_earnings_date_query(text) is False


# --- answer formatting ------------------------------------------------------

def test_format_unconfirmed_single_date_hedges():
    outlook = {"ticker": "URI", "dates": [date(2026, 7, 22)], "days_until": 27}
    msg = ea.format_earnings_answer(outlook, name="United Rentals Inc")
    assert "United Rentals Inc (URI)" in msg
    assert "hasn't officially confirmed" in msg
    assert "Analysts expect it around" in msg
    assert "Jul" in msg and "22" in msg and "2026" in msg
    # short, no tool names leaked, no misleading EPS artifact
    assert "fetch_next_earnings" not in msg
    assert "EPS" not in msg
    assert "\n" not in msg


def test_format_near_term_drops_estimate_language():
    outlook = {"ticker": "NVDA", "dates": [date(2026, 8, 27)], "days_until": 3}
    msg = ea.format_earnings_answer(outlook, name="NVIDIA Corp")
    assert "reports earnings on" in msg
    assert "analyst calendar" in msg


def test_format_date_range_window():
    outlook = {"ticker": "F", "dates": [date(2026, 7, 22), date(2026, 7, 29)],
               "days_until": 27}
    msg = ea.format_earnings_answer(outlook)
    assert msg.startswith("📅 **F**")  # no name → ticker only
    assert "between" in msg
    assert "Jul" in msg and "22" in msg and "29" in msg


# --- yfinance fetch logic (mocked) ------------------------------------------

class _FakeTicker:
    def __init__(self, calendar=None, earnings_df=None):
        self._calendar = calendar
        self._df = earnings_df

    @property
    def calendar(self):
        if self._calendar is None:
            raise RuntimeError("no calendar")
        return self._calendar

    def get_earnings_dates(self, limit=12):
        return self._df


@pytest.mark.asyncio
async def test_fetch_outlook_from_calendar(monkeypatch):
    import yfinance
    cal = {"Earnings Date": [date(2099, 7, 22)], "Earnings Average": 11.5}
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(calendar=cal))
    out = await ea.fetch_earnings_outlook("URI")
    assert out is not None
    assert out["ticker"] == "URI"
    assert out["dates"] == [date(2099, 7, 22)]


@pytest.mark.asyncio
async def test_fetch_outlook_past_only_returns_none(monkeypatch):
    import yfinance
    cal = {"Earnings Date": [date(2000, 1, 1)], "Earnings Average": 1.0}
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(calendar=cal))
    out = await ea.fetch_earnings_outlook("URI")
    assert out is None


@pytest.mark.asyncio
async def test_fetch_outlook_falls_back_to_get_earnings_dates(monkeypatch):
    import yfinance
    import pandas as pd
    df = pd.DataFrame(
        {"EPS Estimate": [11.57, 8.94], "Reported EPS": [float("nan"), 9.71]},
        index=pd.to_datetime(["2099-07-22 16:00:00", "2026-04-22 16:00:00"]),
    )
    # calendar=None → property raises → get_earnings_dates supplies the date
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(calendar=None, earnings_df=df))
    out = await ea.fetch_earnings_outlook("URI")
    assert out is not None
    assert out["dates"] == [date(2099, 7, 22)]


@pytest.mark.asyncio
async def test_fetch_outlook_stale_calendar_uses_get_earnings_dates(monkeypatch):
    """The TLRY case: calendar holds a past date; the real upcoming date is in
    get_earnings_dates and must win."""
    import yfinance
    import pandas as pd
    cal = {"Earnings Date": [date(2000, 1, 1)]}  # stale past date
    df = pd.DataFrame(
        {"EPS Estimate": [float("nan")], "Reported EPS": [float("nan")]},
        index=pd.to_datetime(["2099-07-28 08:00:00"]),
    )
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(calendar=cal, earnings_df=df))
    out = await ea.fetch_earnings_outlook("TLRY")
    assert out is not None
    assert out["dates"] == [date(2099, 7, 28)]


@pytest.mark.asyncio
async def test_fetch_outlook_calendar_window(monkeypatch):
    """Two future calendar dates → an estimate window."""
    import yfinance
    cal = {"Earnings Date": [date(2099, 7, 22), date(2099, 7, 29)]}
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(calendar=cal))
    out = await ea.fetch_earnings_outlook("X")
    assert out["dates"] == [date(2099, 7, 22), date(2099, 7, 29)]


# --- end-to-end intercept (mocked deps) -------------------------------------

@pytest.mark.asyncio
async def test_maybe_answer_non_earnings_returns_false(monkeypatch):
    sent = []
    import consensus_engine.alerts.discord as disc
    async def _rec(c, m, t): sent.append(t)
    monkeypatch.setattr(disc, "send_command_reply", _rec)
    handled = await ea.maybe_answer_earnings("what's NVDA's price", "c", "m")
    assert handled is False
    assert sent == []


@pytest.mark.asyncio
async def test_maybe_answer_posts_earnings_reply(monkeypatch):
    sent = []
    import consensus_engine.alerts.discord as disc
    async def _rec(c, m, t): sent.append(t)
    monkeypatch.setattr(disc, "send_command_reply", _rec)

    async def _fake_resolve(text): return "URI", "United Rentals Inc"
    async def _fake_outlook(sym):
        return {"ticker": "URI", "dates": [date(2026, 7, 22)], "days_until": 27}
    monkeypatch.setattr(ea, "_resolve_ticker", _fake_resolve)
    monkeypatch.setattr(ea, "fetch_earnings_outlook", _fake_outlook)

    handled = await ea.maybe_answer_earnings("when are earnings for URI?", "c", "m")
    assert handled is True
    assert len(sent) == 1
    assert "United Rentals Inc (URI)" in sent[0]
    assert "Analysts expect it around" in sent[0]


@pytest.mark.asyncio
async def test_resolve_single_letter_ticker(monkeypatch):
    """A lone 'F' the shared resolver misses is picked up and named."""
    import consensus_engine.utils.tickers as tk
    async def _empty(text, cap=3): return []
    monkeypatch.setattr(tk, "resolve_chat_ticker_anchors", _empty)
    async def _name(sym): return "Ford Motor Co" if sym == "F" else None
    monkeypatch.setattr(ea, "_company_name", _name)

    sym, name = await ea._resolve_ticker("when are earnings for F?")
    assert sym == "F"
    assert name == "Ford Motor Co"


@pytest.mark.asyncio
async def test_resolve_skips_grammar_single_letter(monkeypatch):
    """'I' is a grammar word, never treated as a ticker."""
    import consensus_engine.utils.tickers as tk
    async def _empty(text, cap=3): return []
    monkeypatch.setattr(tk, "resolve_chat_ticker_anchors", _empty)
    looked_up = []
    async def _name(sym): looked_up.append(sym); return None
    monkeypatch.setattr(ea, "_company_name", _name)

    sym, name = await ea._resolve_ticker("when are earnings for I?")
    assert sym is None
    assert "I" not in looked_up


@pytest.mark.asyncio
async def test_maybe_answer_no_date_owns_reply(monkeypatch):
    """Ticker resolves but no date found → we still answer (never fabricate)."""
    sent = []
    import consensus_engine.alerts.discord as disc
    async def _rec(c, m, t): sent.append(t)
    monkeypatch.setattr(disc, "send_command_reply", _rec)

    async def _fake_resolve(text): return "ZZZZ", "Zeta Corp"
    async def _fake_outlook(sym): return None
    monkeypatch.setattr(ea, "_resolve_ticker", _fake_resolve)
    monkeypatch.setattr(ea, "fetch_earnings_outlook", _fake_outlook)

    handled = await ea.maybe_answer_earnings("when are earnings for ZZZZ?", "c", "m")
    assert handled is True
    assert len(sent) == 1
    assert "couldn't find" in sent[0]


@pytest.mark.asyncio
async def test_maybe_answer_no_ticker_falls_through(monkeypatch):
    async def _fake_resolve(text): return None, None
    monkeypatch.setattr(ea, "_resolve_ticker", _fake_resolve)
    handled = await ea.maybe_answer_earnings("when are earnings season this quarter?", "c", "m")
    assert handled is False
