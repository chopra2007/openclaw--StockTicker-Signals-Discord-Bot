"""Sanitize calls route OFF groq; only synthesis keeps the groq chain.

#6 root-cause fix. The !all sanitize phase (~9 cheap cleanup calls:
`_batch_summarize` per source batch + `vault_excerpt`) used to share the
groq-first `all_command_chain` with the synthesis call, burning groq's
100k/day free-tier budget so synthesis itself 429'd to the slow free models.
These tests pin the split: sanitize uses the groq-free
`all_command_sanitize_chain`; synthesis keeps `all_command_chain`.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.alerts.all_command import narrator


def _has_groq(chain) -> bool:
    return any("groq" in m for m in (chain or []))


def _capture_chain(coro_factory) -> dict:
    """Run an awaitable, capturing the `chain` kwarg passed to the LLM call."""
    captured: dict = {}

    async def fake_call(*, role, messages, chain=None, **_kw):
        captured["role"] = role
        captured["chain"] = chain
        return "1. summary text"

    with patch.object(narrator, "call_with_fallback", new=fake_call):
        asyncio.run(coro_factory())
    return captured


def test_batch_summarize_uses_groqless_sanitize_chain():
    cap = _capture_chain(lambda: narrator._batch_summarize(["some evidence text"]))
    assert cap["chain"] == narrator._sanitize_chain()
    assert not _has_groq(cap["chain"]), (
        f"_batch_summarize must not spend groq budget; got {cap['chain']}"
    )


def test_vault_excerpt_uses_groqless_sanitize_chain():
    cap = _capture_chain(lambda: narrator.vault_excerpt("a prior research note"))
    assert cap["chain"] == narrator._sanitize_chain()
    assert not _has_groq(cap["chain"]), (
        f"vault_excerpt must not spend groq budget; got {cap['chain']}"
    )


def test_synthesis_still_uses_groq_chain():
    cap = _capture_chain(
        lambda: narrator._invoke_synthesis([{"role": "user", "content": "x"}], 30)
    )
    assert cap["chain"] == narrator._all_command_chain()
    assert _has_groq(cap["chain"]), (
        "synthesis must keep the groq head-start chain; "
        f"got {cap['chain']}"
    )


def test_sanitize_chain_groqfree_under_real_config():
    """Integration check against the shipped config/consensus.yaml."""
    assert not _has_groq(narrator._sanitize_chain())
    assert _has_groq(narrator._all_command_chain())


def test_sanitize_chain_absent_key_falls_back_to_none():
    """No config key -> None -> call_with_fallback uses the role-based text
    chain (also groq-free). Confirms the default path is safe."""
    with patch.object(cfg, "get", return_value=None):
        assert narrator._sanitize_chain() is None
