"""r27 — SEC Form 144 (insider intent-to-sell) reader.

Tests:
  1. PARSER — real-structure Form 144 XML (default namespace + ns2 address), planned
     vs discretionary tag, garbage -> None.
  2. Materiality gate + context-line framing (discretionary elevated, planned demoted).
  3. DB shadow-log round-trip (idempotent on accession).
"""
from __future__ import annotations

import time

import pytest

from consensus_engine import db
from consensus_engine.scanners.sec_form144 import (
    parse_form144_xml,
    build_form144_context_line,
    Form144Context,
)

# A structurally-real Form 144 (pinned against a live NVDA 144). Default namespace
# + an ns2-prefixed address prove the parser is namespace-agnostic (local-name).
_FORM144_XML = """<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/document/form144"
                 xmlns:ns2="http://www.sec.gov/edgar/common">
  <formData>
    <issuerInfo>
      <issuerCik>0001045810</issuerCik>
      <issuerName>NVIDIA CORPORATION</issuerName>
    </issuerInfo>
    <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>DONALD ROBERTSON</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
    <relationshipsToIssuer><relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer>
    <securitiesInformation>
      <securitiesClassTitle>Common</securitiesClassTitle>
      <brokerOrMarketmakerDetails>
        <name>Morgan Stanley</name>
        <address><ns2:city>New York</ns2:city></address>
      </brokerOrMarketmakerDetails>
      <noOfUnitsSold>4594</noOfUnitsSold>
      <aggregateMarketValue>967909.86</aggregateMarketValue>
      <approxSaleDate>06/22/2026</approxSaleDate>
    </securitiesInformation>
    <planAdoptionDate>09/18/2025</planAdoptionDate>
    <noticeDate>06/22/2026</noticeDate>
  </formData>
</edgarSubmission>"""

# Same shape, no planAdoptionDate -> discretionary sale.
_FORM144_DISCRETIONARY = _FORM144_XML.replace(
    "<planAdoptionDate>09/18/2025</planAdoptionDate>", "")


def test_parse_form144_core_fields():
    p = parse_form144_xml(_FORM144_XML)
    assert p is not None
    assert p["issuer"] == "NVIDIA CORPORATION"
    assert p["person"] == "DONALD ROBERTSON"
    assert p["relationship"] == "Officer"
    assert p["units_sold"] == 4594.0
    assert p["aggregate_value"] == 967909.86
    assert p["approx_sale_date"] == "06/22/2026"
    # planAdoptionDate present -> planned (10b5-1) sale
    assert p["plan_adoption_date"] == "09/18/2025"
    assert p["is_planned"] is True


def test_parse_form144_discretionary():
    p = parse_form144_xml(_FORM144_DISCRETIONARY)
    assert p is not None
    assert p["is_planned"] is False
    assert p["plan_adoption_date"] == ""


def test_parse_form144_garbage_returns_none():
    assert parse_form144_xml("not xml <<<") is None
    # A well-formed but non-144 doc (no core fields) -> None, never a fake row.
    assert parse_form144_xml("<x><y>1</y></x>") is None


def test_context_line_discretionary_elevated():
    ctx = Form144Context(ticker="NVDA", n_insiders=3, n_discretionary=2,
                         total_value=3_400_000, discretionary_value=2_100_000,
                         passes_materiality=True)
    line = build_form144_context_line(ctx)
    assert line is not None
    assert "Intent-to-sell" in line and "discretionary" in line
    assert "2 insider" in line


def test_context_line_planned_demoted():
    ctx = Form144Context(ticker="NVDA", n_insiders=2, n_discretionary=0,
                         total_value=2_000_000, discretionary_value=0.0,
                         passes_materiality=True)
    line = build_form144_context_line(ctx)
    assert line is not None
    assert "planned (10b5-1)" in line
    assert "⚠️" not in line  # planned-only is not elevated


def test_context_line_below_materiality_is_none():
    ctx = Form144Context(ticker="NVDA", n_insiders=1, n_discretionary=1,
                         total_value=500_000, discretionary_value=500_000,
                         passes_materiality=False)
    assert build_form144_context_line(ctx) is None


async def test_form144_shadow_log_roundtrip_idempotent():
    await db.init_db()
    new = await db.upsert_form144_filing(
        ticker="NVDA", accession_number="ACC-1", cik="1045810",
        person="DONALD ROBERTSON", relationship="Officer", units_sold=4594,
        aggregate_value=967909.86, approx_sale_date="06/22/2026",
        plan_adoption_date="09/18/2025", is_planned=True, filed_at="2026-06-22")
    dup = await db.upsert_form144_filing(ticker="NVDA", accession_number="ACC-1")
    assert new is True and dup is False  # idempotent on accession
    rows = await db.get_form144_recent("NVDA", time.time() - 3600)
    assert len(rows) == 1
    assert rows[0]["is_planned"] is True
    assert rows[0]["aggregate_value"] == 967909.86
