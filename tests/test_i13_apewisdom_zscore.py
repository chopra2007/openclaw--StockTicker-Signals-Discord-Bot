"""I13 (signal-features-2026-06-09) — ApeWisdom mention-count z-score gate.

PRODUCER  — scan_apewisdom persists numeric mention counts to apewisdom_mentions.
BASELINE  — get_apewisdom_baseline / get_latest_apewisdom_mentions math.
SCORER    — _compute_social_breakdown / _compute_apewisdom_zscore_pts flag gate.

Assertions:
  (1) PRODUCER: scan_apewisdom calls upsert_apewisdom_mentions for each ticker;
      DB row is persisted with mentions, rank, mentions_24h_ago.
  (2) BASELINE: get_apewisdom_baseline returns correct mean/std/sample_days.
  (3) SCORER flag-ON:
      (a) z-surge + hard corroborator -> +10
      (b) z-surge alone (no corroborator) -> 0
      (c) thin baseline (< 14 days) -> 0
      (d) stale mention data (outside recency_window "apewisdom" cap) -> 0
  (4) SCORER flag-OFF: legacy presence-only +10 (byte-identical to pre-I13 code).
  (5) score_ticker integration: apewisdom_zscore flag-ON with mocked DB data.
"""
import contextlib
import math
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.cross_reference import (
    _compute_apewisdom_zscore_pts,
    _compute_social_breakdown,
    score_ticker,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


def _flag_on(monkeypatch, extra: dict | None = None):
    """Force features.apewisdom_zscore.enabled ON; all other flags stay at default."""
    overrides = {"features.apewisdom_zscore.enabled": True}
    if extra:
        overrides.update(extra)
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: overrides[k] if k in overrides else real_get(k, d),
    )


def _flag_off(monkeypatch):
    """Ensure features.apewisdom_zscore.enabled is OFF (conftest default)."""
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: False if k == "features.apewisdom_zscore.enabled"
        else real_get(k, d),
    )


def _social(
    *,
    apewisdom_count: int = 1,
    mentions: int = 0,
    sample_days: int = 0,
    mean: float = 0.0,
    std: float = 0.0,
    captured_at: float | None = None,
) -> dict:
    """Build a social_data dict for the scorer."""
    d: dict = {
        "apewisdom": apewisdom_count,
        "stocktwits": 0,
        "reddit": 0,
        "google_trends": 0,
    }
    # These keys are only present when the flag is ON and _run_social_check ran.
    d["apewisdom_mentions"] = mentions
    d["apewisdom_baseline"] = {"mean": mean, "std": std, "sample_days": sample_days}
    d["apewisdom_captured_at"] = captured_at if captured_at is not None else time.time()
    return d


def _mature_social(*, z: float = 3.0, sec_hit: bool = False,
                   catalyst_passed: bool = False, technical_pts: int = 0) -> dict:
    """Build a social_data with 20-day mature baseline and mentions at z sigma above mean."""
    mean = 100.0
    std = 50.0
    mentions = int(mean + z * std)
    return _social(
        apewisdom_count=1,
        mentions=mentions,
        sample_days=20,
        mean=mean,
        std=std,
        captured_at=time.time(),  # fresh
    )


# ---------------------------------------------------------------------------
# 1. PRODUCER — upsert_apewisdom_mentions called by scan_apewisdom
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_producer_persists_mention_count():
    """scan_apewisdom calls upsert_apewisdom_mentions for each valid ticker."""
    fake_api_response = {
        "results": [
            {"ticker": "NVDA", "mentions": 651, "rank": 1, "mentions_24h_ago": 331},
            {"ticker": "MU",   "mentions": 375, "rank": 2, "mentions_24h_ago": 363},
            {"ticker": "SPY",  "mentions": 292, "rank": 3, "mentions_24h_ago": 144},
        ]
    }
    calls: list[dict] = []

    async def fake_upsert(ticker, mentions, rank, mentions_24h_ago, captured_at=None):
        calls.append({"ticker": ticker, "mentions": mentions, "rank": rank,
                      "mentions_24h_ago": mentions_24h_ago})

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=fake_api_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    from consensus_engine.scanners import social as social_mod
    with (
        patch.object(social_mod, "cfg") as mock_cfg,
        patch("consensus_engine.scanners.social.get_session", AsyncMock(return_value=mock_session)),
        patch("consensus_engine.scanners.social.rate_limiter") as mock_rl,
        patch("consensus_engine.scanners.social.db") as mock_db,
        patch("asyncio.sleep", AsyncMock()),
    ):
        mock_cfg.get = lambda k, d=None: {
            "social.apewisdom_enabled": True,
        }.get(k, d)
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_rl.report_success = MagicMock()
        mock_rl.report_failure = MagicMock()
        mock_db.upsert_apewisdom_mentions = AsyncMock(side_effect=fake_upsert)

        signals = await social_mod.scan_apewisdom()

    # 3 tickers returned but scan fetches page 1 then tries page 2 (status!=200 mock
    # returns 200 again for page 2 with same data) — patch to return empty on page 2.
    # The key assertions: every ticker on page 1 was persisted.
    ticker_calls = {c["ticker"] for c in calls}
    assert "NVDA" in ticker_calls
    assert "MU" in ticker_calls
    assert "SPY" in ticker_calls

    nvda_call = next(c for c in calls if c["ticker"] == "NVDA")
    assert nvda_call["mentions"] == 651
    assert nvda_call["rank"] == 1
    assert nvda_call["mentions_24h_ago"] == 331


@pytest.mark.asyncio
async def test_producer_persists_null_24h_ago():
    """mentions_24h_ago=None when the API omits it (older records)."""
    fake_api_response = {
        "results": [
            {"ticker": "TSLA", "mentions": 200, "rank": 5},  # no mentions_24h_ago key
        ]
    }
    persisted = {}

    async def fake_upsert(ticker, mentions, rank, mentions_24h_ago, captured_at=None):
        persisted["mentions_24h_ago"] = mentions_24h_ago

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=fake_api_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    from consensus_engine.scanners import social as social_mod
    with (
        patch.object(social_mod, "cfg") as mock_cfg,
        patch("consensus_engine.scanners.social.get_session", AsyncMock(return_value=mock_session)),
        patch("consensus_engine.scanners.social.rate_limiter") as mock_rl,
        patch("consensus_engine.scanners.social.db") as mock_db,
        patch("asyncio.sleep", AsyncMock()),
    ):
        mock_cfg.get = lambda k, d=None: {"social.apewisdom_enabled": True}.get(k, d)
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_rl.report_success = MagicMock()
        mock_rl.report_failure = MagicMock()
        mock_db.upsert_apewisdom_mentions = AsyncMock(side_effect=fake_upsert)

        await social_mod.scan_apewisdom()

    assert persisted.get("mentions_24h_ago") is None


@pytest.mark.asyncio
async def test_producer_db_error_does_not_break_scan():
    """A DB write failure logs a warning but scan still returns signals."""
    fake_api_response = {
        "results": [
            {"ticker": "NVDA", "mentions": 100, "rank": 1, "mentions_24h_ago": 80},
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=fake_api_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    from consensus_engine.scanners import social as social_mod
    with (
        patch.object(social_mod, "cfg") as mock_cfg,
        patch("consensus_engine.scanners.social.get_session", AsyncMock(return_value=mock_session)),
        patch("consensus_engine.scanners.social.rate_limiter") as mock_rl,
        patch("consensus_engine.scanners.social.db") as mock_db,
        patch("asyncio.sleep", AsyncMock()),
    ):
        mock_cfg.get = lambda k, d=None: {"social.apewisdom_enabled": True}.get(k, d)
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_rl.report_success = MagicMock()
        mock_rl.report_failure = MagicMock()
        mock_db.upsert_apewisdom_mentions = AsyncMock(side_effect=RuntimeError("db gone"))

        signals = await social_mod.scan_apewisdom()

    # Scan returns the signal despite the DB error.
    assert any(s.ticker == "NVDA" for s in signals)


# ---------------------------------------------------------------------------
# 2. BASELINE — get_apewisdom_baseline math
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_baseline_empty_returns_zero_struct():
    """Empty table returns {"mean":0.0,"std":0.0,"sample_days":0}."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    result = await db_mod.get_apewisdom_baseline("NVDA")
    assert result == {"mean": 0.0, "std": 0.0, "sample_days": 0}

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_baseline_single_day():
    """One day with 200 mentions -> mean=200, std=0, sample_days=1."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    now = time.time()
    await db_mod.upsert_apewisdom_mentions("NVDA", 200, 1, None, captured_at=now)
    await db_mod.upsert_apewisdom_mentions("NVDA", 180, 1, None, captured_at=now - 60)  # same day

    result = await db_mod.get_apewisdom_baseline("NVDA")
    # MAX(200, 180) = 200 for the one day
    assert result["sample_days"] == 1
    assert result["mean"] == pytest.approx(200.0)
    assert result["std"] == pytest.approx(0.0)

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_baseline_two_days_std():
    """Two-day baseline: mean=150, std=50 (population)."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    # Anchor to today's UTC midnight (not "now - 86400") so the two rows always
    # land on different calendar days — "now - 86400" vs "now - 3600" can both
    # fall on the same UTC date when "now" is within an hour of UTC midnight.
    today_utc_midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    # Day 1 max: 200 (yesterday); Day 2 max: 100 (today)
    await db_mod.upsert_apewisdom_mentions("NVDA", 200, 1, None, captured_at=today_utc_midnight - 3600)
    await db_mod.upsert_apewisdom_mentions("NVDA", 100, 1, None, captured_at=today_utc_midnight + 3600)

    result = await db_mod.get_apewisdom_baseline("NVDA")
    assert result["sample_days"] == 2
    assert result["mean"] == pytest.approx(150.0)
    # population std of [200, 100]: variance = ((200-150)^2 + (100-150)^2)/2 = 2500 -> std=50
    assert result["std"] == pytest.approx(50.0)

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_baseline_respects_lookback_window():
    """Rows older than lookback_days are excluded."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    now = time.time()
    # Insert a row 40 days ago (outside the default 30-day window).
    await db_mod.upsert_apewisdom_mentions("NVDA", 999, 1, None, captured_at=now - 40 * 86400)
    # Insert a row today.
    await db_mod.upsert_apewisdom_mentions("NVDA", 100, 1, None, captured_at=now - 3600)

    result = await db_mod.get_apewisdom_baseline("NVDA", lookback_days=30)
    assert result["sample_days"] == 1
    assert result["mean"] == pytest.approx(100.0)

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent():
    """get_latest_apewisdom_mentions returns the newest row."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    now = time.time()
    await db_mod.upsert_apewisdom_mentions("NVDA", 100, 5, 80, captured_at=now - 7200)
    await db_mod.upsert_apewisdom_mentions("NVDA", 300, 2, 150, captured_at=now - 60)

    row = await db_mod.get_latest_apewisdom_mentions("NVDA")
    assert row is not None
    assert row["mentions"] == 300
    assert row["rank"] == 2
    assert row["mentions_24h_ago"] == 150

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_missing():
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    row = await db_mod.get_latest_apewisdom_mentions("ZZZZZ")
    assert row is None

    db_mod._db = None
    db_mod.DB_PATH = None


# ---------------------------------------------------------------------------
# 3. SCORER flag-ON: _compute_apewisdom_zscore_pts pure helper
# ---------------------------------------------------------------------------

def test_zscore_surge_with_sec_corroborator_gives_pts(monkeypatch):
    """z > threshold + SEC hit -> +10."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=False, technical_pts=0
    )
    assert result == 10


def test_zscore_surge_with_catalyst_corroborator_gives_pts(monkeypatch):
    """z > threshold + catalyst_passed -> +10."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=False, catalyst_passed=True, technical_pts=0
    )
    assert result == 10


def test_zscore_surge_with_technical_corroborator_gives_pts(monkeypatch):
    """z > threshold + 2 technical filters -> +10."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=False, catalyst_passed=False, technical_pts=2
    )
    assert result == 10


def test_zscore_surge_no_corroborator_gives_zero(monkeypatch):
    """Pure Reddit/ApeWisdom spike with zero hard corroborator earns 0."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=False, catalyst_passed=False, technical_pts=0
    )
    assert result == 0


def test_zscore_one_technical_filter_not_enough(monkeypatch):
    """1 technical filter does not count (spec: >= 2 filters needed)."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=False, catalyst_passed=False, technical_pts=1
    )
    assert result == 0


def test_thin_baseline_gives_zero(monkeypatch):
    """< 14 days of baseline -> 0 (not the old +10)."""
    _flag_on(monkeypatch)
    social = _social(
        apewisdom_count=1,
        mentions=500,
        sample_days=5,  # thin
        mean=100.0,
        std=50.0,
        captured_at=time.time(),
    )
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert result == 0


def test_below_threshold_z_gives_zero(monkeypatch):
    """mentions only 1 sigma above mean (< 2.0 threshold) -> 0."""
    _flag_on(monkeypatch)
    mean, std = 100.0, 50.0
    mentions = int(mean + 1.0 * std)  # z = 1.0
    social = _social(
        apewisdom_count=1,
        mentions=mentions,
        sample_days=20,
        mean=mean,
        std=std,
        captured_at=time.time(),
    )
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert result == 0


def test_stale_data_gives_zero(monkeypatch):
    """Mention data older than the recency_window 'apewisdom' cap -> 0."""
    _flag_on(monkeypatch)
    # captured_at 25 hours ago (> 1440 min cap)
    stale_ts = time.time() - 25 * 3600
    mean, std = 100.0, 50.0
    mentions = int(mean + 4.0 * std)  # large z
    social = _social(
        apewisdom_count=1,
        mentions=mentions,
        sample_days=20,
        mean=mean,
        std=std,
        captured_at=stale_ts,
    )
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert result == 0


def test_zero_std_baseline_gives_zero(monkeypatch):
    """Zero-variance baseline -> 0 (infinite-sigma new-ticker guard)."""
    _flag_on(monkeypatch)
    social = _social(
        apewisdom_count=1,
        mentions=999,
        sample_days=20,
        mean=100.0,
        std=0.0,  # zero std
        captured_at=time.time(),
    )
    result = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert result == 0


# ---------------------------------------------------------------------------
# 4. SCORER — _compute_social_breakdown integration with flag ON/OFF
# ---------------------------------------------------------------------------

def test_flag_on_z_surge_corroborated_breakdown(monkeypatch):
    """With flag ON, a z-surge + SEC hit produces social_apewisdom=10."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    breakdown = _compute_social_breakdown(
        social, sec_hit=True, catalyst_passed=False, technical_pts=0
    )
    assert breakdown["social_apewisdom"] == 10


def test_flag_on_z_surge_no_corroborator_breakdown(monkeypatch):
    """With flag ON, a z-surge alone (no corroborator) produces social_apewisdom=0."""
    _flag_on(monkeypatch)
    social = _mature_social(z=3.0)
    breakdown = _compute_social_breakdown(
        social, sec_hit=False, catalyst_passed=False, technical_pts=0
    )
    assert breakdown["social_apewisdom"] == 0


def test_flag_on_thin_baseline_breakdown(monkeypatch):
    """With flag ON, thin baseline -> social_apewisdom=0 (not the old +10)."""
    _flag_on(monkeypatch)
    social = _social(
        apewisdom_count=1, mentions=999, sample_days=3,
        mean=100.0, std=50.0, captured_at=time.time()
    )
    breakdown = _compute_social_breakdown(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert breakdown["social_apewisdom"] == 0


def test_flag_on_stale_breakdown(monkeypatch):
    """With flag ON, stale mention data -> social_apewisdom=0."""
    _flag_on(monkeypatch)
    stale_ts = time.time() - 25 * 3600  # 25h ago
    mean, std = 100.0, 50.0
    social = _social(
        apewisdom_count=1,
        mentions=int(mean + 5.0 * std),
        sample_days=20,
        mean=mean,
        std=std,
        captured_at=stale_ts,
    )
    breakdown = _compute_social_breakdown(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert breakdown["social_apewisdom"] == 0


def test_flag_off_legacy_presence_score(monkeypatch):
    """Flag OFF -> legacy presence-only +10, byte-identical to pre-I13 code."""
    _flag_off(monkeypatch)
    # Even with stale data / thin baseline, flag OFF must give the old +10.
    social = {
        "apewisdom": 1,
        "stocktwits": 0,
        "reddit": 0,
        "google_trends": 0,
    }
    breakdown = _compute_social_breakdown(social)
    assert breakdown["social_apewisdom"] == 10


def test_flag_off_no_apewisdom_signal(monkeypatch):
    """Flag OFF, no ApeWisdom signal -> 0."""
    _flag_off(monkeypatch)
    social = {"apewisdom": 0, "stocktwits": 0, "reddit": 0, "google_trends": 0}
    breakdown = _compute_social_breakdown(social)
    assert breakdown["social_apewisdom"] == 0


def test_flag_off_other_social_sources_unaffected(monkeypatch):
    """Flag OFF/ON does not touch stocktwits/reddit/google_trends terms."""
    _flag_off(monkeypatch)
    social = {
        "apewisdom": 0,
        "stocktwits": 1,
        "reddit": 3,
        "google_trends": 1,
    }
    bd = _compute_social_breakdown(social)
    assert bd["social_apewisdom"] == 0
    assert bd["social_stocktwits"] == 10
    assert bd["social_reddit"] == 10
    assert bd["google_trends"] == 5


# ---------------------------------------------------------------------------
# 5. Common-recency-window: stale leg test (§8.B)
# ---------------------------------------------------------------------------

def test_stale_leg_does_not_count_toward_apewisdom_score(monkeypatch):
    """A stale apewisdom leg (outside its recency cap) earns 0 regardless of z-score."""
    _flag_on(monkeypatch)
    # 25h ago — past the 1440-minute (24h) cap
    stale_ts = time.time() - 25 * 3600
    mean, std = 50.0, 10.0
    mentions = int(mean + 5.0 * std)  # z = 5.0 — would easily pass the threshold
    social = _social(
        apewisdom_count=1,
        mentions=mentions,
        sample_days=20,
        mean=mean,
        std=std,
        captured_at=stale_ts,
    )
    pts = _compute_apewisdom_zscore_pts(
        social, sec_hit=True, catalyst_passed=True, technical_pts=5
    )
    assert pts == 0, "Stale leg must contribute 0 — no phantom confluence from an EOD-lagged spike"


# ---------------------------------------------------------------------------
# 6. score_ticker integration (mocked DB + gather)
# ---------------------------------------------------------------------------

from consensus_engine.analysis.consolidation import ConsolidationResult as _CR
from consensus_engine.models import CatalystResult

_FAKE_CONS = _CR(
    fired=True,
    consolidated_id=1,
    effective_n_clusters=2,
    combined_log_odds=1.0,
    consensus_boost=20,
    sources_seen=[],
    reason="consolidated",
)


def _patch_fetchers(stack_social: dict):
    """Patch the individual _run_* fetchers (the established score_ticker test
    pattern — see tests/test_cross_reference.py) instead of asyncio.gather, so
    asyncio.TimeoutError and the await machinery stay real.

    `passed` on CatalystResult is a derived property — truthy when
    news_sources + summary exist.
    """
    catalyst = CatalystResult(
        ticker="NVDA",
        catalyst_summary="Beat by 40%",
        catalyst_type="Earnings Beat",
        news_sources=["finnhub"],
        catalyst_body="Beat by 40%",
    )
    return (
        patch("consensus_engine.cross_reference._run_news_cascade",
              new=AsyncMock(return_value=catalyst)),
        patch("consensus_engine.cross_reference._run_sec_check",
              new=AsyncMock(return_value=(True, "CEO bought $500k"))),
        patch("consensus_engine.cross_reference._run_social_check",
              new=AsyncMock(return_value=stack_social)),
        patch("consensus_engine.cross_reference._run_technical",
              new=AsyncMock(return_value=None)),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new=AsyncMock(return_value=[])),
        patch("consensus_engine.cross_reference._run_options_check",
              new=AsyncMock(return_value=None)),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new=AsyncMock(return_value=None)),
    )


@pytest.mark.asyncio
async def test_score_ticker_flag_on_z_surge_corroborated(monkeypatch):
    """score_ticker: flag ON, z-surge + catalyst + SEC -> social_apewisdom=10."""
    mean, std = 100.0, 50.0
    mentions = int(mean + 3.0 * std)
    social = _social(
        apewisdom_count=1, mentions=mentions,
        sample_days=20, mean=mean, std=std, captured_at=time.time(),
    )

    _flag_on(monkeypatch)

    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers(social):
            stack.enter_context(p)
        mock_db = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch(
            "consensus_engine.analysis.consolidation.consolidate_for_ticker",
            new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch(
            "consensus_engine.cross_reference._run_llm_score",
            new_callable=AsyncMock, return_value=(0, "")))
        mock_db.get_signal_counts_by_source = AsyncMock(return_value={})
        mock_db.get_analyst_precision_lb = AsyncMock(return_value=None)
        mock_db.get_apewisdom_baseline = AsyncMock(return_value={
            "mean": mean, "std": std, "sample_days": 20
        })
        mock_db.get_latest_apewisdom_mentions = AsyncMock(return_value={
            "mentions": mentions, "rank": 3, "mentions_24h_ago": 50,
            "captured_at": time.time(),
        })
        mock_db.upsert_apewisdom_mentions = AsyncMock()

        result = await score_ticker("NVDA", base_score=30, direction="long")

    # Catalyst passed=True + sec_hit=True -> corroborated; z=3.0 > 2.0 -> +10
    assert result.breakdown.social_apewisdom == 10


@pytest.mark.asyncio
async def test_score_ticker_flag_off_legacy_presence(monkeypatch):
    """score_ticker: flag OFF -> legacy +10 on mere presence (apewisdom count >= 1)."""
    social = {
        "apewisdom": 1,
        "stocktwits": 0,
        "reddit": 0,
        "google_trends": 0,
    }

    _flag_off(monkeypatch)

    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers(social):
            stack.enter_context(p)
        mock_db = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch(
            "consensus_engine.analysis.consolidation.consolidate_for_ticker",
            new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch(
            "consensus_engine.cross_reference._run_llm_score",
            new_callable=AsyncMock, return_value=(0, "")))
        mock_db.get_signal_counts_by_source = AsyncMock(return_value={})
        mock_db.get_analyst_precision_lb = AsyncMock(return_value=None)
        mock_db.upsert_apewisdom_mentions = AsyncMock()

        result = await score_ticker("NVDA", base_score=30, direction="long")

    assert result.breakdown.social_apewisdom == 10


# ---------------------------------------------------------------------------
# #65 Fix 2 — social-family de-dup (flag OFF default)
# ---------------------------------------------------------------------------

def _dedup_get(monkeypatch, *, dedup_on: bool):
    """Control only the flags the family-dedup path reads; real_get for the rest."""
    overrides = {
        "scoring.multipliers": {
            "social_apewisdom": 10, "social_stocktwits": 10,
            "social_reddit": 10, "google_trends": 5,
        },
        "features.apewisdom_zscore.enabled": False,
        "features.social_family_dedup.enabled": dedup_on,
        "features.social_family_dedup.families": {
            "social_apewisdom": "retail_crowd", "social_stocktwits": "retail_crowd",
            "social_reddit": "retail_crowd", "google_trends": "search",
        },
    }
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: overrides[k] if k in overrides else real_get(k, d),
    )


def test_social_family_dedup_off_counts_all_three(monkeypatch):
    """Flag OFF -> byte-identical: all three retail sources score independently."""
    _dedup_get(monkeypatch, dedup_on=False)
    b = _compute_social_breakdown(
        {"apewisdom": 1, "stocktwits": 1, "reddit": 2, "google_trends": 1}
    )
    assert b == {
        "social_apewisdom": 10, "social_stocktwits": 10,
        "social_reddit": 10, "google_trends": 5,
    }


def test_social_family_dedup_on_collapses_retail_crowd(monkeypatch):
    """Flag ON -> retail crowd collapses to ONE vote; other families untouched."""
    _dedup_get(monkeypatch, dedup_on=True)
    b = _compute_social_breakdown(
        {"apewisdom": 1, "stocktwits": 1, "reddit": 2, "google_trends": 1}
    )
    # google_trends is a family of one -> keeps its points.
    assert b["google_trends"] == 5
    crowd = [b["social_apewisdom"], b["social_stocktwits"], b["social_reddit"]]
    assert sum(1 for x in crowd if x > 0) == 1   # exactly one survivor
    assert sum(crowd) == 10                        # one vote, not three
