"""Discord command routing.

Handles !-prefixed commands received via the Discord Gateway.
Commands:
  !help               — list available commands
  !status             — engine status summary
  !trend              — last Reddit trend digest on demand
  !scan <TICKER>      — run cross-reference on a ticker and reply with score
  !performance        — alert win rates and P&L stats
  !signals <TICKER>   — active signal counts by source
  !analysts <TICKER>  — analysts who recently mentioned a ticker
  !active-tickers     — all tickers with active signals
  !sec <TICKER>       — recent SEC filings (8-K, Form 4, 13D, etc.)
  !options <TICKER>   — unusual options activity (call/put ratios, vol/OI)
  !technical <TICKER> — run 6 technical filters independently
  !news <TICKER>      — run news cascade standalone
  !nitter-health      — check if Nitter service is up
  !google-trends <T>  — Google Trends spike % for a ticker
  !apewisdom          — ApeWisdom trending tickers
  !alert-history <T>  — alert history with price outcomes for a ticker
"""

import asyncio
import logging
from typing import Optional

from consensus_engine.alerts.discord import send_command_reply
from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
from consensus_engine.alerts.discord import send_trend_digest

log = logging.getLogger("consensus_engine.alerts.commands")

HELP_TEXT = """**OpenClaw Signal Engine — Commands**
`!help` — show this message
`!status` — engine health summary (active signals, last alert)
`!trend` — post latest Reddit trend digest
`!scan <TICKER>` — full cross-reference on a ticker (e.g. `!scan NVDA`)
`!performance` — alert win rates and P&L stats

**Ticker Intel**
`!signals <TICKER>` — active signal counts by source
`!analysts <TICKER>` — analysts who recently mentioned a ticker
`!active-tickers` — all tickers with active signals right now
`!news <TICKER>` — run news cascade (headline + catalyst type)
`!sec <TICKER>` — recent SEC filings (8-K, Form 4, 13D, etc.)
`!options <TICKER>` — unusual options activity (vol/OI ratios)
`!technical <TICKER>` — 6 technical filters with pass/fail
`!google-trends <TICKER>` — Google Trends interest spike %
`!alert-history <TICKER>` — past alerts with 1h/24h price outcomes

**Market Scanners**
`!apewisdom` — ApeWisdom trending tickers
`!gaps` — pre-market gap scanner (>3% gaps)
`!leaderboard` — analyst win rate rankings

**Engine Health**
`!nitter-health` — check if Nitter service is responding
`!source-health` — data source status table (freshness, error rate)"""


def parse_command(content: str) -> Optional[tuple[str, list[str]]]:
    """Parse a Discord message into (command, args) if it starts with !.

    Returns None if the message is not a command.
    """
    content = content.strip()
    if not content.startswith("!"):
        return None
    parts = content[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


async def route_command(
    command: str,
    args: list[str],
    channel_id: str,
    message_id: str,
) -> None:
    """Dispatch a parsed command to its handler."""
    if command in ("help", "readme"):
        await send_command_reply(channel_id, message_id, HELP_TEXT)

    elif command == "status":
        await _handle_status(channel_id, message_id)

    elif command == "trend":
        await _handle_trend(channel_id, message_id)

    elif command == "performance":
        await _handle_performance(channel_id, message_id)

    elif command == "scan":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!scan <TICKER>` — e.g. `!scan NVDA`")
        else:
            await _handle_scan(args[0].upper(), channel_id, message_id)

    elif command == "signals":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!signals <TICKER>` — e.g. `!signals NVDA`")
        else:
            await _handle_signals(args[0].upper(), channel_id, message_id)

    elif command == "analysts":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!analysts <TICKER>` — e.g. `!analysts NVDA`")
        else:
            await _handle_analysts(args[0].upper(), channel_id, message_id)

    elif command in ("active-tickers", "active_tickers", "active"):
        await _handle_active_tickers(channel_id, message_id)

    elif command == "news":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!news <TICKER>` — e.g. `!news NVDA`")
        else:
            await _handle_news(args[0].upper(), channel_id, message_id)

    elif command == "sec":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!sec <TICKER>` — e.g. `!sec NVDA`")
        else:
            await _handle_sec(args[0].upper(), channel_id, message_id)

    elif command == "options":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!options <TICKER>` — e.g. `!options NVDA`")
        else:
            await _handle_options(args[0].upper(), channel_id, message_id)

    elif command == "technical":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!technical <TICKER>` — e.g. `!technical NVDA`")
        else:
            direction = args[1].lower() if len(args) > 1 and args[1].lower() in ("long", "short") else "long"
            await _handle_technical(args[0].upper(), direction, channel_id, message_id)

    elif command in ("google-trends", "trends", "gtrends"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!google-trends <TICKER>` — e.g. `!google-trends NVDA`")
        else:
            await _handle_google_trends(args[0].upper(), channel_id, message_id)

    elif command == "serpapi-trends":
        # Run SerpAPI Google Trends for active tickers (called via cron)
        await _run_serpapi_trends(channel_id, message_id)

    elif command == "apewisdom":
        await _handle_apewisdom(channel_id, message_id)

    elif command in ("alert-history", "history"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!alert-history <TICKER>` — e.g. `!alert-history NVDA`")
        else:
            await _handle_alert_history(args[0].upper(), channel_id, message_id)

    elif command == "gaps":
        await _handle_gaps(channel_id, message_id)

    elif command == "leaderboard":
        await _handle_leaderboard(channel_id, message_id)

    elif command in ("source-health", "source_health"):
        await _handle_source_health(channel_id, message_id)

    elif command in ("nitter-health", "nitter"):
        await _handle_nitter_health(channel_id, message_id)

    elif command == "transcript":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!transcript <YOUTUBE_URL>` — e.g. `!transcript https://www.youtube.com/watch?v=xxxxx`")
        else:
            await _handle_transcript(args[0], channel_id, message_id)

    else:
        await send_command_reply(channel_id, message_id, f"Unknown command `!{command}`. Try `!help`.")


# ---------------------------------------------------------------------------
# Existing handlers
# ---------------------------------------------------------------------------

async def _handle_status(channel_id: str, message_id: str) -> None:
    """Reply with a brief engine status summary."""
    try:
        from consensus_engine import db
        import time
        conn = await db.get_db()
        now = time.time()

        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ?", (now,)
        )
        row = await cursor.fetchone()
        active_signals = row["cnt"] if row else 0

        cursor = await conn.execute(
            "SELECT ticker, confidence_score, alerted_at FROM alert_history ORDER BY alerted_at DESC LIMIT 1"
        )
        last_alert = await cursor.fetchone()

        lines = ["**Engine Status**", f"Active signals: {active_signals}"]
        if last_alert:
            ago_min = int((now - last_alert["alerted_at"]) / 60)
            lines.append(f"Last alert: `${last_alert['ticker']}` score={last_alert['confidence_score']:.0f} ({ago_min}m ago)")
        else:
            lines.append("Last alert: none")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Status command error: %s", e)
        await send_command_reply(channel_id, message_id, "Status unavailable.")


async def _handle_trend(channel_id: str, message_id: str) -> None:
    """Trigger an on-demand Reddit trend digest."""
    try:
        await send_command_reply(channel_id, message_id, "Running trend scan... (may take ~30s)")
        trending = await crawl_and_get_trending()
        if trending:
            await send_trend_digest(trending)
            await send_command_reply(channel_id, message_id, f"Trend digest posted — {len(trending)} tickers found.")
        else:
            await send_command_reply(channel_id, message_id, "No trending tickers found right now.")
    except Exception as e:
        log.error("Trend command error: %s", e)
        await send_command_reply(channel_id, message_id, "Trend scan failed.")


async def _handle_performance(channel_id: str, message_id: str) -> None:
    """Reply with alert performance stats (win rates, P&L, top/worst alerts)."""
    try:
        from consensus_engine import db
        from datetime import datetime

        stats = await db.get_performance_stats()

        if stats["total_all"] == 0:
            await send_command_reply(channel_id, message_id, "No alert data yet.")
            return

        lines = ["**Alert Performance**"]
        lines.append(f"Total alerts: **{stats['total_all']}** all-time | **{stats['total_7d']}** last 7d")

        if stats["win_rate_1h"] is not None:
            lines.append(f"Win rate @ 1h: **{stats['win_rate_1h']:.1f}%** ({stats['total_1h']} alerts)")
        else:
            lines.append("Win rate @ 1h: no data")

        if stats["win_rate_24h"] is not None:
            lines.append(f"Win rate @ 24h: **{stats['win_rate_24h']:.1f}%** ({stats['total_24h']} alerts)")
        else:
            lines.append("Win rate @ 24h: no data")

        if stats["avg_pnl_1h"] is not None:
            sign = "+" if stats["avg_pnl_1h"] >= 0 else ""
            lines.append(f"Avg P&L @ 1h: **{sign}{stats['avg_pnl_1h']:.2f}%**")
        if stats["avg_pnl_24h"] is not None:
            sign = "+" if stats["avg_pnl_24h"] >= 0 else ""
            lines.append(f"Avg P&L @ 24h: **{sign}{stats['avg_pnl_24h']:.2f}%**")

        if stats["top3_best_1h"]:
            lines.append("\n**Top 3 Best (1h)**")
            for r in stats["top3_best_1h"]:
                dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
                lines.append(f"`${r['ticker']}` +{r['pnl_pct']:.2f}% ({dt})")

        if stats["top3_worst_1h"]:
            lines.append("\n**Top 3 Worst (1h)**")
            for r in stats["top3_worst_1h"]:
                dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
                lines.append(f"`${r['ticker']}` {r['pnl_pct']:.2f}% ({dt})")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Performance command error: %s", e)
        await send_command_reply(channel_id, message_id, "Performance stats unavailable.")


async def _handle_scan(ticker: str, channel_id: str, message_id: str) -> None:
    """Run cross-reference on a ticker and reply with results."""
    await send_command_reply(channel_id, message_id, f"Scanning `${ticker}`...")
    asyncio.create_task(_scan_and_reply(ticker, channel_id, message_id))


async def _scan_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    """Background task: run cross-reference and post results."""
    try:
        from consensus_engine.cross_reference import cross_reference
        from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction
        fake_tweet = ParsedTweet(
            tweet_url="command",
            analyst="command",
            raw_text=f"!scan {ticker}",
            tweet_type=TweetType.TICKER_CALLOUT,
            tickers=[ticker],
            direction=Direction.NEUTRAL,
            options=None,
            conviction=Conviction.MEDIUM,
            summary=f"On-demand scan for ${ticker}",
        )
        xref = await cross_reference(ticker, fake_tweet, executor=None)
        b = xref.breakdown
        parts = []
        if b.base: parts.append(f"base={b.base}")
        if b.news_catalyst: parts.append(f"news={b.news_catalyst}")
        if b.sec_filing: parts.append(f"sec={b.sec_filing}")
        if b.technical: parts.append(f"tech={b.technical}")
        if b.additional_analysts: parts.append(f"analysts={b.additional_analysts}")
        social = b.social_apewisdom + b.social_stocktwits + b.social_reddit + b.google_trends
        if social: parts.append(f"social={social}")
        if b.llm_boost: parts.append(f"llm={b.llm_boost}")
        if b.options_flow: parts.append(f"options={b.options_flow}")

        score_str = " + ".join(parts) + f" = **{xref.final_score}**"
        summary_lines = [f"**${ticker} Scan — Score: {xref.final_score}**", score_str]
        if xref.catalyst_summary:
            summary_lines.append(f"News: {xref.catalyst_summary[:200]}")
        if xref.social_summary:
            summary_lines.append(f"Social: {xref.social_summary}")
        if xref.options and xref.options.has_unusual_activity:
            opt = xref.options
            opt_parts = []
            if opt.unusual_calls: opt_parts.append(f"unusual calls ({opt.max_call_ratio:.1f}x vol/OI)")
            if opt.unusual_puts: opt_parts.append(f"unusual puts ({opt.max_put_ratio:.1f}x vol/OI)")
            summary_lines.append(f"Options: {', '.join(opt_parts)}")

        await send_command_reply(channel_id, message_id, "\n".join(summary_lines))
    except Exception as e:
        log.error("Scan background task error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Scan failed for `${ticker}`.")


# ---------------------------------------------------------------------------
# New Tier 1 handlers
# ---------------------------------------------------------------------------

async def _handle_signals(ticker: str, channel_id: str, message_id: str) -> None:
    """Show active signal counts by source for a ticker."""
    try:
        from consensus_engine import db
        counts = await db.get_signal_counts_by_source(ticker)
        if not counts:
            await send_command_reply(channel_id, message_id, f"No active signals for `${ticker}`.")
            return
        lines = [f"**Active Signals — ${ticker}**"]
        for source, count in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"`{source}`: {count}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Signals command error: %s", e)
        await send_command_reply(channel_id, message_id, f"Failed to fetch signals for `${ticker}`.")


async def _handle_analysts(ticker: str, channel_id: str, message_id: str) -> None:
    """Show analysts who recently mentioned a ticker."""
    try:
        from consensus_engine import db
        analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
        if not analysts:
            await send_command_reply(channel_id, message_id, f"No analysts mentioned `${ticker}` in the last hour.")
            return
        handles = ", ".join(f"@{a}" for a in analysts)
        await send_command_reply(channel_id, message_id, f"**Analysts mentioning ${ticker} (last 1h)**\n{handles}")
    except Exception as e:
        log.error("Analysts command error: %s", e)
        await send_command_reply(channel_id, message_id, f"Failed to fetch analysts for `${ticker}`.")


async def _handle_active_tickers(channel_id: str, message_id: str) -> None:
    """List all tickers with active signals."""
    try:
        from consensus_engine import db
        tickers = await db.get_active_tickers(min_signals=1)
        if not tickers:
            await send_command_reply(channel_id, message_id, "No active tickers right now.")
            return
        ticker_list = "  ".join(f"`${t}`" for t in tickers[:30])
        await send_command_reply(channel_id, message_id, f"**Active Tickers ({len(tickers)})**\n{ticker_list}")
    except Exception as e:
        log.error("Active-tickers command error: %s", e)
        await send_command_reply(channel_id, message_id, "Failed to fetch active tickers.")


async def _handle_news(ticker: str, channel_id: str, message_id: str) -> None:
    """Run news cascade for a ticker and reply with result."""
    await send_command_reply(channel_id, message_id, f"Running news scan for `${ticker}`...")
    asyncio.create_task(_news_and_reply(ticker, channel_id, message_id))


async def _news_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.news import news_cascade
        result = await news_cascade(ticker)
        if not result:
            await send_command_reply(channel_id, message_id, f"No news found for `${ticker}`.")
            return
        lines = [f"**News — ${ticker}**"]
        lines.append(f"Type: **{result.catalyst_type or 'General'}**")
        if result.catalyst_summary:
            lines.append(f"Summary: {result.catalyst_summary[:200]}")
        if result.news_sources:
            lines.append(f"Sources: {', '.join(result.news_sources[:3])}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("News command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"News scan failed for `${ticker}`.")


async def _handle_sec(ticker: str, channel_id: str, message_id: str) -> None:
    """Show recent SEC filings for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking SEC filings for `${ticker}`...")
    asyncio.create_task(_sec_and_reply(ticker, channel_id, message_id))


async def _sec_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.sec_edgar import check_recent_filings, classify_filing_significance
        filings = await check_recent_filings(ticker, hours_back=72)
        if not filings:
            await send_command_reply(channel_id, message_id, f"No SEC filings in the last 72h for `${ticker}`.")
            return
        has_significant, summary = classify_filing_significance(filings)
        lines = [f"**SEC Filings — ${ticker}** (last 72h)"]
        if summary:
            lines.append(summary)
        for f in filings[:8]:
            form = f.get("form", "?")
            filed = f.get("filing_date", "?")
            lines.append(f"`{form}` — {filed}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("SEC command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"SEC lookup failed for `${ticker}`.")


async def _handle_options(ticker: str, channel_id: str, message_id: str) -> None:
    """Show unusual options activity for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking options flow for `${ticker}`...")
    asyncio.create_task(_options_and_reply(ticker, channel_id, message_id))


async def _options_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.options import check_unusual_options
        result = await check_unusual_options(ticker, executor=None)
        if not result:
            await send_command_reply(channel_id, message_id, f"No options data available for `${ticker}`.")
            return
        lines = [f"**Options Flow — ${ticker}**"]
        lines.append(f"Put/Call ratio: **{result.put_call_ratio:.2f}**")
        if result.unusual_calls:
            lines.append(f"Unusual CALLS — max vol/OI ratio: **{result.max_call_ratio:.1f}x**")
        if result.unusual_puts:
            lines.append(f"Unusual PUTS — max vol/OI ratio: **{result.max_put_ratio:.1f}x**")
        if not result.has_unusual_activity:
            lines.append("No unusual activity detected.")
        if result.top_contract:
            lines.append(f"Top contract: `{result.top_contract}`")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Options command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Options lookup failed for `${ticker}`.")


async def _handle_technical(ticker: str, direction: str, channel_id: str, message_id: str) -> None:
    """Run technical filters for a ticker."""
    await send_command_reply(channel_id, message_id, f"Running technical analysis for `${ticker}` ({direction})...")
    asyncio.create_task(_technical_and_reply(ticker, direction, channel_id, message_id))


async def _technical_and_reply(ticker: str, direction: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.analysis.technical import verify_technical
        result = await verify_technical(ticker, direction=direction)
        if not result:
            await send_command_reply(channel_id, message_id, f"Could not fetch technical data for `${ticker}`.")
            return
        lines = [f"**Technical — ${ticker}** ({direction.upper()})  {result.passed_count}/{len(result.filters)} filters passed"]
        for f in result.filters:
            icon = "✅" if f.passed else "❌"
            lines.append(f"{icon} {f.name}: {f.value} ({f.threshold})")
        if result.price:
            lines.append(f"Price: **${result.price:.2f}** | Change: {result.price_change_pct:+.2f}%")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Technical command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Technical analysis failed for `${ticker}`.")


# ---------------------------------------------------------------------------
# New Tier 2 handlers
# ---------------------------------------------------------------------------

async def _handle_google_trends(ticker: str, channel_id: str, message_id: str) -> None:
    """Check Google Trends spike for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking Google Trends for `${ticker}`...")
    asyncio.create_task(_google_trends_and_reply(ticker, channel_id, message_id))


async def _google_trends_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.social import scan_google_trends
        results = await scan_google_trends([ticker])
        delta = results.get(ticker)
        if delta is None:
            await send_command_reply(channel_id, message_id, f"No Google Trends data for `${ticker}`.")
            return
        sign = "+" if delta >= 0 else ""
        verdict = "spike detected" if delta >= 20 else "normal interest"
        await send_command_reply(
            channel_id, message_id,
            f"**Google Trends — ${ticker}**\nInterest change: **{sign}{delta:.1f}%** ({verdict})"
        )
    except Exception as e:
        log.error("Google Trends command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Google Trends lookup failed for `${ticker}`.")


async def _run_serpapi_trends(channel_id: str, message_id: str) -> None:
    """Run SerpAPI Google Trends for all active tickers (cron job)."""
    await send_command_reply(channel_id, message_id, "Running SerpAPI Google Trends...")
    try:
        from consensus_engine import db
        from consensus_engine.scanners.social import scan_google_trends_serpapi
        from consensus_engine.models import TickerSignal, SourceType, Sentiment
        
        # Get active tickers
        active = await db.get_active_tickers(min_signals=2)
        if not active:
            await send_command_reply(channel_id, message_id, "No active tickers for SerpAPI Google Trends.")
            return
        
        # Run SerpAPI (not Pytrends)
        trends = await scan_google_trends_serpapi(active[:10])
        
        if not trends:
            await send_command_reply(channel_id, message_id, "SerpAPI Google Trends: No data returned.")
            return
        
        # Store results
        for ticker, delta in trends.items():
            await db.insert_signal(TickerSignal(
                ticker=ticker,
                source_type=SourceType.GOOGLE_TRENDS,
                source_detail=f"serpapi delta={delta:.1f}",
                raw_text=f"Google Trends (SerpAPI): {delta:.1f}%",
                sentiment=Sentiment.BULLISH if delta > 0 else Sentiment.NEUTRAL,
            ))
        
        # Format results
        lines = ["**SerpAPI Google Trends Results:**"]
        for ticker, delta in sorted(trends.items(), key=lambda x: -abs(x[1]))[:10]:
            sign = "+" if delta >= 0 else ""
            lines.append(f"  ${ticker}: {sign}{delta:.1f}%")
        
        await send_command_reply(channel_id, message_id, "\n".join(lines))
        
    except Exception as e:
        log.error("SerpAPI trends cron error: %s", e)
        await send_command_reply(channel_id, message_id, f"SerpAPI Google Trends failed: {e}")


async def _handle_apewisdom(channel_id: str, message_id: str) -> None:
    """Show ApeWisdom trending tickers."""
    await send_command_reply(channel_id, message_id, "Fetching ApeWisdom trending...")
    asyncio.create_task(_apewisdom_and_reply(channel_id, message_id))


async def _apewisdom_and_reply(channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.social import scan_apewisdom
        signals = await scan_apewisdom()
        if not signals:
            await send_command_reply(channel_id, message_id, "No ApeWisdom data available.")
            return
        lines = ["**ApeWisdom Trending**"]
        for i, s in enumerate(signals[:15], 1):
            lines.append(f"**{i}.** `${s.ticker}`")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("ApeWisdom command error: %s", e)
        await send_command_reply(channel_id, message_id, "ApeWisdom scan failed.")


async def _handle_alert_history(ticker: str, channel_id: str, message_id: str) -> None:
    """Show alert history with price outcomes for a ticker."""
    try:
        from consensus_engine import db
        from datetime import datetime
        conn = await db.get_db()
        cursor = await conn.execute(
            """SELECT ticker, confidence_score, catalyst_type, price_at_alert,
                      price_1h_later, price_24h_later, alerted_at
               FROM alert_history
               WHERE ticker = ?
               ORDER BY alerted_at DESC
               LIMIT 10""",
            (ticker,)
        )
        rows = await cursor.fetchall()
        if not rows:
            await send_command_reply(channel_id, message_id, f"No alert history for `${ticker}`.")
            return
        lines = [f"**Alert History — ${ticker}** (last {len(rows)})"]
        for r in rows:
            dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
            score = int(r["confidence_score"])
            entry = f"${r['price_at_alert']:.2f}" if r["price_at_alert"] else "n/a"
            pnl_1h = ""
            pnl_24h = ""
            if r["price_at_alert"] and r["price_1h_later"]:
                pct = (r["price_1h_later"] - r["price_at_alert"]) / r["price_at_alert"] * 100
                pnl_1h = f" | 1h: {pct:+.1f}%"
            if r["price_at_alert"] and r["price_24h_later"]:
                pct = (r["price_24h_later"] - r["price_at_alert"]) / r["price_at_alert"] * 100
                pnl_24h = f" | 24h: {pct:+.1f}%"
            catalyst = f" [{r['catalyst_type']}]" if r["catalyst_type"] else ""
            lines.append(f"`{dt}` score={score}{catalyst} entry={entry}{pnl_1h}{pnl_24h}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Alert-history command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Alert history unavailable for `${ticker}`.")


async def _handle_nitter_health(channel_id: str, message_id: str) -> None:
    """Check if Nitter service is responding."""
    try:
        import aiohttp
        from consensus_engine import config as cfg
        nitter_url = cfg.get("nitter.url", "http://localhost:8585")
        async with aiohttp.ClientSession() as session:
            async with session.get(nitter_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    await send_command_reply(channel_id, message_id, f"Nitter: **online** ({nitter_url})")
                else:
                    await send_command_reply(channel_id, message_id, f"Nitter: **degraded** — HTTP {resp.status} ({nitter_url})")
    except Exception:
        from consensus_engine import config as cfg
        nitter_url = cfg.get("nitter.url", "http://localhost:8585")
        await send_command_reply(channel_id, message_id, f"Nitter: **offline** — not responding ({nitter_url})")


async def _handle_gaps(channel_id: str, message_id: str) -> None:
    """Run pre-market gap scan on demand."""
    await send_command_reply(channel_id, message_id, "Scanning pre-market gaps...")
    asyncio.create_task(_gaps_and_reply(channel_id, message_id))


async def _gaps_and_reply(channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.premarket import scan_premarket_gaps, format_gap_digest
        gaps = await scan_premarket_gaps()
        msg = format_gap_digest(gaps)
        await send_command_reply(channel_id, message_id, msg)
    except Exception as e:
        log.error("Gaps command error: %s", e)
        await send_command_reply(channel_id, message_id, "Gap scan failed.")


async def _handle_leaderboard(channel_id: str, message_id: str) -> None:
    """Show analyst performance leaderboard."""
    try:
        from consensus_engine import db
        stats = await db.get_analyst_performance_stats()
        if not stats:
            await send_command_reply(channel_id, message_id, "No analyst performance data yet.")
            return
        lines = ["**Analyst Leaderboard**"]
        for i, s in enumerate(stats[:15], 1):
            sign = "+" if s["avg_pnl_1h"] >= 0 else ""
            lines.append(
                f"**{i}.** `@{s['analyst']}` -- "
                f"{s['total_alerts']} alerts | "
                f"1h: {s['win_rate_1h']:.0f}% ({sign}{s['avg_pnl_1h']:.1f}%) | "
                f"24h: {s['win_rate_24h']:.0f}%"
            )
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Leaderboard command error: %s", e)
        await send_command_reply(channel_id, message_id, "Leaderboard unavailable.")


async def _handle_source_health(channel_id: str, message_id: str) -> None:
    """Show source health status table with freshness and error rate."""
    try:
        from consensus_engine import db, config as cfg
        import time

        rows = await db.get_all_source_health()
        if not rows:
            await send_command_reply(
                channel_id, message_id,
                "No source health data yet — engine must run at least one cycle first.",
            )
            return

        critical = set(cfg.get("source_health.critical_sources", ["finnhub", "yfinance", "nitter"]))
        source_max_age = cfg.get("source_health.source_max_age", {})
        degraded_mult = cfg.get("source_health.degraded_freshness_multiplier", 5)
        max_error_rate = cfg.get("source_health.max_error_rate", 0.3)

        lines = ["**Source Health**", "```"]
        lines.append(f"{'Source':<24} {'Status':<9} {'Freshness':>12} {'Err%':>5}")
        lines.append("-" * 54)

        for r in rows:
            src = r["source_id"]
            freshness = r["freshness_seconds"]
            err_rate = r["error_rate"]
            max_age = source_max_age.get(src, 300)

            if r["last_heartbeat"] == 0 or freshness > max_age * degraded_mult:
                status = "OFFLINE"
            elif err_rate > max_error_rate or freshness > max_age * 2:
                status = "DEGRADED"
            else:
                status = "OK"

            crit_flag = "*" if src in critical else " "
            fresh_str = f"{int(freshness)}s ago" if freshness < 9990 else "never"
            err_str = f"{err_rate * 100:.0f}%"
            lines.append(f"{crit_flag}{src:<23} {status:<9} {fresh_str:>12} {err_str:>5}")

        lines.append("```")
        lines.append("_* = critical source_")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Source-health command error: %s", e)
        await send_command_reply(channel_id, message_id, "Source health unavailable.")


async def _handle_transcript(youtube_url: str, channel_id: str, message_id: str) -> None:
    """Fetch YouTube video transcript."""
    await send_command_reply(channel_id, message_id, f"Fetching transcript for {youtube_url}...")
    asyncio.create_task(_transcript_and_reply(youtube_url, channel_id, message_id))


async def _transcript_and_reply(youtube_url: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.utils.transcript_fetch import (
            parse_video_id,
            fetch_transcript_cascade,
        )

        video_id = parse_video_id(youtube_url)
        if not video_id:
            await send_command_reply(
                channel_id, message_id,
                "Could not parse video ID. Use a standard YouTube URL "
                "(watch, shorts, or youtu.be).",
            )
            return

        text, lang, is_auto = await fetch_transcript_cascade(video_id, ["en"])

        caption_type = "auto-generated" if is_auto else "manual"
        header = f"**Transcript** ({lang}, {caption_type}, {len(text)} chars)"
        preview = text[:1500] + "..." if len(text) > 1500 else text
        await send_command_reply(channel_id, message_id, f"{header}\n{preview}")
    except Exception as e:
        log.error("Transcript command error for %s: %s", youtube_url, e)
        await send_command_reply(channel_id, message_id, f"Transcript failed: {e}")
