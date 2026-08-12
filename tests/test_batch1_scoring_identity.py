"""Hostile identity tests for Batch 1 scoring and later grading."""

import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine import config as cfg, db
from consensus_engine.alerts.discord import format_detail_followup, owner_visible_score
from consensus_engine.cross_reference import _run_other_analysts
from consensus_engine.engine import SignalClass
from consensus_engine.models import CrossReferenceResult, ScoreBreakdown
from consensus_engine.measurement import (
    build_score_cache_key,
    classify_analyst_alignment,
    get_trade_chain,
    record_candidate,
    record_outcome,
    transition_decision,
)


@pytest.fixture
async def measurement_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "measurement.db")}
    await db.init_db()
    yield
    await db.close_db()


def _cache_inputs():
    return {
        "ticker": "NVDA",
        "direction": "long",
        "analyst": "alpha",
        "source": "tweetshift",
        "catalyst": "earnings",
        "base_score": 40,
        "rule_version": "rules-v1",
        "time_bucket": "2026-08-11T10:00",
        "input_fingerprint": "facts-a",
    }


@pytest.mark.parametrize(
    ("field", "other"),
    [
        ("ticker", "TSLA"),
        ("direction", "short"),
        ("analyst", "beta"),
        ("source", "manual"),
        ("catalyst", "guidance"),
        ("base_score", 41),
        ("rule_version", "rules-v2"),
        ("time_bucket", "2026-08-11T10:05"),
        ("input_fingerprint", "facts-b"),
    ],
)
def test_score_cache_key_changes_when_identity_input_changes(field, other):
    original = _cache_inputs()
    changed = dict(original, **{field: other})

    assert build_score_cache_key(**original) != build_score_cache_key(**changed)


def test_score_cache_key_is_stable_sha256():
    first = build_score_cache_key(**_cache_inputs())
    second = build_score_cache_key(**_cache_inputs())

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


def test_opposing_analyst_direction_is_disagreement():
    assert classify_analyst_alignment("long", "short") == "disagreement"


def _detail_xref():
    return CrossReferenceResult(
        ticker="NVDA",
        breakdown=ScoreBreakdown(base=80, technical=25),
        catalyst_summary="",
        catalyst_type="",
    )


@pytest.mark.parametrize(
    ("single_score", "display_honesty", "expected_score"),
    [(False, False, 105), (False, True, 72), (True, False, 72), (True, True, 72)],
)
def test_detail_card_score_matches_owner_visible_score_for_every_current_flag_branch(
    monkeypatch, single_score, display_honesty, expected_score
):
    real_get = cfg.get
    settings = {
        "features.single_score.enabled": single_score,
        "features.score_display_honesty.enabled": display_honesty,
    }
    monkeypatch.setattr(cfg, "get", lambda key, default=None: settings.get(key, real_get(key, default)))
    precision = {
        "skipped": False,
        "classification": SignalClass.WATCHLIST,
        "total_score": 72,
        "reconciled_score": 72,
        "i4_full_budget_depressed": False,
        "skipped_sources": [],
        "market_ok": True,
        "has_mainstream": True,
    }

    score = owner_visible_score(_detail_xref(), precision)
    embed = format_detail_followup(_detail_xref(), precision)
    precision_field = next(field for field in embed["fields"] if field["name"] == "Precision Engine")

    assert score == expected_score
    assert f"Score: {score}" in embed["title"]
    assert f"score={score}" in precision_field["value"]


@pytest.mark.asyncio
async def test_unsigned_legacy_analyst_signal_never_adds_agreement():
    unsigned = [{"analyst": "legacy", "direction": "neutral"}]

    with patch(
        "consensus_engine.cross_reference.db.get_recent_analyst_signals_for_ticker",
        new=AsyncMock(return_value=unsigned),
    ):
        result = await _run_other_analysts("NVDA", "long")

    assert result == {"aligned": [], "opposing": []}


@pytest.mark.asyncio
async def test_analyst_identity_and_short_direction_survive_grading(measurement_db):
    candidate_id = await record_candidate(
        ticker="NVDA", direction="short", analyst="alpha"
    )
    decision_id = await transition_decision(candidate_id=candidate_id, status="scored")

    await record_outcome(
        decision_id=decision_id,
        direction="short",
        horizon="5d",
        status="resolved",
        value=0.12,
        analyst="alpha",
    )

    chain = await get_trade_chain(candidate_id)
    assert chain["outcomes"][0]["analyst"] == "alpha"
    assert chain["outcomes"][0]["direction"] == "short"
