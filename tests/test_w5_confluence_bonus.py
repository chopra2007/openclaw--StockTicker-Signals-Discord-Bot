"""W5 C-C8 confluence bonus tests."""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command.levels import (
    Anchor,
    SCORE_V2_CONFLUENCE_MAX_MULT,
    SCORE_V2_CONFLUENCE_PER_TIER,
    _confluence_bonus,
    _score_v2,
    cluster_anchors,
    rank_anchors,
)


# ---------------------------------------------------------------------------
# _confluence_bonus helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tier_set,expected", [
    (None, 1.0),
    (set(), 1.0),
    ({"yt"}, 1.0),                           # singleton — no bonus
    ({"yt", "web"}, 1.0 + SCORE_V2_CONFLUENCE_PER_TIER),  # 2 tiers → 1.10
    ({"yt", "web", "swing"}, 1.0 + 2 * SCORE_V2_CONFLUENCE_PER_TIER),  # 1.20
    ({"yt", "web", "swing", "yt_curated"}, 1.0 + 3 * SCORE_V2_CONFLUENCE_PER_TIER),  # 1.30
])
def test_confluence_bonus_scales_with_tier_count(tier_set, expected):
    assert _confluence_bonus(tier_set) == pytest.approx(expected, rel=1e-6)


def test_confluence_bonus_capped_at_max():
    """Even with many tiers, bonus never exceeds 1.5×."""
    huge_set = {f"tier_{i}" for i in range(10)}
    assert _confluence_bonus(huge_set) == SCORE_V2_CONFLUENCE_MAX_MULT


# ---------------------------------------------------------------------------
# _score_v2 with the bonus toggle
# ---------------------------------------------------------------------------

def test_score_v2_no_bonus_when_disabled():
    a = Anchor(price=100.0, source="x", source_type="yt", touches=2)
    a.cluster_source_types = {"yt", "web", "swing"}
    base = _score_v2(a, current_price=100.0, confluence_bonus_enabled=False)
    boosted = _score_v2(a, current_price=100.0, confluence_bonus_enabled=True)
    assert boosted > base
    # 3-tier cluster → 1.0 + 2 * 0.1 = 1.2× boost
    assert boosted == pytest.approx(base * 1.2, rel=1e-3)


def test_score_v2_no_bonus_for_singleton_tier():
    a = Anchor(price=100.0, source="x", source_type="yt", touches=2)
    a.cluster_source_types = {"yt"}
    enabled = _score_v2(a, current_price=100.0, confluence_bonus_enabled=True)
    disabled = _score_v2(a, current_price=100.0, confluence_bonus_enabled=False)
    assert enabled == pytest.approx(disabled, rel=1e-9)


def test_score_v2_no_bonus_when_cluster_source_types_none():
    """Singletons that didn't go through cluster_anchors lack the set —
    handled gracefully (no bonus, no crash)."""
    a = Anchor(price=100.0, source="x", source_type="yt")
    a.cluster_source_types = None
    s = _score_v2(a, current_price=100.0, confluence_bonus_enabled=True)
    assert s > 0  # didn't crash


# ---------------------------------------------------------------------------
# End-to-end through cluster_anchors → rank_anchors
# ---------------------------------------------------------------------------

def test_e2e_cluster_bonus_propagates_to_score_v2(monkeypatch):
    """Cluster two anchors of different tiers, enable bonus via monkeypatch
    on the config, run rank_anchors, confirm the merged anchor's score_v2
    reflects the cluster bonus."""
    def _stub(key, default=None):
        if key == "all_command.confluence_bonus_enabled":
            return True
        if key == "all_command.score_v2_shadow_mode":
            return True
        return default
    monkeypatch.setattr("consensus_engine.config.get", _stub)

    a_yt = Anchor(price=100.0, source="yt:lottery", source_type="yt",
                  touches=2, trust_score=0.5)
    a_swing = Anchor(price=100.2, source="swing_low", source_type="swing",
                     touches=2)
    merged = cluster_anchors([a_yt, a_swing], threshold_pct=0.005)
    assert len(merged) == 1
    # Cluster has {yt, swing} → 2 tiers → 1.1× bonus
    assert merged[0].cluster_source_types == {"yt", "swing"}

    supports, _ = rank_anchors(merged, current_price=101.0)
    assert supports[0] is merged[0]
    assert hasattr(merged[0], "score_v2")
    # v2 = base × penalty × swing-mult(0.7) × confluence(1.1)
    base = supports[0].computed_score
    expected_min = base * 0.7 * 1.05  # rough lower bound — sanity only
    assert supports[0].score_v2 >= expected_min
