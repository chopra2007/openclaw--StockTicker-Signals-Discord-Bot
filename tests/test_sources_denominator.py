"""T1-a (#76 menu) — "Sources: N of M attempted" footer denominator.

The !all footer printed a bare `Sources: 4`, which can't distinguish 4 sources
agreeing out of 5 that looked from 4 out of 27. With
`features.sources_denominator.enabled` ON the footer reads
`Sources: 4 of 27 attempted`; OFF it is byte-identical to the old string.

Asserts:
  * flag OFF (default) → footer is the exact old `Sources: N` (byte-identical)
  * flag ON  → `Sources: N of M attempted`
  * flag ON but no denominator passed → falls back to the bare count
  * M is the aggregator's real classify-list length, never a hard-coded literal
"""
from __future__ import annotations

from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.models import ScoreBreakdown
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import embed


def _flag_cfg(enabled: bool):
    """Override only the sources_denominator key; pass-through everything else."""
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "features.sources_denominator.enabled":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


def _footer(n_sources: int, sources_total=None) -> str:
    sf = StructuredFields(
        direction="BULLISH", confidence_label="LOW",
        sl=90.0, tp1=124.0, current_price=100.0,
    )
    bd = ScoreBreakdown(news_catalyst=15, technical=4, llm_boost=9, youtube=15)
    emb = embed.build_embed(
        ticker="NVDA", structured=sf, score_breakdown=bd,
        narrative="**TL;DR:** test.\n## Trade Plan\n| x |",
        sources_used=[f"src{i}" for i in range(n_sources)],
        cache_age_seconds=None,
        sources_total=sources_total,
    )
    return emb["footer"]["text"]


def test_flag_off_is_byte_identical():
    """Default-OFF: the old bare count, even when a denominator is available."""
    with _flag_cfg(False):
        assert _footer(4, sources_total=27) == "Sources: 4"


def test_flag_on_shows_denominator():
    with _flag_cfg(True):
        assert _footer(4, sources_total=27) == "Sources: 4 of 27 attempted"


def test_flag_on_without_denominator_falls_back():
    """A caller that never passes sources_total keeps the old footer."""
    with _flag_cfg(True):
        assert _footer(4) == "Sources: 4"


def test_denominator_is_the_real_classify_list_length():
    """M must be derived from the aggregator's source list, not a literal.

    Guards the failure mode where someone hard-codes 27 and the footer then
    lies the day a source is added or removed.
    """
    import inspect
    from consensus_engine.alerts.all_command import aggregator

    src = inspect.getsource(aggregator._gather_all_sources)
    assert '"sources_total": len(_classify_items)' in src
