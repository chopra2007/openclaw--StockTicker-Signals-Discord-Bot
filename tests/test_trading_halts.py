"""Tests for the r14 Nasdaq/NYSE trading-halt tripwire.

Covers:
  - parsing a CAPTURED real feed sample (no network),
  - PDT-only alert rendering (never Eastern),
  - idempotent dedup: one alert per distinct halt, NO re-alert on re-poll,
  - cooldown gating.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from consensus_engine import db
from consensus_engine.scanners import trading_halts as th

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "nasdaq_trade_halts_sample.xml")
_ET = ZoneInfo("America/New_York")


def _load_sample() -> str:
    with open(_FIXTURE, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- parse

def test_parse_captured_feed():
    halts = th._parse_halts_feed(_load_sample())
    assert halts, "captured sample should yield halts"
    syms = {h["symbol"] for h in halts}
    # The captured sample includes these real tracked-ish symbols.
    assert {"PHOE", "NCT", "APMI"} <= syms
    for h in halts:
        # halt_ts must never be empty — it is the dedup identity key.
        assert h["halt_ts"]
        assert h["reason_code"]  # every real row carries a reason code
        assert isinstance(h["halt_dt"], datetime)


def test_parse_ticker_filter():
    halts = th._parse_halts_feed(_load_sample(), tickers={"PHOE"})
    assert halts
    assert all(h["symbol"] == "PHOE" for h in halts)


def test_parse_empty_resumption_is_none():
    # A halt with a self-closing (empty) resumption time -> resumption_dt None.
    xml = """<rss xmlns:ndaq="http://www.nasdaqtrader.com/"><channel>
      <item>
        <ndaq:HaltDate>07/07/2026</ndaq:HaltDate>
        <ndaq:HaltTime>13:07:57.466</ndaq:HaltTime>
        <ndaq:IssueSymbol>ZZZZ</ndaq:IssueSymbol>
        <ndaq:Market>NASDAQ</ndaq:Market>
        <ndaq:ReasonCode>T1</ndaq:ReasonCode>
        <ndaq:ResumptionDate />
        <ndaq:ResumptionTradeTime />
      </item></channel></rss>"""
    halts = th._parse_halts_feed(xml)
    assert len(halts) == 1
    assert halts[0]["resumption_dt"] is None
    assert halts[0]["resumption_ts"] is None


# --------------------------------------------------------------------------- render

def test_format_alert_is_pdt_never_eastern():
    halt = {
        "symbol": "PHOE",
        "market": "NASDAQ",
        "reason_code": "LUDP",
        "halt_dt": datetime(2026, 7, 7, 13, 7, 57, tzinfo=_ET),       # 10:07 AM PDT
        "resumption_dt": datetime(2026, 7, 7, 13, 17, 57, tzinfo=_ET),  # 10:17 AM PDT
        "halt_ts": "07/07/2026|13:07:57.466",
        "resumption_ts": "07/07/2026|13:17:57",
    }
    msg = th.format_halt_alert(halt)
    assert "$PHOE" in msg
    assert "Volatility Trading Pause (LUDP)" in msg  # LUDP label + raw code
    assert "10:07 AM PDT" in msg
    assert "10:17 AM PDT" in msg
    # HARD RULE: never surface Eastern.
    assert "Eastern" not in msg
    assert "EDT" not in msg
    assert "EST" not in msg


def test_format_alert_unknown_code_shows_raw():
    halt = {"symbol": "APMI", "market": "NASDAQ", "reason_code": "M",
            "halt_dt": None, "resumption_dt": None,
            "halt_ts": "x", "resumption_ts": None}
    msg = th.format_halt_alert(halt)
    assert "$APMI" in msg
    assert "M" in msg           # raw code preserved
    assert "Resumes: TBD" in msg  # no resumption -> TBD, never a fabricated time


# ------------------------------------------------------------------------- hardening

def test_validate_url():
    assert th._validate_url("http://www.nasdaqtrader.com/rss.aspx?feed=tradehalts")
    assert th._validate_url("https://nasdaqtrader.com/x")
    assert not th._validate_url("http://evil.com/nasdaqtrader.com")
    assert not th._validate_url("http://nasdaqtrader.com.evil.com/x")


# ------------------------------------------------------------------------------ dedup

@pytest.mark.asyncio
async def test_dedup_one_alert_per_halt_no_realert_on_repoll():
    """The core requirement: one alert per distinct halt, and re-polling the SAME
    feed produces ZERO new alerts (idempotent via the trading_halts table)."""
    await db.get_db()  # init temp DB (conftest _isolate_db) with the trading_halts table
    halts = th._parse_halts_feed(_load_sample())
    tracked = {"PHOE", "NCT", "APMI"}

    sent: list[str] = []

    async def fake_post(text: str):
        sent.append(text)

    # First poll: every distinct tracked halt alerts exactly once.
    alerted = await th.process_new_halts(halts, tracked, fake_post)
    # Distinct (symbol, halt_ts, reason_code) tracked halts in the sample.
    distinct = {(h["symbol"], h["halt_ts"], h["reason_code"])
                for h in halts if h["symbol"] in tracked}
    assert len(alerted) == len(distinct)
    assert len(sent) == len(distinct)
    assert set(alerted) <= tracked

    # Second poll of the SAME feed: no re-alert.
    sent.clear()
    alerted2 = await th.process_new_halts(halts, tracked, fake_post)
    assert alerted2 == []
    assert sent == []


@pytest.mark.asyncio
async def test_untracked_tickers_never_alert():
    await db.get_db()
    halts = th._parse_halts_feed(_load_sample())
    sent = []

    async def fake_post(text):
        sent.append(text)

    alerted = await th.process_new_halts(halts, {"NOSUCHTICKER"}, fake_post)
    assert alerted == []
    assert sent == []


@pytest.mark.asyncio
async def test_cooldown_blocks_alert(monkeypatch):
    await db.get_db()
    halts = th._parse_halts_feed(_load_sample())
    sent = []

    async def fake_post(text):
        sent.append(text)

    async def blocked(*a, **k):
        return False  # cooldown active -> not allowed

    monkeypatch.setattr(db, "check_alert_cooldown", blocked)
    alerted = await th.process_new_halts(halts, {"PHOE"}, fake_post)
    assert alerted == []
    assert sent == []
    # And because we never posted, nothing was recorded -> it can still fire later.
    row = await db.get_trading_halt(halts[0]["symbol"], halts[0]["halt_ts"], halts[0]["reason_code"])
    assert row is None
