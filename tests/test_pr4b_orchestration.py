"""Tests for PR4b !all command orchestration layer.

Covers cache, discord_history, vault_writer, narrator.synthesize_narrative,
and aggregator.handle_all (mocked end-to-end).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.alerts.all_command import (
    aggregator,
    cache,
    discord_history,
    narrator,
    vault_writer,
)
from consensus_engine.alerts.all_command.levels import Anchor
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


@pytest.fixture
async def isolated_db(tmp_path):
    """Reset L1 cache and point DB at a temp file so cache tests don't bleed."""
    from consensus_engine import config as cfg, db
    from consensus_engine.utils.xref_cache import clear_xref_cache
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    clear_xref_cache()
    await db.init_db()
    yield
    clear_xref_cache()
    await db.close_db()


# ---------------------------------------------------------------------------
# cache.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_miss_then_hit(isolated_db):
    """First call misses, second call hits the cache."""
    miss = await cache.get_cached_all("TESTA")
    assert miss is None

    payload = {"embed": {"title": "x"}, "vault_md": "# x", "cached_at": time.time()}
    await cache.set_cached_all("TESTA", payload)
    hit = await cache.get_cached_all("TESTA")
    assert hit == payload


@pytest.mark.asyncio
async def test_cache_single_flight_dedupes_concurrent_callers(isolated_db):
    """Two concurrent compute_fns for the same ticker resolve to one call."""
    counter = {"n": 0}

    async def compute() -> dict:
        counter["n"] += 1
        await asyncio.sleep(0.05)
        return {"embed": {"title": "y"}, "vault_md": "# y", "cached_at": time.time()}

    a, b = await asyncio.gather(
        cache.all_with_single_flight("TESTB", compute),
        cache.all_with_single_flight("TESTB", compute),
    )
    assert counter["n"] == 1
    assert a == b


# ---------------------------------------------------------------------------
# discord_history.py
# ---------------------------------------------------------------------------

def _build_pattern_match(ticker: str, name):
    return discord_history._build_match_pattern(ticker, name)


def test_discord_history_pattern_cashtag_and_bareword():
    pat = _build_pattern_match("NVDA", None)
    assert pat.search("loving $NVDA today")
    assert pat.search("NVDA is moving")
    assert not pat.search("NVDIA-something-else")


def test_discord_history_pattern_with_company_name():
    pat = _build_pattern_match("NVDA", "Nvidia Corp")
    assert pat.search("NVIDIA CORP earnings beat")
    assert pat.search("nvidia corp filed")
    assert pat.search("$NVDA up")


def test_discord_history_pattern_null_company_graceful():
    """name=None or empty is handled gracefully (no regex error)."""
    pat = _build_pattern_match("AMD", "")
    assert pat.search("$AMD")
    assert pat.search("AMD strong")


@pytest.mark.asyncio
async def test_discord_history_no_token_returns_empty(monkeypatch):
    """Missing token = graceful [] return."""
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.discord_history.cfg.get_api_key",
        lambda key: "",
    )
    result = await discord_history.fetch_chat_24h_ticker_filtered("NVDA", None)
    assert result == []
    result = await discord_history.fetch_brief_last_3()
    assert result == []


@pytest.mark.asyncio
async def test_discord_history_24h_filter_applied(monkeypatch):
    """Messages older than 24h are filtered out."""
    now_ms = int(time.time() * 1000)
    fresh_id = str((now_ms - discord_history._DISCORD_EPOCH_MS) << 22)
    old_ms = now_ms - (25 * 3600 * 1000)
    old_id = str((old_ms - discord_history._DISCORD_EPOCH_MS) << 22)

    pages = [[
        {"id": fresh_id, "content": "$NVDA up today"},
        {"id": old_id, "content": "$NVDA from yesterday"},
    ]]

    async def _fake_fetch(_session, _channel, _headers, **_kwargs):
        return pages.pop(0) if pages else []

    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.discord_history.cfg.get_api_key",
        lambda key: "fake_token",
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.discord_history.cfg.get",
        lambda key, default=None: "1234" if "channel" in key else default,
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.discord_history._fetch_page",
        _fake_fetch,
    )

    result = await discord_history.fetch_chat_24h_ticker_filtered("NVDA", None)
    assert result == ["$NVDA up today"]


# ---------------------------------------------------------------------------
# vault_writer.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_writer_writes_separate_all_md(tmp_path):
    """Writes <TICKER>-all.md, NOT <TICKER>.md."""
    final = await vault_writer.write_all_command_vault(
        "VWA", "# vault content", str(tmp_path),
    )
    assert final.endswith("VWA-all.md")
    assert not final.endswith("VWA.md") or "all" in final
    assert os.path.exists(final)
    with open(final, encoding="utf-8") as f:
        assert f.read() == "# vault content"
    # Atlas's <TICKER>.md path must NOT exist.
    atlas_path = os.path.join(str(tmp_path), "tickers", "VWA.md")
    assert not os.path.exists(atlas_path)


@pytest.mark.asyncio
async def test_vault_writer_atomic_unique_tmp_suffix(tmp_path):
    """Tmp suffix uses pid + uuid8 so two writes never collide."""
    p1 = await vault_writer.write_all_command_vault("VWB", "first", str(tmp_path))
    p2 = await vault_writer.write_all_command_vault("VWB", "second", str(tmp_path))
    # Both writes succeeded against the same final path; second wins.
    assert p1 == p2
    with open(p1, encoding="utf-8") as f:
        assert f.read() == "second"
    # No leftover tmp files
    leftover = [f for f in os.listdir(os.path.join(str(tmp_path), "tickers"))
                if f.endswith(".tmp")]
    assert leftover == []


@pytest.mark.asyncio
async def test_vault_writer_read_existing_returns_none_on_missing(tmp_path):
    """Missing file returns None, never raises."""
    out = await vault_writer.read_existing_vault("VWC", str(tmp_path))
    assert out is None


@pytest.mark.asyncio
async def test_vault_writer_rejects_invalid_ticker(tmp_path):
    """Defense-in-depth (D16): invalid ticker rejected before any path op."""
    with pytest.raises(ValueError):
        await vault_writer.write_all_command_vault("../etc", "x", str(tmp_path))


def test_vault_writer_render_includes_all_sections():
    """Markdown render contains all required headings."""
    structured = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=98.0, tp1=105.0, tp2=110.0, tp3=115.0,
        breakout_timeframe="earnings 2026-05-15",
        magnitude_label="±$5.00 (2× ATR)",
    )
    md = vault_writer.render_all_command_markdown(
        ticker="NVDA",
        structured=structured,
        score_breakdown=ScoreBreakdown(base=0, news_catalyst=10, technical=15),
        narrative="Three paragraph narrative here.",
        sources_used=["news: ok"],
        alert_history=[
            {"alerted_at": time.time(), "final_score": 80, "catalyst": "earnings"},
        ],
        anchors_used=[
            Anchor(price=100.0, source="youtube:LunaTrades", source_type="yt",
                   touches=2, freshness_days=1, computed_score=12.0),
        ],
    )
    assert "# NVDA — !all Analysis" in md
    assert "## Direction / Confidence / Trade Plan" in md
    assert "## Narrative" in md
    assert "## Score Breakdown" in md
    assert "## Sources" in md
    assert "## Alert History" in md
    assert "## Anchored Levels Used" in md
    assert "all:NVDA" in md


# ---------------------------------------------------------------------------
# narrator.synthesize_narrative
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_narrator_synthesize_calls_primary_with_8k_tokens():
    """Primary-tier call_with_fallback hit with role=primary, max_tokens=8000."""
    structured = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    breakdown = ScoreBreakdown(base=10, news_catalyst=20)
    seen = {}

    async def _fake_call(role, messages, *, max_tokens, temperature, timeout,
                         chain=None, **_kw):
        seen.update(role=role, max_tokens=max_tokens, temperature=temperature,
                    timeout=timeout, messages=messages)
        return "Narrative paragraph 1. Bullish setup with strong catalysts."

    with patch(
        "consensus_engine.alerts.all_command.narrator.call_with_fallback",
        new=_fake_call,
    ):
        narrative, status = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=structured,
            score_breakdown=breakdown,
            sanitized_searxng=["news 1"],
            sanitized_chat=["chat 1"],
            sanitized_brief=["brief 1"],
            vault_summary="prior research summary",
            structured_data_json='{"x": 1}',
            deadline_seconds=15.0,
        )
    assert status == "ok"
    assert narrative
    assert seen["role"] == "primary"
    assert seen["max_tokens"] == 8000
    assert seen["temperature"] == 0.35


@pytest.mark.asyncio
async def test_narrator_synthesize_empty_returns_fallback_status():
    """Empty LLM result yields ('', 'fallback_data_only')."""
    async def _empty_call(*args, **kwargs):
        return ""

    with patch(
        "consensus_engine.alerts.all_command.narrator.call_with_fallback",
        new=_empty_call,
    ):
        narrative, status = await narrator.synthesize_narrative(
            ticker="AMD",
            structured=StructuredFields(direction="BULLISH", confidence_label="HIGH"),
            score_breakdown=ScoreBreakdown(),
            sanitized_searxng=[], sanitized_chat=[], sanitized_brief=[],
            vault_summary="", structured_data_json="{}",
            deadline_seconds=15.0,
        )
    assert narrative == ""
    assert status == "fallback_data_only"


@pytest.mark.asyncio
async def test_narrator_synthesize_contradiction_retry_path():
    """A contradicting first response triggers retry; second consistent response wins.

    Ship 2: both responses include the required section markers so the
    has_required_sections retry path is bypassed and only the contradiction
    retry path is exercised.
    """
    structured = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    calls: list[str] = []

    _sections = (
        "\n**TL;DR:** thesis.\n"
        "## Risk Considerations\n"
        "* China export curbs cut revenue [evidence:1].\n"
        "## Trade Plan\n| x |\n"
    )

    async def _call(role, messages, *, max_tokens, temperature, timeout,
                    chain=None, **_kw):
        calls.append(messages[0]["content"])
        if len(calls) == 1:
            return "Outlook is bearish despite the bullish setup." + _sections
        return "Bullish breakout setup with options flow confirming upside." + _sections

    with patch(
        "consensus_engine.alerts.all_command.narrator.call_with_fallback",
        new=_call,
    ):
        narrative, status = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=structured,
            score_breakdown=ScoreBreakdown(),
            sanitized_searxng=[], sanitized_chat=[], sanitized_brief=[],
            vault_summary="", structured_data_json="{}",
            deadline_seconds=15.0,
        )
    assert status == "ok"
    assert "Bullish" in narrative
    assert len(calls) == 2  # initial + retry-once
    assert "STRICT" in calls[1]  # hardened prompt prepended


# ---------------------------------------------------------------------------
# aggregator.handle_all (end-to-end mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregator_handle_all_invalid_ticker_replies_and_returns():
    """Invalid ticker -> plain reply, no compute, no crash."""
    sent: list[tuple] = []

    async def _send(channel_id, msg_id, content):
        sent.append((channel_id, msg_id, content))

    with patch(
        "consensus_engine.alerts.all_command.aggregator.send_command_reply",
        new=_send,
    ):
        await aggregator.handle_all("../bad", "ch", "msg")
    assert any("Invalid" in s[2] for s in sent)


@pytest.mark.asyncio
async def test_aggregator_handle_all_e2e_calls_embed_and_vault(
    tmp_path, monkeypatch, isolated_db,
):
    """End-to-end mocked path: embed reply + vault write happen, cache populated."""

    sent: list[tuple] = []

    async def _send_reply(channel_id, msg_id, content):
        sent.append(("reply", content))

    async def _send_embed(channel_id, msg_id, embed):
        sent.append(("embed", embed))

    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_reply",
        _send_reply,
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_embed_reply",
        _send_embed,
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.cfg.get",
        lambda key, default=None: str(tmp_path) if key == "vault.path" else default,
    )

    async def _empty_gather(ticker):
        return {
            "ticker_meta": {}, "company_name": None,
            "score": None, "technical_long": None, "technical_short": None,
            "twitter_signals": [], "social_signals": [],
            "yt_signals": [], "yt_options": [], "yt_levels": [], "yt_evidence": [],
            "alert_history": [], "decision_snapshots": [],
            "news_catalyst": None, "sec_filings": [], "options_unusual": None,
            "trends": {}, "apewisdom": None,
            "chat_msgs": [], "brief_msgs": [], "prior_vault": None,
            "sources_surfaced": [],
            "source_failures": ["score: unavailable"],
        }

    async def _empty_sanitize(**_kwargs):
        return {"searxng": [], "chat": [], "brief": [], "vault": ""}

    async def _empty_synthesize(**_kwargs):
        return "", "fallback_data_only"

    monkeypatch.setattr(aggregator, "_gather_all_sources", _empty_gather)
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)
    monkeypatch.setattr(narrator, "synthesize_narrative", _empty_synthesize)

    await aggregator.handle_all("ETST", "channel", "msgid")

    kinds = [s[0] for s in sent]
    assert "reply" in kinds   # "Analyzing $TICKER..." reply
    assert "embed" in kinds   # final embed reply
    # Vault file written
    final = os.path.join(str(tmp_path), "tickers", "ETST-all.md")
    assert os.path.exists(final)


@pytest.mark.asyncio
async def test_aggregator_handle_all_cache_hit_short_circuits(
    tmp_path, monkeypatch, isolated_db,
):
    """A second call within TTL hits the cache and skips the gather."""

    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.cfg.get",
        lambda key, default=None: str(tmp_path) if key == "vault.path" else default,
    )

    async def _send(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_reply", _send,
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_embed_reply", _send,
    )

    payload = {
        "embed": {"title": "$ETSC — Full Analysis", "footer": {"text": "x"}},
        "vault_md": "# ETSC — !all Analysis",
        "cached_at": time.time(),
    }
    await cache.set_cached_all("ETSC", payload)

    gather_calls = {"n": 0}

    async def _no_gather(ticker):
        gather_calls["n"] += 1
        return {}

    monkeypatch.setattr(aggregator, "_gather_all_sources", _no_gather)
    await aggregator.handle_all("ETSC", "ch", "msg")
    assert gather_calls["n"] == 0
