"""Chat-completion client with a per-model provider-routed fallback chain.

Single helper for every caller that reads ``llm.model`` or ``llm.text_model``
from config. Walks the chain (primary + configured fallbacks) and returns the
first successful response. Treats 408 / 429 / 5xx / timeouts AND non-429 4xx
errors as retryable — every failure falls through to the next model, since a
model-specific problem (bad id, context overflow) need not affect the others.
``groq/``-prefixed model ids route to Groq; every other id to OpenRouter.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.llm_client")

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

Role = Literal["primary", "text"]


def _chain(role: Role) -> list[str]:
    if role == "text":
        primary = cfg.get("llm.text_model", cfg.get("llm.model", ""))
        fallbacks = cfg.get("llm.text_fallback_models", []) or []
    else:
        primary = cfg.get("llm.model", "")
        fallbacks = cfg.get("llm.fallback_models", []) or []
    seen: set[str] = set()
    chain: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in seen:
            chain.append(model)
            seen.add(model)
    return chain


def _provider_for(model: str) -> str:
    """Map a chain model id to its provider: `groq/`-prefixed -> Groq, else OpenRouter."""
    return "groq" if model.startswith("groq/") else "openrouter"


def _endpoint_for(provider: str) -> str:
    """Chat-completions endpoint URL for a provider."""
    return _GROQ_API_URL if provider == "groq" else _API_URL


def _api_key_for(provider: str) -> str:
    """API key for a provider, resolved from config / environment."""
    return cfg.get_api_key("groq") if provider == "groq" else cfg.get_api_key("openrouter")


async def call_with_fallback(
    role: Role | None,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    timeout: int = 30,
    chain: list[str] | None = None,
) -> str:
    """Call the LLM provider(s), walking the configured fallback chain.

    Returns assistant content as a stripped string, or ``''`` if every model
    in the chain fails. Callers handle empty-string as the "LLM unavailable"
    signal — same contract as the inline code this replaces.

    Pass an explicit ``chain`` to bypass role-based config lookup (used by
    callers that have their own per-feature model chain, e.g. captions).
    """
    if chain is None:
        chain = _chain(role)  # type: ignore[arg-type]
    if not chain:
        log.error("LLM fallback chain is empty for role=%s", role)
        return ""

    for idx, model in enumerate(chain):
        # Per-model provider routing (#12): resolve the provider, endpoint,
        # key, and rate-limit bucket for THIS model. A `groq/`-prefixed id
        # goes to Groq; every other id to OpenRouter.
        provider = _provider_for(model)
        endpoint = _endpoint_for(provider)
        api_key = _api_key_for(provider)
        if not api_key:
            log.warning("LLM %s skipped — %s API key missing", model, provider)
            continue
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            # Wire id is unprefixed; the `groq/` tag is our routing marker only.
            "model": model[len("groq/"):] if provider == "groq" else model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Process-level rate limit, per provider bucket (D17 / S6). If the
        # bucket is in backoff, sleep briefly and retry once; if still
        # blocked, fall through to the next model in the chain.
        if not await rate_limiter.acquire(provider):
            await asyncio.sleep(0.5)
            if not await rate_limiter.acquire(provider):
                log.warning("LLM %s skipped — %s rate limiter blocked",
                            model, provider)
                continue
        try:
            session = await get_session()
            async with session.post(
                endpoint,
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
                # Non-429 4xx: the payload may be wrong for THIS model (bad
                # id, context overflow) but fine for another — try the next
                # model instead of aborting the whole chain.
                log.warning("LLM %s HTTP %d (trying next model): %.200s",
                            model, resp.status, body)
                continue
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            log.warning("LLM %s connection error (retryable): %r", model, exc)
            continue
        except Exception as exc:
            log.warning("LLM %s unexpected error: %s", model, exc)
            continue

    log.error("LLM fallback chain exhausted for role=%s (%d models tried)",
              role, len(chain))
    return ""
