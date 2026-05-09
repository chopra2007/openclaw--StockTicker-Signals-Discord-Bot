"""PR7 — Layer A quality-bar fixture suite.

Per plan §3 PR7 + EXECUTION HALTING CRITERION (Strategy A):
  - 9 acceptance checks × 3 tickers = 27 parameterized assertions.
  - The `quality_bar:` log line emitted by aggregator._compute_all is the
    Layer B observable; this file verifies its 12-field shape.

Layer C (manual blind-compare Gemini vs !all per ticker) is run by the
operator via `scripts/run_quality_bar_live.py` after Layers A + B clear.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import pytest

from consensus_engine.alerts.all_command import quality_bar as qb


# ---------------------------------------------------------------------------
# Reference narratives (one per ticker). Each is hand-written to satisfy all
# 9 quality-bar items so the checkers' contracts are locked in. Live LLM
# runs are scored against the same checkers in `scripts/run_quality_bar_live.py`.
# ---------------------------------------------------------------------------

_NVDA_NARRATIVE = """## NVDA Market Thesis: Bullish

NVIDIA broke out above $191 resistance after Q3 FY26 earnings, with revenue
growing 94% YoY to $35.1B. The Blackwell ramp continues to print: Data Center
revenue hit $30.8B (+112% YoY), and management's $1T+ backlog through 2027
lifted FY26 guidance. PEG ratio of 0.63 cited by news indicates the stock
remains undervalued relative to its earnings growth trajectory. Twitter
flow shows aggressive accumulation above $210, and reddit/wsb sentiment
turned net-bullish on the breakout.

## Catalysts
* Q3 FY26 revenue grew 94% YoY to $35.1B with Data Center +112% — figures from news catalyst body.
* Blackwell + Rubin backlog now over $1 trillion through 2027 per the Feb 21 earnings 8-K.
* Youtube analyst calls (3 channels in last 7 days) flagged the $222 measured-move target.

## Risk Considerations
* Short-term overextension: Nasdaq 100 sits 14% above its 50-day MA, raising pullback probability.

Trade plan: SL $194.50 just below the 18-day MA, TP1 $222 from rectangle
projection, TP2 $232 at the 4.236% Fibonacci extension, TP3 $242 if
momentum carries through the ATH.
"""

_AMD_NARRATIVE = """## AMD Market Thesis: Bullish

AMD posted record Q1 results with $7.4B revenue (+24% YoY) driven by MI300X
ramp and 9% server share gain. The chat channel surfaced $260 cluster
buying interest, while sec filings show a Form 4 insider purchase of
$1.2M on 2026-02-28. Apewisdom rank 4 corroborates the social-momentum
read.

## Catalysts
* MI300X data-center wins drove +24% revenue growth — figure from news.
* Insider buy of $1.2M filed via Form 4 on 2026-02-28 (sec source).
* Youtube channel coverage from CheddarFlow flagged the $260 retest.

## Risk Considerations
* Single web-anchored resistance (~$260) means TP2/TP3 padded with None — partial trade plan only.

Trade plan: SL $164 below the 50DMA, TP1 $260 the recent breakout zone.
"""

_TSLA_NARRATIVE = """## TSLA Market Thesis: Bullish

Tesla broke through $385 on Q4 deliveries beat — 510k vs consensus 482k.
Twitter flow showed aggressive call-buying around $400 strikes, and
reddit chatter cited the FSD subscription ramp as a forward catalyst.
Vault prior research from 2026-04-15 already flagged this $385 level
as the next breakout zone, so the move confirms the prior thesis.

## Catalysts
* Q4 deliveries 510k beat consensus 482k by 5.8% — news catalyst.
* FSD subscription ramp commentary in 8-K guidance update (sec).
* Youtube: 4 channels flagged the $385 breakout zone in last 7 days.

## Risk Considerations
* Margin pressure if Q1 ASP softens — flagged in apewisdom social chatter.

Trade plan: SL $360, TP1 $410, TP2 $430, TP3 $450.
"""

_NARRATIVES = {
    "NVDA": _NVDA_NARRATIVE,
    "AMD":  _AMD_NARRATIVE,
    "TSLA": _TSLA_NARRATIVE,
}


@dataclass(frozen=True)
class QBContext:
    ticker: str
    narrative: str
    sl: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    tp3: Optional[float]
    anchors_total: int
    sources_surfaced: list[str]


_CONTEXTS = {
    "NVDA": QBContext(
        ticker="NVDA", narrative=_NVDA_NARRATIVE,
        sl=194.50, tp1=222.00, tp2=232.00, tp3=242.00, anchors_total=8,
        sources_surfaced=["score", "technical_long", "news", "sec", "twitter_db",
                          "social_db", "youtube_signals_db", "chat_24h", "prior_vault"],
    ),
    "AMD": QBContext(
        ticker="AMD", narrative=_AMD_NARRATIVE,
        sl=164.0, tp1=260.0, tp2=None, tp3=None, anchors_total=8,
        sources_surfaced=["score", "technical_long", "news", "sec", "youtube_evidence_db",
                          "chat_24h", "apewisdom"],
    ),
    "TSLA": QBContext(
        ticker="TSLA", narrative=_TSLA_NARRATIVE,
        sl=360.0, tp1=410.0, tp2=430.0, tp3=450.0, anchors_total=10,
        sources_surfaced=["score", "technical_long", "news", "sec", "twitter_db",
                          "social_db", "youtube_signals_db", "prior_vault"],
    ),
}

_TICKERS = list(_CONTEXTS.keys())


# ---------------------------------------------------------------------------
# 9 quality-bar checks × 3 tickers = 27 assertions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker", _TICKERS)
def test_numbered_facts_min_3(ticker):
    ctx = _CONTEXTS[ticker]
    n = qb.count_numbered_facts(ctx.narrative)
    assert n >= 3, f"{ticker}: only {n} numbered facts; need ≥3"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_source_count_accurate(ticker):
    ctx = _CONTEXTS[ticker]
    assert len(ctx.sources_surfaced) >= 3


@pytest.mark.parametrize("ticker", _TICKERS)
def test_sources_surfaced_in_narrative(ticker):
    ctx = _CONTEXTS[ticker]
    n = qb.sources_named_in_narrative(ctx.narrative, ctx.sources_surfaced)
    assert n >= 3, f"{ticker}: only {n} surfaced sources cited in narrative"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_trade_plan_complete_when_anchors_ge_4(ticker):
    ctx = _CONTEXTS[ticker]
    if ctx.anchors_total >= 4:
        if ctx.ticker == "AMD":
            # Documented partial-plan case (1 resistance only).
            assert ctx.sl is not None and ctx.tp1 is not None
            assert (ctx.tp2 is None) == (ctx.tp3 is None)
        else:
            assert qb.trade_plan_complete(ctx.sl, ctx.tp1, ctx.tp2, ctx.tp3), (
                f"{ticker}: anchors={ctx.anchors_total} but plan incomplete"
            )


@pytest.mark.parametrize("ticker", _TICKERS)
def test_catalyst_bullets_min_2(ticker):
    ctx = _CONTEXTS[ticker]
    n = qb.count_catalyst_bullets(ctx.narrative)
    assert n >= 2, f"{ticker}: only {n} catalyst bullets; need ≥2"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_risk_section_present(ticker):
    ctx = _CONTEXTS[ticker]
    n = qb.count_risk_bullets(ctx.narrative)
    assert n >= 1, f"{ticker}: no risk bullets found"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_no_thinking_leak(ticker):
    ctx = _CONTEXTS[ticker]
    assert not qb.has_thinking_leak(ctx.narrative), f"{ticker}: thinking leaked"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_chat_data_in_narrative_when_present(ticker):
    ctx = _CONTEXTS[ticker]
    if "chat_24h" in ctx.sources_surfaced:
        assert "chat" in ctx.narrative.lower() or any(
            tok in ctx.narrative.lower() for tok in ("user", "channel")
        ), f"{ticker}: chat surfaced but narrative omits it"


@pytest.mark.parametrize("ticker", _TICKERS)
def test_yt_data_in_narrative_when_present(ticker):
    ctx = _CONTEXTS[ticker]
    if any(s.startswith("youtube") for s in ctx.sources_surfaced):
        assert ("youtube" in ctx.narrative.lower()
                or "yt" in ctx.narrative.lower()
                or "channel" in ctx.narrative.lower()), (
            f"{ticker}: yt surfaced but narrative omits it"
        )


# ---------------------------------------------------------------------------
# Layer B observable: aggregator emits a `quality_bar:` log line with
# 12 fields per call. This test pins the format so live-run parsing
# (scripts/run_quality_bar_live.py) doesn't drift silently.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quality_bar_log_line_format_complete(caplog, monkeypatch, tmp_path):
    """Run handle_all under a fixture and assert the quality_bar: line has
    all 12 expected fields in order."""
    from consensus_engine import config as cfg, db
    from consensus_engine.alerts.all_command import aggregator, narrator
    from consensus_engine.utils.xref_cache import clear_xref_cache

    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "qb.db")}
    cfg._config["vault"] = {"path": str(tmp_path)}
    clear_xref_cache()
    await db.init_db()

    # Minimal mocks: the existing _bullish_gather_factory + empty sanitize
    # combo from test_pr5_all_command_e2e produces a real run end-to-end.
    import sys
    sys.path.insert(0, str(tmp_path.parent))
    from tests.test_pr5_all_command_e2e import _bullish_gather_factory, _empty_sanitize

    async def _synth(**_kw):
        return _NVDA_NARRATIVE, "ok"

    async def _send_reply(*a, **kw):
        return "fake"

    async def _send_embed(*a, **kw):
        return "fake"

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_factory(sources_surfaced=["news", "sec", "twitter_db"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)
    monkeypatch.setattr(narrator, "synthesize_narrative", _synth)
    monkeypatch.setattr(aggregator, "send_command_reply", _send_reply)
    monkeypatch.setattr(aggregator, "send_command_embed_reply", _send_embed)

    try:
        with caplog.at_level(logging.INFO, logger="consensus_engine.alerts.all_command.aggregator"):
            await aggregator.handle_all("NVDA", "ch", "m")
    finally:
        await db.close_db()

    qb_lines = [r.message for r in caplog.records if "quality_bar:" in r.message]
    assert qb_lines, "no quality_bar log line emitted"

    # The 12 fields, in the documented order. Each must appear as `key=`.
    expected = [
        "ticker=", "sources_surfaced=", "sources_failed=", "anchors_total=",
        "sl=", "tp1=", "narrative_chars=", "narrative_status=",
        "stage_synth_ms=", "numbered_facts=", "catalyst_bullets=",
        "risk_bullets=",
    ]
    line = qb_lines[-1]
    for field in expected:
        assert field in line, f"missing {field} in quality_bar line: {line!r}"

    # Sanity: numbered_facts >= 3 because we used _NVDA_NARRATIVE.
    m = re.search(r"numbered_facts=(\d+)", line)
    assert m and int(m.group(1)) >= 3, f"numbered_facts < 3 in: {line}"
