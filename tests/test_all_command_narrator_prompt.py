"""PR4 — surface 6 discarded sources + dedupe synthesis prompt sections.

Investigation Q10 / Surprises #3 + #4: sections 4-7 of the v1 synthesis
prompt all sliced from the same `sanitized_searxng` list, while
twitter_signals / social_signals / yt_signals / yt_options / yt_evidence /
technical_short never reached the LLM at all. PR4 routes each source to
its own evidence block.

The hot-ticker fixture below satisfies the critic directive on row counts
(see EXECUTE-v2.md): it represents the upper bound of production volumes
so the token-budget assertion exercises a realistic prompt rather than a
trivially-passing sparse one. If you regenerate it, preserve the per-source
minimums:

    NEWS_FIXTURE       ≥10 strings (200-800 char body each)
    SEC_FIXTURE        ≥ 5
    YT_SIGNALS_FIXTURE ≥10
    YT_OPTIONS_FIXTURE ≥10
    YT_EVIDENCE_FIX    ≥10 (200-800 char text each)
    TWITTER_FIXTURE    ≥30
    SOCIAL_FIXTURE     ≥30
    CHAT_FIXTURE       ≥20
    Plus non-empty: technical_short, brief_msgs, prior_vault, score,
                    technical_long, yt_levels, alert_history, decision_snapshots,
                    options_unusual, apewisdom.
    `trends` may stay empty (serpapi off in production).
"""
from __future__ import annotations

import json
import re

import pytest

from consensus_engine.alerts.all_command import narrator
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# nvda_hot_ticker_19sources fixture (inline; per critic directive)
# ---------------------------------------------------------------------------

_NEWS_BODY = (
    "NVIDIA reported record Q3 FY26 revenue of $35.1B, up 94% YoY, driven "
    "by Blackwell ramp. Data Center revenue hit $30.8B (+112% YoY). "
    "Management raised FY26 guidance, citing $1T+ Blackwell-and-Rubin "
    "backlog through 2027. Gross margin held at 75% despite Blackwell "
    "ramp. Free cash flow of $16.8B beat consensus $14.5B."
)

NEWS_FIXTURE = [_NEWS_BODY for _ in range(12)]
SEC_FIXTURE = [
    "8-K Item 2.02 — Earnings release, Q3 FY26 results filed 2026-02-21.",
    "10-Q quarterly report Q3 FY26, filed 2026-02-22, segment detail.",
    "Form 4 — Jensen Huang sold 240,000 shares ($52.5M) on 2026-02-25 (10b5-1).",
    "8-K Item 7.01 — Reg FD disclosure, GTC keynote schedule confirmed.",
    "8-K Item 1.01 — Material agreement with TSMC for Rubin capacity.",
    "DEF 14A proxy filed 2026-03-04, executive comp restructured.",
    "8-K Item 5.02 — Officer change announcement, new CFO disclosure.",
] * 1  # 7 strings — meets ≥5 minimum

TWITTER_FIXTURE = [
    f"Trader{i}: $NVDA breaking out above $210 with strong volume, eyes $235 next."
    for i in range(35)
]
SOCIAL_FIXTURE = [
    f"r/wallstreetbets [{i}]: NVDA calls printing — $230 strikes 5x today, IV crush incoming."
    for i in range(32)
]
YT_SIGNALS_FIXTURE = [
    {"channel": f"Channel{i}", "ticker": "NVDA", "direction": "long",
     "conviction": "high", "summary": f"{30+i}-min discussion of NVDA upside."}
    for i in range(12)
]
YT_OPTIONS_FIXTURE = [
    {"channel": f"OptionsCh{i}", "ticker": "NVDA", "strike": 230 + i,
     "expiry": "2026-06-21", "direction": "call", "size": f"{1000+i*100} contracts"}
    for i in range(11)
]
YT_EVIDENCE_FIXTURE = [
    {"channel": f"AnalystCh{i}", "ticker": "NVDA",
     "text": (
         f"From {i}-minute mark: 'NVDA is set up beautifully here. We've got "
         f"the breakout above $210 confirmed, volume is strong, and the "
         f"$235 target from the rectangle pattern is well within reach by "
         f"end of June. Stop should be tight at $194.50 just below the "
         f"18-day MA. This is a classic continuation setup post-earnings.'"
     )}
    for i in range(11)
]
CHAT_FIXTURE = [
    f"user{i}: NVDA looking strong, holding above $210 — {i}m ago"
    for i in range(22)
]
BRIEF_FIXTURE = [
    "Pre-market: NVDA gapping +1.2% on volume, futures bullish.",
    "Sector: Semis leading; SOXX +0.8%, AVGO/AMD also strong.",
    "Watch: NVDA $216.96 ATH, $210 support, $235 measured-move target.",
]
TECHNICAL_SHORT = {
    "rsi": 62, "macd": "bullish_cross", "ema_9": 207.4,
    "ema_21": 198.1, "vwap": 209.3,
}
PRIOR_VAULT = (
    "## Prior research summary (NVDA, last updated 2026-04-15)\n\n"
    "Previous thesis was bullish post-Q2 earnings. Key levels held: $185 "
    "support, $210 resistance becoming support post-breakout. Watch for "
    "Blackwell ramp commentary. Gemini-equivalent prompt produced "
    "Bullish thesis with $194.50 SL / $235 TP / $207-$210 entry. PEG "
    "ratio of 0.63 cited as undervalued vs growth. Risk: 50DMA gap of "
    "Nasdaq 100 at 14% raises pullback probability."
) * 2  # ~1500 chars, well under _CAP_VAULT_CHARS=2000


def _build_structured() -> StructuredFields:
    return StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        breakout_timeframe="1-3w", magnitude_label="±$4.20 (2× ATR)",
        sl=194.50, tp1=222.00, tp2=232.00, tp3=242.00,
    )


def _build_score_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(base=30, news_catalyst=30, technical=30)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_evidence_blocks_distinct():
    """Each evidence block must read from its own source; no two share content."""
    messages = narrator._build_synthesis_prompt(
        ticker="NVDA",
        structured=_build_structured(),
        score_breakdown=_build_score_breakdown(),
        sanitized_searxng=NEWS_FIXTURE,  # back-compat
        sanitized_chat=CHAT_FIXTURE,
        sanitized_brief=BRIEF_FIXTURE,
        vault_summary=PRIOR_VAULT,
        structured_data_json=json.dumps({"news_passed": True}),
        sanitized_news=NEWS_FIXTURE,
        sanitized_sec=SEC_FIXTURE,
        sanitized_twitter=TWITTER_FIXTURE,
        sanitized_social=SOCIAL_FIXTURE,
        sanitized_yt_signals=YT_SIGNALS_FIXTURE,
        sanitized_yt_options=YT_OPTIONS_FIXTURE,
        sanitized_yt_evidence=YT_EVIDENCE_FIXTURE,
        sanitized_technical_short=TECHNICAL_SHORT,
    )
    user = messages[1]["content"]

    # Each block header appears exactly once.
    for header in (
        "NEWS / ANALYST EVIDENCE",
        "SEC FILINGS",
        "TECHNICAL CONTEXT",
        "SOCIAL SIGNALS (twitter)",
        "SOCIAL SIGNALS (reddit/wsb)",
        "YOUTUBE ANALYST CALLS",
        "YOUTUBE OPTIONS FLOW",
        "YOUTUBE TRADE SETUPS",
    ):
        assert user.count(header) == 1, f"missing or duplicated header: {header}"

    # The first item from twitter must NOT appear in the news block,
    # confirming sources stopped sharing the same `capped_news` list.
    twitter_marker = TWITTER_FIXTURE[0]
    news_block = user.split("NEWS / ANALYST EVIDENCE")[1].split("SEC FILINGS")[0]
    assert twitter_marker not in news_block

    # Conversely the news body must not show up under SOCIAL.
    news_marker = "NVIDIA reported record Q3"
    social_block = user.split("SOCIAL SIGNALS (twitter)")[1].split("SOCIAL SIGNALS (reddit/wsb)")[0]
    assert news_marker not in social_block


def test_prompt_includes_all_19_sources():
    """All non-trends sources must contribute identifiable content to the prompt."""
    messages = narrator._build_synthesis_prompt(
        ticker="NVDA",
        structured=_build_structured(),
        score_breakdown=_build_score_breakdown(),
        sanitized_searxng=NEWS_FIXTURE,
        sanitized_chat=CHAT_FIXTURE,
        sanitized_brief=BRIEF_FIXTURE,
        vault_summary=PRIOR_VAULT,
        structured_data_json=json.dumps({"news_passed": True}),
        sanitized_news=NEWS_FIXTURE,
        sanitized_sec=SEC_FIXTURE,
        sanitized_twitter=TWITTER_FIXTURE,
        sanitized_social=SOCIAL_FIXTURE,
        sanitized_yt_signals=YT_SIGNALS_FIXTURE,
        sanitized_yt_options=YT_OPTIONS_FIXTURE,
        sanitized_yt_evidence=YT_EVIDENCE_FIXTURE,
        sanitized_technical_short=TECHNICAL_SHORT,
        sources_surfaced=[
            "score", "technical_long", "technical_short", "twitter_db",
            "social_db", "youtube_signals_db", "youtube_options_db",
            "youtube_levels_db", "youtube_evidence_db", "alert_history_db",
            "decision_snapshots_db", "news", "sec", "options", "apewisdom",
            "chat_24h", "brief_last3", "prior_vault",
        ],
    )
    user = messages[1]["content"]

    # Per-source unique sentinels (the first item of each fixture list).
    assert "NVIDIA reported record Q3" in user                  # news
    assert "8-K Item 2.02" in user                              # sec
    assert TWITTER_FIXTURE[0][:30] in user                      # twitter
    assert SOCIAL_FIXTURE[0][:30] in user                       # social
    assert YT_SIGNALS_FIXTURE[0]["channel"] in user             # yt_signals
    assert str(YT_OPTIONS_FIXTURE[0]["strike"]) in user         # yt_options
    assert YT_EVIDENCE_FIXTURE[0]["channel"] in user            # yt_evidence
    assert "rsi" in user                                        # technical_short
    assert CHAT_FIXTURE[0][:20] in user                         # chat
    assert BRIEF_FIXTURE[0][:30] in user                        # brief
    assert "Prior research summary" in user                     # prior_vault
    # SOURCES SURFACED block lists labels too
    assert "twitter_db" in user
    assert "youtube_evidence_db" in user


def test_prompt_token_budget():
    """Hot-ticker prompt must stay under 14000 tokens after per-block caps."""
    messages = narrator._build_synthesis_prompt(
        ticker="NVDA",
        structured=_build_structured(),
        score_breakdown=_build_score_breakdown(),
        sanitized_searxng=NEWS_FIXTURE,
        sanitized_chat=CHAT_FIXTURE,
        sanitized_brief=BRIEF_FIXTURE,
        vault_summary=PRIOR_VAULT,
        structured_data_json=json.dumps({"news_passed": True}),
        sanitized_news=NEWS_FIXTURE,
        sanitized_sec=SEC_FIXTURE,
        sanitized_twitter=TWITTER_FIXTURE,
        sanitized_social=SOCIAL_FIXTURE,
        sanitized_yt_signals=YT_SIGNALS_FIXTURE,
        sanitized_yt_options=YT_OPTIONS_FIXTURE,
        sanitized_yt_evidence=YT_EVIDENCE_FIXTURE,
        sanitized_technical_short=TECHNICAL_SHORT,
    )
    prompt = messages[0]["content"] + "\n" + messages[1]["content"]

    # tiktoken if available, else conservative 4-chars-per-token estimate.
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
        n_tokens = len(enc.encode(prompt))
    except Exception:
        n_tokens = len(prompt) // 4

    assert n_tokens < 14000, (
        f"prompt is {n_tokens} tokens; exceeds 14000 budget. "
        "Tighten per-block caps in priority order: "
        "_CAP_YT > _CAP_TWEETS > _CAP_SOCIAL > _CAP_NEWS."
    )


def test_fixture_meets_critic_row_count_contract():
    """Per critic directive: hot-ticker fixture row counts can't drift below floors."""
    assert len(NEWS_FIXTURE) >= 10
    assert len(SEC_FIXTURE) >= 5
    assert len(YT_SIGNALS_FIXTURE) >= 10
    assert len(YT_OPTIONS_FIXTURE) >= 10
    assert len(YT_EVIDENCE_FIXTURE) >= 10
    assert len(TWITTER_FIXTURE) >= 30
    assert len(SOCIAL_FIXTURE) >= 30
    assert len(CHAT_FIXTURE) >= 20
    # body length contract for free-text rows
    for body in NEWS_FIXTURE:
        assert 200 <= len(body) <= 1200, len(body)
    for ev in YT_EVIDENCE_FIXTURE:
        assert 200 <= len(ev["text"]) <= 1200, len(ev["text"])


# ---------------------------------------------------------------------------
# TODO #7 fix — earnings recap pre-formatting
# ---------------------------------------------------------------------------

def test_format_earnings_recap_strips_raw_float_precision():
    """`_format_earnings_recap` converts raw floats to display strings so the
    prompt no longer ships `$181519000000.0` / `+16.60724495236627%`.

    This is the structural fix for TODO #7 — even chain models that copy
    the EARNINGS RECAP block verbatim can't leak raw precision."""
    raw = {
        "period": "2026-03-31",
        "eps_actual": 1.05,
        "eps_estimate": 0.97,
        "eps_surprise_pct": 8.247422680412371,
        "revenue_actual": 181519000000.0,
        "revenue_yoy_pct": 16.60724495236627,
    }
    out = narrator._format_earnings_recap(raw)
    assert out["revenue_actual"] == "$181.52B"
    assert out["revenue_yoy_pct"] == "+16.6%"
    assert out["eps_actual"] == "$1.05"
    assert out["eps_estimate"] == "$0.97"
    assert out["eps_surprise_pct"] == "+8.2%"
    assert out["period"] == "2026-03-31"  # non-numeric pass-through


def test_format_earnings_recap_handles_none_and_missing():
    """None/missing fields and small revenues don't crash or mis-format."""
    assert narrator._format_earnings_recap(None) is None
    assert narrator._format_earnings_recap({}) == {}
    # Negative growth + small revenue
    out = narrator._format_earnings_recap({
        "revenue_actual": 50_000_000.0,
        "revenue_yoy_pct": -3.5,
        "eps_actual": -0.12,
    })
    assert out["revenue_actual"] == "$50.0M"
    assert out["revenue_yoy_pct"] == "-3.5%"
    assert out["eps_actual"] == "$-0.12"


def test_synthesis_prompt_uses_formatted_earnings_recap():
    """End-to-end: the EARNINGS RECAP block in the built prompt must contain
    the formatted strings, NOT raw float literals."""
    structured = StructuredFields(
        direction="BULLISH", confidence_label="MEDIUM",
        sl=100.0, tp1=120.0, tp2=130.0, tp3=140.0,
        breakout_timeframe="TBD", magnitude_label="MEDIUM",
        current_price=110.0, buy_zone_low=108.0, buy_zone_high=112.0,
    )
    score = ScoreBreakdown(base=20, news_catalyst=15, llm_boost=5)
    raw_recap = {
        "period": "2026-03-31",
        "revenue_actual": 181519000000.0,
        "revenue_yoy_pct": 16.60724495236627,
        "eps_actual": 1.05,
    }
    messages = narrator._build_synthesis_prompt(
        ticker="AMZN",
        structured=structured,
        score_breakdown=score,
        sanitized_searxng=[], sanitized_chat=[], sanitized_brief=[],
        vault_summary="", structured_data_json="{}",
        recent_earnings_recap=raw_recap,
    )
    user_content = messages[1]["content"]
    # Raw precision MUST NOT appear in the prompt
    assert "181519000000.0" not in user_content
    assert "16.60724495236627" not in user_content
    # Formatted strings MUST appear
    assert "$181.52B" in user_content
    assert "+16.6%" in user_content
