"""C2 (reliability-hardening): a canonical 3-state circuit breaker.

Replaces/backs the ad-hoc in-memory breakers (Brave HTTP-402 "open until
restart", Gemini per-key bench) with one breaker that:

  * is 3-state (closed -> open -> half_open) with fail_max / reset_timeout;
  * stores opened_at / next_probe_at as WALL-CLOCK UTC ``time.time()`` — NEVER
    ``time.monotonic()``. A monotonic opened_at compared against a persisted
    wall-clock value would never elapse after a restart -> stuck open forever.
    This is the #1 adversarial defeater for the run and is pinned by a test;
  * SELF-DRIVES recovery: every ``allow()`` re-checks the clock and grants a
    single half-open probe once the cooldown elapses, with NO external traffic
    needed, so a recovered source is never silently kept down;
  * probes immediately on restart if a persisted OPEN's cooldown already passed
    during downtime (half-open-on-restart);
  * persists ONLY durable conditions (quota / 402 / bench) so a transient blip
    is retried fresh after a restart (Gemini's point), while a known-exhausted
    source is not blindly re-hammered every restart;
  * is flag-gated default-OFF (``circuit_breaker.enabled``). When disabled it
    NEVER gates a call (signal-first) but still records transitions so we can
    shadow-log what it *would* do before flipping the gate on;
  * fails toward ALLOW on any DB error — a storage hiccup can never silently
    block a source.

Design note (deviation from the plan's literal text, chosen deliberately):
every OPEN — including durable quota/402 — re-probes within ``min(retry_after,
hard_max_open_s)`` rather than waiting out a multi-hour quota window. The run's
north star is availability, and the named #1 risk is *stuck-open*; bounding
every state to <= hard_max_open_s recovery is the safest choice. A re-probe of an
exhausted source is one cheap call that simply re-opens.

The breaker only ever makes a source *absent* for a cycle (``allow()`` False ->
caller skips it -> the aggregator already None-filters); it never raises into,
blocks, or delays the alert path.
"""
import logging
import time
from typing import Callable, Optional

from consensus_engine import config
from consensus_engine.utils.burst_retry import classify_retry, parse_retry_after, RetryClass

log = logging.getLogger("consensus_engine.circuit_breaker")

# C5: how long (seconds) to suppress a repeat ops alert for the same source so a
# flapping source can't spam the ops channel.
# #71: the alert throttle now lives in consensus_engine/alerts/ops_alert.py, which
# fires on state transitions and persists them. `last_alerted_at` is still tracked
# in _state so a flapping source's history stays inspectable via health_summary().
_OPS_ALERT_THROTTLE_S = 1800  # 30 min (retained: still read by the flap tests)

# Reasons whose OPEN survives a restart (real, durable limits). Everything else
# (transient 5xx/timeout, corroborated permanent) stays in-memory only.
DURABLE_REASONS = frozenset({"quota", "402", "bench"})


class CircuitBreaker:
    def __init__(self, *, now_fn: Callable[[], float] = time.time):
        self._now = now_fn
        self._state: dict[str, dict] = {}
        self._health: dict[str, dict] = {}  # C5: per-source counters
        self._loaded = False
        # Transient breaker state intentionally does not survive a restart, but
        # the matching #errors state does. Check each source once after boot so a
        # successful first call can clear an outage that ended during the restart.
        self._recovery_synced: set[str] = set()

    def _health_for(self, key: str) -> dict:
        return self._health.setdefault(
            key, {"attempts": 0, "skipped": 0, "failures": 0, "recoveries": 0})

    # ---- config (read live so a hot-reload of consensus.yaml takes effect) ----
    def _enabled(self) -> bool:
        return bool(config.get("circuit_breaker.enabled", False))

    def _fail_max(self) -> int:
        try:
            return max(1, int(config.get("circuit_breaker.fail_max", 5)))
        except (TypeError, ValueError):
            return 5

    def _reset_timeout(self) -> float:
        try:
            return float(config.get("circuit_breaker.reset_timeout_s", 120))
        except (TypeError, ValueError):
            return 120.0

    def _hard_max(self) -> float:
        try:
            return float(config.get("circuit_breaker.hard_max_open_s", 1800))
        except (TypeError, ValueError):
            return 1800.0

    @staticmethod
    def _key(source: str, cred_version: str) -> str:
        return f"{source}@{cred_version}"

    @staticmethod
    def _fresh() -> dict:
        return {"state": "closed", "failure_count": 0, "opened_at": None,
                "open_reason": None, "next_probe_at": None, "last_alerted_at": None}

    def _next_probe(self, now: float, retry_after: Optional[float]) -> float:
        base = retry_after if (retry_after and retry_after > 0) else self._reset_timeout()
        return now + min(base, self._hard_max())

    # ----------------------------- decision ---------------------------------
    def allow(self, source: str, cred_version: str = "v1") -> bool:
        """True if the call may proceed. Sync + pure in-memory (no DB on the hot
        path). When the flag is OFF, always True (shadow mode) but still logs a
        would-block so operators can see the breaker's behavior pre-flip."""
        key = self._key(source, cred_version)
        self._health_for(key)["attempts"] += 1
        decision = self._decide(source, cred_version)
        if not self._enabled():
            if not decision:
                log.debug("circuit_breaker[SHADOW] would block %s@%s", source, cred_version)
            return True
        if not decision:
            self._health_for(key)["skipped"] += 1
        return decision

    def _decide(self, source: str, cred_version: str) -> bool:
        key = self._key(source, cred_version)
        st = self._state.get(key)
        if st is None or st["state"] == "closed":
            return True
        now = self._now()
        opened_at = st["opened_at"] or now
        next_probe = st["next_probe_at"] or 0.0
        probe_due = now >= next_probe or (now - opened_at) >= self._hard_max()
        if probe_due:
            # grant exactly ONE probe; re-arm so a probe that never reports back
            # (caller crash) can't wedge the breaker in half_open forever.
            st["state"] = "half_open"
            st["next_probe_at"] = now + self._reset_timeout()
            log.info("circuit_breaker %s -> half_open (probe)", key)
            return True
        return False

    # ----------------------------- transitions ------------------------------
    async def record_failure(self, source: str, *, reason: str = "transient",
                             cred_version: str = "v1",
                             retry_after: Optional[float] = None,
                             immediate: bool = False) -> Optional[dict]:
        key = self._key(source, cred_version)
        now = self._now()
        st = self._state.setdefault(key, self._fresh())
        st["failure_count"] += 1
        self._health_for(key)["failures"] += 1
        prev = st["state"]

        if prev == "half_open":
            self._open(st, now, reason, retry_after)
            await self._persist_if_durable(key, st, reason)
            return {"key": key, "source": source, "from": "half_open", "to": "open",
                    "reason": reason, "failure_count": st["failure_count"]}

        if prev == "closed" and (immediate or st["failure_count"] >= self._fail_max()):
            self._open(st, now, reason, retry_after)
            await self._persist_if_durable(key, st, reason)
            return {"key": key, "source": source, "from": "closed", "to": "open",
                    "reason": reason, "failure_count": st["failure_count"]}

        return None  # still accumulating, or already open

    async def record_success(self, source: str, cred_version: str = "v1") -> Optional[dict]:
        key = self._key(source, cred_version)
        st = self._state.get(key)
        if st is None:
            return None
        prev = st["state"]
        # Preserve last_alerted_at across the reset so a flapping source
        # (open -> close -> open within the throttle window) can't re-alert.
        last_alerted = st.get("last_alerted_at")
        st.update(self._fresh())
        st["last_alerted_at"] = last_alerted
        if prev != "closed":
            self._health_for(key)["recoveries"] += 1
            await self._unpersist(key)
            log.info("circuit_breaker %s -> closed (recovered)", key)
            return {"key": key, "source": source, "from": prev, "to": "closed"}
        return None

    def _open(self, st: dict, now: float, reason: str, retry_after: Optional[float]) -> None:
        st["state"] = "open"
        st["opened_at"] = now
        st["open_reason"] = reason
        st["next_probe_at"] = self._next_probe(now, retry_after)
        log.warning("circuit_breaker OPEN (reason=%s, retry_after=%s)", reason, retry_after)

    # ----------------------------- persistence ------------------------------
    async def load_persisted(self) -> None:
        """Reload durable OPEN rows on startup. Fails toward a clean (closed)
        state so a DB error can never silently keep every source down."""
        from consensus_engine import db
        try:
            rows = await db.cb_load_open()
        except Exception as e:
            log.warning("circuit_breaker: could not load persisted state (%s) — clean start", e)
            return
        for r in rows:
            self._state[r["source_key"]] = {
                "state": "open",
                "failure_count": int(r.get("failure_count") or 0),
                "opened_at": r.get("opened_at"),
                "open_reason": r.get("open_reason"),
                "next_probe_at": r.get("next_probe_at"),
                "last_alerted_at": r.get("last_alerted_at"),
            }
        self._loaded = True
        if rows:
            log.info("circuit_breaker: reloaded %d persisted OPEN source(s)", len(rows))

    async def _persist_if_durable(self, key: str, st: dict, reason: str) -> None:
        # Only write the DB when the breaker is actually enabled — when OFF we
        # shadow-track in-memory only (no side effects beyond logging).
        if reason not in DURABLE_REASONS or not self._enabled():
            return
        from consensus_engine import db
        try:
            await db.cb_save({"source_key": key, **st})
        except Exception as e:
            log.warning("circuit_breaker: persist failed for %s: %s", key, e)

    async def _unpersist(self, key: str) -> None:
        if not self._enabled():
            return
        from consensus_engine import db
        try:
            await db.cb_delete(key)
        except Exception as e:
            log.warning("circuit_breaker: unpersist failed for %s: %s", key, e)

    # ----------------------------- C5: dead-source ladder -------------------
    async def note_failure(self, source: str, *, status: int | None = None,
                           body: str | None = None, exc: Exception | None = None,
                           cred_version: str = "v1") -> None:
        """Classify a failure, record it, and fire a throttled ops alert if the
        source just transitioned to OPEN. The reusable breaker entrypoint for
        every wired source (news cascade, Exa, ...)."""
        cls = classify_retry(http_status=status, body=body, exc=exc)
        if status == 402:
            reason = "402"
        elif cls is RetryClass.QUOTA_BLOCKED:
            reason = "quota"
        elif cls is RetryClass.PERMANENT:
            reason = "permanent"
        else:
            reason = "transient"
        immediate = reason in ("quota", "402")  # definitive -> open at once
        retry_after = parse_retry_after(body) if cls is RetryClass.QUOTA_BLOCKED else None
        event = await self.record_failure(
            source, reason=reason, immediate=immediate,
            retry_after=retry_after, cred_version=cred_version)
        await self.alert_if_opened(event)

    async def note_success(self, source: str, cred_version: str = "v1") -> None:
        key = self._key(source, cred_version)
        event = await self.record_success(source, cred_version)
        # A transient OPEN is memory-only, while report_ops_state persists its
        # DOWN row. After a process restart record_success() therefore sees no
        # local transition. Reconcile once per source after boot, then retain the
        # old zero-DB-read steady-state path. Real in-process recoveries still
        # reconcile immediately through `event`.
        if event or key not in self._recovery_synced:
            await self.alert_if_recovered(source)
            self._recovery_synced.add(key)

    async def alert_if_opened(self, event: Optional[dict]) -> None:
        """Send ONE #errors alert on a closed/half_open -> open transition.

        Flag-gated (dead_source.ops_alert_enabled). Never raises into the caller.

        #71: this used to resolve its channel from `discord.ops_channel_id`, falling
        back to `discord.channel_id` — NEITHER key has ever existed in
        config/consensus.yaml, so `channel` was always "" and the function returned
        before sending. This alert was dead from the day it shipped. It now goes
        through the shared #errors sender, which owns the fire-on-transition logic
        (and persists it, so an engine restart mid-outage doesn't re-alert).
        """
        if not event or event.get("to") != "open":
            return
        if not config.get("dead_source.ops_alert_enabled", False):
            return
        key = event["key"]
        st = self._state.get(key)
        if st is None:
            return
        st["last_alerted_at"] = self._now()
        if st.get("open_reason") in DURABLE_REASONS:
            await self._persist_if_durable(key, st, st["open_reason"])
        from consensus_engine.alerts.ops_alert import report_ops_state
        await report_ops_state(
            f"source:{event['source']}",
            down=True, failure_class="dead_source",
            title=f"Data source `{event['source']}` has stopped responding",
            detail=(f"It failed {event.get('failure_count', '?')} times in a row "
                    f"(reason: {event.get('reason', '?')}). The bot will skip it and "
                    f"keep quietly retrying until it comes back."),
            fix="Usually none — it recovers on its own. If this keeps happening, the "
                "source's API key or quota is the place to look.",
        )

    async def alert_if_recovered(self, source: str) -> None:
        """#71: post the 'source is back' follow-up so a dead-source @-mention never
        sits unanswered. Safe to call on every success — the shared sender stays
        silent unless the state actually changed."""
        if not config.get("dead_source.ops_alert_enabled", False):
            return
        from consensus_engine.alerts.ops_alert import report_ops_state
        await report_ops_state(
            f"source:{source}", down=False, failure_class="dead_source",
            title=f"Data source `{source}` is responding again",
        )

    def health_summary(self) -> str:
        """Compact per-source health line for periodic logging."""
        if not self._health:
            return "source-health: (none)"
        parts = []
        for key, h in sorted(self._health.items()):
            state = self._state.get(key, {}).get("state", "closed")
            parts.append(f"{key}[{state}] att={h['attempts']} skip={h['skipped']} "
                         f"fail={h['failures']} rec={h['recoveries']}")
        return "source-health: " + " | ".join(parts)


# Process-wide singleton.
circuit_breaker = CircuitBreaker()
