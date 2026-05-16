"""LLM chain-order regression test (updated 2026-05-16, TODO #7).

History:
  - PR1 (2026-05-08): ring-2.6-1t pinned as PRIMARY (R8: 14s vs gpt-oss-120b 78.7s).
  - TODO #5 (2026-05-15, commit 732dba6): ring-2.6-1t delisted from OpenRouter
    free tier → promoted gpt-oss-120b to PRIMARY, shipped 5-model chain
    (gpt-oss-120b, glm-4.5-air, deepseek-v4-flash, trinity-large-thinking, cobuddy).
  - TODO #7 (2026-05-16): isolation test showed positions 2-4 fail !all parallel
    load → replaced with gpt-oss-20b + 2 nemotron-30b variants; glm-4.5-air
    demoted to last-resort. Methodology + raw data in
    .omc/research/llm-chain-2026-05-16/RESULTS.md.

This test enforces the post-TODO-#7 chain. If you change the chain (any of
model, fallback_models, text_model, text_fallback_models) re-run the
isolation harness at .omc/research/llm-chain-2026-05-16/probe_llm_chain.py
+ live_test_all.py before updating these assertions.
"""
from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus.yaml"

EXPECTED_PRIMARY = "openai/gpt-oss-120b:free"
EXPECTED_FALLBACKS = [
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "z-ai/glm-4.5-air:free",
]


def _llm_block() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text()).get("llm", {})


def test_primary_model_is_gpt_oss_120b():
    """gpt-oss-120b must be PRIMARY (proven baseline, 3/3 parallel-load test)."""
    llm = _llm_block()
    assert llm.get("model") == EXPECTED_PRIMARY, (
        f"llm.model={llm.get('model')!r}; expected {EXPECTED_PRIMARY}"
    )


def test_text_primary_mirrors_primary():
    """text_model mirrors model — both roles share the same chain."""
    llm = _llm_block()
    assert llm.get("text_model") == EXPECTED_PRIMARY


def test_fallback_chain_matches_expected_order():
    """Fallback order must match the 2026-05-16 re-selection ranking
    (RESULTS.md). Order matters: chain walks first-to-last on retryable errors."""
    llm = _llm_block()
    assert llm.get("fallback_models") == EXPECTED_FALLBACKS, (
        f"got {llm.get('fallback_models')!r}; expected {EXPECTED_FALLBACKS!r}"
    )
    assert llm.get("text_fallback_models") == EXPECTED_FALLBACKS, (
        "text_fallback_models drifted from fallback_models"
    )


def test_no_known_failed_models_in_chain():
    """Defense-in-depth: models that failed !all isolation must not reappear."""
    llm = _llm_block()
    chain = [llm.get("model")] + (llm.get("fallback_models") or [])
    forbidden = {
        "deepseek/deepseek-v4-flash:free",           # 49s > 30s timeout
        "arcee-ai/trinity-large-thinking:free",      # empty .content on thinking models
        "baidu/cobuddy:free",                        # TimeoutError under parallel
        "nvidia/nemotron-3-super-120b-a12b:free",    # 0/3 parallel
        "google/gemma-4-26b-a4b-it:free",            # 0/3 parallel (rate-limited upstream)
        "inclusionai/ring-2.6-1t:free",              # delisted
        "openrouter/auto",                           # bypasses manual ordering
    }
    leaked = [m for m in chain if m in forbidden]
    assert not leaked, (
        f"forbidden models in chain: {leaked} — see "
        ".omc/research/llm-chain-2026-05-16/RESULTS.md"
    )
