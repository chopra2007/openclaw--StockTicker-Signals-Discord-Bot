"""Gap 3 wiring — chart pattern data flows from aggregator to synth prompt.

Pattern detection itself is covered by tests/test_chart_patterns.py.
This file verifies the wiring inside the !all command:

  - aggregator runs detect_all() over swing candles and stashes the
    result as data["chart_pattern"]
  - narrator._build_synthesis_prompt includes a CHART PATTERN block when
    a pattern is present (bypassing sanitize — the data is internal)
  - prompt CONSTRAINTS reference the pattern so the LLM cites it
"""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import aggregator, narrator


@pytest.mark.asyncio
async def test_aggregator_stashes_chart_pattern(monkeypatch):
    """_gather_all_sources runs pattern detection on swing candles."""
    from consensus_engine.analysis import patterns

    captured: dict = {}
    sentinel = {"pattern": "bull_flag", "confidence": 0.7, "key_level": 130.0}

    def _fake_detect(candles):
        captured["called_with_n"] = len(candles or [])
        return sentinel

    monkeypatch.setattr(patterns, "detect_all", _fake_detect)

    class _Tech:
        current_price = 100.0
        atr14 = 2.0
        candles = [{"high": 100 + i, "low": 99 + i, "close": 99.5 + i} for i in range(25)]

    async def _routing_scanner(*_a, **_kw):
        return None

    async def _none(*_a, **_kw):
        return None

    async def _empty_list(*_a, **_kw):
        return []

    async def _empty_dict(*_a, **_kw):
        return {}

    async def _verify_long(_t, kind):
        return _Tech() if kind == "long" else None

    monkeypatch.setattr(aggregator, "_db_call", _empty_list)
    monkeypatch.setattr(aggregator, "_score_ticker_safe", _none)
    monkeypatch.setattr(aggregator, "_verify_technical_safe", _verify_long)
    monkeypatch.setattr(aggregator, "_scanner_call", _routing_scanner)
    monkeypatch.setattr(
        aggregator.discord_history, "fetch_chat_24h_ticker_filtered", _empty_list,
    )
    monkeypatch.setattr(
        aggregator.discord_history, "fetch_brief_last_3", _empty_list,
    )
    monkeypatch.setattr(
        aggregator.vault_writer, "read_existing_vault", _empty_dict,
    )

    out = await aggregator._gather_all_sources("NVDA")
    assert captured["called_with_n"] >= 20, "should pass at least 20 candles to detector"
    assert out["chart_pattern"] == sentinel


def test_synthesis_prompt_includes_chart_pattern_block():
    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
    structured = StructuredFields(
        direction="BULLISH", confidence_label="LOW",
        sl=100.0, tp1=140.0, current_price=125.0,
    )
    pattern = {"pattern": "bull_flag", "confidence": 0.78, "key_level": 130.0}

    msgs = narrator._build_synthesis_prompt(
        ticker="NVDA",
        structured=structured,
        score_breakdown=None,
        sanitized_searxng=None,
        sanitized_chat=[], sanitized_brief=[], vault_summary="",
        structured_data_json="{}",
        sources_surfaced=["score", "chart_pattern"],
        sanitized_news=[], sanitized_sec=[], sanitized_twitter=[],
        sanitized_social=[], sanitized_yt_signals=[], sanitized_yt_options=[],
        sanitized_yt_evidence=[], sanitized_technical_short={},
        chart_pattern=pattern,
    )
    user_text = msgs[1]["content"]
    assert "CHART PATTERN" in user_text, "prompt missing CHART PATTERN block"
    assert "bull_flag" in user_text
    assert "130" in user_text


def test_synthesis_prompt_omits_chart_pattern_block_when_none():
    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
    structured = StructuredFields(direction="NEUTRAL", confidence_label="LOW")

    msgs = narrator._build_synthesis_prompt(
        ticker="ZZZZ", structured=structured, score_breakdown=None,
        sanitized_searxng=None, sanitized_chat=[], sanitized_brief=[],
        vault_summary="", structured_data_json="{}", sources_surfaced=[],
        sanitized_news=[], sanitized_sec=[], sanitized_twitter=[],
        sanitized_social=[], sanitized_yt_signals=[], sanitized_yt_options=[],
        sanitized_yt_evidence=[], sanitized_technical_short={},
        chart_pattern=None,
    )
    assert "CHART PATTERN (literal —" not in msgs[1]["content"]
