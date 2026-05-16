"""Tests for captions_llm_parser — the F1 caption-text → EvidenceBundle path.

Covers:
- Happy path: LLM returns valid JSON → EvidenceBundle with spans+tickers
- Empty transcript → None
- Chain exhaustion (LLM returns "") → None
- Malformed JSON → None
- Markdown-fenced JSON gets cleaned
- Long transcript is truncated
- Tickers normalize (uppercase, strip $, drop TA abbreviations, drop bad symbols)
- Spans with no tickers after normalization are dropped
- Chain is built from config (primary + fallbacks, no duplicates)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.models import RunTelemetry
from consensus_engine.analysis import captions_llm_parser as clp


_VALID_LLM_JSON = json.dumps({
    "spans": [
        {"quote": "Look at Apple and Nvidia today.", "tickers": ["AAPL", "NVDA"]},
        {"quote": "Tesla is breaking out.", "tickers": ["TSLA"]},
        {"quote": "The Q's are leading.", "tickers": ["QQQ"]},
    ]
})


@pytest.mark.asyncio
async def test_happy_path_returns_bundle_with_tickers():
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value=_VALID_LLM_JSON):
        tel = RunTelemetry()
        bundle = await clp.extract_evidence_from_captions(
            "dQw4w9WgXcQ", "Some transcript text.", "2026-05-15T00:00:00Z", tel,
        )
    assert bundle is not None
    assert bundle.video_id == "dQw4w9WgXcQ"
    assert len(bundle.spans) == 3
    assert tel.span_count == 3
    tickers = {t for sp in bundle.spans for t in sp.tickers}
    assert tickers == {"AAPL", "NVDA", "TSLA", "QQQ"}
    # ts_sec is bucketed 0, 30, 60 so the classifier has something monotonic
    assert [sp.ts_sec for sp in bundle.spans] == [0, 30, 60]


@pytest.mark.asyncio
async def test_empty_transcript_returns_none():
    bundle = await clp.extract_evidence_from_captions("vid12345678", "", "", RunTelemetry())
    assert bundle is None
    bundle = await clp.extract_evidence_from_captions("vid12345678", "   \n\t  ", "", RunTelemetry())
    assert bundle is None


@pytest.mark.asyncio
async def test_chain_exhausted_returns_none():
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value=""):
        bundle = await clp.extract_evidence_from_captions(
            "vid12345678", "real transcript", "", RunTelemetry(),
        )
    assert bundle is None


@pytest.mark.asyncio
async def test_malformed_json_returns_none():
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value="this is not json at all"):
        bundle = await clp.extract_evidence_from_captions(
            "vid12345678", "real transcript", "", RunTelemetry(),
        )
    assert bundle is None


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_cleaned():
    fenced = "```json\n" + _VALID_LLM_JSON + "\n```"
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value=fenced):
        bundle = await clp.extract_evidence_from_captions(
            "vid12345678", "transcript", "", RunTelemetry(),
        )
    assert bundle is not None
    assert len(bundle.spans) == 3


@pytest.mark.asyncio
async def test_long_transcript_is_truncated():
    long_text = "Lots of words. " * 5000  # ~75K chars
    captured: dict[str, list] = {}

    async def capture(role, messages, **kw):
        captured["messages"] = messages
        return _VALID_LLM_JSON

    with patch.object(clp, "call_with_fallback", new=capture):
        await clp.extract_evidence_from_captions("vid12345678", long_text, "", RunTelemetry())

    user_content = captured["messages"][1]["content"]
    # The truncation cap is 15K — user prompt + transcript should be well under 20K total.
    assert len(user_content) < 20000
    assert "Lots of words." in user_content


@pytest.mark.asyncio
async def test_tickers_normalize_and_drop_garbage():
    raw = json.dumps({
        "spans": [
            # mixed case + $ prefix + dup + TA abbrev + non-ticker garbage
            {"quote": "Mixed bag here.", "tickers": ["aapl", "$NVDA", "NVDA", "RSI", "TOOLONGSYM", "123"]},
            # span has only TA abbrev → entire span gets dropped
            {"quote": "Pure indicator chat.", "tickers": ["MACD", "EMA"]},
            # valid second span
            {"quote": "Tesla call.", "tickers": ["TSLA"]},
        ]
    })
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value=raw):
        bundle = await clp.extract_evidence_from_captions(
            "vid12345678", "transcript", "", RunTelemetry(),
        )
    assert bundle is not None
    assert len(bundle.spans) == 2
    assert bundle.spans[0].tickers == ["AAPL", "NVDA"]
    assert bundle.spans[1].tickers == ["TSLA"]


@pytest.mark.asyncio
async def test_all_spans_filtered_out_returns_none():
    """If every LLM span has only TA abbreviations / no real tickers, bundle is None."""
    raw = json.dumps({
        "spans": [
            {"quote": "RSI is overbought.", "tickers": ["RSI"]},
            {"quote": "MACD crossover.", "tickers": ["MACD"]},
        ]
    })
    with patch.object(clp, "call_with_fallback", new_callable=AsyncMock, return_value=raw):
        bundle = await clp.extract_evidence_from_captions(
            "vid12345678", "transcript", "", RunTelemetry(),
        )
    assert bundle is None


def test_chain_built_from_config_dedupes():
    def fake_cfg(key, default=None):
        if key == "youtube.captions.llm.model":
            return "google/gemini-2.5-flash"
        if key == "youtube.captions.llm.fallback_models":
            return [
                "inclusionai/ring-2.6-1t:free",
                "google/gemini-2.5-flash",  # dup of primary — should be deduped
                "z-ai/glm-4.5-air:free",
            ]
        return default

    with patch.object(clp.cfg, "get", side_effect=fake_cfg):
        chain = clp._build_chain()
    assert chain == [
        "google/gemini-2.5-flash",
        "inclusionai/ring-2.6-1t:free",
        "z-ai/glm-4.5-air:free",
    ]


@pytest.mark.asyncio
async def test_passes_chain_into_call_with_fallback():
    """captions_llm_parser must pass the captions-specific chain to call_with_fallback
    explicitly (not use a role lookup), so the F1 path doesn't share a model chain
    with synthesis/text paths."""
    captured_kwargs: dict = {}

    async def capture(role, messages, **kw):
        captured_kwargs["role"] = role
        captured_kwargs.update(kw)
        return _VALID_LLM_JSON

    with patch.object(clp, "call_with_fallback", new=capture):
        await clp.extract_evidence_from_captions("vid12345678", "x", "", RunTelemetry())

    assert captured_kwargs["role"] is None  # not using role lookup
    assert isinstance(captured_kwargs.get("chain"), list) and len(captured_kwargs["chain"]) >= 1
