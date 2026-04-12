"""Cross-Reference Engine — orchestrates all multiplier sources.

Runs in parallel after the instant Discord ping. Computes a final
score from news, social, technical, other analysts, and LLM confidence.
"""

import asyncio
import logging
import time
from typing import Any, Optional

from consensus_engine.utils.xref_cache import get_cached_xref, cache_xref

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

_sem_news = asyncio.Semaphore(3)
_sem_social = asyncio.Semaphore(5)
_sem_technical = asyncio.Semaphore(3)
_sem_llm = asyncio.Semaphore(2)


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


def _get_catalyst_score(catalyst_type: str) -> int:
    """Look up tiered score for a catalyst type. Defaults to medium (15)."""
    tiers = cfg.get("scoring.catalyst_tiers", {})
    for tier_data in tiers.values():
        if catalyst_type in tier_data.get("types", []):
            return tier_data.get("score", 15)
    return tiers.get("medium", {}).get("score", 15)


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


async def _run_technical(ticker: str, direction: str = "long") -> Optional[TechnicalResult]:
    return await verify_technical(ticker, direction=direction)


async def _run_other_analysts(ticker: str, exclude_analyst: str = "") -> list[str]:
    """Get other analysts who recently mentioned this ticker."""
    analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
    return [a for a in analysts if a != exclude_analyst]


async def _run_llm_score(ticker: str, catalyst: Optional[CatalystResult],
                          technical: Optional[TechnicalResult], sec_summary: str = "") -> tuple[float, str]:
    """Get LLM confidence score with SEC/EDGAR data for thesis generation."""
    return await score_confidence(ticker, None, None, catalyst, technical, sec_summary)


async def _timed(coro, metrics: dict, key: str) -> Any:
    """Await a coroutine and record its elapsed time in milliseconds to metrics."""
    t0 = time.perf_counter()
    result = await coro
    metrics[key] = int((time.perf_counter() - t0) * 1000)
    return result


async def _with_timeout(coro, timeout: float, default: Any, label: str,
                        sem: Optional[asyncio.Semaphore] = None) -> Any:
    """Run a coroutine with a timeout, returning default on timeout or error."""
    async def _run():
        if sem is None:
            return await coro
        async with sem:
            return await coro

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("Cross-reference source timed out after %.0fs: %s", timeout, label)
        await db.record_metric(f"xref_{label}_timeout", 1)
        return default
    except Exception as e:
        log.warning("Cross-reference source error (%s): %s", label, e)
        await db.record_metric(f"xref_{label}_error", 1)
        return default


async def _run_options_check(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity."""
    if executor is None:
        return None
    try:
        from consensus_engine.scanners.options import check_unusual_options
        return await check_unusual_options(ticker, executor)
    except Exception as e:
        log.debug("Options check error for %s: %s", ticker, e)
        return None


async def _get_youtube_context(ticker: str):
    """Query YouTube signals for ticker (8th source for cross-reference)."""
    try:
        from consensus_engine.models import YouTubeContext, Direction, Conviction
        mentions = await db.get_youtube_signals_for_ticker(ticker, days=7)
        if not mentions:
            return None

        # Aggregate mentions
        direction_votes = {"long": 0, "short": 0, "neutral": 0}
        conviction_scores = {"high": 3, "medium": 2, "low": 1}
        max_conviction_score = 0
        top_conviction = "medium"

        for mention in mentions:
            direction = mention.get("direction", "neutral")
            conviction = mention.get("conviction", "medium")
            direction_votes[direction] = direction_votes.get(direction, 0) + 1
            conv_score = conviction_scores.get(conviction, 1)
            if conv_score > max_conviction_score:
                max_conviction_score = conv_score
                top_conviction = conviction

        # Consensus direction
        consensus_dir = max(direction_votes, key=direction_votes.get)

        # Get price levels
        levels = await db.get_youtube_levels_for_ticker(ticker, days=7)
        level_data = [
            {
                "type": level.get("level_type"),
                "price": level.get("price"),
                "confidence": level.get("confidence", 0.8),
            }
            for level in levels
        ]

        # Determine score boost
        conv_map = {"high": 15, "medium": 10, "low": 5}
        score_boost = conv_map.get(top_conviction, 10)

        return YouTubeContext(
            mention_count=len(mentions),
            direction=Direction(consensus_dir),
            top_conviction=Conviction(top_conviction),
            channels=list(set(m.get("channel_name") for m in mentions if m.get("channel_name"))),
            levels=level_data,
            score_boost=score_boost,
        )
    except Exception as e:
        log.debug("YouTube context error for $%s: %s", ticker, e)
        return None


async def cross_reference(ticker: str, tweet: ParsedTweet, executor=None) -> CrossReferenceResult:
    """Run all cross-reference sources in parallel and compute final score."""
    log.info("Starting cross-reference for $%s (base=%d)", ticker, tweet.base_score)
    m = cfg.get("scoring.multipliers", {})

    direction = tweet.direction.value if hasattr(tweet.direction, 'value') else "long"

    # Check xref cache (prevents redundant API calls for same ticker within 5 min)
    cached = await get_cached_xref(ticker)
    if cached is not None:
        log.info("Cross-reference cache HIT for $%s", ticker)
        return cached

    metrics: dict[str, int] = {}
    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, options, youtube = \
        await asyncio.gather(
            _with_timeout(_timed(_run_news_cascade(ticker), metrics, "news_cascade_ms"), 15.0, None, "news", sem=_sem_news),
            _with_timeout(_timed(_run_sec_check(ticker), metrics, "sec_check_ms"), 10.0, (False, ""), "sec", sem=_sem_news),
            _with_timeout(_timed(_run_social_check(ticker), metrics, "social_ms"), 5.0, {}, "social", sem=_sem_social),
            _with_timeout(_timed(_run_technical(ticker, direction=direction), metrics, "technical_ms"), 20.0, None, "technical", sem=_sem_technical),
            _with_timeout(_timed(_run_other_analysts(ticker, exclude_analyst=tweet.analyst), metrics, "analyst_check_ms"), 5.0, [], "analysts"),
            _with_timeout(_timed(_run_options_check(ticker, executor), metrics, "options_check_ms"), 15.0, None, "options", sem=_sem_technical),
            _with_timeout(_timed(_get_youtube_context(ticker), metrics, "youtube_ms"), 8.0, None, "youtube"),
        )

    llm_score, llm_reasoning = 0.0, ""
    if technical or catalyst:
        t0 = time.perf_counter()
        try:
            async with _sem_llm:
                llm_score, llm_reasoning = await asyncio.wait_for(
                    _run_llm_score(ticker, catalyst, technical, sec_summary), timeout=15.0
                )
        except asyncio.TimeoutError:
            log.warning("LLM scorer timed out after 15s for $%s", ticker)
        metrics["llm_score_ms"] = int((time.perf_counter() - t0) * 1000)

    max_analysts = cfg.get("scoring.multipliers.max_additional_analysts", 3)
    analyst_pts = min(len(other_analysts), max_analysts) * m.get("additional_analyst", 20)
    news_pts = _get_catalyst_score(catalyst.catalyst_type) if (catalyst and catalyst.passed) else 0
    sec_pts = m.get("sec_filing", 15) if sec_hit else 0
    tech_pts = compute_technical_score(technical)
    social_breakdown = _compute_social_breakdown(social_data)

    llm_max = m.get("llm_boost_max", 15)
    llm_pts = int(llm_score / 100 * llm_max)

    options_pts = m.get("options_flow", 10) if (options and options.has_unusual_activity) else 0

    youtube_pts = youtube.score_boost if youtube else 0

    social_parts = []
    if social_data.get("apewisdom", 0) >= 1:
        social_parts.append(f"ApeWisdom ({social_data['apewisdom']} mentions)")
    if social_data.get("stocktwits", 0) >= 1:
        social_parts.append("StockTwits trending")
    if social_data.get("reddit", 0) >= 2:
        social_parts.append(f"Reddit ({social_data['reddit']} mentions)")
    if social_data.get("google_trends", 0) >= 1:
        social_parts.append("Google Trends spike")

    youtube_parts = []
    if youtube:
        youtube_parts.append(f"YouTube ({youtube.mention_count} videos, {youtube.direction.value})")
        if youtube.levels:
            youtube_parts.append(f"Levels: {len(youtube.levels)} S/R zones")

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
    # Add YouTube boost directly to breakdown
    breakdown.llm_boost += youtube_pts  # Roll YouTube into LLM boost category

    # Build social + YouTube summary
    all_sources = social_parts + youtube_parts
    sources_summary = ", ".join(all_sources) if all_sources else ""

    result = CrossReferenceResult(
        ticker=ticker,
        breakdown=breakdown,
        catalyst_summary=catalyst.catalyst_summary if catalyst else "",
        catalyst_type=catalyst.catalyst_type if catalyst else "",
        catalyst_sources=catalyst.news_sources if catalyst else [],
        catalyst_urls=catalyst.source_urls if catalyst else [],
        technical=technical,
        other_analysts=other_analysts,
        social_summary=sources_summary,  # Include YouTube in summary
        sec_summary=sec_summary,
        llm_reasoning=llm_reasoning,
        options=options,
    )

    log.info("Cross-reference for $%s: score=%d (base=%d + xref=%d, youtube=%d)",
             ticker, result.final_score, tweet.base_score,
             result.final_score - tweet.base_score, youtube_pts)

    await cache_xref(ticker, result)

    # Record per-component latency metrics
    for metric_key, ms_value in metrics.items():
        await db.record_metric(f"xref_{metric_key}", ms_value)

    return result
