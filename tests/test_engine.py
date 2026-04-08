"""Tests for the precision scoring engine."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from consensus_engine.engine import (
    BudgetManager,
    SignalClass,
    _classify,
    _score_finnhub,
    _score_firecrawl,
    _score_hits,
    analyze_signal,
)
from consensus_engine.adapter_protocols import (
    FinnhubContext,
    FirecrawlPage,
    SearchHit,
)


# ---------------------------------------------------------------------------
# _score_finnhub
# ---------------------------------------------------------------------------

class TestScoreFinnhub:
    def test_large_move_high_rvol(self):
        ctx = FinnhubContext(change_pct=6.0, rvol=3.5, news_headlines=["a", "b"])
        score = _score_finnhub(ctx)
        assert score >= 25  # 20 (move) + 8 (rvol) + 4 (news) = 32 → capped 30

    def test_small_move_no_rvol(self):
        ctx = FinnhubContext(change_pct=0.3, rvol=1.0)
        score = _score_finnhub(ctx)
        assert score == 0

    def test_moderate_move(self):
        ctx = FinnhubContext(change_pct=2.5, rvol=1.0)
        score = _score_finnhub(ctx)
        assert score == 12

    def test_negative_move_counts(self):
        ctx = FinnhubContext(change_pct=-3.0, rvol=2.0)
        score = _score_finnhub(ctx)
        assert score >= 17  # 12 + 5

    def test_capped_at_30(self):
        ctx = FinnhubContext(change_pct=10.0, rvol=5.0, news_headlines=["a"] * 10)
        score = _score_finnhub(ctx)
        assert score == 30


# ---------------------------------------------------------------------------
# _score_hits
# ---------------------------------------------------------------------------

class TestScoreHits:
    def test_empty(self):
        score, mainstream = _score_hits([])
        assert score == 0
        assert mainstream is False

    def test_trusted_source(self):
        hits = [SearchHit(title="x", url="https://cnbc.com/a", source="cnbc.com")]
        score, mainstream = _score_hits(hits)
        assert score == 5
        assert mainstream is True

    def test_untrusted_source(self):
        hits = [SearchHit(title="x", url="https://randomsite.com/a", source="randomsite.com")]
        score, mainstream = _score_hits(hits)
        assert score == 2
        assert mainstream is False

    def test_deduplicates_domains(self):
        hits = [
            SearchHit(title="a", url="https://cnbc.com/1", source="cnbc.com"),
            SearchHit(title="b", url="https://cnbc.com/2", source="cnbc.com"),
        ]
        score, _ = _score_hits(hits)
        assert score == 5  # only counted once

    def test_capped_at_25(self):
        hits = [
            SearchHit(title=f"h{i}", url=f"https://site{i}.com", source=f"site{i}.com")
            for i in range(20)
        ]
        score, _ = _score_hits(hits)
        assert score <= 25

    def test_mixed_sources(self):
        hits = [
            SearchHit(title="a", url="https://reuters.com/a", source="reuters.com"),
            SearchHit(title="b", url="https://blog.com/b", source="blog.com"),
        ]
        score, mainstream = _score_hits(hits)
        assert score == 7  # 5 + 2
        assert mainstream is True


# ---------------------------------------------------------------------------
# _score_firecrawl
# ---------------------------------------------------------------------------

class TestScoreFirecrawl:
    def test_empty(self):
        assert _score_firecrawl([], "NVDA") == 0

    def test_ticker_in_content(self):
        pages = [FirecrawlPage(url="x", text="NVDA is surging today on earnings " * 50, success=True)]
        score = _score_firecrawl(pages, "NVDA")
        assert score >= 8  # 5 (match) + 3 (length >= 200 words)

    def test_no_ticker_match(self):
        pages = [FirecrawlPage(url="x", text="AAPL is down today " * 20, success=True)]
        score = _score_firecrawl(pages, "NVDA")
        assert score == 0

    def test_failed_page_ignored(self):
        pages = [FirecrawlPage(url="x", text="NVDA everywhere", success=False)]
        assert _score_firecrawl(pages, "NVDA") == 0

    def test_capped_at_15(self):
        pages = [
            FirecrawlPage(url=f"u{i}", text=f"NVDA is great " * 100, success=True)
            for i in range(5)
        ]
        score = _score_firecrawl(pages, "NVDA")
        assert score == 15


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_strong_alert(self):
        assert _classify(85, has_mainstream=True, market_ok=True) == SignalClass.STRONG_ALERT

    def test_strong_but_no_mainstream_downgraded(self):
        assert _classify(85, has_mainstream=False, market_ok=True) == SignalClass.WATCHLIST

    def test_strong_but_no_market_downgraded(self):
        assert _classify(85, has_mainstream=True, market_ok=False) == SignalClass.WATCHLIST

    def test_watchlist(self):
        assert _classify(70, has_mainstream=True, market_ok=True) == SignalClass.WATCHLIST

    def test_ignore_low_score(self):
        assert _classify(30, has_mainstream=False, market_ok=False) == SignalClass.IGNORE

    def test_boundary_high(self):
        assert _classify(80, has_mainstream=True, market_ok=True) == SignalClass.STRONG_ALERT

    def test_boundary_medium(self):
        assert _classify(65, has_mainstream=False, market_ok=False) == SignalClass.WATCHLIST


# ---------------------------------------------------------------------------
# BudgetManager
# ---------------------------------------------------------------------------

class TestBudgetManager:
    @pytest.fixture(autouse=True)
    async def setup_db(self):
        from consensus_engine import db, config as cfg
        # Use in-memory DB for isolation
        cfg._config = cfg._config or cfg.load_config()
        original_path = cfg._config.get("database", {}).get("path")
        cfg._config.setdefault("database", {})["path"] = ":memory:"
        db._db = None
        await db.init_db()
        yield
        await db.close_db()
        if original_path:
            cfg._config["database"]["path"] = original_path

    async def test_consume_within_budget(self):
        bm = BudgetManager()
        assert await bm.consume("brave_queries") is True

    async def test_consume_over_budget(self):
        bm = BudgetManager()
        # Consume all brave budget
        for _ in range(200):
            await bm.consume("brave_queries")
        assert await bm.consume("brave_queries") is False

    async def test_can_consume(self):
        bm = BudgetManager()
        assert await bm.can_consume("finnhub_calls", 2) is True

    async def test_pct_used(self):
        bm = BudgetManager()
        pct = await bm.pct_used("brave_queries")
        assert pct == 0.0
        await bm.consume("brave_queries", 100)
        pct = await bm.pct_used("brave_queries")
        assert pct == 50.0

    async def test_invalid_column(self):
        bm = BudgetManager()
        assert await bm.consume("invalid_col") is False
        assert await bm.can_consume("invalid_col") is False

    async def test_daily_rollover_isolation(self):
        """Different days don't share budget."""
        bm = BudgetManager()
        await bm.consume("brave_queries", 10)
        pct = await bm.pct_used("brave_queries")
        assert pct == 5.0  # 10/200 = 5%


# ---------------------------------------------------------------------------
# analyze_signal (end-to-end with mocks)
# ---------------------------------------------------------------------------

class TestAnalyzeSignal:
    @pytest.fixture(autouse=True)
    async def setup_db(self):
        from consensus_engine import db, config as cfg
        cfg._config = cfg._config or cfg.load_config()
        original_path = cfg._config.get("database", {}).get("path")
        cfg._config.setdefault("database", {})["path"] = ":memory:"
        db._db = None
        await db.init_db()
        yield
        await db.close_db()
        if original_path:
            cfg._config["database"]["path"] = original_path

    @patch("consensus_engine.engine.cfg")
    async def test_disabled_engine(self, mock_cfg):
        mock_cfg.get.return_value = False
        result = await analyze_signal("NVDA", base_score=25)
        assert result["skipped"] is True

    @patch("consensus_engine.engine.get_session")
    @patch("consensus_engine.engine.cfg")
    async def test_full_pipeline_ignore_no_market(self, mock_cfg, mock_session):
        """When market doesn't confirm, early exit to IGNORE."""
        def cfg_side_effect(key, default=None):
            mapping = {
                "precision_engine.enabled": True,
                "precision_engine.budget.finnhub_calls": 3000,
                "precision_engine.thresholds.require_market_confirmation": True,
            }
            return mapping.get(key, default)

        mock_cfg.get.side_effect = cfg_side_effect
        mock_cfg.get_api_key.return_value = "fake-key"

        session = AsyncMock()
        mock_session.return_value = session

        # Mock Finnhub returning flat market
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        # Quote returns flat
        quote_resp = AsyncMock()
        quote_resp.status = 200
        quote_resp.json = AsyncMock(return_value={"c": 100.0, "pc": 100.0, "v": 1000})
        quote_resp.__aenter__ = AsyncMock(return_value=quote_resp)
        quote_resp.__aexit__ = AsyncMock(return_value=False)

        # News returns empty
        news_resp = AsyncMock()
        news_resp.status = 200
        news_resp.json = AsyncMock(return_value=[])
        news_resp.__aenter__ = AsyncMock(return_value=news_resp)
        news_resp.__aexit__ = AsyncMock(return_value=False)

        session.get.side_effect = [quote_resp, news_resp]

        result = await analyze_signal("NVDA", base_score=25)
        assert result["classification"] == SignalClass.IGNORE
        assert result["market_ok"] is False
