"""PR5 — End-to-end integration tests for the wired-up `!all` command.

Exercises `aggregator.handle_all` with the entire data-source layer mocked
(DB, scanners, channel history, SearXNG, LLM client) and asserts:

- "Analyzing $TICKER..." plain reply is sent
- Final embed reply is sent with all 8 fields and a direction-coloured embed
- Vault file is written to `<vault>/tickers/<TICKER>-all.md`
- Cache hit on second invocation skips the gather and embed-sends only once
- Partial source failure yields `<source>: unavailable` in sources_used
- Score-gate suppression (LOW confidence / NEUTRAL direction) -> SL/TP all "—"
- Empty LLM result -> narrative falls back to `render_data_only_fallback`
- Path traversal ticker (`../../etc/passwd`) is rejected by `is_valid_ticker`

Per plan §9.2 — covers the test_aggregator_e2e.py bucket as the final wiring
sanity check after `_handle_all` in commands.py points at `handle_all`.
"""
from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import patch

import pytest

from consensus_engine.alerts.all_command import (
    aggregator,
    cache,
    narrator,
)
from consensus_engine.alerts.all_command.embed import (
    COLOR_BULLISH,
    COLOR_BEARISH,
    COLOR_NEUTRAL,
)
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def isolated_db(tmp_path):
    """Reset L1 cache and point DB at a temp file so cache rows don't bleed."""
    from consensus_engine import config as cfg, db
    from consensus_engine.utils.xref_cache import clear_xref_cache
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    clear_xref_cache()
    await db.init_db()
    yield
    clear_xref_cache()
    await db.close_db()


@pytest.fixture
def vault_path(tmp_path, monkeypatch):
    """Point `cfg.get('vault.path', ...)` at tmp_path inside the aggregator.

    Delegates non-vault.path lookups back to the real `cfg.get` so that
    `database.path` (set by the `isolated_db` fixture) is respected — earlier
    versions returned `default` for everything else, which silently routed
    `db.init_db()` at the production sqlite file.
    """
    from consensus_engine import config as _cfg
    _orig_get = _cfg.get
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.cfg.get",
        lambda key, default=None: str(tmp_path) if key == "vault.path" else _orig_get(key, default),
    )
    return tmp_path


@pytest.fixture
def captured_sends(monkeypatch):
    """Patch the two Discord-bound sends so the test can inspect payloads."""
    captured: dict[str, list] = {"reply": [], "embed": []}

    async def _send_reply(channel_id, msg_id, content):
        captured["reply"].append((channel_id, msg_id, content))
        return "fake_reply_id"

    async def _send_embed(channel_id, msg_id, embed):
        captured["embed"].append((channel_id, msg_id, embed))
        return "fake_embed_id"

    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_reply",
        _send_reply,
    )
    monkeypatch.setattr(
        "consensus_engine.alerts.all_command.aggregator.send_command_embed_reply",
        _send_embed,
    )
    return captured


def _bullish_gather_factory(
    source_status: list[str] | None = None,
    sources_surfaced: list[str] | None = None,
):
    """Return an async `_gather_all_sources` mock that yields a bullish data dict.

    Score breakdown produces direction=BULLISH (positive technical+news), and
    technical_long stub provides a current_price + ATR so structured fields
    compute SL/TP1/TP2/TP3 (i.e. the `<4 anchors` suppression DOES NOT fire).

    `source_status` is now `source_failures` (PR2 rename); `sources_surfaced`
    is the parallel list of labels whose data made it into the prompt/embed.
    """
    class _Tech:
        current_price = 100.0
        atr14 = 2.0
        candles = [
            {"high": 102.0, "low": 98.0},
            {"high": 103.0, "low": 99.0},
            {"high": 104.0, "low": 100.0},
        ]

    # Score must clear `precision_engine.thresholds.high_confidence` (default 80)
    # so the aggregator preserves direction colour and SL/TP fields.
    bd = ScoreBreakdown(base=30, news_catalyst=30, technical=30)
    score_obj = type("Score", (), {"breakdown": bd, "final_score": bd.total})()

    async def _gather(ticker):
        return {
            "ticker_meta": {"name": "Test Co"},
            "company_name": "Test Co",
            "score": score_obj,
            "technical_long": _Tech(),
            "technical_short": None,
            "twitter_signals": [],
            "social_signals": [],
            "yt_signals": [],
            "yt_options": [],
            "yt_levels": [],
            "yt_evidence": [],
            "alert_history": [],
            "decision_snapshots": [],
            "news_catalyst": None,
            "sec_filings": [],
            "options_unusual": None,
            "trends": {},
            "apewisdom": None,
            "chat_msgs": [],
            "brief_msgs": [],
            "prior_vault": None,
            "sources_surfaced": list(sources_surfaced or []),
            "source_failures": list(source_status or []),
        }
    return _gather


def _empty_gather_factory(source_status: list[str] | None = None):
    """Async `_gather_all_sources` with NO score / technical (forces NEUTRAL)."""
    async def _gather(ticker):
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
            "source_failures": list(source_status or []),
        }
    return _gather


async def _empty_sanitize(**_kwargs):
    return {"searxng": [], "chat": [], "brief": [], "vault": ""}


# ---------------------------------------------------------------------------
# E2E: full pipeline with bullish synthetic data + non-empty narrative
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_e2e_full_pipeline_bullish(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Full pipeline: gather -> structure -> synthesize -> embed -> vault."""

    monkeypatch.setattr(
        aggregator, "_gather_all_sources", _bullish_gather_factory(["news: ok"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    async def _synthesize(**_kwargs):
        return "Bullish breakout setup with strong tech and catalyst confirmation.", "ok"

    monkeypatch.setattr(narrator, "synthesize_narrative", _synthesize)

    await aggregator.handle_all("NVDA", "channel123", "message456")

    # 1. "Analyzing `$NVDA`..." plain reply was sent exactly once.
    assert len(captured_sends["reply"]) == 1
    assert captured_sends["reply"][0][0] == "channel123"
    assert captured_sends["reply"][0][1] == "message456"
    assert "Analyzing" in captured_sends["reply"][0][2]
    assert "NVDA" in captured_sends["reply"][0][2]

    # 2. Final embed reply was sent exactly once.
    assert len(captured_sends["embed"]) == 1
    embed = captured_sends["embed"][0][2]
    assert isinstance(embed, dict)

    # 3. Embed has color matching direction (BULLISH).
    assert embed["color"] == COLOR_BULLISH

    # 4. Embed has all 11 expected inline fields. W4 added Next Catalyst,
    #    Swing Horizon, and Expected Move (replacing Timeframe + Magnitude
    #    when all_command.swing_v2_enabled is True; default true).
    field_names = [f["name"] for f in embed["fields"]]
    assert field_names == [
        "Direction", "Confidence", "Price", "Buy Zone",
        "SL", "TP1", "TP2", "TP3",
        "Next Catalyst", "Swing Horizon", "Expected Move",
    ]
    assert all(f.get("inline") is True for f in embed["fields"])

    # 5. Embed description includes the narrative paragraph.
    assert "Bullish breakout setup" in embed["description"]
    assert "BULLISH" in embed["description"]

    # 6. Vault file is written to `<vault>/tickers/NVDA-all.md`.
    final = os.path.join(str(vault_path), "tickers", "NVDA-all.md")
    assert os.path.exists(final), f"vault file missing: {final}"
    with open(final, "r", encoding="utf-8") as fh:
        vault_md = fh.read()
    assert "# NVDA — !all Analysis" in vault_md
    assert "## Narrative" in vault_md


# ---------------------------------------------------------------------------
# Cache hit: second invocation -> only ONE Discord embed send total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_second_invocation_hits_cache(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Pre-populate the cache; verify the gather is NOT called and the cached
    embed is what gets sent."""

    payload = {
        "embed": {
            "title": "$TSLA — Full Analysis",
            "color": COLOR_BULLISH,
            "description": "📈 BULLISH\nCached narrative goes here.",
            "fields": [
                {"name": "Direction", "value": "📈 BULLISH", "inline": True},
                {"name": "Confidence", "value": "HIGH", "inline": True},
                {"name": "Timeframe", "value": "swing", "inline": True},
                {"name": "Magnitude", "value": "±$5", "inline": True},
                {"name": "SL", "value": "$98.00", "inline": True},
                {"name": "TP1", "value": "$105.00", "inline": True},
                {"name": "TP2", "value": "$110.00", "inline": True},
                {"name": "TP3", "value": "$115.00", "inline": True},
            ],
            "footer": {"text": "sources: 5"},
        },
        "vault_md": "# TSLA — !all Analysis\n\nbody",
        "cached_at": time.time() - 120,  # 2 minutes ago
    }
    await cache.set_cached_all("TSLA", payload)

    gather_calls = {"n": 0}

    async def _no_gather(ticker):
        gather_calls["n"] += 1
        return {}

    monkeypatch.setattr(aggregator, "_gather_all_sources", _no_gather)

    await aggregator.handle_all("TSLA", "ch1", "msg1")

    # gather must NOT be called on a cache hit
    assert gather_calls["n"] == 0
    # exactly one "Analyzing..." reply + one embed send
    assert len(captured_sends["reply"]) == 1
    assert len(captured_sends["embed"]) == 1
    embed = captured_sends["embed"][0][2]
    # cache age was injected into the footer text by handle_all
    assert "cached" in embed["footer"]["text"]


# ---------------------------------------------------------------------------
# Partial source failure: <source>: unavailable surfaces in sources_used
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_partial_source_failure_continues(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Even if one source raised inside the gather (surfaced as
    `<source>: unavailable`), the embed should still be produced with the
    label propagated through to sources_used."""

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_factory(
            source_status=["sec: unavailable"],
            sources_surfaced=["news", "twitter_db"],
        ),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    async def _synthesize(**_kwargs):
        return "Bullish narrative even with one source down.", "ok"

    monkeypatch.setattr(narrator, "synthesize_narrative", _synthesize)

    await aggregator.handle_all("AAPL", "ch", "m")

    assert len(captured_sends["embed"]) == 1
    embed = captured_sends["embed"][0][2]
    # PR2: failed sources land in source_failures (not rendered in embed); the
    # embed Sources line and footer count both reflect sources_surfaced only.
    desc = embed["description"]
    assert "news" in desc
    assert "twitter_db" in desc
    assert "sources: 2" in embed["footer"]["text"]


# ---------------------------------------------------------------------------
# Score gate: <4 anchors -> SL/TP1/TP2/TP3 all "—"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_low_anchor_count_suppresses_trade_plan(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """No score, no technical -> direction NEUTRAL & confidence LOW -> all
    SL/TP fields render as the em-dash placeholder."""

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _empty_gather_factory(["score: unavailable"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    async def _synthesize(**_kwargs):
        return "Some narrative.", "ok"

    monkeypatch.setattr(narrator, "synthesize_narrative", _synthesize)

    await aggregator.handle_all("ZZZZ", "ch", "m")

    embed = captured_sends["embed"][0][2]
    # Direction NEUTRAL is in description.
    assert "NEUTRAL" in embed["description"]
    # All four trade-plan fields -> em-dash.
    fields_by_name = {f["name"]: f["value"] for f in embed["fields"]}
    for key in ("SL", "TP1", "TP2", "TP3"):
        assert fields_by_name[key] == "—", f"{key} should be — but is {fields_by_name[key]!r}"
    # Color is neutral when confidence=LOW.
    assert embed["color"] == COLOR_NEUTRAL


# ---------------------------------------------------------------------------
# Empty LLM result -> data-only fallback narrative
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_empty_llm_falls_back_to_data_only(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """When `synthesize_narrative` returns ('', 'fallback_data_only'), the
    aggregator must call `output_filter.render_data_only_fallback` and the
    embed description should contain its sentinel text."""

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_factory(["news: ok"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    async def _empty(**_kwargs):
        return "", "fallback_data_only"

    monkeypatch.setattr(narrator, "synthesize_narrative", _empty)

    await aggregator.handle_all("MSFT", "ch", "m")

    embed = captured_sends["embed"][0][2]
    # `render_data_only_fallback` produces this exact prefix.
    assert "Narrative auto-redacted" in embed["description"]


# ---------------------------------------------------------------------------
# Path traversal: ../../etc/passwd is rejected by is_valid_ticker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_path_traversal_ticker_rejected(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Invalid ticker -> plain reply with 'Invalid', NO embed send, NO
    gather call, NO vault write."""

    gather_calls = {"n": 0}

    async def _gather(ticker):
        gather_calls["n"] += 1
        return {}

    monkeypatch.setattr(aggregator, "_gather_all_sources", _gather)

    await aggregator.handle_all("../../etc/passwd", "ch", "m")

    # The Analyzing... reply was NOT sent; only an "Invalid ticker" reply.
    assert any("Invalid" in r[2] for r in captured_sends["reply"])
    assert len(captured_sends["embed"]) == 0
    assert gather_calls["n"] == 0
    # No vault file created.
    final = os.path.join(str(vault_path), "tickers")
    if os.path.exists(final):
        assert not any(f.endswith("-all.md") for f in os.listdir(final))


# ---------------------------------------------------------------------------
# Sanity check: cache populated after a successful first run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_all_first_run_populates_cache(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """After the first run, `cache.get_cached_all` must return a populated
    payload (proving set_cached_all was called inside single_flight_get)."""

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_factory(["news: ok"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    async def _synthesize(**_kwargs):
        return "Bullish narrative.", "ok"

    monkeypatch.setattr(narrator, "synthesize_narrative", _synthesize)

    await aggregator.handle_all("AMD", "ch", "m")

    cached = await cache.get_cached_all("AMD")
    assert cached is not None
    assert "embed" in cached
    assert "vault_md" in cached
    assert cached["embed"]["title"].startswith("$AMD")
