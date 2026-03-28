"""Signal-first pipeline orchestrator for the Stock Trend Consensus Engine.

Nitter RSS polls trigger instant Discord alerts. Cross-references run
asynchronously and update the alert with a detail follow-up reply.

Usage:
    python3 -m consensus_engine              # Run the full engine
    python3 -m consensus_engine --once       # Run one poll cycle and exit
    python3 -m consensus_engine --test       # Run the test suite
    python3 -m consensus_engine --status     # Print engine health report
    python3 -m consensus_engine --dry-run    # Run without sending Discord alerts
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils import setup_logging
from consensus_engine.models import (
    TickerSignal, SourceType, Sentiment,
)
from consensus_engine.scanners.nitter import NitterPoller
from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
from consensus_engine.scanners.social import (
    scan_reddit, scan_stocktwits, scan_apewisdom, scan_google_trends,
)
from consensus_engine.analysis.tweet_parser import parse_tweet
from consensus_engine.cross_reference import cross_reference
from consensus_engine.alerts.discord import send_instant_ping, send_detail_followup, send_trend_digest
from consensus_engine.alerts.commands import route_command
from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
from consensus_engine.utils.tickers import validate_ticker_market_cap, is_valid_ticker
from consensus_engine.models import Conviction, Direction

log = logging.getLogger("consensus_engine")

_executor = ThreadPoolExecutor(max_workers=4)


def shutdown_executor():
    _executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Core tweet processing pipeline
# ---------------------------------------------------------------------------

async def _fetch_price(ticker: str) -> float:
    """Fetch current price via yfinance (blocking, runs in executor)."""
    try:
        import yfinance as yf
        loop = asyncio.get_event_loop()
        t = await loop.run_in_executor(_executor, lambda: yf.Ticker(ticker))
        info = await loop.run_in_executor(_executor, lambda: t.fast_info)
        return float(getattr(info, "last_price", 0) or 0)
    except Exception as e:
        log.debug("Price fetch failed for %s: %s", ticker, e)
        return 0.0


def _passes_quality_gate(parsed, ticker: str) -> bool:
    """Pre-alert quality check. Pure Python, no I/O."""
    if not is_valid_ticker(ticker):
        return False
    if len(ticker) < 2:
        return False
    if parsed.conviction == Conviction.LOW and parsed.direction == Direction.NEUTRAL:
        return False
    if len(parsed.raw_text.strip()) < 15:
        return False
    min_score = cfg.get("alerts.min_base_score_for_alert", 25)
    if parsed.base_score < min_score:
        return False
    return True


async def process_tweet(tweet_data: dict):
    """Process a single new tweet through the signal-first pipeline.

    1. Parse with LLM (classify type, extract tickers/direction)
    2. Skip non-actionable types (B, D)
    3. Validate ticker (market cap check)
    4. Send instant Discord ping (Phase 1)
    5. Launch async cross-reference (Phase 2)
    """
    url = tweet_data["url"]
    analyst = tweet_data["analyst"]
    text = tweet_data["text"]
    image_url = tweet_data.get("image_url")

    parsed = await parse_tweet(url, analyst, text, image_url=image_url)

    log.info("Tweet from @%s: type=%s tickers=%s dir=%s conv=%s — %s",
             analyst, parsed.tweet_type.value, parsed.tickers,
             parsed.direction.value, parsed.conviction.value, text[:80])

    if not parsed.is_actionable:
        log.info("REJECTED @%s: non-actionable type=%s", analyst, parsed.tweet_type.value)
        return

    if not parsed.tickers:
        log.info("REJECTED @%s: no tickers extracted", analyst)
        return

    ticker = parsed.tickers[0]

    # Market-cap validation
    if not await validate_ticker_market_cap(ticker):
        log.info("REJECTED $%s from @%s: failed market-cap validation", ticker, analyst)
        return

    # Quality gate — block low-quality signals before instant ping
    if not _passes_quality_gate(parsed, ticker):
        log.info("REJECTED $%s from @%s: failed quality gate (conv=%s dir=%s score=%d)",
                 ticker, analyst, parsed.conviction.value, parsed.direction.value, parsed.base_score)
        return

    # Store the signal in DB
    await db.insert_signal(TickerSignal(
        ticker=ticker,
        source_type=SourceType.TWITTER,
        source_detail=analyst,
        raw_text=text[:500],
        sentiment=Sentiment.BULLISH if parsed.direction.value == "long" else
                  Sentiment.BEARISH if parsed.direction.value == "short" else
                  Sentiment.NEUTRAL,
        detected_at=time.time(),
    ))

    log.info("PASSED $%s from @%s: type=%s dir=%s conv=%s score=%d — sending alert",
             ticker, analyst, parsed.tweet_type.value, parsed.direction.value,
             parsed.conviction.value, parsed.base_score)

    # Fetch price + send instant ping concurrently
    price = await _fetch_price(ticker)
    msg_id = await send_instant_ping(parsed, current_price=price)

    if msg_id:
        # Record in DB for tracking
        row_id = await db.insert_alert_message(ticker, analyst, msg_id, parsed.base_score)
        # Launch cross-reference in background
        asyncio.create_task(
            _run_cross_reference_and_followup(ticker, parsed, msg_id, row_id, price),
            name=f"xref-{ticker}",
        )
    else:
        log.warning("Instant ping failed for $%s — skipping cross-reference", ticker)


async def _run_cross_reference_and_followup(
    ticker: str, parsed, msg_id: str, row_id: int, price_at_alert: float = 0.0
):
    """Background task: run cross-references then send detail follow-up."""
    try:
        xref = await cross_reference(ticker, parsed, executor=_executor)
        followup_id = await send_detail_followup(xref, msg_id)
        if followup_id:
            await db.update_alert_message_followup(row_id, followup_id, xref.final_score)
        # Record in alert_history
        await db.insert_alert(
            ticker=ticker,
            confidence=xref.final_score,
            catalyst=xref.catalyst_summary or "",
            catalyst_type=xref.catalyst_type or "",
            consensus_json=json.dumps({"breakdown": str(xref.breakdown)}),
            technical_json=json.dumps({"filters": len(xref.technical.filters) if xref.technical else 0}),
            analysts_json=json.dumps(xref.other_analysts),
            price=price_at_alert,
        )
    except Exception as e:
        log.error("Cross-reference failed for $%s: %s", ticker, e, exc_info=True)


# ---------------------------------------------------------------------------
# Scanner loops
# ---------------------------------------------------------------------------

async def nitter_poll_loop(stop_event: asyncio.Event):
    """Primary loop: poll Nitter RSS for new analyst tweets."""
    poller = NitterPoller()

    # Health check on startup
    healthy = await poller.health_check()
    if not healthy:
        log.warning("Nitter not reachable at startup — will retry each cycle")

    while not stop_event.is_set():
        try:
            new_tweets = await poller.poll_all()
            for tweet_data in new_tweets:
                try:
                    await process_tweet(tweet_data)
                except Exception as e:
                    log.error("Tweet processing error: %s", e, exc_info=True)
        except Exception as e:
            log.error("Nitter poll error: %s", e, exc_info=True)

        interval = poller.get_poll_interval()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def social_scan_loop(stop_event: asyncio.Event):
    """Background loop: scan social sources for cross-reference data."""
    interval = cfg.get("intervals.social_scan", 300)
    while not stop_event.is_set():
        try:
            t0 = time.time()
            # Reddit disabled — rate-limited (403); StockTwits disabled — Cloudflare blocked
            results = await asyncio.gather(
                scan_apewisdom(),
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

            # Google Trends for tickers that already have signals
            active = await db.get_active_tickers(min_signals=2)
            if active:
                trends = await scan_google_trends(active[:10])
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


async def price_followup_loop(stop_event: asyncio.Event):
    """Background loop: update price_1h_later and price_24h_later on past alerts."""
    interval = 300  # check every 5 minutes
    while not stop_event.is_set():
        try:
            for field in ("price_1h_later", "price_24h_later"):
                alerts = await db.get_alerts_needing_price_update(field)
                for alert in alerts:
                    try:
                        price = await _fetch_price(alert["ticker"])
                        if price > 0:
                            await db.update_alert_price(alert["id"], field, price)
                            pct = ((price - alert["price_at_alert"]) / alert["price_at_alert"] * 100
                                   if alert["price_at_alert"] else 0)
                            label = "1h" if field == "price_1h_later" else "24h"
                            log.info("Price %s for $%s: $%.2f → $%.2f (%+.1f%%)",
                                     label, alert["ticker"], alert["price_at_alert"], price, pct)
                    except Exception as e:
                        log.debug("Price followup error for %s: %s", alert["ticker"], e)
        except Exception as e:
            log.error("Price followup loop error: %s", e)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def tweetshift_listener_loop(stop_event: asyncio.Event):
    """Discord Gateway loop: receive TweetShift tweets and process them."""
    listener = DiscordTweetShiftListener(on_tweet=process_tweet, on_command=route_command)
    await listener.run(stop_event)


async def reddit_trend_loop(stop_event: asyncio.Event):
    """Background loop: crawl Reddit every 4h and post trend digest."""
    interval = cfg.get("intervals.reddit_trend", 14400)  # 4 hours
    while not stop_event.is_set():
        try:
            trending = await crawl_and_get_trending()
            if trending:
                await send_trend_digest(trending)
        except Exception as e:
            log.error("Reddit trend loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def prune_loop(stop_event: asyncio.Event):
    """Database pruning loop — cleans expired signals + daily VACUUM."""
    interval = cfg.get("intervals.state_prune", 900)
    last_vacuum = 0.0
    vacuum_interval = 86400  # once per day
    while not stop_event.is_set():
        try:
            await db.prune_expired()
            if time.time() - last_vacuum >= vacuum_interval:
                await db.vacuum()
                last_vacuum = time.time()
        except Exception as e:
            log.error("Prune error: %s", e)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Engine entry points
# ---------------------------------------------------------------------------

async def run(once: bool = False):
    """Main engine entry point."""
    global log
    cfg.load_config()
    log = setup_logging()

    log.info("=" * 60)
    log.info("OpenClaw Signal Engine starting...")
    log.info("Mode: %s", "signal-first (Nitter RSS)")
    log.info("Dry run: %s", cfg.dry_run)
    log.info("=" * 60)

    await db.init_db()

    if once:
        log.info("Running single poll cycle...")
        try:
            poller = NitterPoller()
            new_tweets = await poller.poll_all()
            for tweet_data in new_tweets:
                await process_tweet(tweet_data)
            # Wait briefly for background cross-reference tasks
            await asyncio.sleep(5)
            log.info("Single cycle complete: %d tweets processed", len(new_tweets))
        finally:
            shutdown_executor()
            await db.close_db()
        return

    # Continuous mode
    stop_event = asyncio.Event()
    tasks = []

    def _signal_handler():
        log.info("Shutdown signal received...")
        stop_event.set()
        # Cancel all running tasks so they don't hang
        for task in tasks:
            task.cancel()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    tasks = [
        # Nitter disabled — TweetShift handles tweet ingestion
        asyncio.create_task(tweetshift_listener_loop(stop_event), name="tweetshift-listener"),
        asyncio.create_task(social_scan_loop(stop_event), name="social-scanner"),
        asyncio.create_task(price_followup_loop(stop_event), name="price-followup"),
        asyncio.create_task(prune_loop(stop_event), name="pruner"),
        # Reddit trend disabled — Reddit rate-limits RSS feeds
    ]

    log.info("All loops started: tweetshift-listener, social-scanner, price-followup, pruner")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        shutdown_executor()
        await db.close_db()
        log.info("Engine stopped.")


async def print_status():
    """Print a quick engine health report."""
    cfg.load_config()
    await db.init_db()
    conn = await db.get_db()
    now = time.time()

    print("=" * 55)
    print("  OpenClaw Signal Engine — Status Report")
    print("=" * 55)

    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    try:
        db_size = os.path.getsize(db_path)
        size_str = f"{db_size / 1_048_576:.1f} MB" if db_size >= 1_048_576 else f"{db_size / 1024:.1f} KB"
    except OSError:
        size_str = "unknown"
    print(f"\n  Database: {db_path} ({size_str})")

    # Active signals
    cursor = await conn.execute(
        "SELECT source_type, COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ? GROUP BY source_type ORDER BY cnt DESC",
        (now,),
    )
    source_counts = await cursor.fetchall()
    total_signals = sum(r["cnt"] for r in source_counts)
    print(f"\n  Active signals: {total_signals}")
    for row in source_counts:
        print(f"    {row['source_type']:20s} {row['cnt']}")

    # Active tickers
    cursor = await conn.execute(
        "SELECT ticker, COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ? GROUP BY ticker ORDER BY cnt DESC LIMIT 15",
        (now,),
    )
    tickers = await cursor.fetchall()
    print(f"\n  Active tickers: {len(tickers)}")
    for row in tickers:
        print(f"    ${row['ticker']:8s} {row['cnt']} signals")

    # Seen tweets
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM seen_tweets")
    row = await cursor.fetchone()
    print(f"\n  Seen tweets: {row['cnt']}")

    # Alerts
    cutoff_24h = now - 86400
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM alert_history WHERE alerted_at > ?", (cutoff_24h,),
    )
    row = await cursor.fetchone()
    print(f"\n  Alerts (last 24h): {row['cnt']}")

    cursor = await conn.execute(
        """SELECT ticker, confidence_score, price_at_alert, price_1h_later, price_24h_later, alerted_at
           FROM alert_history WHERE alerted_at > ? ORDER BY alerted_at DESC LIMIT 5""",
        (cutoff_24h,),
    )
    for alert in await cursor.fetchall():
        ago = (now - alert["alerted_at"]) / 60
        line = f"    ${alert['ticker']:8s} score={alert['confidence_score']:.0f}  {ago:.0f}m ago"
        if alert["price_at_alert"] and alert["price_at_alert"] > 0:
            line += f"  entry=${alert['price_at_alert']:.2f}"
            if alert["price_1h_later"]:
                pct = (alert["price_1h_later"] - alert["price_at_alert"]) / alert["price_at_alert"] * 100
                line += f"  1h={pct:+.1f}%"
            if alert["price_24h_later"]:
                pct = (alert["price_24h_later"] - alert["price_at_alert"]) / alert["price_at_alert"] * 100
                line += f"  24h={pct:+.1f}%"
        print(line)

    # Nitter poll timing
    print("\n  Last timings:")
    for metric in ["nitter_poll_seconds", "scanner_social_seconds"]:
        cursor = await conn.execute(
            "SELECT value, recorded_at FROM pipeline_metrics WHERE metric_name = ? ORDER BY recorded_at DESC LIMIT 1",
            (metric,),
        )
        row = await cursor.fetchone()
        label = metric.replace("_seconds", "").replace("scanner_", "")
        if row:
            ago = (now - row["recorded_at"]) / 60
            print(f"    {label:20s} {row['value']:.1f}s  ({ago:.0f}m ago)")
        else:
            print(f"    {label:20s} no data")

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
        import subprocess
        sys.exit(subprocess.call([sys.executable, "-m", "pytest", "tests/", "-v"]))
    else:
        if dry_run:
            cfg.dry_run = True
        asyncio.run(run(once=once))


if __name__ == "__main__":
    main()
