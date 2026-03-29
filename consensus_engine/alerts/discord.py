"""Two-Phase Discord Alert Delivery.

Phase 1: Instant ping — analyst name, ticker, direction, options, price
Phase 2: Detail follow-up — replies to ping with cross-reference results
"""

import json
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    Direction, TweetType,
)

log = logging.getLogger("consensus_engine.alerts.discord")


def format_instant_ping(tweet: ParsedTweet, current_price: float = 0.0) -> dict:
    """Build Discord embed for the instant ping (Phase 1)."""
    direction_str = tweet.direction.value.upper()
    ticker = tweet.tickers[0] if tweet.tickers else "???"

    color_map = {
        Direction.LONG: cfg.get("alerts.embed_color_long", 0x00FF00),
        Direction.SHORT: cfg.get("alerts.embed_color_short", 0xFF0000),
        Direction.NEUTRAL: cfg.get("alerts.embed_color_neutral", 0xFFAA00),
    }
    color = color_map.get(tweet.direction, 0xFFAA00)

    fields = []

    if current_price > 0:
        fields.append({
            "name": "Current Price",
            "value": f"${current_price:.2f}",
            "inline": True,
        })

    if tweet.options and tweet.options.present:
        opt = tweet.options
        parts = []
        if opt.option_type:
            parts.append(opt.option_type.capitalize())
        if opt.strike:
            parts.append(f"${opt.strike:.0f} strike")
        if opt.expiry:
            parts.append(f"{opt.expiry} expiry")
        if opt.target_price:
            parts.append(f"Target: ${opt.target_price:.0f}")
        if opt.profit_target_pct:
            parts.append(f"{opt.profit_target_pct:.0f}% profit target")

        if parts:
            fields.append({
                "name": "Options",
                "value": " | ".join(parts),
                "inline": False,
            })

    fields.append({
        "name": "Score",
        "value": f"{tweet.base_score} (cross-references pending...)",
        "inline": True,
    })

    author_block = {
        "name": tweet.display_name or f"@{tweet.analyst}",
        "url": f"https://twitter.com/{tweet.analyst}",
    }
    if tweet.avatar_url:
        author_block["icon_url"] = tweet.avatar_url

    embed = {
        "author": author_block,
        "title": f"${ticker} {direction_str}",
        "url": tweet.tweet_url,
        "description": tweet.raw_text[:300],
        "color": color,
        "fields": fields,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine"},
    }

    if tweet.image_url:
        embed["image"] = {"url": tweet.image_url}

    return embed


def format_detail_followup(xref: CrossReferenceResult) -> dict:
    """Build Discord embed for the detail follow-up (Phase 2)."""
    b = xref.breakdown
    total = b.total

    fields = []

    if xref.catalyst_summary:
        catalyst_text = f"**{xref.catalyst_type}**\n{xref.catalyst_summary[:200]}"
        if xref.catalyst_sources:
            catalyst_text += f"\nSources: {', '.join(xref.catalyst_sources[:3])}"
        fields.append({"name": "News Catalyst", "value": catalyst_text, "inline": False})

    if xref.sec_summary:
        fields.append({"name": "SEC Filings", "value": xref.sec_summary, "inline": False})

    if xref.technical and xref.technical.filters:
        tech_lines = []
        for f in xref.technical.filters:
            icon = "\u2705" if f.passed else "\u274c"
            tech_lines.append(f"{icon} {f.name}: {f.value} ({f.threshold})")
        fields.append({"name": "Technical Snapshot", "value": "\n".join(tech_lines), "inline": False})

    if xref.social_summary:
        fields.append({"name": "Social", "value": xref.social_summary, "inline": False})

    if xref.options and xref.options.has_unusual_activity:
        opt = xref.options
        parts_o = []
        if opt.unusual_calls:
            parts_o.append(f"Unusual CALLS (max ratio {opt.max_call_ratio:.1f}x)")
        if opt.unusual_puts:
            parts_o.append(f"Unusual PUTS (max ratio {opt.max_put_ratio:.1f}x)")
        parts_o.append(f"P/C ratio: {opt.put_call_ratio:.2f}")
        fields.append({"name": "Options Flow", "value": "\n".join(parts_o), "inline": False})

    if xref.other_analysts:
        analyst_text = ", ".join(f"@{a}" for a in xref.other_analysts[:10])
        analyst_text += f" (+{b.additional_analysts} pts)"
        fields.append({"name": "Other Analysts", "value": analyst_text, "inline": False})

    if xref.llm_reasoning:
        fields.append({"name": "LLM Analysis", "value": f"+{b.llm_boost} pts — {xref.llm_reasoning[:150]}", "inline": False})

    parts = []
    if b.base: parts.append(f"base({b.base})")
    if b.additional_analysts: parts.append(f"analysts({b.additional_analysts})")
    if b.news_catalyst: parts.append(f"news({b.news_catalyst})")
    if b.sec_filing: parts.append(f"sec({b.sec_filing})")
    if b.social_apewisdom: parts.append(f"ape({b.social_apewisdom})")
    if b.social_stocktwits: parts.append(f"st({b.social_stocktwits})")
    if b.social_reddit: parts.append(f"reddit({b.social_reddit})")
    if b.google_trends: parts.append(f"trends({b.google_trends})")
    if b.technical: parts.append(f"tech({b.technical})")
    if b.llm_boost: parts.append(f"llm({b.llm_boost})")
    if b.options_flow: parts.append(f"options({b.options_flow})")
    breakdown_text = " + ".join(parts) + f" = {total}"
    fields.append({"name": "Breakdown", "value": breakdown_text, "inline": False})

    if not xref.catalyst_summary and not xref.other_analysts and not xref.social_summary:
        fields.insert(0, {"name": "Status", "value": "No additional signals found", "inline": False})

    embed = {
        "title": f"Cross-Reference: ${xref.ticker} | Score: {total}",
        "color": 0x5865F2,
        "fields": fields,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine"},
    }

    return embed


async def send_instant_ping(tweet: ParsedTweet, current_price: float = 0.0) -> Optional[str]:
    """Send the instant ping to Discord. Returns the message ID or None."""
    if cfg.dry_run:
        ticker = tweet.tickers[0] if tweet.tickers else "???"
        log.info("[DRY-RUN] Instant ping: @%s $%s %s (score=%d)",
                 tweet.analyst, ticker, tweet.direction.value, tweet.base_score)
        return "dry_run_msg_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for instant ping")
        return None

    embed = format_instant_ping(tweet, current_price)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            body = {"embeds": [embed]}

            async with session.post(url, headers=headers, json=body,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    msg_id = data.get("id")
                    log.info("Instant ping sent for $%s by @%s (msg_id=%s)",
                             tweet.tickers[0] if tweet.tickers else "???",
                             tweet.analyst, msg_id)
                    return msg_id
                else:
                    error = await resp.text()
                    log.warning("Discord ping error (%d): %s", resp.status, error[:200])
                    return None
    except Exception as e:
        log.error("Failed to send instant ping: %s", e)
        return None


async def send_trend_digest(trending: list[dict]) -> Optional[str]:
    """Post a Reddit trend digest to the main Discord channel. Returns message ID."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Trend digest: %d tickers", len(trending))
        return "dry_run_digest_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for trend digest")
        return None

    if not trending:
        return None

    lines = []
    for i, t in enumerate(trending[:15], 1):
        momentum_str = f"{t['momentum']:.1f}x" if t.get("momentum", 1.0) > 1.0 else "—"
        lines.append(
            f"**{i}.** `${t['ticker']}` — {t['mentions']} mentions | "
            f"{t['unique_authors']} authors | momentum {momentum_str}"
        )

    embed = {
        "title": "Reddit Trend Digest",
        "description": "\n".join(lines),
        "color": 0x7289DA,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine — last 24h"},
    }

    async with aiohttp.ClientSession() as session:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {"embeds": [embed]}
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                log.warning("Trend digest send failed: %d", resp.status)
                return None
            data = await resp.json()
            return data.get("id")


async def send_command_reply(channel_id: str, reply_to_msg_id: str, content: str) -> Optional[str]:
    """Send a plain-text reply to a Discord command message."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Command reply to %s: %s", reply_to_msg_id, content[:80])
        return "dry_run_reply_id"

    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None

    async with aiohttp.ClientSession() as session:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {
            "content": content[:2000],
            "message_reference": {"message_id": reply_to_msg_id},
        }
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                log.warning("Command reply failed: %d", resp.status)
                return None
            data = await resp.json()
            return data.get("id")


async def send_detail_followup(xref: CrossReferenceResult, reply_to_msg_id: str) -> Optional[str]:
    """Send the detail follow-up as a reply to the instant ping. Returns message ID."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Detail follow-up: $%s score=%d", xref.ticker, xref.final_score)
        return "dry_run_followup_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        return None

    embed = format_detail_followup(xref)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            body = {
                "embeds": [embed],
                "message_reference": {"message_id": reply_to_msg_id},
            }

            async with session.post(url, headers=headers, json=body,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    msg_id = data.get("id")
                    log.info("Detail follow-up sent for $%s (score=%d, msg_id=%s)",
                             xref.ticker, xref.final_score, msg_id)
                    return msg_id
                else:
                    error = await resp.text()
                    log.warning("Discord follow-up error (%d): %s", resp.status, error[:200])
                    return None
    except Exception as e:
        log.error("Failed to send detail follow-up: %s", e)
        return None
