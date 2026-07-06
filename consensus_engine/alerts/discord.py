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
from consensus_engine.alerts.display_scale import regime_stress, regime_emoji, disagreement, call_put_split
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
        return f"Disagreement {disagreement(xref.contradiction_index)}/100 rising — monitor closely"
    return "Signal valid while disagreement stays below 60/100"


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
            parts_o.append(f"Unusual CALLS (max ratio {opt.max_call_ratio:.1f}x vol/OI)")
        if opt.unusual_puts:
            parts_o.append(f"Unusual PUTS (max ratio {opt.max_put_ratio:.1f}x vol/OI)")
        # #53: show the day's call/put lean as an intuitive % split (from raw
        # volumes, never the put_call_ratio, which is 0.0 on a one-sided day).
        _split = call_put_split(opt.total_call_vol, opt.total_put_vol)
        if _split:
            parts_o.append(f"🟢 Calls {_split[0]}% / 🔴 Puts {_split[1]}% (today's volume)")
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
            stress = regime_stress(regime.z_score)
            regime_text = (
                f"{regime_emoji(regime.label)} Market stress: {stress}/100 "
                f"({regime.label})"
            )
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
            f"Disagreement: `{contra_bar}` {disagreement(xref.contradiction_index)}/100",
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


# --- #63 decision-first render ------------------------------------------------
# One self-editing card that answers "act or watch?" first. Deliberately hides the
# additive-score arithmetic, the Precision-Engine green-checks, the Regime line, the
# raw score number, and SNAKE_CASE driver codes — the numeric score has ~no
# predictive edge (AUC ~0.50), so ACT/WATCH keys off CATALYST + independent
# corroboration, never the number. Most alerts default to WATCH (honest abstention).

_DECISION_FRESHNESS_WORDS = {
    "FRESH": "news is fresh",
    "MODERATE": "news is hours old",
    "STALE": "news is stale",
}


def _decision_direction(xref: CrossReferenceResult, override=None) -> str:
    """Resolve LONG/SHORT for the card. CrossReferenceResult carries no direction
    field, so production threads the real `tweet.direction` in via `override` (the
    price stop's side depends on it — a SHORT stops ABOVE spot, a LONG below).
    Falls back to any `xref.direction` if later threaded, else LONG."""
    d = override if override is not None else getattr(xref, "direction", None)
    if d is None:
        return "LONG"
    val = d.value if hasattr(d, "value") else str(d)
    return "SHORT" if str(val).lower() == "short" else "LONG"


def format_decision_card(
    xref: CrossReferenceResult, precision: Optional[dict] = None, *, direction=None,
) -> dict:
    """Build the decision-first Discord embed (#63): ACT/WATCH + Strong/Lean/Watch
    bucket + a concrete price stop, in one card. Pure (no I/O). `direction` is the
    signal's Direction enum (or "long"/"short"); when omitted, defaults to LONG."""
    from consensus_engine.alerts.all_command.levels import _compute_atr_fallback

    ticker = xref.ticker

    # Precision classification string, only when precision ran.
    cls = None
    if precision and not precision.get("skipped"):
        c = precision.get("classification")
        cls = c.value if hasattr(c, "value") else (str(c) if c is not None else None)

    has_options = bool(xref.options and xref.options.has_unusual_activity)
    hard_corroborator = bool(xref.sec_summary or has_options or xref.catalyst_summary)
    stop_available = bool(
        xref.technical is not None and xref.technical.atr14 and xref.technical.price > 0
    )

    if cls == "STRONG_ALERT" and hard_corroborator:
        bucket = "Strong"
    elif cls == "STRONG_ALERT" or (cls == "WATCHLIST" and hard_corroborator):
        bucket = "Lean"
    else:
        bucket = "Watch"
    act = bucket == "Strong" and stop_available

    long_short = _decision_direction(xref, direction)
    bull_bear = "BEARISH" if long_short == "SHORT" else "BULLISH"

    # Description: bucket + plain-English reason naming the corroborators.
    corr = []
    if has_options:
        corr.append("unusual options activity")
    if xref.sec_summary:
        corr.append("an SEC filing")
    if xref.catalyst_summary:
        corr.append("a news catalyst")
    if corr:
        reason = " — " + " + ".join(corr)
    else:
        reason = " — no confirmed catalyst — monitor"
    description = f"**{bucket}**{reason}"

    fields = []
    stop = None

    # Trade — only when a real ATR stop is computable.
    if stop_available:
        spot = xref.technical.price
        atr14 = xref.technical.atr14
        # _compute_atr_fallback puts the stop at 2×ATR and returns a 1/2/3×ATR target
        # ladder. Advertising the 1×ATR rung as "Target" would show R:R 1:0.5 (risk 2
        # to make 1) — misleading on a card that says ACT. Use the 2×ATR rung so the
        # primary target is at least as far as the stop (honest 1:1 or better).
        stop, tps = _compute_atr_fallback(spot, atr14, bull_bear)
        risk = abs(spot - stop)
        target = next((t for t in tps if abs(t - spot) >= risk), tps[-1])
        stop_pct = (stop - spot) / spot * 100.0
        tp_pct = (target - spot) / spot * 100.0
        reward = abs(target - spot)
        rr = round(reward / risk, 1) if risk else 0.0
        fields.append({
            "name": "Trade",
            "value": (
                f"Enter ~${spot:.2f} · Stop ${stop:.2f} ({stop_pct:+.1f}%) · "
                f"Target ${target:.2f} ({tp_pct:+.1f}%) · R:R 1:{rr}"
            ),
            "inline": False,
        })

    # Why — plain-English catalyst.
    if xref.catalyst_summary:
        why = xref.catalyst_summary[:180]
        if xref.catalyst_type:
            why = f"{xref.catalyst_type}: {why}"
    elif has_options:
        sides = []
        if xref.options.unusual_calls:
            sides.append("calls")
        if xref.options.unusual_puts:
            sides.append("puts")
        why = "Unusual options flow" + (f" ({' & '.join(sides)})" if sides else "")
    elif xref.social_summary:
        why = xref.social_summary[:180]
    else:
        why = "No hard catalyst; social/technical only."
    fields.append({"name": "Why", "value": why, "inline": False})

    # Watch — invalidation, disagreement, freshness; ends with a subtle vault pointer.
    dis = disagreement(xref.contradiction_index)
    fresh_word = _DECISION_FRESHNESS_WORDS.get(
        _freshness_label(xref.reliability_weights), "freshness unknown"
    )
    if stop_available:
        watch_value = (
            f"Invalid below ${stop:.2f}. Disagreement {dis}/100. {fresh_word}. "
            f"Full breakdown in vault."
        )
    else:
        watch_value = (
            f"No price level yet — monitor, not actionable. "
            f"Disagreement {dis}/100. {fresh_word}. Full breakdown in vault."
        )
    fields.append({"name": "Watch", "value": watch_value, "inline": False})

    embed = {
        "title": f"{'🟢 ACT' if act else '🟡 WATCH'} — ${ticker} {long_short}",
        "description": description,
        "color": 0x00C853 if act else 0xFFB300,
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


def _human_span(seconds: float) -> str:
    """Plain-English elapsed span for the swarm title: '40 min', '1 hour', '5 hours'."""
    if seconds < 3600:
        m = max(1, int(round(seconds / 60.0)))
        return f"{m} min"
    h = max(1, int(round(seconds / 3600.0)))
    return f"{h} hour" + ("" if h == 1 else "s")


def format_swarm_alert(swarm, current_price: float = 0.0, links: Optional[dict] = None) -> dict:
    """Build the loud SWARM embed for a SwarmResult. Pure (no I/O) so it is unit-testable.
    `links` maps analyst handle -> source URL (clickable handles); missing -> plain @handle.
    Title time = how long the swarm has been building (first tweet -> latest)."""
    links = links or {}
    ticker = swarm.ticker
    members = list(swarm.analysts or [])
    n = swarm.count or len(members)
    span_txt = _human_span(max(0.0, (swarm.now_ts or 0.0) - (swarm.opened_at or 0.0)))

    def _handle(a):
        url = links.get(a)
        return f"[@{a}]({url})" if url else f"@{a}"

    handles = ", ".join(_handle(a) for a in members[:20])
    fields = [{"name": "Analysts", "value": handles or "—", "inline": False}]

    times = swarm.member_times or {}
    posted = sorted(t for t in times.values() if t)
    if posted:
        first = time.strftime("%H:%M", time.gmtime(posted[0]))
        last = time.strftime("%H:%M", time.gmtime(posted[-1]))
        fields.append({"name": "Window", "value": f"{n} posts, {first}–{last} UTC", "inline": False})

    if current_price and current_price > 0:
        fields.append({"name": "Price", "value": f"${current_price:.2f}", "inline": True})

    return {
        "title": f"\U0001f6a8 SWARM: ${ticker} — {n} analysts tweeting in {span_txt}",
        "color": 0xED4245,  # red — loud, breaking
        "fields": fields,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine | analyst swarm"},
    }


async def send_swarm_alert(swarm, current_price: float = 0.0) -> Optional[str]:
    """Post the loud SWARM alert + @-ping the configured user. Returns the message ID or
    None. Fires on swarm open and on every new analyst that joins (caller decides)."""
    members = list(swarm.analysts or [])
    if cfg.dry_run:
        log.info("[DRY-RUN] SWARM alert: $%s %d analysts (%s)", swarm.ticker, swarm.count, swarm.reason)
        return "dry_run_msg_id"

    token = cfg.get_api_key("discord_bot_token")
    # A2: SWARM alerts post to the dedicated #alerts channel; falls back to the
    # main channel when swarm_alert_channel_id is blank.
    channel_id = str(cfg.get("api_keys.swarm_alert_channel_id", "") or "")
    if not channel_id:
        channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for swarm alert")
        return None

    # Best-effort: clickable handles via signal_events.source_link (NULL on old rows).
    links: dict = {}
    try:
        from consensus_engine import db as _db
        if members:
            conn = await _db.get_db()
            ph = ",".join("?" * len(members))
            cur = await conn.execute(
                f"""SELECT source_detail, source_link FROM signal_events
                    WHERE source_type='twitter' AND ticker=? AND source_detail IN ({ph})
                      AND source_link IS NOT NULL GROUP BY source_detail""",
                [swarm.ticker] + members,
            )
            for row in await cur.fetchall():
                if row["source_link"] and row["source_detail"]:
                    links[row["source_detail"]] = row["source_link"]
    except Exception as e:
        log.debug("[A2] swarm link lookup failed: %s", e)

    embed = format_swarm_alert(swarm, current_price, links=links)
    payload: dict = {"embeds": [embed]}
    # Ping the configured user. allowed_mentions is set HERE (before _safe_send_kwargs's
    # setdefault) so the bot's default parse:[] mention-block doesn't strip this one ping.
    ping_id = str(cfg.get("features.analyst_herding.ping_user_id", "") or "")
    if ping_id.isdigit():
        payload["content"] = f"<@{ping_id}>"
        payload["allowed_mentions"] = {"users": [ping_id]}

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = _safe_send_kwargs(payload)
    data = await _safe_send(url, headers, body)
    if data:
        msg_id = data.get("id")
        log.info("[A2] SWARM alert sent for $%s (%d analysts, %s, msg_id=%s)",
                 swarm.ticker, swarm.count, swarm.reason, msg_id)
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


async def edit_instant_ping_embed(msg_id: str, embed: dict) -> bool:
    """Replace an existing Phase-1 message's EMBED via PATCH (#63 decision-first).

    Same token/channel guards and dry_run behaviour as edit_instant_ping, but the
    PATCH body carries {"embeds": [embed]} instead of text content, so the instant
    ping is rewritten in place into the decision card (no second message). Returns
    True on 200/204.
    """
    if cfg.dry_run:
        log.info("[DRY-RUN] Edit ping embed %s: %s", msg_id, embed.get("title", "")[:120])
        return True

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit() or not msg_id:
        log.warning("Discord not configured for edit_instant_ping_embed")
        return False

    try:
        session = await get_session()
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{msg_id}"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        async with session.patch(url, headers=headers, json={"embeds": [embed]},
                                 timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status in (200, 204):
                return True
            error = await resp.text()
            log.warning("Discord embed edit error (%d) for msg %s: %s",
                        resp.status, msg_id, error[:200])
            return False
    except Exception as e:
        log.error("Failed to edit instant ping embed %s: %s", msg_id, e)
        return False


async def send_decision_followup(
    xref: CrossReferenceResult, instant_msg_id: str, precision: Optional[dict] = None,
    *, direction=None,
) -> Optional[str]:
    """Decision-first follow-up (#63): EDIT the instant ping in place into the
    decision card — no new message. Returns instant_msg_id on success (so the
    caller's followup bookkeeping still gets a message id), None on failure."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Decision card (edit-in-place) for $%s", xref.ticker)
        return "dry_run_decision_id"

    embed = format_decision_card(xref, precision, direction=direction)
    ok = await edit_instant_ping_embed(instant_msg_id, embed)
    return instant_msg_id if ok else None


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
        # #53: momentum (mentions ÷ 24h) was a unitless ".42" that read as noise
        # and just restated the mention count already shown — dropped from display.
        lines.append(
            f"**{i}.** `${t['ticker']}` — {t['mentions']} mentions | "
            f"{t['unique_authors']} authors"
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


async def send_message(channel_id: str, content: str) -> Optional[str]:
    """Post a plain-text message to a channel (no reply reference).

    Used for ops/health alerts (e.g. the C5 dead-source alert and the existing
    feature-volume-drop monitor, whose import previously referenced this missing
    function inside a bare except — silently dead until now). Splits content
    >2000 chars; respects dry_run. Returns the last message id, or None.
    """
    if cfg.dry_run:
        log.info("[DRY-RUN] ops message to %s: %s", channel_id, content[:80])
        return "dry_run_msg_id"
    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None
    chunks = _split_for_discord(content)
    if not chunks:
        return None
    last_id: Optional[str] = None
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    for chunk in chunks:
        data = await _safe_send(url, headers, _safe_send_kwargs({"content": chunk}))
        if not data:
            return last_id
        last_id = data.get("id")
    return last_id


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


async def send_command_embed_with_image(
    channel_id: str,
    reply_to_msg_id: str,
    embed: dict,
    image_bytes: Optional[bytes],
    filename: str,
) -> Optional[str]:
    """Send an embed reply with an attached PNG (multipart upload, used by !em).

    The embed should reference the image via ``{"image": {"url":
    "attachment://<filename>"}}``. Mirrors send_command_embed_reply's
    dry-run/token/allowed-mentions handling and retries on 429. If the image is
    missing or the multipart upload fails, it falls back to the embed without
    the image so the user still gets the numbers.
    """
    if cfg.dry_run:
        log.info(
            "[DRY-RUN] Embed+image reply to %s: %s (%s, %d bytes)",
            reply_to_msg_id, embed.get("title", ""), filename,
            len(image_bytes or b""),
        )
        return "dry_run_reply_id"

    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None

    # No chart bytes — degrade to an image-less embed rather than fail.
    if not image_bytes:
        embed_noimg = {k: v for k, v in embed.items() if k != "image"}
        return await send_command_embed_reply(channel_id, reply_to_msg_id, embed_noimg)

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}  # aiohttp sets the multipart Content-Type
    payload = _safe_send_kwargs({
        "embeds": [embed],
        "message_reference": {"message_id": reply_to_msg_id},
        "attachments": [{"id": 0, "filename": filename}],
    })

    session = await get_session()
    for attempt in range(4):
        try:
            # FormData is single-use; rebuild it each attempt.
            form = aiohttp.FormData()
            form.add_field("payload_json", json.dumps(payload),
                           content_type="application/json")
            form.add_field("files[0]", image_bytes, filename=filename,
                           content_type="image/png")
            async with session.post(
                url, headers=headers, data=form,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get("id")
                if resp.status == 429 and attempt < 3:
                    retry_after = float(resp.headers.get("Retry-After", 1.0))
                    try:
                        rbody = await resp.json()
                        retry_after = float(rbody.get("retry_after", retry_after))
                    except Exception:
                        pass
                    log.warning(
                        "send_command_embed_with_image 429 — sleeping %.1fs (attempt=%d)",
                        retry_after, attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                error_body = await resp.text()
                log.warning(
                    "send_command_embed_with_image HTTP %d (attempt=%d): %s",
                    resp.status, attempt, _redact_secrets(error_body[:300]),
                )
                break
        except Exception as e:
            log.error("send_command_embed_with_image exception (attempt=%d): %s", attempt, e)
            break

    # Multipart failed — send the embed without the image so the numbers land.
    fallback = {k: v for k, v in embed.items() if k != "image"}
    return await send_command_embed_reply(channel_id, reply_to_msg_id, fallback)


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
