"""Stage 5 — Discord Alert Delivery.

Formats rich embeds and sends them via the Discord bot API.
"""

import json
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import AlertPayload, ConsensusResult

log = logging.getLogger("consensus_engine.alerts.discord")


def _format_embed(payload: AlertPayload) -> dict:
    """Build a Discord embed from an AlertPayload."""
    consensus = payload.consensus
    gates = consensus.gate_summary()
    all_passed = consensus.all_gates_passed

    # Color: green for bullish, red for bearish, orange for neutral
    if payload.confidence_score >= 80:
        color = cfg.get("alerts.embed_color_bullish", 0x00FF00)
    elif payload.confidence_score >= 70:
        color = cfg.get("alerts.embed_color_neutral", 0xFFAA00)
    else:
        color = cfg.get("alerts.embed_color_bearish", 0xFF0000)

    # Technical snapshot
    tech_lines = []
    if payload.technical and payload.technical.filters:
        for f in payload.technical.filters:
            icon = "\u2705" if f.passed else "\u274c"
            tech_lines.append(f"{icon} {f.name}: {f.value} ({f.threshold})")

    tech_text = "\n".join(tech_lines) if tech_lines else "No technical data"

    # Analyst mentions
    analyst_text = ", ".join(f"@{a}" for a in payload.analyst_mentions[:10])
    if not analyst_text:
        analyst_text = "None detected"
    analyst_header = f"{len(payload.analyst_mentions)} analysts in {payload.analyst_window_minutes:.0f} min"

    # Consensus breakdown
    gate_icons = {True: "\u2705", False: "\u274c"}
    consensus_lines = [
        f"{gate_icons[gates.get('twitter', False)]} X/Twitter: {len(payload.analyst_mentions)} analysts",
        f"{gate_icons[gates.get('social', False)]} Social: {'confirmed' if gates.get('social') else 'unconfirmed'}",
        f"{gate_icons[gates.get('catalyst', False)]} News Catalyst: {payload.catalyst_type or 'none'}",
        f"{gate_icons[gates.get('technical', False)]} Technical: {payload.technical.passed_count}/{payload.technical.total_count} filters" if payload.technical else f"{gate_icons[False]} Technical: no data",
        f"{gate_icons[gates.get('llm_confidence', False)]} LLM Score: {payload.confidence_score:.0f}/100",
    ]
    consensus_text = "\n".join(consensus_lines)

    # Source links (suppress embeds with angle brackets)
    source_links = []
    for url in payload.news_urls[:3]:
        source_links.append(f"<{url}>")
    sources_text = "\n".join(source_links) if source_links else "No source links"

    embed = {
        "title": f"\U0001f6a8 BREAKOUT ALERT: ${payload.ticker}",
        "color": color,
        "fields": [
            {
                "name": "\U0001f4b0 Confidence Score",
                "value": f"**{payload.confidence_score:.0f}/100**",
                "inline": True,
            },
            {
                "name": "\U0001f4b5 Price",
                "value": f"${payload.price:.2f} ({payload.technical.price_change_pct:+.1f}%)" if payload.technical else "N/A",
                "inline": True,
            },
            {
                "name": "\U0001f4f0 Catalyst",
                "value": f"**{payload.catalyst_type}**\n{payload.catalyst_summary[:200]}",
                "inline": False,
            },
            {
                "name": f"\U0001f426 Analyst Mentions ({analyst_header})",
                "value": analyst_text,
                "inline": False,
            },
            {
                "name": "\U0001f4ca Technical Snapshot",
                "value": tech_text,
                "inline": False,
            },
            {
                "name": "\u2705 Consensus Breakdown",
                "value": consensus_text,
                "inline": False,
            },
            {
                "name": "\U0001f517 Sources",
                "value": sources_text,
                "inline": False,
            },
        ],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {
            "text": "Stock Trend Consensus Engine",
        },
    }

    return embed


async def send_alert(payload: AlertPayload) -> bool:
    """Send a rich embed alert to Discord.

    Uses the bot token + channel ID from config.
    Returns True on success.
    """
    # Dry-run mode: log the alert but don't send to Discord
    if cfg.dry_run:
        log.info("[DRY-RUN] Would send Discord alert for $%s (confidence=%.0f)",
                 payload.ticker, payload.confidence_score)
        _log_alert_fallback(payload)
        # Still record in alert history so status reporting works
        await db.insert_alert(
            ticker=payload.ticker,
            confidence=payload.confidence_score,
            catalyst=payload.catalyst_summary,
            catalyst_type=payload.catalyst_type,
            consensus_json=json.dumps(payload.consensus.gate_summary()),
            technical_json=json.dumps([
                {"name": f.name, "value": f.value, "passed": f.passed}
                for f in payload.technical.filters
            ] if payload.technical else []),
            analysts_json=json.dumps(payload.analyst_mentions),
            price=payload.price,
        )
        return True

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))

    if not token or not channel_id:
        log.warning("Discord not configured (token=%s, channel=%s)",
                     bool(token), bool(channel_id))
        _log_alert_fallback(payload)
        return False

    # Validate channel_id is numeric to prevent URL injection
    if not channel_id.isdigit():
        log.error("Invalid Discord channel_id (must be numeric): %s", channel_id[:20])
        _log_alert_fallback(payload)
        return False

    embed = _format_embed(payload)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            }
            body = {
                "embeds": [embed],
            }

            async with session.post(url, headers=headers, json=body,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201, 204):
                    log.info("Discord alert sent for %s (confidence=%.0f)",
                             payload.ticker, payload.confidence_score)

                    # Record in alert history
                    await db.insert_alert(
                        ticker=payload.ticker,
                        confidence=payload.confidence_score,
                        catalyst=payload.catalyst_summary,
                        catalyst_type=payload.catalyst_type,
                        consensus_json=json.dumps(payload.consensus.gate_summary()),
                        technical_json=json.dumps([
                            {"name": f.name, "value": f.value, "passed": f.passed}
                            for f in payload.technical.filters
                        ] if payload.technical else []),
                        analysts_json=json.dumps(payload.analyst_mentions),
                        price=payload.price,
                    )
                    return True
                else:
                    error = await resp.text()
                    log.warning("Discord API error (%d): %s", resp.status, error[:200])
                    return False

    except Exception as e:
        log.error("Failed to send Discord alert: %s", e)
        return False


def _log_alert_fallback(payload: AlertPayload):
    """Log alert details to console when Discord is not configured."""
    log.info("=" * 60)
    log.info("BREAKOUT ALERT: $%s (Confidence: %.0f/100)", payload.ticker, payload.confidence_score)
    log.info("Catalyst: %s — %s", payload.catalyst_type, payload.catalyst_summary[:100])
    log.info("Analysts: %s", ", ".join(payload.analyst_mentions[:5]))
    if payload.technical:
        for f in payload.technical.filters:
            status = "PASS" if f.passed else "FAIL"
            log.info("  [%s] %s: %s (%s)", status, f.name, f.value, f.threshold)
    log.info("Gates: %s", payload.consensus.gate_summary())
    log.info("=" * 60)
