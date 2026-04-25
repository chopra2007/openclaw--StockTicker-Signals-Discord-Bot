"""Tests for M1: SEC watcher item-type whitelist + Form 4 dollar filter.

Re-enables the SEC background watchers with two filters added on top of
the existing scan_8k_filings + check_recent_filings code paths:

1. 8-K item-type whitelist: only material agreements (1.01), earnings
   releases (2.02), Reg FD (7.01), other events (8.01), and officer
   changes (5.02) trigger downstream signals. Boilerplate filings
   (e.g. 9.01 financial-statements-only) are dropped.

2. Form 4 dollar filter: insider purchases below the configured floor
   (sec_watcher.min_insider_dollars_buy) and sales below
   sec_watcher.min_insider_dollars_sell are dropped.
"""
import pytest

from consensus_engine.scanners.sec_watcher import (
    _extract_item_types,
    _is_item_whitelisted,
    _parse_8k_feed,
)
from consensus_engine.scanners.sec_edgar import (
    compute_insider_value,
    insider_buy_or_sell,
)


# ---------------------------------------------------------------------------
# 8-K item-type extraction
# ---------------------------------------------------------------------------

class TestExtractItemTypes:
    def test_extracts_single_item(self):
        summary = "8-K filed by NVIDIA CORP. Items: 2.02"
        assert _extract_item_types(summary) == ["2.02"]

    def test_extracts_multiple_items(self):
        summary = "Form 8-K, Items: 1.01, 5.02, 9.01"
        items = _extract_item_types(summary)
        assert "1.01" in items
        assert "5.02" in items
        assert "9.01" in items

    def test_returns_empty_when_no_items(self):
        assert _extract_item_types("8-K filed by ABC CORP") == []

    def test_handles_item_word_form(self):
        """Variants like 'Item 1.01' (singular, no colon) are accepted."""
        summary = "Form 8-K Item 1.01 Material Definitive Agreement"
        assert _extract_item_types(summary) == ["1.01"]


# ---------------------------------------------------------------------------
# Item whitelist filter
# ---------------------------------------------------------------------------

class TestItemWhitelist:
    def test_material_event_passes(self):
        whitelist = {"1.01", "2.02", "5.02", "7.01", "8.01"}
        assert _is_item_whitelisted(["1.01"], whitelist) is True

    def test_only_boilerplate_filtered_out(self):
        whitelist = {"1.01", "2.02", "5.02", "7.01", "8.01"}
        # 9.01 = financial statements/exhibits, boilerplate
        assert _is_item_whitelisted(["9.01"], whitelist) is False

    def test_mixed_passes_when_at_least_one_whitelisted(self):
        whitelist = {"1.01", "2.02", "5.02", "7.01", "8.01"}
        assert _is_item_whitelisted(["9.01", "2.02"], whitelist) is True

    def test_empty_items_passes(self):
        """No item codes parsed → assume material; don't block (precision/recall trade-off)."""
        whitelist = {"1.01", "2.02"}
        assert _is_item_whitelisted([], whitelist) is True


# ---------------------------------------------------------------------------
# Updated _parse_8k_feed surfaces item_types
# ---------------------------------------------------------------------------

ATOM_WITH_ITEMS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - NVIDIA CORP (0001045810) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1045810/000104581024000123/0001045810-24-000123-index.htm" rel="alternate" type="text/html"/>
    <summary>Form 8-K, Items: 2.02, 9.01</summary>
    <updated>2026-03-29T10:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2026:0001045810-24-000123</id>
  </entry>
</feed>"""


def test_parse_8k_feed_includes_item_types():
    filings = _parse_8k_feed(ATOM_WITH_ITEMS)
    assert len(filings) == 1
    assert filings[0]["item_types"] == ["2.02", "9.01"]


# ---------------------------------------------------------------------------
# Form 4 dollar filter
# ---------------------------------------------------------------------------

class TestComputeInsiderValue:
    def test_sums_buy_dollars(self):
        txs = [
            {"shares": 1000, "price": 50.0, "transaction_type": "Open Market Purchase",
             "direction": "Buy"},
            {"shares": 500, "price": 50.0, "transaction_type": "Open Market Purchase",
             "direction": "Buy"},
        ]
        assert compute_insider_value(txs, "Buy") == 75_000.0

    def test_only_sums_matching_direction(self):
        txs = [
            {"shares": 1000, "price": 50.0, "transaction_type": "Open Market Purchase",
             "direction": "Buy"},
            {"shares": 1000, "price": 50.0, "transaction_type": "Open Market Sale",
             "direction": "Sell"},
        ]
        assert compute_insider_value(txs, "Buy") == 50_000.0
        assert compute_insider_value(txs, "Sell") == 50_000.0

    def test_ignores_non_open_market(self):
        """Awards, gifts, tax withholding don't count as insider conviction."""
        txs = [
            {"shares": 1000, "price": 50.0, "transaction_type": "Award/Grant",
             "direction": "Buy"},
            {"shares": 1000, "price": 50.0, "transaction_type": "Tax Withholding",
             "direction": "Sell"},
        ]
        assert compute_insider_value(txs, "Buy") == 0.0
        assert compute_insider_value(txs, "Sell") == 0.0

    def test_empty_list(self):
        assert compute_insider_value([], "Buy") == 0.0


class TestInsiderBuyOrSell:
    def test_returns_buy_when_buys_dominate(self):
        txs = [{"shares": 1000, "price": 50.0,
                "transaction_type": "Open Market Purchase", "direction": "Buy"}]
        assert insider_buy_or_sell(txs) == "Buy"

    def test_returns_sell_when_sells_dominate(self):
        txs = [{"shares": 1000, "price": 50.0,
                "transaction_type": "Open Market Sale", "direction": "Sell"}]
        assert insider_buy_or_sell(txs) == "Sell"

    def test_returns_none_when_no_open_market(self):
        txs = [{"shares": 1000, "price": 50.0,
                "transaction_type": "Award/Grant", "direction": "Buy"}]
        assert insider_buy_or_sell(txs) is None
