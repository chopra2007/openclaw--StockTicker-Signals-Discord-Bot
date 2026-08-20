"""Groq's TPM cap bills prompt + reserved output, so an oversized !all synthesis
request 413s whichever way it is sent — skipping only the head-start *window*
still let race_all fire a guaranteed-failing groq call (and trip a ~54s backoff
on the shared 'groq' source the llm_scorer C4 fallback depends on).

The gate must therefore drop groq models from the chain entirely when the
estimated request exceeds the cap, and leave the chain untouched when it fits.
"""
import pytest

from consensus_engine.alerts.all_command import narrator

CHAIN = ["groq/openai/gpt-oss-120b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def _setup(monkeypatch, *, prompt_chars):
    captured = {}

    async def fake_cwf(**kw):
        captured.update(kw)
        return "narrative"

    monkeypatch.setattr(narrator, "call_with_fallback", fake_cwf)
    monkeypatch.setattr(narrator, "_all_command_chain", lambda: list(CHAIN))

    from consensus_engine import config as cfg
    real = cfg.get
    cfgmap = {
        "llm.all_command_strategy": "head_start",
        "llm.all_command_chain": list(CHAIN),
        "llm.all_command_synthesis_max_tokens": 4000,
        "llm.all_command_head_start_max_tokens": 8000,
        "llm.all_command_head_start_timeout": 15,
    }
    monkeypatch.setattr(cfg, "get", lambda k, d=None: cfgmap.get(k, real(k, d)))
    messages = [{"role": "user", "content": "x" * prompt_chars}]
    return captured, messages


async def test_oversized_request_drops_groq_from_chain(monkeypatch):
    # ~5000 prompt tokens + 4000 reserved = 9000 > the 8000 cap.
    captured, messages = _setup(monkeypatch, prompt_chars=21000)

    assert await narrator._invoke_synthesis(messages, 60.0) == "narrative"

    assert captured["strategy"] == "race_all"
    assert captured["chain"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], (
        "a request over groq's TPM cap must not be sent to groq at all"
    )


async def test_small_request_keeps_groq_head_start(monkeypatch):
    # ~500 prompt tokens + 4000 reserved = 4500 < the 8000 cap.
    captured, messages = _setup(monkeypatch, prompt_chars=3000)

    assert await narrator._invoke_synthesis(messages, 60.0) == "narrative"

    assert captured["strategy"] == "head_start"
    assert captured["chain"] == CHAIN, "an in-budget request keeps groq first"
