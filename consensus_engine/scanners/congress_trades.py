"""r13: Congressional (STOCK Act) trading tracker — House only, CONTEXT ONLY.

NON-EDGAR, free House Clerk disclosure feed (probed live 2026-07-08):

    INDEX  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
           -> {YEAR}FD.txt  (tab-separated: Prefix Last First Suffix FilingType
              StateDst Year FilingDate DocID). FilingType == 'P' == Periodic
              Transaction Report (an actual stock trade).
    PTR    https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{YEAR}/{DocID}.pdf
           -> machine-readable via pdfplumber. Each transaction line carries an asset
              name + ticker in parens, a P/S/E transaction type, transaction + notify
              dates, and an amount RANGE, e.g.:
                  Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000

Reports lag up to ~45 statutory days, so this is SLOW context — a per-ticker
confirmation leg, never a standalone instant alert. Default OFF; shadow-logs to
`congress_trades`, deduped by DocID. Senate side (efdsearch.senate.gov, gated) is
DEFERRED. All user-facing dates render in PDT (never ET) per project rule — the
stored strings are the feed's raw MM/DD/YYYY (identity only).

HTTP hardening mirrors scanners/trading_halts.py: no redirects, final-URL host
re-validated to disclosures-clerk.house.gov, response body size-capped, [] on error.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger(__name__)

_HOST = "disclosures-clerk.house.gov"
_ALLOWED_DOMAIN_SUFFIX = "house.gov"
_MAX_RESPONSE_BYTES = 25 * 1024 * 1024   # index zip ~48 KB, PTR PDFs << 1 MB
_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"

# One complete transaction: ticker in parens, an optional [ST]-style asset-type tag,
# a P/S/E code (optionally "(partial)"/"(full)"), two dates, an amount range. The
# type code must follow ITS OWN ticker (only whitespace + an optional bracket tag
# between), so the match can never bridge into the next line's ticker — a dangling
# wrapped asset line simply yields no match (best-effort, degrades to no-data).
_TXN_RE = re.compile(
    r"\(([A-Z][A-Z.]{0,5})\)"                # ticker
    r"\s*(?:\[[A-Z]{1,4}\]\s*)?"             # optional [ST]/[OP] asset-type tag
    r"([PSE])\b"                             # transaction type
    r"(?:\s*\((?:partial|full)\))?"          # optional (partial)/(full)
    r"\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})"   # txn date, notify date
    r"\s+\$([\d,]+)\s*-\s*\$([\d,]+)"        # amount range
)


def _validate_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host == _HOST or host.endswith("." + _ALLOWED_DOMAIN_SUFFIX)
    except Exception:
        return False


async def _hardened_get_bytes(url: str, timeout_sec: float = 30.0) -> Optional[bytes]:
    """Fetch a URL's bytes with the trading_halts security guarantees; None on error."""
    if not _validate_url(url):
        log.error("[r13] URL failed domain validation: %s", url)
        return None
    try:
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    log.warning("[r13] redirect refused for %s (status=%d)", url, resp.status)
                    return None
                if resp.status != 200:
                    log.debug("[r13] status %d for %s", resp.status, url)
                    return None
                if not _validate_url(str(resp.url)):
                    log.error("[r13] response URL failed domain check: %s", resp.url)
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        log.error("[r13] response for %s exceeds %d byte cap", url, _MAX_RESPONSE_BYTES)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
    except asyncio.TimeoutError:
        log.warning("[r13] timeout fetching %s", url)
        return None
    except Exception as exc:  # noqa: BLE001 — a fetch error is a skip, never fatal
        log.warning("[r13] fetch error for %s: %s", url, exc)
        return None


def parse_index_txt(raw_txt: str) -> list[dict]:
    """Parse {YEAR}FD.txt into a list of FilingType=='P' (Periodic Transaction Report) rows."""
    lines = raw_txt.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    out: list[dict] = []
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        if row.get("FilingType") == "P":
            out.append(row)
    return out


async def fetch_house_ptr_index(year: int) -> list[dict]:
    """Download + parse {YEAR}FD.zip -> the year's FilingType=='P' index rows. [] on error."""
    url = f"https://{_HOST}/public_disc/financial-pdfs/{year}FD.zip"
    raw = await _hardened_get_bytes(url)
    if not raw:
        return []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        txt = zf.read(f"{year}FD.txt").decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log.warning("[r13] index unzip/parse error for %d: %s", year, exc)
        return []
    rows = parse_index_txt(txt)
    log.info("[r13] %dFD index: %d Periodic Transaction Report rows", year, len(rows))
    return rows


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Blocking pdfplumber text extraction (run in an executor). '' on any error."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # noqa: BLE001 — scanned/encrypted PDFs degrade to ''
        log.debug("[r13] pdfplumber extract error: %s", exc)
        return ""


def parse_ptr_text(text: str, tracked: Optional[set[str]] = None) -> list[dict]:
    """Extract transaction dicts from PTR PDF text. Filters to ``tracked`` when given.

    Each dict: ticker, txn_type (P/S/E), txn_date, notification_date, amount_range,
    amount_low. Best-effort: unmatched/scanned PDFs yield [].
    """
    out: list[dict] = []
    seen: set[tuple] = set()
    for m in _TXN_RE.finditer(text or ""):
        ticker = m.group(1).upper().strip(".")
        if tracked is not None and ticker not in tracked:
            continue
        txn_type = m.group(2)
        txn_date = m.group(3)
        notify_date = m.group(4)
        low_raw = m.group(5).replace(",", "")
        high_raw = m.group(6)
        try:
            amount_low = float(low_raw)
        except ValueError:
            amount_low = None
        key = (ticker, txn_type, txn_date)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "ticker": ticker,
            "txn_type": txn_type,
            "txn_date": txn_date,
            "notification_date": notify_date,
            "amount_range": f"${m.group(5)} - ${high_raw}",
            "amount_low": amount_low,
        })
    return out


def _parse_filed_date(s: str) -> Optional[datetime]:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass
class CongressTradeContext:
    ticker: str
    trades: list[dict] = field(default_factory=list)


async def scan_congress_trades(
    year: Optional[int] = None,
    freshness_days: Optional[int] = None,
    max_pdfs: Optional[int] = None,
) -> list[CongressTradeContext]:
    """Scan the House PTR feed for trades touching tracked tickers; shadow-log + aggregate.

    Bounded: only the most-recent ``max_pdfs`` PTRs within ``freshness_days`` are
    fetched/parsed per cycle (the feed lists hundreds; PDFs are the cost). Each matched
    transaction is shadow-logged (idempotent on DocID+ticker+type+date). Returns a
    per-ticker context aggregate for tracked tickers that appear.
    """
    if freshness_days is None:
        freshness_days = int(cfg.get("features.congress_trades.freshness_days", 45))
    if max_pdfs is None:
        max_pdfs = int(cfg.get("features.congress_trades.max_pdfs_per_cycle", 40))
    if year is None:
        year = datetime.now(timezone.utc).year

    tracked = {t.upper() for t in await db.get_active_tickers(min_signals=1)}
    if not tracked:
        return []

    rows = await fetch_house_ptr_index(year)
    if not rows and year > 2000:
        rows = await fetch_house_ptr_index(year - 1)  # early-January fallback to prior year
    if not rows:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=freshness_days)
    fresh = []
    for r in rows:
        fd = _parse_filed_date(r.get("FilingDate", ""))
        if fd is None or fd >= cutoff:
            fresh.append((fd, r))
    # Newest first; unknown-date rows sort last.
    fresh.sort(key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    by_ticker: dict[str, CongressTradeContext] = {}
    loop = asyncio.get_event_loop()
    processed = 0
    for _fd, row in fresh:
        if processed >= max_pdfs:
            break
        doc_id = (row.get("DocID") or "").strip()
        if not doc_id or not doc_id.isdigit():
            continue
        pdf_year = (row.get("Year") or str(year)).strip() or str(year)
        pdf_url = f"https://{_HOST}/public_disc/ptr-pdfs/{pdf_year}/{doc_id}.pdf"
        pdf_bytes = await _hardened_get_bytes(pdf_url)
        processed += 1
        if not pdf_bytes:
            continue
        text = await loop.run_in_executor(None, _extract_pdf_text, pdf_bytes)
        if not text:
            continue
        member = f"{row.get('First','').strip()} {row.get('Last','').strip()}".strip()
        for tx in parse_ptr_text(text, tracked=tracked):
            try:
                await db.insert_congress_trade(
                    doc_id=doc_id,
                    ticker=tx["ticker"],
                    member_name=member,
                    txn_type=tx["txn_type"],
                    txn_date=tx["txn_date"],
                    notification_date=tx["notification_date"],
                    amount_range=tx["amount_range"],
                    amount_low=tx["amount_low"],
                    filed_date=row.get("FilingDate"),
                )
            except Exception as e:  # noqa: BLE001 — shadow-log failure never voids the scan
                log.debug("[r13] congress shadow-log error %s/%s: %s", doc_id, tx["ticker"], e)
            ctx = by_ticker.setdefault(tx["ticker"], CongressTradeContext(ticker=tx["ticker"]))
            ctx.trades.append({**tx, "member": member, "doc_id": doc_id})

    if by_ticker:
        log.info("[r13] congress: %d ticker(s) matched across %d PTR(s) scanned",
                 len(by_ticker), processed)
    return list(by_ticker.values())


def build_congress_context_line(ctx: CongressTradeContext) -> Optional[str]:
    """One insider-display context line for a ticker's recent Congressional trades, or None."""
    if not ctx.trades:
        return None
    buys = sum(1 for t in ctx.trades if t.get("txn_type") == "P")
    sells = sum(1 for t in ctx.trades if t.get("txn_type") == "S")
    members = sorted({t.get("member", "").strip() for t in ctx.trades if t.get("member")})
    who = members[0] if len(members) == 1 else f"{len(members)} members"
    bits = []
    if buys:
        bits.append(f"{buys} buy(s)")
    if sells:
        bits.append(f"{sells} sell(s)")
    action = ", ".join(bits) if bits else f"{len(ctx.trades)} trade(s)"
    return f"🏛️ Congress (House): {who} disclosed {action} (STOCK Act, lagged)"
