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
import datetime
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


# Three independent SerpAPI free-tier accounts (separate billing, ~250 searches/mo
# each, reset independently — verified 2026-06-01: keys map to 3 distinct accounts).
# Tried primary-first; a key that returns HTTP 429 ("out of searches") is skipped for
# the rest of the day so we don't waste a call probing a dead key.
_SERPAPI_KEY_ALIASES = ("serpapi", "serpapi2", "serpapi3")
_EXHAUST_MARKERS = ("out of searches",)
# alias -> ISO date (YYYY-MM-DD) the key last returned "out of searches". Same-day ->
# skip; the date rolls over the next day -> retried (covers the monthly quota reset).
_serpapi_exhausted: dict[str, str] = {}


def _serpapi_keys() -> list[tuple[str, str]]:
    """Ordered (alias, key) pairs: configured, non-empty, not exhausted today."""
    today = datetime.date.today().isoformat()
    pairs: list[tuple[str, str]] = []
    for alias in _SERPAPI_KEY_ALIASES:
        key = cfg.get_api_key(alias)
        if not key:
            continue
        if _serpapi_exhausted.get(alias) == today:
            continue
        pairs.append((alias, key))
    return pairs


async def _serpapi_organic(query: str, freshness: str) -> list[dict]:
    """Run one SerpAPI Google search, rotating keys on exhaustion.

    Tries each available key in priority order. A key that returns HTTP 429 (or a
    body carrying an "out of searches" error) is marked exhausted-for-today and the
    next key is tried. Any other failure on a key returns [] without burning the rest
    (a transient 500 shouldn't drain every key). Returns the raw ``organic_results``
    list (possibly empty). No lock needed: callers run as coroutines in one asyncio
    event loop (gap_fill.py asyncio.gather), so the dict writes don't interleave.
    """
    today = datetime.date.today().isoformat()
    keys = _serpapi_keys()
    if not keys:
        return []
    url = "https://serpapi.com/search"
    for alias, api_key in keys:
        params = {
            "q": query, "api_key": api_key, "engine": "google",
            "num": 10, "tbs": freshness,
        }
        try:
            session = await get_session()
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=_PER_QUERY_TIMEOUT),
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json()
                except Exception:  # noqa: BLE001
                    data = {}
        except Exception as exc:  # noqa: BLE001
            log.debug("serpapi: key %s failed for %s: %s", alias, query, exc)
            return []
        err = str(data.get("error") or "").lower()
        if status == 429 or any(m in err for m in _EXHAUST_MARKERS):
            _serpapi_exhausted[alias] = today
            log.warning(
                "serpapi: key '%s' out of searches (HTTP %d) — rotating to next key",
                alias, status,
            )
            continue
        if status != 200:
            log.debug("serpapi: HTTP %d for %s (key %s)", status, query, alias)
            return []
        return data.get("organic_results", []) or []
    log.warning("serpapi: all keys exhausted/unavailable for query: %s", query)
    return []


async def _search_serpapi_raw(query: str, freshness: str = "qdr:y") -> list[str]:
    """Thin Google-via-SerpAPI wrapper returning title+snippet pairs.

    `freshness='qdr:y'` = past year; `'qdr:m'` = past month. Past year is
    right for catalyst mining because partnership/product announcements
    can have multi-month visibility (the AMD-Meta deal pre-flight
    surfaced an October 2026 announcement that's still load-bearing).
    Key selection + 429 rotation live in `_serpapi_organic`.
    """
    out: list[str] = []
    for r in await _serpapi_organic(query, freshness):
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        if title or snippet:
            out.append(f"{title}: {snippet}")
    return out


async def _search_serpapi_trusted(query: str, freshness: str = "qdr:m") -> list[str]:
    """Feature E: macro-risk SerpAPI search filtered to trusted sources.

    Same SerpAPI call shape as `_search_serpapi_raw`, but only returns
    title+snippet pairs whose result URL is from a `news.trusted_sources`
    domain (reuters, cnbc, bloomberg, sec.gov, …). Macro/regulatory risk
    must be CURRENT, so the default freshness is `qdr:m` (past month), not the
    catalyst queries' `qdr:y`.
    """
    trusted = cfg.get("news.trusted_sources", []) or []
    out: list[str] = []
    for r in await _serpapi_organic(query, freshness):
        link = (r.get("link") or r.get("source") or "").lower()
        if not any(src in link for src in trusted):
            continue
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
    company_name: str = "",
    sector: str = "",
) -> dict:
    """Run output-field-driven gap-fill queries.

    Returns dict with these keys, each a list of content strings:
        harvested_anchors_snippets: from the price-targets query
        eight_k_summary_snippets:   from the 8-K filing query
        event_date_snippets:        from the catalyst/earnings query
        catalyst_research_snippets: union of the cat_* SerpAPI queries
        macro_risk_snippets:        from the [macro_risk] SerpAPI query
                                    (Feature E — recent macro/sector/regulatory
                                    risk news, disambiguated by company_name +
                                    sector so single-word tickers don't return
                                    garbage; empty when disabled, no name, or
                                    the query did not fire).

    `company_name` and `sector` default to "" so existing callers/tests keep
    working; the macro-risk query is skipped when company_name is empty.

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
        "macro_risk_snippets": [],         # Feature E: recent macro/sector risk
    }

    # Feature E — one recent (past-month) macro/sector/regulatory risk query,
    # disambiguated by company name + sector so single-word tickers (AI, ON,
    # NOW, CAT) don't return garbage. Config-gated, default ON. Built here so
    # it joins the same wall-clock budget as the catalyst queries below.
    macro_risk_query: Optional[str] = None
    if (
        company_name
        and cfg.get("all_command.macro_risk_query.enabled", True)
    ):
        terms = '(export restriction OR regulation OR ban OR "demand" OR "guidance cut")'
        sector_clause = f' OR "{sector}"' if sector else ""
        macro_risk_query = f'"{company_name}"{sector_clause} {terms} 2026'

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
    # Feature E — macro-risk query shares the same gather + wall-clock budget.
    # If it blows the deadline the outer wait_for aborts the whole gather and
    # returns `out` (empty macro_risk_snippets); it never blocks the catalyst
    # queries on its own because they all run concurrently.
    macro_coros = []
    macro_specs: list[tuple[str, str]] = []
    if macro_risk_query is not None:
        macro_coros.append(
            asyncio.wait_for(
                _search_serpapi_trusted(macro_risk_query, freshness="qdr:m"),
                timeout=_PER_QUERY_TIMEOUT,
            )
        )
        macro_specs.append(("macro_risk", macro_risk_query))
    all_coros = sx_coros + serp_coros + macro_coros
    queries = list(queries) + list(catalyst_queries) + macro_specs
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
    macro_buckets: list[str] = []
    for (kind, _query), result in zip(queries, results):
        if isinstance(result, Exception):
            log.warning("gap_fill: %s query exception: %s", kind, result)
            continue
        if kind == "macro_risk":
            # Feature E — already trusted-source-filtered title+snippet strings.
            # Keep the [macro_risk] tag so the narrator can distinguish these
            # from company-specific catalyst rows.
            raw = result if isinstance(result, list) else []
            macro_buckets.extend(
                f"[macro_risk] {s}" for s in raw if isinstance(s, str) and s
            )
        elif kind.startswith("cat_"):
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
    # Feature E — cap macro-risk rows; trusted-source filter already trims junk.
    out["macro_risk_snippets"] = macro_buckets[:5]
    return out
