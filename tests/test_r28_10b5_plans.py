"""r28 — Rule 10b5-1 plan adoption/termination state.

Tests:
  1. cross_reference._parse_form4_for_graduation reads the STRUCTURED <aff10b5One>
     flag + reporter cik (additive; existing keys untouched).
  2. classify_plan_transition — cold-start None -> no event; 0->1 adoption;
     1->0 termination; unchanged -> None.
  3. scan_10b5_plan_events on a COLD-START empty table emits NOTHING (seeds silently);
     a later plan flip yields exactly one event.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import db
from consensus_engine.cross_reference import _parse_form4_for_graduation
from consensus_engine.scanners.insider_10b5 import (
    classify_plan_transition,
    scan_10b5_plan_events,
)


def _form4_xml(aff10b5: str | None, cik: str = "111", code: str = "P") -> str:
    """Minimal Form 4 XML with an optional <aff10b5One> flag."""
    aff = f"<aff10b5One>{aff10b5}</aff10b5One>" if aff10b5 is not None else ""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>{cik}</rptOwnerCik>
      <rptOwnerName>JANE DOE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  {aff}
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
    <transactionDate><value>2026-07-05</value></transactionDate>
    <transactionAmounts>
      <transactionShares><value>1000</value></transactionShares>
      <transactionPricePerShare><value>100</value></transactionPricePerShare>
    </transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


def test_parser_reads_structured_10b5_flag():
    p = _parse_form4_for_graduation(_form4_xml("1"))
    assert p is not None
    assert p["is_10b5_1_structured"] is True
    assert p["structured_plan_flag_seen"] is True
    assert p["reporter_cik"] == "111"
    assert p["reporter_name"] == "JANE DOE"
    # existing I5 keys untouched
    assert set(["role", "is_planned", "plan_flag_seen", "buy_dollars",
                "buy_date", "has_sell"]).issubset(p.keys())


def test_parser_structured_flag_absent_and_zero():
    # aff10b5One absent
    p0 = _parse_form4_for_graduation(_form4_xml(None))
    assert p0["structured_plan_flag_seen"] is False
    assert p0["is_10b5_1_structured"] is False
    # aff10b5One present but "0"
    p1 = _parse_form4_for_graduation(_form4_xml("0"))
    assert p1["structured_plan_flag_seen"] is True
    assert p1["is_10b5_1_structured"] is False


def test_classify_plan_transition():
    assert classify_plan_transition(None, True) is None          # cold-start seed
    assert classify_plan_transition(None, False) is None
    assert classify_plan_transition({"plan_active": 0}, True) == "adoption"
    assert classify_plan_transition({"plan_active": 1}, False) == "termination"
    assert classify_plan_transition({"plan_active": 1}, True) is None
    assert classify_plan_transition({"plan_active": 0}, False) is None


async def test_cold_start_emits_nothing_then_transition():
    await db.init_db()
    filing = {"form": "4", "cik": "111", "accession_number": "a-1",
              "primary_document": "form4.xml"}

    with patch("consensus_engine.db.get_active_tickers", AsyncMock(return_value=["NVDA"])), \
         patch("consensus_engine.scanners.insider_10b5.check_recent_filings",
               AsyncMock(return_value=[filing])), \
         patch("consensus_engine.scanners.insider_10b5.rate_limiter.acquire",
               AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
               AsyncMock(return_value=_form4_xml("0"))):
        # First scan on an EMPTY table: seeds state silently, emits NO event.
        assert await db.insider_10b5_plans_count() == 0
        events = await scan_10b5_plan_events()
        assert events == []
        assert await db.insider_10b5_plans_count() == 1
        st = await db.get_insider_10b5_plan("NVDA", "111")
        assert st["plan_active"] == 0

    # Now the same insider adopts a plan (flag flips 0 -> 1): exactly one adoption.
    with patch("consensus_engine.db.get_active_tickers", AsyncMock(return_value=["NVDA"])), \
         patch("consensus_engine.scanners.insider_10b5.check_recent_filings",
               AsyncMock(return_value=[filing])), \
         patch("consensus_engine.scanners.insider_10b5.rate_limiter.acquire",
               AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
               AsyncMock(return_value=_form4_xml("1"))):
        events = await scan_10b5_plan_events()
        assert len(events) == 1
        assert events[0].event_type == "adoption"
        assert events[0].ticker == "NVDA"
        st = await db.get_insider_10b5_plan("NVDA", "111")
        assert st["plan_active"] == 1
