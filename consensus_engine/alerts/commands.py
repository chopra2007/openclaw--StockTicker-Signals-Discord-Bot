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
  !google-trends <T>  — Google Trends spike % for a ticker
  !apewisdom          — ApeWisdom trending tickers
  !alert-history <T>  — alert history with price outcomes for a ticker
  !market-view <T>    — current verdict from latest decision snapshot
  !levels <T>         — price levels (support/resistance) from YouTube + signals
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from consensus_engine import config as cfg, db
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
`!leaderboard` — analyst win rate rankings

**Engine Health**
`!source-health` — data source status table (freshness, error rate)

**Reliability & Levels**
`!market-view <TICKER>` — current verdict from latest decision snapshot (e.g. `!market-view NVDA`)
`!levels <TICKER>` — price levels with condition text from YouTube + signals

**YouTube Intelligence**
`!yt <URL>` — on-demand analysis of a YouTube video (tickers, conviction, macro, levels)
`!yt-mentions <TICKER>` — YouTube signals for a ticker (last 7 days)
`!macro` — macro digest across all channels (last 7 days)
`!yt-follow <@handle or URL>` — add a YouTube channel to the follow list (e.g. `!yt-follow @FiguringOutMoney`)"""


def parse_command(content: str) -> Optional[tuple[str, list[str]]]:
    """Parse a Discord message into (command, args) if it starts with !.

    Returns None if the message is not a command.
    Handles messages that begin with a bot mention: <@123> !command args
    """
    content = content.strip()
    # Strip leading Discord mention so "@bot !options TSLA" works
    content = re.sub(r'^<@!?[0-9]+>\s*', '', content)
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
    author_id: str | None = None,
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

    elif command == "leaderboard":
        await _handle_leaderboard(channel_id, message_id)

    elif command in ("source-health", "source_health"):
        await _handle_source_health(channel_id, message_id)

    elif command == "transcript":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!transcript <YOUTUBE_URL>` — e.g. `!transcript https://www.youtube.com/watch?v=xxxxx`")
        else:
            await _handle_transcript(args[0], channel_id, message_id)

    elif command in ("market-view", "market_view", "marketview"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!market-view <TICKER>` — e.g. `!market-view NVDA`")
        else:
            await _handle_market_view(args[0].upper(), channel_id, message_id)

    elif command == "levels":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!levels <TICKER>` — e.g. `!levels NVDA`")
        else:
            await _handle_levels(args[0].upper(), channel_id, message_id)

    elif command == "yt":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!yt <URL>` — e.g. `!yt https://youtu.be/xxxxx`")
        else:
            await _handle_yt(args[0], channel_id, message_id, author_id=author_id)

    elif command in ("yt-mentions", "yt_mentions"):
        raw = args[0].lstrip("$").upper() if args else ""
        if not raw:
            await send_command_reply(channel_id, message_id, "Usage: `!yt-mentions $TICKER` — e.g. `!yt-mentions $NVDA`")
        else:
            await _handle_yt_mentions(raw, channel_id, message_id)

    elif command == "macro":
        await _handle_macro(channel_id, message_id)

    elif command in ("yt-follow", "yt_follow"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!yt-follow @handle` or `!yt-follow https://youtube.com/@handle`")
        else:
            await _handle_yt_follow(args[0], channel_id, message_id)

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


def _fmt_insider_name(raw: str) -> str:
    """Convert SEC 'LAST FIRST' format to 'First Last' for display."""
    parts = raw.strip().split()
    if len(parts) >= 2:
        return " ".join(reversed(parts))
    return raw.title()


def _fmt_security(raw: str) -> str:
    s = raw.strip()
    if "restricted stock unit" in s.lower():
        return "RSUs"
    if "common stock" in s.lower():
        return "Common Stock"
    return s


async def _sec_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.sec_edgar import (
            check_recent_filings, classify_filing_significance, fetch_form4_details
        )
        filings = await check_recent_filings(ticker, hours_back=72)
        if not filings:
            await send_command_reply(channel_id, message_id, f"No SEC filings in the last 72h for `${ticker}`.")
            return

        lines = [f"**SEC Filings — ${ticker}** (last 72h)"]

        for f in filings[:8]:
            form = f.get("form", "?")
            filed = f.get("filing_date", "?")

            if form == "4":
                txs = await fetch_form4_details(
                    f.get("cik", ""),
                    f.get("accession_number", ""),
                    f.get("primary_document", ""),
                )
                # Group transactions by insider
                grouped: dict[str, list] = {}
                meta: dict[str, str] = {}
                for tx in txs:
                    key = tx["reporter_name"]
                    grouped.setdefault(key, []).append(tx)
                    meta[key] = tx["title"]

                try:
                    date_fmt = datetime.strptime(filed, "%Y-%m-%d").strftime("%b %-d")
                except ValueError:
                    date_fmt = filed

                lines.append(f"\n📋 **Form 4 · {date_fmt}** — Insider Transactions")
                for raw_name, insider_txs in grouped.items():
                    display_name = _fmt_insider_name(raw_name)
                    title = meta[raw_name]
                    lines.append(f"👤 **{display_name}** · {title}")
                    for tx in insider_txs:
                        direction = tx["direction"]
                        shares = tx["shares"]
                        price = tx["price"]
                        tx_type = tx["transaction_type"]
                        security = _fmt_security(tx["security"])
                        icon = "🟢" if direction == "Buy" else "🔴" if direction == "Sell" else "⚪"
                        prefix = "+" if direction == "Buy" else "−" if direction == "Sell" else ""
                        shares_fmt = f"{shares:,.0f}"
                        price_str = f" @ **${price:.2f}**" if price else ""
                        lines.append(f"  {icon} {prefix}{shares_fmt} {security}{price_str}  _{tx_type}_")
            else:
                lines.append(f"\n📄 **{form}** · {filed}")

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
    """Run SerpAPI Google Trends for trending tickers from ApeWisdom (cron job)."""
    await send_command_reply(channel_id, message_id, "Running SerpAPI Google Trends...")
    try:
        from consensus_engine import db
        from consensus_engine.scanners.social import scan_google_trends_serpapi, scan_apewisdom
        from consensus_engine.models import TickerSignal, SourceType, Sentiment
        
        # Get trending tickers from ApeWisdom (retail sentiment) instead of database
        ape_signals = await scan_apewisdom()
        if not ape_signals:
            await send_command_reply(channel_id, message_id, "No ApeWisdom data - cannot determine trending tickers.")
            return
        
        # Extract top tickers by mentions
        active = [s.ticker for s in ape_signals[:20]]  # Top 20 from ApeWisdom
        if not active:
            await send_command_reply(channel_id, message_id, "No trending tickers from ApeWisdom.")
            return
        
        # Run SerpAPI on ApeWisdom tickers
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

        critical = set(cfg.get("source_health.critical_sources", ["finnhub", "yfinance"]))
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


# ---------------------------------------------------------------------------
# Reliability commands
# ---------------------------------------------------------------------------

async def _handle_market_view(ticker: str, channel_id: str, message_id: str) -> None:
    """Show current verdict from the latest decision snapshot for a ticker."""
    try:
        from consensus_engine.analysis.calibration import calibrate

        snapshots = await db.get_recent_decision_snapshots(ticker, limit=1)
        if not snapshots:
            await send_command_reply(
                channel_id, message_id,
                f"No decision snapshots for `${ticker}` yet — run `!scan {ticker}` first.",
            )
            return

        s = snapshots[0]
        decision = s.get("decision", "UNKNOWN")
        score = s.get("final_score", 0.0)
        contradiction = s.get("contradiction_index", 0.0)
        recorded_at = s.get("recorded_at", 0.0)

        import time
        age_min = int((time.time() - recorded_at) / 60)

        p_up = calibrate(float(score), "1h")
        p_down = round(1.0 - p_up, 3)

        _ICONS = {
            "ALERT": "🟢", "WATCHLIST": "🟡", "IGNORE": "🔴",
            "UNCERTAIN": "⚠️", "INSUFFICIENT_EVIDENCE": "❓", "DEGRADED_MODE": "🔧",
        }
        icon = _ICONS.get(decision, "⚪")

        lines = [
            f"**Market View — ${ticker}** ({age_min}m ago)",
            f"{icon} **{decision}** | Score: {score:.0f}",
            f"P(up 1h): **{p_up * 100:.1f}%** | P(down): **{p_down * 100:.1f}%**",
            f"Contradiction index: {contradiction:.2f}",
        ]

        # Uncertainty warnings
        if decision in ("UNCERTAIN", "DEGRADED_MODE", "INSUFFICIENT_EVIDENCE"):
            lines.append(f"\n⚠️ State: **{decision}** — treat with caution")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Market-view command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Market view unavailable for `${ticker}`.")


async def _handle_levels(ticker: str, channel_id: str, message_id: str) -> None:
    """Show price levels (support/resistance) from YouTube + signal_events."""
    try:
        levels = await db.get_youtube_levels_for_ticker(ticker, days=14)
        if not levels:
            await send_command_reply(
                channel_id, message_id,
                f"No price levels found for `${ticker}` in the last 14 days.",
            )
            return

        lines = [f"**Price Levels — ${ticker}** ({len(levels)} zones)"]
        for lv in levels[:10]:
            ltype = lv.get("level_type", "level").upper()
            price = lv.get("price", 0.0)
            conf = lv.get("confidence", 0.0)
            condition = lv.get("condition_text") or ""
            consequence = lv.get("consequence_text") or ""
            channel = lv.get("channel_name") or "unknown"

            conf_bar = "★" * round(conf * 5) + "☆" * (5 - round(conf * 5))
            entry = f"`{ltype}` **${price:.2f}** {conf_bar} [{channel}]"
            if condition:
                entry += f"\n  ↳ IF {condition}"
            if consequence:
                entry += f"\n  ↳ THEN {consequence}"
            lines.append(entry)

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Levels command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Levels lookup failed for `${ticker}`.")


# ---------------------------------------------------------------------------
# YouTube intelligence commands
# ---------------------------------------------------------------------------

def _format_ts(sec: int | None) -> str:
    """Render a video timestamp as ``mm:ss`` (or ``h:mm:ss`` when ≥ 1 hour)."""
    if sec is None:
        return ""
    try:
        s = int(sec)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _format_verified(verified: int | None) -> str:
    """Return ``✓`` (confirmed), ``?`` (unverified), or ``⚠`` (contradicted)."""
    if verified == 1:
        return "✓"
    if verified == -1:
        return "⚠"
    return "?"


def _format_youtube_option_summary(opt) -> str:
    """Format a VideoOptionIdea (dataclass or dict) as a short Discord line."""
    def _get(attr, key):
        return getattr(opt, attr, None) if hasattr(opt, attr) else (opt.get(key) if hasattr(opt, "get") else None)

    ticker = _get("ticker", "ticker") or "?"
    opt_type = (_get("option_type", "option_type") or "?").upper()
    strike = _get("strike", "strike")
    expiry = _get("expiry", "expiry")
    source = _get("source", "source") or ""
    ts_sec = _get("video_timestamp_sec", "video_timestamp_sec")

    src_icon = "🔥" if "flow" in source.lower() else "💡"
    strike_str = f"${strike:.0f}" if strike is not None else ""
    expiry_str = f" exp {expiry}" if expiry else ""
    ts_str = f" @ {_format_ts(ts_sec)}" if ts_sec is not None else ""
    return f"  {src_icon} `{ticker}` {opt_type} {strike_str}{expiry_str}{ts_str}".rstrip()


def _format_youtube_setup_summary(setup) -> str:
    """Format a VideoTradeSetup (dataclass or dict) as a short Discord line."""
    def _get(attr, key):
        return getattr(setup, attr, None) if hasattr(setup, attr) else (setup.get(key) if hasattr(setup, "get") else None)

    ticker = _get("ticker", "ticker") or "?"
    entry_low = _get("entry_low", "entry_low")
    entry_high = _get("entry_high", "entry_high")
    # dataclass uses 'stop'; DB dict uses 'stop_price'
    stop = _get("stop", "stop") if _get("stop", "stop") is not None else _get("stop_price", "stop_price")
    targets_raw = _get("targets", "targets")
    targets_json = _get("targets_json", "targets_json")
    risk_reward = _get("risk_reward", "risk_reward")
    ts_sec = _get("video_timestamp_sec", "video_timestamp_sec")
    catalyst_date = _get("catalyst_date", "catalyst_date")
    catalyst_desc = _get("catalyst_desc", "catalyst_desc")

    # Resolve targets to a list
    targets: list = []
    if isinstance(targets_raw, list):
        targets = targets_raw
    elif isinstance(targets_json, str):
        import json as _json
        try:
            targets = _json.loads(targets_json)
        except Exception:
            targets = []

    entry_str = f"${entry_low:.0f}–${entry_high:.0f}" if entry_low is not None and entry_high is not None else (f"${entry_low:.0f}" if entry_low is not None else "?")
    stop_str = f"${stop:.0f}" if stop is not None else "?"
    target_str = f"${targets[0]:.0f}" if targets else "?"
    rr_str = f" (R/R {risk_reward:.1f}x)" if risk_reward is not None else ""
    ts_str = f" @ {_format_ts(ts_sec)}" if ts_sec is not None else ""
    catalyst_str = ""
    if catalyst_date:
        desc = f" {catalyst_desc}" if catalyst_desc else ""
        catalyst_str = f" | Catalyst {catalyst_date}{desc}"
    return f"  📐 `{ticker}` Entry {entry_str}{ts_str} | Stop {stop_str} | Target {target_str}{rr_str}{catalyst_str}"


async def _handle_yt(
    youtube_url: str,
    channel_id: str,
    message_id: str,
    author_id: str | None = None,
) -> None:
    """On-demand full analysis of a YouTube video."""
    if author_id:
        limit = int(cfg.get("youtube.user_rate_limit_per_hour", 5) or 5)
        if await db.check_user_rate_limit(author_id, "yt", limit=limit, window_sec=3600):
            await send_command_reply(
                channel_id, message_id,
                f"Rate limit: {limit} `!yt` per hour per user. Try again later.",
            )
            return
        await db.log_user_command(author_id, "yt")
    await send_command_reply(channel_id, message_id, f"Analysing {youtube_url} ...")
    asyncio.create_task(_yt_analyse_and_reply(youtube_url, channel_id, message_id))


def _format_two_stage_reply(
    title: str,
    channel_name: str,
    bundle,
    result,
    catalysts,
    min_confidence: float,
    require_verified: bool,
) -> str:
    """Render the v2 two-stage `!yt` reply: outline + macro + catalysts + candidates."""
    lines = [f"🎬 **{title}** — {channel_name}", ""]

    # Timestamped outline
    segments = getattr(bundle, "segments", []) or []
    if segments:
        lines.append("**Timestamped outline:**")
        for seg in segments[:20]:
            ts = _format_ts(seg.get("ts_start_sec"))
            seg_title = (seg.get("title") or "").strip()
            lines.append(f"[{ts}] {seg_title}")
        lines.append("")

    # Macro thesis (narrative)
    macro = getattr(result, "macro_thesis", None)
    if macro is not None:
        dir_label = {
            "long": "🟢 BULLISH", "short": "🔴 BEARISH", "neutral": "⚪ NEUTRAL",
        }.get(getattr(macro.direction, "value", str(macro.direction)), "⚪ NEUTRAL")
        lines.append(f"**Macro thesis:** {dir_label}")
        narrative = getattr(macro, "narrative", "") or macro.summary or ""
        if narrative:
            lines.append(narrative[:500])
        lines.append("")

    # Upcoming catalysts
    visible_catalysts = []
    for cat in catalysts or []:
        if require_verified and cat.verified != 1:
            continue
        if cat.suppressed:
            continue
        visible_catalysts.append(cat)
    if visible_catalysts:
        lines.append("**Upcoming catalysts:**")
        for cat in visible_catalysts[:8]:
            date_str = cat.resolved_date or cat.mentioned_date
            mark = _format_verified(cat.verified)
            lines.append(f"• {cat.ticker} {date_str} {cat.catalyst_type} {mark}")
        lines.append("")

    # Tickers (signals)
    visible_signals = [s for s in (result.signals or []) if not s.suppressed
                       and s.classifier_confidence >= min_confidence]
    if visible_signals:
        lines.append("**Tickers:**")
        for sig in visible_signals[:10]:
            dir_icon = {"long": "🟢", "short": "🔴"}.get(sig.direction.value, "⚪")
            conv = sig.conviction.value.upper()
            lines.append(
                f"{dir_icon} {sig.ticker} {sig.direction.value.upper()} "
                f"({conv}, {sig.classifier_confidence:.2f})"
            )
        lines.append("")

    # Setups
    visible_setups = [s for s in (result.setups or []) if not s.suppressed
                      and s.classifier_confidence >= min_confidence]
    if visible_setups:
        lines.append("**Setups:**")
        for setup in visible_setups[:5]:
            lines.append(_format_youtube_setup_summary(setup).lstrip())
        lines.append("")

    # Levels (separate support / resistance rows)
    visible_levels = [lv for lv in (result.levels or []) if not lv.suppressed
                      and lv.classifier_confidence >= min_confidence]
    support = [lv for lv in visible_levels if lv.level_type == "support"]
    resistance = [lv for lv in visible_levels if lv.level_type == "resistance"]
    targets = [lv for lv in visible_levels if lv.level_type == "target"]
    if support or resistance or targets:
        lines.append("**Levels:**")
        for lv in support[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"SUPPORT {lv.ticker} ${lv.price:g}{ts_str}")
        for lv in resistance[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"RESISTANCE {lv.ticker} ${lv.price:g}{ts_str}")
        for lv in targets[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"TARGET {lv.ticker} ${lv.price:g}{ts_str}")

    return "\n".join(lines).rstrip()


async def _yt_analyse_and_reply(youtube_url: str, channel_id: str, message_id: str) -> None:
    try:
        import time as _time
        import aiohttp as _aiohttp
        from consensus_engine.utils.transcript_fetch import parse_video_id, fetch_transcript_cascade
        from consensus_engine.analysis.video_parser import parse_video_transcript

        video_id = parse_video_id(youtube_url)
        if not video_id:
            await send_command_reply(channel_id, message_id, "Could not parse video ID from URL.")
            return

        # oEmbed for title + channel
        title, channel_name = video_id, "unknown"
        try:
            async with _aiohttp.ClientSession() as sess:
                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                async with sess.get(oembed_url, timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", video_id)
                        channel_name = data.get("author_name", "unknown")
        except Exception:
            pass

        # ── v2 two-stage evidence pipeline (flag-gated) ───────────────────────
        if cfg.get("youtube.use_two_stage", False):
            try:
                from consensus_engine.analysis.gemini_video_parser import extract_evidence_with_gemini
                from consensus_engine.analysis.video_classifier import classify_evidence
                from consensus_engine.analysis.catalyst_resolver import resolve_and_verify_catalysts

                published_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
                bundle, _telemetry = await extract_evidence_with_gemini(
                    video_id, channel_name, published_at,
                )
                if bundle is not None:
                    result = classify_evidence(bundle)
                    catalysts = await resolve_and_verify_catalysts(
                        result.catalyst_candidates, bundle.publish_ts,
                    )
                    min_conf = float(cfg.get("youtube.classifier.min_confidence", 0.5))
                    require_verified = bool(cfg.get("youtube.catalyst.require_verified", False))
                    msg = _format_two_stage_reply(
                        title, channel_name, bundle, result, catalysts,
                        min_conf, require_verified,
                    )
                    await send_command_reply(channel_id, message_id, msg)
                    return
            except Exception as e:
                log.warning("!yt two-stage error for %s, falling back: %s", video_id, e)
                if not cfg.get("youtube.legacy_fallback", True):
                    await send_command_reply(channel_id, message_id, f"Analysis failed: {e}")
                    return

        # Check if already parsed
        already = await db.has_video_been_processed(video_id)
        if not already:
            text, _lang, _is_auto = await fetch_transcript_cascade(video_id, ["en"])
            if not text:
                await send_command_reply(channel_id, message_id, "Could not fetch transcript for this video.")
                return
            parsed = await parse_video_transcript(
                video_id, text, channel_name, _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            )
        else:
            # Pull cached signals from DB
            sigs = await db.get_youtube_signals_for_ticker("", days=30)
            sigs = [s for s in sigs if s.get("video_id") == video_id]
            parsed = None

        lines = [f"🎬 **{title}** — {channel_name}"]
        if parsed is not None:
            tickers = parsed.tickers[:5]
            if tickers:
                lines.append("**Tickers:**")
                for t in tickers:
                    dir_icon = {"long": "🟢", "short": "🔴"}.get(t.get("direction", ""), "⚪")
                    lines.append(f"  {dir_icon} `${t['symbol']}` {t.get('direction','').upper()} [{t.get('conviction','').upper()}]")
            else:
                lines.append("No tickers extracted.")

            macro = parsed.macro_thesis
            dir_label = {"long": "BULLISH", "short": "BEARISH", "neutral": "NEUTRAL"}.get(macro.direction.value, str(macro.direction))
            lines.append(f"**Macro:** {dir_label} — {macro.summary[:120] if macro.summary else 'N/A'}")
            lines.append(f"**Conviction:** {parsed.overall_conviction.value.upper()}")

            lvls = parsed.price_levels[:3]
            if lvls:
                lines.append("**Levels:**")
                for lv in lvls:
                    lines.append(f"  `{lv.level_type.upper()}` ${lv.price:.2f} (conf {lv.confidence:.0%})")

            setups = getattr(parsed, "setups", [])[:3]
            if setups:
                lines.append("**Trade Setups:**")
                for s in setups:
                    lines.append(_format_youtube_setup_summary(s))

            options = getattr(parsed, "options", [])[:3]
            if options:
                lines.append("**Options Ideas:**")
                for o in options:
                    lines.append(_format_youtube_option_summary(o))
        else:
            lines.append("Already processed — use `!yt-mentions $TICKER` to see signals.")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt command error for %s: %s", youtube_url, e)
        await send_command_reply(channel_id, message_id, f"Analysis failed: {e}")


async def _handle_yt_mentions(ticker: str, channel_id: str, message_id: str) -> None:
    """Show YouTube signals for a ticker (last 7 days, top 5 by conviction)."""
    try:
        sigs = await db.get_youtube_signals_for_ticker(ticker, days=7)
        if not sigs:
            await send_command_reply(channel_id, message_id, f"No YouTube mentions of `${ticker}` in the last 7 days.")
            return

        _CONV_ORDER = {"high": 0, "medium": 1, "low": 2}
        sigs.sort(key=lambda s: _CONV_ORDER.get(s.get("conviction", "low"), 2))
        sigs = sigs[:5]

        lines = [f"📹 **YouTube Mentions — ${ticker}** ({len(sigs)} results)"]
        for s in sigs:
            dir_icon = {"long": "🟢", "short": "🔴", "neutral": "⚪"}.get(s.get("direction", ""), "⚪")
            conv = s.get("conviction", "").upper()
            ch = s.get("channel_name") or "unknown"
            lines.append(f"{dir_icon} [{ch}] {s.get('direction','').upper()} [{conv}] — video `{s.get('video_id','')}`")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt-mentions command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Lookup failed for `${ticker}`.")


async def build_macro_digest() -> str:
    """Build the macro digest string from youtube_macro (last 7 days)."""
    rows = await db.get_recent_youtube_macro(days=7)
    if not rows:
        return "📊 Macro Digest: No data in the last 7 days."

    counts: dict[str, int] = {"long": 0, "short": 0, "neutral": 0}
    all_themes: list[str] = []
    for r in rows:
        direction = r.get("direction", "neutral").lower()
        norm = {"bullish": "long", "long": "long", "bearish": "short", "short": "short"}.get(direction, "neutral")
        counts[norm] = counts.get(norm, 0) + 1
        all_themes.extend(r.get("themes") or [])

    # Top 3 themes by frequency
    theme_freq: dict[str, int] = {}
    for t in all_themes:
        theme_freq[t] = theme_freq.get(t, 0) + 1
    top_themes = sorted(theme_freq, key=lambda x: -theme_freq[x])[:3]

    bull = counts.get("long", 0)
    bear = counts.get("short", 0)
    neut = counts.get("neutral", 0)
    themes_str = ", ".join(top_themes) if top_themes else "none"
    return f"📊 Macro Digest: BULLISH ({bull} channels) / BEARISH ({bear}) / NEUTRAL ({neut}) — Top themes: {themes_str}"


async def _handle_macro(channel_id: str, message_id: str) -> None:
    """Post macro digest from youtube_macro (last 7 days)."""
    try:
        digest = await build_macro_digest()
        await send_command_reply(channel_id, message_id, digest)
    except Exception as e:
        log.error("!macro command error: %s", e)
        await send_command_reply(channel_id, message_id, "Macro digest unavailable.")


# ---------------------------------------------------------------------------
# !yt-follow
# ---------------------------------------------------------------------------

async def _handle_yt_follow(handle_or_url: str, channel_id: str, message_id: str) -> None:
    """Resolve a YouTube @handle or channel URL to a channel_id and add it to the follow list."""
    await send_command_reply(channel_id, message_id, f"Looking up `{handle_or_url}`...")
    asyncio.create_task(_yt_follow_and_reply(handle_or_url, channel_id, message_id))


async def _yt_follow_and_reply(handle_or_url: str, channel_id_discord: str, message_id: str) -> None:
    import re
    import json as _json
    from consensus_engine.utils.http import get_session

    # Normalise input → canonical URL
    raw = handle_or_url.strip().lstrip("@")
    if handle_or_url.startswith("@"):
        url = f"https://www.youtube.com/@{raw}"
    elif "youtube.com" in handle_or_url:
        url = handle_or_url if handle_or_url.startswith("http") else f"https://{handle_or_url}"
    else:
        url = f"https://www.youtube.com/@{raw}"

    try:
        session = await get_session()
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True) as resp:
            if resp.status != 200:
                await send_command_reply(channel_id_discord, message_id, f"Could not fetch channel page (HTTP {resp.status}).")
                return
            html = await resp.text()

        # Extract channel_id from page HTML
        m = re.search(r'"channelId"\s*:\s*"(UC[^"]{20,})"', html)
        if not m:
            # Fallback: canonical link
            m = re.search(r'href="https://www\.youtube\.com/channel/(UC[^"]{20,})"', html)
        if not m:
            await send_command_reply(channel_id_discord, message_id, f"Could not find a channel ID for `{handle_or_url}`. Make sure the handle is correct.")
            return

        yt_channel_id = m.group(1)

        # Extract display name
        name_m = re.search(r'"title"\s*:\s*"([^"]+)".*?"channelId"\s*:\s*"' + re.escape(yt_channel_id), html, re.DOTALL)
        if not name_m:
            name_m = re.search(r'<title>([^<]+)\s*-\s*YouTube</title>', html)
        display_name = name_m.group(1).strip() if name_m else yt_channel_id

        # Check if already followed
        existing = await db.get_channel_display_name(yt_channel_id)
        if existing != yt_channel_id:  # found a real name → already in DB
            await send_command_reply(channel_id_discord, message_id, f"Already following **{existing}** (`{yt_channel_id}`).")
            return

        # Insert into DB
        conn = await db.get_db()
        await conn.execute(
            "INSERT OR IGNORE INTO youtube_channels (channel_id, display_name, approved, trust_score) VALUES (?, ?, 1, 1.0)",
            (yt_channel_id, display_name),
        )
        await conn.commit()

        # Persist to sources.json
        sources_path = "/root/.openclaw/sources.json"
        try:
            with open(sources_path) as f:
                sources = _json.load(f)
            channels = sources.setdefault("youtube_channels", [])
            if not any(c.get("channel_id") == yt_channel_id for c in channels):
                channels.append({"channel_id": yt_channel_id, "display_name": display_name})
                with open(sources_path, "w") as f:
                    _json.dump(sources, f, indent=2)
        except Exception as e:
            log.warning("!yt-follow: could not update sources.json: %s", e)

        await send_command_reply(
            channel_id_discord, message_id,
            f"✅ Now following **{display_name}** (`{yt_channel_id}`). New videos will be scanned automatically."
        )

    except Exception as e:
        log.error("!yt-follow error for %s: %s", handle_or_url, e)
        await send_command_reply(channel_id_discord, message_id, f"Error looking up channel: {e}")
