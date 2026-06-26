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


def test_format_confirmed_date_is_definite():
    outlook = {"ticker": "MRK", "dates": [date(2026, 8, 4)],
               "days_until": 40, "confirmed": True}
    msg = ea.format_earnings_answer(outlook, name="Merck & Co Inc")
    assert "is scheduled to report earnings on" in msg
    assert "hasn't officially confirmed" not in msg  # not hedged — it IS confirmed
    assert "Aug" in msg and "4" in msg and "2026" in msg


def test_format_date_range_window():
    outlook = {"ticker": "F", "dates": [date(2026, 7, 22), date(2026, 7, 29)],
               "days_until": 27, "confirmed": False}
    msg = ea.format_earnings_answer(outlook)
    assert msg.startswith("📅 **F**")  # no name → ticker only
    assert "between" in msg
    assert "Jul" in msg and "22" in msg and "29" in msg


# --- yfinance fetch logic (mocked) ------------------------------------------

class _FakeData:
    """Stands in for yfinance Ticker._data — returns a quoteSummary-shaped dict."""
    def __init__(self, dates_fmt, is_estimate):
        self._dates_fmt = dates_fmt
        self._is_estimate = is_estimate

    def get_raw_json(self, url, params=None):
        return {"quoteSummary": {"result": [{"calendarEvents": {"earnings": {
            "earningsDate": [{"fmt": f} for f in self._dates_fmt],
            "isEarningsDateEstimate": self._is_estimate,
        }}}]}}


class _FakeTicker:
    def __init__(self, qs=None, earnings_df=None):
        # qs = (list_of_fmt_strings, is_estimate) or None to simulate a failure
        self._data = _FakeData(*qs) if qs is not None else None
        self._df = earnings_df

    def get_earnings_dates(self, limit=12):
        return self._df


@pytest.mark.asyncio
async def test_fetch_outlook_confirmed(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=(["2099-08-04"], False)))
    out = await ea.fetch_earnings_outlook("MRK")
    assert out is not None
    assert out["dates"] == [date(2099, 8, 4)]
    assert out["confirmed"] is True


@pytest.mark.asyncio
async def test_fetch_outlook_estimate(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=(["2099-07-22"], True)))
    out = await ea.fetch_earnings_outlook("URI")
    assert out["dates"] == [date(2099, 7, 22)]
    assert out["confirmed"] is False


@pytest.mark.asyncio
async def test_fetch_outlook_past_only_returns_none(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=(["2000-01-01"], False)))
    out = await ea.fetch_earnings_outlook("URI")
    assert out is None


@pytest.mark.asyncio
async def test_fetch_outlook_stale_quotesummary_uses_get_earnings_dates(monkeypatch):
    """The TLRY case: quoteSummary holds a past confirmed date; the real upcoming
    date is only in get_earnings_dates and must win — and stays hedged."""
    import yfinance
    import pandas as pd
    df = pd.DataFrame(
        {"EPS Estimate": [float("nan")], "Reported EPS": [float("nan")]},
        index=pd.to_datetime(["2099-07-28 08:00:00"]),
    )
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=(["2000-01-01"], False), earnings_df=df))
    out = await ea.fetch_earnings_outlook("TLRY")
    assert out is not None
    assert out["dates"] == [date(2099, 7, 28)]
    assert out["confirmed"] is False  # date came from get_earnings_dates → hedge


@pytest.mark.asyncio
async def test_fetch_outlook_quotesummary_fails_falls_back(monkeypatch):
    """quoteSummary unavailable → date still comes from get_earnings_dates, hedged."""
    import yfinance
    import pandas as pd
    df = pd.DataFrame(
        {"EPS Estimate": [float("nan")], "Reported EPS": [float("nan")]},
        index=pd.to_datetime(["2099-07-22 16:00:00"]),
    )
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=None, earnings_df=df))
    out = await ea.fetch_earnings_outlook("URI")
    assert out["dates"] == [date(2099, 7, 22)]
    assert out["confirmed"] is False


@pytest.mark.asyncio
async def test_fetch_outlook_window(monkeypatch):
    """Two future quoteSummary dates → an estimate window, never confirmed."""
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker",
                        lambda t: _FakeTicker(qs=(["2099-07-22", "2099-07-29"], True)))
    out = await ea.fetch_earnings_outlook("X")
    assert out["dates"] == [date(2099, 7, 22), date(2099, 7, 29)]
    assert out["confirmed"] is False


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
