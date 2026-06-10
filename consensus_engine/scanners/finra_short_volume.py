"""FINRA consolidated daily short-volume scanner (E1, signal-features-2026-06-09).

Fetches the FINRA RegSho daily consolidated short-sale volume file (CNMS series)
and persists per-ticker short-volume rows to the ``finra_short_volume`` DB table.

Security requirements (from the plan):
  - Response-size cap: read at most 10 MB then abort.
  - ``allow_redirects=False``: the CDN URL must not redirect.
  - Domain validation: final URL hostname must end with ``cdn.finra.org``.
  - dtype-pinned parse: int() the three volume columns; rows that fail int()
    conversion are skipped — never eval or loose-parse.

``short_pct`` computation (spec: net out ShortExemptVolume):
    short_pct = (ShortVolume - ShortExemptVolume) / TotalVolume

Provenance label (spec — hard render rule, never change):
    ``"short-volume %, MM-hedging-inflated proxy"``

File format (CNMS):
    Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

The file is published after market close (EOD). ``finra_published_at`` is set to
the time the row is ingested so the recency_window freshness check works correctly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import aiohttp

from consensus_engine import db

log = logging.getLogger(__name__)

# Hard provenance label — NEVER change; used as a constant by any future render code.
FINRA_SHORT_VOL_PROVENANCE = "short-volume %, MM-hedging-inflated proxy"

# CNMS daily file URL template.
_URL_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"

# Maximum response size: 10 MB (spec).
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB

# Allowed domain suffix for the URL (security: no-redirect + domain re-validation).
_ALLOWED_DOMAIN_SUFFIX = "cdn.finra.org"


def _make_url(trade_date: date) -> str:
    """Return the CNMS file URL for a given trade date."""
    return _URL_TEMPLATE.format(date=trade_date.strftime("%Y%m%d"))


def _validate_url(url: str) -> bool:
    """Return True only when the URL's host ends with cdn.finra.org."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return host == _ALLOWED_DOMAIN_SUFFIX or host.endswith("." + _ALLOWED_DOMAIN_SUFFIX)
    except Exception:
        return False


def _parse_finra_file(raw_text: str, tickers: set[str] | None = None) -> list[dict]:
    """Parse a FINRA CNMS short-volume pipe-delimited file.

    Returns a list of dicts with keys:
      symbol, short_volume, short_exempt_volume, total_volume, short_pct, trade_date

    Only rows for tickers in ``tickers`` are kept when ``tickers`` is non-None.
    Rows that fail int() column conversion are skipped with a debug log.
    """
    results: list[dict] = []
    lines = raw_text.splitlines()
    # Skip header line (Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market)
    for line in lines:
        line = line.strip()
        if not line or line.startswith("Date"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            log.debug("[E1] skipping short line: %r", line[:80])
            continue
        date_str, symbol = parts[0], parts[1]
        # dtype-pinned parse — never eval or loose-parse. The live CNMS file
        # carries FRACTIONAL share volumes (e.g. "444175.935740" — consolidated
        # tape fractional shares), so parse as float (raises on garbage) and
        # round down to whole shares. int() alone rejected every such row,
        # which made the first live backfill insert 0 rows (2026-06-10).
        try:
            short_vol = int(float(parts[2]))
            short_exempt_vol = int(float(parts[3]))
            total_vol = int(float(parts[4]))
        except (ValueError, IndexError):
            log.debug("[E1] skipping non-numeric row: %r", line[:80])
            continue
        if total_vol <= 0:
            continue
        if tickers is not None and symbol not in tickers:
            continue
        # Spec: net out ShortExemptVolume
        net_short = short_vol - short_exempt_vol
        short_pct = net_short / total_vol
        # Parse trade date from the file
        try:
            trade_date_obj = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            log.debug("[E1] unparseable date in row: %r", date_str)
            continue
        results.append({
            "symbol": symbol,
            "short_volume": short_vol,
            "short_exempt_volume": short_exempt_vol,
            "total_volume": total_vol,
            "short_pct": short_pct,
            "trade_date": trade_date_obj.isoformat(),
        })
    return results


async def fetch_finra_short_volume(
    trade_date: date,
    tickers: set[str] | None = None,
    *,
    timeout_sec: float = 30.0,
) -> list[dict]:
    """Fetch and parse FINRA CNMS short-volume file for one trade date.

    Returns a list of parsed row dicts (see ``_parse_finra_file``).
    Returns [] on 404 (weekend/holiday) or any error — never raises.

    Security guarantees:
      - allow_redirects=False (no silent redirect followed)
      - URL domain validated before reading (cdn.finra.org only)
      - Response body capped at _MAX_RESPONSE_BYTES (~10 MB)
    """
    url = _make_url(trade_date)
    if not _validate_url(url):
        log.error("[E1] URL failed domain validation: %s", url)
        return []

    try:
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                # 3xx redirect -> security policy: do not follow
                if resp.status in (301, 302, 303, 307, 308):
                    log.warning("[E1] redirect refused for %s (status=%d)", url, resp.status)
                    return []
                if resp.status == 404:
                    log.debug("[E1] 404 for %s (weekend/holiday)", url)
                    return []
                if resp.status != 200:
                    log.warning("[E1] unexpected status %d for %s", resp.status, url)
                    return []
                # Validate the actual URL responded to (no unexpected redirect slip)
                if not _validate_url(str(resp.url)):
                    log.error("[E1] response URL failed domain check: %s", resp.url)
                    return []
                # Size-capped read. NOTE: stream .read(n) returns as soon as the
                # FIRST network chunk arrives (at most n bytes, not exactly n) —
                # a single read() call silently truncated the file to its first
                # ~chunk and only A-tickers parsed (found live 2026-06-10).
                # Accumulate chunks until EOF, aborting past the cap.
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        log.error(
                            "[E1] response for %s exceeds %d byte cap — aborting",
                            url, _MAX_RESPONSE_BYTES,
                        )
                        return []
                    chunks.append(chunk)
                raw_text = b"".join(chunks).decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        log.warning("[E1] timeout fetching %s", url)
        return []
    except Exception as exc:
        log.warning("[E1] fetch error for %s: %s", url, exc)
        return []

    rows = _parse_finra_file(raw_text, tickers=tickers)
    log.info(
        "[E1] parsed %d rows from %s (tickers_filter=%d)",
        len(rows), url, len(tickers) if tickers else -1,
    )
    return rows


async def ingest_finra_day(
    trade_date: date,
    tickers: set[str] | None = None,
    *,
    finra_published_at: float | None = None,
) -> int:
    """Fetch + persist all tracked-ticker rows for one trade date.

    Returns the number of rows inserted (0 on failure or weekend/holiday).
    ``finra_published_at`` defaults to ``time.time()`` (ingestion time).

    Ticker-set decision (spec: filter to tickers we track):
      Accepts an explicit ``tickers`` argument.  When ``None``, fetches the
      active-ticker set from ``db.get_active_tickers()`` (unexpired ticker_signals).
      This keeps the table bounded to what the engine cares about (~10k symbols
      in the full file vs. a few dozen active tickers).
    """
    if finra_published_at is None:
        finra_published_at = time.time()

    if tickers is None:
        try:
            tickers_list = await db.get_active_tickers(min_signals=1)
            tickers = set(tickers_list)
        except Exception as exc:
            log.warning("[E1] could not fetch active tickers: %s", exc)
            tickers = set()

    if not tickers:
        log.info("[E1] no tracked tickers — skipping FINRA ingest for %s", trade_date)
        return 0

    rows = await fetch_finra_short_volume(trade_date, tickers=tickers)
    if not rows:
        return 0

    inserted = 0
    for row in rows:
        try:
            await db.upsert_finra_short_volume(
                ticker=row["symbol"],
                trade_date=row["trade_date"],
                total_volume=row["total_volume"],
                short_volume=row["short_volume"],
                short_exempt_volume=row["short_exempt_volume"],
                short_pct=row["short_pct"],
                finra_published_at=finra_published_at,
            )
            inserted += 1
        except Exception as exc:
            log.warning("[E1] DB write failed for %s %s: %s", row["symbol"], trade_date, exc)
    log.info("[E1] ingested %d/%d rows for %s", inserted, len(rows), trade_date)
    return inserted
