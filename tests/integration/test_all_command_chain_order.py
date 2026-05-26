"""LLM chain-order regression test.

History:
  - PR1 (2026-05-08): ring-2.6-1t pinned as PRIMARY (R8: 14s vs gpt-oss-120b 78.7s).
  - TODO #5 (2026-05-15, commit 732dba6): ring-2.6-1t delisted from OpenRouter
    free tier → promoted gpt-oss-120b to PRIMARY, shipped 5-model chain
    (gpt-oss-120b, glm-4.5-air, deepseek-v4-flash, trinity-large-thinking, cobuddy).
  - TODO #7 (2026-05-16): isolation test showed positions 2-4 fail !all parallel
    load → replaced with gpt-oss-20b + 2 nemotron-30b variants; glm-4.5-air
    demoted to last-resort.
  - 2026-05-26: user-requested split of role chains. role="primary"
    (alfred / research / video_parser fallback) moved to paid
    deepseek-v4-flash; tweetshift signal scoring (llm_scorer.py, now
    role="text") moved to the openrouter/free meta-router with
    gpt-oss-120b:free as the empty-content safety net. See
    .omc/notes/model-swap-2026-05-26-revert.md.
"""
from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus.yaml"

# role="primary" chain (alfred morning brief, research/sources.py,
# video_parser openrouter fallback path).
EXPECTED_PRIMARY = "deepseek/deepseek-v4-flash"
EXPECTED_FALLBACKS = ["openrouter/free"]

# role="text" chain (llm_scorer.score_confidence — tweetshift signal volume).
EXPECTED_TEXT_PRIMARY = "openrouter/free"
EXPECTED_TEXT_FALLBACKS = ["openai/gpt-oss-120b:free"]


def _llm_block() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text()).get("llm", {})


def test_primary_model_is_deepseek_v4_flash():
    """role=primary primary must be paid deepseek-v4-flash."""
    llm = _llm_block()
    assert llm.get("model") == EXPECTED_PRIMARY, (
        f"llm.model={llm.get('model')!r}; expected {EXPECTED_PRIMARY}"
    )


def test_text_primary_is_openrouter_free():
    """role=text primary is the openrouter/free meta-router (tweetshift path)."""
    llm = _llm_block()
    assert llm.get("text_model") == EXPECTED_TEXT_PRIMARY, (
        f"llm.text_model={llm.get('text_model')!r}; expected {EXPECTED_TEXT_PRIMARY}"
    )


def test_primary_fallback_chain_matches_expected():
    llm = _llm_block()
    assert llm.get("fallback_models") == EXPECTED_FALLBACKS, (
        f"got {llm.get('fallback_models')!r}; expected {EXPECTED_FALLBACKS!r}"
    )


def test_text_fallback_chain_matches_expected():
    llm = _llm_block()
    assert llm.get("text_fallback_models") == EXPECTED_TEXT_FALLBACKS, (
        f"got {llm.get('text_fallback_models')!r}; "
        f"expected {EXPECTED_TEXT_FALLBACKS!r}"
    )


def test_no_known_failed_models_in_chain():
    """Defense-in-depth: models that failed isolation must not reappear in
    either role chain."""
    llm = _llm_block()
    chain = (
        [llm.get("model")]
        + (llm.get("fallback_models") or [])
        + [llm.get("text_model")]
        + (llm.get("text_fallback_models") or [])
    )
    forbidden = {
        "deepseek/deepseek-v4-flash:free",           # 49s > 30s timeout; :free variant
        "arcee-ai/trinity-large-thinking:free",      # empty .content on thinking models
        "baidu/cobuddy:free",                        # TimeoutError under parallel
        "nvidia/nemotron-3-super-120b-a12b:free",    # 0/3 parallel
        "google/gemma-4-26b-a4b-it:free",            # 0/3 parallel (rate-limited upstream)
        "inclusionai/ring-2.6-1t:free",              # delisted
        "openrouter/auto",                           # paid meta-router; we want free
    }
    leaked = [m for m in chain if m in forbidden]
    assert not leaked, f"forbidden models in chain: {leaked}"
