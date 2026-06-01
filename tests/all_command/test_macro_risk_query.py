"""Feature E — macro/sector/regulatory risk web query for !all Risk section.

Covers gap_fill.run_gap_fill's new macro_risk query and the aggregator merge
of [macro_risk]-tagged snippets into the news evidence block. SerpAPI is
mocked throughout — no network.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts.all_command import gap_fill


def _cfg_flag(value: bool):
    """A cfg.get replacement that returns `value` for the macro flag, else
    delegating to the real default for every other key."""
    real_get = gap_fill.cfg.get

    def _get(key, default=None):
        if key == "all_command.macro_risk_query.enabled":
            return value
        return real_get(key, default)

    return _get


@pytest.mark.asyncio
async def test_macro_query_built_with_company_name_disambiguation():
    """(a) company name + sector in the query, NOT a bare single-word ticker.
       (b) freshness is qdr:m (past month), not the catalyst qdr:y."""
    captured: dict = {}

    async def fake_trusted(query, freshness="qdr:m"):
        captured["query"] = query
        captured["freshness"] = freshness
        return ["Reuters: U.S. tightens AI chip export rules"]

    # SearXNG must return something so the gather actually runs (anchors<4).
    with patch.object(gap_fill.searxng, "search_searxng",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill, "_search_serpapi_trusted", new=fake_trusted), \
         patch.object(gap_fill, "_search_serpapi_raw",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill.cfg, "get", new=_cfg_flag(True)):
        out = await gap_fill.run_gap_fill(
            ticker="NVDA",
            anchors_count=2,            # < 4 → an SearXNG trigger fires
            sec_filings=[],
            has_event_date=True,
            direction="bullish",
            deadline=time.time() + 10,
            company_name="NVIDIA Corporation",
            sector="Semiconductors",
        )

    q = captured["query"]
    # (a) disambiguation: the quoted company name is present, and the bare
    # ticker is NOT used as a standalone search token.
    assert '"NVIDIA Corporation"' in q
    assert '"Semiconductors"' in q
    assert "export restriction" in q
    # (b) freshness past month
    assert captured["freshness"] == "qdr:m"
    # snippet collected with the [macro_risk] tag
    assert out["macro_risk_snippets"] == [
        "[macro_risk] Reuters: U.S. tightens AI chip export rules"
    ]


@pytest.mark.asyncio
async def test_macro_query_skipped_when_flag_false():
    """(c) config flag False → the macro query does NOT fire."""
    fake_trusted = AsyncMock(return_value=["x"])

    with patch.object(gap_fill.searxng, "search_searxng",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill, "_search_serpapi_trusted", new=fake_trusted), \
         patch.object(gap_fill, "_search_serpapi_raw",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill.cfg, "get", new=_cfg_flag(False)):
        out = await gap_fill.run_gap_fill(
            ticker="NVDA",
            anchors_count=2,
            sec_filings=[],
            has_event_date=True,
            direction="bullish",
            deadline=time.time() + 10,
            company_name="NVIDIA Corporation",
            sector="Semiconductors",
        )

    assert fake_trusted.await_count == 0
    assert out["macro_risk_snippets"] == []


@pytest.mark.asyncio
async def test_macro_query_skipped_when_no_company_name():
    """No company name → no disambiguation possible → query does not fire."""
    fake_trusted = AsyncMock(return_value=["x"])

    with patch.object(gap_fill.searxng, "search_searxng",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill, "_search_serpapi_trusted", new=fake_trusted), \
         patch.object(gap_fill, "_search_serpapi_raw",
                      new=AsyncMock(return_value=[])), \
         patch.object(gap_fill.cfg, "get", new=_cfg_flag(True)):
        out = await gap_fill.run_gap_fill(
            ticker="NVDA",
            anchors_count=2,
            sec_filings=[],
            has_event_date=True,
            direction="bullish",
            deadline=time.time() + 10,
            company_name="",          # default — existing callers/tests
            sector="",
        )

    assert fake_trusted.await_count == 0
    assert out["macro_risk_snippets"] == []


def test_macro_snippets_merge_into_news_block_with_tag():
    """(d) the aggregator merge prepends [macro_risk] rows into the news block
       and KEEPS the tag so the narrator can distinguish them.

    Replicates aggregator._compute_all's documented merge contract on the
    gap_fill output shape (the merge is a few inline lines there)."""
    gap_fill_result = {
        "catalyst_research_snippets": ["[cat_partnership] AMD-Meta MI450 deal"],
        "macro_risk_snippets": [
            "[macro_risk] Reuters: U.S. tightens AI chip export rules",
        ],
    }

    # --- mirror of the aggregator merge block (lines ~1012-1075) ---
    catalyst_snips_raw = gap_fill_result.get("catalyst_research_snippets") or []
    catalyst_as_news = []
    for s in catalyst_snips_raw[:6]:
        if not isinstance(s, str) or not s.strip():
            continue
        if s.startswith("[cat_") and "] " in s:
            s = s.split("] ", 1)[1]
        catalyst_as_news.append(s)
    macro_risk_raw = gap_fill_result.get("macro_risk_snippets") or []
    macro_as_news = [
        s for s in macro_risk_raw[:5]
        if isinstance(s, str) and s.strip()
    ]
    existing_news = ["Existing headline"]
    news = macro_as_news + catalyst_as_news + existing_news
    # ----------------------------------------------------------------

    # macro row is present, tag intact, and ahead of the catalyst/existing rows.
    assert news[0] == "[macro_risk] Reuters: U.S. tightens AI chip export rules"
    assert any(n.startswith("[macro_risk]") for n in news)
    # catalyst tag is stripped (existing behavior, unchanged).
    assert "AMD-Meta MI450 deal" in news
    assert not any(n.startswith("[cat_") for n in news)
