"""Main orchestrator for the Stock Trend Consensus Engine.

Runs all scanner stages concurrently and evaluates consensus on a loop.

Usage:
    python3 -m consensus_engine              # Run the full engine
    python3 -m consensus_engine --once       # Run one cycle and exit
    python3 -m consensus_engine --test       # Inject test data and verify
"""

import asyncio
import logging
import signal
import sys
import time

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils import setup_logging
from consensus_engine.scanners.twitter import scan_twitter_accounts
from consensus_engine.scanners.social import (
    scan_reddit, scan_stocktwits, scan_apewisdom, scan_google_trends,
)
from consensus_engine.scanners.news import scan_news_for_tickers
from consensus_engine.consensus import run_consensus_cycle

log: logging.Logger


async def scanner_loop_twitter(stop_event: asyncio.Event):
    """Stage 1: Twitter/X scanning loop."""
    interval = cfg.get("intervals.twitter_scan", 120)
    while not stop_event.is_set():
        try:
            signals = await scan_twitter_accounts()
            if signals:
                await db.insert_signals(signals)
                log.info("Twitter: stored %d signals", len(signals))
        except Exception as e:
            log.error("Twitter scanner error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def scanner_loop_social(stop_event: asyncio.Event):
    """Stage 2: Social scanning loop (Reddit, StockTwits, ApeWisdom)."""
    interval = cfg.get("intervals.social_scan", 300)
    while not stop_event.is_set():
        try:
            # Run all social scanners concurrently
            reddit_task = scan_reddit()
            stocktwits_task = scan_stocktwits()
            apewisdom_task = scan_apewisdom()

            results = await asyncio.gather(
                reddit_task, stocktwits_task, apewisdom_task,
                return_exceptions=True,
            )

            all_signals = []
            for r in results:
                if isinstance(r, list):
                    all_signals.extend(r)
                elif isinstance(r, Exception):
                    log.error("Social scanner error: %s", r)

            if all_signals:
                await db.insert_signals(all_signals)
                log.info("Social: stored %d signals", len(all_signals))

            # Google Trends — only check tickers that already have signals
            active = await db.get_active_tickers(min_signals=3)
            if active:
                trends = await scan_google_trends(active[:10])
                # Store trend signals
                from consensus_engine.models import TickerSignal, SourceType, Sentiment
                for ticker, delta in trends.items():
                    await db.insert_signal(TickerSignal(
                        ticker=ticker,
                        source_type=SourceType.GOOGLE_TRENDS,
                        source_detail=f"delta={delta:.1f}",
                        raw_text=f"Google Trends spike: {delta:.1f}",
                        sentiment=Sentiment.BULLISH if delta > 0 else Sentiment.NEUTRAL,
                    ))

        except Exception as e:
            log.error("Social scanner error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def scanner_loop_news(stop_event: asyncio.Event):
    """Stage 3: News scanning loop — only triggers for active tickers."""
    interval = cfg.get("intervals.news_scan", 300)
    while not stop_event.is_set():
        try:
            # Only search news for tickers that have signals from both twitter + social
            active = await db.get_active_tickers(min_signals=3)
            tickers_needing_news = []

            for ticker in active[:15]:
                counts = await db.get_signal_counts_by_source(ticker)
                has_twitter = counts.get("twitter", 0) > 0
                has_social = any(counts.get(s, 0) > 0 for s in
                                 ["reddit", "stocktwits", "apewisdom", "google_trends"])
                has_news = counts.get("news", 0) > 0
                if (has_twitter or has_social) and not has_news:
                    tickers_needing_news.append(ticker)

            if tickers_needing_news:
                signals = await scan_news_for_tickers(tickers_needing_news)
                if signals:
                    await db.insert_signals(signals)
                    log.info("News: stored %d signals for %d tickers",
                             len(signals), len(tickers_needing_news))

        except Exception as e:
            log.error("News scanner error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def consensus_loop(stop_event: asyncio.Event):
    """Consensus evaluation loop — checks every 30 seconds."""
    interval = cfg.get("intervals.consensus_eval", 30)
    # Wait for initial data before first evaluation
    await asyncio.sleep(min(interval, 10))

    while not stop_event.is_set():
        try:
            await run_consensus_cycle()
        except Exception as e:
            log.error("Consensus evaluator error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def prune_loop(stop_event: asyncio.Event):
    """Database pruning loop — cleans expired signals every 15 minutes."""
    interval = cfg.get("intervals.state_prune", 900)
    while not stop_event.is_set():
        try:
            pruned = await db.prune_expired()
        except Exception as e:
            log.error("Prune error: %s", e)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def run(once: bool = False):
    """Main engine entry point.

    Args:
        once: If True, run one cycle of all scanners + consensus and exit.
    """
    global log
    cfg.load_config()
    log = setup_logging()

    log.info("=" * 60)
    log.info("Stock Trend Consensus Engine starting...")
    log.info("Twitter accounts: %d", len(cfg.get_twitter_accounts()))
    log.info("Subreddits: %s", ", ".join(cfg.get("social.subreddits", [])))
    log.info("Technical filters: %d", 6)
    log.info("Min LLM confidence: %d", cfg.get("llm.min_confidence", 70))
    log.info("=" * 60)

    await db.init_db()

    if once:
        # Single cycle mode
        log.info("Running single cycle...")

        # Run scanners concurrently
        twitter_signals, reddit_signals, st_signals, ape_signals = await asyncio.gather(
            scan_twitter_accounts(),
            scan_reddit(),
            scan_stocktwits(),
            scan_apewisdom(),
            return_exceptions=True,
        )

        for result in [twitter_signals, reddit_signals, st_signals, ape_signals]:
            if isinstance(result, list) and result:
                await db.insert_signals(result)

        # News scan for active tickers
        active = await db.get_active_tickers(min_signals=2)
        if active:
            news_signals = await scan_news_for_tickers(active[:10])
            if isinstance(news_signals, list):
                await db.insert_signals(news_signals)

        # Run consensus
        await run_consensus_cycle()
        await db.close_db()
        log.info("Single cycle complete.")
        return

    # Continuous mode — run all loops concurrently
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    tasks = [
        asyncio.create_task(scanner_loop_twitter(stop_event), name="twitter-scanner"),
        asyncio.create_task(scanner_loop_social(stop_event), name="social-scanner"),
        asyncio.create_task(scanner_loop_news(stop_event), name="news-scanner"),
        asyncio.create_task(consensus_loop(stop_event), name="consensus-evaluator"),
        asyncio.create_task(prune_loop(stop_event), name="pruner"),
    ]

    log.info("All scanner loops started. Monitoring...")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await db.close_db()
        log.info("Engine stopped.")


def main():
    """CLI entry point."""
    once = "--once" in sys.argv
    test = "--test" in sys.argv

    if test:
        from consensus_engine.tests import run_test
        asyncio.run(run_test())
    else:
        asyncio.run(run(once=once))


if __name__ == "__main__":
    main()
