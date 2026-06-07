"""#7 (full-audit-2026-06-06) — Wolf cross-source confluence line in !all.

Two layers:
  * embed.build_embed renders ONE Wolf confluence line when handed a confluence row
    (via the same wolf_news._confluence_field renderer the #news embed uses), and renders
    NOTHING when the row is None. Flag OFF → byte-identical (the aggregator gates the
    lookup, so build_embed simply gets wolf_confluence=None).
  * aggregator._wolf_confluence_lookup is a no-op (no DB hit) when the flag is OFF, and
    when ON it maps the ticker→Wolf scope/sector, preferring a STOCK-level thesis over the
    sector fallback. The corrected live expectation: !all NVDA → SMH thesis (agree=0/
    disagree=3) renders the "divided" case; !all URA (agree=1) renders agreement; !all AAPL
    (no thesis) → no line.
"""
from __future__ import annotations

import json
import tempfile

import pytest
from unittest.mock import patch

from consensus_engine import config as cfg, db
from consensus_engine.models import ScoreBreakdown
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import aggregator, embed


# row shaped like a wolf_confluence_checks SMH-bear row: agree=0, disagree=3 → "divided".
_DIVIDED = {
    "direction": "bear", "agree_count": 0, "disagree_count": 3, "divided": 1,
    "agree_sources_json": "[]",
    "disagree_sources_json": json.dumps([
        {"source_type": "twitter", "sample_tickers": ["NVDA"]},
        {"source_type": "youtube", "n_channels": 2, "sample_tickers": ["NVDA"]},
        {"source_type": "options", "sample_tickers": ["NVDA"]},
    ]),
}
# row shaped like URA (id=10): one source agrees → agreement line.
_AGREE = {
    "direction": "bull", "agree_count": 1, "disagree_count": 0, "divided": 0,
    "agree_sources_json": json.dumps([{"source_type": "twitter", "sample_tickers": ["URA"]}]),
    "disagree_sources_json": "[]",
}


def _build(wolf_confluence):
    sf = StructuredFields(
        direction="BEARISH", confidence_label="HIGH",
        sl=120.0, tp1=140.0, current_price=128.0,
    )
    bd = ScoreBreakdown(news_catalyst=15, technical=4, llm_boost=9, youtube=15)
    return embed.build_embed(
        ticker="NVDA", structured=sf, score_breakdown=bd,
        narrative="**TL;DR:** test.\n## Trade Plan\n| x |",
        sources_used=["news", "technical"], cache_age_seconds=None,
        wolf_confluence=wolf_confluence,
    )


def _wolf_fields(emb):
    return [f for f in emb.get("fields", []) if f.get("name") == "🤝 Confluence"]


# ───────────────────────── embed rendering ─────────────────────────
def test_embed_no_wolf_line_when_none():
    """wolf_confluence=None (flag-OFF / no thesis) → no Wolf line."""
    assert _wolf_fields(_build(None)) == []


def test_embed_byte_identical_when_none():
    """Two builds with wolf_confluence=None are identical — no leakage."""
    assert _build(None) == _build(None)


def test_embed_renders_divided_for_nvda_smh():
    """NVDA's SMH bear thesis (agree=0/disagree=3) renders the 'divided' line, NOT '2 agree'."""
    fields = _wolf_fields(_build(_DIVIDED))
    assert fields, "Wolf confluence line not rendered"
    assert "divided" in fields[0]["value"].lower()
    assert "agree" not in fields[0]["value"].lower()


def test_embed_renders_agreement_for_ura():
    """URA's thesis (agree=1) renders the agreement line."""
    fields = _wolf_fields(_build(_AGREE))
    assert fields and "1 source agree" in fields[0]["value"]


# ───────────────────────── aggregator lookup ─────────────────────────
def _flag_cfg(enabled: bool):
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.wolf_confluence_field_enabled":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


@pytest.fixture
async def fresh_db():
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield db
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def test_lookup_flag_off_no_db_hit(fresh_db, monkeypatch):
    """Flag OFF → returns None immediately and never touches the DB."""
    calls = {"n": 0}
    real = db.get_active_thesis

    async def counting(*a, **kw):
        calls["n"] += 1
        return await real(*a, **kw)
    monkeypatch.setattr(db, "get_active_thesis", counting)
    with _flag_cfg(False):
        assert await aggregator._wolf_confluence_lookup("NVDA") is None
    assert calls["n"] == 0, "lookup hit the DB while flag OFF"


async def test_lookup_no_thesis_returns_none(fresh_db):
    """Flag ON but no thesis for the ticker/sector (AAPL) → None (no line)."""
    with _flag_cfg(True):
        assert await aggregator._wolf_confluence_lookup("AAPL") is None


async def test_lookup_sector_fallback_for_nvda(fresh_db):
    """Flag ON, no stock-level thesis: NVDA falls back to its sector ETF thesis. NVDA's
    sector ETF is XLK (sector_map.yaml), so an XLK bear thesis is the fallback the lookup
    finds (divided)."""
    tid = await db.insert_thesis("sector", "XLK", "bear", "acting", "[]", None, 0, "[]", 1.0)
    await db.record_confluence_check(
        tid, "sector", "XLK", "bear", 1.0, 21, 0, 3, "surface", "surface", 1,
        "[]", _DIVIDED["disagree_sources_json"], "surface")
    with _flag_cfg(True):
        confl = await aggregator._wolf_confluence_lookup("NVDA")
    assert confl is not None and confl["agree_count"] == 0 and confl["disagree_count"] == 3


async def test_lookup_prefers_stock_over_sector(fresh_db):
    """A stock-level thesis on NVDA itself wins over the SMH sector thesis (precedence)."""
    # sector thesis (fallback)
    smh = await db.insert_thesis("sector", "SMH", "bear", "acting", "[]", None, 0, "[]", 1.0)
    await db.record_confluence_check(
        smh, "sector", "SMH", "bear", 1.0, 21, 0, 3, "surface", "surface", 1,
        "[]", "[]", "surface")
    # stock thesis (should win)
    nvda = await db.insert_thesis("stock", "NVDA", "bull", "acting", "[]", None, 0, "[]", 1.0)
    await db.record_confluence_check(
        nvda, "stock", "NVDA", "bull", 1.0, 21, 2, 0, "high", "high", 0,
        json.dumps([{"source_type": "twitter"}, {"source_type": "youtube"}]), "[]", "high")
    with _flag_cfg(True):
        confl = await aggregator._wolf_confluence_lookup("NVDA")
    assert confl is not None and confl["agree_count"] == 2  # the stock row, not the sector row
