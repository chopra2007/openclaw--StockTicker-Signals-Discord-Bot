"""Gap 1 — Earnings date must flow into the !all embed.

Two paths are tested:
  - Path A: decision_snapshots row carries `earnings_date` → existing
    `_earnings_iso(data["decision_snapshots"])` should already extract it.
    This test guards the existing plumbing.
  - Path B: decision_snapshots row is silent on earnings, but the new
    `fetch_next_earnings_for_ticker(ticker)` scanner returns an upcoming
    date. The aggregator must add this as `data["next_earnings_iso"]` and
    `_earnings_iso` must check it as a fallback.

W4: the embed field was renamed from "Timeframe" (string, e.g.
"earnings 2026-05-20") to "Next Catalyst" (integer day count, e.g. "9d")
when `all_command.swing_v2_enabled` is True. The user-visible contract
now: the Next Catalyst field shows a positive day count whenever any
source has an upcoming earnings date.
"""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import aggregator, narrator
from consensus_engine.models import ScoreBreakdown


class _Tech:
    current_price = 200.0
    atr14 = 4.0
    candles = [{"high": 202.0, "low": 198.0}]


def _bullish_gather_with_decision_snapshot_earnings():
    bd = ScoreBreakdown(base=30, news_catalyst=30, technical=30)
    score_obj = type("Score", (), {"breakdown": bd, "final_score": bd.total})()

    async def _gather(_ticker):
        return {
            "ticker_meta": {"name": "NVIDIA"}, "company_name": "NVIDIA",
            "score": score_obj,
            "technical_long": _Tech(),
            "technical_short": None,
            "twitter_signals": [], "social_signals": [],
            "yt_signals": [], "yt_options": [], "yt_levels": [], "yt_evidence": [],
            "alert_history": [],
            "decision_snapshots": [{"earnings_date": "2026-05-20"}],
            "news_catalyst": None, "sec_filings": [],
            "options_unusual": None, "trends": {}, "apewisdom": None,
            "chat_msgs": [], "brief_msgs": [], "prior_vault": None,
            "sources_surfaced": ["score", "technical_long"],
            "source_failures": [],
            "next_earnings_iso": None,
        }
    return _gather


def _bullish_gather_with_scanner_earnings():
    """No decision_snapshot earnings, but next_earnings_iso scanner field set."""
    bd = ScoreBreakdown(base=30, news_catalyst=30, technical=30)
    score_obj = type("Score", (), {"breakdown": bd, "final_score": bd.total})()

    async def _gather(_ticker):
        return {
            "ticker_meta": {"name": "NVIDIA"}, "company_name": "NVIDIA",
            "score": score_obj,
            "technical_long": _Tech(),
            "technical_short": None,
            "twitter_signals": [], "social_signals": [],
            "yt_signals": [], "yt_options": [], "yt_levels": [], "yt_evidence": [],
            "alert_history": [],
            "decision_snapshots": [],
            "news_catalyst": None, "sec_filings": [],
            "options_unusual": None, "trends": {}, "apewisdom": None,
            "chat_msgs": [], "brief_msgs": [], "prior_vault": None,
            "sources_surfaced": ["score", "technical_long", "earnings_calendar"],
            "source_failures": [],
            "next_earnings_iso": "2026-05-20",
        }
    return _gather


@pytest.mark.asyncio
async def test_earnings_date_from_decision_snapshot_populates_timeframe(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Path A: decision_snapshot earnings_date → embed Timeframe shows it."""
    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_with_decision_snapshot_earnings(),
    )

    async def _empty_sanitize(**_kw):
        return {"searxng": [], "chat": [], "brief": [], "vault": ""}

    async def _synth(**_kw):
        return "Bullish thesis.\n## Catalysts\n* x\n## Risk\n* z", "ok"

    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)
    monkeypatch.setattr(narrator, "synthesize_narrative", _synth)

    await aggregator.handle_all("NVDA", "ch", "m")

    embed = captured_sends["embed"][0][2]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    # W4 + Ship 1 N7: Next Catalyst is rendered as relative phrasing
    # ("today" / "in N sessions" / "in N days"), not a raw "Nd" count.
    nc = fields["Next Catalyst"]
    assert nc != "—", f"Expected non-empty Next Catalyst, got {nc!r}"
    assert (
        nc == "today" or nc.startswith("in ")
    ), f"Expected relative phrasing (today / in N sessions / in N days), got {nc!r}"


@pytest.mark.asyncio
async def test_next_earnings_scanner_fallback_when_decision_snapshot_empty(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """Path B: data['next_earnings_iso'] populated by scanner → Next Catalyst set."""
    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _bullish_gather_with_scanner_earnings(),
    )

    async def _empty_sanitize(**_kw):
        return {"searxng": [], "chat": [], "brief": [], "vault": ""}

    async def _synth(**_kw):
        return "Bullish thesis.\n## Catalysts\n* x\n## Risk\n* z", "ok"

    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)
    monkeypatch.setattr(narrator, "synthesize_narrative", _synth)

    await aggregator.handle_all("NVDA", "ch", "m")

    embed = captured_sends["embed"][0][2]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    nc = fields["Next Catalyst"]
    assert nc != "—", f"Scanner-sourced earnings should yield non-empty Next Catalyst; got {nc!r}"
    # Ship 1 N7 relative phrasing replaces raw "Nd" suffix.
    assert (
        nc == "today" or nc.startswith("in ")
    ), f"Expected relative phrasing, got {nc!r}"


@pytest.mark.asyncio
async def test_aggregator_calls_fetch_next_earnings_scanner(monkeypatch):
    """The aggregator's _gather_all_sources MUST dispatch to the new scanner.

    Routes _scanner_call by (module_path, attr) so the earnings dispatch
    returns "2026-05-20" while every other scanner stays None. Asserts the
    resulting data dict carries next_earnings_iso.
    """
    seen: list[tuple[str, str]] = []

    async def _routing_scanner(module_path, attr, *_a, **_kw):
        seen.append((module_path, attr))
        if (module_path, attr) == (
            "consensus_engine.scanners.earnings_calendar",
            "fetch_next_earnings_for_ticker",
        ):
            return "2026-05-20"
        return None

    async def _none(*_a, **_kw):
        return None

    async def _empty_list(*_a, **_kw):
        return []

    async def _empty_dict(*_a, **_kw):
        return {}

    monkeypatch.setattr(aggregator, "_db_call", _empty_list)
    monkeypatch.setattr(aggregator, "_score_ticker_safe", _none)
    monkeypatch.setattr(aggregator, "_verify_technical_safe", _none)
    monkeypatch.setattr(aggregator, "_scanner_call", _routing_scanner)
    monkeypatch.setattr(
        aggregator.discord_history, "fetch_chat_24h_ticker_filtered", _empty_list,
    )
    monkeypatch.setattr(
        aggregator.discord_history, "fetch_brief_last_3", _empty_list,
    )
    monkeypatch.setattr(
        aggregator.vault_writer, "read_existing_vault", _empty_dict,
    )

    out = await aggregator._gather_all_sources("NVDA")
    assert (
        "consensus_engine.scanners.earnings_calendar",
        "fetch_next_earnings_for_ticker",
    ) in seen, f"earnings scanner not dispatched; saw {seen}"
    assert out["next_earnings_iso"] == "2026-05-20", (
        f"data dict must include next_earnings_iso; got {out.get('next_earnings_iso')!r}"
    )


# Reuse the e2e fixtures
from tests.test_pr5_all_command_e2e import vault_path, captured_sends, isolated_db  # noqa: E402,F401
