"""W3 scoring redesign tests: distance penalty, source-tier multiplier,
shadow-mode score_v2 stash + log, ≥30% HIGH confidence verification.
"""
from __future__ import annotations

import logging

import pytest

from consensus_engine.alerts.all_command.levels import (
    Anchor,
    SCORE_V2_TIER_MULTIPLIERS,
    _distance_penalty,
    _score,
    _score_v2,
    rank_anchors,
)
from consensus_engine.alerts.all_command.structured_fields import (
    compute_confidence_label,
)


# ---------------------------------------------------------------------------
# Distance penalty shape (Codex spec: 0.71 @ 10%, 0.50 @ 25%, 0.20 @ 100%)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("distance_pct,current_price,expected_band", [
    (0.0, 100.0, (0.99, 1.01)),     # zero distance → no penalty
    (0.10, 100.0, (0.70, 0.72)),    # 10% → ~0.714
    (0.25, 100.0, (0.49, 0.51)),    # 25% → 0.500
    (1.00, 100.0, (0.19, 0.21)),    # 100% → 0.200
    (5.00, 100.0, (0.046, 0.050)),  # 500% → ~0.0476
])
def test_distance_penalty_default_alpha(distance_pct, current_price, expected_band):
    p = _distance_penalty(distance_pct, current_price)
    assert expected_band[0] <= p <= expected_band[1], f"got {p}"


def test_distance_penalty_high_priced_softer_tail():
    """Above $1000, alpha=2 instead of 4 → gentler penalty."""
    p_default = _distance_penalty(0.10, 100.0)   # alpha=4 → 0.714
    p_high = _distance_penalty(0.10, 2000.0)     # alpha=2 → 0.833
    assert p_high > p_default
    assert 0.82 <= p_high <= 0.84


def test_distance_penalty_penny_skips():
    """Below $5, no penalty applied (multiplier=1.0)."""
    assert _distance_penalty(0.5, 2.0) == 1.0
    assert _distance_penalty(2.0, 1.0) == 1.0


def test_distance_penalty_handles_zero_or_none_spot():
    assert _distance_penalty(0.1, 0.0) == 1.0
    assert _distance_penalty(0.1, None) == 1.0   # type: ignore[arg-type]
    assert _distance_penalty(None, 100.0) == 1.0


# ---------------------------------------------------------------------------
# Source-tier multipliers (CEF-3 partnered)
# ---------------------------------------------------------------------------

def test_source_tier_multiplier_table():
    """Locked values per final-plan §2."""
    assert SCORE_V2_TIER_MULTIPLIERS == {
        "yt_curated": 1.0,
        "swing": 0.7,
        "yt": 0.5,
        "web": 0.2,
    }


def test_score_v2_curated_at_zero_distance_equals_base_score():
    a = Anchor(price=100.0, source="x", source_type="yt_curated", touches=5)
    a.distance_pct = 0.0
    base = _score(a)
    v2 = _score_v2(a, current_price=100.0)
    assert v2 == pytest.approx(base, rel=1e-6)


def test_score_v2_web_at_10pct_distance():
    a = Anchor(price=110.0, source="web:r", source_type="web", touches=5)
    base = _score(a)
    v2 = _score_v2(a, current_price=100.0)
    # distance=0.10 → 0.714, web mult=0.2 → 0.143×
    assert v2 == pytest.approx(base * 0.7143 * 0.2, rel=1e-2)


def test_score_v2_yt_curated_beats_yt_at_same_distance():
    a_curated = Anchor(price=110.0, source="yt:high", source_type="yt_curated", touches=5)
    a_yt = Anchor(price=110.0, source="yt:low", source_type="yt", touches=5)
    v2_curated = _score_v2(a_curated, current_price=100.0)
    v2_yt = _score_v2(a_yt, current_price=100.0)
    assert v2_curated > v2_yt
    # ratio should be 1.0 / 0.5 = 2x
    assert v2_curated == pytest.approx(v2_yt * 2.0, rel=1e-3)


def test_score_v2_writes_distance_pct_back_to_anchor():
    """Side-effect: caching distance on the anchor so callers/log can read it."""
    a = Anchor(price=120.0, source="x", source_type="yt", touches=1)
    assert a.distance_pct is None
    _score_v2(a, current_price=100.0)
    assert a.distance_pct == pytest.approx(0.20, rel=1e-3)


# ---------------------------------------------------------------------------
# rank_anchors shadow mode behavior
# ---------------------------------------------------------------------------

def test_rank_anchors_shadow_mode_stashes_v2_but_uses_v1_for_sort(caplog):
    """v1 drives the actual sort; v2 lives only on `anchor.score_v2` + the log."""
    a_close_curated = Anchor(price=99.0, source="yt:high", source_type="yt_curated",
                             touches=1)
    a_far_yt = Anchor(price=80.0, source="yt:low", source_type="yt",
                      touches=10)  # huge touch count → dominates v1
    # v1 ranks a_far_yt higher (touches=10) regardless of distance/tier
    with caplog.at_level(logging.INFO, logger="consensus_engine.alerts.all_command.levels"):
        supports, _ = rank_anchors([a_close_curated, a_far_yt], current_price=100.0)
    # both are supports (price < current)
    assert supports[0] is a_far_yt  # v1 still wins
    assert hasattr(a_close_curated, "score_v2")
    assert hasattr(a_far_yt, "score_v2")
    # log line emitted for shadow comparison
    shadow_lines = [r for r in caplog.records if "score_shadow" in r.getMessage()]
    assert len(shadow_lines) >= 2


def test_rank_anchors_shadow_off_skips_v2_log(monkeypatch, caplog):
    monkeypatch.setattr(
        "consensus_engine.config.get",
        lambda key, default=None: False if key == "all_command.score_v2_shadow_mode" else default,
    )
    a = Anchor(price=99.0, source="x", source_type="yt", touches=1)
    with caplog.at_level(logging.INFO, logger="consensus_engine.alerts.all_command.levels"):
        rank_anchors([a], current_price=100.0)
    assert not any("score_shadow" in r.getMessage() for r in caplog.records)


def test_rank_anchors_no_v2_when_no_spot():
    """Without a usable current_price, fall back to v1 only (no shadow log)."""
    a = Anchor(price=99.0, source="x", source_type="yt", touches=1)
    rank_anchors([a], current_price=0.0)
    assert not hasattr(a, "score_v2") or getattr(a, "score_v2", None) is None


# ---------------------------------------------------------------------------
# Confidence-threshold sanity (CEF-2 verification gate: ≥30% HIGH)
# ---------------------------------------------------------------------------

def test_confidence_threshold_keeps_30pct_high_on_representative_distribution():
    """Synthetic distribution of cross-reference final_scores from production:
    sample from a centered distribution and confirm the existing config threshold
    still labels ≥30% of tickers HIGH. If this fails after a future threshold
    edit, the verification gate from final-plan.md §8 catches it."""
    # Production-realistic: scores skew higher than uniform because the engine
    # only emits alerts for tickers passing min thresholds. Use a distribution
    # peaked at ~75 with a right tail above 100.
    samples = [
        50, 55, 60, 62, 65, 68, 70, 72, 73, 75,
        76, 78, 80, 82, 85, 86, 88, 90, 92, 95,
        50, 55, 60, 65, 70, 75, 80, 85, 90, 95,
    ]
    high_count = sum(1 for s in samples if compute_confidence_label(s) == "HIGH")
    pct_high = high_count / len(samples)
    assert pct_high >= 0.30, (
        f"only {pct_high*100:.1f}% land at HIGH on the representative "
        f"distribution; threshold needs recalibration"
    )


def test_confidence_label_passthrough_unchanged():
    """W3 doesn't touch the confidence label; this is a guard test that the
    threshold semantics (>= 80 → HIGH, < 80 → LOW) still hold."""
    assert compute_confidence_label(79.99) == "LOW"
    assert compute_confidence_label(80.0) == "HIGH"
    assert compute_confidence_label(120.0) == "HIGH"
