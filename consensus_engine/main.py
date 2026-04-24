"""
Consensus Engine - Main orchestrator
Signal-first stock alert system
"""

import asyncio
import concurrent.futures
from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta
import json
import logging
import time

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
from consensus_engine.analysis.tweet_parser import parse_tweet
from consensus_engine.cross_reference import cross_reference
from consensus_engine.alerts.discord import edit_instant_ping, send_detail_followup, send_instant_ping
from consensus_engine.analysis.calibration import calibrate, log_shadow_prediction
from consensus_engine.utils.http import close_session, get_session
from consensus_engine.utils.tickers import is_valid_ticker, validate_ticker_market_cap
from consensus_engine.scanners.youtube import youtube_poll_loop
from consensus_engine.engine import analyze_signal, SignalClass
from consensus_engine.research.atlas import atlas_worker_loop, atlas_sweep_loop
from consensus_engine.briefing.alfred import alfred_loop

log = logging.getLogger("consensus_engine.main")

ET = timezone(timedelta(hours=-4))  # Eastern Time (EDT)

# ---------------------------------------------------------------------------
# Source health tracking (in-process stats, flushed to DB every poll cycle)
# ---------------------------------------------------------------------------
_source_stats: dict[str, dict] = {}

# Global degraded-mode flag: set True when >=2 critical sources are unhealthy.
DEGRADED_MODE: bool = False


def _record_source_ok(source_id: str) -> None:
    """Record a successful data fetch for a source."""
    s = _source_stats.setdefault(source_id, {"calls": 0, "errors": 0, "last_ok": 0.0})
    s["calls"] += 1
    s["last_ok"] = time.time()


def _record_source_error(source_id: str) -> None:
    """Record a failed fetch for a source."""
    s = _source_stats.setdefault(source_id, {"calls": 0, "errors": 0, "last_ok": 0.0})
    s["calls"] += 1
    s["errors"] += 1


def _is_source_unhealthy(source_id: str) -> bool:
    """Return True if this source's in-process stats indicate it is unhealthy."""
    stats = _source_stats.get(source_id)
    if not stats or stats["last_ok"] == 0.0:
        return True  # Never seen a successful call
    max_age = cfg.get(f"source_health.source_max_age.{source_id}", 300)
    degraded_mult = cfg.get("source_health.degraded_freshness_multiplier", 5)
    max_error_rate = cfg.get("source_health.max_error_rate", 0.3)
    freshness = time.time() - stats["last_ok"]
    calls = stats["calls"]
    error_rate = stats["errors"] / calls if calls > 0 else 0.0
    return freshness > max_age * degraded_mult or error_rate > max_error_rate


def _recompute_degraded_mode() -> bool:
    """Return True if >=2 critical sources are currently unhealthy."""
    critical = cfg.get("source_health.critical_sources", ["finnhub", "yfinance"])
    unhealthy_count = sum(1 for src in critical if _is_source_unhealthy(src))
    return unhealthy_count >= 2


def _is_weekend_pause() -> bool:
    """Check if we're in the weekend pause window (Fri 3pm ET → Sun 2pm ET)."""
    now = datetime.now(ET)
    wd = now.weekday()  # Mon=0 … Sun=6
    if wd == 4 and now.hour >= 15:   # Friday 3pm+
        return True
    if wd == 5:                       # All Saturday
        return True
    if wd == 6 and now.hour < 14:    # Sunday before 2pm
        return True
    return False


def _seconds_until_resume() -> int:
    """Seconds until Sunday 2pm ET."""
    now = datetime.now(ET)
    wd = now.weekday()
    days_ahead = (6 - wd) % 7
    if days_ahead == 0 and now.hour >= 14:
        days_ahead = 7  # Already past Sunday 2pm, next week
    resume = now.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    return max(int((resume - now).total_seconds()), 1)


def _seconds_until_pause() -> int:
    """Seconds until Friday 3pm ET (next pause window)."""
    now = datetime.now(ET)
    wd = now.weekday()
    days_ahead = (4 - wd) % 7  # Friday=4
    if days_ahead == 0 and now.hour >= 15:
        days_ahead = 7  # Already past this Friday 3pm
    pause = now.replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    return max(int((pause - now).total_seconds()), 1)


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
            _record_source_ok("apewisdom")
    except Exception as e:
        log.error("ApeWisdom scan failed: %s", e)
        _record_source_error("apewisdom")

    try:
        if cfg.get("social.reddit_enabled", False):
            results = await scan_reddit()
            for result in results:
                await db.insert_signal(result)
                total += 1
            _record_source_ok("reddit")
    except Exception as e:
        log.error("Reddit scan failed: %s", e)
        _record_source_error("reddit")

    try:
        if cfg.get("social.stocktwits_enabled", False):
            results = await scan_stocktwits()
            for result in results:
                await db.insert_signal(result)
                total += 1
            _record_source_ok("stocktwits")
    except Exception as e:
        log.error("StockTwits scan failed: %s", e)
        _record_source_error("stocktwits")

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
    """Run continuous mode with all scanners. Pauses Fri 3pm–Sun 2pm ET."""
    while not stop_event.is_set():
        # Weekend pause gate
        if _is_weekend_pause():
            log.info("Weekend pause active — running command listener only")
            
            async def on_command_weekend(cmd, args, channel_id, message_id, author_id=None):
                from consensus_engine.alerts.commands import route_command
                await route_command(cmd, args, channel_id, message_id, author_id=author_id)
            
            async def _noop_tweet(_):
                pass

            # Run command listener during weekend
            tweetshift_listener = DiscordTweetShiftListener(
                on_tweet=_noop_tweet,
                on_command=on_command_weekend
            )
            weekend_stop = asyncio.Event()
            try:
                await tweetshift_listener.run(weekend_stop)
            except Exception as e:
                log.debug("Command listener paused: %s", e)
            
            await asyncio.sleep(5)
            continue

        log.info("Starting live mode...")

        async def on_tweet(tweet_data: dict):
            await process_tweet(tweet_data)

        async def on_command(cmd: str, args: str, channel_id: str, message_id: str, author_id: str | None = None):
            from consensus_engine.alerts.commands import route_command

            await route_command(cmd, args, channel_id, message_id, author_id=author_id)

        pause_event = asyncio.Event()

        async def weekend_watchdog():
            """Sleep exactly until Friday 3pm ET, then trigger pause."""
            secs = _seconds_until_pause()
            log.info("Weekend pause scheduled in %d seconds (Friday 3pm ET)", secs)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=secs)
            except asyncio.TimeoutError:
                log.info("Weekend pause triggered — stopping all scanners")
                pause_event.set()

        tweetshift_listener = DiscordTweetShiftListener(on_tweet=on_tweet, on_command=on_command)
        combined_stop = asyncio.Event()

        async def stop_watcher():
            """Set combined_stop when either stop_event or pause_event fires."""
            done, _ = await asyncio.wait(
                [asyncio.create_task(stop_event.wait()), asyncio.create_task(pause_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            combined_stop.set()

        tasks = [
            asyncio.create_task(stop_watcher()),
            asyncio.create_task(weekend_watchdog()),
            asyncio.create_task(tweetshift_listener.run(combined_stop)),
            asyncio.create_task(fetch_loop(combined_stop, interval=300)),
            asyncio.create_task(price_outcome_loop(combined_stop)),
            asyncio.create_task(youtube_poll_loop(combined_stop)),
            asyncio.create_task(source_health_updater_loop(combined_stop)),
            asyncio.create_task(macro_digest_loop(combined_stop)),
        ]
        if cfg.get("scanners.sec_background_watchers_enabled", False):
            tasks.extend([
                asyncio.create_task(sec_8k_watcher_loop(combined_stop)),
                asyncio.create_task(sec_edgar_polling_loop(combined_stop)),
            ])
        tasks.extend([
            asyncio.create_task(atlas_worker_loop(combined_stop)),
            asyncio.create_task(atlas_sweep_loop(combined_stop)),
            asyncio.create_task(alfred_loop(combined_stop)),
        ])

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Live mode cancelled")

        # Cancel any lingering tasks
        for t in tasks:
            if not t.done():
                t.cancel()

        if stop_event.is_set():
            await close_session()
            return  # Full shutdown requested


async def fetch_loop(stop_event: asyncio.Event, interval: int = 300):
    """Periodic signal fetching."""
    while not stop_event.is_set():
        try:
            await fetch_signals()
        except Exception as e:
            log.error("Fetch loop error: %s", e)
        try:
            await _check_youtube_level_alerts()
        except Exception as e:
            log.error("Level proximity check error: %s", e)
        await asyncio.sleep(interval)


async def _post_to_alerts_channel(text: str) -> None:
    """Post a plain text message to the main Discord alerts channel."""
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        return
    if cfg.dry_run:
        log.info("[DRY-RUN] alerts channel: %s", text[:80])
        return
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            async with session.post(url, headers=headers,
                                    json={"content": text[:2000]},
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status not in (200, 201):
                    log.warning("Discord post failed: %d", resp.status)
    except Exception as e:
        log.error("_post_to_alerts_channel error: %s", e)


async def _check_youtube_level_alerts() -> None:
    """Check stored YouTube price levels against current prices; alert on proximity."""
    proximity_pct = float(cfg.get("youtube.level_alert_proximity_pct", 0.005))
    cutoff = time.time() - (14 * 86400)
    try:
        conn = await db.get_db()
        cursor = await conn.execute(
            "SELECT DISTINCT ticker FROM youtube_levels WHERE extracted_at >= ?", (cutoff,)
        )
        tickers = [row["ticker"] for row in await cursor.fetchall()]
    except Exception as e:
        log.debug("Level alert ticker fetch failed: %s", e)
        return

    loop = asyncio.get_event_loop()
    for ticker in tickers:
        try:
            current_price = await loop.run_in_executor(None, _fetch_yfinance_price, ticker)
            if not current_price:
                continue
            levels = await db.get_youtube_levels_for_ticker(ticker, days=14)
            for level in levels:
                lv_price = float(level.get("price", 0.0))
                if not lv_price:
                    continue
                if abs(current_price - lv_price) / lv_price < proximity_pct:
                    if not await db.was_level_recently_alerted(ticker, lv_price):
                        ltype = level.get("level_type", "level")
                        channel = level.get("channel_name") or "unknown"
                        pub = level.get("published_at") or ""
                        days_ago = ""
                        if pub:
                            try:
                                from datetime import datetime as _dt, timezone as _tz
                                pub_dt = _dt.fromisoformat(pub.replace("Z", "+00:00"))
                                delta = int((_dt.now(_tz.utc) - pub_dt).total_seconds() / 86400)
                                days_ago = f" {delta} days ago"
                            except Exception:
                                pass
                        msg = (
                            f"🎯 ${ticker} approaching {ltype} @ ${lv_price:.2f}"
                            f" (flagged by {channel}{days_ago}) — current ${current_price:.2f}"
                        )
                        await _post_to_alerts_channel(msg)
                        await db.record_level_alert(ticker, ltype, lv_price, channel)
                        log.info("Level proximity alert fired: %s", msg)
        except Exception as e:
            log.debug("Level check error for %s: %s", ticker, e)


async def macro_digest_loop(stop_event: asyncio.Event) -> None:
    """Post daily macro digest to Discord at the configured UTC hour on weekdays."""
    last_posted_date = ""
    while not stop_event.is_set():
        try:
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)
            target_hour = int(cfg.get("youtube.macro_digest_utc_hour", 11))
            if now.weekday() < 5 and now.hour == target_hour:
                today = now.strftime("%Y-%m-%d")
                if today != last_posted_date:
                    from consensus_engine.alerts.commands import build_macro_digest
                    digest = await build_macro_digest()
                    await _post_to_alerts_channel(digest)
                    last_posted_date = today
                    log.info("Daily macro digest posted for %s", today)
        except Exception as e:
            log.error("macro_digest_loop error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            continue


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
        price = float(data.get("c") or 0.0)
        _record_source_ok("finnhub")
        return price
    except Exception as e:
        log.debug("Price fetch failed for $%s: %s", ticker, e)
        _record_source_error("finnhub")
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

    tweet = await parse_tweet(
        tweet_url,
        analyst,
        text,
        image_url=raw_tweet.get("image_url"),
        image_urls=raw_tweet.get("image_urls"),
    )
    tweet.avatar_url = raw_tweet.get("avatar_url")
    tweet.display_name = raw_tweet.get("display_name")
    tweet.discord_source_link = raw_tweet.get("discord_source_link")

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

        if not await db.check_alert_cooldown(ticker, tweet.analyst, tweet.base_score):
            continue

        # Degraded-mode suppression: skip high-confidence alerts when data is unreliable
        suppress_when_degraded = cfg.get("alerts.suppress_when_degraded", False)
        high_conf_threshold = cfg.get("precision_engine.thresholds.high_confidence", 80)
        if DEGRADED_MODE and suppress_when_degraded and tweet.base_score >= high_conf_threshold:
            log.warning(
                "DEGRADED_MODE: suppressing high-confidence alert for $%s (score=%d)",
                ticker, tweet.base_score,
            )
            continue

        alert_tweet = replace(tweet, tickers=[ticker])
        price = await _fetch_price(ticker)
        instant_msg_id = await send_instant_ping(alert_tweet, price, degraded=DEGRADED_MODE)
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

        # Q2a: wrap ONLY xref_task in wait_for. precision_task must survive an xref
        # timeout so a slow xref does not cancel the fast precision engine.
        timeout_sec = cfg.get("intervals.cross_reference_timeout", 120)
        xref_timed_out = False
        xref = None
        try:
            xref = await asyncio.wait_for(asyncio.shield(xref_task), timeout=timeout_sec)
        except asyncio.TimeoutError:
            xref_timed_out = True
            log.warning("Phase-2 xref timed out after %ss for $%s", timeout_sec, ticker)
        except Exception as e:
            log.error("Phase-2 xref failed for $%s: %s", ticker, e)

        try:
            precision = await precision_task
        except Exception as e:
            log.warning("Precision engine failed for $%s: %s", ticker, e)
            precision = None

        classification = None
        if precision and not precision.get("skipped"):
            classification = precision.get("classification", SignalClass.IGNORE)

        # Silent failure is the worst failure: surface the skip reason on the Phase-1 msg.
        if xref_timed_out:
            await edit_instant_ping(instant_msg_id, "Phase 2 skipped — timeout")
            return
        if classification == SignalClass.IGNORE:
            await edit_instant_ping(instant_msg_id, "Phase 2 skipped — low precision")
            return
        if xref is None:
            # xref raised a non-timeout exception; nothing to follow up with
            return

        if classification is not None:
            log.info(
                "$%s: precision=%s overrides xref_score=%.1f",
                ticker, classification, xref.final_score,
            )

        followup_id = await send_detail_followup(xref, instant_msg_id, precision=precision)
        await db.update_alert_message_followup(alert_message_id, followup_id, xref.final_score)

        # Q1 shadow-mode logging: record a decision_snapshots row and merge the
        # calibrated probability into its feature_vector_json. Never raises.
        try:
            final_score = float(xref.final_score)
            shadow_prob = calibrate(final_score, "1h")
            try:
                sources_json = _serialize_breakdown(xref.breakdown)
            except Exception:
                sources_json = "{}"
            snapshot_id = await db.record_decision_snapshot(
                ticker=ticker,
                decision=(classification.value if classification is not None else "UNCLASSIFIED"),
                final_score=final_score,
                sources_json=sources_json,
                contradiction_index=float(getattr(xref, "contradiction_index", 0.0) or 0.0),
            )
            await log_shadow_prediction(snapshot_id, score=final_score, calibrated_prob=shadow_prob)
        except Exception as shadow_exc:
            log.debug("shadow calibration logging skipped for $%s: %s", ticker, shadow_exc)

        breakdown_dict = json.loads(_serialize_breakdown(xref.breakdown))
        if classification is not None:
            breakdown_dict["precision_classification"] = classification.value
        await db.update_alert_breakdown(
            alert_row_id,
            json.dumps(breakdown_dict),
            json.dumps(asdict(xref.technical)) if xref.technical else json.dumps({}),
            json.dumps(xref.other_analysts),
            confidence=float(xref.final_score),
            catalyst=xref.catalyst_summary,
            catalyst_type=xref.catalyst_type,
        )
    except Exception as e:
        log.error("Cross-reference follow-up failed for $%s: %s", ticker, e, exc_info=True)


async def source_health_updater_loop(stop_event: asyncio.Event) -> None:
    """Periodically flush in-process source stats to the source_health DB table.

    Also recomputes the global DEGRADED_MODE flag after each flush.
    """
    global DEGRADED_MODE
    interval = cfg.get("source_health.poll_interval", 60)
    while True:
        try:
            now = time.time()
            for source_id, stats in list(_source_stats.items()):
                calls = stats["calls"]
                errors = stats["errors"]
                error_rate = errors / calls if calls > 0 else 0.0
                freshness = now - stats["last_ok"] if stats["last_ok"] > 0 else 9999.0
                await db.upsert_source_health(source_id, stats["last_ok"], error_rate, freshness)

            new_mode = _recompute_degraded_mode()
            if new_mode != DEGRADED_MODE:
                if new_mode:
                    log.warning("DEGRADED_MODE activated — >=2 critical sources unhealthy")
                else:
                    log.info("DEGRADED_MODE cleared — critical sources recovering")
            DEGRADED_MODE = new_mode
        except Exception as e:
            log.error("Source health updater error: %s", e)
        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
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
                _record_source_ok("yfinance")
                return float(close.iloc[-1])
    except Exception as e:
        log.debug("Outcome price fetch failed for $%s: %s", ticker, e)
        _record_source_error("yfinance")
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
        import fcntl
        _lock_file = open("/tmp/consensus_engine.lock", "w")
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("Another instance of consensus_engine --live is already running. Exiting.")
            _lock_file.close()
            return
        stop = asyncio.Event()
        asyncio.run(run_live(stop))
    else:
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
