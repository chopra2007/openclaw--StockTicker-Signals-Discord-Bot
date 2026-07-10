"""#71: the one place that tells the user something is BROKEN.

Not stock signals — outages. Schwab unreachable, a data source dead, the LLM chain
failing. These go to the `#errors` Discord channel, and the user-facing-critical ones
@-mention the owner.

Three rules, learned from the drift-alert and dead-source work:

1. **Fire on the transition, not the state.** Schwab down for an hour must post ONE
   alert, not sixty. Every caller reports its current state on every check; this
   module posts only when the state actually flips.
2. **Always follow up on recovery.** A resolved outage must not leave a scary
   unanswered @-mention. Coming back up posts a "restored" note with how long it was
   out.
3. **The state is persisted.** An engine restart in the middle of an outage must not
   re-ping. It lives in the `ops_alert_state` table, not memory.

Callers do not decide whether to send. They call `report_ops_state()` on every check
and this module stays silent unless something changed.

    await report_ops_state(
        "schwab_token", down=True, failure_class="token_lapsed",
        title="Schwab real-time feed is down",
        detail="The weekly login expired. Options data has fallen back to free "
               "15-minute-delayed prices.",
        fix="Run: python3 scripts/schwab_login.py",
    )
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger(__name__)

# Outage classes that @-mention the user. Everything else posts quietly.
# The bar: would the user want to be pulled out of dinner for this? Schwab dying
# silently degrades every options number the bot prints, and the LLM chain dying
# means no alert gets written at all. A single flaky scraper does not qualify.
MENTION_CLASSES = frozenset({"schwab_token", "schwab_auth", "schwab_api", "llm_health"})

# A source that dies and revives every 30 seconds would otherwise post a "broken"
# and a "recovered" message every 30 seconds. After an alert goes out, the same key
# cannot raise another DOWN alert for this long. A change of failure class bypasses
# it (the user's next action differs, so the message is worth the noise).
_DEFAULT_MIN_INTERVAL_S = 1800.0   # 30 min


def errors_channel_id() -> str:
    """The #errors channel. Falls back to the old ops channel so a missing env var
    degrades to 'posted somewhere' rather than 'silently swallowed'."""
    return str(
        cfg.get("discord.errors_channel_id", "")
        or cfg.get_api_key("discord_errors_channel_id")
        or os.environ.get("DISCORD_ERRORS_CHANNEL_ID", "")
        or cfg.get("dead_source.ops_channel_id", "")
        or cfg.get_api_key("discord_channel_id")
        or ""
    )


def owner_user_id() -> str:
    return str(cfg.get_api_key("discord_owner_user_id")
               or cfg.get("features.analyst_herding.ping_user_id", "") or "")


def _humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{int(seconds)} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def format_down(title: str, detail: str, fix: str = "") -> str:
    lines = [f"🔴 **{title}**", "", detail]
    if fix:
        lines += ["", f"**To fix:** {fix}"]
    lines += ["", "_You will get one more message here when it recovers._"]
    return "\n".join(lines)


def format_restored(title: str, down_for: float) -> str:
    return (f"🟢 **Recovered — {title}**\n\n"
            f"It was down for {_humanize_duration(down_for)}. Nothing to do.")


async def report_ops_state(
    alert_key: str,
    *,
    down: bool,
    title: str,
    detail: str = "",
    failure_class: Optional[str] = None,
    fix: str = "",
    mention: Optional[bool] = None,
) -> bool:
    """Report the CURRENT state of one thing. Posts only on a change.

    Returns True when a Discord message was actually sent.

    A change of `failure_class` while still down (e.g. the token lapsed, and now the
    API is 500ing too) re-alerts, because the user's next action differs. Never
    raises — an alerting bug must not take down the caller.
    """
    try:
        if not cfg.get("ops_alerts.enabled", True):
            return False

        state = "down" if down else "up"
        prior = await db.get_ops_alert_state(alert_key)
        prior_state = (prior or {}).get("state", "up")
        prior_class = (prior or {}).get("failure_class")
        # On recovery the caller has no failure class to give — inherit the one that
        # broke. Without this, a Schwab outage @-mentions the user going down and
        # then answers itself silently, leaving the ping hanging.
        klass = failure_class or (prior_class if not down else None) or alert_key

        class_changed = down and prior_state == "down" and prior_class != klass
        changed = (prior_state != state) or class_changed
        if not changed:
            return False   # steady state — say nothing

        # Never announce a recovery for something we never announced as broken.
        if not down and prior_state != "down":
            await db.set_ops_alert_state(alert_key, "up", klass, detail)
            return False

        now = time.time()
        last_alerted = (prior or {}).get("last_alerted_at") or 0.0
        since = float((prior or {}).get("since") or now)
        min_interval = float(cfg.get("ops_alerts.min_interval_s", _DEFAULT_MIN_INTERVAL_S))

        if down:
            # Flap guard. A class change is worth breaking it for; a plain re-open
            # of a source that just bounced is not.
            if last_alerted and not class_changed and (now - last_alerted) < min_interval:
                await db.set_ops_alert_state(alert_key, "down", klass, detail)
                log.info("ops_alert: %s re-opened within the flap window — staying quiet",
                         alert_key)
                return False
        else:
            # Only answer a ping we actually sent. If the DOWN alert for this episode
            # was swallowed by the flap guard, its "recovered" note would be a reply
            # to a message the user never saw.
            if last_alerted < since:
                await db.set_ops_alert_state(alert_key, "up", klass, detail)
                return False

        channel = errors_channel_id()
        if not channel:
            log.warning("ops_alert: no #errors channel configured; %s -> %s not sent",
                        alert_key, state)
            await db.set_ops_alert_state(alert_key, state, klass, detail)
            return False

        if down:
            content = format_down(title, detail, fix)
        else:
            content = format_restored(title, now - since)

        should_ping = (klass in MENTION_CLASSES) if mention is None else mention
        ping = owner_user_id() if should_ping else None

        from consensus_engine.alerts.discord import send_message
        msg_id = await send_message(channel, content, ping_user_id=ping)
        sent = bool(msg_id)
        await db.set_ops_alert_state(alert_key, state, klass, detail, alerted=sent)
        if sent:
            log.warning("ops_alert: %s -> %s (class=%s, pinged=%s)",
                        alert_key, state, klass, bool(ping))
        else:
            log.warning("ops_alert: %s -> %s but Discord send failed", alert_key, state)
        return sent
    except Exception as e:   # alerting must never break the caller
        log.warning("ops_alert: report_ops_state(%s) failed: %s", alert_key, e)
        return False
