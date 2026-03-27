"""SEC EDGAR Filing Checker — detects recent 8-K, 10-Q, 10-K, Form 4 filings.

Uses the SEC EDGAR REST API (data.sec.gov) which requires a User-Agent header.
CIK lookups are cached in the ticker_metadata table.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
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
        async with aiohttp.ClientSession() as session:
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
        async with aiohttp.ClientSession() as session:
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
            results.append({
                "form": form,
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "acceptance_datetime": acceptance_str,
                "accession_number": accession,
            })

        if results:
            log.info("SEC EDGAR $%s: %d recent filings (%s)",
                     ticker, len(results), ", ".join(r["form"] for r in results))
        return results

    except Exception as e:
        log.warning("SEC EDGAR error for $%s: %s", ticker, e)
        rate_limiter.report_failure("sec_edgar")
        return []


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
