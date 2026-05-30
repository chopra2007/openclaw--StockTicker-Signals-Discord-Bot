"""B3 (#17) — per-number ticker tagging for YouTube visual chart numbers.

Feature is OFF by default (youtube.visual.per_number_ticker_tagging). These
tests cover: the prompt addendum gating, the parser capturing/validating the
per-number ticker, and the two-tier attribution in
get_youtube_visual_evidence_for_ticker (tagged → own ticker; untagged → the
video's top-mention ticker, i.e. identical to pre-B3 when nothing is tagged).
"""
from __future__ import annotations

import os
import tempfile

import pytest

from consensus_engine import db
from consensus_engine.analysis import gemini_video_parser as gvp


# ---------------------------------------------------------------------------
# Prompt gating + parser capture
# ---------------------------------------------------------------------------

def test_evidence_prompt_addendum_gated(monkeypatch):
    monkeypatch.setattr(gvp, "_EVIDENCE_PROMPT", "BASE")
    import consensus_engine.config as cfg

    monkeypatch.setattr(cfg, "get",
                        lambda k, d=None: False if "per_number_ticker_tagging" in k else d)
    assert gvp._evidence_prompt() == "BASE"

    monkeypatch.setattr(cfg, "get",
                        lambda k, d=None: True if "per_number_ticker_tagging" in k else d)
    out = gvp._evidence_prompt()
    assert out.startswith("BASE")
    assert "PER-NUMBER TICKER TAGGING" in out


def test_clean_visual_evidence_captures_valid_ticker():
    raw = [
        {"ts_sec": 1, "value": "182.40", "kind": "price", "where": "chart", "ticker": "nvda"},
        {"ts_sec": 2, "value": "164.10", "kind": "price", "where": "chart", "ticker": "$AMD"},
        {"ts_sec": 3, "value": "14.2", "kind": "price", "where": "vix overlay", "ticker": None},
        {"ts_sec": 4, "value": "99.9", "kind": "price", "where": "chart", "ticker": "NOT_A_TICKER_123"},
        {"ts_sec": 5, "value": "42.0", "kind": "price", "where": "chart"},  # no ticker key
    ]
    out = gvp._clean_visual_evidence(raw, duration_sec=600)
    by_val = {e["value"]: e for e in out}
    assert by_val["182.40"]["ticker"] == "NVDA"     # lowercased -> upper
    assert by_val["164.10"]["ticker"] == "AMD"      # $ stripped
    assert "ticker" not in by_val["14.2"]           # null -> untagged
    assert "ticker" not in by_val["99.9"]           # junk -> untagged
    assert "ticker" not in by_val["42.0"]           # missing -> untagged


# ---------------------------------------------------------------------------
# Two-tier attribution (temp DB)
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db():
    prev = db.DB_PATH
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    try:
        os.unlink(db.DB_PATH)
    except OSError:
        pass
    db.DB_PATH = prev
    db._db = None


async def _seed_multistock(video_id="vidB3"):
    # DELL is the top-mention ticker (3) of a multi-stock video; SMCI secondary.
    await db.insert_youtube_signal(video_id, "Chan", "DELL", "bullish", "high", mention_count=3)
    await db.insert_youtube_signal(video_id, "Chan", "SMCI", "bullish", "low", mention_count=1)
    await db.insert_youtube_visual_evidence(video_id, [
        {"ts_sec": 1, "value": "420.50", "kind": "price", "where": "dell chart"},          # untagged
        {"ts_sec": 2, "value": "510.43", "kind": "price", "where": "smci chart", "ticker": "SMCI"},  # B3 tagged
    ])


@pytest.mark.asyncio
async def test_tagged_number_goes_to_its_own_ticker(tmp_db):
    await _seed_multistock()
    dell = await db.get_youtube_visual_evidence_for_ticker("DELL", days=7)
    smci = await db.get_youtube_visual_evidence_for_ticker("SMCI", days=7)
    dell_vals = {r["value"] for r in dell}
    smci_vals = {r["value"] for r in smci}
    # Untagged number → top ticker (DELL). Tagged number → SMCI only, NOT DELL.
    assert "420.50" in dell_vals and "510.43" not in dell_vals
    assert "510.43" in smci_vals and "420.50" not in smci_vals


@pytest.mark.asyncio
async def test_untagged_only_is_pre_b3_behavior(tmp_db):
    """All-NULL (feature off) → only the top ticker gets the numbers."""
    vid = "vidLegacy"
    await db.insert_youtube_signal(vid, "Chan", "AAA", "bullish", "high", mention_count=5)
    await db.insert_youtube_signal(vid, "Chan", "BBB", "bullish", "low", mention_count=1)
    await db.insert_youtube_visual_evidence(vid, [
        {"ts_sec": 1, "value": "100.0", "kind": "price", "where": "chart"},
        {"ts_sec": 2, "value": "200.0", "kind": "price", "where": "chart"},
    ])
    top = await db.get_youtube_visual_evidence_for_ticker("AAA", days=7)
    sec = await db.get_youtube_visual_evidence_for_ticker("BBB", days=7)
    assert {r["value"] for r in top} == {"100.0", "200.0"}  # top ticker gets all
    assert sec == []                                          # secondary gets none
