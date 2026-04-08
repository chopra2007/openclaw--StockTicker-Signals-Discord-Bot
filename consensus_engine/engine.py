"""Precision scoring engine — budget-aware, multi-adapter signal analysis.

Classifies signals into STRONG_ALERT / WATCHLIST / IGNORE using an
escalation pipeline: cheap sources first (Finnhub, Brave), expensive
sources only if the score is promising (Exa, SerpApi, Firecrawl).
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from consensus_engine import config as cfg, db
from consensus_engine.adapter_protocols import (
    FinnhubContext,
    FirecrawlPage,
    SearchHit,
)
from consensus_engine.api_adapters import (
    BraveAdapter,
    ExaAdapter,
    FinnhubAdapter,
    FirecrawlAdapter,
    SerpApiAdapter,
)
from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.engine")

_TRUSTED_DOMAINS = {
    "reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "marketwatch.com",
    "finance.yahoo.com", "sec.gov", "fda.gov", "prnewswire.com",
    "businesswire.com", "seekingalpha.com", "benzinga.com", "barrons.com",
    "investors.com", "ft.com",
}

_MAINSTREAM = {"reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "ft.com"}


class SignalClass(str, Enum):
    STRONG_ALERT = "STRONG_ALERT"
    WATCHLIST = "WATCHLIST"
    IGNORE = "IGNORE"


# ---------------------------------------------------------------------------
# Budget Manager — async SQLite daily usage tracking
# ---------------------------------------------------------------------------

class BudgetManager:
    """Tracks daily API consumption in the api_usage_daily table."""

    _COLUMNS = (
        "finnhub_calls", "brave_queries", "exa_queries",
        "serpapi_queries", "firecrawl_credits",
    )

    async def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def _ensure_row(self, conn, day: str):
        cursor = await conn.execute(
            "SELECT 1 FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        if not row:
            await conn.execute(
                "INSERT OR IGNORE INTO api_usage_daily (day_utc) VALUES (?)", (day,)
            )
            await conn.commit()

    async def consume(self, adapter_col: str, amount: int = 1) -> bool:
        """Increment usage. Returns True if within budget, False if over."""
        if adapter_col not in self._COLUMNS:
            return False
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 9999)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"SELECT {adapter_col} FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        current = row[adapter_col] if row else 0

        if current + amount > limit:
            log.warning("Budget exceeded for %s: %d + %d > %d", adapter_col, current, amount, limit)
            return False

        await conn.execute(
            f"UPDATE api_usage_daily SET {adapter_col} = {adapter_col} + ?, updated_at = datetime('now') WHERE day_utc = ?",
            (amount, day),
        )
        await conn.commit()
        return True

    async def can_consume(self, adapter_col: str, amount: int = 1) -> bool:
        """Check if budget allows without consuming."""
        if adapter_col not in self._COLUMNS:
            return False
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 9999)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"SELECT {adapter_col} FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        current = row[adapter_col] if row else 0
        return current + amount <= limit

    async def pct_used(self, adapter_col: str) -> float:
        """Return percentage of daily budget used (0-100)."""
        if adapter_col not in self._COLUMNS:
            return 0.0
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 1)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"SELECT {adapter_col} FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        current = row[adapter_col] if row else 0
        return (current / limit) * 100 if limit > 0 else 0.0


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_finnhub(ctx: FinnhubContext) -> int:
    """Score from Finnhub market data: 0-30 points."""
    score = 0
    pct = abs(ctx.change_pct)
    if pct >= 5.0:
        score += 20
    elif pct >= 2.0:
        score += 12
    elif pct >= 0.5:
        score += 5

    if ctx.rvol >= 3.0:
        score += 8
    elif ctx.rvol >= 2.0:
        score += 5
    elif ctx.rvol >= 1.5:
        score += 2

    if ctx.news_headlines:
        score += min(len(ctx.news_headlines), 3) * 2
    return min(score, 30)


def _score_hits(hits: list[SearchHit]) -> tuple[int, bool]:
    """Score from search results. Returns (points, has_mainstream)."""
    if not hits:
        return 0, False

    score = 0
    has_mainstream = False
    seen_domains = set()

    for hit in hits:
        domain = hit.source.lower().lstrip("www.")
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        if domain in _TRUSTED_DOMAINS:
            score += 5
        else:
            score += 2

        if domain in _MAINSTREAM:
            has_mainstream = True

    return min(score, 25), has_mainstream


def _score_firecrawl(pages: list[FirecrawlPage], ticker: str) -> int:
    """Score from deep content extraction: 0-15 points."""
    if not pages:
        return 0
    score = 0
    ticker_lower = ticker.lower()
    for page in pages:
        if not page.success:
            continue
        text_lower = page.text.lower()
        if ticker_lower in text_lower or f"${ticker_lower}" in text_lower:
            score += 5
            word_count = len(page.text.split())
            if word_count >= 200:
                score += 3
    return min(score, 15)


def _classify(
    total_score: int,
    has_mainstream: bool,
    market_ok: bool,
) -> SignalClass:
    """Map total score + quality flags to a signal classification."""
    high = cfg.get("precision_engine.thresholds.high_confidence", 80)
    med = cfg.get("precision_engine.thresholds.medium_confidence", 65)
    require_mainstream = cfg.get("precision_engine.thresholds.require_mainstream_for_strong", True)
    require_market = cfg.get("precision_engine.thresholds.require_market_confirmation", True)

    if total_score >= high:
        if require_mainstream and not has_mainstream:
            return SignalClass.WATCHLIST
        if require_market and not market_ok:
            return SignalClass.WATCHLIST
        return SignalClass.STRONG_ALERT

    if total_score >= med:
        return SignalClass.WATCHLIST

    return SignalClass.IGNORE


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def analyze_signal(
    ticker: str,
    base_score: int = 0,
    budget: Optional[BudgetManager] = None,
) -> dict:
    """Run the precision scoring pipeline for a ticker.

    Returns a dict with keys:
        ticker, classification, total_score, finnhub_score, search_score,
        firecrawl_score, has_mainstream, market_ok, finnhub_ctx,
        search_hits, firecrawl_pages
    """
    if not cfg.get("precision_engine.enabled", False):
        return {
            "ticker": ticker,
            "classification": SignalClass.IGNORE,
            "total_score": base_score,
            "skipped": True,
        }

    budget = budget or BudgetManager()
    session = await get_session()

    score = base_score
    has_mainstream = False
    market_ok = False
    finnhub_ctx = FinnhubContext()
    all_hits: list[SearchHit] = []
    fc_pages: list[FirecrawlPage] = []

    # --- Phase 1: Finnhub (cheap, 2 calls) ---
    if await budget.consume("finnhub_calls", 2):
        adapter = FinnhubAdapter(session)
        finnhub_ctx = await adapter.get_context(ticker)
        fh_score = _score_finnhub(finnhub_ctx)
        score += fh_score
        market_ok = finnhub_ctx.market_ok
        log.info("$%s Finnhub: +%d pts (change=%.1f%%, rvol=%.1f, news=%d)",
                 ticker, fh_score, finnhub_ctx.change_pct, finnhub_ctx.rvol,
                 len(finnhub_ctx.news_headlines))

        if not market_ok and cfg.get("precision_engine.thresholds.require_market_confirmation", True):
            log.info("$%s early exit: market not confirming (change=%.1f%%)", ticker, finnhub_ctx.change_pct)
            return {
                "ticker": ticker,
                "classification": SignalClass.IGNORE,
                "total_score": score,
                "finnhub_score": _score_finnhub(finnhub_ctx),
                "search_score": 0,
                "firecrawl_score": 0,
                "has_mainstream": False,
                "market_ok": False,
                "finnhub_ctx": finnhub_ctx,
                "search_hits": [],
                "firecrawl_pages": [],
            }

    # --- Phase 2: Brave Search (cheap) ---
    query = f"{ticker} stock news today"
    if await budget.consume("brave_queries"):
        brave = BraveAdapter(session)
        brave_hits = await brave.search(query)
        all_hits.extend(brave_hits)

    search_score, has_mainstream = _score_hits(all_hits)
    score += search_score

    # --- Phase 3: Exa (medium cost, only if score < high threshold) ---
    high_thresh = cfg.get("precision_engine.thresholds.high_confidence", 80)
    if score < high_thresh and await budget.can_consume("exa_queries"):
        await budget.consume("exa_queries")
        exa = ExaAdapter(session)
        exa_hits = await exa.search(f"{ticker} stock catalyst breaking news")
        all_hits.extend(exa_hits)
        search_score, has_mainstream = _score_hits(all_hits)
        score = base_score + _score_finnhub(finnhub_ctx) + search_score

    # --- Phase 4: SerpApi (expensive, only if score >= threshold) ---
    serpapi_thresh = cfg.get("precision_engine.thresholds.min_score_for_serpapi", 60)
    if score >= serpapi_thresh and await budget.can_consume("serpapi_queries"):
        await budget.consume("serpapi_queries")
        serpapi = SerpApiAdapter(session)
        serp_hits = await serpapi.search(f"{ticker} stock news")
        all_hits.extend(serp_hits)
        search_score, has_mainstream = _score_hits(all_hits)
        score = base_score + _score_finnhub(finnhub_ctx) + search_score

    # --- Phase 5: Firecrawl (most expensive, only if score >= threshold) ---
    fc_thresh = cfg.get("precision_engine.thresholds.min_score_for_firecrawl", 65)
    max_fc_urls = cfg.get("precision_engine.thresholds.max_firecrawl_urls", 2)
    if score >= fc_thresh and all_hits:
        urls_to_scrape = [h.url for h in all_hits if h.url][:max_fc_urls]
        credits_needed = len(urls_to_scrape)
        if credits_needed > 0 and await budget.can_consume("firecrawl_credits", credits_needed):
            await budget.consume("firecrawl_credits", credits_needed)
            fc = FirecrawlAdapter(session)
            fc_pages = await fc.extract(urls_to_scrape)
            fc_score = _score_firecrawl(fc_pages, ticker)
            score += fc_score

    # --- Classify ---
    classification = _classify(score, has_mainstream, market_ok)
    log.info("$%s precision result: %s (score=%d, mainstream=%s, market_ok=%s)",
             ticker, classification.value, score, has_mainstream, market_ok)

    return {
        "ticker": ticker,
        "classification": classification,
        "total_score": score,
        "finnhub_score": _score_finnhub(finnhub_ctx),
        "search_score": search_score,
        "firecrawl_score": _score_firecrawl(fc_pages, ticker) if fc_pages else 0,
        "has_mainstream": has_mainstream,
        "market_ok": market_ok,
        "finnhub_ctx": finnhub_ctx,
        "search_hits": all_hits,
        "firecrawl_pages": fc_pages,
    }
