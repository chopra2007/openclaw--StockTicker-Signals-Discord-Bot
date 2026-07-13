"""r27: SEC Form 144 (insider intent-to-sell) reader — CONTEXT ONLY.

Form 144 is the notice an affiliate files BEFORE selling restricted/control stock.
It already rides in the same CIK submissions JSON `check_recent_filings` fetches;
it is surfaced only because '144' was added to `sec_edgar._RELEVANT_FORMS` (r27).

This module mirrors `sec_form4_cluster.py`: it reuses `_get_cik`, `_USER_AGENT`,
`rate_limiter('sec_edgar')` (via `check_recent_filings`), and a `_fetch_form144_xml`
copy of `_fetch_form4_xml` (same Archives URL shape). It is NOT a standalone alert:
default OFF, shadow-logs every parsed 144 to the `form144_filings` table, and (once
shadow data justifies it) surfaces a single CONTEXT line through the shared
`insider_display` renderer.

Real Form 144 XML tags (pinned against a live NVDA 144, 2026-06-22):
    <issuerName>                                         issuer
    <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold> selling person
    <relationshipToIssuer>                               role (Officer/Director/…)
    securitiesInformation/<noOfUnitsSold>                shares to be sold
    securitiesInformation/<aggregateMarketValue>         intended $ value
    securitiesInformation/<approxSaleDate>               MM/DD/YYYY
    <planAdoptionDate>          present => sale is under a 10b5-1 plan (planned)

The XML carries a default namespace, so parsing is namespace-agnostic (local-name).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils.http import get_session
from consensus_engine.scanners.sec_edgar import _USER_AGENT, check_recent_filings

log = logging.getLogger(__name__)

_MAX_TICKERS_PER_SCAN = 50


def _local(el: ET.Element, name: str) -> str:
    """First descendant whose local (namespace-stripped) tag == name; '' if absent.

    Form 144 XML declares a default namespace, so a plain `.//issuerName` misses;
    matching on the local name is namespace-agnostic and robust to schema churn.
    """
    for node in el.iter():
        if node.tag.rsplit("}", 1)[-1] == name:
            return (node.text or "").strip()
    return ""


def parse_form144_xml(raw_xml: str) -> Optional[dict]:
    """Parse one Form 144 notice into a flat dict, or None on parse failure.

    Returns {issuer, person, relationship, class_title, units_sold, aggregate_value,
             approx_sale_date, plan_adoption_date, is_planned}. is_planned is True
    when a 10b5-1 planAdoptionDate is present (planned sale) — the discretionary/
    planned split the materiality gate uses.
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None

    def _num(name: str) -> Optional[float]:
        s = _local(root, name).replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    plan_adoption_date = _local(root, "planAdoptionDate")
    units = _num("noOfUnitsSold")
    value = _num("aggregateMarketValue")
    person = _local(root, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    issuer = _local(root, "issuerName")

    # A doc with none of the core fields is not a parseable 144 (e.g. the
    # primaryDocument pointed at a paper/cover file) -> treat as unparseable.
    if not (issuer or person or value or units):
        return None

    return {
        "issuer": issuer,
        "person": person or "Unknown",
        "relationship": _local(root, "relationshipToIssuer"),
        "class_title": _local(root, "securitiesClassTitle"),
        "units_sold": units,
        "aggregate_value": value,
        "approx_sale_date": _local(root, "approxSaleDate"),
        "plan_adoption_date": plan_adoption_date,
        "is_planned": bool(plan_adoption_date),
    }


async def _fetch_form144_xml(cik: str, accession_number: str, primary_document: str) -> Optional[str]:
    """Fetch raw Form 144 XML from SEC EDGAR Archives (copy of sec_form4_cluster._fetch_form4_xml)."""
    if not accession_number or not primary_document:
        return None
    accession_nodash = accession_number.replace("-", "")
    cik_int = str(int(cik)) if cik and cik.isdigit() else cik
    filename = primary_document.split("/")[-1]
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}"
        f"/{accession_nodash}/{filename}"
    )
    try:
        session = await get_session()
        async with session.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.debug("[r27] Form 144 XML %d: %s", resp.status, url)
                return None
            return await resp.text()
    except Exception as e:  # noqa: BLE001 — a fetch error is a skip, never fatal
        log.debug("[r27] Form 144 XML fetch error: %s", e)
        return None


@dataclass
class Form144Context:
    """Per-ticker aggregate of recent Form 144 intent-to-sell notices."""
    ticker: str
    n_insiders: int
    n_discretionary: int
    total_value: float
    discretionary_value: float
    passes_materiality: bool
    notices: list[dict] = field(default_factory=list)


async def scan_form144_filings(
    hours_back: int = 168,
    min_dollars: Optional[float] = None,
    min_unique: Optional[int] = None,
) -> list[Form144Context]:
    """Scan recent Form 144 filings for active tickers; shadow-log + aggregate.

    Every parsed 144 is shadow-logged to form144_filings (idempotent on accession).
    A Form144Context is returned per ticker; passes_materiality is True when the
    aggregate intended sale value >= min_dollars AND the notice count of DISTINCT
    insiders >= min_unique (planned 10b5-1 sales are counted but demoted — only the
    discretionary aggregate drives the 'elevated' framing in the context line).
    """
    if min_dollars is None:
        min_dollars = float(cfg.get("sec_watcher.min_form144_dollars", 1_000_000))
    if min_unique is None:
        min_unique = int(cfg.get("sec_watcher.min_form144_unique", 2))

    tickers = await db.get_active_tickers(min_signals=1)
    out: list[Form144Context] = []

    for ticker in tickers[:_MAX_TICKERS_PER_SCAN]:
        filings = await check_recent_filings(ticker, hours_back=hours_back)
        notices: list[dict] = []
        persons: set[str] = set()
        discretionary_persons: set[str] = set()
        total_value = 0.0
        discretionary_value = 0.0
        for filing in filings:
            if filing.get("form") != "144":
                continue
            raw_xml = await _fetch_form144_xml(
                filing.get("cik", ""),
                filing.get("accession_number", ""),
                filing.get("primary_document", ""),
            )
            if not raw_xml:
                continue
            parsed = parse_form144_xml(raw_xml)
            if not parsed:
                continue

            acc = filing.get("accession_number", "")
            try:
                await db.upsert_form144_filing(
                    ticker=ticker,
                    accession_number=acc,
                    cik=filing.get("cik"),
                    person=parsed["person"],
                    relationship=parsed["relationship"],
                    units_sold=parsed["units_sold"],
                    aggregate_value=parsed["aggregate_value"],
                    approx_sale_date=parsed["approx_sale_date"],
                    plan_adoption_date=parsed["plan_adoption_date"],
                    is_planned=parsed["is_planned"],
                    filed_at=filing.get("filing_date"),
                )
            except Exception as e:  # noqa: BLE001 — shadow-log failure never voids the scan
                log.debug("[r27] $%s form144 shadow-log error: %s", ticker, e)

            value = parsed["aggregate_value"] or 0.0
            notices.append({**parsed, "accession_number": acc})
            persons.add(parsed["person"])
            total_value += value
            if not parsed["is_planned"]:
                discretionary_persons.add(parsed["person"])
                discretionary_value += value

        if not notices:
            continue

        passes = total_value >= min_dollars and len(persons) >= min_unique
        out.append(Form144Context(
            ticker=ticker,
            n_insiders=len(persons),
            n_discretionary=len(discretionary_persons),
            total_value=total_value,
            discretionary_value=discretionary_value,
            passes_materiality=passes,
            notices=notices,
        ))
        if passes:
            log.info("[r27] $%s intent-to-sell: %d insiders $%.0f (%d discretionary $%.0f)",
                     ticker, len(persons), total_value,
                     len(discretionary_persons), discretionary_value)

    return out


def build_form144_context_line(ctx: Form144Context) -> Optional[str]:
    """One insider-display context line for a material Form 144 aggregate, or None.

    Discretionary (non-10b5-1) sales are framed as elevated; a purely planned set
    is demoted to a neutral note. Dollar figures use the shared compact format.
    """
    if not ctx.passes_materiality:
        return None
    from consensus_engine.alerts.insider_display import _compact_dollar
    if ctx.n_discretionary:
        return (f"⚠️ Intent-to-sell: {ctx.n_discretionary} insider(s) filed "
                f"discretionary Form 144 ~{_compact_dollar(ctx.discretionary_value)} "
                f"(of {ctx.n_insiders} total, {_compact_dollar(ctx.total_value)})")
    return (f"Intent-to-sell: {ctx.n_insiders} insider(s) filed planned (10b5-1) "
            f"Form 144 ~{_compact_dollar(ctx.total_value)}")
