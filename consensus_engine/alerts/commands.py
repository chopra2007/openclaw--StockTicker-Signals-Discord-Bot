"""Discord command routing.

Handles !-prefixed commands received via the Discord Gateway.
Commands:
  !help          — list available commands
  !status        — engine status summary
  !trend         — last Reddit trend digest on demand
  !scan <TICKER> — run cross-reference on a ticker and reply with score
"""

import logging
from typing import Optional

from consensus_engine.alerts.discord import send_command_reply

log = logging.getLogger("consensus_engine.alerts.commands")

HELP_TEXT = """**OpenClaw Signal Engine — Commands**
`!help` — show this message
`!status` — engine health summary (active signals, last alert)
`!trend` — post latest Reddit trend digest
`!scan <TICKER>` — run cross-reference on a ticker (e.g. `!scan NVDA`)"""


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

    elif command == "scan":
        if not args:
            await send_command_reply(
                channel_id, message_id,
                "Usage: `!scan <TICKER>` — e.g. `!scan NVDA`"
            )
        else:
            await _handle_scan(args[0].upper(), channel_id, message_id)

    else:
        await send_command_reply(
            channel_id, message_id,
            f"Unknown command `!{command}`. Try `!help`."
        )


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

        lines = [f"**Engine Status**", f"Active signals: {active_signals}"]
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
        from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
        from consensus_engine.alerts.discord import send_trend_digest
        trending = await crawl_and_get_trending()
        if trending:
            await send_trend_digest(trending)
        else:
            await send_command_reply(channel_id, message_id, "No trending tickers found right now.")
    except Exception as e:
        log.error("Trend command error: %s", e)
        await send_command_reply(channel_id, message_id, "Trend scan failed.")


async def _handle_scan(ticker: str, channel_id: str, message_id: str) -> None:
    """Run cross-reference on a ticker and reply with results."""
    try:
        await send_command_reply(channel_id, message_id, f"Scanning `${ticker}`...")
        from consensus_engine.cross_reference import cross_reference
        from consensus_engine.models import (
            ParsedTweet, TweetType, Direction, Conviction, OptionsDetail
        )
        # Build a minimal ParsedTweet so cross_reference() has what it needs
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
        xref = await cross_reference(ticker, fake_tweet)
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

        score_str = " + ".join(parts) + f" = **{xref.final_score}**"
        summary_lines = [f"**${ticker} Scan — Score: {xref.final_score}**", score_str]
        if xref.catalyst_summary:
            summary_lines.append(f"News: {xref.catalyst_summary[:200]}")
        if xref.social_summary:
            summary_lines.append(f"Social: {xref.social_summary}")

        await send_command_reply(channel_id, message_id, "\n".join(summary_lines))
    except Exception as e:
        log.error("Scan command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Scan failed for `${ticker}`.")
