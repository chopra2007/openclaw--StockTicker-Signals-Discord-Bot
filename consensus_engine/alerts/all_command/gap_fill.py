"""Output-field-driven SearXNG gap-fill for !all command.

Three trigger types fire at most one query each, gathered concurrently with
asyncio.gather. Each query has a per-call 8s timeout; the outer 20s deadline
acts as a hard cap.

Triggers:
    anchors_count < 4         -> "{ticker} price target support resistance"
    has 8-K filing w/o body   -> "{ticker} 8-K {filing_date}"
    direction != neutral and  -> "{ticker} upcoming catalyst earnings"
    not has_event_date
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from consensus_engine.scanners import searxng

log = logging.getLogger("consensus_engine.alerts.all_command.gap_fill")


_PER_QUERY_TIMEOUT = 8.0


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

    out = {
        "harvested_anchors_snippets": [],
        "eight_k_summary_snippets": [],
        "event_date_snippets": [],
    }
    if not queries:
        return out

    # Outer wall-clock deadline cap
    remaining = max(0.0, deadline - time.time())
    if remaining <= 0:
        return out

    coros = [_run_query(q) for _, q in queries]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True),
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
    for (kind, _query), result in zip(queries, results):
        if isinstance(result, Exception):
            log.warning("gap_fill: %s query exception: %s", kind, result)
            continue
        out[key_for[kind]] = _snippets_from_results(result)
    return out
