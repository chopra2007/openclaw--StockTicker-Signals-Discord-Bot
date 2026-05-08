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
