"""Output-field-driven gap-fill for !all command (SearXNG + Brave).

Triggers fire at most one query each, gathered concurrently with
asyncio.gather. Each query has a per-call 8s timeout; the outer 20s deadline
acts as a hard cap.

Triggers:
    anchors_count < 4         -> "{ticker} price target support resistance"
    has 8-K filing w/o body   -> "{ticker} 8-K {filing_date}"
    direction != neutral and  -> "{ticker} upcoming catalyst earnings"
    not has_event_date
    direction != neutral      -> [Commit 7 catalyst-mining] 5 broader queries
                                 for partnerships / product launches / supply
                                 deals / regulatory dates / analyst days,
                                 always fires for directional thesis since the
                                 substance bottleneck per user iter5 feedback
                                 was "bot doesn't find real catalysts" — the
                                 narrow earnings-only query missed verifiable
                                 events like AMD's $100B+ Meta 6GW partnership.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine.scanners import searxng
from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.alerts.all_command.gap_fill")


_PER_QUERY_TIMEOUT = 8.0
# Commit 7 — SerpAPI (Google Search) is used for catalyst mining: SearXNG
# returns generic Wikipedia/driver pages on broad "TICKER partnership"
# queries, and Brave hit its $5 monthly cap. SerpAPI key returned the
# AMD-Meta MI450 partnership ($100B+ deal, H2 2026 shipments) as the
# first result for "AMD Meta partnership 2026" in pre-flight — exactly
# the substance the user's iter5 verdict said the bot was missing.
# Free tier is 100/month; per-!all cap keeps headroom for testing.
_CATALYST_SERPAPI_MAX_CALLS = 3


async def _search_serpapi_raw(query: str, freshness: str = "qdr:y") -> list[str]:
    """Thin Google-via-SerpAPI wrapper returning title+snippet pairs.

    `freshness='qdr:y'` = past year; `'qdr:m'` = past month. Past year is
    right for catalyst mining because partnership/product announcements
    can have multi-month visibility (the AMD-Meta deal pre-flight
    surfaced an October 2026 announcement that's still load-bearing).
    """
    api_key = (
        cfg.get_api_key("serpapi3")
        or cfg.get_api_key("serpapi2")
        or cfg.get_api_key("serpapi")
    )
    if not api_key:
        return []
    try:
        session = await get_session()
        url = "https://serpapi.com/search"
        params = {
            "q": query, "api_key": api_key, "engine": "google",
            "num": 10, "tbs": freshness,
        }
        async with session.get(
            url, params=params,
            timeout=aiohttp.ClientTimeout(total=_PER_QUERY_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.debug("serpapi_raw: HTTP %d for %s", resp.status, query)
                return []
            data = await resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("serpapi_raw: failed %s: %s", query, exc)
        return []
    out: list[str] = []
    for r in data.get("organic_results", []) or []:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        if title or snippet:
            out.append(f"{title}: {snippet}")
    return out


def _extract_8k_filing(sec_filings: list) -> Optional[dict]:
    """Find the most recent 8-K filing missing a body, if any."""
    for filing in sec_filings or []:
        if not isinstance(filing, dict):
            continue
        form = (filing.get("form_type") or filing.get("form") or "").upper()
        if form != "8-K":
            continue
        if filing.get("body"):
            continue
        return filing
    return None


async def _run_query(query: str) -> list[dict]:
    """Run one SearXNG query with an 8s wait_for cap."""
    try:
        return await asyncio.wait_for(
            searxng.search_searxng(query),
            timeout=_PER_QUERY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("gap_fill: query timed out after %.1fs: %s",
                    _PER_QUERY_TIMEOUT, query)
        return []
    except Exception as e:
        log.warning("gap_fill: query failed for '%s': %s", query, e)
        return []


def _snippets_from_results(results: list[dict]) -> list[str]:
    """Extract content strings from SearXNG result dicts."""
    out: list[str] = []
    for r in results or []:
        if isinstance(r, dict):
            content = r.get("content") or r.get("title") or ""
            if content:
                out.append(content)
    return out


async def run_gap_fill(
    ticker: str,
    anchors_count: int,
    sec_filings: list,
    has_event_date: bool,
    direction: str,
    deadline: float,
) -> dict:
    """Run output-field-driven gap-fill queries.

    Returns dict with three keys, each a list of content strings:
        harvested_anchors_snippets: from the price-targets query
        eight_k_summary_snippets:   from the 8-K filing query
        event_date_snippets:        from the catalyst/earnings query

    Each empty list when its trigger did not fire or returned nothing.
    """
    queries: list[tuple[str, str]] = []

    # Trigger 1: anchor harvest
    if anchors_count < 4:
        queries.append((
            "anchors",
            f"{ticker} price target support resistance",
        ))

    # Trigger 2: 8-K body missing
    eight_k = _extract_8k_filing(sec_filings)
    if eight_k is not None:
        filing_date = (eight_k.get("filing_date")
                       or eight_k.get("date")
                       or eight_k.get("filed_at")
                       or "")
        date_str = str(filing_date)[:10] if filing_date else ""
        queries.append((
            "eight_k",
            f"{ticker} 8-K {date_str}".strip(),
        ))

    # Trigger 3: directional with no event date
    if direction and direction.lower() != "neutral" and not has_event_date:
        queries.append((
            "event_date",
            f"{ticker} upcoming catalyst earnings",
        ))

    # Trigger 4 — Commit 12/15: SerpAPI catalyst mining with high-signal
    # query patterns. Catalysts apply regardless of direction — Commit 15
    # dropped the `direction != neutral` gate because aggregator passes
    # the cross-ref scorer's breakdown.direction which is None on manual
    # !all invocations (resolving to literal "neutral"), so the entire
    # catalyst branch was being skipped in production even though the
    # SerpAPI queries themselves worked perfectly in isolated tests.
    _CATALYST_SERPAPI_MAX_CALLS_LOCAL = 3
    catalyst_queries: list[tuple[str, str]] = [
        ("cat_partnership", f'"{ticker}" partnership deal billion'),
        ("cat_analyst_day", f"{ticker} upcoming catalyst analyst day"),
        ("cat_catalyst",    f"{ticker} stock catalyst 2026"),
    ][:_CATALYST_SERPAPI_MAX_CALLS_LOCAL]

    out = {
        "harvested_anchors_snippets": [],
        "eight_k_summary_snippets": [],
        "event_date_snippets": [],
        "catalyst_research_snippets": [],  # NEW: union of all 5 cat_* tags
    }
    if not queries:
        return out

    # Outer wall-clock deadline cap
    remaining = max(0.0, deadline - time.time())
    if remaining <= 0:
        return out

    # Commit 11 fix: SearXNG + SerpAPI catalyst queries fire under ONE
    # asyncio.gather so they're truly parallel. Prior implementation
    # used two sequential asyncio.wait_for blocks which serialised the
    # catalyst wait behind the SearXNG wait and ate ~8s of wall clock
    # — the resulting synthesis-deadline pressure caused iter10's
    # "all 6 models timed out" symptom even though the chain was fine.
    sx_coros = [_run_query(q) for _, q in queries]
    serp_coros = [
        asyncio.wait_for(
            _search_serpapi_raw(q, freshness="qdr:y"),
            timeout=_PER_QUERY_TIMEOUT,
        )
        for _, q in catalyst_queries
    ]
    all_coros = sx_coros + serp_coros
    queries = list(queries) + list(catalyst_queries)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*all_coros, return_exceptions=True),
            timeout=remaining,
        )
    except asyncio.TimeoutError:
        log.warning("gap_fill: outer deadline %.1fs exceeded for %s",
                    remaining, ticker)
        return out

    key_for: dict[str, str] = {
        "anchors": "harvested_anchors_snippets",
        "eight_k": "eight_k_summary_snippets",
        "event_date": "event_date_snippets",
    }
    catalyst_buckets: list[str] = []
    for (kind, _query), result in zip(queries, results):
        if isinstance(result, Exception):
            log.warning("gap_fill: %s query exception: %s", kind, result)
            continue
        if kind.startswith("cat_"):
            # SerpAPI already returns title+snippet strings, not the
            # SearXNG dict-list shape. Tag each with its query type for
            # downstream attribution.
            raw = result if isinstance(result, list) else []
            tagged = [f"[{kind}] {s}" for s in raw if isinstance(s, str) and s]
            catalyst_buckets.extend(tagged)
        else:
            snippets = _snippets_from_results(result)
            out[key_for[kind]] = snippets
    # De-dupe near-identical catalyst snippets and cap to 15 to keep prompt
    # budget reasonable. Most search engines return the same article via
    # multiple feeds.
    seen: set[str] = set()
    deduped: list[str] = []
    for s in catalyst_buckets:
        key = s[:200].lower()  # rough dedupe on prefix
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
        if len(deduped) >= 15:
            break
    out["catalyst_research_snippets"] = deduped
    return out
