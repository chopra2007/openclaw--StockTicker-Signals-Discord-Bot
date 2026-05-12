"""D1: Cluster-buy detector for SEC Form 4 insider purchases.

Scans the last 30 days of Form 4 filings for active tickers. When ≥3 unique
insiders make open-market purchases (txn_code='P', >$250k, excluding 10b5-1
plan trades), returns Form4ClusterAlert objects for emission.

Gated by `features.form4_cluster.enabled` and
`scanners.sec_background_watchers_enabled`.
"""
from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Union, Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.analysis.regime import lookup_regime
from consensus_engine.scanners.sec_edgar import check_recent_filings
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger(__name__)

_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"
_YF_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_TEN_B5_1_PATTERNS = [
    "10b5-1", "10b5–1", "rule 10b5", "trading plan", "pre-arranged",
]

_MIN_PURCHASE_DOLLARS = 250_000.0


def is_10b5_1(footnote_text: str) -> bool:
    """Conservative check; biased to OVER-exclude. Returns True on any keyword match."""
    lower = footnote_text.lower()
    return any(p in lower for p in _TEN_B5_1_PATTERNS)


@dataclass
class Form4ClusterAlert:
    ticker: str
    n_insiders: int
    total_dollars: float
    members: list[dict]              # [{cik, name, role, dollars, txn_date}]
    window_start: datetime
    window_end: datetime
    passes_falling_knife: bool
    falling_knife_threshold: Union[float, str]   # 0.85 | 0.65 | "disabled"
    regime_label: str


def _parse_form4_xml_for_cluster(raw_xml: str) -> Optional[dict]:
    """Extract cluster-relevant fields from Form 4 XML.

    Returns dict: {person_cik, reporter_name, title, footnote_text, purchases}
    where purchases is list[{date, dollars}]. Returns None on parse error.
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None

    def _val(node, tag):
        el = node.find(f".//{tag}/value")
        if el is None:
            el = node.find(f".//{tag}")
        return (el.text or "").strip() if el is not None else ""

    person_cik = _val(root, "rptOwnerCik")
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

    footnote_text = " ".join(
        (fn.text or "") for fn in root.findall(".//footnote")
    )

    purchases = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        if _val(tx, "transactionCode") != "P":
            continue
        shares_str = _val(tx, "transactionShares")
        price_str = _val(tx, "transactionPricePerShare")
        date = _val(tx, "transactionDate")
        try:
            shares = float(shares_str) if shares_str else 0.0
            price = float(price_str) if price_str else 0.0
        except ValueError:
            continue
        dollars = shares * price
        if dollars > 0:
            purchases.append({"date": date, "dollars": dollars})

    return {
        "person_cik": person_cik,
        "reporter_name": reporter_name,
        "title": title,
        "footnote_text": footnote_text,
        "purchases": purchases,
    }


async def _fetch_form4_xml(cik: str, accession_number: str, primary_document: str) -> Optional[str]:
    """Fetch raw Form 4 XML from SEC EDGAR Archives."""
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
                log.debug("[D1] Form 4 XML %d: %s", resp.status, url)
                return None
            return await resp.text()
    except Exception as e:
        log.debug("[D1] Form 4 XML fetch error: %s", e)
        return None


async def _fetch_price_and_30d_high(ticker: str) -> tuple[float, float]:
    """Fetch current close and 30-day high for ticker via Yahoo Finance.

    Returns (current_price, high_30d). Returns (0.0, 0.0) on failure.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "1mo"}
    try:
        session = await get_session()
        async with session.get(
            url, params=params, headers=_YF_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.debug("[D1] Yahoo Finance %d for $%s", resp.status, ticker)
                return 0.0, 0.0
            data = await resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return 0.0, 0.0
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]
            closes = [c for c in (quote.get("close") or []) if c is not None]
            highs = [h for h in (quote.get("high") or []) if h is not None]
            if not closes:
                return 0.0, 0.0
            current_price = closes[-1]
            high_30d = max(highs) if highs else current_price
            return current_price, high_30d
    except Exception as e:
        log.debug("[D1] Yahoo Finance error for $%s: %s", ticker, e)
        return 0.0, 0.0


async def passes_falling_knife_filter(
    ticker: str,
    regime_label: str,
    n_insiders: int,
) -> tuple[bool, Union[float, str]]:
    """Falling-knife regime gate.

    panic: require n_insiders >= 5; price floor disabled.
    elevated: require price >= 0.65 * 30d-high.
    calm/normal/cold_start: require price >= 0.85 * 30d-high.
    Returns (passes, threshold_used).
    """
    if regime_label == "panic":
        return n_insiders >= 5, "disabled"

    current_price, high_30d = await _fetch_price_and_30d_high(ticker)
    if current_price == 0.0 or high_30d == 0.0:
        return True, "disabled"

    threshold = 0.65 if regime_label == "elevated" else 0.85
    return current_price >= threshold * high_30d, threshold


async def _check_form4_cooldown(ticker: str, window_days: int = 14) -> bool:
    """Return True if no form4_clusters row exists for ticker within window_days."""
    conn = await db.get_db()
    cutoff = time.time() - (window_days * 86400)
    try:
        cur = await conn.execute(
            "SELECT COUNT(*) as cnt FROM form4_clusters WHERE ticker = ? AND alerted_at > ?",
            (ticker, cutoff),
        )
        row = await cur.fetchone()
        return (row["cnt"] if row else 0) == 0
    except Exception:
        return True  # fail-open: if table missing, allow through


async def _store_form4_cluster(alert: Form4ClusterAlert) -> None:
    """INSERT OR IGNORE into form4_clusters. First writer wins on (ticker, window_end)."""
    conn = await db.get_db()
    members_json = json.dumps(alert.members)
    window_end_str = alert.window_end.strftime("%Y-%m-%d")
    window_start_str = alert.window_start.strftime("%Y-%m-%d")
    threshold_str = str(alert.falling_knife_threshold)
    try:
        await conn.execute(
            """INSERT OR IGNORE INTO form4_clusters
               (ticker, window_start, window_end, n_insiders, total_dollars,
                members_json, regime_label, falling_knife_threshold, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.ticker, window_start_str, window_end_str,
                alert.n_insiders, alert.total_dollars, members_json,
                alert.regime_label, threshold_str, time.time(),
            ),
        )
        await conn.commit()
    except Exception as e:
        log.warning("[D1] form4_clusters insert error: %s", e)


async def scan_form4_clusters(
    window_days: int = 30,
    min_unique: int = 3,
) -> list[Form4ClusterAlert]:
    """Scan last window_days of Form 4 filings for cluster buys.

    Reuses rate_limiter('sec_edgar') via check_recent_filings. Groups by
    (ticker, person_cik) to dedupe split filings. Returns Form4ClusterAlert
    list for tickers that pass cooldown + falling-knife gate.
    """
    regime = await lookup_regime()
    regime_label = regime.label

    tickers = await db.get_active_tickers(min_signals=1)
    hours_back = window_days * 24
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=window_days)

    # ticker -> person_cik -> accumulated purchase entry
    ticker_insiders: dict[str, dict[str, dict]] = {}

    for ticker in tickers[:50]:
        filings = await check_recent_filings(ticker, hours_back=hours_back)
        for filing in filings:
            if filing.get("form") != "4":
                continue
            raw_xml = await _fetch_form4_xml(
                filing.get("cik", ""),
                filing.get("accession_number", ""),
                filing.get("primary_document", ""),
            )
            if not raw_xml:
                continue
            parsed = _parse_form4_xml_for_cluster(raw_xml)
            if not parsed:
                continue
            if is_10b5_1(parsed["footnote_text"]):
                log.debug("[D1] $%s: 10b5-1 filing excluded (%s)", ticker, parsed["reporter_name"])
                continue

            person_cik = parsed["person_cik"] or parsed["reporter_name"]
            purchase_dollars = sum(p["dollars"] for p in parsed["purchases"])
            if purchase_dollars < _MIN_PURCHASE_DOLLARS:
                continue

            txn_dates = [p["date"] for p in parsed["purchases"] if p["date"]]
            txn_date = max(txn_dates) if txn_dates else ""

            if ticker not in ticker_insiders:
                ticker_insiders[ticker] = {}

            existing = ticker_insiders[ticker].get(person_cik)
            if existing:
                existing["dollars"] += purchase_dollars
                if txn_date > existing.get("txn_date", ""):
                    existing["txn_date"] = txn_date
            else:
                ticker_insiders[ticker][person_cik] = {
                    "cik": person_cik,
                    "name": parsed["reporter_name"],
                    "role": parsed["title"],
                    "dollars": purchase_dollars,
                    "txn_date": txn_date,
                }

    alerts = []
    for ticker, insiders in ticker_insiders.items():
        qualifying = [m for m in insiders.values() if m["dollars"] >= _MIN_PURCHASE_DOLLARS]
        if len(qualifying) < min_unique:
            continue

        if not await _check_form4_cooldown(ticker):
            log.info("[D1] $%s: 14d cooldown active, skipping", ticker)
            continue

        total_dollars = sum(m["dollars"] for m in qualifying)
        members = sorted(qualifying, key=lambda m: m["dollars"], reverse=True)

        passes_fk, threshold = await passes_falling_knife_filter(
            ticker, regime_label, len(qualifying)
        )

        alert = Form4ClusterAlert(
            ticker=ticker,
            n_insiders=len(qualifying),
            total_dollars=total_dollars,
            members=members,
            window_start=window_start,
            window_end=window_end,
            passes_falling_knife=passes_fk,
            falling_knife_threshold=threshold,
            regime_label=regime_label,
        )

        if passes_fk:
            await _store_form4_cluster(alert)
            log.info("[D1] Cluster alert: $%s %d insiders $%.0f (regime=%s)",
                     ticker, len(qualifying), total_dollars, regime_label)
            alerts.append(alert)
        else:
            log.info("[D1] $%s cluster blocked by falling-knife (regime=%s n=%d threshold=%s)",
                     ticker, regime_label, len(qualifying), threshold)

    return alerts
