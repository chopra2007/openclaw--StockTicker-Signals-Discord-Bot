"""#22 (full-audit-2026-06-06) — data-sparseness banner.

When `all_command.sparse_banner.enabled` is ON and the number of surfaced
sources is <= max_sources (default 3), `build_embed` prepends a one-line
low-coverage caveat to the embed description. Default OFF → no banner.

Asserts:
  * flag OFF (default) → no banner regardless of source count (byte-identical)
  * flag ON, N <= 3 → banner present in description
  * flag ON, N = 12 → no banner
"""
from __future__ import annotations

from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.models import ScoreBreakdown
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import embed


_BANNER_FRAGMENT = "Low coverage"


def _flag_cfg(enabled: bool, max_sources: int = 3):
    """Override only the sparse_banner keys; pass-through everything else."""
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.sparse_banner.enabled":
            return enabled
        if key == "all_command.sparse_banner.max_sources":
            return max_sources
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


def _build(n_sources: int):
    sf = StructuredFields(
        direction="BULLISH", confidence_label="LOW",
        sl=90.0, tp1=124.0, current_price=100.0,
    )
    bd = ScoreBreakdown(news_catalyst=15, technical=4, llm_boost=9, youtube=15)
    sources = [f"src{i}" for i in range(n_sources)]
    return embed.build_embed(
        ticker="NVDA", structured=sf, score_breakdown=bd,
        narrative="**TL;DR:** test.\n## Trade Plan\n| x |",
        sources_used=sources, cache_age_seconds=None,
    )


def test_flag_off_no_banner_when_sparse():
    """Default-OFF: even 1 source → no banner."""
    with _flag_cfg(False):
        emb = _build(1)
    assert _BANNER_FRAGMENT not in emb.get("description", "")


def test_flag_off_byte_identical():
    """Flag OFF: a sparse run and a rich run differ only by the sources line,
    never by a banner. Confirm neither carries the banner string."""
    with _flag_cfg(False):
        sparse = _build(1)
        rich = _build(12)
    assert _BANNER_FRAGMENT not in sparse.get("description", "")
    assert _BANNER_FRAGMENT not in rich.get("description", "")


def test_flag_on_banner_present_at_n_le_3():
    """Flag ON, 3 surfaced sources (== max) → banner present with the count."""
    with _flag_cfg(True):
        emb = _build(3)
    desc = emb.get("description", "")
    assert _BANNER_FRAGMENT in desc
    assert "only 3 sources" in desc


def test_flag_on_banner_present_at_n_1():
    with _flag_cfg(True):
        emb = _build(1)
    assert "only 1 sources" in emb.get("description", "")


def test_flag_on_banner_absent_at_n_12():
    """Flag ON but 12 surfaced sources (> max) → no banner."""
    with _flag_cfg(True):
        emb = _build(12)
    assert _BANNER_FRAGMENT not in emb.get("description", "")


def test_flag_on_respects_custom_max_sources():
    """Custom max_sources=5: N=5 → banner, N=6 → none."""
    with _flag_cfg(True, max_sources=5):
        at_max = _build(5)
        above = _build(6)
    assert _BANNER_FRAGMENT in at_max.get("description", "")
    assert _BANNER_FRAGMENT not in above.get("description", "")
