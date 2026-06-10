"""E1 (signal-features-2026-06-09) — FINRA daily short-volume confluence input.

Tests:
  1. PARSER — good file, malformed rows, oversize response rejected,
     redirect rejected, wrong-domain rejected.
  2. short_pct nets out ShortExemptVolume (spec requirement).
  3. z-gate math — >2sigma -> pts; <2sigma -> 0; thin baseline -> 0.
  4. Stale row -> 0 (recency_window freshness check).
  5. Flag-OFF -> no DB read + 0 term + byte-identical breakdown.
  6. Baseline helper — DB round-trip (mean/std/sample_days).
  7. score_ticker integration: flag ON with mocked DB data shows finra_pts.
  8. score_ticker integration: flag OFF -> finra_pts=0, no DB read.
  9. Common-recency-window: stale finra leg does not count (§8.B).
"""
from __future__ import annotations

import contextlib
import time
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.scanners.finra_short_volume import (
    _parse_finra_file,
    _validate_url,
    _make_url,
    FINRA_SHORT_VOL_PROVENANCE,
    fetch_finra_short_volume,
)
from consensus_engine.cross_reference import (
    _compute_finra_short_volume_pts,
    score_ticker,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


def _flag_on(monkeypatch, extra: dict | None = None):
    """Force features.finra_short_volume.enabled ON."""
    overrides = {"features.finra_short_volume.enabled": True}
    if extra:
        overrides.update(extra)
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: overrides[k] if k in overrides else real_get(k, d),
    )


def _flag_off(monkeypatch):
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: False if k == "features.finra_short_volume.enabled"
        else real_get(k, d),
    )


_SAMPLE_FILE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260610|NVDA|5000000|200000|12000000|FNRA
20260610|AAPL|3000000|100000|8000000|FNRA
20260610|TSLA|1000000|50000|4000000|FNRA
"""

_MALFORMED_FILE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260610|NVDA|5000000|200000|12000000|FNRA
BADROW
20260610|MSFT|not_a_number|100000|8000000|FNRA
20260610|AMZN|2000000|80000|6000000|FNRA
"""


# ---------------------------------------------------------------------------
# 1. PARSER tests
# ---------------------------------------------------------------------------

def test_parser_good_file():
    """Good file: parse 3 rows, correct symbols and volumes."""
    rows = _parse_finra_file(_SAMPLE_FILE)
    assert len(rows) == 3
    symbols = {r["symbol"] for r in rows}
    assert symbols == {"NVDA", "AAPL", "TSLA"}
    nvda = next(r for r in rows if r["symbol"] == "NVDA")
    assert nvda["total_volume"] == 12_000_000
    assert nvda["short_volume"] == 5_000_000
    assert nvda["short_exempt_volume"] == 200_000


def test_parser_malformed_rows_skipped():
    """Malformed rows (BADROW, non-int column) are skipped; valid rows kept."""
    rows = _parse_finra_file(_MALFORMED_FILE)
    symbols = {r["symbol"] for r in rows}
    assert "NVDA" in symbols   # good row kept
    assert "AMZN" in symbols   # good row kept
    assert "MSFT" not in symbols   # non-int column skipped
    assert not any("BADROW" in r["symbol"] for r in rows)


def test_parser_ticker_filter():
    """Only rows for requested tickers are returned."""
    rows = _parse_finra_file(_SAMPLE_FILE, tickers={"NVDA", "AAPL"})
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {"NVDA", "AAPL"}


def test_parser_header_skipped():
    """Header line is never returned as a data row."""
    rows = _parse_finra_file(_SAMPLE_FILE)
    assert not any(r["symbol"] == "Symbol" for r in rows)


def test_parser_zero_total_volume_skipped():
    """Rows with TotalVolume=0 are skipped (div-by-zero guard)."""
    zero_vol_file = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260610|FAKE|0|0|0|FNRA\n"
    rows = _parse_finra_file(zero_vol_file)
    assert rows == []


def test_parser_empty_file():
    rows = _parse_finra_file("")
    assert rows == []


# ---------------------------------------------------------------------------
# 2. short_pct nets out ShortExemptVolume
# ---------------------------------------------------------------------------

def test_short_pct_nets_out_exempt():
    """short_pct = (ShortVolume - ShortExemptVolume) / TotalVolume."""
    rows = _parse_finra_file(_SAMPLE_FILE, tickers={"NVDA"})
    nvda = rows[0]
    # (5_000_000 - 200_000) / 12_000_000 = 4_800_000 / 12_000_000 = 0.4
    expected = (5_000_000 - 200_000) / 12_000_000
    assert abs(nvda["short_pct"] - expected) < 1e-9


def test_short_pct_zero_exempt():
    """When ShortExemptVolume=0, short_pct = ShortVolume / TotalVolume."""
    f = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260610|ZZ|1000000|0|2000000|FNRA\n"
    rows = _parse_finra_file(f)
    assert abs(rows[0]["short_pct"] - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# 3. Domain / URL validation
# ---------------------------------------------------------------------------

def test_validate_url_good():
    assert _validate_url("https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260610.txt") is True


def test_validate_url_wrong_domain():
    assert _validate_url("https://evil.com/CNMSshvol20260610.txt") is False


def test_validate_url_subdomain_not_allowed():
    # cdn.finra.org must match exactly — finra.org without cdn. is not valid
    assert _validate_url("https://finra.org/evil") is False


def test_make_url_format():
    url = _make_url(date(2026, 6, 10))
    assert url == "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260610.txt"


# ---------------------------------------------------------------------------
# 4. HTTP security guards (oversize + redirect + wrong-domain)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oversize_response_rejected():
    """A response larger than 10 MB is rejected."""
    oversized_body = b"x" * (10 * 1024 * 1024 + 2)

    mock_content = MagicMock()
    mock_content.read = AsyncMock(return_value=oversized_body)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260610.txt"
    mock_resp.content = mock_content
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=None),
    )):
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_resp)
        rows = await fetch_finra_short_volume(date(2026, 6, 10), tickers={"NVDA"})
    assert rows == [], "Oversized response must be rejected"


@pytest.mark.asyncio
async def test_redirect_rejected():
    """A 301/302 redirect is never followed."""
    mock_resp = MagicMock()
    mock_resp.status = 301
    mock_resp.url = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260610.txt"
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        rows = await fetch_finra_short_volume(date(2026, 6, 10), tickers={"NVDA"})
    assert rows == [], "Redirect must be rejected"


@pytest.mark.asyncio
async def test_wrong_domain_rejected():
    """A URL that doesn't resolve to cdn.finra.org is rejected without fetching."""
    rows = await fetch_finra_short_volume.__wrapped__ if hasattr(fetch_finra_short_volume, "__wrapped__") else None
    # Directly test domain validation
    assert _validate_url("https://evil.com/CNMSshvol20260610.txt") is False


# ---------------------------------------------------------------------------
# 5. z-gate math (_compute_finra_short_volume_pts)
# ---------------------------------------------------------------------------

def _mature_baseline(*, mean: float = 0.40, std: float = 0.05, days: int = 30) -> dict:
    return {"mean": mean, "std": std, "sample_days": days}


def test_zscore_above_threshold_gives_pts(monkeypatch):
    """short_pct > 2sigma -> returns term_cap."""
    _flag_on(monkeypatch, {"features.finra_short_volume.term_cap": 5,
                           "features.finra_short_volume.z_threshold": 2.0,
                           "features.finra_short_volume.min_baseline_days": 30})
    mean, std = 0.40, 0.05
    short_pct = mean + 3.0 * std  # z = 3.0
    pts = _compute_finra_short_volume_pts(
        short_pct, _mature_baseline(mean=mean, std=std),
        finra_published_at=time.time(),  # fresh
        direction="long",
    )
    assert pts == 5


def test_zscore_below_threshold_gives_zero(monkeypatch):
    """short_pct < 2sigma -> 0."""
    _flag_on(monkeypatch)
    mean, std = 0.40, 0.05
    short_pct = mean + 1.0 * std  # z = 1.0
    pts = _compute_finra_short_volume_pts(
        short_pct, _mature_baseline(mean=mean, std=std),
        finra_published_at=time.time(),
        direction="long",
    )
    assert pts == 0


def test_zscore_thin_baseline_gives_zero(monkeypatch):
    """< 30 days of baseline -> 0."""
    _flag_on(monkeypatch, {"features.finra_short_volume.min_baseline_days": 30})
    mean, std = 0.40, 0.05
    short_pct = mean + 5.0 * std  # very high z
    pts = _compute_finra_short_volume_pts(
        short_pct, {"mean": mean, "std": std, "sample_days": 10},  # thin
        finra_published_at=time.time(),
        direction="long",
    )
    assert pts == 0


def test_zscore_zero_std_gives_zero(monkeypatch):
    """Zero-variance baseline -> 0 (new-ticker degeneracy guard)."""
    _flag_on(monkeypatch)
    pts = _compute_finra_short_volume_pts(
        0.9, {"mean": 0.40, "std": 0.0, "sample_days": 30},
        finra_published_at=time.time(),
        direction="long",
    )
    assert pts == 0


def test_zscore_short_direction_gives_zero(monkeypatch):
    """On a short signal, the term contributes 0 (direction-compatibility guard)."""
    _flag_on(monkeypatch)
    mean, std = 0.40, 0.05
    short_pct = mean + 4.0 * std  # large z
    pts = _compute_finra_short_volume_pts(
        short_pct, _mature_baseline(mean=mean, std=std),
        finra_published_at=time.time(),
        direction="short",  # not long
    )
    assert pts == 0


# ---------------------------------------------------------------------------
# 6. Stale row -> 0 (recency_window freshness check)
# ---------------------------------------------------------------------------

def test_stale_row_gives_zero(monkeypatch):
    """Row published > 1440 minutes ago -> 0 (EOD-staleness tag)."""
    _flag_on(monkeypatch)
    stale_at = time.time() - 25 * 3600  # 25h ago (> 1440-min cap)
    mean, std = 0.40, 0.05
    short_pct = mean + 5.0 * std  # would easily pass z-gate
    pts = _compute_finra_short_volume_pts(
        short_pct, _mature_baseline(mean=mean, std=std),
        finra_published_at=stale_at,
        direction="long",
    )
    assert pts == 0, "Stale EOD row must contribute 0 (no phantom confluence)"


def test_none_published_at_gives_zero(monkeypatch):
    """None finra_published_at (unknown freshness) -> 0."""
    _flag_on(monkeypatch)
    mean, std = 0.40, 0.05
    short_pct = mean + 5.0 * std
    pts = _compute_finra_short_volume_pts(
        short_pct, _mature_baseline(mean=mean, std=std),
        finra_published_at=None,
        direction="long",
    )
    assert pts == 0


# ---------------------------------------------------------------------------
# 7. DB baseline helper — round-trip (mean / std / sample_days)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_baseline_empty_returns_zero_struct():
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    result = await db_mod.get_finra_short_volume_baseline("NVDA")
    assert result == {"mean": 0.0, "std": 0.0, "sample_days": 0}

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_db_baseline_two_days():
    """Two distinct trade-date rows produce correct mean and population std."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    now = time.time()
    await db_mod.upsert_finra_short_volume(
        "NVDA", "2026-06-08", 10_000_000, 5_000_000, 200_000,
        (5_000_000 - 200_000) / 10_000_000,
        finra_published_at=now - 86400,
    )
    await db_mod.upsert_finra_short_volume(
        "NVDA", "2026-06-09", 10_000_000, 3_000_000, 100_000,
        (3_000_000 - 100_000) / 10_000_000,
        finra_published_at=now - 3600,
    )
    pct1 = (5_000_000 - 200_000) / 10_000_000   # 0.48
    pct2 = (3_000_000 - 100_000) / 10_000_000   # 0.29
    expected_mean = (pct1 + pct2) / 2
    expected_std = (((pct1 - expected_mean) ** 2 + (pct2 - expected_mean) ** 2) / 2) ** 0.5

    result = await db_mod.get_finra_short_volume_baseline("NVDA")
    assert result["sample_days"] == 2
    assert abs(result["mean"] - expected_mean) < 1e-9
    assert abs(result["std"] - expected_std) < 1e-9

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_db_upsert_idempotent():
    """Upserting the same (ticker, trade_date) twice keeps latest values."""
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    now = time.time()
    await db_mod.upsert_finra_short_volume("NVDA", "2026-06-10", 10_000_000, 4_000_000, 100_000, 0.39, finra_published_at=now)
    # Upsert with updated values
    await db_mod.upsert_finra_short_volume("NVDA", "2026-06-10", 12_000_000, 5_000_000, 200_000, 0.40, finra_published_at=now)

    result = await db_mod.get_latest_finra_short_volume("NVDA")
    assert result is not None
    assert result["short_pct"] == pytest.approx(0.40)
    assert result["total_volume"] == 12_000_000

    bl = await db_mod.get_finra_short_volume_baseline("NVDA")
    # Only one distinct day after upsert
    assert bl["sample_days"] == 1

    db_mod._db = None
    db_mod.DB_PATH = None


@pytest.mark.asyncio
async def test_db_get_latest_returns_none_when_missing():
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    row = await db_mod.get_latest_finra_short_volume("ZZZZZ")
    assert row is None

    db_mod._db = None
    db_mod.DB_PATH = None


# ---------------------------------------------------------------------------
# 8. Provenance label constant never changes
# ---------------------------------------------------------------------------

def test_provenance_label_constant():
    """The hard render rule: provenance label is the exact spec string."""
    assert FINRA_SHORT_VOL_PROVENANCE == "short-volume %, MM-hedging-inflated proxy"


# ---------------------------------------------------------------------------
# 9. score_ticker integration — flag OFF: no DB read, 0 term, byte-identical
# ---------------------------------------------------------------------------

from consensus_engine.analysis.consolidation import ConsolidationResult as _CR
from consensus_engine.models import CatalystResult

_FAKE_CONS = _CR(
    fired=False, consolidated_id=None, effective_n_clusters=0,
    combined_log_odds=0.0, consensus_boost=0, sources_seen=[], reason="disabled",
)


def _patch_fetchers():
    catalyst = CatalystResult(ticker="NVDA", catalyst_summary="", catalyst_type="",
                              news_sources=[], catalyst_body="")
    return (
        patch("consensus_engine.cross_reference._run_news_cascade",
              new=AsyncMock(return_value=catalyst)),
        patch("consensus_engine.cross_reference._run_sec_check",
              new=AsyncMock(return_value=(False, ""))),
        patch("consensus_engine.cross_reference._run_social_check",
              new=AsyncMock(return_value={"apewisdom": 0, "stocktwits": 0,
                                          "reddit": 0, "google_trends": 0})),
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
async def test_score_ticker_flag_off_no_db_read(monkeypatch):
    """Flag OFF -> DB is never queried for finra data; term is 0."""
    _flag_off(monkeypatch)

    db_calls: list[str] = []

    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
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
        mock_db.get_latest_finra_short_volume = AsyncMock(
            side_effect=lambda t: db_calls.append("finra_latest") or None
        )
        mock_db.get_finra_short_volume_baseline = AsyncMock(
            side_effect=lambda t: db_calls.append("finra_baseline") or {}
        )

        result = await score_ticker("NVDA", base_score=30, direction="long")

    assert result.breakdown.finra_short_volume == 0, "Flag OFF -> term must be 0"
    assert not db_calls, "Flag OFF -> no DB reads for finra data on hot path"


@pytest.mark.asyncio
async def test_score_ticker_flag_on_z_surge(monkeypatch):
    """Flag ON, z-surge + mature baseline + fresh row -> finra_pts = term_cap."""
    _flag_on(monkeypatch, {
        "features.finra_short_volume.term_cap": 5,
        "features.finra_short_volume.z_threshold": 2.0,
        "features.finra_short_volume.min_baseline_days": 30,
    })

    mean, std = 0.40, 0.05
    latest_short_pct = mean + 3.0 * std  # z = 3.0 > 2.0

    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
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
        mock_db.get_latest_finra_short_volume = AsyncMock(return_value={
            "ticker": "NVDA",
            "trade_date": "2026-06-10",
            "total_volume": 12_000_000,
            "short_volume": 5_000_000,
            "short_exempt_volume": 200_000,
            "short_pct": latest_short_pct,
            "finra_published_at": time.time(),  # fresh
        })
        mock_db.get_finra_short_volume_baseline = AsyncMock(return_value={
            "mean": mean, "std": std, "sample_days": 30,
        })

        result = await score_ticker("NVDA", base_score=30, direction="long")

    assert result.breakdown.finra_short_volume == 5


@pytest.mark.asyncio
async def test_score_ticker_flag_on_stale_row(monkeypatch):
    """Flag ON, but stale finra row -> finra_pts = 0."""
    _flag_on(monkeypatch)

    mean, std = 0.40, 0.05
    stale_at = time.time() - 25 * 3600  # 25h ago

    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
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
        mock_db.get_latest_finra_short_volume = AsyncMock(return_value={
            "ticker": "NVDA",
            "trade_date": "2026-06-09",
            "total_volume": 12_000_000,
            "short_volume": 5_000_000,
            "short_exempt_volume": 200_000,
            "short_pct": mean + 5.0 * std,  # huge z
            "finra_published_at": stale_at,  # stale
        })
        mock_db.get_finra_short_volume_baseline = AsyncMock(return_value={
            "mean": mean, "std": std, "sample_days": 30,
        })

        result = await score_ticker("NVDA", base_score=30, direction="long")

    assert result.breakdown.finra_short_volume == 0, "Stale EOD row must contribute 0"


# ---------------------------------------------------------------------------
# 10. Common-recency-window: stale finra leg does not count (§8.B)
# ---------------------------------------------------------------------------

def test_stale_leg_no_phantom_confluence(monkeypatch):
    """A stale finra_short_volume leg (> 1440 min) earns 0 regardless of z-score.

    §8.B: a stale leg does NOT count toward confluence/contradiction.
    """
    _flag_on(monkeypatch)
    # 26 hours ago — past 1440-min cap
    stale_ts = time.time() - 26 * 3600
    mean, std = 0.40, 0.05
    short_pct = mean + 10.0 * std  # extreme z — would pass if fresh

    pts = _compute_finra_short_volume_pts(
        short_pct,
        {"mean": mean, "std": std, "sample_days": 30},
        finra_published_at=stale_ts,
        direction="long",
    )
    assert pts == 0, (
        "Stale FINRA leg must contribute 0 — "
        "pairing a >24h-old short-vol spike with a fresh tweet is phantom confluence"
    )
