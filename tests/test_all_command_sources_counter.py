"""PR2 — fix the inverted `sources_used` counter.

v1: `source_status` was populated only on exception (aggregator.py:209-233),
then the embed footer said `sources: {len(source_status)}`. A clean run
showed `sources: 0` because zero sources errored — the counter was actually
counting failures. Investigation Q2 / Surprise #1.

v2 splits the concept in two:
  - `source_failures: list[str]`   — labels of sources that errored
  - `sources_surfaced: list[str]`  — labels of sources that returned data

The footer reads `len(sources_surfaced)`; the LLM prompt gets the surfaced
list verbatim so it can name the contributing sources in narrative.
"""
from __future__ import annotations

from consensus_engine.alerts.all_command import aggregator, embed as embed_mod
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


# Reproduce the production gather output for 19 sources. Trends is empty
# because production runs with serpapi_enabled=false.
_NON_EMPTY_19 = [
    ("score", object()),
    ("technical_long", object()),
    ("technical_short", object()),
    ("twitter_db", [{"id": 1}]),
    ("social_db", [{"id": 1}]),
    ("youtube_signals_db", [{"id": 1}]),
    ("youtube_options_db", [{"id": 1}]),
    ("youtube_levels_db", [{"id": 1}]),
    ("youtube_evidence_db", [{"id": 1}]),
    ("alert_history_db", [{"id": 1}]),
    ("decision_snapshots_db", [{"id": 1}]),
    ("news", {"catalyst_body": "x"}),
    ("sec", [{"item": "1.01"}]),
    ("options", {"unusual": True}),
    ("trends", {}),  # production is always empty
    ("apewisdom", {"score": 1}),
    ("chat_24h", [{"content": "x"}]),
    ("brief_last3", [{"content": "x"}]),
    ("prior_vault", "## prior research"),
]


def test_clean_run_reports_nonzero_sources():
    """All 19 sources non-empty (except the trends dict) → ≥15 surfaced."""
    surfaced, failures = aggregator._classify_sources(_NON_EMPTY_19)
    assert len(surfaced) >= 15, (
        f"surfaced={surfaced!r}; expected ≥15 of 19 (trends empty in prod)"
    )
    assert failures == []


def test_failed_sources_not_in_surfaced():
    """Sources that raised must appear in failures, not in surfaced."""
    items = list(_NON_EMPTY_19)
    items[3] = ("twitter_db", RuntimeError("boom"))
    items[5] = ("youtube_signals_db", TimeoutError("slow"))
    items[11] = ("news", ValueError("bad json"))

    surfaced, failures = aggregator._classify_sources(items)
    failure_labels = [f.split(":")[0] for f in failures]

    assert "twitter_db" in failure_labels
    assert "youtube_signals_db" in failure_labels
    assert "news" in failure_labels
    assert "twitter_db" not in surfaced
    assert "youtube_signals_db" not in surfaced
    assert "news" not in surfaced


def test_empty_value_not_in_surfaced():
    """An empty list/dict/string is gathered-but-empty — not surfaced."""
    items = [
        ("twitter_db", []),
        ("social_db", {}),
        ("prior_vault", ""),
        ("apewisdom", None),
    ]
    surfaced, failures = aggregator._classify_sources(items)
    assert surfaced == []
    assert failures == []  # None is not an exception, just absence


def _make_structured(direction: str = "BULLISH") -> StructuredFields:
    return StructuredFields(
        direction=direction,
        confidence_label="HIGH",
        breakout_timeframe="1-3d",
        magnitude_label="±$3.00 (1.5× ATR)",
        sl=95.0,
        tp1=105.0,
        tp2=110.0,
        tp3=115.0,
    )


def test_footer_shows_surfaced_count():
    """Embed footer reads len(sources) — must reflect surfaced, not failures."""
    out = embed_mod.build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(base=30, news_catalyst=30, technical=30),
        narrative="Bullish thesis...",
        sources_used=["news", "sec", "twitter_db"],
        cache_age_seconds=None,
    )
    assert "sources: 3" in out["footer"]["text"], out["footer"]["text"]


def test_footer_zero_when_nothing_surfaced():
    """Empty sources list → footer says sources: 0 (true zero, not inverted)."""
    out = embed_mod.build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(base=30, news_catalyst=30, technical=30),
        narrative="...",
        sources_used=[],
        cache_age_seconds=None,
    )
    assert "sources: 0" in out["footer"]["text"]
