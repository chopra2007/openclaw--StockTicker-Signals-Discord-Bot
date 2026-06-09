"""Shared OpenRouter client for text and vision calls."""

import logging
from typing import Any

import aiohttp

from . import model_config

# Cross-package import to share the consensus_engine process-level rate
# limiter (D17 / S6). Wrapped in try/except so models/ remains importable in
# isolation if the consensus_engine package is unavailable.
try:
    from consensus_engine.utils.rate_limiter import rate_limiter as _rate_limiter
except ImportError:  # pragma: no cover - standalone-use fallback
    _rate_limiter = None

log = logging.getLogger("models.openrouter")


async def chat_completion(model: str, messages: list[dict[str, Any]], *, max_tokens: int = 2048, temperature: float = 0.1) -> str:
    """Run a chat completion call against OpenRouter."""
    if not model_config.OPENROUTER_API_KEY:
        return ""

    headers = {
        "Authorization": f"Bearer {model_config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # Acquire openrouter token before posting (60 req/min process-level cap).
    if _rate_limiter is not None:
        if not await _rate_limiter.acquire("openrouter"):
            log.warning("OpenRouter rate-limited (backoff active); skipping call")
            return ""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                model_config.OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=model_config.MODEL_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    log.warning("OpenRouter error (%d)", resp.status)
                    return ""
                data = await resp.json()
        return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception as e:
        log.warning("OpenRouter request failed: %s", e)
        return ""


async def vision_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> tuple[str, int | None, str | None]:
    """Like chat_completion but returns (content, http_status, raw_body) instead of
    swallowing the status — so the vision caller can classify 429 vs 502 vs empty and
    retry/rotate (item A, deep-dive-2026-06-08). Does NOT touch chat_completion (an
    engine-wide tripwire). http_status is None on a transport exception (treat as TRANSIENT).

    Never silently drops on a limiter backoff: when the process rate-limiter is backed off,
    it WAITS and retries rather than returning an empty final (vision must never abandon a
    chart on a transient limiter state)."""
    if not model_config.OPENROUTER_API_KEY:
        return ("", None, "no_api_key")

    headers = {
        "Authorization": f"Bearer {model_config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # Wait for a limiter token (don't drop the chart). Bounded so a wedged limiter can't
    # hang the per-email loop forever — the caller's per-chart wall-clock budget is the
    # outer bound; here we just avoid an instant empty-return.
    if _rate_limiter is not None:
        import asyncio
        for _ in range(20):  # up to ~20s waiting on the limiter
            if await _rate_limiter.acquire("openrouter"):
                break
            await asyncio.sleep(1.0)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                model_config.OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=model_config.MODEL_TIMEOUT_SECONDS),
            ) as resp:
                status = resp.status
                body = await resp.text()
                if status != 200:
                    log.warning("OpenRouter vision error (%d) model=%s", status, model)
                    return ("", status, body)
                try:
                    data = await resp.json()
                except Exception:
                    import json as _json
                    data = _json.loads(body) if body else {}
        content = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return (content, 200, body)
    except Exception as e:
        log.warning("OpenRouter vision request failed model=%s: %s", model, e)
        return ("", None, str(e))
