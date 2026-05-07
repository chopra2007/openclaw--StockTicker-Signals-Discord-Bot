"""OpenRouter chat-completion client with a configured fallback chain.

Single helper for every caller that reads ``llm.model`` or ``llm.text_model``
from config. Walks the chain (primary + configured fallbacks) and returns the
first successful response. Treats 429 / 5xx / timeouts as retryable; treats
other 4xx as fatal (a malformed payload or auth issue would fail on every
model in the chain).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import aiohttp

from consensus_engine import config as cfg

log = logging.getLogger("consensus_engine.llm_client")

_API_URL = "https://openrouter.ai/api/v1/chat/completions"

Role = Literal["primary", "text"]


def _chain(role: Role) -> list[str]:
    if role == "text":
        primary = cfg.get("llm.text_model",
                          cfg.get("llm.model", "poolside/laguna-m.1:free"))
        fallbacks = cfg.get("llm.text_fallback_models", []) or []
    else:
        primary = cfg.get("llm.model", "poolside/laguna-m.1:free")
        fallbacks = cfg.get("llm.fallback_models", []) or []
    seen: set[str] = set()
    chain: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in seen:
            chain.append(model)
            seen.add(model)
    return chain


async def call_with_fallback(
    role: Role,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    timeout: int = 30,
) -> str:
    """Call OpenRouter, walking the configured fallback chain.

    Returns assistant content as a stripped string, or ``''`` if every model
    in the chain fails. Callers handle empty-string as the "LLM unavailable"
    signal — same contract as the inline code this replaces.
    """
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        log.warning("OpenRouter API key missing")
        return ""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    chain = _chain(role)
    if not chain:
        log.error("LLM fallback chain is empty for role=%s", role)
        return ""

    for idx, model in enumerate(chain):
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _API_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = (data.get("choices", [{}])[0]
                                       .get("message", {})
                                       .get("content") or "").strip()
                        if content:
                            if idx > 0:
                                log.info("LLM fallback hit %s (chain idx=%d, role=%s)",
                                         model, idx, role)
                            return content
                        log.warning("LLM %s returned empty content; trying next", model)
                        continue
                    body = await resp.text()
                    if resp.status in (408, 429) or 500 <= resp.status < 600:
                        log.warning("LLM %s HTTP %d (retryable): %.200s",
                                    model, resp.status, body)
                        continue
                    log.warning("LLM %s HTTP %d (fatal, aborting chain): %.200s",
                                model, resp.status, body)
                    return ""
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            log.warning("LLM %s connection error (retryable): %s", model, exc)
            continue
        except Exception as exc:
            log.warning("LLM %s unexpected error: %s", model, exc)
            continue

    log.error("LLM fallback chain exhausted for role=%s (%d models tried)",
              role, len(chain))
    return ""
