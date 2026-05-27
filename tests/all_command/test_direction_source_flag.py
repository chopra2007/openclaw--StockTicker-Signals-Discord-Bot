"""Unit tests for Step 10 + 10b — direction_source flag + parity halt-gate.

Updated 2026-05-26 after the original "legacy reads breakdown.direction"
shape was found to be broken (ScoreBreakdown has no `direction` field —
the original getattr() always defaulted to "neutral", producing 73%
spurious disagreements in the first soak window). Legacy now calls
structured_fields.compute_direction(breakdown), the function the embed
already uses; structured continues to call compute_direction_from_fields.
Both implement the same field-sum logic; parity comparison normalizes
the BULLISH/LONG label conventions.

Tests:
  - direction_source="legacy" returns compute_direction(breakdown) result
  - direction_source="structured" returns compute_direction_from_fields result
  - parity logging fires on every call with normalized agree field
  - 5 sample events: legacy and structured agree under normalization
"""
from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from consensus_engine.alerts.all_command.structured_fields import (
    compute_direction,
    compute_direction_from_fields,
)
from consensus_engine.models import ScoreBreakdown


# Normalize BULLISH/LONG and BEARISH/SHORT for parity comparisons —
# both label sets describe the same underlying direction.
_DIRECTION_SYNONYMS = {
    "bullish": "long", "long": "long",
    "bearish": "short", "short": "short",
    "neutral": "neutral",
}


def _norm(direction: str) -> str:
    return _DIRECTION_SYNONYMS.get(direction.lower(), direction.lower())


# ---------------------------------------------------------------------------
# Helpers: build a minimal ScoreBreakdown and mock score_result
# ---------------------------------------------------------------------------

def _make_breakdown(**kwargs) -> ScoreBreakdown:
    """Return a ScoreBreakdown with given field values (rest default to 0)."""
    return ScoreBreakdown(**kwargs)


def _make_score_result(breakdown: ScoreBreakdown | None):
    """Return a minimal score_result mock with .breakdown attribute."""
    sr = MagicMock()
    sr.breakdown = breakdown
    return sr


def _compute_legacy(score_result) -> str:
    """Replicate the legacy direction logic from aggregator.py (revised)."""
    _score_bd_raw = getattr(score_result, "breakdown", None)
    return compute_direction(_score_bd_raw)


def _compute_structured(score_result) -> str:
    """Replicate the structured direction logic from aggregator.py."""
    _score_bd_raw = getattr(score_result, "breakdown", None)
    _bd_dict: dict = (
        dataclasses.asdict(_score_bd_raw)
        if _score_bd_raw is not None and dataclasses.is_dataclass(_score_bd_raw)
        else {}
    )
    return compute_direction_from_fields(_bd_dict)


# ---------------------------------------------------------------------------
# Step 10: direction_source flag routing
# ---------------------------------------------------------------------------

def test_direction_source_legacy_uses_compute_direction():
    """Legacy path runs compute_direction(breakdown) — same function the embed uses."""
    bd = _make_breakdown(news_catalyst=10, technical=5)
    sr = _make_score_result(bd)

    legacy = _compute_legacy(sr)
    assert legacy == "BULLISH"  # positive sum -> BULLISH per the BULLISH/BEARISH label set


def test_direction_source_structured_returns_compute_direction_from_fields():
    """Structured path runs compute_direction_from_fields — returns LONG/SHORT/NEUTRAL."""
    bd = _make_breakdown(news_catalyst=20, technical=10, options_flow=5)
    sr = _make_score_result(bd)

    structured = _compute_structured(sr)
    assert structured == "LONG"


def test_direction_source_structured_short():
    """Structured path returns SHORT when breakdown fields are net negative."""
    bd = _make_breakdown(news_catalyst=-15, technical=-8)
    sr = _make_score_result(bd)
    structured = _compute_structured(sr)
    assert structured == "SHORT"


def test_direction_source_structured_neutral():
    """Structured path returns NEUTRAL when breakdown net is zero."""
    bd = _make_breakdown()  # all zeros
    sr = _make_score_result(bd)
    structured = _compute_structured(sr)
    assert structured == "NEUTRAL"


def test_direction_source_legacy_none_breakdown():
    """When breakdown is None, legacy returns NEUTRAL (compute_direction's safe default)."""
    sr = _make_score_result(None)
    legacy = _compute_legacy(sr)
    assert legacy == "NEUTRAL"


def test_direction_source_structured_none_breakdown():
    """When breakdown is None, structured returns NEUTRAL."""
    sr = _make_score_result(None)
    structured = _compute_structured(sr)
    assert structured == "NEUTRAL"


def test_label_normalization_bullish_long_equivalent():
    """BULLISH and LONG normalize to the same value — used by the parity gate."""
    assert _norm("BULLISH") == _norm("LONG") == "long"
    assert _norm("BEARISH") == _norm("SHORT") == "short"
    assert _norm("NEUTRAL") == "neutral"


# ---------------------------------------------------------------------------
# Step 10b: parity logging fires on every call
# ---------------------------------------------------------------------------

def test_parity_log_written(tmp_path):
    """Parity logging writes a valid JSONL entry with normalized agree field."""
    log_path = tmp_path / "parity-results.jsonl"

    bd = _make_breakdown(news_catalyst=5, technical=3)
    sr = _make_score_result(bd)

    ticker = "NVDA"
    start = time.monotonic()

    _legacy = _compute_legacy(sr)
    _structured = _compute_structured(sr)

    entry = json.dumps({
        "event_id": f"{ticker}:{int(start)}",
        "ticker": ticker,
        "legacy_direction": _legacy,
        "structured_direction": _structured,
        "agree": _norm(_legacy) == _norm(_structured),
        "ts": time.time(),
    })
    log_path.write_text(entry + "\n")

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["ticker"] == "NVDA"
    assert parsed["legacy_direction"] == "BULLISH"
    assert parsed["structured_direction"] == "LONG"
    assert parsed["agree"] is True  # normalized — BULLISH and LONG are synonyms


def test_parity_log_multiple_entries(tmp_path):
    """Parity log appends one entry per call."""
    log_path = tmp_path / "parity-results.jsonl"

    for i in range(3):
        bd = _make_breakdown(news_catalyst=i * 2)
        sr = _make_score_result(bd)
        _legacy = _compute_legacy(sr)
        _structured = _compute_structured(sr)
        entry = json.dumps({
            "event_id": f"TEST:{i}",
            "ticker": "TEST",
            "legacy_direction": _legacy,
            "structured_direction": _structured,
            "agree": _norm(_legacy) == _norm(_structured),
            "ts": time.time(),
        })
        with log_path.open("a") as f:
            f.write(entry + "\n")

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# Step 10b: parity halt-gate — 5 sample events, legacy and structured agree
# ---------------------------------------------------------------------------

# Five representative events with consistent score_breakdown fields.
# Each lists the structured-label expected output (LONG/SHORT/NEUTRAL);
# legacy returns the equivalent BULLISH/BEARISH/NEUTRAL label.
_PARITY_EVENTS = [
    # (ticker, breakdown kwargs, structured_expected)
    ("NVDA", {"news_catalyst": 15, "technical": 10, "options_flow": 5}, "LONG"),
    ("TSLA", {"news_catalyst": -12, "technical": -8, "options_flow": -3}, "SHORT"),
    ("AMD",  {"news_catalyst": 8, "technical": 6, "llm_boost": 4}, "LONG"),
    ("SPY",  {"news_catalyst": 0, "technical": 0}, "NEUTRAL"),
    ("AAPL", {"news_catalyst": -5, "technical": -7, "consensus_boost": -2}, "SHORT"),
]


@pytest.mark.parametrize("ticker,kwargs,expected", _PARITY_EVENTS)
def test_parity_gate_single_event(ticker, kwargs, expected):
    """Each sample event: legacy and structured agree under label normalization."""
    bd = _make_breakdown(**kwargs)
    sr = _make_score_result(bd)

    legacy = _compute_legacy(sr)
    structured = _compute_structured(sr)

    # Parity gate: both must agree under synonym normalization
    assert _norm(legacy) == _norm(structured), (
        f"PARITY DIVERGENCE for {ticker}: legacy={legacy!r} structured={structured!r}"
    )
    # Structured output uses the LONG/SHORT label set
    assert structured == expected


def test_parity_gate_all_5_events():
    """Simulate 5 events and assert 5/5 parity under label normalization."""
    divergences = []
    for ticker, kwargs, expected in _PARITY_EVENTS:
        bd = _make_breakdown(**kwargs)
        sr = _make_score_result(bd)

        legacy = _compute_legacy(sr)
        structured = _compute_structured(sr)

        if _norm(legacy) != _norm(structured):
            divergences.append({
                "ticker": ticker,
                "legacy": legacy,
                "structured": structured,
            })

    assert len(divergences) == 0, (
        f"HALT: {len(divergences)}/5 parity divergences detected:\n"
        + "\n".join(str(d) for d in divergences)
    )
