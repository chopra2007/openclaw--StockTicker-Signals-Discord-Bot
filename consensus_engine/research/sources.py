"""Atlas source adapters: analyst signals, SEC filings, news.

Each fetcher returns a markdown section string, or None when there's
nothing to summarize / the upstream call failed. Callers are responsible
for upserting into research_sections.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.research.sources")

_ANALYST_LOOKBACK_SECONDS = 30 * 86400
_NEWS_LOOKBACK_SECONDS = 12 * 3600


async def _summarize_with_llm(prompt: str) -> str:
    """Thin OpenRouter call via the configured fallback chain.
    Returns the assistant's text, or '' if every model in the chain fails.
    """
    from consensus_engine.llm_client import call_with_fallback
    return await call_with_fallback(
        role="primary",
        messages=[
            {"role": "system", "content":
                "You are a concise equity research analyst. "
                "Summarize in markdown bullet points — no preamble."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=cfg.get("llm.max_tokens", 1024),
        temperature=0.3,
    )


async def fetch_analyst_section(ticker: str) -> str | None:
    """Summarize last-30d TweetShift/Twitter signals for a ticker.
    Returns markdown, or None if no signals exist in the window.
    """
    conn = await db.get_db()
    cutoff = time.time() - _ANALYST_LOOKBACK_SECONDS
    cur = await conn.execute(
        """SELECT source_detail, raw_text, sentiment, detected_at
           FROM ticker_signals
           WHERE ticker=? AND source_type='twitter' AND detected_at >= ?
           ORDER BY detected_at DESC LIMIT 50""",
        (ticker.upper(), cutoff),
    )
    rows = await cur.fetchall()
    if not rows:
        return None

    lines = []
    for r in rows:
        who = r["source_detail"] or "unknown"
        sent = r["sentiment"] or "neutral"
        txt = (r["raw_text"] or "").replace("\n", " ").strip()
        lines.append(f"- [{sent}] {who}: {txt[:240]}")

    prompt = (
        f"Ticker: {ticker}\n"
        f"Last 30 days of analyst tweets ({len(rows)} total):\n\n"
        + "\n".join(lines)
        + "\n\nWrite 3-6 markdown bullets capturing the dominant thesis, "
          "direction skew, and any price targets. Be specific; quote analysts."
    )
    summary = await _summarize_with_llm(prompt)
    if not summary:
        # Fall back to a raw count so the section isn't empty.
        bulls = sum(1 for r in rows if (r["sentiment"] or "").lower() == "bullish")
        bears = sum(1 for r in rows if (r["sentiment"] or "").lower() == "bearish")
        return f"- {len(rows)} analyst posts in last 30d ({bulls} bullish / {bears} bearish)"
    return summary


async def fetch_news_section(ticker: str) -> str | None:
    """Query SearXNG for `"TICKER" stock news`, summarize top hits."""
    from consensus_engine.scanners.searxng import search_searxng
    try:
        results = await search_searxng(f'"{ticker}" stock news')
    except Exception as exc:
        log.warning("SearXNG news query failed for %s: %s", ticker, exc)
        return None

    results = results[:10]
    if not results:
        return None

    lines = [f"- {r.get('title', '').strip()} — {r.get('url', '')}" for r in results]
    prompt = (
        f"Ticker: {ticker}\n"
        f"Recent news results:\n\n" + "\n".join(lines) +
        "\n\nWrite 3-5 markdown bullets describing the most material news. "
        "Link to sources. Skip pure PR fluff."
    )
    summary = await _summarize_with_llm(prompt)
    return summary or "\n".join(lines[:5])


_SEC_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"


async def _recent_filings(ticker: str, limit: int = 5) -> list[dict]:
    """Return recent 8-K/10-Q/10-K filings for ticker (most recent first)."""
    from consensus_engine.scanners import sec_edgar
    await sec_edgar._load_ticker_map()
    cik = sec_edgar._ticker_to_cik.get(ticker.upper())
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _SEC_USER_AGENT}) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except Exception as exc:
        log.warning("SEC submissions fetch failed for %s: %s", ticker, exc)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filed = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    primary_doc = recent.get("primaryDocDescription", [])

    out: list[dict] = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "10-Q", "10-K"):
            continue
        out.append({
            "form": form,
            "filed": filed[i] if i < len(filed) else "",
            "accession": accs[i] if i < len(accs) else "",
            "items": items[i] if i < len(items) else "",
            "summary": primary_doc[i] if i < len(primary_doc) else "",
        })
        if len(out) >= limit:
            break
    return out


async def fetch_sec_section(ticker: str) -> str | None:
    """Summarize the most recent SEC filings (8-K/10-Q/10-K) for ticker."""
    filings = await _recent_filings(ticker, limit=5)
    if not filings:
        return None
    lines = [
        f"- **{f['form']}** filed {f['filed']} — {' '.join(p for p in [f['items'], f['summary']] if p).strip()}"
        for f in filings
    ]
    prompt = (
        f"Ticker: {ticker}\nRecent SEC filings:\n\n" + "\n".join(lines) +
        "\n\nWrite 3-5 markdown bullets summarizing material financial / "
        "strategic events. Call out earnings prints, guidance changes, "
        "executive departures, or material contracts."
    )
    summary = await _summarize_with_llm(prompt)
    return summary or "\n".join(lines)
