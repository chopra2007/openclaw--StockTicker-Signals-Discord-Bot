"""W2 provenance plumbing tests: max-tier cluster, channel_id propagation,
trust pre-fetch, cluster_source_types retention.
"""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import levels
from consensus_engine.alerts.all_command.levels import (
    Anchor,
    SOURCE_TIER_ORDER,
    _max_tier,
    cluster_anchors,
    extract_anchors_from_youtube_levels,
)


# ---------------------------------------------------------------------------
# _max_tier helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_types,expected", [
    (["yt_curated", "web"], "yt_curated"),
    (["web", "yt_curated"], "yt_curated"),
    (["yt", "web"], "yt"),
    (["swing", "web"], "swing"),
    (["swing", "yt", "yt_curated"], "yt_curated"),
    (["web"], "web"),
    (["yt"], "yt"),
    (["unknown"], "unknown"),  # falls back to first element
    ([], "web"),                # empty cluster → conservative default
])
def test_max_tier(input_types, expected):
    assert _max_tier(input_types) == expected


def test_source_tier_order_is_stable():
    """Order matters for cluster merging — guard against accidental reorder.

    full-audit Wave 2 inserted the smart-levels tech_* tiers BETWEEN swing and
    yt (design §2.2), preserving the relative order of the pre-existing types.
    """
    assert SOURCE_TIER_ORDER == (
        "yt_curated", "swing",
        "tech_sr", "tech_vp", "tech_vpoc", "tech_zone", "tech_fib",
        "yt", "web",
    )
    # the pre-existing types keep their relative order (the real invariant)
    o = SOURCE_TIER_ORDER
    assert o.index("yt_curated") < o.index("swing") < o.index("yt") < o.index("web")


# ---------------------------------------------------------------------------
# cluster_anchors with mixed tiers (CEF-3 fix)
# ---------------------------------------------------------------------------

def test_cluster_anchors_max_tier_when_mixed():
    """Mixed web + yt_curated cluster yields source_type='yt_curated' (not 'web')."""
    a_web = Anchor(price=100.0, source="web:reuters", source_type="web", touches=1)
    a_curated = Anchor(price=100.2, source="youtube:Stockwatch", source_type="yt_curated",
                       trust_score=1.0, touches=1)
    merged = cluster_anchors([a_web, a_curated], threshold_pct=0.005)
    assert len(merged) == 1
    assert merged[0].source_type == "yt_curated"


def test_cluster_anchors_retains_cluster_source_types_set():
    """The merged anchor exposes the full tier set as a frozenset-like attr."""
    a_web = Anchor(price=100.0, source="web:reuters", source_type="web")
    a_yt = Anchor(price=100.2, source="youtube:Lottery", source_type="yt")
    a_curated = Anchor(price=100.3, source="youtube:Stockwatch", source_type="yt_curated")
    merged = cluster_anchors([a_web, a_yt, a_curated], threshold_pct=0.005)
    assert len(merged) == 1
    assert merged[0].cluster_source_types == {"web", "yt", "yt_curated"}


def test_cluster_anchors_singleton_gets_singleton_tier_set():
    """A non-merged anchor still gets cluster_source_types populated with its own type."""
    a = Anchor(price=100.0, source="web:r", source_type="web")
    merged = cluster_anchors([a], threshold_pct=0.005)
    assert merged[0].cluster_source_types == {"web"}


def test_cluster_anchors_first_arrival_no_longer_wins():
    """Regression for CEF-3: web sorted before yt_curated by price → previously
    cluster[0].source_type would be 'web'. Now max_tier wins."""
    a_web = Anchor(price=99.9, source="web:r", source_type="web", touches=1)
    a_curated = Anchor(price=100.0, source="youtube:Stockwatch", source_type="yt_curated",
                       touches=1)
    merged = cluster_anchors([a_web, a_curated], threshold_pct=0.005)
    assert len(merged) == 1, "should merge — 0.1% gap"
    assert merged[0].source_type == "yt_curated"


def test_cluster_anchors_picks_max_trust_score():
    """Merged anchor inherits the highest trust score from its contributors."""
    a_low = Anchor(price=100.0, source="x", source_type="yt", trust_score=0.5)
    a_high = Anchor(price=100.2, source="y", source_type="yt_curated", trust_score=0.9)
    merged = cluster_anchors([a_low, a_high], threshold_pct=0.005)
    assert merged[0].trust_score == 0.9


def test_cluster_anchors_picks_channel_id_matching_winning_tier():
    """Merged channel_id should reflect the channel that won the tier vote."""
    a_yt = Anchor(price=100.0, source="x", source_type="yt", channel_id="UC_low")
    a_curated = Anchor(price=100.2, source="y", source_type="yt_curated",
                       trust_score=1.0, channel_id="UC_high")
    merged = cluster_anchors([a_yt, a_curated], threshold_pct=0.005)
    assert merged[0].channel_id == "UC_high"


# ---------------------------------------------------------------------------
# extract_anchors_from_youtube_levels — trust-driven tiering
# ---------------------------------------------------------------------------

def test_extract_anchors_curated_when_trust_high_and_approved():
    rows = [{
        "price": 100.0,
        "channel_name": "Stockwatch",
        "channel_id": "UC_high",
        "trust_score": 0.9,
        "approved": 1,
    }]
    anchors = extract_anchors_from_youtube_levels(rows)
    assert len(anchors) == 1
    assert anchors[0].source_type == "yt_curated"
    assert anchors[0].channel_id == "UC_high"
    assert anchors[0].trust_score == 0.9


def test_extract_anchors_yt_when_trust_below_threshold():
    rows = [{
        "price": 100.0,
        "channel_name": "Probationary",
        "channel_id": "UC_low",
        "trust_score": 0.4,
        "approved": 1,
    }]
    anchors = extract_anchors_from_youtube_levels(rows)
    assert anchors[0].source_type == "yt"


def test_extract_anchors_yt_when_not_approved_even_with_high_trust():
    rows = [{
        "price": 100.0,
        "channel_name": "Unapproved",
        "channel_id": "UC_x",
        "trust_score": 0.95,
        "approved": 0,
    }]
    anchors = extract_anchors_from_youtube_levels(rows)
    assert anchors[0].source_type == "yt"


def test_channel_trust_miss_defaults_yt_not_web():
    """CEF-1 amendment: missing channel/trust defaults to yt tier (mult 0.5), NOT web (0.2).
    Preserves backward compat for legacy rows + new channels added since last seed."""
    rows = [{
        "price": 100.0,
        "channel_name": "Unregistered",
        # no channel_id, no trust_score, no approved → LEFT JOIN miss
    }]
    anchors = extract_anchors_from_youtube_levels(rows)
    assert anchors[0].source_type == "yt"
    assert anchors[0].trust_score == 0.5  # bootstrap default
    assert anchors[0].channel_id is None


def test_anchor_dataclass_has_new_provenance_fields():
    """W2 schema additions: channel_id, distance_pct, trust_score, cluster_source_types."""
    a = Anchor(price=100.0, source="x", source_type="yt")
    assert hasattr(a, "channel_id")
    assert hasattr(a, "trust_score")
    assert hasattr(a, "distance_pct")
    assert hasattr(a, "cluster_source_types")
    # Defaults must be None so we can distinguish "unknown" from "explicitly set".
    assert a.channel_id is None
    assert a.trust_score is None
    assert a.distance_pct is None
    assert a.cluster_source_types is None
