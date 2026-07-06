"""Tests for the #63 decision-first alert card.

Covers the new `format_decision_card` render and confirms the flag-OFF legacy
path (`format_detail_followup`) is untouched. The classification-driven
ACT/WATCH + Strong/Lean/Watch bucket rule is exercised across the three shapes
that matter: Strong+corroborator+stop (ACT with a Trade), and WATCHLIST with no
corroborator and no stop (WATCH, no Trade).
"""
from consensus_engine.models import (
    CrossReferenceResult, ScoreBreakdown, TechnicalResult, OptionsResult,
)
from consensus_engine.alerts.discord import (
    format_decision_card, format_detail_followup,
)


def _strong_precision():
    """Minimal precision dict standing in for a STRONG_ALERT classification.
    format_decision_card reads only .get('skipped') and .get('classification');
    classification is compared by its string form, so a plain string works."""
    return {"skipped": False, "classification": "STRONG_ALERT"}


def _watchlist_precision():
    return {"skipped": False, "classification": "WATCHLIST"}


def test_flag_off_legacy_detail_followup_unchanged():
    """Flag-OFF path is unaffected: format_detail_followup still builds the legacy
    'Cross-Reference: $... | Score: ...' title."""
    breakdown = ScoreBreakdown(base=30, news_catalyst=15)
    xref = CrossReferenceResult(
        ticker="NVDA", breakdown=breakdown,
        catalyst_summary="PT raised", catalyst_type="Analyst Upgrade",
        technical=None, other_analysts=[], social_summary="", llm_reasoning="",
    )
    embed = format_detail_followup(xref)
    assert embed["title"].startswith("Cross-Reference: $NVDA | Score:")


def test_decision_card_strong_corroborated_with_stop_is_act():
    """Strong class + hard corroborator (unusual options) + a real ATR stop →
    '🟢 ACT' title and a Trade field with a Stop."""
    breakdown = ScoreBreakdown(base=30, options_flow=10)
    tech = TechnicalResult(ticker="TSLA", filters=[], price=400.0, atr14=8.0)
    opt = OptionsResult(
        ticker="TSLA", unusual_calls=True,
        max_call_ratio=12.0, total_call_vol=20000.0, total_put_vol=5000.0,
    )
    xref = CrossReferenceResult(
        ticker="TSLA", breakdown=breakdown,
        catalyst_summary="", catalyst_type="",
        technical=tech, other_analysts=[], social_summary="",
        llm_reasoning="", options=opt,
    )
    embed = format_decision_card(xref, _strong_precision())
    assert embed["title"].startswith("🟢 ACT")
    assert "TSLA" in embed["title"]
    trade = next((f for f in embed["fields"] if f["name"] == "Trade"), None)
    assert trade is not None
    assert "Stop" in trade["value"]


def test_decision_card_watchlist_no_corroborator_no_stop_is_watch():
    """WATCHLIST, no corroborator, atr14=None → '🟡 WATCH' title, NO Trade field,
    bucket 'Watch' in the description."""
    breakdown = ScoreBreakdown(base=20)
    tech = TechnicalResult(ticker="AMD", filters=[], price=150.0, atr14=None)
    xref = CrossReferenceResult(
        ticker="AMD", breakdown=breakdown,
        catalyst_summary="", catalyst_type="",
        technical=tech, other_analysts=[], social_summary="", llm_reasoning="",
    )
    embed = format_decision_card(xref, _watchlist_precision())
    assert embed["title"].startswith("🟡 WATCH")
    assert not any(f["name"] == "Trade" for f in embed["fields"])
    assert "Watch" in embed["description"]
    # No-stop Watch line must say it's not actionable.
    watch = next(f for f in embed["fields"] if f["name"] == "Watch")
    assert "not actionable" in watch["value"]


def test_decision_card_hides_legacy_internal_fields():
    """Kill-list: none of the additive-arithmetic / precision / regime fields
    leak into the decision card."""
    breakdown = ScoreBreakdown(base=30, options_flow=10)
    tech = TechnicalResult(ticker="MU", filters=[], price=100.0, atr14=3.0)
    opt = OptionsResult(ticker="MU", unusual_calls=True, max_call_ratio=9.0,
                        total_call_vol=8000.0, total_put_vol=2000.0)
    xref = CrossReferenceResult(
        ticker="MU", breakdown=breakdown,
        catalyst_summary="Guidance raised", catalyst_type="Guidance",
        technical=tech, other_analysts=[], social_summary="",
        llm_reasoning="", options=opt,
    )
    embed = format_decision_card(xref, _strong_precision())
    names = {f["name"] for f in embed["fields"]}
    assert "Breakdown" not in names
    assert "Precision Engine" not in names
    assert "Regime" not in names
