"""Tests for Gemini budget + user command rate limit (Phase P7)."""
import pytest

from consensus_engine import db, config as cfg
from consensus_engine.engine import BudgetManager


@pytest.fixture(autouse=True)
def _config():
    cfg.load_config()


@pytest.fixture
async def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_budget.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    await db.init_db()
    yield
    await db.close_db()


# --- Gemini token budget ----------------------------------------------------


@pytest.mark.asyncio
async def test_consume_gemini_under_budget(tmp_db):
    bm = BudgetManager()
    ok = await bm.consume_gemini(input_tokens=10_000, output_tokens=2_000)
    assert ok is True
    pct_in = await bm.pct_used("gemini_input_tokens")
    pct_out = await bm.pct_used("gemini_output_tokens")
    pct_calls = await bm.pct_used("gemini_video_calls")
    assert 0.0 < pct_in < 100.0
    assert 0.0 < pct_out < 100.0
    assert 0.0 < pct_calls < 100.0
    # peek still ok
    assert await bm.can_consume_gemini(50_000) is True


@pytest.mark.asyncio
async def test_consume_gemini_over_budget(tmp_db):
    """Saturating gemini_video_calls prevents further can_consume_gemini."""
    bm = BudgetManager()
    call_cap = int(cfg.get("precision_engine.budget.gemini_video_calls", 100))
    # Saturate the call cap in one big bump
    for _ in range(call_cap):
        await bm.consume("gemini_video_calls", 1)
    assert await bm.can_consume_gemini(1) is False


@pytest.mark.asyncio
async def test_consume_gemini_over_input_tokens(tmp_db):
    """Exceeding input-token cap flips can_consume_gemini False."""
    bm = BudgetManager()
    tok_cap = int(cfg.get("precision_engine.budget.gemini_input_tokens", 2_000_000))
    await bm.consume("gemini_input_tokens", tok_cap)
    assert await bm.can_consume_gemini(estimated_tokens=1) is False


# --- User rate limit --------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_user_yt(tmp_db):
    for _ in range(5):
        await db.log_user_command("user1", "yt")
    # 5 logged in window of 3600s — limit=5 reached
    assert await db.check_user_rate_limit("user1", "yt", limit=5, window_sec=3600) is True
    # Still under if limit is 6
    assert await db.check_user_rate_limit("user1", "yt", limit=6, window_sec=3600) is False


@pytest.mark.asyncio
async def test_rate_limit_user_yt_other_user_unaffected(tmp_db):
    for _ in range(5):
        await db.log_user_command("user1", "yt")
    assert await db.check_user_rate_limit("user2", "yt", limit=5, window_sec=3600) is False
    # Different command for user1 also unaffected
    assert await db.check_user_rate_limit("user1", "scan", limit=5, window_sec=3600) is False


# --- Rate limiter entry -----------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_rate_limiter_entry():
    from consensus_engine.utils.rate_limiter import rate_limiter
    # interval registered at 0.5s (2 qps)
    assert rate_limiter._min_intervals.get("gemini") == 0.5
    ok = await rate_limiter.acquire("gemini")
    assert ok is True
