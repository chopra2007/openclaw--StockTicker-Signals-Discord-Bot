"""Daily health check for the LLM model chains configured in consensus.yaml.

Probes every model in both chains (primary + configured fallbacks for the
``llm.model`` and ``llm.text_model`` roles) once per day with a trivial
prompt. Posts a markdown summary to the configured Discord channel — by
default only when at least one model is unhealthy, so a green chain is
silent.

The point is to catch upstream rate-limiting, dropped model ids, or
provider outages before users notice them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine.alerts.discord import _safe_send_kwargs

_PT = ZoneInfo("America/Los_Angeles")  # Pacific — user's timezone; all user-facing health timestamps are PDT

_LLM_HEALTH_ALERT_TITLE = "One or more configured AI models failed a health check"
_LLM_HEALTH_ALERT_DETAIL = (
    "At least one configured model failed its daily test. Other models may still "
    "be working, so alerts can continue through the remaining chain. The full "
    "report in #errors shows exactly which model failed."
)

# Gateway agent config — read for drift detection against consensus.yaml.
# scripts/sync_gateway_models.py is the only thing that should write here.
# Use the real path, not the /root/.openclaw symlink: the engine runs as
# `openclaw` and cannot traverse /root.
_GATEWAY_CONFIG = Path("/home/openclaw/.openclaw/openclaw.json")

# Sticky marker so a boot that finds clean chains after a previous boot saw
# drift can emit a paired ✅ resolution message to Discord. Without this, a
# resolved drift leaves the channel reading as permanently broken.
_DRIFT_STATE_FILE = Path(__file__).resolve().parent.parent / ".drift_state.json"

log = logging.getLogger("consensus_engine.health")


def _enumerate_chain_models() -> list[tuple[str, str, str]]:
    """Return [(role_label, position, model_id), ...] for the LLM, TEXT, and
    ALL (!all-command) chains."""
    out: list[tuple[str, str, str]] = []
    primary_llm = cfg.get("llm.model", "")
    if primary_llm:
        out.append(("LLM", "primary", primary_llm))
    for i, m in enumerate(cfg.get("llm.fallback_models", []) or [], 1):
        if m:
            out.append(("LLM", f"fallback {i}", m))
    primary_text = cfg.get("llm.text_model", "")
    if primary_text:
        out.append(("TEXT", "primary", primary_text))
    for i, m in enumerate(cfg.get("llm.text_fallback_models", []) or [], 1):
        if m:
            out.append(("TEXT", f"fallback {i}", m))
    for i, m in enumerate(cfg.get("llm.all_command_chain", []) or []):
        if m:
            position = "primary" if i == 0 else f"fallback {i}"
            out.append(("ALL", position, m))
    return out


def _enumerate_gateway_chain_models() -> tuple[list[tuple[str, str, str]], str]:
    """Read the agent model chain from openclaw.json for drift detection.

    openclaw's ``openclaw agent`` failover walks ``agents.defaults.model`` —
    a ``{"primary": ..., "fallbacks": [...]}`` object. Strips the
    ``openrouter/`` prefix so ids match consensus.yaml shape (and so
    ``_probe_model`` hits the same OpenRouter endpoint). If the file is
    missing or unparseable, returns ``([], "<reason>")`` — the caller renders
    that as a ❌ row in the report so the failure surfaces in the same daily
    Discord alert as model outages.
    """
    try:
        if not _GATEWAY_CONFIG.exists():
            return [], f"missing: {_GATEWAY_CONFIG}"
        data = json.loads(_GATEWAY_CONFIG.read_text())
    except PermissionError as exc:
        # Treat an unreadable config as a reported ❌ row rather than
        # crashing the engine's health loop.
        return [], f"unreadable: {exc}"
    except Exception as exc:
        return [], f"unparseable: {type(exc).__name__}: {exc}"

    model_cfg = (data.get("agents", {})
                     .get("defaults", {})
                     .get("model", {}))
    if isinstance(model_cfg, str):
        chain = [model_cfg]
    elif isinstance(model_cfg, dict):
        primary = model_cfg.get("primary")
        chain = [primary, *(model_cfg.get("fallbacks") or [])] if primary else []
    else:
        chain = []
    out: list[tuple[str, str, str]] = []
    for i, raw_id in enumerate(m for m in chain if m):
        clean = raw_id[len("openrouter/"):] if raw_id.startswith("openrouter/") else raw_id
        position = "primary" if i == 0 else f"fallback {i}"
        out.append(("GATEWAY", position, clean))
    return out, ""


async def _probe_model(session: aiohttp.ClientSession,
                       model: str) -> tuple[str, float, str]:
    """Send a trivial completion request, routed to the model's provider.

    Returns (status_label, dt_seconds, detail). A `groq/`-prefixed id is
    probed against Groq; every other id against OpenRouter. Reports
    "KEY MISSING" without issuing a request when the provider key is absent.
    """
    from consensus_engine.llm_client import (
        _api_key_for, _endpoint_for, _provider_for,
    )
    provider = _provider_for(model)
    api_key = _api_key_for(provider)
    if not api_key:
        return "KEY MISSING", 0.0, f"{provider} API key not configured"
    payload = {
        "model": model[len("groq/"):] if provider == "groq" else model,
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "max_tokens": 200,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    t0 = time.time()
    try:
        async with session.post(
            _endpoint_for(provider), headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            dt = time.time() - t0
            if resp.status == 200:
                data = await resp.json()
                content = (data.get("choices", [{}])[0]
                              .get("message", {})
                              .get("content") or "").strip()
                if content:
                    return "OK", dt, content[:60].replace("\n", " ")
                return "EMPTY", dt, "200 with empty content"
            body = await resp.text()
            return f"HTTP {resp.status}", dt, body[:120].replace("\n", " ")
    except Exception as exc:
        return "ERR", time.time() - t0, f"{type(exc).__name__}: {exc}"[:120]


def _consensus_agent_chain() -> list[str]:
    """The agent-path chain from consensus.yaml — the sync source of truth."""
    chain: list[str] = []
    seen: set[str] = set()
    for m in [cfg.get("llm.agent_model", ""),
              *(cfg.get("llm.agent_fallback_models", []) or [])]:
        if m and m not in seen:
            chain.append(m)
            seen.add(m)
    return chain


def _compute_drift(gateway_models: list[tuple[str, str, str]]) -> str:
    """Return a one-line drift description, or "" if chains match.

    Compares consensus.yaml's agent chain (``llm.agent_model`` +
    ``llm.agent_fallback_models``) against the chain openclaw.json actually
    exposes at ``agents.defaults.model.{primary,fallbacks}``. Both should be
    identical ordered lists. Catches silent drift — e.g. an openclaw npm
    update overwriting openclaw.json — that per-model probing alone misses.
    """
    expected = _consensus_agent_chain()
    gw_chain = [m for _, _, m in gateway_models]
    if not expected or not gw_chain:
        return ""
    if expected == gw_chain:
        return ""
    return f"consensus={expected} vs gateway={gw_chain}"


async def run_chain_check() -> tuple[bool, str]:
    """Probe every model. Returns (any_failed, markdown_report).

    Each model is probed against its own provider with its own key, so a
    missing OpenRouter key no longer blanks the whole report — affected
    models report KEY MISSING individually.
    """
    models = _enumerate_chain_models()
    gateway_models, gateway_error = _enumerate_gateway_chain_models()
    drift_detail = _compute_drift(gateway_models)
    all_models = models + gateway_models

    if not all_models and not gateway_error:
        return True, "**LLM chain health:** no models configured."

    header = f"**LLM chain health — {datetime.now(tz=_PT).strftime('%Y-%m-%d %H:%M %Z')}**"
    lines = [header, ""]
    any_failed = False

    if gateway_error:
        lines.append(f"❌ `GATEWAY` `config` — {gateway_error}")
        any_failed = True
    if drift_detail:
        lines.append(f"❌ `GATEWAY` `drift` — {drift_detail[:140]}")
        any_failed = True

    session = await get_session()
    for role, position, model_id in all_models:
        status, dt, detail = await _probe_model(session, model_id)
        mark = "✅" if status == "OK" else "❌"
        if status != "OK":
            any_failed = True
        lines.append(
            f"{mark} `{role}` `{position}` `{model_id}` — {status} ({dt:.1f}s) — {detail[:60]}"
        )

    return any_failed, "\n".join(lines)


async def boot_drift_check() -> None:
    """One-shot drift check fired during engine startup.

    Runs the same string comparison as ``run_chain_check`` but skips the
    per-model LLM probes — boot is not the time to pay 9× 30-second timeouts.
    Posts a Discord alert immediately if the gateway chain has drifted from
    consensus.yaml. Bounds MTTD for the May 8 bug class from 24h (daily probe)
    down to "the time it takes the engine to start."

    Wrapped in a broad try/except: if anything goes wrong inside the check it
    must not take down the engine's asyncio.gather. We log the failure and
    return — the daily probe will surface the same drift independently.
    """
    try:
        if not cfg.get("health_check.enabled", True):
            return
        gateway_models, gateway_error = _enumerate_gateway_chain_models()
        drift_detail = _compute_drift(gateway_models)
        when = datetime.now(tz=_PT).strftime("%Y-%m-%d %H:%M %Z")

        if not gateway_error and not drift_detail:
            log.info("boot drift check: gateway chain matches consensus.yaml")
            prior = _read_drift_state()
            if prior:
                msg = (f"**✅ LLM chain drift resolved — {when}**\n\n"
                       f"Previous alert ({prior.get('first_seen','?')}) cleared. "
                       f"Gateway chain now matches consensus.yaml.")
                await _post_to_discord(msg)
                _clear_drift_state()
            return

        lines = [f"**LLM chain drift at boot — {when}**", ""]
        if gateway_error:
            lines.append(f"❌ `GATEWAY` `config` — {gateway_error}")
        if drift_detail:
            lines.append(f"❌ `GATEWAY` `drift` — {drift_detail[:140]}")
        lines.append("")
        lines.append("Run `make sync-models` to restore.")
        report = "\n".join(lines)
        log.warning("boot drift check FAILED:\n%s", report)
        await _post_to_discord(report)
        _write_drift_state(when, gateway_error, drift_detail)
    except Exception as exc:
        log.error("boot drift check crashed (continuing): %s", exc)


def _read_drift_state() -> dict | None:
    try:
        if _DRIFT_STATE_FILE.exists():
            return json.loads(_DRIFT_STATE_FILE.read_text())
    except Exception as exc:
        log.warning("drift state unreadable: %s", exc)
    return None


def _write_drift_state(when: str, gateway_error: str, drift_detail: str) -> None:
    try:
        existing = _read_drift_state() or {}
        first_seen = existing.get("first_seen") or when
        _DRIFT_STATE_FILE.write_text(json.dumps({
            "first_seen": first_seen,
            "last_seen": when,
            "gateway_error": gateway_error,
            "drift_detail": drift_detail,
        }))
    except Exception as exc:
        log.warning("drift state unwritable: %s", exc)


def _clear_drift_state() -> None:
    try:
        _DRIFT_STATE_FILE.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("drift state unclearable: %s", exc)


# --- Silent-outage alarm (item #5) ----------------------------------------
# A feed that has ingested nothing for too long (Gmail OAuth lapsed, YouTube
# chain dead) is silent — no error, just no new rows. Folded into the daily
# chain_health_loop pass so there is no second loop. Each feed has its own
# literal MAX-timestamp query (no generic table/column helper => no SQL
# injection surface) and a sticky per-feed state entry so we ping once per
# outage + once on recovery, not every day.

# Same dir as .drift_state.json. Keyed BY feed id: {"wolf": {...}, ...}.
_FEED_OUTAGE_STATE_FILE = Path(__file__).resolve().parent.parent / ".feed_outage_state.json"

# Default feed registry. The coordinator may add a health_check.feeds map to
# yaml; these literals are the OFF/safe defaults if it does not.
_DEFAULT_FEEDS = {
    "wolf": {"label": "Wolf email", "max_age_hours": 24,
             "auth_hint": " — check the Gmail auth gate (OAuth token may have lapsed)."},
    "youtube": {"label": "YouTube", "max_age_hours": 36,
                "auth_hint": " — check the YouTube caption/transcript chain."},
}

# Literal MAX(<ts>) queries, one per feed id. NOT built from config strings.
_FEED_MAX_TS_SQL = {
    "wolf": "SELECT MAX(received_at) FROM wolf_emails_processed",
    "youtube": "SELECT MAX(extracted_at) FROM youtube_signals",
}


def _read_feed_outage_state() -> dict:
    try:
        if _FEED_OUTAGE_STATE_FILE.exists():
            data = json.loads(_FEED_OUTAGE_STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception as exc:
        log.warning("feed outage state unreadable: %s", exc)
    return {}


def _write_feed_outage_state(state: dict) -> None:
    try:
        _FEED_OUTAGE_STATE_FILE.write_text(json.dumps(state))
    except Exception as exc:
        log.warning("feed outage state unwritable: %s", exc)


def _clear_feed_outage_state(feed_id: str) -> None:
    state = _read_feed_outage_state()
    if feed_id in state:
        state.pop(feed_id, None)
        _write_feed_outage_state(state)


async def _latest_feed_ts(feed_id: str) -> float | None:
    """Latest ingest timestamp (epoch seconds) for a feed, or None if the
    table is empty / never ingested. Uses a literal per-feed query."""
    import aiosqlite

    sql = _FEED_MAX_TS_SQL.get(feed_id)
    if not sql:
        return None
    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(sql) as cur:
                row = await cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as exc:
        log.warning("feed freshness: query for %s failed: %s", feed_id, exc)
    return None


def _errors_channel() -> str:
    """#71: the #errors room, or "" to fall back to the briefing channel."""
    try:
        from consensus_engine.alerts.ops_alert import errors_channel_id
        return errors_channel_id()
    except Exception:
        return ""


async def _check_feed_freshness() -> None:
    """Daily silent-outage check, called from chain_health_loop's daily pass.

    For each configured feed: read latest ingest ts via a literal query,
    compute age in hours. None (never ingested) is NOT armed => no alert.
    Fire ONE Discord ping per outage and ONE on recovery, deduped via the
    sticky per-feed state file.
    """
    feeds = cfg.get("health_check.feeds", _DEFAULT_FEEDS) or _DEFAULT_FEEDS
    state = _read_feed_outage_state()
    now = time.time()

    for feed_id, spec in feeds.items():
        if feed_id not in _FEED_MAX_TS_SQL:
            continue  # no literal query => unknown feed, skip (no injection)
        label = spec.get("label", feed_id)
        max_age = float(spec.get("max_age_hours", 24))
        auth_hint = spec.get("auth_hint", "")

        latest = await _latest_feed_ts(feed_id)
        already_alerted = feed_id in state

        if latest is None:
            # Never ingested anything — not armed; don't false-alarm a feed
            # that has simply never run. Leave any existing state untouched.
            continue

        age_hours = (now - latest) / 3600.0
        last_dt = datetime.fromtimestamp(latest, tz=_PT).strftime("%Y-%m-%d")

        if age_hours > max_age:
            if already_alerted:
                continue  # already pinged this outage; stay quiet
            days = age_hours / 24.0
            msg = (
                f"**⚠️ {label} feed silent — {datetime.now(tz=_PT).strftime('%Y-%m-%d %H:%M %Z')}**\n\n"
                f"No new {label} data in {days:.1f} days "
                f"(last ingest {last_dt}, threshold {max_age:.0f}h).{auth_hint}"
            )
            await _post_to_discord(msg, channel_id=_errors_channel())
            state[feed_id] = {"first_seen": datetime.now(tz=_PT).strftime("%Y-%m-%d %H:%M %Z"),
                              "last_ingest": last_dt}
            _write_feed_outage_state(state)
        else:
            if already_alerted:
                msg = (
                    f"**✅ {label} feed recovered — {datetime.now(tz=_PT).strftime('%Y-%m-%d %H:%M %Z')}**\n\n"
                    f"New {label} data ingested again (last ingest {last_dt})."
                )
                await _post_to_discord(msg, channel_id=_errors_channel())
                _clear_feed_outage_state(feed_id)


async def _post_to_discord(content: str, channel_id: str | None = None) -> None:
    """Post a health message. Defaults to the briefing channel.

    #71: outage-class messages (a feed gone silent) pass the #errors channel instead,
    so 'something is broken' and 'here is your daily report' stop sharing a room.
    """
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(channel_id or "") or str(
        cfg.get("health_check.channel_id", "")
        or cfg.get("alfred.channel_id", "")
        or cfg.get("api_keys.discord_briefing_channel_id", "")
        or ""
    )
    if not token or not channel_id:
        log.warning("health: missing bot token or channel id; skipping Discord post")
        return
    if getattr(cfg, "dry_run", False):
        log.info("[DRY-RUN] health would post: %.120s", content)
        return
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = _safe_send_kwargs({"content": content[:1990]})
    try:
        session = await get_session()
        async with session.post(
            url,
            headers={"Authorization": f"Bot {token}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status not in (200, 201):
                log.warning("health: Discord post HTTP %d", resp.status)
    except Exception as exc:
        log.warning("health: Discord post error: %s", exc)


def _seconds_until_next(hh: int, mm: int) -> float:
    now = datetime.now(tz=_PT)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def chain_health_loop(stop_event: asyncio.Event) -> None:
    """Run the chain check once per day at the configured PDT time."""
    if not cfg.get("health_check.enabled", True):
        log.info("health: disabled in config; loop exiting")
        return
    daily = str(cfg.get("health_check.daily_time_pdt", "17:30") or "17:30")
    try:
        hh, mm = (int(x) for x in daily.split(":", 1))
    except Exception:
        log.warning("health: invalid daily_time_pdt=%r; using 17:30", daily)
        hh, mm = 17, 30
    alert_only = bool(cfg.get("health_check.alert_only_on_failure", True))

    log.info("health: chain check enabled, fires daily at %02d:%02d PDT (alert_only=%s)",
             hh, mm, alert_only)

    while not stop_event.is_set():
        wait_s = _seconds_until_next(hh, mm)
        log.info("health: next chain check in %.1f minutes", wait_s / 60)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_s)
            return
        except asyncio.TimeoutError:
            pass

        try:
            failed, report = await run_chain_check()
            log.info("health: chain check %s\n%s",
                     "FAILED" if failed else "OK", report)
            if failed or not alert_only:
                # 2026-07-10 (user): LLM chain-health reports belong in #errors, not
                # the #brief channel. Falls back to briefing if #errors is unavailable.
                await _post_to_discord(report, channel_id=_errors_channel())
            # Track a red daily probe as one transition-based ops event. A single
            # failed fallback does not mean the entire chain is unavailable; the
            # full report above shows the exact working and failed models.
            from consensus_engine.alerts.ops_alert import report_ops_state
            await report_ops_state(
                "llm_health", down=bool(failed), failure_class="llm_health",
                title=_LLM_HEALTH_ALERT_TITLE,
                detail=_LLM_HEALTH_ALERT_DETAIL,
                fix=("Read the failed line in the report. Check that model's provider "
                     "only if it stays red on the next daily test."),
            )
        except Exception as exc:
            log.error("health: chain check error: %s", exc)

        # Silent-outage alarm (item #5): same daily pass, no new loop.
        try:
            await _check_feed_freshness()
        except Exception as exc:
            log.error("health: feed freshness check error: %s", exc)
