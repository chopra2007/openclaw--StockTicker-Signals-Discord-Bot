"""Nasdaq/NYSE trading-halt tripwire (r14).

Fetches the public Nasdaq Trader trade-halts RSS feed and, for any halt on a
ticker we actively track, fires an INSTANT Discord alert. Per CLAUDE.md's Alert
Philosophy a trading halt is an explicit instant-trigger exception (no second
source required) — a halt is a hard, unambiguous market event.

Feed: http://www.nasdaqtrader.com/rss.aspx?feed=tradehalts
    RSS 2.0 with an ``xmlns:ndaq="http://www.nasdaqtrader.com/"`` namespace. Each
    <item> carries ndaq:-prefixed fields (confirmed live 2026-07-07):
        HaltDate (MM/DD/YYYY), HaltTime (HH:MM:SS.mmm, Eastern),
        IssueSymbol, IssueName, Market, ReasonCode,
        ResumptionDate, ResumptionQuoteTime, ResumptionTradeTime.
    Feed times are Eastern (exchange local); we NEVER surface Eastern — the alert
    renders every time in Pacific via ZoneInfo("America/Los_Angeles").

HTTP hardening (mirrors scanners/finra_short_volume.py):
    - allow_redirects=False (the feed URL must not redirect elsewhere)
    - final-URL host re-validated to end with nasdaqtrader.com
    - response body capped (~5 MB; the live feed is ~90 KB)
    - returns [] on any error — never raises

Dedup: every alerted halt is recorded in the ``trading_halts`` DB table keyed on
(symbol, halt_ts, reason_code), so re-polling the same feed NEVER re-alerts the
same halt. See db.upsert_trading_halt / db.get_trading_halt.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger(__name__)

# Public Nasdaq Trader trade-halts RSS feed.
FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"  # https direct: http 301-redirects and the hardened fetch refuses redirects

# Allowed domain suffix (security: no-redirect + domain re-validation).
_ALLOWED_DOMAIN_SUFFIX = "nasdaqtrader.com"

# Response-size cap. Live feed is ~90 KB; 5 MB is a generous abort ceiling.
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Exchange-local timezone of the feed's clock (Eastern). Parsed internally ONLY;
# never surfaced. All user-facing times convert to Pacific below.
_ET = ZoneInfo("America/New_York")
_PT = ZoneInfo("America/Los_Angeles")  # the user's timezone — the only tz ever shown

# Human labels for the well-documented Nasdaq halt reason codes. Any code not in
# this map still alerts and shows its raw code — no meaning is fabricated.
_REASON_LABELS: dict[str, str] = {
    "LUDP": "Volatility Trading Pause",
    "T1": "News Pending",
    "T2": "News Released",
    "T5": "Single-Stock Trading Pause",
    "T6": "Extraordinary Market Activity",
    "T12": "Additional Information Requested",
    "H10": "SEC Trading Suspension",
    "H4": "Non-compliance",
    "D": "Deficiency / Delisting",
    "IPO1": "IPO Not Yet Trading",
}


def _validate_url(url: str) -> bool:
    """Return True only when the URL's host is (a subdomain of) nasdaqtrader.com."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return host == _ALLOWED_DOMAIN_SUFFIX or host.endswith("." + _ALLOWED_DOMAIN_SUFFIX)
    except Exception:
        return False


def _field(item_xml: str, tag: str) -> str:
    """Extract the text of an ndaq:<tag> element from one <item> block.

    Returns "" for empty/self-closing tags (e.g. <ndaq:ResumptionTradeTime />)."""
    m = re.search(rf"<ndaq:{tag}>(.*?)</ndaq:{tag}>", item_xml, re.S)
    return m.group(1).strip() if m else ""


def _parse_et_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse a feed date (MM/DD/YYYY) + time (HH:MM:SS[.ms]) as an ET datetime.

    Returns None when either part is missing/unparseable (e.g. a halt with no
    resumption time yet)."""
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()
    if not date_str or not time_str:
        return None
    time_str = time_str.split(".")[0]  # drop milliseconds
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=_ET)


def _fmt_pt(dt_et: datetime | None) -> str | None:
    """Render an ET datetime in Pacific time (e.g. '10:07 AM PDT · Jul 07'). None-safe."""
    if dt_et is None:
        return None
    dt_pt = dt_et.astimezone(_PT)
    # %Z on America/Los_Angeles yields PDT (summer) / PST (winter) — always Pacific,
    # never Eastern. Matches utils/time_context.py house style.
    return f"{dt_pt.strftime('%I:%M %p %Z')} · {dt_pt.strftime('%b %d')}"


def _parse_halts_feed(raw_xml: str, tickers: set[str] | None = None) -> list[dict]:
    """Parse the trade-halts RSS into a list of halt dicts.

    Each dict: symbol, name, market, reason_code, halt_dt (ET|None),
    resumption_dt (ET|None), halt_ts (stable identity str), resumption_ts (str|None).

    Only halts whose symbol is in ``tickers`` are kept when ``tickers`` is non-None.
    ``halt_ts`` is the raw "MM/DD/YYYY|HH:MM:SS.mmm" identity key (never empty), so
    the DB UNIQUE(symbol, halt_ts, reason_code) dedup is stable across polls.
    """
    results: list[dict] = []
    for item_xml in re.findall(r"<item>(.*?)</item>", raw_xml, re.S):
        symbol = _field(item_xml, "IssueSymbol").upper()
        if not symbol:
            continue
        if tickers is not None and symbol not in tickers:
            continue
        halt_date = _field(item_xml, "HaltDate")
        halt_time = _field(item_xml, "HaltTime")
        reason_code = _field(item_xml, "ReasonCode")
        res_date = _field(item_xml, "ResumptionDate")
        res_time = _field(item_xml, "ResumptionTradeTime")

        halt_dt = _parse_et_datetime(halt_date, halt_time)
        resumption_dt = _parse_et_datetime(res_date, res_time)
        # Stable identity key — always non-empty so NULLs never break UNIQUE dedup.
        halt_ts = f"{halt_date}|{halt_time}" if (halt_date or halt_time) else symbol
        resumption_ts = f"{res_date}|{res_time}" if (res_date or res_time) else None

        results.append({
            "symbol": symbol,
            "name": _field(item_xml, "IssueName"),
            "market": _field(item_xml, "Market"),
            "reason_code": reason_code,
            "halt_dt": halt_dt,
            "resumption_dt": resumption_dt,
            "halt_ts": halt_ts,
            "resumption_ts": resumption_ts,
        })
    return results


def format_halt_alert(halt: dict) -> str:
    """Build the instant-alert text for one halt. All times PDT — never Eastern."""
    symbol = halt.get("symbol", "?")
    market = halt.get("market") or "—"
    code = halt.get("reason_code") or ""
    label = _REASON_LABELS.get(code)
    reason = f"{label} ({code})" if label else (code or "trading halt")
    halted = _fmt_pt(halt.get("halt_dt"))
    resumes = _fmt_pt(halt.get("resumption_dt"))
    lines = [f"\U0001f6d1 **Trading Halt — ${symbol}** ({market})", f"Reason: {reason}"]
    if halted:
        lines.append(f"Halted: {halted}")
    lines.append(f"Resumes: {resumes}" if resumes else "Resumes: TBD")
    return "\n".join(lines)


async def fetch_trading_halts(
    tickers: set[str] | None = None,
    *,
    timeout_sec: float = 30.0,
) -> list[dict]:
    """Fetch + parse the Nasdaq trade-halts feed. Returns [] on any error — never raises.

    Security guarantees mirror finra_short_volume: no redirects followed, final URL
    re-validated to nasdaqtrader.com, response body size-capped.
    """
    if not _validate_url(FEED_URL):
        log.error("[HALT] feed URL failed domain validation: %s", FEED_URL)
        return []
    try:
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                FEED_URL,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    log.warning("[HALT] redirect refused for %s (status=%d)", FEED_URL, resp.status)
                    return []
                if resp.status != 200:
                    log.warning("[HALT] unexpected status %d for %s", resp.status, FEED_URL)
                    return []
                if not _validate_url(str(resp.url)):
                    log.error("[HALT] response URL failed domain check: %s", resp.url)
                    return []
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        log.error("[HALT] response for %s exceeds %d byte cap — aborting",
                                  FEED_URL, _MAX_RESPONSE_BYTES)
                        return []
                    chunks.append(chunk)
                raw_xml = b"".join(chunks).decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        log.warning("[HALT] timeout fetching %s", FEED_URL)
        return []
    except Exception as exc:
        log.warning("[HALT] fetch error for %s: %s", FEED_URL, exc)
        return []

    halts = _parse_halts_feed(raw_xml, tickers=tickers)
    log.info("[HALT] parsed %d halt(s) from feed (tickers_filter=%d)",
             len(halts), len(tickers) if tickers else -1)
    return halts


async def process_new_halts(halts: list[dict], tickers, post_fn) -> list[str]:
    """Dedup, cooldown-gate, and post an instant alert for each NEW halt.

    ``post_fn`` is an async callable that sends the alert text (in main.py this is
    ``_post_to_alerts_channel``). Idempotent: a halt already in the trading_halts
    table (UNIQUE symbol+halt_ts+reason_code) is skipped, so re-polling the same
    feed never re-alerts. Returns the list of symbols alerted this call.
    """
    from consensus_engine import db

    tickset = set(tickers) if tickers is not None else None
    alerted: list[str] = []
    for h in halts:
        sym = h.get("symbol")
        if not sym:
            continue
        if tickset is not None and sym not in tickset:
            continue
        halt_ts = h.get("halt_ts") or sym
        reason_code = h.get("reason_code") or ""
        # Primary dedup — never re-alert a halt already handled in an earlier poll.
        try:
            if await db.get_trading_halt(sym, halt_ts, reason_code) is not None:
                continue
        except Exception as exc:
            log.warning("[HALT] dedup check failed for %s: %s", sym, exc)
            continue
        # Instant-trigger exception (halts) still respects the per-ticker cooldown.
        try:
            if not await db.check_alert_cooldown(sym):
                continue
        except Exception as exc:
            log.warning("[HALT] cooldown check failed for %s: %s", sym, exc)
            continue
        try:
            await post_fn(format_halt_alert(h))
        except Exception as exc:
            log.warning("[HALT] alert post failed for %s: %s", sym, exc)
            continue
        # Record ONLY after a successful post so a failed send can retry next poll.
        try:
            await db.upsert_trading_halt(
                symbol=sym,
                halt_ts=halt_ts,
                reason_code=reason_code,
                resumption_ts=h.get("resumption_ts"),
                alerted_at=time.time(),
            )
        except Exception as exc:
            log.warning("[HALT] DB record failed for %s: %s", sym, exc)
        alerted.append(sym)
    return alerted
