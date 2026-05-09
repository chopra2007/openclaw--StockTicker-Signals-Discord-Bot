"""Gap 2 follow-up — earnings recap dict must reach the synth prompt unmodified.

When news_cascade selects the recent_earnings tier, the resulting
CatalystResult.catalyst_body flows through `news_batch` which LLM-summarizes
each item into one bland sentence — stripping the specific revenue / EPS
numbers we worked hard to fetch. Live verification on 2026-05-09 showed
the LLM emitting "NVDA reported earnings for the quarter ending 2026"
(truncated) instead of citing the $68.13B / +73% / EPS $1.62 figures.

Fix: aggregator separately stashes the raw recap dict as
`data["recent_earnings_recap"]` so the narrator prompt can include the
literal numbers as a dedicated EARNINGS RECAP block that bypasses the
sanitize chain.
"""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import aggregator, narrator


@pytest.mark.asyncio
async def test_aggregator_stashes_recent_earnings_recap_dict(monkeypatch):
    """_gather_all_sources must add data['recent_earnings_recap'] populated."""
    recap_dict = {
        "period": "2026-03-31",
        "eps_actual": 1.62, "eps_estimate": 1.5634, "eps_surprise_pct": 3.62,
        "revenue_actual": 68127000000.0, "revenue_yoy_pct": 73.21,
    }

    async def _routing_scanner(module_path, attr, *_a, **_kw):
        if (module_path, attr) == (
            "consensus_engine.scanners.earnings_calendar",
            "fetch_recent_earnings_for_ticker",
        ):
            return recap_dict
        return None

    async def _none(*_a, **_kw):
        return None

    async def _empty_list(*_a, **_kw):
        return []

    async def _empty_dict(*_a, **_kw):
        return {}

    monkeypatch.setattr(aggregator, "_db_call", _empty_list)
    monkeypatch.setattr(aggregator, "_score_ticker_safe", _none)
    monkeypatch.setattr(aggregator, "_verify_technical_safe", _none)
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
    assert out["recent_earnings_recap"] == recap_dict, (
        f"data['recent_earnings_recap'] missing or wrong; got {out.get('recent_earnings_recap')!r}"
    )


def test_synthesis_prompt_includes_earnings_recap_block():
    """When recap dict provided, prompt MUST contain a literal EARNINGS RECAP block."""
    from consensus_engine.alerts.all_command.structured_fields import StructuredFields

    structured = StructuredFields(
        direction="BULLISH", confidence_label="LOW",
        sl=180.0, tp1=265.0, current_price=215.20,
    )
    recap = {
        "period": "2026-03-31",
        "eps_actual": 1.62, "eps_estimate": 1.5634, "eps_surprise_pct": 3.62,
        "revenue_actual": 68127000000.0, "revenue_yoy_pct": 73.21,
    }

    messages = narrator._build_synthesis_prompt(
        ticker="NVDA",
        structured=structured,
        score_breakdown=None,
        sanitized_searxng=None,
        sanitized_chat=[], sanitized_brief=[], vault_summary="",
        structured_data_json="{}",
        sources_surfaced=["score", "earnings_calendar"],
        sanitized_news=[], sanitized_sec=[], sanitized_twitter=[],
        sanitized_social=[], sanitized_yt_signals=[], sanitized_yt_options=[],
        sanitized_yt_evidence=[], sanitized_technical_short={},
        recent_earnings_recap=recap,
    )

    user_text = messages[1]["content"]
    assert "EARNINGS RECAP" in user_text, "prompt missing EARNINGS RECAP block"
    # Literal numbers must be present (NOT LLM-summarized)
    assert "68127000000" in user_text or "68.13" in user_text or "68127" in user_text, (
        "revenue_actual must appear literally in EARNINGS RECAP block"
    )
    assert "73.21" in user_text or "73." in user_text, (
        "revenue_yoy_pct must appear literally"
    )
    assert "1.62" in user_text, "eps_actual must appear literally"


def test_synthesis_prompt_omits_block_when_recap_none():
    """No recap → no EARNINGS RECAP block (don't pollute the prompt)."""
    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
    structured = StructuredFields(direction="NEUTRAL", confidence_label="LOW")

    messages = narrator._build_synthesis_prompt(
        ticker="ZZZZ",
        structured=structured,
        score_breakdown=None,
        sanitized_searxng=None,
        sanitized_chat=[], sanitized_brief=[], vault_summary="",
        structured_data_json="{}",
        sources_surfaced=[],
        sanitized_news=[], sanitized_sec=[], sanitized_twitter=[],
        sanitized_social=[], sanitized_yt_signals=[], sanitized_yt_options=[],
        sanitized_yt_evidence=[], sanitized_technical_short={},
        recent_earnings_recap=None,
    )
    # The literal data-block header is "EARNINGS RECAP (literal —"; the
    # CONSTRAINTS section also mentions the phrase but only for instructions,
    # never with the literal-token marker.
    assert "EARNINGS RECAP (literal —" not in messages[1]["content"]
