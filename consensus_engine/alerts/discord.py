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


# ---------------------------------------------------------------------------
# Reliability display helpers
# ---------------------------------------------------------------------------

_DECISION_ICONS = {
    "ALERT": "🟢",
    "WATCHLIST": "🟡",
    "IGNORE": "🔴",
    "UNCERTAIN": "⚠️",
    "INSUFFICIENT_EVIDENCE": "❓",
    "DEGRADED_MODE": "🔧",
}

_DECISION_LABELS = {
    "ALERT": "ALERT",
    "WATCHLIST": "WATCHLIST",
    "IGNORE": "NO_TRADE",
    "UNCERTAIN": "UNCERTAIN",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
    "DEGRADED_MODE": "DEGRADED_MODE",
}


def _top_reason_codes(xref: CrossReferenceResult) -> list[str]:
    """Derive top-3 reason codes from score breakdown."""
    b = xref.breakdown
    candidates = []
    if b.news_catalyst > 0:
        candidates.append(("NEWS_CATALYST", b.news_catalyst))
    if b.additional_analysts >= 20:
        candidates.append(("MULTI_ANALYST", b.additional_analysts))
    if b.technical >= 6:
        candidates.append(("STRONG_TECHNICALS", b.technical))
    if (b.social_reddit + b.social_apewisdom) >= 10:
        candidates.append(("SOCIAL_MOMENTUM", b.social_reddit + b.social_apewisdom))
    if b.options_flow > 0:
        candidates.append(("OPTIONS_FLOW", b.options_flow))
    if b.sec_filing > 0:
        candidates.append(("SEC_FILING", b.sec_filing))
    if b.llm_boost > 0:
        candidates.append(("LLM_CONFIDENCE", b.llm_boost))
    candidates.sort(key=lambda x: -x[1])
    return [code for code, _ in candidates[:3]]


def _freshness_label(weights: dict) -> str:
    """Summarise source freshness from reliability weights."""
    if not weights:
        return "UNKNOWN"
    vals = list(weights.values())
    max_w = max(vals)
    avg_w = sum(vals) / len(vals)
    if max_w >= 0.5:
        return "FRESH"
    if avg_w >= 0.2:
        return "MODERATE"
    return "STALE"


def _invalidation_condition(xref: CrossReferenceResult) -> str:
    """One-line condition under which this signal should be discarded."""
    decision = xref.reliability_decision
    if decision == "UNCERTAIN":
        return "Contradicting signals — verify before acting"
    if decision == "DEGRADED_MODE":
        return "Engine in degraded mode — signals may be unreliable"
    if decision == "INSUFFICIENT_EVIDENCE":
        return "Wait for additional source confirmation"
    if xref.contradiction_index > 0.4:
        return f"Contradiction index {xref.contradiction_index:.2f} rising — monitor closely"
    return "Signal valid while contradiction index stays below 0.6"


def _calibrated_section(xref: CrossReferenceResult) -> list[str]:
    """Build lines for the calibrated probability field. Never raises."""
    try:
        from consensus_engine.analysis.calibration import calibrate
        p_up = calibrate(float(xref.final_score), "1h")
        p_down = round(1.0 - p_up, 3)
        p_up_pct = f"{p_up * 100:.1f}%"
        p_down_pct = f"{p_down * 100:.1f}%"
        return [
            f"P(up 1h): **{p_up_pct}** | P(down): **{p_down_pct}**",
            f"Calibrated conf: **{p_up_pct}**",
        ]
    except Exception:
        return []


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

    if tweet.discord_source_link:
        fields.append({
            "name": "Source",
            "value": f"[View TweetShift message]({tweet.discord_source_link})",
            "inline": False,
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


def format_detail_followup(xref: CrossReferenceResult, precision: Optional[dict] = None) -> dict:
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

    if precision and not precision.get("skipped"):
        cls = precision.get("classification")
        cls_val = cls.value if hasattr(cls, "value") else str(cls)
        icon = {"STRONG_ALERT": "🟢", "WATCHLIST": "🟡", "IGNORE": "🔴"}.get(cls_val, "⚪")
        p_score = precision.get("total_score", 0)
        flags = []
        if precision.get("market_ok"):
            flags.append("market ✅")
        else:
            flags.append("market ❌")
        if precision.get("has_mainstream"):
            flags.append("mainstream ✅")
        precision_text = f"{icon} **{cls_val}** | score={p_score} | {' | '.join(flags)}"
        fields.append({"name": "Precision Engine", "value": precision_text, "inline": False})

    # Reliability + calibration fields (additive, only shown when reliability engine ran)
    if xref.reliability_decision:
        decision = xref.reliability_decision
        icon = _DECISION_ICONS.get(decision, "⚪")
        label = _DECISION_LABELS.get(decision, decision)

        cal_lines = _calibrated_section(xref)
        rel_parts = [f"{icon} **{label}**"]
        if cal_lines:
            rel_parts.extend(cal_lines)
        fields.append({"name": "Signal Verdict", "value": "\n".join(rel_parts), "inline": False})

        # Contradiction + freshness
        freshness = _freshness_label(xref.reliability_weights)
        contra_bar = "█" * int(xref.contradiction_index * 10) + "░" * (10 - int(xref.contradiction_index * 10))
        risk_lines = [
            f"Contradiction: `{contra_bar}` {xref.contradiction_index:.2f}",
            f"Freshness: **{freshness}**",
        ]
        reason_codes = _top_reason_codes(xref)
        if reason_codes:
            risk_lines.append(f"Drivers: {' · '.join(reason_codes)}")
        risk_lines.append(f"Invalidation: _{_invalidation_condition(xref)}_")
        fields.append({"name": "Risk Factors", "value": "\n".join(risk_lines), "inline": False})

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


async def send_instant_ping(
    tweet: ParsedTweet,
    current_price: float = 0.0,
    degraded: bool = False,
) -> Optional[str]:
    """Send the instant ping to Discord. Returns the message ID or None.

    When degraded=True, appends a DEGRADED DATA SOURCES warning to the embed footer.
    """
    if cfg.dry_run:
        ticker = tweet.tickers[0] if tweet.tickers else "???"
        log.info("[DRY-RUN] Instant ping: @%s $%s %s (score=%d)%s",
                 tweet.analyst, ticker, tweet.direction.value, tweet.base_score,
                 " [DEGRADED]" if degraded else "")
        return "dry_run_msg_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for instant ping")
        return None

    embed = format_instant_ping(tweet, current_price)
    if degraded:
        embed["footer"] = {"text": "OpenClaw Signal Engine | ⚠️ DEGRADED — data sources may be unreliable"}

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


async def edit_instant_ping(msg_id: str, content: str) -> bool:
    """Append a short status line (e.g. 'Phase 2 skipped — timeout') to an existing
    Phase-1 Discord message via PATCH. Returns True on 200/204.

    Silence never equals failure — callers invoke this on xref timeout or
    SignalClass.IGNORE so the user sees an explicit skip reason.
    """
    if cfg.dry_run:
        log.info("[DRY-RUN] Edit ping %s: %s", msg_id, content[:120])
        return True

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit() or not msg_id:
        log.warning("Discord not configured for edit_instant_ping")
        return False

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{msg_id}"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            async with session.patch(url, headers=headers, json={"content": content},
                                     timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 204):
                    return True
                error = await resp.text()
                log.warning("Discord edit error (%d) for msg %s: %s",
                            resp.status, msg_id, error[:200])
                return False
    except Exception as e:
        log.error("Failed to edit instant ping %s: %s", msg_id, e)
        return False


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
        momentum_str = f"{t['momentum']:.2f}".lstrip("0") if t.get("momentum", 0.0) > 0 else "—"
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


async def send_detail_followup(xref: CrossReferenceResult, reply_to_msg_id: str, precision: Optional[dict] = None) -> Optional[str]:
    """Send the detail follow-up as a reply to the instant ping. Returns message ID."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Detail follow-up: $%s score=%d", xref.ticker, xref.final_score)
        return "dry_run_followup_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        return None

    embed = format_detail_followup(xref, precision)

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
