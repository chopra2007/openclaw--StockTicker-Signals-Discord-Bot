"""I10 — STRONG requires a hard-evidence component.

Tests for features.strong_requires_hard_evidence.enabled.

Flag-ON tests:
  (a) crowd-only stack (analysts+social+trends >= high, zero catalyst/sec/technical/options)
      → WATCHLIST, not STRONG
  (b) same crowd-only stack + a real catalyst → STRONG preserved
  (c) high-track-record analyst (analyst_lb >= threshold) → STRONG preserved with zero
      other hard evidence (before-mainstream carve-out)
  (d) confirming source in the budget-skipped set → NOT demoted
  (e) technical with only 1 filter passing does NOT count as hard evidence;
      >= 2 filters DOES count

Flag-OFF tests:
  Same inputs classify identically to the pre-I10 legacy path.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from consensus_engine.engine import _classify, SignalClass
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_breakdown(
    news_catalyst: int = 0,
    sec_filing: int = 0,
    options_flow: int = 0,
    base: int = 0,
    additional_analysts: int = 0,
    social_apewisdom: int = 0,
    google_trends: int = 0,
    technical: int = 0,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        base=base,
        additional_analysts=additional_analysts,
        news_catalyst=news_catalyst,
        sec_filing=sec_filing,
        options_flow=options_flow,
        social_apewisdom=social_apewisdom,
        google_trends=google_trends,
        technical=technical,
    )


def _cfg_factory(flag_on: bool, extra: dict | None = None) -> dict:
    """Build a minimal cfg.get mapping for I10 tests."""
    base = {
        "precision_engine.thresholds.high_confidence": 80,
        "precision_engine.thresholds.medium_confidence": 65,
        "precision_engine.thresholds.require_mainstream_for_strong": False,
        "precision_engine.thresholds.require_market_confirmation_for_low_conviction": False,
        "features.regime_classifier.enabled": False,
        "features.strong_requires_hard_evidence.enabled": flag_on,
        "features.strong_requires_hard_evidence.min_technical_filters": 2,
        "features.strong_requires_hard_evidence.analyst_lb_threshold": 0.65,
    }
    if extra:
        base.update(extra)
    return base


def _classify_with_cfg(
    cfg_map: dict,
    total_score: int,
    breakdown: ScoreBreakdown | None = None,
    technical_filter_count: int = 0,
    analyst_lb: float | None = None,
    budget_skipped_sources: set | None = None,
    ticker: str = "TEST",
) -> SignalClass:
    """Call _classify with a patched cfg.get, return only the SignalClass."""
    def _get(key, default=None):
        return cfg_map.get(key, default)

    with patch("consensus_engine.engine.cfg") as mock_cfg:
        mock_cfg.get.side_effect = _get
        sig, _ = _classify(
            total_score,
            has_mainstream=True,
            market_ok=True,
            bypass_market_confirmation=False,
            contradiction_index=0.0,
            regime=None,
            breakdown=breakdown,
            technical_filter_count=technical_filter_count,
            analyst_lb=analyst_lb,
            budget_skipped_sources=budget_skipped_sources or set(),
            ticker=ticker,
        )
    return sig


# ---------------------------------------------------------------------------
# Flag-ON tests
# ---------------------------------------------------------------------------

class TestI10FlagOn:
    """I10 active: crowd-only STRONG must be capped at WATCHLIST."""

    def test_a_crowd_only_stack_caps_at_watchlist(self):
        """(a) analysts(60)+social(35) >= 80 with zero catalyst/sec/technical/options
        → WATCHLIST, not STRONG."""
        breakdown = _make_breakdown(
            base=0,
            additional_analysts=60,
            social_apewisdom=10,
            google_trends=5,
            # zero news_catalyst, sec_filing, technical, options_flow
        )
        # Score = 60+10+5 = 75, below 80. Need to push above high threshold.
        # Use a higher base to simulate crowd-only >= high.
        breakdown2 = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            # total = 90, all crowd, zero hard evidence
        )
        assert breakdown2.total == 90

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=90,
            breakdown=breakdown2,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.WATCHLIST, (
            "Crowd-only stack at 90 should be capped at WATCHLIST when flag is ON"
        )

    def test_b_real_catalyst_preserves_strong(self):
        """(b) Same crowd-only stack + a real catalyst → STRONG preserved."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            news_catalyst=20,  # hard evidence: catalyst > 0
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT, (
            "Stack with a real news catalyst should still reach STRONG"
        )

    def test_c_high_track_record_analyst_preserves_strong(self):
        """(c) High-track-record analyst (analyst_lb=0.8 >= 0.65 threshold) → STRONG
        preserved with zero other hard evidence (before-mainstream carve-out)."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            # zero catalyst, sec, technical, options
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=0.8,  # high track record — counts as hard evidence
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT, (
            "Proven analyst (LB=0.8 >= 0.65) should count as hard evidence and reach STRONG"
        )

    def test_c_low_track_record_analyst_does_not_save(self):
        """Analyst LB below threshold (0.5 < 0.65) does NOT count as hard evidence."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=0.50,  # below threshold
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.WATCHLIST, (
            "Analyst LB=0.50 < 0.65 threshold should NOT count as hard evidence"
        )

    def test_d_budget_skipped_confirming_source_no_demotion(self):
        """(d) Confirming source (exa_queries) in budget-skipped set → NOT demoted,
        because we can't prove absence of evidence when we didn't fetch."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            # zero hard evidence
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources={"exa_queries"},  # paid confirming source skipped
        )
        assert result == SignalClass.STRONG_ALERT, (
            "Budget-skipped confirming source (exa_queries) must NOT cause demotion"
        )

    def test_d_non_confirming_skipped_source_still_demotes(self):
        """A skipped source that is NOT in confirming_paid_cols (e.g., finnhub_calls)
        does NOT block demotion."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources={"finnhub_calls"},  # NOT a confirming paid col
        )
        assert result == SignalClass.WATCHLIST, (
            "Skipping a non-confirming source (finnhub_calls) should not block demotion"
        )

    def test_e_one_technical_filter_not_enough(self):
        """(e) technical_filter_count=1 does NOT count as hard evidence (needs >= 2)."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=1,  # one filter — below min_technical_filters=2
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.WATCHLIST, (
            "1 technical filter (< min=2) should NOT count as hard evidence"
        )

    def test_e_two_technical_filters_counts_as_hard_evidence(self):
        """(e) technical_filter_count=2 counts as hard evidence (>= min_technical_filters=2)."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
        )
        assert breakdown.total >= 80

        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=2,  # exactly at min — should count
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT, (
            "2 technical filters (== min=2) should count as hard evidence → STRONG"
        )

    def test_sec_filing_preserves_strong(self):
        """SEC filing > 0 counts as hard evidence."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            sec_filing=15,
        )
        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT

    def test_options_flow_preserves_strong(self):
        """options_flow > 0 counts as hard evidence."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            options_flow=10,
        )
        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT

    def test_serpapi_skipped_no_demotion(self):
        """serpapi_queries in skipped set → NOT demoted."""
        breakdown = _make_breakdown(base=10, additional_analysts=60, social_apewisdom=15, google_trends=5)
        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources={"serpapi_queries"},
        )
        assert result == SignalClass.STRONG_ALERT

    def test_firecrawl_skipped_no_demotion(self):
        """firecrawl_credits in skipped set → NOT demoted."""
        breakdown = _make_breakdown(base=10, additional_analysts=60, social_apewisdom=15, google_trends=5)
        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources={"firecrawl_credits"},
        )
        assert result == SignalClass.STRONG_ALERT


# ---------------------------------------------------------------------------
# Flag-OFF tests — results must be byte-identical to legacy
# ---------------------------------------------------------------------------

class TestI10FlagOff:
    """Flag OFF: _classify must produce the same result as if I10 never existed."""

    def test_crowd_only_still_strong_when_flag_off(self):
        """With flag OFF, a crowd-only 90-point stack still reaches STRONG (legacy)."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
        )
        assert breakdown.total >= 80

        # Flag OFF
        result = _classify_with_cfg(
            _cfg_factory(flag_on=False),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT, (
            "Flag OFF: crowd-only STRONG should still reach STRONG (legacy behavior)"
        )

    def test_no_breakdown_still_strong_when_flag_off(self):
        """Without a breakdown arg, flag OFF, score >= high → STRONG (legacy path)."""
        result = _classify_with_cfg(
            _cfg_factory(flag_on=False),
            total_score=85,
            breakdown=None,  # no breakdown → I10 block skipped entirely
        )
        assert result == SignalClass.STRONG_ALERT

    def test_no_breakdown_flag_on_no_i10_cap(self):
        """Without a breakdown arg, even with flag ON, I10 cannot cap (no data to evaluate).
        The gate condition is `breakdown is not None` so it's a no-op."""
        result = _classify_with_cfg(
            _cfg_factory(flag_on=True),
            total_score=85,
            breakdown=None,
        )
        assert result == SignalClass.STRONG_ALERT, (
            "No breakdown + flag ON: I10 gate must be a no-op (can't evaluate without data)"
        )

    def test_watchlist_below_high_unaffected(self):
        """Scores below the high threshold are not touched by I10 logic at all."""
        breakdown = _make_breakdown(base=0, additional_analysts=30, social_apewisdom=10)
        # total = 40, well below high=80
        for flag in (True, False):
            result = _classify_with_cfg(
                _cfg_factory(flag_on=flag),
                total_score=40,
                breakdown=breakdown,
            )
            assert result == SignalClass.IGNORE, f"flag={flag}: score=40 should be IGNORE"

    def test_legacy_strong_with_breakdown_flag_off(self):
        """Flag OFF: even with breakdown passed in, STRONG is preserved (no gate fires)."""
        breakdown = _make_breakdown(
            base=10,
            additional_analysts=60,
            social_apewisdom=15,
            google_trends=5,
            # zero hard evidence
        )
        result = _classify_with_cfg(
            _cfg_factory(flag_on=False),
            total_score=breakdown.total,
            breakdown=breakdown,
            technical_filter_count=0,
            analyst_lb=None,
            budget_skipped_sources=set(),
        )
        assert result == SignalClass.STRONG_ALERT, (
            "Flag OFF: I10 gate must not fire even when breakdown is provided"
        )


# ---------------------------------------------------------------------------
# Shadow-log test: verify the log line fires regardless of flag state
# ---------------------------------------------------------------------------

class TestI10ShadowLog:
    """The [I10 shadow] log line must fire on every STRONG-threshold eval,
    even when the flag is OFF (no demotion action)."""

    def test_shadow_log_fires_flag_off(self, caplog):
        import logging
        breakdown = _make_breakdown(base=10, additional_analysts=60, social_apewisdom=15, google_trends=5)
        with caplog.at_level(logging.INFO, logger="consensus_engine.engine"):
            _classify_with_cfg(
                _cfg_factory(flag_on=False),
                total_score=breakdown.total,
                breakdown=breakdown,
                ticker="NVDA",
            )
        assert any("[I10 shadow]" in r.message for r in caplog.records), (
            "[I10 shadow] log line must fire even when the flag is OFF"
        )

    def test_shadow_log_fires_flag_on(self, caplog):
        import logging
        breakdown = _make_breakdown(base=10, additional_analysts=60, social_apewisdom=15, google_trends=5)
        with caplog.at_level(logging.INFO, logger="consensus_engine.engine"):
            _classify_with_cfg(
                _cfg_factory(flag_on=True),
                total_score=breakdown.total,
                breakdown=breakdown,
                ticker="TSLA",
            )
        assert any("[I10 shadow]" in r.message for r in caplog.records), (
            "[I10 shadow] log line must fire when the flag is ON"
        )

    def test_shadow_log_not_fired_below_threshold(self, caplog):
        """Shadow log must NOT fire when score < high (I10 only evaluates at STRONG threshold)."""
        import logging
        breakdown = _make_breakdown(base=0, additional_analysts=30, social_apewisdom=10)
        with caplog.at_level(logging.INFO, logger="consensus_engine.engine"):
            _classify_with_cfg(
                _cfg_factory(flag_on=True),
                total_score=40,
                breakdown=breakdown,
                ticker="AAPL",
            )
        assert not any("[I10 shadow]" in r.message for r in caplog.records), (
            "[I10 shadow] must NOT fire when score is below the high threshold"
        )

    def test_shadow_log_no_breakdown_no_fire(self, caplog):
        """Shadow log must NOT fire when no breakdown is passed (no data to evaluate)."""
        import logging
        with caplog.at_level(logging.INFO, logger="consensus_engine.engine"):
            _classify_with_cfg(
                _cfg_factory(flag_on=True),
                total_score=90,
                breakdown=None,
                ticker="SPY",
            )
        assert not any("[I10 shadow]" in r.message for r in caplog.records), (
            "[I10 shadow] must NOT fire without a breakdown argument"
        )
