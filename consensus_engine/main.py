"""Main orchestrator for the Stock Trend Consensus Engine.

Runs all scanner stages concurrently and evaluates consensus on a loop.

Usage:
    python3 -m consensus_engine              # Run the full engine
    python3 -m consensus_engine --once       # Run one cycle and exit
    python3 -m consensus_engine --test       # Inject test data and verify
    python3 -m consensus_engine --status     # Print engine health report
    python3 -m consensus_engine --dry-run    # Run without sending Discord alerts
"""

import asyncio
import logging
import os
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
from consensus_engine.analysis.technical import shutdown_executor

log = logging.getLogger("consensus_engine")


async def scanner_loop_twitter(stop_event: asyncio.Event):
    """Stage 1: Twitter/X scanning loop."""
    interval = cfg.get("intervals.twitter_scan", 120)
    while not stop_event.is_set():
        try:
            t0 = time.time()
            signals = await scan_twitter_accounts()
            elapsed = time.time() - t0
            await db.record_metric("scanner_twitter_seconds", elapsed)
            if signals:
                await db.insert_signals(signals)
                log.info("Twitter: stored %d signals in %.1fs", len(signals), elapsed)
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
            t0 = time.time()
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

            elapsed = time.time() - t0
            await db.record_metric("scanner_social_seconds", elapsed)
            if all_signals:
                await db.insert_signals(all_signals)
                log.info("Social: stored %d signals in %.1fs", len(all_signals), elapsed)

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
            t0 = time.time()
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

            elapsed = time.time() - t0
            await db.record_metric("scanner_news_seconds", elapsed)

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
        try:
            # Run scanners concurrently
            twitter_signals, reddit_signals, st_signals, ape_signals = await asyncio.gather(
                scan_twitter_accounts(),
                scan_reddit(),
                scan_stocktwits(),
                scan_apewisdom(),
                return_exceptions=True,
            )

            for result in [twitter_signals, reddit_signals, st_signals, ape_signals]:
                if isinstance(result, Exception):
                    log.error("Scanner error in single cycle: %s", result)
                elif isinstance(result, list) and result:
                    await db.insert_signals(result)

            # News scan for active tickers
            active = await db.get_active_tickers(min_signals=2)
            if active:
                try:
                    news_signals = await scan_news_for_tickers(active[:10])
                    if isinstance(news_signals, list):
                        await db.insert_signals(news_signals)
                except Exception as e:
                    log.error("News scan error in single cycle: %s", e)

            # Run consensus
            await run_consensus_cycle()
            log.info("Single cycle complete.")
        finally:
            shutdown_executor()
            await db.close_db()
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
        shutdown_executor()
        await db.close_db()
        log.info("Engine stopped.")


async def print_status():
    """Print a quick engine health report from the database."""
    cfg.load_config()
    await db.init_db()
    conn = await db.get_db()
    now = time.time()

    print("=" * 55)
    print("  Stock Trend Consensus Engine — Status Report")
    print("=" * 55)

    # Database size
    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    try:
        db_size = os.path.getsize(db_path)
        if db_size >= 1_048_576:
            size_str = f"{db_size / 1_048_576:.1f} MB"
        else:
            size_str = f"{db_size / 1024:.1f} KB"
    except OSError:
        size_str = "unknown"
    print(f"\n  Database: {db_path} ({size_str})")

    # Active signals by source type
    cursor = await conn.execute(
        """SELECT source_type, COUNT(*) as cnt FROM ticker_signals
           WHERE expires_at > ? GROUP BY source_type ORDER BY cnt DESC""",
        (now,),
    )
    source_counts = await cursor.fetchall()
    total_signals = sum(r["cnt"] for r in source_counts)
    print(f"\n  Active signals: {total_signals}")
    for row in source_counts:
        print(f"    {row['source_type']:20s} {row['cnt']}")

    # Active tickers
    cursor = await conn.execute(
        """SELECT ticker, COUNT(*) as cnt FROM ticker_signals
           WHERE expires_at > ? GROUP BY ticker ORDER BY cnt DESC LIMIT 15""",
        (now,),
    )
    tickers = await cursor.fetchall()
    print(f"\n  Active tickers: {len(tickers)}")
    for row in tickers:
        print(f"    ${row['ticker']:8s} {row['cnt']} signals")

    # Alerts in last 24h
    cutoff_24h = now - 86400
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM alert_history WHERE alerted_at > ?",
        (cutoff_24h,),
    )
    row = await cursor.fetchone()
    alerts_24h = row["cnt"]

    cursor = await conn.execute(
        """SELECT ticker, confidence_score, alerted_at FROM alert_history
           WHERE alerted_at > ? ORDER BY alerted_at DESC LIMIT 5""",
        (cutoff_24h,),
    )
    recent_alerts = await cursor.fetchall()
    print(f"\n  Alerts (last 24h): {alerts_24h}")
    for alert in recent_alerts:
        ago = (now - alert["alerted_at"]) / 60
        print(f"    ${alert['ticker']:8s} confidence={alert['confidence_score']:.0f}  {ago:.0f}m ago")

    # Last scanner timings from pipeline_metrics
    print("\n  Last scanner timings:")
    for scanner in ["scanner_twitter_seconds", "scanner_social_seconds", "scanner_news_seconds"]:
        cursor = await conn.execute(
            """SELECT value, recorded_at FROM pipeline_metrics
               WHERE metric_name = ? ORDER BY recorded_at DESC LIMIT 1""",
            (scanner,),
        )
        row = await cursor.fetchone()
        label = scanner.replace("scanner_", "").replace("_seconds", "")
        if row:
            ago = (now - row["recorded_at"]) / 60
            print(f"    {label:20s} {row['value']:.1f}s  ({ago:.0f}m ago)")
        else:
            print(f"    {label:20s} no data")

    # Last consensus cycle timing
    cursor = await conn.execute(
        """SELECT value, recorded_at FROM pipeline_metrics
           WHERE metric_name = 'consensus_cycle_seconds'
           ORDER BY recorded_at DESC LIMIT 1""",
    )
    row = await cursor.fetchone()
    if row:
        ago = (now - row["recorded_at"]) / 60
        print(f"    {'consensus':20s} {row['value']:.1f}s  ({ago:.0f}m ago)")

    print("\n" + "=" * 55)
    await db.close_db()


def main():
    """CLI entry point."""
    once = "--once" in sys.argv
    test = "--test" in sys.argv
    status = "--status" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if status:
        asyncio.run(print_status())
    elif test:
        from tests.test_consensus import run_test
        asyncio.run(run_test())
    else:
        if dry_run:
            cfg.dry_run = True
        asyncio.run(run(once=once))


if __name__ == "__main__":
    main()
