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
    gpt-oss-120b:free as the empty-content safety net.
  - 2026-06-04 (TODO #24): 24-model live bake-off rebuilt both chains.
    role="primary" -> gpt-oss-120b (competence 9.5/10, 0.3s, 5/5) with
    qwen3-235b-2507 + deepseek-v4-flash + openrouter/free (credit net).
    role="text" -> gpt-4.1-nano (non-reasoning, robust at the tight 512-tok
    narrator budget where nemotron-nano returned empty live) with
    mistral-nemo + nemotron-nano-9b-v2 + openrouter/free. Data:
    .omc/research/model-bakeoff-2026-06-04/.
  - 2026-06-15: nvidia/nemotron-nano-9b-v2 retired by OpenRouter (daily health
    check ❌ HTTP 404 "No endpoints found"). Replaced text fallback 2 with
    google/gemini-2.5-flash-lite, then with qwen/qwen3-235b-a22b-2507 after the
    2026-06-15 bake-off (.omc/research/model-bakeoff-2026-06-15/): qwen matched
    gemini on clean tight-512 + 3/3 reliability at $0.10/M out (4x cheaper),
    non-reasoning, 16k cap clears the 8k floor, +Alibaba provider diversity.
  - 2026-06-16 calibration + agent real-path bake-off (same dir): role="text"
    LEAD promoted gpt-4.1-nano -> qwen3-235b-2507 (best-calibrated scorer: 0/36
    ordering inversions, 9/9 in-band, vs nano 1 inversion/7-of-9; 4x cheaper),
    nano demoted to text fallback 1. role="agent" (in this file's sibling
    chain, mirrored to openclaw.json) promoted gpt-4.1-nano -> lead and dropped
    gpt-oss-120b, which timed out / returned empty on 5/5 heavy tool questions.
"""
from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus.yaml"

# role="primary" chain (alfred morning brief, research/sources.py,
# video_parser openrouter fallback path).
EXPECTED_PRIMARY = "openai/gpt-oss-120b"
EXPECTED_FALLBACKS = [
    "qwen/qwen3-235b-a22b-2507",
    "deepseek/deepseek-v4-flash",
    "openrouter/free",
]

# role="text" chain (llm_scorer.score_confidence — tweetshift signal volume).
EXPECTED_TEXT_PRIMARY = "qwen/qwen3-235b-a22b-2507"  # 2026-06-16 calibration bake-off: best-calibrated scorer (0/36 inversions, 9/9 in-band) + 4x cheaper than prior lead gpt-4.1-nano
EXPECTED_TEXT_FALLBACKS = [
    "openai/gpt-4.1-nano",            # prior text lead — deterministic, fast, proven; kept as diverse backup 1
    "mistralai/mistral-nemo",
    "openrouter/free",
]


def _llm_block() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text()).get("llm", {})


def test_primary_model_is_gpt_oss_120b():
    """role=primary lead must be gpt-oss-120b (2026-06-04 bake-off winner)."""
    llm = _llm_block()
    assert llm.get("model") == EXPECTED_PRIMARY, (
        f"llm.model={llm.get('model')!r}; expected {EXPECTED_PRIMARY}"
    )


def test_text_primary_is_qwen3_235b():
    """role=text lead is qwen3-235b-2507 (2026-06-16 best-calibrated scorer + 4x cheaper)."""
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
        "nvidia/nemotron-nano-9b-v2",                # retired by OpenRouter 2026-06-15 (404 No endpoints)
        "openrouter/auto",                           # paid meta-router; we want free
    }
    leaked = [m for m in chain if m in forbidden]
    assert not leaked, f"forbidden models in chain: {leaked}"
