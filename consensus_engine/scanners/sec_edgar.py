"""SEC EDGAR Filing Checker — detects recent 8-K, 10-Q, 10-K, Form 4 filings.

Uses the SEC EDGAR REST API (data.sec.gov) which requires a User-Agent header.
CIK lookups are cached in the ticker_metadata table.
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.sec_edgar")

_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"

# Forms we care about and their significance
_RELEVANT_FORMS = {"8-K", "10-K", "10-Q", "4", "SC 13D", "SC 13G"}

# Cache: ticker → CIK (loaded once from SEC's company_tickers.json)
_ticker_to_cik: dict[str, str] = {}


async def _load_ticker_map():
    """Load the full ticker → CIK mapping from SEC. Cached in memory."""
    global _ticker_to_cik
    if _ticker_to_cik:
        return

    try:
        session = await get_session()
        headers = {"User-Agent": _USER_AGENT}
        url = "https://www.sec.gov/files/company_tickers.json"
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("SEC ticker map fetch failed: %d", resp.status)
                return
            data = await resp.json(content_type=None)

        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            if ticker and cik:
                _ticker_to_cik[ticker] = cik.zfill(10)

        log.info("SEC EDGAR: loaded %d ticker→CIK mappings", len(_ticker_to_cik))
    except Exception as e:
        log.warning("Failed to load SEC ticker map: %s", e)


async def _get_cik(ticker: str) -> Optional[str]:
    """Get the 10-digit zero-padded CIK for a ticker."""
    await _load_ticker_map()
    return _ticker_to_cik.get(ticker.upper())


async def check_recent_filings(ticker: str, hours_back: int = 48) -> list[dict]:
    """Check SEC EDGAR for recent filings of a given ticker.

    Returns list of dicts with keys: form, filing_date, acceptance_datetime, accession_number.
    Only returns filings from the last `hours_back` hours.
    """
    if not await rate_limiter.acquire("sec_edgar"):
        return []

    cik = await _get_cik(ticker)
    if not cik:
        log.debug("No CIK found for $%s", ticker)
        return []

    try:
        session = await get_session()
        headers = {"User-Agent": _USER_AGENT}
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.debug("SEC EDGAR %d for $%s (CIK %s)", resp.status, ticker, cik)
                rate_limiter.report_failure("sec_edgar")
                return []
            data = await resp.json(content_type=None)

        rate_limiter.report_success("sec_edgar")

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        acceptance_times = recent.get("acceptanceDateTime", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        results = []

        for i in range(min(len(forms), 50)):  # check last 50 filings max
            form = forms[i] if i < len(forms) else ""
            if form not in _RELEVANT_FORMS:
                continue

            acceptance_str = acceptance_times[i] if i < len(acceptance_times) else ""
            try:
                filed_dt = datetime.fromisoformat(acceptance_str.replace("Z", "+00:00"))
                if filed_dt < cutoff:
                    break  # filings are in reverse chronological order
            except (ValueError, TypeError):
                # Fall back to filing_date string
                filing_date_str = filing_dates[i] if i < len(filing_dates) else ""
                try:
                    filed_dt = datetime.strptime(filing_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if filed_dt < cutoff:
                        break
                except ValueError:
                    continue

            accession = accession_numbers[i] if i < len(accession_numbers) else ""
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            results.append({
                "form": form,
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "acceptance_datetime": acceptance_str,
                "accession_number": accession,
                "primary_document": primary_doc,
                "cik": cik,
            })

        if results:
            log.info("SEC EDGAR $%s: %d recent filings (%s)",
                     ticker, len(results), ", ".join(r["form"] for r in results))
        return results

    except Exception as e:
        log.warning("SEC EDGAR error for $%s: %s", ticker, e)
        rate_limiter.report_failure("sec_edgar")
        return []


# Open-market transactions only — awards, gifts, tax withholding don't
# express insider conviction and are excluded from the dollar filter.
_OPEN_MARKET_TX_TYPES = {"Open Market Purchase", "Open Market Sale"}


def compute_insider_value(transactions: list[dict], direction: str) -> float:
    """Sum dollar value of open-market insider transactions in `direction`.

    direction: "Buy" | "Sell". Awards / tax withholding / gifts are
    excluded — only conviction trades count toward the M1 filter.
    """
    total = 0.0
    for tx in transactions:
        if tx.get("transaction_type") not in _OPEN_MARKET_TX_TYPES:
            continue
        if tx.get("direction") != direction:
            continue
        try:
            shares = float(tx.get("shares") or 0)
            price = float(tx.get("price") or 0)
        except (TypeError, ValueError):
            continue
        total += shares * price
    return total


def insider_buy_or_sell(transactions: list[dict]) -> Optional[str]:
    """Whichever side has the higher dollar value, or None if neither side trades."""
    buy = compute_insider_value(transactions, "Buy")
    sell = compute_insider_value(transactions, "Sell")
    if buy == 0 and sell == 0:
        return None
    return "Buy" if buy >= sell else "Sell"


def classify_filing_significance(filings: list[dict]) -> tuple[bool, str]:
    """Classify filings by significance for cross-reference scoring.

    Returns (has_significant_filing, summary_string).
    """
    if not filings:
        return False, ""

    forms_found = {f["form"] for f in filings}
    significant = forms_found & {"8-K", "10-K", "10-Q", "SC 13D"}
    insider = "4" in forms_found

    parts = []
    if "8-K" in forms_found:
        parts.append("8-K (material event)")
    if "10-K" in forms_found:
        parts.append("10-K (annual report)")
    if "10-Q" in forms_found:
        parts.append("10-Q (quarterly report)")
    if "SC 13D" in forms_found or "SC 13G" in forms_found:
        parts.append("SC 13D/G (activist/institutional)")
    if insider:
        count = sum(1 for f in filings if f["form"] == "4")
        parts.append(f"Form 4 x{count} (insider trading)")

    summary = "; ".join(parts)
    return bool(significant) or insider, summary


async def fetch_form4_details(cik: str, accession_number: str, primary_document: str) -> list[dict]:
    """Fetch and parse a Form 4 XML filing.

    Returns a list of transaction dicts, each with:
      reporter_name, title, transaction_type, shares, price, direction, security, date
    """
    if not accession_number or not primary_document:
        return []

    accession_nodash = accession_number.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for the path
    # primaryDocument may have a stylesheet prefix like "xslF345X06/form4.xml"
    filename = primary_document.split("/")[-1]
    xml_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}"
        f"/{accession_nodash}/{filename}"
    )

    try:
        session = await get_session()
        headers = {"User-Agent": _USER_AGENT}
        async with session.get(xml_url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.debug("Form 4 XML fetch failed %d: %s", resp.status, xml_url)
                return []
            raw = await resp.text()
    except Exception as e:
        log.debug("Form 4 fetch error: %s", e)
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        log.debug("Form 4 XML parse error: %s", e)
        return []

    def _val(node, tag):
        el = node.find(f".//{tag}/value")
        if el is None:
            el = node.find(f".//{tag}")
        return (el.text or "").strip() if el is not None else ""

    # Reporter identity
    reporter_name = _val(root, "rptOwnerName") or "Unknown"
    is_director = _val(root, "isDirector") == "1"
    is_officer = _val(root, "isOfficer") == "1"
    is_ten_pct = _val(root, "isTenPercentOwner") == "1"
    officer_title = _val(root, "officerTitle")

    if officer_title:
        title = officer_title
    elif is_director and is_officer:
        title = "Director & Officer"
    elif is_director:
        title = "Director"
    elif is_ten_pct:
        title = "10% Owner"
    else:
        title = "Insider"

    transactions = []

    for tx in root.findall(".//nonDerivativeTransaction"):
        shares_str = _val(tx, "transactionShares")
        price_str = _val(tx, "transactionPricePerShare")
        code = _val(tx, "transactionAcquiredDisposedCode")
        date = _val(tx, "transactionDate")
        security = _val(tx, "securityTitle") or "Common Stock"
        tx_code = _val(tx, "transactionCode")  # P=purchase, S=sale, A=award, etc.

        try:
            shares = float(shares_str) if shares_str else 0.0
        except ValueError:
            shares = 0.0
        try:
            price = float(price_str) if price_str else 0.0
        except ValueError:
            price = 0.0

        direction = "Buy" if code == "A" else "Sell" if code == "D" else code
        tx_label = {"P": "Open Market Purchase", "S": "Open Market Sale",
                    "A": "Award/Grant", "F": "Tax Withholding", "M": "Option Exercise",
                    "G": "Gift", "D": "Disposition"}.get(tx_code, tx_code or "Transaction")

        transactions.append({
            "reporter_name": reporter_name,
            "title": title,
            "security": security,
            "date": date,
            "shares": shares,
            "price": price,
            "direction": direction,
            "transaction_type": tx_label,
        })

    for tx in root.findall(".//derivativeTransaction"):
        shares_str = _val(tx, "transactionShares")
        price_str = _val(tx, "transactionPricePerShare")
        code = _val(tx, "transactionAcquiredDisposedCode")
        date = _val(tx, "transactionDate")
        security = _val(tx, "securityTitle") or "Derivative"
        tx_code = _val(tx, "transactionCode")

        try:
            shares = float(shares_str) if shares_str else 0.0
        except ValueError:
            shares = 0.0
        try:
            price = float(price_str) if price_str else 0.0
        except ValueError:
            price = 0.0

        direction = "Buy" if code == "A" else "Sell" if code == "D" else code
        tx_label = {"P": "Open Market Purchase", "S": "Open Market Sale",
                    "A": "Award/Grant", "F": "Tax Withholding", "M": "Option Exercise",
                    "G": "Gift", "D": "Disposition"}.get(tx_code, tx_code or "Transaction")

        transactions.append({
            "reporter_name": reporter_name,
            "title": title,
            "security": security,
            "date": date,
            "shares": shares,
            "price": price,
            "direction": direction,
            "transaction_type": tx_label,
        })

    return transactions
