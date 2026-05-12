"""SEC 8-K Real-Time Watcher.

Polls SEC EDGAR for new 8-K filings every 15 minutes.
Catches material events before analysts tweet about them.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.sec_watcher")

_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"

_8K_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom"
)

# 8-K item codes that drive material price-moving events.
# Reference: https://www.sec.gov/forms-8-k
# 1.01 material agreement; 2.02 results of operations; 5.02 officer change;
# 7.01 Reg FD disclosure; 8.01 other material events.
_DEFAULT_ITEM_WHITELIST = {"1.01", "2.02", "5.02", "7.01", "8.01"}

_ITEM_PATTERN = re.compile(r"\bItems?:?\s*((?:\d+\.\d+(?:\s*,\s*)?)+)", re.IGNORECASE)
_ITEM_NUMBER_PATTERN = re.compile(r"\d+\.\d+")


def _extract_item_types(summary: str) -> list[str]:
    """Pull 8-K item codes (e.g. '2.02') from an ATOM <summary> string."""
    if not summary:
        return []
    match = _ITEM_PATTERN.search(summary)
    if not match:
        return []
    return _ITEM_NUMBER_PATTERN.findall(match.group(1))


def _is_item_whitelisted(items: list[str], whitelist: set[str]) -> bool:
    """True when at least one item is whitelisted, or no items are listed.

    No-items case is treated as a pass: parsing failed or feed is sparse, so
    fall through to the next filter rather than drop the filing.
    """
    if not items:
        return True
    return any(item in whitelist for item in items)


@dataclass
class Filing8K:
    cik: str
    company: str
    form: str
    url: str
    filing_id: str


def _parse_8k_feed(xml_text: str) -> list[dict]:
    """Parse SEC EDGAR ATOM feed for 8-K filings.

    Returns list of dicts with keys: cik, company, form, url, filing_id.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("SEC 8-K feed: invalid XML")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    filings = []

    for entry in entries:
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        id_el = entry.find("atom:id", ns)
        summary_el = entry.find("atom:summary", ns)

        if title_el is None or title_el.text is None:
            continue

        title = title_el.text
        if not title.startswith("8-K"):
            continue

        cik_match = re.search(r'\((\d{10})\)', title)
        cik = cik_match.group(1) if cik_match else ""

        company = title.split(" - ", 1)[1].split(" (")[0] if " - " in title else ""

        url = link_el.get("href", "") if link_el is not None else ""
        filing_id = id_el.text if id_el is not None and id_el.text else url
        summary = (summary_el.text or "") if summary_el is not None else ""
        item_types = _extract_item_types(summary)

        filings.append({
            "cik": cik,
            "company": company,
            "form": "8-K",
            "url": url,
            "filing_id": filing_id,
            "item_types": item_types,
        })

    return filings


async def fetch_recent_8k_filings() -> list[dict]:
    """Fetch recent 8-K filings from SEC EDGAR ATOM feed."""
    if not await rate_limiter.acquire("sec_edgar"):
        return []

    try:
        session = await get_session()
        headers = {"User-Agent": _USER_AGENT}
        async with session.get(_8K_FEED_URL, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("SEC 8-K feed returned %d", resp.status)
                rate_limiter.report_failure("sec_edgar")
                return []
            xml_text = await resp.text()

        rate_limiter.report_success("sec_edgar")
        return _parse_8k_feed(xml_text)
    except Exception as e:
        log.warning("SEC 8-K feed error: %s", e)
        rate_limiter.report_failure("sec_edgar")
        return []


async def _resolve_ticker_from_cik(cik: str) -> Optional[str]:
    """Resolve a CIK to a ticker using the SEC ticker map."""
    try:
        from consensus_engine.scanners.sec_edgar import _load_ticker_map, _ticker_to_cik
        await _load_ticker_map()
        for ticker, mapped_cik in _ticker_to_cik.items():
            if mapped_cik == cik:
                return ticker
    except Exception as e:
        log.debug("CIK->ticker resolve error: %s", e)
    return None


async def scan_8k_filings() -> list[dict]:
    """Scan for new 8-K filings, dedup, resolve tickers, filter by market cap.

    Returns list of dicts: {ticker, company, url, filing_id, form}.
    """
    filings = await fetch_recent_8k_filings()
    if not filings:
        return []

    whitelist_cfg = cfg.get("sec_watcher.item_whitelist", None)
    whitelist = set(whitelist_cfg) if whitelist_cfg else _DEFAULT_ITEM_WHITELIST

    results = []
    for f in filings:
        filing_id = f["filing_id"]
        item_types = f.get("item_types", [])
        if not _is_item_whitelisted(item_types, whitelist):
            log.debug("SEC 8-K skipped (items=%s not whitelisted): %s",
                      item_types, f.get("company", ""))
            continue

        if not await db.is_new_tweet(filing_id):
            continue

        ticker = await _resolve_ticker_from_cik(f["cik"])
        if not ticker:
            continue

        from consensus_engine.utils.tickers import validate_ticker_market_cap
        if not await validate_ticker_market_cap(ticker):
            continue

        await db.mark_tweet_seen(filing_id, f"SEC-8K-{f['company'][:30]}")
        results.append({
            "ticker": ticker,
            "company": f["company"],
            "url": f["url"],
            "filing_id": filing_id,
            "form": "8-K",
            "item_types": item_types,
        })

    if results:
        log.info("SEC 8-K watcher: %d new filings for tracked tickers", len(results))
    return results
