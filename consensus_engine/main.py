"""
Consensus Engine - Main orchestrator
Signal-first stock alert system
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional
import os

from consensus_engine import config as cfg, db
from consensus_engine.models import Direction, Conviction, SourceType
from consensus_engine.scanners.social import (
    scan_reddit, scan_stocktwits, scan_apewisdom,
    scan_google_trends_combined as scan_google_trends,
)
from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
from consensus_engine.scanners.news import news_cascade
from consensus_engine.scanners.sec_edgar import check_recent_filings
from consensus_engine.scanners.sec_watcher import scan_8k_filings
from consensus_engine.analysis.llm_scorer import score_confidence
from consensus_engine.cross_reference import cross_reference
from consensus_engine.alerts.discord import send_instant_ping

log = logging.getLogger("consensus")

# =============================================================================
# Signal Sources
# =============================================================================

async def fetch_signals(tickers: list[str] = None) -> int:
    """Fetch fresh signals from all sources. Returns count of new signals."""
    total = 0

    # 1. Social: ApeWisdom
    try:
        if cfg.get("social.apewisdom_enabled", True):
            results = await scan_apewisdom()
            for r in results:
                await db.insert_signal(r)
                total += 1
    except Exception as e:
        log.error("ApeWisdom scan failed: %s", e)
    
    # 3. Social: Reddit
    try:
        if cfg.get("social.reddit_enabled", False):
            results = await scan_reddit()
            for r in results:
                await db.insert_signal(r)
                total += 1
    except Exception as e:
        log.error("Reddit scan failed: %s", e)
    
    # 4. Social: StockTwits
    try:
        if cfg.get("social.stocktwits_enabled", False):
            results = await scan_stocktwits()
            for r in results:
                await db.insert_signal(r)
                total += 1
    except Exception as e:
        log.error("StockTwits scan failed: %s", e)
    
    # 5. Google Trends (via Pytrends - free, runs frequently)
    try:
        if cfg.get("social.google_trends_enabled", True):
            tickers_to_check = tickers or await db.get_active_tickers(min_signals=1)
            trends = await scan_google_trends(tickers_to_check[:10])
            for ticker, delta in trends.items():
                await db.insert_signal({
                    "ticker": ticker,
                    "source_type": SourceType.GOOGLE_TRENDS,
                    "source_detail": f"Pytrends delta={delta:.1f}%",
                    "raw_text": f"Google Trends: {delta:.1f}%",
                    "sentiment": "BULLISH" if delta > 0 else "NEUTRAL",
                })
                total += 1
    except Exception as e:
        log.error("Google Trends scan failed: %s", e)
    
    return total


# =============================================================================
# SEC Watchers - NO ALERTS, STORE SIGNALS ONLY
# =============================================================================

async def sec_8k_watcher_loop(stop_event: asyncio.Event):
    """Background loop: poll SEC EDGAR for new 8-K filings every 15 min.
    
    IMPORTANT: 8-K filings NEVER trigger alerts on their own.
    They are stored as signals and added to cross-reference scoring only.
    """
    interval = 900
    while not stop_event.is_set():
        try:
            from consensus_engine.scanners.sec_watcher import scan_8k_filings
            filings = await scan_8k_filings()
            if not filings:
                await asyncio.sleep(interval)
                continue
                
            for filing in filings:
                ticker = filing["ticker"]
                company = filing["company"]
                form_type = filing.get("form_type", "8-K")
                
                # DO NOT send alert - only store for cross-reference
                log.info("SEC 8-K stored (no alert): $%s — %s", ticker, company)
                
                # Store as signal in DB only
                from consensus_engine.models import TickerSignal, SourceType, Sentiment
                await db.insert_signal(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.SEC_FILING,
                    source_detail=f"{form_type}: {company}",
                    raw_text=f"SEC {form_type}: {filing['url']}",
                    sentiment=Sentiment.NEUTRAL,
                ))
        except Exception as e:
            log.error("SEC 8-K watcher error: %s", e, exc_info=True)


async def sec_edgar_polling_loop(stop_event: asyncio.Event):
    """Background loop: poll SEC EDGAR for new filings every 5 min.

    IMPORTANT: SEC filings NEVER trigger standalone alerts.
    They are stored as signals and added to cross-reference scoring only.
    """
    interval = 300
    while not stop_event.is_set():
        try:
            from consensus_engine.scanners.sec_edgar import check_recent_filings
            filings = await check_recent_filings()
            if not filings:
                await asyncio.sleep(interval)
                continue

            for filing in filings:
                ticker = filing["ticker"]
                company = filing.get("company", ticker)
                form_type = filing.get("form_type", "Unknown")

                # DO NOT send alert - only store for cross-reference
                log.info("SEC filing stored (no alert): $%s — %s", ticker, company)

                # Store as signal in DB only
                from consensus_engine.models import TickerSignal, SourceType, Sentiment
                await db.insert_signal(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.SEC_FILING,
                    source_detail=f"{form_type}: {company}",
                    raw_text=f"SEC {form_type}: {filing.get('url', '')}",
                    sentiment=Sentiment.NEUTRAL,
                ))
        except Exception as e:
            log.error("SEC EDGAR polling error: %s", e, exc_info=True)


# =============================================================================
# Run Modes
# =============================================================================

async def run_once():
    """Run one cycle of signal fetching."""
    log.info("Running consensus engine (once)...")
    count = await fetch_signals()
    log.info(f"Fetched %d new signals", count)
    return count


async def run_live(stop_event: asyncio.Event):
    """Run continuous mode with all scanners."""
    log.info("Starting live mode...")

    # TweetShift listener callbacks
    async def on_tweet(tweet_data: dict):
        """Callback when TweetShift posts a new tweet."""
        await process_tweet(tweet_data)

    async def on_command(cmd: str, args: str, channel_id: str, message_id: str):
        """Callback when a command is received in Discord."""
        from consensus_engine.alerts.commands import handle_command
        await handle_command(cmd, args, channel_id, message_id)

    # Start background tasks
    tweetshift_listener = DiscordTweetShiftListener(on_tweet=on_tweet, on_command=on_command)
    tasks = [
        asyncio.create_task(tweetshift_listener.run(stop_event)),     # TweetShift Gateway listener
        asyncio.create_task(fetch_loop(stop_event, interval=300)),    # Social every 5 min
        asyncio.create_task(sec_8k_watcher_loop(stop_event)),         # 8-K every 15 min
        asyncio.create_task(sec_edgar_polling_loop(stop_event)),      # EDGAR every 5 min
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("Live mode cancelled")


async def fetch_loop(stop_event: asyncio.Event, interval: int = 300):
    """Periodic signal fetching."""
    while not stop_event.is_set():
        try:
            await fetch_signals()
        except Exception as e:
            log.error("Fetch loop error: %s", e)
        await asyncio.sleep(interval)


# =============================================================================
# CLI Entry Points
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Consensus Engine")
    parser.add_argument("--once", action="store_true", help="Run once")
    parser.add_argument("--live", action="store_true", help="Run live mode")
    parser.add_argument("--status", action="store_true", help="Show status")
    args = parser.parse_args()
    
    if args.status:
        print("Consensus Engine Status")
        print("Use --once or --live to run")
        return
    
    if args.live:
        stop = asyncio.Event()
        asyncio.run(run_live(stop))
    else:
        asyncio.run(run_once())


if __name__ == "__main__":
    main()