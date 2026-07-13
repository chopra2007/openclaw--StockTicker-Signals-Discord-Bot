"""FINRA twice-monthly SETTLEMENT short-interest scanner (r12, standalone-scanners).

DISTINCT product from the daily short-VOLUME scanner (finra_short_volume.py):
this fetches FINRA's official consolidated **settlement short interest** — the
number of shares short as of each twice-monthly settlement date — plus FINRA's
own averageDailyVolumeQuantity and daysToCoverQuantity, and the bi-monthly change
vs the prior settlement. Persists per-ticker rows to ``finra_short_interest``.

Feed (probed live 2026-07-08, NO auth):
    POST https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest
    Accept: text/plain  -> quoted CSV. Columns (header row):
      accountingYearMonthNumber, symbolCode, issueName,
      issuerServicesGroupExchangeCode, marketClassCode,
      currentShortPositionQuantity, previousShortPositionQuantity, stockSplitFlag,
      averageDailyVolumeQuantity, daysToCoverQuantity, revisionFlag,
      changePercent, changePreviousNumber, settlementDate

Security requirements (cloned from finra_short_volume.py's hardened fetch):
  - ``allow_redirects=False``: the API URL must not redirect.
  - Domain re-validation: final URL host must be ``api.finra.org``.
  - Response-size cap: read at most 10 MB then abort (iter_chunked).
  - dtype-pinned parse: float()->int() the numeric columns; rows that fail
    conversion are skipped — never eval or loose-parse.

Provenance label (hard render rule — never change):
    ``"settlement short interest (FINRA, twice-monthly)"``

The data updates only ~2x/month and is published ~8 days after each settlement,
so the loop re-checks a few times a day (cheap; upsert is idempotent).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from datetime import date, datetime, timedelta

import aiohttp

from consensus_engine import db

log = logging.getLogger(__name__)

# Hard provenance label — NEVER change; distinguishes settlement short-INTEREST
# from the daily short-VOLUME proxy the other scanner ingests.
FINRA_SHORT_INTEREST_PROVENANCE = "settlement short interest (FINRA, twice-monthly)"

# FINRA consolidated short-interest query endpoint (public, no auth).
_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

# Maximum response size: 10 MB (mirrors finra_short_volume).
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Allowed host for the URL (security: no-redirect + host re-validation).
_ALLOWED_HOST = "api.finra.org"

# How far back to request settlements (days). ~120 days covers the most recent
# ~8 twice-monthly settlements even accounting for FINRA's publication lag.
_DEFAULT_LOOKBACK_DAYS = 120


def _validate_url(url: str) -> bool:
    """Return True only when the URL's host is api.finra.org (or a subdomain)."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return host == _ALLOWED_HOST or host.endswith("." + _ALLOWED_HOST)
    except Exception:
        return False


def _parse_short_interest_csv(raw_text: str, tickers: set[str] | None = None) -> list[dict]:
    """Parse the FINRA consolidated short-interest quoted CSV.

    Returns a list of dicts with keys:
      symbol, settlement_date, short_interest, avg_daily_volume, days_to_cover,
      prev_short_interest, pct_change

    Columns are mapped BY HEADER NAME (robust to column reorder). Rows that fail
    int()/float() conversion on the required short-interest column are skipped.
    Only rows for tickers in ``tickers`` are kept when ``tickers`` is non-None.
    """
    results: list[dict] = []
    if not raw_text.strip():
        return results
    reader = csv.reader(io.StringIO(raw_text))
    rows = list(reader)
    if not rows:
        return results
    header = [h.strip() for h in rows[0]]
    try:
        idx = {name: header.index(name) for name in (
            "symbolCode", "settlementDate", "currentShortPositionQuantity",
        )}
    except ValueError:
        log.warning("[r12] unexpected FINRA short-interest header: %r", header[:6])
        return results

    def _col(row: list[str], name: str) -> str:
        i = header.index(name) if name in header else -1
        return row[i].strip() if 0 <= i < len(row) else ""

    for row in rows[1:]:
        if len(row) < len(header):
            continue
        symbol = row[idx["symbolCode"]].strip()
        if not symbol:
            continue
        if tickers is not None and symbol not in tickers:
            continue
        # dtype-pinned parse — never eval or loose-parse. Required column first.
        try:
            short_interest = int(float(row[idx["currentShortPositionQuantity"]]))
        except (ValueError, IndexError):
            log.debug("[r12] skipping non-numeric short-interest row: %r", row[:6])
            continue
        if short_interest < 0:
            continue

        def _opt_int(name: str) -> int | None:
            v = _col(row, name)
            try:
                return int(float(v)) if v else None
            except ValueError:
                return None

        def _opt_float(name: str) -> float | None:
            v = _col(row, name)
            try:
                return float(v) if v else None
            except ValueError:
                return None

        settlement_date = _col(row, "settlementDate")
        # Normalise settlement_date to YYYY-MM-DD (the feed already uses it).
        try:
            settlement_date = datetime.strptime(settlement_date[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            log.debug("[r12] unparseable settlement date: %r", settlement_date)
            continue

        results.append({
            "symbol": symbol,
            "settlement_date": settlement_date,
            "short_interest": short_interest,
            "avg_daily_volume": _opt_int("averageDailyVolumeQuantity"),
            "days_to_cover": _opt_float("daysToCoverQuantity"),
            "prev_short_interest": _opt_int("previousShortPositionQuantity"),
            "pct_change": _opt_float("changePercent"),
        })
    return results


async def fetch_finra_short_interest(
    ticker: str,
    *,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    timeout_sec: float = 30.0,
) -> list[dict]:
    """Fetch recent settlement short-interest rows for ONE ticker.

    Returns a list of parsed row dicts (newest last, feed order). Returns [] on
    any error — never raises.

    Security guarantees mirror finra_short_volume.fetch_finra_short_volume:
      - allow_redirects=False (no silent redirect followed)
      - URL host validated before + after (api.finra.org only)
      - Response body capped at _MAX_RESPONSE_BYTES (~10 MB)
    """
    if not _validate_url(_URL):
        log.error("[r12] URL failed host validation: %s", _URL)
        return []

    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    body = json.dumps({
        "limit": 24,
        "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": ticker.upper()},
        ],
        "dateRangeFilters": [
            {"fieldName": "settlementDate", "startDate": start, "endDate": end},
        ],
    })
    headers = {"Content-Type": "application/json", "Accept": "text/plain"}

    try:
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                _URL,
                data=body,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    log.warning("[r12] redirect refused for %s (status=%d)", _URL, resp.status)
                    return []
                if resp.status != 200:
                    log.warning("[r12] unexpected status %d for %s ($%s)", resp.status, _URL, ticker)
                    return []
                if not _validate_url(str(resp.url)):
                    log.error("[r12] response URL failed host check: %s", resp.url)
                    return []
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        log.error("[r12] response for $%s exceeds %d byte cap — aborting",
                                  ticker, _MAX_RESPONSE_BYTES)
                        return []
                    chunks.append(chunk)
                raw_text = b"".join(chunks).decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        log.warning("[r12] timeout fetching short interest for $%s", ticker)
        return []
    except Exception as exc:
        log.warning("[r12] fetch error for $%s: %s", ticker, exc)
        return []

    rows = _parse_short_interest_csv(raw_text, tickers={ticker.upper()})
    rows.sort(key=lambda r: r["settlement_date"])  # chronological (newest last)
    log.info("[r12] parsed %d settlement rows for $%s", len(rows), ticker)
    return rows


async def ingest_short_interest(
    tickers: set[str] | None = None,
    *,
    published_at: float | None = None,
) -> int:
    """Fetch + persist recent settlement rows for tracked tickers.

    Returns the number of rows upserted (0 on failure). ``tickers`` defaults to
    the active-ticker set (unexpired ticker_signals), keeping the table bounded.
    ``published_at`` defaults to ``time.time()`` (ingestion time).
    """
    if published_at is None:
        published_at = time.time()

    if tickers is None:
        try:
            tickers = set(await db.get_active_tickers(min_signals=1))
        except Exception as exc:
            log.warning("[r12] could not fetch active tickers: %s", exc)
            tickers = set()

    if not tickers:
        log.info("[r12] no tracked tickers — skipping short-interest ingest")
        return 0

    inserted = 0
    for ticker in sorted(tickers):
        rows = await fetch_finra_short_interest(ticker)
        for row in rows:
            try:
                await db.upsert_finra_short_interest(
                    ticker=row["symbol"],
                    settlement_date=row["settlement_date"],
                    short_interest=row["short_interest"],
                    avg_daily_volume=row["avg_daily_volume"],
                    days_to_cover=row["days_to_cover"],
                    prev_short_interest=row["prev_short_interest"],
                    pct_change=row["pct_change"],
                    published_at=published_at,
                )
                inserted += 1
            except Exception as exc:
                log.warning("[r12] DB write failed for %s %s: %s",
                            row["symbol"], row["settlement_date"], exc)
    log.info("[r12] ingested %d settlement rows across %d tickers", inserted, len(tickers))
    return inserted


async def finra_short_interest_loop(stop_event) -> None:
    """Twice-daily FINRA settlement short-interest ingest so the r12 days-to-cover
    confluence leg has FRESH data.

    Ingests when features.short_interest.enabled OR features.short_interest.collect
    is true (collect:true shadow-fills the table without turning on the r12 score
    leg, which stays gated on .enabled ONLY in cross_reference). FINRA short interest
    updates only ~2x/month (published ~8 days after settlement), so a twice-daily
    re-check is ample; the upsert is idempotent."""
    from consensus_engine import config as cfg
    interval = int(cfg.get("intervals.finra_short_interest_loop", 43200))  # 12h
    while not stop_event.is_set():
        try:
            if (cfg.get("features.short_interest.enabled", False)
                    or cfg.get("features.short_interest.collect", False)):
                await ingest_short_interest()
        except Exception as exc:
            log.error("finra_short_interest_loop error: %s", exc, exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
