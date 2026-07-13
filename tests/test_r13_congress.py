"""r13 — Congressional (STOCK Act) House PTR tracker.

Tests:
  1. index parse — only FilingType=='P' rows survive.
  2. PTR text parser — real captured PTR lines -> ticker/type/date/amount, ticker filter.
  3. URL domain validation (disclosures-clerk.house.gov only).
  4. context-line framing + DB shadow-log round-trip (idempotent on DocID).
"""
from __future__ import annotations

import time

import pytest

from consensus_engine import db
from consensus_engine.scanners.congress_trades import (
    parse_index_txt,
    parse_ptr_text,
    _validate_url,
    build_congress_context_line,
    CongressTradeContext,
)

_INDEX_TXT = (
    "Prefix\tLast\tFirst\tSuffix\tFilingType\tStateDst\tYear\tFilingDate\tDocID\n"
    "Hon.\tAlford\tMark\t\tP\tMO03\t2026\t3/20/2026\t20034201\n"
    "Hon.\tSmith\tJane\t\tO\tCA12\t2026\t3/21/2026\t20034202\n"   # 'O' = other, dropped
    "Hon.\tDoe\tJohn\t\tP\tTX05\t2026\t3/22/2026\t20034203\n"
)

# Captured verbatim from a live House PTR PDF via pdfplumber (Rep. Alford, 2026).
_PTR_TEXT = """SP Some Asset (AMZN) [ST]
Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
AT&T Inc. (T) [ST] S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
PayPal Holdings Stock (PYPL) [ST]
SPDR S&P 500 Buyback ETF (SPYB) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
Nvidia Corp (NVDA) P 03/10/2026 03/12/2026 $15,001 - $50,000
"""


def test_parse_index_only_periodic():
    rows = parse_index_txt(_INDEX_TXT)
    assert len(rows) == 2
    docids = {r["DocID"] for r in rows}
    assert docids == {"20034201", "20034203"}
    assert all(r["FilingType"] == "P" for r in rows)


def test_parse_ptr_text_extracts_transactions():
    txns = parse_ptr_text(_PTR_TEXT)
    by_ticker = {t["ticker"]: t for t in txns}
    assert "AAPL" in by_ticker and by_ticker["AAPL"]["txn_type"] == "S"
    assert by_ticker["AAPL"]["txn_date"] == "03/16/2026"
    assert by_ticker["AAPL"]["amount_range"] == "$1,001 - $15,000"
    assert by_ticker["AAPL"]["amount_low"] == 1001.0
    assert "NVDA" in by_ticker and by_ticker["NVDA"]["txn_type"] == "P"
    assert by_ticker["NVDA"]["amount_low"] == 15001.0
    assert "T" in by_ticker  # single-letter ticker


def test_parse_ptr_text_ticker_filter():
    txns = parse_ptr_text(_PTR_TEXT, tracked={"AAPL", "NVDA"})
    tickers = {t["ticker"] for t in txns}
    assert tickers == {"AAPL", "NVDA"}


def test_validate_url():
    assert _validate_url("https://disclosures-clerk.house.gov/public_disc/x.zip")
    assert not _validate_url("https://evil.com/x.zip")
    assert not _validate_url("https://disclosures-clerk.house.gov.evil.com/x")


def test_build_context_line():
    ctx = CongressTradeContext(ticker="AAPL", trades=[
        {"ticker": "AAPL", "txn_type": "S", "member": "Mark Alford"},
        {"ticker": "AAPL", "txn_type": "P", "member": "Mark Alford"},
    ])
    line = build_congress_context_line(ctx)
    assert line is not None
    assert "Congress (House)" in line and "Mark Alford" in line
    assert "1 buy" in line and "1 sell" in line
    # no trades -> None
    assert build_congress_context_line(CongressTradeContext(ticker="AAPL")) is None


async def test_congress_shadow_log_idempotent():
    await db.init_db()
    new = await db.insert_congress_trade(
        doc_id="20034201", ticker="AAPL", member_name="Mark Alford",
        txn_type="S", txn_date="03/16/2026", notification_date="03/16/2026",
        amount_range="$1,001 - $15,000", amount_low=1001.0, filed_date="03/20/2026")
    dup = await db.insert_congress_trade(
        doc_id="20034201", ticker="AAPL", txn_type="S", txn_date="03/16/2026")
    assert new is True and dup is False
    rows = await db.get_congress_trades("AAPL", time.time() - 3600)
    assert len(rows) == 1 and rows[0]["amount_range"] == "$1,001 - $15,000"
