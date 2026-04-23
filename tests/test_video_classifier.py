"""Unit tests for the Stage B deterministic video classifier.

Covers direction/conviction, level type, setup clustering, catalyst extraction,
macro thesis building, suppression, near-price dedup, and a synthetic
4mSyMr8PGLI-style fixture (MSFT/SPY/NDX bullish; USO not-short; TSLA/NVDA
neutral-low suppressed).
"""
from __future__ import annotations

from consensus_engine.analysis.video_classifier import (
    ClassificationResult,
    _build_macro_thesis,
    _classify_direction,
    _classify_level_type,
    _cluster_setups,
    _extract_catalyst_candidates,
    _suppress_near_price_dedup,
    _suppress_weak_signals,
    classify_evidence,
)
from consensus_engine.models import (
    CATALYST_TYPES,
    CandidateLevel,
    CandidateSignal,
    Conviction,
    Direction,
    EvidenceBundle,
    EvidenceSpan,
    LEVEL_TYPES,
)


# ---------------------------------------------------------------------------
# 1. Direction tests
# ---------------------------------------------------------------------------

def test_direction_bullish_happy_path():
    spans = [
        EvidenceSpan(ts_sec=10, quote="MSFT is my top pick, going long",
                     tickers=["MSFT"]),
        EvidenceSpan(ts_sec=30, quote="MSFT breakout target higher",
                     tickers=["MSFT"]),
        EvidenceSpan(ts_sec=50, quote="MSFT bullish setup",
                     tickers=["MSFT"]),
    ]
    direction, conviction, conf, count, ctx = _classify_direction(spans, "MSFT")
    assert direction == Direction.LONG
    assert conviction in (Conviction.MEDIUM, Conviction.HIGH)
    assert count == 3
    assert conf > 0.4
    assert "MSFT" in ctx


def test_direction_rejects_short_from_past_tense_recap():
    # The USO counterexample from the plan.
    spans = [
        EvidenceSpan(ts_sec=20, quote="oil is down 18% this year",
                     tickers=["USO"]),
    ]
    direction, conviction, _, _, _ = _classify_direction(spans, "USO")
    # past-tense "is down" without forward-looking verb → must not be SHORT.
    assert direction != Direction.SHORT
    assert conviction == Conviction.LOW


def test_direction_negation_flips_to_neutral():
    spans = [
        EvidenceSpan(ts_sec=20, quote="I don't like TSLA here, not bullish",
                     tickers=["TSLA"]),
    ]
    direction, _, _, _, _ = _classify_direction(spans, "TSLA")
    assert direction == Direction.NEUTRAL


def test_direction_forward_looking_short_accepted():
    spans = [
        EvidenceSpan(ts_sec=10, quote="I'd short XYZ if it breaks below support",
                     tickers=["XYZ"]),
        EvidenceSpan(ts_sec=30, quote="XYZ bias to lower, going to fade",
                     tickers=["XYZ"]),
    ]
    direction, _, _, _, _ = _classify_direction(spans, "XYZ")
    assert direction == Direction.SHORT


def test_direction_neutral_when_no_tickers_match():
    spans = [EvidenceSpan(ts_sec=10, quote="bullish", tickers=["AAPL"])]
    direction, conviction, conf, count, _ = _classify_direction(spans, "MSFT")
    assert direction == Direction.NEUTRAL
    assert count == 0
    assert conf == 0.0


def test_direction_conviction_scales_with_mention_count():
    one = [EvidenceSpan(ts_sec=1, quote="NVDA long", tickers=["NVDA"])]
    two = [
        EvidenceSpan(ts_sec=1, quote="NVDA long", tickers=["NVDA"]),
        EvidenceSpan(ts_sec=2, quote="NVDA bullish", tickers=["NVDA"]),
    ]
    four = [
        EvidenceSpan(ts_sec=i, quote="NVDA long bullish", tickers=["NVDA"])
        for i in range(4)
    ]
    _, c1, _, _, _ = _classify_direction(one, "NVDA")
    _, c2, _, _, _ = _classify_direction(two, "NVDA")
    _, c3, _, _, _ = _classify_direction(four, "NVDA")
    assert c1 == Conviction.LOW
    assert c2 == Conviction.MEDIUM
    assert c3 == Conviction.HIGH


def test_direction_upgrades_on_top_pick_phrase():
    spans = [
        EvidenceSpan(ts_sec=1, quote="MSFT my number one draft pick",
                     tickers=["MSFT"]),
    ]
    _, conv, _, _, _ = _classify_direction(spans, "MSFT")
    # low → upgraded to medium by "number one draft pick".
    assert conv == Conviction.MEDIUM


# ---------------------------------------------------------------------------
# 2. Level-type tests
# ---------------------------------------------------------------------------

def test_level_type_resistance():
    sp = EvidenceSpan(ts_sec=1, quote="500 is overhead resistance, capping rally",
                      tickers=["MSFT"], numbers=[500])
    lt, conf = _classify_level_type(sp, 500)
    assert lt == "resistance"
    assert conf > 0.7


def test_level_type_support():
    sp = EvidenceSpan(ts_sec=1, quote="buyers at 400 support, defended on pullback",
                      tickers=["MSFT"], numbers=[400])
    lt, _ = _classify_level_type(sp, 400)
    assert lt == "support"


def test_level_type_ema():
    sp = EvidenceSpan(ts_sec=1, quote="the 8 EMA is at 400.15",
                      tickers=["MSFT"], numbers=[400.15])
    lt, _ = _classify_level_type(sp, 400.15)
    assert lt == "ema"


def test_level_type_ma_moving_average():
    sp = EvidenceSpan(ts_sec=1, quote="200-day moving average holds at 450",
                      tickers=["MSFT"], numbers=[450])
    lt, _ = _classify_level_type(sp, 450)
    assert lt == "ma"


def test_level_type_target():
    sp = EvidenceSpan(ts_sec=1, quote="target is 700 for MSFT objective",
                      tickers=["MSFT"], numbers=[700])
    lt, _ = _classify_level_type(sp, 700)
    assert lt == "target"


def test_level_type_breakdown():
    sp = EvidenceSpan(ts_sec=1, quote="breakdown below 600 would be bad",
                      tickers=["MSFT"], numbers=[600])
    lt, _ = _classify_level_type(sp, 600)
    assert lt == "breakdown"


def test_level_type_prior_ath_context_is_support():
    sp = EvidenceSpan(
        ts_sec=1,
        quote="400 was the previous all-time high, now support on pullback",
        tickers=["MSFT"], numbers=[400],
    )
    lt, _ = _classify_level_type(sp, 400)
    assert lt == "support"


def test_level_type_defaults_to_target_when_ambiguous():
    sp = EvidenceSpan(ts_sec=1, quote="MSFT at 500", tickers=["MSFT"],
                      numbers=[500])
    lt, conf = _classify_level_type(sp, 500)
    assert lt in LEVEL_TYPES
    # Ambiguous → low confidence so read-time filters can drop.
    assert conf <= 0.5


# ---------------------------------------------------------------------------
# 3. Setup clustering tests
# ---------------------------------------------------------------------------

def test_setup_requires_at_least_two_components():
    spans = [
        EvidenceSpan(ts_sec=10,
                     quote="entry at 400", tickers=["MSFT"], numbers=[400]),
    ]
    setups = _cluster_setups(spans, "MSFT")
    assert setups == []


def test_setup_entry_stop_target_same_cluster():
    spans = [
        EvidenceSpan(ts_sec=10, quote="entry at 400 target 450",
                     tickers=["MSFT"], numbers=[400, 450]),
        EvidenceSpan(ts_sec=30, quote="stop below 389",
                     tickers=["MSFT"], numbers=[389]),
    ]
    setups = _cluster_setups(spans, "MSFT")
    assert len(setups) == 1
    s = setups[0]
    assert s.entry_low == 400
    assert s.stop == 389
    assert 450 in s.targets
    assert s.risk_reward is not None


def test_setup_entry_plus_catalyst_date_counts_as_two():
    spans = [
        EvidenceSpan(ts_sec=10,
                     quote="entry at 400 into April 29 earnings",
                     tickers=["MSFT"], numbers=[400],
                     dates_mentioned=["April 29"]),
    ]
    setups = _cluster_setups(spans, "MSFT")
    assert len(setups) == 1
    assert setups[0].catalyst_date == "April 29"


def test_setup_clusters_split_beyond_window():
    spans = [
        EvidenceSpan(ts_sec=10, quote="entry at 400",
                     tickers=["MSFT"], numbers=[400]),
        EvidenceSpan(ts_sec=2000,
                     quote="stop at 389 target 450",
                     tickers=["MSFT"], numbers=[389, 450]),
    ]
    # 2000s gap > 90s window → separate clusters, first has only entry → dropped,
    # second has stop+target → kept.
    setups = _cluster_setups(spans, "MSFT")
    assert len(setups) == 1
    assert setups[0].stop == 389


# ---------------------------------------------------------------------------
# 4. Catalyst extraction tests
# ---------------------------------------------------------------------------

def test_catalyst_one_per_ticker_date_pair():
    spans = [
        EvidenceSpan(ts_sec=10, quote="MSFT April 29 earnings",
                     tickers=["MSFT"],
                     dates_mentioned=["April 29"]),
        EvidenceSpan(ts_sec=15, quote="MSFT April 29 beat expected",
                     tickers=["MSFT"],
                     dates_mentioned=["April 29"]),
    ]
    cats = _extract_catalyst_candidates(spans)
    assert len(cats) == 1
    assert cats[0].ticker == "MSFT"
    assert cats[0].mentioned_date == "April 29"
    assert cats[0].catalyst_type == "earnings"
    assert cats[0].resolved_date is None
    assert cats[0].verified == 0


def test_catalyst_type_inference():
    spans = [
        EvidenceSpan(ts_sec=1, quote="FOMC rate decision next Wednesday",
                     tickers=["SPY"], dates_mentioned=["next Wednesday"]),
        EvidenceSpan(ts_sec=2, quote="CPI inflation print on Tuesday",
                     tickers=["SPY"], dates_mentioned=["Tuesday"]),
        EvidenceSpan(ts_sec=3, quote="NFP jobs Friday",
                     tickers=["SPY"], dates_mentioned=["Friday"]),
    ]
    cats = _extract_catalyst_candidates(spans)
    types = {c.catalyst_type for c in cats}
    assert "fed" in types
    assert "cpi" in types
    assert "jobs" in types
    for c in cats:
        assert c.catalyst_type in CATALYST_TYPES


def test_catalyst_type_falls_back_to_other():
    spans = [
        EvidenceSpan(ts_sec=1, quote="product launch on June 1",
                     tickers=["AAPL"], dates_mentioned=["June 1"]),
    ]
    cats = _extract_catalyst_candidates(spans)
    assert len(cats) == 1
    assert cats[0].catalyst_type == "other"


# ---------------------------------------------------------------------------
# 5. Macro thesis tests
# ---------------------------------------------------------------------------

def test_macro_thesis_narrative_concatenates_macro_spans():
    spans = [
        EvidenceSpan(ts_sec=1, quote="S&P showing strong uptrend",
                     tickers=["SPY"]),
        EvidenceSpan(ts_sec=2, quote="Nasdaq leading bullish breakout",
                     tickers=["QQQ"]),
        EvidenceSpan(ts_sec=3, quote="VIX crushed, macro risk-on",
                     tickers=[]),
        EvidenceSpan(ts_sec=4, quote="random chit-chat", tickers=[]),
    ]
    macro = _build_macro_thesis(spans)
    # macro keywords in three spans, so narrative should include them
    assert "S&P" in macro.narrative or "Nasdaq" in macro.narrative
    assert "VIX" in macro.narrative or "macro" in macro.narrative
    assert macro.direction == Direction.LONG


def test_macro_thesis_empty_when_no_macro_spans():
    spans = [
        EvidenceSpan(ts_sec=1, quote="MSFT looking strong",
                     tickers=["MSFT"]),
    ]
    macro = _build_macro_thesis(spans)
    assert macro.narrative == ""
    assert macro.direction == Direction.NEUTRAL


# ---------------------------------------------------------------------------
# 6. Suppression tests
# ---------------------------------------------------------------------------

def test_suppress_weak_signals_marks_neutral_low():
    sigs = [
        CandidateSignal(ticker="TSLA", direction=Direction.NEUTRAL,
                        conviction=Conviction.LOW, mention_count=1,
                        context=""),
        CandidateSignal(ticker="MSFT", direction=Direction.LONG,
                        conviction=Conviction.HIGH, mention_count=5,
                        context=""),
    ]
    _suppress_weak_signals(sigs)
    assert sigs[0].suppressed is True
    assert sigs[0].suppression_reason == "neutral_low"
    assert sigs[1].suppressed is False


def test_near_price_dedup_keeps_first_suppresses_duplicate():
    levels = [
        CandidateLevel(ticker="SPY", level_type="support",
                       price=7000.0, context=""),
        CandidateLevel(ticker="SPY", level_type="support",
                       price=7002.0, context=""),  # within 0.5%
        CandidateLevel(ticker="SPY", level_type="support",
                       price=7500.0, context=""),  # far apart
    ]
    _suppress_near_price_dedup(levels)
    # Group sorted by price — 7000 kept, 7002 suppressed, 7500 kept
    by_price = {l.price: l for l in levels}
    assert by_price[7000.0].suppressed is False
    assert by_price[7002.0].suppressed is True
    assert by_price[7002.0].suppression_reason == "near_price_dedup"
    assert by_price[7500.0].suppressed is False


def test_near_price_dedup_separate_types_independent():
    levels = [
        CandidateLevel(ticker="SPY", level_type="support",
                       price=7000.0, context=""),
        CandidateLevel(ticker="SPY", level_type="resistance",
                       price=7001.0, context=""),
    ]
    _suppress_near_price_dedup(levels)
    # different level_types → neither suppressed
    assert all(not l.suppressed for l in levels)


# ---------------------------------------------------------------------------
# 7. Public API / end-to-end tests
# ---------------------------------------------------------------------------

def _span(ts, quote, tickers=None, numbers=None, dates=None):
    return EvidenceSpan(
        ts_sec=ts, quote=quote,
        tickers=list(tickers or []),
        numbers=list(numbers or []),
        dates_mentioned=list(dates or []),
    )


def test_classify_evidence_returns_classification_result():
    bundle = EvidenceBundle(
        video_id="x", duration_sec=60, publish_ts="2026-04-17T00:00:00Z",
        spans=[_span(1, "MSFT long bullish", ["MSFT"])],
    )
    result = classify_evidence(bundle)
    assert isinstance(result, ClassificationResult)
    assert result.macro_thesis is not None
    assert len(result.signals) == 1


def test_classify_evidence_empty_bundle():
    bundle = EvidenceBundle(
        video_id="x", duration_sec=None, publish_ts="2026-04-17T00:00:00Z",
        spans=[],
    )
    result = classify_evidence(bundle)
    assert result.signals == []
    assert result.levels == []
    assert result.setups == []
    assert result.catalyst_candidates == []


def test_reference_video_style_fixture_4mSyMr8PGLI():
    """Synthetic replay of the reference video: MSFT/SPY/NDX bullish HIGH,
    USO past-tense (not SHORT), TSLA/NVDA neutral-low (suppressed)."""
    spans = [
        # MSFT — bullish, multiple mentions, earnings catalyst
        _span(100, "MSFT my number one draft pick going long",
              ["MSFT"]),
        _span(120, "MSFT bullish breakout at 400.15 on 8 EMA",
              ["MSFT"], [400.15]),
        _span(150, "MSFT entry 400 stop 389 target 450 into April 29 earnings",
              ["MSFT"], [400, 389, 450], ["April 29"]),
        _span(170, "MSFT uptrend conviction", ["MSFT"]),
        # SPY — bullish macro
        _span(200, "S&P bullish breakout, market going higher",
              ["SPY"]),
        _span(230, "SPY long, rally continues", ["SPY"]),
        _span(260, "SPY bullish", ["SPY"]),
        _span(290, "SPY uptrend", ["SPY"]),
        # NDX — bullish
        _span(300, "Nasdaq NDX bullish breakout target", ["NDX"]),
        _span(330, "NDX long call", ["NDX"]),
        _span(360, "NDX rally higher", ["NDX"]),
        _span(390, "NDX bullish", ["NDX"]),
        # USO — past tense recap, not short
        _span(500, "oil is down 18% this year", ["USO"]),
        # TSLA — one mention, neutral-low
        _span(600, "TSLA interesting chart", ["TSLA"]),
        # NVDA — one mention, neutral-low
        _span(700, "NVDA at all time highs, wait and see", ["NVDA"]),
    ]
    bundle = EvidenceBundle(
        video_id="4mSyMr8PGLI", duration_sec=2400,
        publish_ts="2026-04-17T00:00:00Z", spans=spans,
    )
    r = classify_evidence(bundle)
    sig_by_ticker = {s.ticker: s for s in r.signals}

    # MSFT/SPY/NDX — long + high conviction
    for sym in ("MSFT", "SPY", "NDX"):
        assert sig_by_ticker[sym].direction == Direction.LONG, sym
        assert sig_by_ticker[sym].conviction == Conviction.HIGH, sym
        assert sig_by_ticker[sym].suppressed is False, sym

    # USO — NOT short
    assert sig_by_ticker["USO"].direction != Direction.SHORT

    # TSLA / NVDA — neutral + low → suppressed
    for sym in ("TSLA", "NVDA"):
        assert sig_by_ticker[sym].direction == Direction.NEUTRAL
        assert sig_by_ticker[sym].conviction == Conviction.LOW
        assert sig_by_ticker[sym].suppressed is True, sym
        assert sig_by_ticker[sym].suppression_reason == "neutral_low"

    # MSFT setup absorbed: entry+stop+target present + catalyst date
    msft_setups = [s for s in r.setups if s.ticker == "MSFT"]
    assert len(msft_setups) >= 1
    s = msft_setups[0]
    assert s.entry_low == 400
    assert s.stop == 389
    assert 450 in s.targets
    # classify_evidence resolves raw dates against bundle.publish_ts.
    assert s.catalyst_date == "2026-04-29"
    assert s.risk_reward is not None

    # Macro thesis built from SPY/NDX quotes
    assert r.macro_thesis.direction == Direction.LONG
    assert r.macro_thesis.narrative != ""

    # At least one earnings catalyst candidate
    assert any(c.catalyst_type == "earnings" for c in r.catalyst_candidates)


def test_classify_evidence_suppresses_not_deletes():
    """Regression: suppressed candidates must still be returned (filters happen
    at read time, per plan principle 1)."""
    spans = [_span(1, "TSLA nothing much", ["TSLA"])]
    bundle = EvidenceBundle(
        video_id="x", duration_sec=60, publish_ts="2026-04-17T00:00:00Z",
        spans=spans,
    )
    r = classify_evidence(bundle)
    assert len(r.signals) == 1
    assert r.signals[0].suppressed is True
    # Still present, not dropped
    assert r.signals[0].ticker == "TSLA"


def test_classify_evidence_near_price_dedup_applies():
    spans = [
        _span(1, "SPY support at 7000 defended", ["SPY"], [7000]),
        _span(2, "SPY support at 7002 buyers", ["SPY"], [7002]),
    ]
    bundle = EvidenceBundle(
        video_id="x", duration_sec=60, publish_ts="2026-04-17T00:00:00Z",
        spans=spans,
    )
    r = classify_evidence(bundle)
    support_levels = [
        l for l in r.levels if l.level_type == "support" and l.ticker == "SPY"
    ]
    assert len(support_levels) == 2
    assert sum(1 for l in support_levels if l.suppressed) == 1
    assert sum(1 for l in support_levels if not l.suppressed) == 1


def test_classify_evidence_respects_taxonomy():
    """Every level/setup/catalyst type must belong to its taxonomy constant."""
    spans = [
        _span(1, "MSFT support at 400", ["MSFT"], [400]),
        _span(2, "MSFT resistance at 500", ["MSFT"], [500]),
        _span(3, "MSFT 8 EMA at 410", ["MSFT"], [410]),
        _span(4, "MSFT April 29 earnings report", ["MSFT"],
              dates=["April 29"]),
    ]
    bundle = EvidenceBundle(
        video_id="x", duration_sec=60, publish_ts="2026-04-17T00:00:00Z",
        spans=spans,
    )
    r = classify_evidence(bundle)
    for lvl in r.levels:
        assert lvl.level_type in LEVEL_TYPES, lvl.level_type
    for cat in r.catalyst_candidates:
        assert cat.catalyst_type in CATALYST_TYPES, cat.catalyst_type
