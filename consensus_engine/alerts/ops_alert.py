"""#71: the one place that tells the user something is BROKEN.

Not stock signals — outages. Schwab unreachable, a data source dead, the LLM chain
failing. These go to the `#errors` Discord channel, quietly: nothing here ever
@-mentions anyone (2026-07-12, user).

Four rules, learned from the drift-alert and dead-source work:

1. **Fire on the transition, not the state.** Schwab down for an hour must post ONE
   alert, not sixty. Every caller reports its current state on every check; this
   module posts only when the state actually flips.
2. **Always follow up on recovery.** Coming back up posts a "restored" note with how
   long it was out, so a scary message never sits there unanswered.
3. **The state is persisted.** An engine restart in the middle of an outage must not
   re-alert. It lives in the `ops_alert_state` table, not memory.
4. **One reporter at a time.** Callers run concurrently (a batch of quotes fans out
   over `asyncio.gather`), so the read-decide-send-write below is serialized per key.
   Without that, N coroutines all read "down", all send, and the user gets N copies
   of the same message.

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

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger(__name__)

# A source that dies and revives every 10 minutes would otherwise post a "broken"
# and a "recovered" message every 10 minutes. After an alert goes out, the same key
# cannot raise another DOWN alert for this long, so a thing that keeps breaking all
# afternoon costs at most one broken + one recovered message an hour. A change of
# failure class bypasses it (the user's next action differs, so it's worth the noise).
_DEFAULT_MIN_INTERVAL_S = 3600.0   # 1 hour

# Some things fail one call and are fine on the next. For those, the caller passes
# `confirm_after_s`: the thing has to still be down that many seconds later before a
# word is said. Schwab spent 2026-07-27 → 2026-08-03 posting a "servers are not
# responding" and a "recovered — down for 0 seconds" every hour, all day, off single
# blown calls. Default 0 = announce on the first failure, which is right for anything
# already checked on a slow cadence (the daily LLM probe would otherwise wait a day).
_DEFAULT_CONFIRM_AFTER_S = 0.0

# One lock per alert key. Serializes the read-decide-send-write below so concurrent
# callers cannot each decide, independently, that they are the one to announce.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


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
    confirm_after_s: Optional[float] = None,
) -> bool:
    """Report the CURRENT state of one thing. Posts only on a change.

    Returns True when a Discord message was actually sent.

    A change of `failure_class` while still down (e.g. the token lapsed, and now the
    API is 500ing too) re-alerts, because the user's next action differs. Never
    raises — an alerting bug must not take down the caller.

    `confirm_after_s` holds a DOWN alert until the thing has been continuously down
    that long, so a single blown call never reaches the user. Recovering inside the
    window is silent on both sides. Only pass it for something checked often.
    """
    try:
        if not cfg.get("ops_alerts.enabled", True):
            return False

        # Everything from reading the prior state to writing the new one runs under
        # this key's lock. Concurrent callers queue; the first one flips the state,
        # and the rest fall out at the "steady state" check below instead of each
        # posting their own copy of the same message.
        async with _locks[alert_key]:
            state = "down" if down else "up"
            prior = await db.get_ops_alert_state(alert_key)
            prior_state = (prior or {}).get("state", "up")
            prior_class = (prior or {}).get("failure_class")
            # On recovery the caller has no failure class to give — inherit the one
            # that broke, so the recovery is judged against the outage it answers.
            klass = failure_class or (prior_class if not down else None) or alert_key

            class_changed = down and prior_state == "down" and prior_class != klass

            now = time.time()
            last_alerted = float((prior or {}).get("last_alerted_at") or 0.0)
            since = float((prior or {}).get("since") or now)
            min_interval = float(
                cfg.get("ops_alerts.min_interval_s", _DEFAULT_MIN_INTERVAL_S))
            confirm_after = float(
                _DEFAULT_CONFIRM_AFTER_S if confirm_after_s is None else confirm_after_s)

            if down:
                if prior_state != "down" and confirm_after > 0:
                    # First failure of this episode. Start the clock; whether it is
                    # worth telling anyone about depends on it still being down when
                    # the next check comes round.
                    await db.set_ops_alert_state(alert_key, "down", klass, detail)
                    return False
                elif prior_state == "down" and last_alerted >= since and not class_changed:
                    return False   # steady state — already announced this episode
                elif not class_changed and (now - since) < confirm_after:
                    await db.set_ops_alert_state(alert_key, "down", klass, detail)
                    return False   # still inside the confirmation window

                # Flap guard. A class change is worth breaking it for; a plain re-open
                # of a source that just bounced is not.
                if last_alerted and not class_changed and (now - last_alerted) < min_interval:
                    await db.set_ops_alert_state(alert_key, "down", klass, detail)
                    log.info("ops_alert: %s re-opened within the quiet window — staying quiet",
                             alert_key)
                    return False
            else:
                # Never announce a recovery for something we never announced as broken,
                # and only answer a message we actually sent. If this episode's DOWN
                # alert was swallowed by the confirmation window or the flap guard, its
                # "recovered" note would reply to a message the user never saw.
                if prior_state != "down":
                    return False   # steady state — say nothing, write nothing
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

            # No @-mentions in #errors, ever (2026-07-12, user).
            from consensus_engine.alerts.discord import send_message
            msg_id = await send_message(channel, content, ping_user_id=None)
            sent = bool(msg_id)
            await db.set_ops_alert_state(alert_key, state, klass, detail, alerted=sent)
            if sent:
                log.warning("ops_alert: %s -> %s (class=%s)", alert_key, state, klass)
            else:
                log.warning("ops_alert: %s -> %s but Discord send failed", alert_key, state)
        return sent
    except Exception as e:   # alerting must never break the caller
        log.warning("ops_alert: report_ops_state(%s) failed: %s", alert_key, e)
        return False
