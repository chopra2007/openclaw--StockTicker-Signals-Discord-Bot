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
from consensus_engine.alerts.discord import _safe_send_kwargs

_ET = ZoneInfo("America/New_York")
_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Gateway agent config — read for drift detection against consensus.yaml.
# scripts/sync_gateway_models.py is the only thing that should write here.
_GATEWAY_CONFIG = Path("/root/.openclaw/openclaw.json")

log = logging.getLogger("consensus_engine.health")


def _enumerate_chain_models() -> list[tuple[str, str, str]]:
    """Return [(role_label, position, model_id), ...] for both chains."""
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
    return out


def _enumerate_gateway_chain_models() -> tuple[list[tuple[str, str, str]], str]:
    """Read the gateway model chain from openclaw.json for drift detection.

    Strips the ``openrouter/`` prefix so model ids match consensus.yaml shape
    (and so ``_probe_model`` hits the same OpenRouter endpoint). If the file is
    missing or unparseable, returns ``([], "<reason>")`` — the caller renders
    that as a ❌ row in the report so the failure surfaces in the same daily
    Discord alert as model outages.
    """
    if not _GATEWAY_CONFIG.exists():
        return [], f"missing: {_GATEWAY_CONFIG}"
    try:
        data = json.loads(_GATEWAY_CONFIG.read_text())
    except Exception as exc:
        return [], f"unparseable: {type(exc).__name__}: {exc}"

    models = (data.get("agents", {})
                  .get("defaults", {})
                  .get("models", {})
                  .get("openrouter/auto", {})
                  .get("params", {})
                  .get("models", [])) or []
    out: list[tuple[str, str, str]] = []
    for i, raw_id in enumerate(models):
        clean = raw_id[len("openrouter/"):] if raw_id.startswith("openrouter/") else raw_id
        position = "primary" if i == 0 else f"fallback {i}"
        out.append(("GATEWAY", position, clean))
    return out, ""


async def _probe_model(session: aiohttp.ClientSession,
                       model: str,
                       api_key: str) -> tuple[str, float, str]:
    """Send a trivial completion request. Returns (status_label, dt_seconds, detail)."""
    payload = {
        "model": model,
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
            _API_URL, headers=headers, json=_safe_send_kwargs(payload),
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


def _compute_drift(models: list[tuple[str, str, str]],
                   gateway_models: list[tuple[str, str, str]]) -> str:
    """Return a one-line drift description, or "" if chains match.

    Compares consensus.yaml's LLM chain (primary + fallbacks) against the
    gateway's resolved chain. Both should be identical ordered lists of model
    ids. This catches silent drift where both chains point to *alive* but
    *different* models — a failure mode per-model probing alone misses.
    """
    llm_chain = [m for r, _, m in models if r == "LLM"]
    gw_chain = [m for _, _, m in gateway_models]
    if not llm_chain or not gw_chain:
        return ""
    if llm_chain == gw_chain:
        return ""
    return f"consensus={llm_chain} vs gateway={gw_chain}"


async def run_chain_check() -> tuple[bool, str]:
    """Probe every model. Returns (any_failed, markdown_report)."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return True, "**LLM chain health:** OpenRouter API key missing — cannot probe."

    models = _enumerate_chain_models()
    gateway_models, gateway_error = _enumerate_gateway_chain_models()
    drift_detail = _compute_drift(models, gateway_models)
    all_models = models + gateway_models

    if not all_models and not gateway_error:
        return True, "**LLM chain health:** no models configured."

    header = f"**LLM chain health — {datetime.now(tz=_ET).strftime('%Y-%m-%d %H:%M ET')}**"
    lines = [header, ""]
    any_failed = False

    if gateway_error:
        lines.append(f"❌ `GATEWAY` `config` — {gateway_error}")
        any_failed = True
    if drift_detail:
        lines.append(f"❌ `GATEWAY` `drift` — {drift_detail[:140]}")
        any_failed = True

    async with aiohttp.ClientSession() as session:
        for role, position, model_id in all_models:
            status, dt, detail = await _probe_model(session, model_id, api_key)
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
    """
    if not cfg.get("health_check.enabled", True):
        return
    models = _enumerate_chain_models()
    gateway_models, gateway_error = _enumerate_gateway_chain_models()
    drift_detail = _compute_drift(models, gateway_models)
    if not gateway_error and not drift_detail:
        log.info("boot drift check: gateway chain matches consensus.yaml")
        return

    when = datetime.now(tz=_ET).strftime("%Y-%m-%d %H:%M ET")
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


async def _post_to_discord(content: str) -> None:
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(
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
        async with aiohttp.ClientSession() as session:
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
    now = datetime.now(tz=_ET)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def chain_health_loop(stop_event: asyncio.Event) -> None:
    """Run the chain check once per day at the configured ET time."""
    if not cfg.get("health_check.enabled", True):
        log.info("health: disabled in config; loop exiting")
        return
    daily = str(cfg.get("health_check.daily_time_et", "08:30") or "08:30")
    try:
        hh, mm = (int(x) for x in daily.split(":", 1))
    except Exception:
        log.warning("health: invalid daily_time_et=%r; using 08:30", daily)
        hh, mm = 8, 30
    alert_only = bool(cfg.get("health_check.alert_only_on_failure", True))

    log.info("health: chain check enabled, fires daily at %02d:%02d ET (alert_only=%s)",
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
                await _post_to_discord(report)
        except Exception as exc:
            log.error("health: chain check error: %s", exc)
