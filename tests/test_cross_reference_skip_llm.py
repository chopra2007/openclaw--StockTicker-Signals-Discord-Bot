"""#16 — flag-gated, decision-safe LLM-scorer skip in score_ticker().

When `scoring.skip_llm_below_threshold` is ON, score_ticker() skips the
per-ticker LLM confidence scorer for tickers where even the maximum possible
LLM boost cannot lift `base + cheap subtotals` up to the alert line
(`precision_engine.thresholds.medium_confidence`). Because the LLM call cannot
change the WATCHLIST/IGNORE outcome in that case, skipping is decision-safe.

These tests lock:
  (a) flag OFF -> low-signal ticker STILL calls the scorer (behavior unchanged)
  (b) flag ON  -> low-signal ticker SKIPS; llm_boost==0; classification IDENTICAL to flag-OFF
  (c) boundary ticker (base+cheap+llm_max == or > medium_confidence) STILL calls the scorer
  (d) flag ON  -> high-signal ticker STILL calls the scorer
"""
import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine import config as cfg
from consensus_engine.engine import _classify
from consensus_engine.models import TechnicalResult
from consensus_engine.cross_reference import score_ticker, ScoreTickerResult


# Real config values these tests assume (read from config, asserted here so the
# test fails loudly if the production defaults ever drift).
MED = cfg.get("precision_engine.thresholds.medium_confidence", 65)
LLM_MAX = cfg.get("scoring.multipliers.llm_boost_max", 15)


def _empty_source_patches(*, llm_mock):
    """All cheap sources empty -> cheap_subtotal == 0. `technical` is a truthy
    TechnicalResult with no filters (tech_pts == 0) so the LLM guard
    (`if technical or catalyst`) is satisfied and only the skip can stop it."""
    return [
        patch("consensus_engine.cross_reference._run_news_cascade",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._run_sec_check",
              new_callable=AsyncMock, return_value=(False, "")),
        patch("consensus_engine.cross_reference._run_social_check",
              new_callable=AsyncMock, return_value={}),
        patch("consensus_engine.cross_reference._run_technical",
              new_callable=AsyncMock, return_value=TechnicalResult("X")),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new_callable=AsyncMock, return_value=[]),
        patch("consensus_engine.cross_reference._run_llm_score", llm_mock),
        patch("consensus_engine.cross_reference._run_options_check",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new_callable=AsyncMock, return_value=None),
    ]


def _flag_cfg(skip_enabled: bool):
    """Wrap config.get so only `scoring.skip_llm_below_threshold` is overridden;
    every other key passes through to the real config (no consensus.yaml edit)."""
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "scoring.skip_llm_below_threshold":
            return skip_enabled
        return real_get(key, default)

    return patch("consensus_engine.cross_reference.cfg.get", side_effect=fake_get)


async def _run(*, skip_enabled, base_score, llm_return=(0.0, "")):
    llm_mock = AsyncMock(return_value=llm_return)
    stack = _empty_source_patches(llm_mock=llm_mock) + [_flag_cfg(skip_enabled)]
    for p in stack:
        p.start()
    try:
        result = await score_ticker("X", base_score=base_score)
    finally:
        for p in stack:
            p.stop()
    return result, llm_mock


@pytest.mark.asyncio
async def test_flag_off_low_signal_still_calls_scorer():
    """(a) Flag OFF -> low-signal ticker STILL invokes the LLM scorer."""
    result, llm_mock = await _run(skip_enabled=False, base_score=0)
    assert isinstance(result, ScoreTickerResult)
    assert llm_mock.call_count == 1, "flag OFF must preserve the LLM call"


@pytest.mark.asyncio
async def test_flag_on_low_signal_skips_and_classification_identical():
    """(b) Flag ON -> low-signal ticker SKIPS the scorer, llm_boost==0, and the
    final classification is IDENTICAL to the flag-OFF run for that ticker."""
    # base+cheap+llm_max = 0+0+15 = 15 < MED(65) -> skip when ON.
    off_result, off_mock = await _run(skip_enabled=False, base_score=0)
    on_result, on_mock = await _run(skip_enabled=True, base_score=0)

    assert off_mock.call_count == 1
    assert on_mock.call_count == 0, "flag ON must skip the LLM scorer below threshold"
    assert on_result.breakdown.llm_boost == 0
    assert on_result.llm_reasoning == ""

    # Decision-safety: identical total -> identical classification.
    assert on_result.breakdown.total == off_result.breakdown.total
    on_class = _classify(on_result.breakdown.total, has_mainstream=False, market_ok=False)
    off_class = _classify(off_result.breakdown.total, has_mainstream=False, market_ok=False)
    assert on_class[0] == off_class[0], "classification must be identical ON vs OFF"


@pytest.mark.asyncio
async def test_flag_on_boundary_still_calls_scorer():
    """(c) Boundary ticker where base+cheap+llm_max >= medium_confidence STILL
    calls the scorer (the LLM could still tip the decision)."""
    # Just AT the line: base + 0 + LLM_MAX == MED -> NOT skipped.
    at_line_base = MED - LLM_MAX
    result_at, mock_at = await _run(skip_enabled=True, base_score=at_line_base)
    assert mock_at.call_count == 1, "boundary == threshold must still call the scorer"

    # Just BELOW the line by 1: skipped.
    below_base = MED - LLM_MAX - 1
    _, mock_below = await _run(skip_enabled=True, base_score=below_base)
    assert mock_below.call_count == 0, "just below threshold must skip"


@pytest.mark.asyncio
async def test_flag_on_high_signal_still_calls_scorer():
    """(d) Flag ON -> high-signal ticker (well above threshold) STILL calls the scorer."""
    result, llm_mock = await _run(skip_enabled=True, base_score=MED + 20)
    assert llm_mock.call_count == 1, "high-signal ticker must still call the scorer"
