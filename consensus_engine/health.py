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
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

from consensus_engine import config as cfg

_ET = ZoneInfo("America/New_York")
_API_URL = "https://openrouter.ai/api/v1/chat/completions"

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
            _API_URL, headers=headers, json=payload,
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


async def run_chain_check() -> tuple[bool, str]:
    """Probe every model. Returns (any_failed, markdown_report)."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return True, "**LLM chain health:** OpenRouter API key missing — cannot probe."

    models = _enumerate_chain_models()
    if not models:
        return True, "**LLM chain health:** no models configured."

    header = f"**LLM chain health — {datetime.now(tz=_ET).strftime('%Y-%m-%d %H:%M ET')}**"
    lines = [header, ""]
    any_failed = False

    async with aiohttp.ClientSession() as session:
        for role, position, model_id in models:
            status, dt, detail = await _probe_model(session, model_id, api_key)
            mark = "✅" if status == "OK" else "❌"
            if status != "OK":
                any_failed = True
            lines.append(
                f"{mark} `{role}` `{position}` `{model_id}` — {status} ({dt:.1f}s) — {detail[:60]}"
            )

    return any_failed, "\n".join(lines)


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
    payload = {"content": content[:1990]}
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
