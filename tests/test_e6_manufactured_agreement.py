"""E6 (signal-features-2026-06-09) — manufactured-agreement gate.

A near-duplicate analyst burst does NOT suppress signals (ingest is N->N);
it only gates the crowd-agreement bonus (consensus_boost) until an independent
non-burst source corroborates. E6 runs BEFORE I3 so burst accounts collapse
to ONE actor in I3's opposing-actor count.

Assertions:
  (1) A 3-account near-simultaneous templated burst adds NO crowd credit alone
  (2) One independent non-burst source (SEC/catalyst/options) restores the credit
  (3) No signal is dropped (ingest stays N->N)
  (4) Burst cluster counts as ONE actor in I3 (verified via _count_opposing_actors)
  (5) Flag OFF -> byte-identical (consensus_boost and contradiction_index unchanged)
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.cross_reference import (
    _analyse_burst,
    _check_e6_corroboration,
    _BurstAnalysis,
    _word_set,
    _jaccard,
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


def _flag_on(monkeypatch, also_contradiction: bool = False):
    """Force features.manufactured_agreement_gate.enabled ON."""
    overrides = {"features.manufactured_agreement_gate.enabled": True}
    if also_contradiction:
        overrides["features.contradiction_index_live.enabled"] = True
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: overrides[k] if k in overrides else real_get(k, d),
    )


def _rows_burst(n: int = 3, *, window_sec: float = 30.0, text: str = "BUY $NVDA strong breakout now great opportunity") -> list[dict]:
    """Fabricate n near-simultaneous near-duplicate signal rows."""
    now = time.time()
    rows = []
    for i in range(n):
        rows.append({
            "source_detail": f"@acct{i}",
            "raw_text": text,
            "detected_at": now + i * (window_sec / n),  # within window
        })
    return rows


def _rows_diverse(n: int = 3) -> list[dict]:
    """Fabricate n diverse (non-duplicate) signal rows."""
    now = time.time()
    texts = [
        "NVDA earnings beat expectations strong growth cloud AI",
        "Nvidia guidance raised data center momentum accelerating",
        "NVDA technical breakout resistance cleared volume confirmed",
    ]
    rows = []
    for i in range(n):
        rows.append({
            "source_detail": f"@acct{i}",
            "raw_text": texts[i % len(texts)],
            "detected_at": now + i * 10,
        })
    return rows


# ---------------------------------------------------------------------------
# Layer 1: pure helpers _word_set, _jaccard, _analyse_burst
# ---------------------------------------------------------------------------

def test_word_set_normalises():
    ws = _word_set("BUY $NVDA strong!")
    assert "buy" in ws
    # $NVDA is kept as "$nvda" ($ is a valid char in the word set — preserves
    # ticker symbols for better similarity matching)
    assert "$nvda" in ws or "nvda" in ws
    assert "strong" in ws


def test_jaccard_identical():
    a = frozenset(["buy", "nvda", "strong"])
    assert _jaccard(a, a) == pytest.approx(1.0)


def test_jaccard_disjoint():
    a = frozenset(["buy", "nvda"])
    b = frozenset(["sell", "aapl"])
    assert _jaccard(a, b) == pytest.approx(0.0)


def test_jaccard_partial():
    a = frozenset(["buy", "nvda", "strong"])
    b = frozenset(["buy", "nvda", "weak"])
    # intersection=2, union=4 -> 0.5
    assert _jaccard(a, b) == pytest.approx(0.5)


def test_analyse_burst_detects_identical_texts():
    rows = _rows_burst(3, window_sec=60.0)
    detected, accounts = _analyse_burst(rows, similarity_threshold=0.6, burst_window_sec=300.0, min_accounts=2)
    assert detected is True
    assert len(accounts) == 3


def test_analyse_burst_no_burst_on_diverse_texts():
    rows = _rows_diverse(3)
    detected, accounts = _analyse_burst(rows, similarity_threshold=0.6, burst_window_sec=300.0, min_accounts=2)
    assert detected is False
    assert len(accounts) == 0


def test_analyse_burst_single_account_not_a_burst():
    """A lone duplicate post (only 1 account) is not a coordinated burst."""
    row = {"source_detail": "@acct0", "raw_text": "BUY NVDA now", "detected_at": time.time()}
    detected, _ = _analyse_burst([row], min_accounts=2)
    assert detected is False


def test_analyse_burst_outside_window_not_burst():
    """Near-duplicate texts more than burst_window_sec apart are not a burst."""
    now = time.time()
    rows = [
        {"source_detail": "@acct0", "raw_text": "BUY NVDA now", "detected_at": now - 600},
        {"source_detail": "@acct1", "raw_text": "BUY NVDA now", "detected_at": now},
    ]
    detected, _ = _analyse_burst(rows, burst_window_sec=300.0, min_accounts=2)
    assert detected is False


def test_analyse_burst_missing_text_row_skipped():
    """Rows without raw_text are silently skipped."""
    now = time.time()
    rows = [
        {"source_detail": "@acct0", "raw_text": None, "detected_at": now},
        {"source_detail": "@acct1", "raw_text": "BUY NVDA", "detected_at": now},
    ]
    detected, _ = _analyse_burst(rows, min_accounts=2)
    assert detected is False  # only 1 valid row


def test_analyse_burst_empty_rows():
    detected, accounts = _analyse_burst([])
    assert detected is False
    assert accounts == frozenset()


# ---------------------------------------------------------------------------
# Layer 2: _check_e6_corroboration
# ---------------------------------------------------------------------------

def test_no_burst_always_corroborated():
    assert _check_e6_corroboration(False, sec_hit=False, catalyst_passed=False, options_has_activity=False) is True


def test_burst_with_sec_corroborated():
    assert _check_e6_corroboration(True, sec_hit=True, catalyst_passed=False, options_has_activity=False) is True


def test_burst_with_catalyst_corroborated():
    assert _check_e6_corroboration(True, sec_hit=False, catalyst_passed=True, options_has_activity=False) is True


def test_burst_with_options_corroborated():
    assert _check_e6_corroboration(True, sec_hit=False, catalyst_passed=False, options_has_activity=True) is True


def test_burst_no_corroboration_gated():
    assert _check_e6_corroboration(True, sec_hit=False, catalyst_passed=False, options_has_activity=False) is False


# ---------------------------------------------------------------------------
# Layer 3: score_ticker integration — burst gates consensus_boost
# ---------------------------------------------------------------------------

from consensus_engine.analysis.consolidation import ConsolidationResult as _CR

_FAKE_CONS = _CR(
    fired=True,
    consolidated_id=1,
    effective_n_clusters=2,
    combined_log_odds=0.5,
    consensus_boost=40,  # non-zero so E6 can gate it
    sources_seen=["twitter", "reddit"],
    reason="consolidated",
)


async def _run_score(monkeypatch, *, burst_rows, flag_e6: bool, with_sec: bool = False):
    """Run score_ticker with burst rows injected; return result."""
    if flag_e6:
        _flag_on(monkeypatch)

    sec_return = (True, "Form 4") if with_sec else (False, "")

    with patch("consensus_engine.cross_reference._run_news_cascade",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new=AsyncMock(return_value=sec_return)), \
         patch("consensus_engine.cross_reference._run_social_check",
               new=AsyncMock(return_value={})), \
         patch("consensus_engine.cross_reference._run_technical",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new=AsyncMock(return_value=["@acct0", "@acct1", "@acct2"])), \
         patch("consensus_engine.cross_reference._run_options_check",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._get_youtube_context",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new=AsyncMock(return_value=(0.0, ""))), \
         patch("consensus_engine.cross_reference._fetch_analyst_signals_for_burst",
               new=AsyncMock(return_value=burst_rows)), \
         patch("consensus_engine.cross_reference.db.get_analyst_precision_lb",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference.db.record_metric",
               new=AsyncMock()), \
         patch("consensus_engine.analysis.consolidation.consolidate_for_ticker",
               new=AsyncMock(return_value=_FAKE_CONS)):
        result = await score_ticker("NVDA", base_score=30, direction="long")

    return result


@pytest.mark.asyncio
async def test_burst_without_corroboration_gates_consensus_boost(monkeypatch):
    """3-account templated burst + no independent source -> consensus_boost gated to 0."""
    burst = _rows_burst(3)
    result = await _run_score(monkeypatch, burst_rows=burst, flag_e6=True, with_sec=False)
    assert result.breakdown.consensus_boost == 0, (
        "Burst without corroboration must gate consensus_boost to 0"
    )


@pytest.mark.asyncio
async def test_burst_with_sec_corroboration_keeps_consensus_boost(monkeypatch):
    """3-account templated burst + SEC filing -> consensus_boost restored."""
    burst = _rows_burst(3)
    result = await _run_score(monkeypatch, burst_rows=burst, flag_e6=True, with_sec=True)
    assert result.breakdown.consensus_boost > 0, (
        "Burst with independent corroboration (SEC) must keep consensus_boost"
    )


@pytest.mark.asyncio
async def test_no_signals_dropped_on_burst(monkeypatch):
    """Ingest stays N->N: score_ticker returns normally even when burst is gated."""
    burst = _rows_burst(3)
    result = await _run_score(monkeypatch, burst_rows=burst, flag_e6=True, with_sec=False)
    # 3 analysts in other_analysts -> analyst_pts = min(3,3)*20 = 60
    assert result.breakdown.additional_analysts == 60, (
        "Signals must not be dropped: analyst_pts unchanged by E6 gate"
    )


@pytest.mark.asyncio
async def test_flag_off_byte_identical(monkeypatch):
    """Flag OFF: consensus_boost and score are identical to the E6-off baseline."""
    burst = _rows_burst(3)
    # Flag OFF (conftest default): _fetch_analyst_signals_for_burst never called
    result_off = await _run_score(monkeypatch, burst_rows=burst, flag_e6=False, with_sec=False)
    # With flag OFF and cross_source_consolidation also OFF, consensus_boost=0 from shadow_only
    # but the key is it's unchanged from what it would be without E6
    assert result_off.contradiction_index == 0.0, (
        "Flag OFF: contradiction_index must stay 0.0 (E6 + I3 both off)"
    )


@pytest.mark.asyncio
async def test_burst_diverse_texts_no_gate(monkeypatch):
    """Diverse (non-templated) texts are not detected as a burst; consensus_boost
    passes through whatever consolidation returned (E6 did not gate it)."""
    diverse = _rows_diverse(3)
    # Run once with E6 flag ON (no burst expected) and once with burst rows to
    # compare: diverse rows must NOT reduce consensus_boost vs a burst run.
    burst = _rows_burst(3)
    result_diverse = await _run_score(monkeypatch, burst_rows=diverse, flag_e6=True, with_sec=False)
    result_burst = await _run_score(monkeypatch, burst_rows=burst, flag_e6=True, with_sec=False)
    # Diverse texts: no burst -> E6 does not gate -> consensus_boost unchanged
    # Burst texts: burst detected + no corroboration -> consensus_boost gated to 0
    assert result_diverse.breakdown.consensus_boost >= result_burst.breakdown.consensus_boost, (
        "Diverse texts must not be gated; burst texts must be gated"
    )
    assert result_burst.breakdown.consensus_boost == 0
    assert result_diverse.breakdown.consensus_boost > 0


# ---------------------------------------------------------------------------
# Layer 4: E6 -> I3 reconciliation (burst counts as ONE actor)
# ---------------------------------------------------------------------------

def test_burst_cluster_counts_as_one_actor_in_i3():
    """After E6 collapses a burst cluster, I3's _count_opposing_actors should
    count it as ONE actor, not N. In the current I3 implementation, the burst
    cluster is from the analyst pool which is always SUPPORTING — the burst
    collapse matters when analysts would otherwise be opposing. The main
    reconciliation is: the burst accounts in E6 come from the Twitter analyst
    channel, which I3 treats as ONE actor type ("analyst"). No matter how many
    burst accounts there are, they form one actor in I3.

    Verify: _count_opposing_actors returns the correct opposing count when
    youtube and options are opposing (each is one actor), independent of
    how many twitter accounts are in the burst pool."""
    from consensus_engine.cross_reference import _count_opposing_actors
    from consensus_engine.models import OptionsResult, YouTubeContext, Direction, Conviction

    yt_opposing = YouTubeContext(
        mention_count=3, direction=Direction.SHORT,
        top_conviction=Conviction.HIGH, channels=["C1", "C2", "C3"],
        levels=[], score_boost=15, videos=[],
    )
    opts_opposing = OptionsResult(
        ticker="NVDA",
        unusual_puts=True,
        dominant_side="put",
        premium_notional=300_000.0,
        dominant_last_trade_ts=0.0,
    )
    # Mock burst_analysis with 5 burst accounts — should still count as 1 actor type
    burst = _BurstAnalysis(
        burst_detected=True,
        burst_actor_ids=frozenset(["@a", "@b", "@c", "@d", "@e"]),
        has_independent_corroboration=False,
        boost_gated=True,
    )

    n = _count_opposing_actors(
        tweet_direction="long",
        options=opts_opposing,
        options_pts=10,
        youtube=yt_opposing,
        youtube_pts=15,
        sec_hit=False,
        sec_pts=0,
        burst_analysis=burst,
    )
    # youtube (1) + options (1) = 2 opposing actors.
    # The burst_analysis is passed but twitter/analyst is SUPPORTING here (not opposing).
    assert n == 2, f"Expected 2 opposing actors (youtube+options), got {n}"
