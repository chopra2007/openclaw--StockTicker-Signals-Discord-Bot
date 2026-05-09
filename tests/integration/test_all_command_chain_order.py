"""PR1 — LLM chain order: ring-2.6-1t is PRIMARY (latency-budget realism).

R8 measured: gpt-oss-120b 78.7s (Gemini-tier quality) vs ring-2.6-1t 14.0s
(Gemini-tier quality). Putting the fast one first means the synthesis call
completes inside the 50s cap on the common path; gpt-oss-120b becomes
FALLBACK 1 for runs where ring exceeds 14s.
"""
from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus.yaml"


def _llm_block() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text()).get("llm", {})


def test_primary_model_is_ring():
    """ring-2.6-1t must be the PRIMARY model (was: gpt-oss-120b)."""
    llm = _llm_block()
    assert llm.get("model") == "inclusionai/ring-2.6-1t:free", (
        f"llm.model={llm.get('model')!r}; expected inclusionai/ring-2.6-1t:free "
        "(R8: 14s vs gpt-oss-120b 78.7s)"
    )


def test_text_primary_model_is_ring():
    """text_model mirrors model — same latency reasoning applies."""
    llm = _llm_block()
    assert llm.get("text_model") == "inclusionai/ring-2.6-1t:free"


def test_gpt_oss_remains_in_fallback_chain():
    """Chain reorder must not lose access to gpt-oss-120b's quality."""
    llm = _llm_block()
    assert "openai/gpt-oss-120b:free" in llm.get("fallback_models", [])
    assert "openai/gpt-oss-120b:free" in llm.get("text_fallback_models", [])
