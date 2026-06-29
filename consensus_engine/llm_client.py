"""Chat-completion client with a per-model provider-routed fallback chain.

Single helper for every caller that reads ``llm.model`` or ``llm.text_model``
from config. Walks the chain (primary + configured fallbacks) and returns the
first successful response. Treats 408 / 429 / 5xx / timeouts AND non-429 4xx
errors as retryable — every failure falls through to the next model, since a
model-specific problem (bad id, context overflow) need not affect the others.
``groq/``-prefixed model ids route to Groq; every other id to OpenRouter.

The default ``serial`` strategy is the original one-model-at-a-time walk. The
``!all`` synthesis call opts into ``head_start`` (#6 latency-speedup): groq gets
a short solo head-start and the fallback models are raced only if it stalls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Literal

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.utils.burst_retry import classify_retry, parse_retry_after, RetryClass

log = logging.getLogger("consensus_engine.llm_client")


def _note_llm_retry(provider: str, status: int, body: str | None, headers) -> None:
    """C3: when an LLM HTTP failure is a QUOTA block AND the server gave a
    Retry-After, pace that provider bucket for the (capped) hint so the bot
    stops hammering a hard-429ing provider. Flag-gated (retry.use_classifier,
    default OFF); a hint-less 429 is a deliberate no-op so we never introduce
    LLM-bucket backoff without an explicit server signal. The cap
    (retry.llm_retry_after_cap_s, 120) prevents a per-day 86399s hint from
    blocking the LLM bucket for hours — the blank-thesis amplifier."""
    if not cfg.get("retry.use_classifier", False):
        return
    if classify_retry(http_status=status, body=body) is not RetryClass.QUOTA_BLOCKED:
        return
    text = body or ""
    if headers is not None and hasattr(headers, "get"):
        ra = headers.get("Retry-After")
        if ra:
            text = f"{text} Retry-After: {ra}"
    parsed = parse_retry_after(text)
    if not parsed:
        return  # no server hint -> preserve current no-backoff behavior
    cap = float(cfg.get("retry.llm_retry_after_cap_s", 120))
    rate_limiter.report_failure(provider, retry_after=min(parsed, cap))
    log.info("LLM %s QUOTA — pacing bucket %.0fs (capped)", provider, min(parsed, cap))

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

Role = Literal["primary", "text"]

# --- !all synthesis latency (#6): groq head-start circuit breaker ----------
# When groq (chain[0]) repeatedly stalls, stop paying the head-start wait on
# every call: open the breaker and race the whole chain straight away until it
# cools off, then allow one half-open groq probe (the next non-open call).
_BREAKER_COOLDOWN = 120.0  # seconds the breaker stays open after it trips
_groq_breaker_open_until: float = 0.0
_groq_fail_streak: int = 0


def _breaker_is_open() -> bool:
    return time.monotonic() < _groq_breaker_open_until


def _reset_groq_breaker() -> None:
    global _groq_fail_streak, _groq_breaker_open_until
    _groq_fail_streak = 0
    _groq_breaker_open_until = 0.0


def _record_groq_stall(threshold: int) -> None:
    global _groq_fail_streak, _groq_breaker_open_until
    _groq_fail_streak += 1
    if threshold > 0 and _groq_fail_streak >= threshold:
        _groq_breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN
        log.warning(
            "LLM groq circuit-breaker OPEN for %.0fs (%d consecutive stalls)",
            _BREAKER_COOLDOWN, _groq_fail_streak,
        )


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


async def _try_model(
    model: str,
    *,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> str | None:
    """One model attempt. Returns stripped content on success, ``None`` on any
    failure (missing key, rate-limit block, HTTP error, timeout, empty body).

    Deliberately does NOT catch ``asyncio.CancelledError``: a race loser must
    tear down cleanly, and callers absorb the cancellation via
    ``gather(return_exceptions=True)``. (In Python 3.8+ ``CancelledError`` is a
    ``BaseException``, so the ``except Exception`` below never swallows it.)
    """
    provider = _provider_for(model)
    endpoint = _endpoint_for(provider)
    api_key = _api_key_for(provider)
    if not api_key:
        log.warning("LLM %s skipped — %s API key missing", model, provider)
        return None
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
    # Process-level rate limit, per provider bucket (D17 / S6). If the bucket
    # is in backoff, sleep briefly and retry once; if still blocked, give up
    # on this model (the next model in the chain is tried).
    if not await rate_limiter.acquire(provider):
        await asyncio.sleep(0.5)
        if not await rate_limiter.acquire(provider):
            log.warning("LLM %s skipped — %s rate limiter blocked",
                        model, provider)
            return None
    try:
        session = await get_session()
        async with session.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 200:
                if cfg.get("retry.use_classifier", False):
                    rate_limiter.report_success(provider)  # C3: clear any pacing
                data = await resp.json()
                content = (data.get("choices", [{}])[0]
                               .get("message", {})
                               .get("content") or "").strip()
                if content:
                    return content
                log.warning("LLM %s returned empty content; trying next", model)
                return None
            body = await resp.text()
            if resp.status in (408, 429) or 500 <= resp.status < 600:
                _note_llm_retry(provider, resp.status, body, getattr(resp, "headers", None))  # C3
                log.warning("LLM %s HTTP %d (retryable): %.200s",
                            model, resp.status, body)
                return None
            # Non-429 4xx: the payload may be wrong for THIS model (bad id,
            # context overflow) but fine for another — try the next model
            # instead of aborting the whole chain.
            log.warning("LLM %s HTTP %d (trying next model): %.200s",
                        model, resp.status, body)
            return None
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        log.warning("LLM %s connection error (retryable): %r", model, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM %s unexpected error: %s", model, exc)
        return None


async def _serial(
    chain: list[str],
    role: Role | None,
    *,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> str:
    """Original behavior: walk the chain one model at a time, first success
    wins. Behaviorally identical to the pre-#6 inline loop — the dark-ship
    default so nothing changes until the !all flag is flipped."""
    for idx, model in enumerate(chain):
        content = await _try_model(
            model, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout,
        )
        if content:
            if idx > 0:
                log.info("LLM fallback hit %s (chain idx=%d, role=%s)",
                         model, idx, role)
            return content
    log.error("LLM fallback chain exhausted for role=%s (%d models tried)",
              role, len(chain))
    return ""


async def _race(
    models: list[str],
    role: Role | None,
    *,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
    accept: Callable[[str], bool] | None,
) -> str:
    """Fire all ``models`` concurrently; return the first response that is
    non-empty AND passes ``accept`` (then cancel the rest). If none pass
    ``accept``, fall back to the first non-empty response seen; else ``''``.

    A fast FAILURE never wins, and a fast-but-structurally-incomplete answer
    never beats a slower valid one — this preserves quality parity in the tail.
    """
    tasks = [
        asyncio.create_task(_try_model(
            m, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout))
        for m in models
    ]
    first_nonempty = ""
    winner = ""
    try:
        for fut in asyncio.as_completed(tasks):
            content = await fut
            if not content:
                continue
            if not first_nonempty:
                first_nonempty = content
            if accept is None or accept(content):
                winner = content
                break
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        # Absorb the cancelled losers' CancelledError without noise.
        await asyncio.gather(*tasks, return_exceptions=True)
    result = winner or first_nonempty
    if result:
        log.info("LLM race resolved (role=%s, models=%d, structurally_valid=%s)",
                 role, len(models), bool(winner))
    return result


async def _head_start(
    chain: list[str],
    role: Role | None,
    *,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
    window: float,
    accept: Callable[[str], bool] | None,
    breaker_threshold: int,
) -> str:
    """Give chain[0] (groq) a short solo head-start; only if it stalls, race
    the remaining models concurrently and take the first valid answer. When the
    groq breaker is open, skip the wait and race the whole chain immediately."""
    if len(chain) <= 1:
        return await _serial(
            chain, role, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout)

    if not _breaker_is_open():
        head = chain[0]
        head_timeout = max(1, min(int(window), timeout))
        content = await _try_model(
            head, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=head_timeout)
        if content:
            _reset_groq_breaker()
            return content
        _record_groq_stall(breaker_threshold)
        log.info("LLM head-start: %s stalled within %ds — fanning out to %d fallback(s)",
                 head, head_timeout, len(chain) - 1)
        race_models = chain[1:]
    else:
        log.info("LLM head-start: groq breaker open — racing all %d models",
                 len(chain))
        race_models = chain

    won = await _race(
        race_models, role, messages=messages, max_tokens=max_tokens,
        temperature=temperature, timeout=timeout, accept=accept)
    if won:
        return won
    log.error("LLM fallback chain exhausted for role=%s (%d models tried)",
              role, len(chain))
    return ""


async def call_with_fallback(
    role: Role | None,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    timeout: int = 30,
    chain: list[str] | None = None,
    strategy: str = "serial",
    head_start: float = 15.0,
    accept: Callable[[str], bool] | None = None,
) -> str:
    """Call the LLM provider(s), walking the configured fallback chain.

    Returns assistant content as a stripped string, or ``''`` if every model
    in the chain fails. Callers handle empty-string as the "LLM unavailable"
    signal — same contract as the inline code this replaces.

    Pass an explicit ``chain`` to bypass role-based config lookup (used by
    callers that have their own per-feature model chain, e.g. captions).

    ``strategy`` (default ``"serial"`` — unchanged behavior) selects how the
    chain is walked. ``"head_start"`` and ``"race_all"`` are opt-in per call
    (currently only the !all synthesis); ``accept`` rejects a structurally
    incomplete race winner so the tail keeps quality parity. See #6.
    """
    if chain is None:
        chain = _chain(role)  # type: ignore[arg-type]
    if not chain:
        log.error("LLM fallback chain is empty for role=%s", role)
        return ""

    if strategy == "head_start":
        threshold = int(cfg.get("llm.all_command_circuit_breaker_threshold", 3))
        return await _head_start(
            chain, role, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout, window=head_start,
            accept=accept, breaker_threshold=threshold)
    if strategy == "race_all":
        won = await _race(
            chain, role, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout, accept=accept)
        if won:
            return won
        log.error("LLM fallback chain exhausted for role=%s (%d models tried)",
                  role, len(chain))
        return ""
    return await _serial(
        chain, role, messages=messages, max_tokens=max_tokens,
        temperature=temperature, timeout=timeout)
