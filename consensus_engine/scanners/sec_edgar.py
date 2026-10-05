"""SEC EDGAR Filing Checker — detects recent 8-K, 10-Q, 10-K, Form 4 filings.

Uses the SEC EDGAR REST API (data.sec.gov) which requires a User-Agent header.
CIK lookups are cached in the ticker_metadata table.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

async def get_session():
    """Bot-only lazy default; injected collection never calls this adapter."""
    from consensus_engine.utils.http import get_session as default_session
    return await default_session()


class _BotLimiter:
    def __getattr__(self, name):
        if name not in {'acquire', 'report_success', 'report_failure'}:
            raise AttributeError(name)
        from consensus_engine.utils.rate_limiter import rate_limiter as default_limiter
        return getattr(default_limiter, name)


rate_limiter = _BotLimiter()

log = logging.getLogger("consensus_engine.scanner.sec_edgar")

_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"

# Forms we care about and their significance.
# NOTE (r27): '144' (insider intent-to-sell) is surfaced so sec_form144.py can read
# it from the same CIK submissions JSON. It is CONTEXT-ONLY — classify_filing_significance
# never scores it and every existing form=='4' filter is unaffected (144 != 4).
_RELEVANT_FORMS = {"8-K", "10-K", "10-Q", "4", "144", "SC 13D", "SC 13G"}

# Cache: ticker → CIK (loaded once from SEC's company_tickers.json)
_ticker_to_cik: dict[str, str] = {}
_ticker_map_lock = asyncio.Lock()
_ticker_map_retry_after = 0.0
_TICKER_MAP_ATTEMPTS = 3


async def _load_ticker_map():
    """Load the full ticker → CIK mapping from SEC. Cached in memory."""
    global _ticker_to_cik, _ticker_map_retry_after
    if _ticker_to_cik:
        return True

    async with _ticker_map_lock:
        if _ticker_to_cik:
            return True
        if time.monotonic() < _ticker_map_retry_after:
            return False

        context = await _bot_sec_context()
        for attempt in range(_TICKER_MAP_ATTEMPTS):
            outcome = await fetch_ticker_map_outcome(context.client, context.limiter, context.clock,
                                                     context.telemetry, context=context)
            if outcome.status == 'ok' or not outcome.retryable or attempt + 1 == _TICKER_MAP_ATTEMPTS:
                break
            await asyncio.sleep(float(2 ** attempt))
        if outcome.status == 'ok':
            _ticker_to_cik = dict(outcome.data)
            _ticker_map_retry_after = 0.0
            rate_limiter.report_success('sec_edgar')
            try:
                from consensus_engine.alerts.ops_alert import report_ops_state
                await report_ops_state(
                    "sec_ticker_map", down=False,
                    failure_class="sec_ticker_map",
                    title="SEC ticker lookup",
                )
            except Exception as exc:
                log.warning("SEC ticker map: could not update outage state: %s",
                            exc)
            return True
        last_error = outcome.reason_code

        rate_limiter.report_failure("sec_edgar")
        _ticker_map_retry_after = time.monotonic() + 30.0
        log.warning("Failed to load SEC ticker map after %d attempts: %s",
                    _TICKER_MAP_ATTEMPTS, last_error)
        try:
            from consensus_engine.alerts.ops_alert import report_ops_state
            await report_ops_state(
                "sec_ticker_map", down=True,
                failure_class="sec_ticker_map",
                title="SEC ticker lookup",
                detail=("The ticker list still could not be downloaded after three tries. "
                        "SEC filing checks cannot match stock symbols until it recovers."),
                fix="If it stays down, check this server's access to sec.gov.",
            )
        except Exception as exc:
            log.warning("SEC ticker map: could not update outage state: %s", exc)
        return False


async def _get_cik(ticker: str) -> Optional[str]:
    """Get the 10-digit zero-padded CIK for a ticker."""
    await _load_ticker_map()
    return _ticker_to_cik.get(ticker.upper())


async def check_recent_filings(ticker: str, hours_back: int = 48) -> list[dict]:
    """Historical bot list adapter; restricted consumers use structured outcomes."""
    if not await rate_limiter.acquire('sec_edgar'):
        return []
    try:
        context = await _bot_sec_context()
        outcome = await fetch_filings_outcome(ticker, hours_back, context)
        if outcome.status == 'ok' and isinstance(outcome.data, _BotSecRows):
            rate_limiter.report_success('sec_edgar')
            return outcome.data.rows
        if outcome.status != 'not_found': rate_limiter.report_failure('sec_edgar')
    except Exception as exc:
        log.warning('SEC EDGAR error for $%s: %s', ticker, exc)
        rate_limiter.report_failure('sec_edgar')
    return []


def _parse_filings_bot(data, cik, hours_back, now):
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    acceptance_times = recent.get("acceptanceDateTime", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    cutoff = now - timedelta(hours=hours_back)
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
    return results


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
    """Legacy permissive list projection of the shared lower fetch boundary."""
    if not accession_number or not primary_document: return []
    # Preserve the historical invalid-CIK exception before transport.
    int(cik)
    try:
        outcome = await fetch_form4_outcome(cik, accession_number, primary_document, await _bot_sec_context())
        return outcome.data.rows if outcome.status == 'ok' and isinstance(outcome.data, _BotSecRows) else []
    except Exception as exc:
        log.debug('Form 4 fetch error: %s', exc)
        return []


def _parse_form4_bot(root):

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


# Explicit collection boundary used by restricted consumers. Legacy bot adapters
# above deliberately retain their historical permissive list/number semantics.
from dataclasses import dataclass, field
from types import MappingProxyType
import math
import re
from consensus_engine.analysis.research_contracts import FetchOutcome, SecFiling, InsiderTransaction
from consensus_engine.utils.provider_budget import retry_after_seconds


@dataclass
class SecContext:
    client: object
    limiter: object
    clock: object
    telemetry: object
    map_url: str = 'https://www.sec.gov/files/company_tickers.json'
    submissions_base: str = 'https://data.sec.gov/submissions'
    archives_base: str = 'https://www.sec.gov/Archives/edgar/data'
    user_agent: str = 'Member research collection'
    sleep: object = asyncio.sleep
    timeout: float = 15.0
    attempts: int = 3
    ticker_map: object = None
    lock: object = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        if not 0 < self.timeout <= 15 or not 1 <= self.attempts <= 3:
            raise ValueError('Bounded SEC transport required')
        _sec_now(self.clock)


def _sec_now(clock):
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware SEC clock required')
    return now


def _cik(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,10}', str(value)) or int(value) <= 0:
        raise ValueError('Invalid CIK')
    return str(value).zfill(10)


def filing_url(cik, accession, document):
    cik = _cik(cik)
    if not isinstance(accession, str) or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession):
        raise ValueError('Invalid accession')
    if not isinstance(document, str) or not re.fullmatch(r'(?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}', document) or '..' in document:
        raise ValueError('Invalid document')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}'


async def _sec_request(url, context, *, xml=False):
    epoch = _sec_now(context.clock).timestamp()
    for attempt in range(context.attempts):
        if not await context.limiter('sec_edgar'):
            return FetchOutcome('unavailable', None, epoch, 'budget_unavailable', True)
        retry_after = None
        try:
            async with context.client.get(url, headers={'User-Agent': context.user_agent},
                                          timeout=aiohttp.ClientTimeout(total=context.timeout)) as response:
                if response.status == 200:
                    if isinstance(context, _BotSecContext):
                        value = await response.text() if xml else await response.json(content_type=None)
                        return FetchOutcome('ok', value, epoch)
                    # Bound content before parsing XML/JSON and expanding records.
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > 4_000_000:
                            return FetchOutcome('unavailable', None, epoch, 'response_too_large')
                        chunks.append(chunk)
                    raw = b''.join(chunks)
                    import json
                    try: value = raw.decode('utf-8') if xml else json.loads(raw)
                    except (ValueError, UnicodeError):
                        return FetchOutcome('unavailable', None, epoch, 'invalid_response')
                    return FetchOutcome('ok', value, epoch)
                retry_after = retry_after_seconds(response.headers.get('Retry-After'), now=epoch)
                reason = ('rate_limited' if response.status == 429 else
                          'access_refused' if response.status in (401, 403) else 'upstream_unavailable')
                retryable = response.status == 429 or response.status >= 500
        except (aiohttp.ClientError, TimeoutError, OSError):
            reason, retryable = 'transport_unavailable', True
        except Exception:
            # Quota denial or injected transport failure: never disclose exception text.
            reason, retryable = 'transport_unavailable', True
        context.telemetry({'event': 'sec_fetch_failure', 'reason_code': reason, 'attempt': attempt + 1})
        # A server hold is returned to the scheduler, never slept beyond this job.
        if not retryable or retry_after is not None or attempt + 1 == context.attempts:
            return FetchOutcome('unavailable', None, epoch, reason, retryable, retry_after)
        await context.sleep(2 ** attempt)


async def fetch_ticker_map_outcome(client, limiter, clock, telemetry, *, context=None):
    context = context or SecContext(client, limiter, clock, telemetry)
    raw = await _sec_request(context.map_url, context)
    if raw.status != 'ok': return raw
    if isinstance(context, _BotSecContext):
        try:
            mapping = {entry.get('ticker','').upper(): str(entry.get('cik_str','')).zfill(10)
                       for entry in raw.data.values() if entry.get('ticker','') and str(entry.get('cik_str',''))}
        except (AttributeError, TypeError): mapping = {}
        if not mapping: return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_ticker_map', True)
        return FetchOutcome('ok', MappingProxyType(mapping), raw.observed_at)
    if not isinstance(raw.data, dict) or not raw.data:
        return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_ticker_map')
    mapping, excluded, ambiguous = {}, [], set()
    for entry in raw.data.values():
        try:
            ticker = entry['ticker']
            if not isinstance(ticker, str) or not re.fullmatch(r'[A-Za-z]{1,12}(?:[.-][A-Za-z]{1,3})?', ticker):
                raise ValueError('Invalid symbol')
            ticker = ticker.upper().replace('-', '.')
            cik = _cik(entry['cik_str'])
            if ticker in ambiguous: raise ValueError('Ambiguous CIK')
            if ticker in mapping and mapping[ticker] != cik:
                mapping.pop(ticker)
                ambiguous.add(ticker)
                raise ValueError('Ambiguous CIK')
            mapping[ticker] = cik
        except (KeyError, TypeError, ValueError): excluded.append('invalid_ticker_entry')
    if not mapping: return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_ticker_map')
    return FetchOutcome('partial' if excluded else 'ok', MappingProxyType(mapping), raw.observed_at,
                        'invalid_ticker_entry' if excluded else None, exclusions=tuple(excluded))


async def resolve_cik_outcome(ticker, context):
    async with context.lock:
        if context.ticker_map is None:
            outcome = await fetch_ticker_map_outcome(context.client, context.limiter, context.clock,
                                                     context.telemetry, context=context)
            if outcome.status in ('ok', 'partial'): context.ticker_map = outcome
        else: outcome = context.ticker_map
    if outcome.status not in ('ok', 'partial'): return outcome
    cik = outcome.data.get(ticker.upper().replace('-', '.'))
    if cik is not None: return FetchOutcome('ok', cik, outcome.observed_at)
    return FetchOutcome('not_found' if outcome.status == 'ok' else 'unavailable', None,
                        outcome.observed_at, 'unsupported_symbol' if outcome.status == 'ok' else 'incomplete_ticker_map')


async def fetch_filings_outcome(ticker, hours_back, context):
    if isinstance(context, _BotSecContext):
        cik = await _get_cik(ticker)
        resolved = FetchOutcome('ok' if cik else 'not_found', cik, _sec_now(context.clock).timestamp())
    else:
        resolved = await resolve_cik_outcome(ticker, context)
    if resolved.status != 'ok': return resolved
    cik = resolved.data
    raw = await _sec_request(f'{context.submissions_base}/CIK{cik}.json', context)
    if raw.status != 'ok': return raw
    if isinstance(context, _BotSecContext):
        try:
            rows = _parse_filings_bot(raw.data, cik, hours_back, _sec_now(context.clock))
            return FetchOutcome('ok', _BotSecRows(rows), raw.observed_at)
        except Exception:
            return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_filings_structure')
    keys = ('form', 'filingDate', 'acceptanceDateTime', 'accessionNumber', 'primaryDocument')
    try:
        if _cik(raw.data['cik']) != cik: raise ValueError('Wrong CIK')
        recent = raw.data['filings']['recent']
        if not all(isinstance(recent[key], list) for key in keys): raise ValueError('Wrong arrays')
        if len({len(recent[key]) for key in keys}) != 1: raise ValueError('Unaligned arrays')
    except (KeyError, TypeError, ValueError):
        return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_filings_structure')
    cutoff = _sec_now(context.clock) - timedelta(hours=hours_back)
    results, exclusions = [], []
    for values in zip(*(recent[key][:50] for key in keys)):
        form, filed_date, accepted, accession, document = values
        try:
            if not all(isinstance(value, str) for value in values): raise ValueError('Invalid row')
            if form not in _RELEVANT_FORMS: continue
            datetime.strptime(filed_date, '%Y-%m-%d')
            # Missing acceptance time may use the valid filing date; malformed time may not.
            dt = datetime.fromisoformat(accepted.replace('Z', '+00:00')) if accepted else datetime.strptime(filed_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if dt.tzinfo is None: raise ValueError('Naive acceptance time')
            url = filing_url(cik, accession, document)
            if dt < cutoff: continue
            results.append(SecFiling(form, filed_date, accepted, accession, document, cik, dt.timestamp(), url))
        except (ValueError, TypeError): exclusions.append('invalid_filing_row')
    if exclusions and not results: return FetchOutcome('unavailable', None, raw.observed_at, 'invalid_filing_rows', exclusions=tuple(exclusions))
    return FetchOutcome('partial' if exclusions else 'ok', tuple(results), raw.observed_at,
                        'excluded_filing_rows' if exclusions else None, exclusions=tuple(exclusions))


async def fetch_form4_outcome(cik, accession_number, primary_document, context):
    epoch = _sec_now(context.clock).timestamp()
    try:
        if not isinstance(context, _BotSecContext):
            filing_url(cik, accession_number, primary_document)
        path = f'{int(cik)}/{accession_number.replace("-", "")}/{primary_document.split("/")[-1]}'
    except (ValueError, TypeError): return FetchOutcome('unavailable', None, epoch, 'invalid_filing_metadata')
    raw = await _sec_request(f'{context.archives_base}/{path}', context, xml=True)
    if raw.status != 'ok': return raw
    try:
        if '<!DOCTYPE' in raw.data.upper() or '<!ENTITY' in raw.data.upper(): raise ValueError('Unsafe XML')
        root = ET.fromstring(raw.data)
        if not isinstance(context, _BotSecContext) and root.tag != 'ownershipDocument': raise ValueError('Wrong document')
    except (ET.ParseError, ValueError): return FetchOutcome('unavailable', None, epoch, 'invalid_form4')
    if isinstance(context, _BotSecContext):
        return FetchOutcome('ok', _BotSecRows(_parse_form4_bot(root)), epoch)
    def val(node, tag):
        item = node.find(f'.//{tag}/value')
        if item is None: item = node.find(f'.//{tag}')
        return (item.text or '').strip() if item is not None else ''
    reporter = val(root, 'rptOwnerName')
    if not reporter: return FetchOutcome('unavailable', None, epoch, 'invalid_form4_identity')
    title = val(root, 'officerTitle') or ('Director' if val(root, 'isDirector') == '1' else 'Insider')
    transactions, exclusions = [], []
    for tx in root.findall('.//nonDerivativeTransaction') + root.findall('.//derivativeTransaction'):
        try:
            date = val(tx, 'transactionDate')
            datetime.strptime(date, '%Y-%m-%d')
            code = val(tx, 'transactionAcquiredDisposedCode')
            if code not in ('A', 'D'): raise ValueError('Invalid direction')
            numbers = []
            for tag in ('transactionShares', 'transactionPricePerShare'):
                text = val(tx, tag)
                number = float(text) if text else None
                if number is not None and (not math.isfinite(number) or number < 0): raise ValueError('Invalid numeric field')
                numbers.append(number)
            tx_code = val(tx, 'transactionCode')
            label = {'P': 'Open Market Purchase', 'S': 'Open Market Sale', 'A': 'Award/Grant', 'F': 'Tax Withholding',
                     'M': 'Option Exercise', 'G': 'Gift', 'D': 'Disposition'}.get(tx_code, 'Transaction')
            transactions.append(InsiderTransaction(reporter, title, val(tx, 'securityTitle'), date, *numbers,
                                                   'Buy' if code == 'A' else 'Sell', label))
            if None in numbers: exclusions.append('missing_transaction_value')
        except ValueError: exclusions.append('invalid_transaction')
    if exclusions and not transactions: return FetchOutcome('unavailable', None, epoch, 'invalid_transactions', exclusions=tuple(exclusions))
    return FetchOutcome('partial' if exclusions else 'ok', tuple(transactions), epoch,
                        'incomplete_transactions' if exclusions else None, exclusions=tuple(exclusions))


@dataclass(frozen=True)
class _BotSecRows:
    """Historical unvalidated rows; never accepted as member records."""
    rows: list


class _BotSecContext(SecContext):
    bot_compat = True


async def _bot_sec_context():
    async def admitted(_): return True
    return _BotSecContext(await get_session(), admitted, lambda: datetime.now(timezone.utc),
                          lambda event: None, attempts=1, user_agent=_USER_AGENT)
