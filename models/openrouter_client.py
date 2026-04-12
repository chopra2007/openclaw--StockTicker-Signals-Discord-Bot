"""Shared OpenRouter client for text and vision calls."""

import logging
from typing import Any

import aiohttp

from . import model_config

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
