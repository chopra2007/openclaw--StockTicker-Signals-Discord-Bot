"""Two-Phase Discord Alert Delivery.

Phase 1: Instant ping — analyst name, ticker, direction, options, price
Phase 2: Detail follow-up — replies to ping with cross-reference results
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine.utils.obs_log import obs_log
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    Direction, TweetType,
)

log = logging.getLogger("consensus_engine.alerts.discord")


def _safe_send_kwargs(payload: dict) -> dict:
    """Add allowed_mentions safety to any Discord POST payload.

    Always-on defense-in-depth: every Discord-bound POST passes through this
    helper so the bot can never @everyone/@here/role/user-ping via an
    accidentally-rendered string from an LLM, scraped page, or contributor
    text. The caller's payload is mutated in-place AND returned so it can be
    used inline (e.g. ``json=_safe_send_kwargs({...})``).
    """
    payload.setdefault("allowed_mentions", {"parse": []})
    return payload


# Regex to redact token-like strings before posting error text to Discord.
_SECRET_RE = re.compile(
    r'(?:token|key|secret|password|MTQ[A-Za-z0-9_-]{20,})',
    re.IGNORECASE,
)


def _redact_secrets(text: str) -> str:
    """Replace secret-like substrings with [REDACTED] in error text."""
    return _SECRET_RE.sub("[REDACTED]", text)


async def _safe_send(
    url: str,
    headers: dict,
    payload: dict,
    *,
    max_retries: int = 3,
) -> Optional[dict]:
    """POST payload to a Discord messages endpoint with retry/backoff.

    - On 400: falls back to chunked plaintext (strips embed, posts content).
    - On 429: reads Retry-After (header or body), sleeps, retries up to max_retries.
    - On exhaustion: posts a truncated-tail embed and returns None.
    - All error strings pass through _redact_secrets before any log/post.
    - Semaphore discipline: callers use `async with` — this helper has no semaphore.
    """
    session = await get_session()

    for attempt in range(max_retries + 1):
        try:
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    obs_log({"ts": time.time(), "event": "safe_send", "attempts": attempt, "status": "ok"})
                    return await resp.json()

                if resp.status == 400:
                    error_body = await resp.text()
                    log.warning(
                        "_safe_send 400 (attempt=%d): %s",
                        attempt, _redact_secrets(error_body[:300]),
                    )
                    # Strip embeds, fall back to plaintext content
                    text_fallback = ""
                    if "embeds" in payload:
                        for emb in payload.get("embeds", []):
                            text_fallback = (
                                emb.get("description", "")
                                or emb.get("title", "")
                            )[:1900]
                            break
                    if not text_fallback:
                        text_fallback = "[embed delivery failed — Discord rejected the payload]"
                    plain_payload = _safe_send_kwargs({
                        "content": text_fallback,
                    })
                    if "message_reference" in payload:
                        plain_payload["message_reference"] = payload["message_reference"]
                    async with session.post(
                        url, headers=headers, json=plain_payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as fb_resp:
                        if fb_resp.status in (200, 201):
                            return await fb_resp.json()
                    return None  # fallback also failed

                if resp.status == 429:
                    if attempt >= max_retries:
                        break
                    retry_after = float(
                        resp.headers.get("Retry-After", 1.0)
                    )
                    try:
                        body = await resp.json()
                        retry_after = float(body.get("retry_after", retry_after))
                    except Exception:
                        pass
                    log.warning(
                        "_safe_send 429 — sleeping %.1fs (attempt=%d/%d)",
                        retry_after, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # Other non-success
                error_body = await resp.text()
                log.warning(
                    "_safe_send HTTP %d (attempt=%d): %s",
                    resp.status, attempt, _redact_secrets(error_body[:300]),
                )
                return None

        except Exception as e:
            log.error("_safe_send exception (attempt=%d): %s", attempt, e)
            obs_log({"ts": time.time(), "event": "safe_send", "attempts": attempt, "status": "error"})
            return None

    # 429 exhausted — post truncated-tail embed
    obs_log({"ts": time.time(), "event": "safe_send", "attempts": attempt, "status": "exhausted"})
    log.error("_safe_send: 429 retries exhausted — posting truncation notice")
    truncation_payload = _safe_send_kwargs({
        "embeds": [{
            "description": "[reply truncated — Discord throttling]",
            "color": 0xFF6600,
        }],
    })
    if "message_reference" in payload:
        truncation_payload["message_reference"] = payload["message_reference"]
    try:
        async with session.post(
            url, headers=headers, json=truncation_payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            pass
    except Exception:
        pass
    return None


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
    """Build lines for the calibrated probability field. Never raises.

    Q1: stop lying. When shadow_mode is enabled and no trained model is loaded,
    render "score/100 (uncalibrated)" instead of the fake "Calibrated conf"
    label — the underlying value has always been score/100 in that state.
    """
    try:
        from consensus_engine.analysis.calibration import calibrate, has_trained_model
        score = float(xref.final_score)
        p_up = calibrate(score, "1h")
        p_up_pct = f"{p_up * 100:.1f}%"

        shadow_mode = cfg.get("calibration.shadow_mode.enabled", True)
        if shadow_mode and not has_trained_model("1h"):
            return [f"score/100 (uncalibrated): **{score:.0f}/100**"]

        p_down = round(1.0 - p_up, 3)
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

    # I4-full — single-score reconciliation (features.single_score.enabled).
    # Supersedes I4-display-honesty when both flags are ON.  When single_score is
    # ON, main.py has already computed precision["reconciled_score"] and
    # precision["i4_full_budget_depressed"] and embedded them in the precision dict;
    # this block reads those values directly for the headline and degraded flag.
    # Flag OFF → falls through to the I4-display-honesty block below (or legacy).
    #
    # Precedence rule (comment preserved for auditors):
    #   single_score ON  → this block runs; score_display_honesty is bypassed.
    #   single_score OFF, score_display_honesty ON → the honesty block runs.
    #   both OFF → legacy headline (raw additive total).
    single_score_on = cfg.get("features.single_score.enabled", False)
    honesty_on = cfg.get("features.score_display_honesty.enabled", False)
    headline_total = total
    budget_degraded = False
    displayed_score = None
    if single_score_on and precision and not precision.get("skipped") and "reconciled_score" in precision:
        # I4-full path: reconciled_score was computed in main.py with the never-contradict
        # and budget-fallback rules already applied.
        displayed_score = int(precision["reconciled_score"])
        budget_degraded = bool(precision.get("i4_full_budget_depressed"))
        headline_total = displayed_score
    elif honesty_on and precision and not precision.get("skipped"):
        # I4-display-honesty: behind features.score_display_honesty.enabled. With the
        # flag OFF, headline_total stays the raw additive sum (total) → byte-identical
        # legacy headline. With it ON, render the precision-gated number (never the
        # inflated additive sum), surface an explicit budget-degraded state when a paid
        # source was skipped, and never show a number that contradicts the class
        # (no STRONG with a sub-medium number).
        med = cfg.get("precision_engine.thresholds.medium_confidence", 65)
        cls_obj = precision.get("classification")
        cls_str = cls_obj.value if hasattr(cls_obj, "value") else str(cls_obj)
        p_score = int(precision.get("total_score", 0) or 0)
        displayed_score = p_score
        # never show a number that contradicts the class
        if cls_str == "STRONG_ALERT" and displayed_score < med:
            displayed_score = med
        budget_degraded = bool(precision.get("skipped_sources"))
        # budget-depressed: never silently show the higher number — show the gated
        # number with an explicit degraded state.
        headline_total = displayed_score
        log.info(
            "[I4-display] $%s reconciled: additive=%d precision=%d displayed=%d class=%s budget_degraded=%s skipped=%s",
            xref.ticker, total, p_score, displayed_score, cls_str,
            budget_degraded, precision.get("skipped_sources"),
        )

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
        if single_score_on and displayed_score is not None:
            # I4-full: show the reconciled number and flag budget-degraded state.
            if budget_degraded:
                flags.append("confidence degraded: budget")
            precision_text = f"{icon} **{cls_val}** | score={displayed_score} | {' | '.join(flags)}"
        elif honesty_on and displayed_score is not None:
            # I4-display-honesty: show the gated number, and on a budget-depressed
            # run flag the degraded confidence explicitly (never the higher number).
            if budget_degraded:
                flags.append("confidence degraded: budget")
            precision_text = f"{icon} **{cls_val}** | score={displayed_score} | {' | '.join(flags)}"
        else:
            precision_text = f"{icon} **{cls_val}** | score={p_score} | {' | '.join(flags)}"
        fields.append({"name": "Precision Engine", "value": precision_text, "inline": False})

    # I14-display: regime risk-context line, behind features.regime_context_line.enabled.
    # Pure-additive display. On cold-start render "warming up" (no implied protection).
    if cfg.get("features.regime_context_line.enabled", False) and precision and precision.get("regime"):
        regime = precision["regime"]
        if getattr(regime, "cold_start", False):
            regime_text = "regime: warming up"
        else:
            regime_text = f"Regime: {regime.label} (z={regime.z_score:.1f})"
        fields.append({"name": "Regime", "value": regime_text, "inline": False})

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
    # I4/#46: when the gated headline differs from the raw additive sum, end the
    # Breakdown line at the SAME number the title shows (no two disagreeing numbers
    # in one alert). Both-flags-OFF path stays byte-identical to the legacy render.
    if headline_total != total and (single_score_on or honesty_on):
        breakdown_text = " + ".join(parts) + f" = {total} raw → {headline_total} after quality gates"
    else:
        breakdown_text = " + ".join(parts) + f" = {total}"
    fields.append({"name": "Breakdown", "value": breakdown_text, "inline": False})

    if not xref.catalyst_summary and not xref.other_analysts and not xref.social_summary:
        fields.insert(0, {"name": "Status", "value": "No additional signals found", "inline": False})

    title = f"Cross-Reference: ${xref.ticker} | Score: {headline_total}"
    # Show budget-degraded suffix when either I4-full or I4-display-honesty is active.
    if budget_degraded and (single_score_on or honesty_on):
        title += " | confidence degraded: budget"
    embed = {
        "title": title,
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

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = _safe_send_kwargs({"embeds": [embed]})
    data = await _safe_send(url, headers, body)
    if data:
        msg_id = data.get("id")
        log.info("Instant ping sent for $%s by @%s (msg_id=%s)",
                 tweet.tickers[0] if tweet.tickers else "???",
                 tweet.analyst, msg_id)
        return msg_id
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
        session = await get_session()
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

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = _safe_send_kwargs({"embeds": [embed]})
    data = await _safe_send(url, headers, payload)
    if not data:
        log.warning("Trend digest send failed")
        return None
    return data.get("id")


_DISCORD_MSG_LIMIT = 2000


def _split_for_discord(content: str, limit: int = _DISCORD_MSG_LIMIT) -> list[str]:
    """Split `content` into chunks ≤ `limit` chars. Prefer paragraph then line breaks.

    Returns [] for empty input. Any single line longer than the limit is hard-cut
    on a character boundary as a last resort.
    """
    if not content:
        return []
    if len(content) <= limit:
        return [content]

    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 4:
            cut = window.rfind("\n")
        if cut < limit // 4:
            cut = window.rfind(" ")
        if cut < limit // 4:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n").lstrip()
    return chunks


async def send_command_reply(channel_id: str, reply_to_msg_id: str, content: str) -> Optional[str]:
    """Send a plain-text reply, splitting into multiple messages if > 2000 chars.

    Each subsequent chunk replies to the prior bot message so the thread stays
    visually grouped. Returns the ID of the last sent message (or None on
    first-message failure).
    """
    if cfg.dry_run:
        log.info("[DRY-RUN] Command reply to %s: %s", reply_to_msg_id, content[:80])
        return "dry_run_reply_id"

    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None

    chunks = _split_for_discord(content)
    if not chunks:
        return None

    last_id: Optional[str] = None
    reply_target = reply_to_msg_id
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    for chunk in chunks:
        payload = _safe_send_kwargs({
            "content": chunk,
            "message_reference": {"message_id": reply_target},
        })
        data = await _safe_send(url, headers, payload)
        if not data:
            return last_id
        last_id = data.get("id")
        if last_id:
            reply_target = last_id
    return last_id


async def send_command_embed_reply(
    channel_id: str,
    reply_to_msg_id: str,
    embed: dict,
) -> Optional[str]:
    """Send an embed reply to a Discord command message (used by !all)."""
    if cfg.dry_run:
        log.info(
            "[DRY-RUN] Embed reply to %s: %s",
            reply_to_msg_id, embed.get("title", ""),
        )
        return "dry_run_reply_id"

    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = _safe_send_kwargs({
        "embeds": [embed],
        "message_reference": {"message_id": reply_to_msg_id},
    })
    data = await _safe_send(url, headers, body)
    return data.get("id") if data else None


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
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = _safe_send_kwargs({
        "embeds": [embed],
        "message_reference": {"message_id": reply_to_msg_id},
    })
    data = await _safe_send(url, headers, body)
    if data:
        msg_id = data.get("id")
        log.info("Detail follow-up sent for $%s (score=%d, msg_id=%s)",
                 xref.ticker, xref.final_score, msg_id)
        return msg_id
    return None
