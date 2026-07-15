"""F9 (#76 menu) — SEC XBRL company-facts fundamentals (DISPLAY ONLY).

Pulls real company financials from SEC's free XBRL company-facts API
(data.sec.gov/api/xbrl/companyfacts) — revenue, net income, diluted EPS, assets,
liabilities — and derives YoY revenue growth + net margin. The result feeds ONE
display line on the !all card; it is NEVER folded into the score.

Reuses sec_edgar's cached ticker->CIK map and its compliant User-Agent — a second
CIK map could resolve the same ticker differently, so we import the one resolver.

Revenue-tag hazard: many filers (NVDA among them) report revenue ONLY under the
RevenueFromContractWithCustomer* tags, not us-gaap/Revenues — so we try all three
and record which tag the number came from. Quarterly points are identified by a
~3-month duration (works for off-calendar fiscal years, unlike calendar frames)
and keyed by the filer's own (fiscal-year, fiscal-period), so YoY compares like
with like.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import aiohttp

from consensus_engine.utils.http import get_session
# Reuse sec_edgar's resolver + UA — do NOT build a second CIK map.
from consensus_engine.scanners.sec_edgar import _get_cik, _USER_AGENT

log = logging.getLogger("consensus_engine.scanner.sec_xbrl")

# Ordered by preference; the first tag that has data wins and is recorded.
_REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
]

_XBRL_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


async def fetch_company_facts(ticker: str) -> Optional[dict]:
    """Fetch the raw companyfacts JSON for a ticker (has top-level 'cik' + 'facts').
    None on no-CIK / non-200 / network error (caller skips the ticker)."""
    cik = await _get_cik(ticker)
    if not cik:
        log.debug("sec_xbrl: no CIK for $%s", ticker)
        return None
    url = _XBRL_URL.format(cik=cik)
    try:
        session = await get_session()
        async with session.get(url, headers={"User-Agent": _USER_AGENT},
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                log.debug("sec_xbrl: %d for $%s (CIK %s)", resp.status, ticker, cik)
                return None
            return await resp.json(content_type=None)
    except Exception as e:
        log.debug("sec_xbrl: fetch error for $%s: %s", ticker, e)
        return None


def _dur_days(p: dict) -> Optional[int]:
    try:
        s = date.fromisoformat(p["start"])
        e = date.fromisoformat(p["end"])
        return (e - s).days
    except (KeyError, TypeError, ValueError):
        return None


def _quarterly_by_period(facts: dict, tag: str, unit: str = "USD") -> dict:
    """{(fy, fp): {'end','val'}} for ~3-month duration facts (one fiscal quarter).
    Latest-filed wins on a duplicate period."""
    node = facts.get("us-gaap", {}).get(tag)
    if not node:
        return {}
    out: dict = {}
    for p in node.get("units", {}).get(unit, []):
        d = _dur_days(p)
        if d is None or not (80 <= d <= 100):  # a single quarter, any fiscal calendar
            continue
        fy, fp = p.get("fy"), p.get("fp")
        if fy is None or fp not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        key = (fy, fp)
        prev = out.get(key)
        if prev is None or (p.get("filed", "") > prev["filed"]):
            out[key] = {"end": p.get("end"), "val": p.get("val"), "filed": p.get("filed", "")}
    return out


def _instant_by_end(facts: dict, tag: str, unit: str = "USD") -> dict:
    """{end_date: val} for instantaneous (no 'start') facts — balance-sheet items."""
    node = facts.get("us-gaap", {}).get(tag)
    if not node:
        return {}
    out: dict = {}
    seen_filed: dict = {}
    for p in node.get("units", {}).get(unit, []):
        if p.get("start"):  # duration, not an instant
            continue
        end = p.get("end")
        if not end:
            continue
        filed = p.get("filed", "")
        if end not in out or filed > seen_filed.get(end, ""):
            out[end] = p.get("val")
            seen_filed[end] = filed
    return out


def parse_fundamentals(data: dict, max_quarters: int = 8) -> tuple[list[dict], Optional[str]]:
    """Return (rows, revenue_tag). rows are up to `max_quarters` most-recent
    fiscal quarters, newest first, each with revenue/net_income/eps/assets/
    liabilities + derived revenue_yoy and net_margin. Missing values are None."""
    facts = data.get("facts", {})
    if not facts:
        return [], None

    rev_tag = None
    rev_q: dict = {}
    for t in _REVENUE_TAGS:
        q = _quarterly_by_period(facts, t)
        if q:
            rev_tag, rev_q = t, q
            break
    if not rev_q:
        return [], None

    ni_q = _quarterly_by_period(facts, "NetIncomeLoss")
    eps_q = _quarterly_by_period(facts, "EarningsPerShareDiluted", unit="USD/shares")
    assets_e = _instant_by_end(facts, "Assets")
    liab_e = _instant_by_end(facts, "Liabilities")

    # sort fiscal quarters newest first by their end date
    ordered = sorted(rev_q.items(), key=lambda kv: kv[1]["end"] or "", reverse=True)
    rows = []
    for (fy, fp), rv in ordered[:max_quarters]:
        rev = rv["val"]
        end = rv["end"]
        prior = rev_q.get((fy - 1, fp))
        yoy = None
        if prior and prior["val"]:
            try:
                yoy = (rev - prior["val"]) / prior["val"]
            except (TypeError, ZeroDivisionError):
                yoy = None
        ni = (ni_q.get((fy, fp)) or {}).get("val")
        margin = None
        if ni is not None and rev:
            try:
                margin = ni / rev
            except (TypeError, ZeroDivisionError):
                margin = None
        rows.append({
            "period_end": end,
            "fiscal_period": f"{fy} {fp}",
            "revenue": rev,
            "revenue_tag": rev_tag,
            "net_income": ni,
            "eps_diluted": (eps_q.get((fy, fp)) or {}).get("val"),
            "assets": assets_e.get(end),
            "liabilities": liab_e.get(end),
            "revenue_yoy": yoy,
            "net_margin": margin,
        })
    return rows, rev_tag


def format_fundamentals_line(row: dict) -> str:
    """One plain-English !all line from the latest fundamentals row."""
    parts = []
    rev = row.get("revenue")
    if rev is not None:
        parts.append(f"Rev ${rev/1e9:.1f}B")
    yoy = row.get("revenue_yoy")
    if yoy is not None:
        parts.append(f"{yoy*100:+.0f}% YoY")
    margin = row.get("net_margin")
    if margin is not None:
        parts.append(f"net margin {margin*100:.0f}%")
    eps = row.get("eps_diluted")
    if eps is not None:
        parts.append(f"EPS ${eps:.2f}")
    body = " · ".join(parts) if parts else "no parsed fundamentals"
    return f"🏢 Fundamentals ({row.get('fiscal_period', '')}): {body}"
