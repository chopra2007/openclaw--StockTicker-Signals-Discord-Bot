"""Positive render test — drives the REAL build_embed with all three
all-quality-and-yt-score levers populated and asserts they appear:
  #19 yt= footer term, A2 Snapshot field, A3 R:R field.
"""
from consensus_engine.models import ScoreBreakdown
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import embed


def _build():
    sf = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=90.0, tp1=124.0, current_price=100.0,
        risk_reward=2.4,
        snapshot={"target_mean": 215.0, "target_high": 260.0, "target_low": 180.0,
                  "n_analysts": 58, "rating": "Strong Buy", "fwd_pe": 31.0,
                  "short_pct": 0.0092, "short_days": 3.11},
    )
    bd = ScoreBreakdown(news_catalyst=15, technical=4, llm_boost=9, youtube=15)
    return embed.build_embed(
        ticker="NVDA", structured=sf, score_breakdown=bd,
        narrative="**TL;DR:** test. **What could go wrong:** x. **Risks & mitigants:** y -> z.",
        sources_used=["news", "technical"], cache_age_seconds=None,
    )


def test_yt_term_in_footer():
    emb = _build()
    desc = emb.get("description", "")
    assert "yt=15" in desc, f"yt= missing from score line: {desc!r}"
    assert "llm=9" in desc  # llm is the LLM-only contribution, not 9+15


def test_rr_field_rendered():
    fields = _build().get("fields", [])
    rr = [f for f in fields if f.get("name") == "R:R"]
    assert rr, "R:R field not rendered"
    assert rr[0]["value"] == "1:2.4"


def test_snapshot_field_rendered():
    fields = _build().get("fields", [])
    snap = [f for f in fields if f.get("name") == "📊 Snapshot"]
    assert snap, "Snapshot field not rendered"
    assert "🎯 $215 avg" in snap[0]["value"]
    assert "Strong Buy" in snap[0]["value"]
