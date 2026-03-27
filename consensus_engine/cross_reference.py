"""Cross-Reference Engine — orchestrates all multiplier sources.

Runs in parallel after the instant Discord ping. Computes a final
score from news, social, technical, other analysts, and LLM confidence.
"""

import asyncio
import logging
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    CatalystResult, TechnicalResult, OptionsResult,
)
from consensus_engine.scanners.news import news_cascade
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.analysis.llm_scorer import score_confidence

log = logging.getLogger("consensus_engine.cross_reference")


def compute_technical_score(technical: Optional[TechnicalResult]) -> int:
    """Compute score from technical filters. +2 per passing filter, max 12."""
    if not technical or not technical.filters:
        return 0
    per_filter = cfg.get("scoring.multipliers.technical_per_filter", 2)
    max_pts = cfg.get("scoring.multipliers.technical_max", 12)
    return min(technical.passed_count * per_filter, max_pts)


def compute_social_score(social_data: dict[str, int]) -> int:
    """Compute social cross-reference score from platform signal counts."""
    score = 0
    m = cfg.get("scoring.multipliers", {})
    if social_data.get("apewisdom", 0) >= 1:
        score += m.get("social_apewisdom", 10)
    if social_data.get("stocktwits", 0) >= 1:
        score += m.get("social_stocktwits", 10)
    if social_data.get("reddit", 0) >= 2:
        score += m.get("social_reddit", 10)
    if social_data.get("google_trends", 0) >= 1:
        score += m.get("google_trends", 5)
    return score


def _compute_social_breakdown(social_data: dict[str, int]) -> dict[str, int]:
    """Return per-source social points for the ScoreBreakdown."""
    m = cfg.get("scoring.multipliers", {})
    return {
        "social_apewisdom": m.get("social_apewisdom", 10) if social_data.get("apewisdom", 0) >= 1 else 0,
        "social_stocktwits": m.get("social_stocktwits", 10) if social_data.get("stocktwits", 0) >= 1 else 0,
        "social_reddit": m.get("social_reddit", 10) if social_data.get("reddit", 0) >= 2 else 0,
        "google_trends": m.get("google_trends", 5) if social_data.get("google_trends", 0) >= 1 else 0,
    }


async def _run_news_cascade(ticker: str) -> Optional[CatalystResult]:
    return await news_cascade(ticker)


async def _run_sec_check(ticker: str) -> tuple[bool, str]:
    """Check SEC EDGAR for recent filings. Returns (has_filing, summary)."""
    try:
        from consensus_engine.scanners.sec_edgar import check_recent_filings, classify_filing_significance
        filings = await check_recent_filings(ticker, hours_back=48)
        return classify_filing_significance(filings)
    except Exception as e:
        log.debug("SEC check error for %s: %s", ticker, e)
        return False, ""


async def _run_social_check(ticker: str) -> dict[str, int]:
    """Get social signal counts for a ticker from the database."""
    counts = await db.get_signal_counts_by_source(ticker)
    return {
        "apewisdom": counts.get("apewisdom", 0),
        "stocktwits": counts.get("stocktwits", 0),
        "reddit": counts.get("reddit", 0),
        "google_trends": counts.get("google_trends", 0),
    }


async def _run_technical(ticker: str) -> Optional[TechnicalResult]:
    return await verify_technical(ticker)


async def _run_other_analysts(ticker: str, exclude_analyst: str = "") -> list[str]:
    """Get other analysts who recently mentioned this ticker."""
    analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
    return [a for a in analysts if a != exclude_analyst]


async def _run_llm_score(ticker: str, catalyst: Optional[CatalystResult],
                          technical: Optional[TechnicalResult]) -> tuple[float, str]:
    """Get LLM confidence score."""
    return await score_confidence(ticker, None, None, catalyst, technical)


async def _run_options_check(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity."""
    try:
        from consensus_engine.scanners.options import check_unusual_options
        return await check_unusual_options(ticker, executor)
    except Exception as e:
        log.debug("Options check error for %s: %s", ticker, e)
        return None


async def cross_reference(ticker: str, tweet: ParsedTweet, executor=None) -> CrossReferenceResult:
    """Run all cross-reference sources in parallel and compute final score."""
    log.info("Starting cross-reference for $%s (base=%d)", ticker, tweet.base_score)
    m = cfg.get("scoring.multipliers", {})

    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, (llm_score, llm_reasoning), options = \
        await asyncio.gather(
            _run_news_cascade(ticker),
            _run_sec_check(ticker),
            _run_social_check(ticker),
            _run_technical(ticker),
            _run_other_analysts(ticker, exclude_analyst=tweet.analyst),
            _run_llm_score(ticker, None, None),
            _run_options_check(ticker, executor),
        )

    if technical or catalyst:
        llm_score, llm_reasoning = await _run_llm_score(ticker, catalyst, technical)

    analyst_pts = len(other_analysts) * m.get("additional_analyst", 20)
    news_pts = m.get("news_catalyst", 15) if (catalyst and catalyst.passed) else 0
    sec_pts = m.get("sec_filing", 15) if sec_hit else 0
    tech_pts = compute_technical_score(technical)
    social_breakdown = _compute_social_breakdown(social_data)

    llm_max = m.get("llm_boost_max", 15)
    llm_pts = int(llm_score / 100 * llm_max)

    options_pts = m.get("options_flow", 10) if (options and options.has_unusual_activity) else 0

    social_parts = []
    if social_data.get("apewisdom", 0) >= 1:
        social_parts.append(f"ApeWisdom ({social_data['apewisdom']} mentions)")
    if social_data.get("stocktwits", 0) >= 1:
        social_parts.append("StockTwits trending")
    if social_data.get("reddit", 0) >= 2:
        social_parts.append(f"Reddit ({social_data['reddit']} mentions)")
    if social_data.get("google_trends", 0) >= 1:
        social_parts.append("Google Trends spike")

    breakdown = ScoreBreakdown(
        base=tweet.base_score,
        additional_analysts=analyst_pts,
        news_catalyst=news_pts,
        sec_filing=sec_pts,
        technical=tech_pts,
        llm_boost=llm_pts,
        options_flow=options_pts,
        **social_breakdown,
    )

    result = CrossReferenceResult(
        ticker=ticker,
        breakdown=breakdown,
        catalyst_summary=catalyst.catalyst_summary if catalyst else "",
        catalyst_type=catalyst.catalyst_type if catalyst else "",
        catalyst_sources=catalyst.news_sources if catalyst else [],
        catalyst_urls=catalyst.source_urls if catalyst else [],
        technical=technical,
        other_analysts=other_analysts,
        social_summary=", ".join(social_parts) if social_parts else "",
        sec_summary=sec_summary,
        llm_reasoning=llm_reasoning,
        options=options,
    )

    log.info("Cross-reference for $%s: score=%d (base=%d + xref=%d)",
             ticker, result.final_score, tweet.base_score,
             result.final_score - tweet.base_score)

    return result
