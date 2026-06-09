"""I6 (signal-features-2026-06-09) — scale options by premium, SAME-DIRECTION only.

Today `options_pts` is a flat +10 on any unusual options activity. Behind
`features.options_graduated_scoring.enabled` it becomes a same-direction-only
confluence nudge:
  +10  a >$250k single-strike dominant-side premium ALIGNED with the tweet dir
  +6   aligned dominant side but premium <= $250k
  0    opposing OR ambiguous dominant side, OR a stale/after-hours snapshot

Mandatory safeguards asserted here (E4):
  - opposing put-wall on a long  -> 0, NEVER negative (Pan-Poteshman drop)
  - ambiguous dominant side      -> 0, never a sign
  - stale / after-hours snapshot -> 0
  - flag OFF                     -> flat +10 (byte-identical)
  - the contribution carries the intraday/1-2d horizon attribute
  - the narrator is FORBIDDEN from framing public flow as "smart money"

The new premium/dominant-side/staleness fields ride on OptionsResult with
defaults, so all existing options mocks keep working.
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.models import OptionsResult
from consensus_engine.cross_reference import _graduate_options_pts, score_ticker
from consensus_engine.alerts.all_command import narrator
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


def _flag_on(monkeypatch):
    """Force ONLY features.options_graduated_scoring.enabled ON; all else default."""
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: True if k == "features.options_graduated_scoring.enabled"
        else real_get(k, d),
    )


_FRESH = time.time()
_STALE = time.time() - 6 * 3600  # 6h ago, well past the 60-min staleness cap


def _opts(*, side: str, premium: float, ts: float = _FRESH) -> OptionsResult:
    """Build an OptionsResult that reports unusual activity on `side`."""
    return OptionsResult(
        ticker="AAPL",
        unusual_calls=(side == "call"),
        unusual_puts=(side == "put"),
        max_call_ratio=8.0 if side == "call" else 0.0,
        max_put_ratio=8.0 if side == "put" else 0.0,
        premium_notional=premium,
        dominant_side=side,
        dominant_last_trade_ts=ts,
    )


# ── Layer 1: pure helper _graduate_options_pts ─────────────────────────────

def test_helper_aligned_large_call_long_is_10():
    o = _opts(side="call", premium=400_000.0)
    assert _graduate_options_pts(o, "long") == 10


def test_helper_aligned_small_call_long_is_6():
    o = _opts(side="call", premium=100_000.0)  # below $250k -> small-flow nudge
    assert _graduate_options_pts(o, "long") == 6


def test_helper_aligned_large_put_short_is_10():
    o = _opts(side="put", premium=400_000.0)
    assert _graduate_options_pts(o, "short") == 10


def test_helper_opposing_putwall_on_long_is_0_never_negative():
    o = _opts(side="put", premium=900_000.0)  # huge put flow on a LONG
    pts = _graduate_options_pts(o, "long")
    assert pts == 0          # opposing branch DROPPED, not scored
    assert pts >= 0          # never a negative sign


def test_helper_ambiguous_side_is_0():
    o = _opts(side="call", premium=400_000.0)
    o.dominant_side = ""     # call/put premium tie -> ambiguous
    assert _graduate_options_pts(o, "long") == 0


def test_helper_stale_snapshot_is_0():
    o = _opts(side="call", premium=400_000.0, ts=_STALE)
    assert _graduate_options_pts(o, "long") == 0


def test_helper_no_timestamp_treated_stale_is_0():
    o = _opts(side="call", premium=400_000.0, ts=0.0)
    assert _graduate_options_pts(o, "long") == 0


def test_helper_magnitude_capped_at_aligned():
    o = _opts(side="call", premium=50_000_000.0)  # $50M sweep
    assert _graduate_options_pts(o, "long") == 10  # capped, never a driver


# ── Layer 2: full score_ticker path (flag ON) ─────────────────────────────

async def _options_pts_via_score(options, direction) -> int:
    with patch("consensus_engine.cross_reference._run_news_cascade",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new=AsyncMock(return_value=(False, ""))), \
         patch("consensus_engine.cross_reference._run_social_check",
               new=AsyncMock(return_value={})), \
         patch("consensus_engine.cross_reference._run_technical",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new=AsyncMock(return_value=[])), \
         patch("consensus_engine.cross_reference._run_options_check",
               new=AsyncMock(return_value=options)), \
         patch("consensus_engine.cross_reference._get_youtube_context",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new=AsyncMock(return_value=(0.0, ""))):
        result = await score_ticker("AAPL", base_score=0, direction=direction)
    return result.breakdown.options_flow, result.options


@pytest.mark.asyncio
async def test_score_aligned_large_sweep_is_10(monkeypatch):
    _flag_on(monkeypatch)
    pts, _ = await _options_pts_via_score(_opts(side="call", premium=400_000.0), "long")
    assert pts == 10


@pytest.mark.asyncio
async def test_score_opposing_putwall_is_0_never_negative(monkeypatch):
    _flag_on(monkeypatch)
    pts, _ = await _options_pts_via_score(_opts(side="put", premium=900_000.0), "long")
    assert pts == 0
    assert pts >= 0


@pytest.mark.asyncio
async def test_score_ambiguous_is_0(monkeypatch):
    _flag_on(monkeypatch)
    o = _opts(side="call", premium=400_000.0)
    o.dominant_side = ""
    pts, _ = await _options_pts_via_score(o, "long")
    assert pts == 0


@pytest.mark.asyncio
async def test_score_stale_is_0(monkeypatch):
    _flag_on(monkeypatch)
    pts, _ = await _options_pts_via_score(
        _opts(side="call", premium=400_000.0, ts=_STALE), "long")
    assert pts == 0


@pytest.mark.asyncio
async def test_score_contribution_carries_horizon_attribute(monkeypatch):
    _flag_on(monkeypatch)
    pts, options = await _options_pts_via_score(_opts(side="call", premium=400_000.0), "long")
    assert pts == 10
    # E4 regression: the contribution carries the intraday/1-2d horizon attr.
    assert options.horizon == "1-2d"


# ── Layer 3: flag OFF is byte-identical (+10 flat) ─────────────────────────

@pytest.mark.asyncio
async def test_score_flag_off_is_flat_10():
    # No _flag_on -> conftest force-off keeps the feature dark. Even a
    # huge OPPOSING put-wall on a long scores the legacy flat +10.
    pts, options = await _options_pts_via_score(_opts(side="put", premium=900_000.0), "long")
    assert pts == 10          # legacy flat +10 on mere has_unusual_activity
    assert options.horizon == ""  # flag off -> graduation block never runs


# ── Layer 4: narrator E4 framing ban (flag ON) ─────────────────────────────

def test_narrator_forbids_smart_money_framing_when_flag_on(monkeypatch):
    from consensus_engine import config as _cfg
    real = _cfg.get
    monkeypatch.setattr(
        _cfg, "get",
        lambda k, d=None: True if k == "features.options_graduated_scoring.enabled"
        else real(k, d),
    )
    for swing_v2 in (True, False):
        block = narrator._build_constraints_block(swing_v2)
        assert "smart money" in block.lower()
        assert "unusual options flow" in block.lower()
        assert "1-2-day" in block.lower()


def test_narrator_ban_absent_when_flag_off():
    # conftest force-off keeps the I6 flag dark -> ban string absent -> the
    # constraints block stays byte-identical (the synthesis_prompt_trim test
    # locks the full-block length).
    block = narrator._build_constraints_block(True)
    assert "smart money" not in block.lower()
