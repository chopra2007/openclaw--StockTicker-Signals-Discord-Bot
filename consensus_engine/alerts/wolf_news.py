"""#news alert layer for the Wolf macro-brain (TODO #20, phase 1).

Posts proactive alerts on a new or stage-changed Wolf thesis, through a durable
outbox so a crash can never double-post or lose an alert:

    create pending row (dedupe_key = "<thesis_id>|<stage>")  -> post -> mark posted

Tiers (phase 1, Wolf-only — no confluence yet):
    surface  = forming / diverging / imminent  -> plain #news post, no @-ping
    high     = acting (Wolf revealed a position) -> louder #news post, no @-ping
    critical = Wolf + >=2 corroborating sources  -> @-ping  (PHASE 2 only)

The @-ping path (allowed_mentions override + <=3/hr rate limit) is built and
unit-tested but stays dormant in phase 1: critical tier is never reached without
the phase-2 confluence engine, and `wolf.enable_critical_ping` defaults off.
"""
from __future__ import annotations

import json
import logging
import time

from consensus_engine import config as cfg, db

log = logging.getLogger(__name__)

# Critical @-ping rate limit (independent of the email ingestion cap).
_CRITICAL_PING_WINDOW = 3600
_CRITICAL_PING_MAX = 3
_critical_ping_log: list[float] = []

_DIR_EMOJI = {"bull": "🟢", "bear": "🔴"}
_STAGE_LABEL = {
    "forming": "forming",
    "diverging": "divergences building",
    "imminent": "imminent",
    "acting": "Wolf has taken a position",
}


def tier_for(event: dict) -> str:
    """Phase-1 tier from the stage. 'acting' is the highest Wolf-only signal."""
    return "high" if event.get("stage") == "acting" else "surface"


def _can_ping(now: float) -> bool:
    """True if a critical @-ping is allowed under the <=3/hr rate limit."""
    cutoff = now - _CRITICAL_PING_WINDOW
    _critical_ping_log[:] = [t for t in _critical_ping_log if t > cutoff]
    if len(_critical_ping_log) >= _CRITICAL_PING_MAX:
        return False
    _critical_ping_log.append(now)
    return True


def format_message(event: dict, levels: list[dict]) -> str:
    """Build the #news message text from VALIDATED fields only (never raw email text)."""
    direction = event["direction"]
    emoji = _DIR_EMOJI.get(direction, "⚪")
    scope_key = event["scope_key"]
    scope_type = event["scope_type"]
    stage_lbl = _STAGE_LABEL.get(event["stage"], event["stage"])
    head = "🆕 New thesis" if event["kind"] == "new" else "🔄 Stage change"
    arrow = ""
    if event["kind"] == "stage_change" and event.get("old_stage"):
        arrow = f" ({event['old_stage']} → {event['stage']})"
    lines = [
        f"{emoji} **{scope_key}** ({scope_type}) — Wolf turns **{direction.upper()}**",
        f"{head}: {stage_lbl}{arrow}",
    ]
    if levels:
        lvl_txt = ", ".join(
            f"{l['price']:g}" + (f" ({l['role']})" if l.get("role") else "")
            for l in levels[:5]
        )
        lines.append(f"Key levels: {lvl_txt}")
    snippet = event.get("snippet", "")
    if snippet:
        lines.append(f"_{snippet}_")
    return "\n".join(lines)


async def _send_news(content: str, ping_user_id: str | None = None) -> str | None:
    """POST to #news. If ping_user_id is set, prefix an @-mention and allow it.

    Returns the Discord message id on success, None otherwise.
    """
    import aiohttp

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_news_channel_id", "") or "")
    if not token or not channel_id:
        log.warning("wolf_news: missing discord token or news channel_id; skipping post")
        return None

    payload: dict = {"content": content[:1990]}
    if ping_user_id:
        payload["content"] = f"<@{ping_user_id}> " + payload["content"]
        payload["content"] = payload["content"][:1990]
        payload["allowed_mentions"] = {"users": [str(ping_user_id)]}
    else:
        payload["allowed_mentions"] = {"parse": []}

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get("id")
                body = await resp.text()
                log.error("wolf_news: discord post failed %s: %s", resp.status, body[:200])
                return None
    except Exception as exc:
        log.error("wolf_news: discord post error: %s", exc)
        return None


async def post_event(event: dict) -> bool:
    """Post one thesis event to #news via the durable outbox. Returns True if posted.

    Dry-run (config wolf.dry_run, default True) records the outbox row + logs the
    rendered message but does NOT hit Discord — used for the pre-sign-off gate.
    """
    now = time.time()
    tier = tier_for(event)
    thesis_id = event["thesis_id"]
    dedupe_key = f"{thesis_id}|{event['stage']}"

    # fetch the thesis levels for rendering
    levels = []
    thesis = await db.get_active_thesis(event["scope_type"], event["scope_key"], event["direction"])
    if thesis:
        try:
            levels = json.loads(thesis["key_levels_json"]) or []
        except Exception:
            levels = []

    payload = {"event": event, "tier": tier}
    alert_id = await db.create_pending_alert(dedupe_key, thesis_id, tier, json.dumps(payload), now)
    if alert_id is None:
        log.debug("wolf_news: already alerted for %s, skipping", dedupe_key)
        return False

    content = format_message(event, levels)

    # critical @-ping is phase-2 only (needs confluence corroborator) AND opt-in
    ping_user = None
    if (tier == "critical"
            and cfg.get("wolf.enable_critical_ping", False)
            and _can_ping(now)):
        ping_user = str(cfg.get("api_keys.discord_owner_user_id", "") or "") or None

    dry_run = cfg.get("wolf.dry_run", True)
    if dry_run:
        log.info("wolf_news[DRY-RUN] would post to #news (tier=%s):\n%s", tier, content)
        await db.mark_alert_posted(alert_id, None, now)
        return True

    msg_id = await _send_news(content, ping_user_id=ping_user)
    if msg_id:
        await db.mark_alert_posted(alert_id, msg_id, now)
        return True
    await db.mark_alert_failed(alert_id)
    return False


async def post_events(events: list[dict]) -> int:
    """Post a batch of events. Returns the count actually posted."""
    posted = 0
    for ev in events:
        try:
            if await post_event(ev):
                posted += 1
        except Exception as exc:
            log.error("wolf_news: post_event error: %s", exc, exc_info=True)
    return posted
