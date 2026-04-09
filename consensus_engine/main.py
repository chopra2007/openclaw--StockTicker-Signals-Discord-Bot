"""
Consensus Engine - Main orchestrator
Signal-first stock alert system
"""

import asyncio
import concurrent.futures
from dataclasses import asdict, replace
import json
import logging

import aiohttp

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    ScoreBreakdown,
    Sentiment,
    SourceType,
    TickerSignal,
)
from consensus_engine.scanners.social import (
    scan_apewisdom,
    scan_google_trends_combined as scan_google_trends,
    scan_reddit,
    scan_stocktwits,
)
from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
from consensus_engine.scanners.nitter import NitterPoller
from consensus_engine.analysis.tweet_parser import parse_tweet
from consensus_engine.cross_reference import cross_reference
from consensus_engine.alerts.discord import send_detail_followup, send_instant_ping
from consensus_engine.utils.http import get_session
from consensus_engine.utils.tickers import is_valid_ticker, validate_ticker_market_cap
from consensus_engine.scanners.youtube import youtube_poll_loop
from consensus_engine.engine import analyze_signal, SignalClass

log = logging.getLogger("consensus_engine.main")


# =============================================================================
# Signal Sources
# =============================================================================

async def fetch_signals(tickers: list[str] = None) -> int:
    """Fetch fresh signals from all sources. Returns count of new signals."""
    total = 0

    try:
        if cfg.get("social.apewisdom_enabled", True):
            results = await scan_apewisdom()
            for result in results:
                await db.insert_signal(result)
                total += 1
    except Exception as e:
        log.error("ApeWisdom scan failed: %s", e)

    try:
        if cfg.get("social.reddit_enabled", False):
            results = await scan_reddit()
            for result in results:
                await db.insert_signal(result)
                total += 1
    except Exception as e:
        log.error("Reddit scan failed: %s", e)

    try:
        if cfg.get("social.stocktwits_enabled", False):
            results = await scan_stocktwits()
            for result in results:
                await db.insert_signal(result)
                total += 1
    except Exception as e:
        log.error("StockTwits scan failed: %s", e)

    try:
        if cfg.get("social.google_trends_enabled", True):
            tickers_to_check = tickers or await db.get_active_tickers(min_signals=1)
            trends = await scan_google_trends(tickers_to_check[:10])
            for ticker, delta in trends.items():
                await db.insert_signal(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.GOOGLE_TRENDS,
                    source_detail=f"Pytrends delta={delta:.1f}%",
                    raw_text=f"Google Trends: {delta:.1f}%",
                    sentiment=Sentiment.BULLISH if delta > 0 else Sentiment.NEUTRAL,
                ))
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
            if filings:
                for filing in filings:
                    ticker = filing["ticker"]
                    company = filing["company"]
                    form_type = filing.get("form_type", "8-K")

                    log.info("SEC 8-K stored (no alert): $%s - %s", ticker, company)

                    await db.insert_signal(TickerSignal(
                        ticker=ticker,
                        source_type=SourceType.SEC_FILING,
                        source_detail=f"{form_type}: {company}",
                        raw_text=f"SEC {form_type}: {filing['url']}",
                        sentiment=Sentiment.NEUTRAL,
                    ))
        except Exception as e:
            log.error("SEC 8-K watcher error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


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
            if filings:
                for filing in filings:
                    ticker = filing["ticker"]
                    company = filing.get("company", ticker)
                    form_type = filing.get("form_type", "Unknown")

                    log.info("SEC filing stored (no alert): $%s - %s", ticker, company)

                    await db.insert_signal(TickerSignal(
                        ticker=ticker,
                        source_type=SourceType.SEC_FILING,
                        source_detail=f"{form_type}: {company}",
                        raw_text=f"SEC {form_type}: {filing.get('url', '')}",
                        sentiment=Sentiment.NEUTRAL,
                    ))
        except Exception as e:
            log.error("SEC EDGAR polling error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


# =============================================================================
# Run Modes
# =============================================================================

async def run_once():
    """Run one cycle of signal fetching."""
    log.info("Running consensus engine (once)...")
    count = await fetch_signals()
    log.info("Fetched %d new signals", count)
    return count


async def run_live(stop_event: asyncio.Event):
    """Run continuous mode with all scanners."""
    log.info("Starting live mode...")

    async def on_tweet(tweet_data: dict):
        await process_tweet(tweet_data)

    async def on_command(cmd: str, args: str, channel_id: str, message_id: str):
        from consensus_engine.alerts.commands import handle_command

        await handle_command(cmd, args, channel_id, message_id)

    tweetshift_listener = DiscordTweetShiftListener(on_tweet=on_tweet, on_command=on_command)
    tasks = [
        asyncio.create_task(nitter_poll_loop(stop_event)),
        asyncio.create_task(tweetshift_listener.run(stop_event)),
        asyncio.create_task(fetch_loop(stop_event, interval=300)),
        asyncio.create_task(price_outcome_loop(stop_event)),
        asyncio.create_task(youtube_poll_loop(stop_event)),
    ]
    if cfg.get("scanners.sec_background_watchers_enabled", False):
        tasks.extend([
            asyncio.create_task(sec_8k_watcher_loop(stop_event)),
            asyncio.create_task(sec_edgar_polling_loop(stop_event)),
        ])

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


def _tweet_sentiment(tweet) -> Sentiment:
    direction = getattr(getattr(tweet, "direction", None), "value", getattr(tweet, "direction", "neutral"))
    if direction == "long":
        return Sentiment.BULLISH
    if direction == "short":
        return Sentiment.BEARISH
    return Sentiment.NEUTRAL


def _serialize_breakdown(breakdown: ScoreBreakdown) -> str:
    return json.dumps({
        "base": breakdown.base,
        "additional_analysts": breakdown.additional_analysts,
        "news_catalyst": breakdown.news_catalyst,
        "sec_filing": breakdown.sec_filing,
        "social_apewisdom": breakdown.social_apewisdom,
        "social_stocktwits": breakdown.social_stocktwits,
        "social_reddit": breakdown.social_reddit,
        "google_trends": breakdown.google_trends,
        "technical": breakdown.technical,
        "llm_boost": breakdown.llm_boost,
        "options_flow": breakdown.options_flow,
        "total": breakdown.total,
    })


def _passes_quality_gate(tweet, ticker: str) -> bool:
    """Cheap pre-alert filter for obvious parser noise."""
    if not ticker or len(ticker) < 2 or not is_valid_ticker(ticker):
        return False
    if len((tweet.raw_text or "").strip()) < 10:
        return False

    # Block SEC/EDGAR/8-K content from triggering alerts - only store for cross-reference
    text_lower = (tweet.raw_text or "").lower()
    analyst_lower = (tweet.analyst or "").lower()
    if any(kw in text_lower for kw in ["8-k", "sec filing", "edgar", "form 4", "form-4", "filed with the sec", "filed an 8"]):
        log.debug("Blocking SEC content from alert: %s", ticker)
        return False
    if "sec" in analyst_lower and any(kw in analyst_lower for kw in ["edgar", "filing", "8k", "form"]):
        log.debug("Blocking SEC analyst from alert: %s", tweet.analyst)
        return False

    quality_score = tweet.base_score
    if getattr(getattr(tweet, "direction", None), "value", getattr(tweet, "direction", "neutral")) == "neutral":
        quality_score -= 5
    return quality_score >= 20


async def _fetch_price(ticker: str) -> float:
    """Fetch the current quote from Finnhub."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return 0.0

    try:
        session = await get_session()
        async with session.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": api_key},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status != 200:
                return 0.0
            data = await resp.json()
        return float(data.get("c") or 0.0)
    except Exception as e:
        log.debug("Price fetch failed for $%s: %s", ticker, e)
        return 0.0


async def process_tweet(raw_tweet: dict):
    """Parse a tweet, store the signal, and launch alert delivery."""
    tweet_url = raw_tweet.get("url") or raw_tweet.get("tweet_url") or ""
    analyst = raw_tweet.get("analyst") or ""
    text = raw_tweet.get("text") or ""

    analyst_norm = analyst.strip().lower().replace("_", " ").replace("-", " ")
    if "sec" in analyst_norm and "edgar" in analyst_norm:
        log.warning("Ignoring SEC/EDGAR standalone payload in tweet pipeline: analyst=%s", analyst)
        return

    if not tweet_url or not analyst or not text:
        log.warning("Skipping malformed tweet payload: %s", raw_tweet)
        return

    if await db.check_seen_tweet(tweet_url):
        return
    await db.mark_tweet_seen(tweet_url, analyst)

    tweet = await parse_tweet(tweet_url, analyst, text, image_url=raw_tweet.get("image_url"))
    tweet.avatar_url = raw_tweet.get("avatar_url")
    tweet.display_name = raw_tweet.get("display_name")

    if not tweet.is_actionable:
        for ticker in tweet.tickers:
            await db.insert_signal(TickerSignal(
                ticker=ticker,
                source_type=SourceType.TWITTER,
                source_detail=tweet.analyst,
                raw_text=tweet.raw_text,
                sentiment=_tweet_sentiment(tweet),
            ))
        return

    for ticker in tweet.tickers:
        if not _passes_quality_gate(tweet, ticker):
            continue
        if not await validate_ticker_market_cap(ticker):
            log.info("Skipping $%s from @%s due to market-cap filter", ticker, tweet.analyst)
            continue

        await db.insert_signal(TickerSignal(
            ticker=ticker,
            source_type=SourceType.TWITTER,
            source_detail=tweet.analyst,
            raw_text=tweet.raw_text,
            sentiment=_tweet_sentiment(tweet),
        ))

        if not await db.check_alert_cooldown(ticker):
            continue

        alert_tweet = replace(tweet, tickers=[ticker])
        price = await _fetch_price(ticker)
        instant_msg_id = await send_instant_ping(alert_tweet, price)
        if instant_msg_id is None:
            continue

        alert_row_id = await db.insert_alert(
            ticker=ticker,
            confidence=float(alert_tweet.base_score),
            catalyst="",
            catalyst_type="",
            consensus_json=_serialize_breakdown(ScoreBreakdown(base=alert_tweet.base_score)),
            technical_json=json.dumps({}),
            analysts_json=json.dumps([]),
            price=price,
        )
        alert_message_id = await db.insert_alert_message(
            ticker=ticker,
            analyst=tweet.analyst,
            instant_msg_id=instant_msg_id,
            base_score=alert_tweet.base_score,
        )
        asyncio.create_task(
            _run_cross_reference_and_followup(
                ticker,
                alert_tweet,
                instant_msg_id,
                alert_message_id,
                alert_row_id,
            ),
            name=f"xref-{ticker}-{instant_msg_id}",
        )


async def _run_cross_reference_and_followup(
    ticker: str,
    tweet,
    instant_msg_id: str,
    alert_message_id: int,
    alert_row_id: int,
):
    """Run slow xref work after the instant alert has already been persisted."""
    try:
        xref_task = asyncio.create_task(cross_reference(ticker, tweet))
        precision_task = asyncio.create_task(
            analyze_signal(ticker, base_score=tweet.base_score)
        )
        xref, precision = await asyncio.gather(xref_task, precision_task, return_exceptions=True)

        if isinstance(xref, Exception):
            raise xref
        if isinstance(precision, Exception):
            log.warning("Precision engine failed for $%s: %s", ticker, precision)
            precision = None

        if precision and not precision.get("skipped"):
            classification = precision.get("classification", SignalClass.IGNORE)
            log.info(
                "$%s precision classification: %s (score=%d, mainstream=%s, market_ok=%s)",
                ticker,
                classification.value,
                precision.get("total_score", 0),
                precision.get("has_mainstream"),
                precision.get("market_ok"),
            )

        followup_id = await send_detail_followup(xref, instant_msg_id, precision=precision)
        await db.update_alert_message_followup(alert_message_id, followup_id, xref.final_score)
        await db.update_alert_breakdown(
            alert_row_id,
            _serialize_breakdown(xref.breakdown),
            json.dumps(asdict(xref.technical)) if xref.technical else json.dumps({}),
            json.dumps(xref.other_analysts),
            confidence=float(xref.final_score),
            catalyst=xref.catalyst_summary,
            catalyst_type=xref.catalyst_type,
        )
    except Exception as e:
        log.error("Cross-reference follow-up failed for $%s: %s", ticker, e, exc_info=True)


async def nitter_poll_loop(stop_event: asyncio.Event):
    """Poll Nitter RSS feeds and hand any new tweets to the main pipeline."""
    poller = NitterPoller()
    healthy = await poller.health_check()
    if not healthy:
        log.warning("Nitter health check failed at startup")

    while not stop_event.is_set():
        try:
            for tweet_data in await poller.poll_all():
                await process_tweet(tweet_data)
        except Exception as e:
            log.error("Nitter poll loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poller.get_poll_interval())
        except asyncio.TimeoutError:
            continue


def _fetch_yfinance_price(ticker: str) -> float:
    """Blocking helper for 1h/24h price outcome tracking."""
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        fast_info = getattr(stock, "fast_info", None) or {}
        for key in ("lastPrice", "last_price", "regularMarketPrice"):
            price = fast_info.get(key) if hasattr(fast_info, "get") else None
            if price:
                return float(price)

        history = stock.history(period="5d", interval="1d")
        if history is not None and not history.empty:
            close = history["Close"].dropna()
            if not close.empty:
                return float(close.iloc[-1])
    except Exception as e:
        log.debug("Outcome price fetch failed for $%s: %s", ticker, e)
    return 0.0


async def price_outcome_loop(stop_event: asyncio.Event):
    """Backfill 1h and 24h alert outcome prices."""
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="price-outcome",
    )
    loop = asyncio.get_running_loop()

    try:
        while not stop_event.is_set():
            try:
                for field in ("price_1h_later", "price_24h_later"):
                    alerts = await db.get_alerts_needing_price_update(field)
                    for alert in alerts:
                        price = await loop.run_in_executor(executor, _fetch_yfinance_price, alert["ticker"])
                        if price > 0:
                            await db.update_alert_price(alert["id"], field, price)
            except Exception as e:
                log.error("Price outcome loop error: %s", e, exc_info=True)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                continue
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


# =============================================================================
# CLI Entry Points
# =============================================================================

def main():
    from consensus_engine.utils import setup_logging
    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Consensus Engine")
    parser.add_argument("--dry-run", action="store_true", help="Do not send alerts or bot replies")
    parser.add_argument("--once", action="store_true", help="Run once")
    parser.add_argument("--live", action="store_true", help="Run live mode")
    parser.add_argument("--status", action="store_true", help="Show status")
    args = parser.parse_args()

    cfg.dry_run = args.dry_run

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
