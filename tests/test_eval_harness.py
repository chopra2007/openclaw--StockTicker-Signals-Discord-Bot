"""Unit tests for the eval harness in scripts/eval_extraction.py.

Covers:
- YAML corpus loads and skip=true entries are filtered out
- Per-video scoring math (precision/recall/compliance/setup/level/narrative/span)
- CLI entry point skips gracefully when GEMINI_API_KEY is unset
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "eval_extraction.py"
CORPUS_PATH = ROOT / "evals" / "youtube_videos.yaml"


def _load_script():
    """Import scripts/eval_extraction.py as a module without running __main__."""
    spec = importlib.util.spec_from_file_location("eval_extraction", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["eval_extraction"] = module
    spec.loader.exec_module(module)
    return module


harness = _load_script()

# Re-use internal types for scoring tests.
from consensus_engine.analysis.video_classifier import ClassificationResult
from consensus_engine.models import (
    CandidateLevel,
    CandidateSetup,
    CandidateSignal,
    Conviction,
    Direction,
    MacroThesis,
)


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def test_eval_yaml_loads():
    entries = harness.load_corpus(CORPUS_PATH)
    # Only non-skipped entries should be returned.
    assert len(entries) >= 1
    assert all(not e.get("skip") for e in entries)
    assert any(e["video_id"] == "4mSyMr8PGLI" for e in entries)


def test_eval_yaml_placeholders_skipped(tmp_path):
    """Sanity: entries marked skip:true are filtered out of load_corpus."""
    yaml_text = """
videos:
  - video_id: REAL
    channel: X
    skip: false
    expected: {high_conviction_tickers: [MSFT]}
  - video_id: PLACEHOLDER
    channel: Y
    skip: true
    expected: {}
"""
    p = tmp_path / "corpus.yaml"
    p.write_text(yaml_text)
    entries = harness.load_corpus(p)
    assert [e["video_id"] for e in entries] == ["REAL"]


# ---------------------------------------------------------------------------
# Scoring math
# ---------------------------------------------------------------------------

def _make_result(
    tickers_long_high=(), tickers_neutral_low=(), levels=(), setups=(),
    narrative="",
) -> ClassificationResult:
    signals = [
        CandidateSignal(
            ticker=t, direction=Direction.LONG, conviction=Conviction.HIGH,
            mention_count=4, context="", classifier_confidence=0.8,
        )
        for t in tickers_long_high
    ]
    signals.extend(
        CandidateSignal(
            ticker=t, direction=Direction.NEUTRAL, conviction=Conviction.LOW,
            mention_count=1, context="", suppressed=True,
            suppression_reason="neutral_low",
        )
        for t in tickers_neutral_low
    )
    return ClassificationResult(
        signals=signals,
        levels=list(levels),
        setups=list(setups),
        catalyst_candidates=[],
        macro_thesis=MacroThesis(
            direction=Direction.NEUTRAL, themes=[], timeframe="short",
            summary="", narrative=narrative,
        ),
    )


def test_precision_recall_perfect():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"high_conviction_tickers": ["MSFT", "SPY"]},
    }
    result = _make_result(tickers_long_high=["MSFT", "SPY"])
    m = harness.score_video(entry, result, span_count=40)
    assert m.ticker_precision == 1.0
    assert m.ticker_recall == 1.0


def test_precision_drops_when_actual_has_extras():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"high_conviction_tickers": ["MSFT"]},
    }
    # pipeline also alerts on NVDA → precision 0.5, recall 1.0
    result = _make_result(tickers_long_high=["MSFT", "NVDA"])
    m = harness.score_video(entry, result, span_count=40)
    assert m.ticker_precision == 0.5
    assert m.ticker_recall == 1.0


def test_recall_drops_when_missing_expected():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"high_conviction_tickers": ["MSFT", "SPY", "NDX"]},
    }
    result = _make_result(tickers_long_high=["MSFT"])  # missing 2 of 3
    m = harness.score_video(entry, result, span_count=40)
    assert m.ticker_precision == 1.0
    assert abs(m.ticker_recall - (1 / 3)) < 1e-9


def test_exclusion_compliance_counts_suppressed_or_neutral():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"excluded_tickers": ["USO", "TSLA"]},
    }
    # USO present but neutral-low (suppressed) → compliant. TSLA not observed.
    result = _make_result(tickers_neutral_low=["USO"])
    m = harness.score_video(entry, result, span_count=40)
    assert m.exclusion_compliance == 1.0


def test_exclusion_compliance_violated_when_excluded_alerts():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"excluded_tickers": ["USO"]},
    }
    # USO appears as LONG/HIGH → violation → 0 of 1 = 0
    result = _make_result(tickers_long_high=["USO"])
    m = harness.score_video(entry, result, span_count=40)
    assert m.exclusion_compliance == 0.0


def test_setup_match_rate():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {
            "setups": [{
                "ticker": "MSFT", "entry_low_min": 395, "entry_low_max": 405,
                "catalyst_date": "April 29",
            }],
        },
    }
    result = ClassificationResult(
        signals=[],
        levels=[],
        setups=[CandidateSetup(
            ticker="MSFT", entry_low=400, entry_high=400, stop=389,
            targets=[450], timeframe=None, setup_type=None,
            catalyst_date="April 29", catalyst_desc=None,
            context="", classifier_confidence=0.9,
        )],
        catalyst_candidates=[],
        macro_thesis=MacroThesis(
            direction=Direction.NEUTRAL, themes=[], timeframe="short",
            summary="", narrative="",
        ),
    )
    m = harness.score_video(entry, result, span_count=40)
    assert m.setup_match_rate == 1.0


def test_level_match_rate_partial():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {
            "levels": [
                {"ticker": "SPY", "type": "support", "price_min": 7000, "price_max": 7050},
                {"ticker": "NDX", "type": "resistance", "price_min": 27000, "price_max": 27500},
            ],
        },
    }
    levels = [
        CandidateLevel(ticker="SPY", level_type="support", price=7025, context=""),
        # NDX resistance price OUT OF range → miss
        CandidateLevel(ticker="NDX", level_type="resistance", price=30000, context=""),
    ]
    result = _make_result(levels=levels)
    m = harness.score_video(entry, result, span_count=40)
    assert m.level_match_rate == 0.5


def test_narrative_must_contain_any_positive():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"narrative_must_contain_any": ["Virgin POC", "FOMO"]},
    }
    result = _make_result(narrative="the sellers shut off and FOMO buyers stepped in")
    m = harness.score_video(entry, result, span_count=40)
    assert m.narrative_ok is True


def test_narrative_must_contain_any_negative():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"narrative_must_contain_any": ["Virgin POC"]},
    }
    result = _make_result(narrative="totally unrelated words")
    m = harness.score_video(entry, result, span_count=40)
    assert m.narrative_ok is False


def test_span_count_ok_threshold():
    entry = {
        "video_id": "v", "channel": "c",
        "expected": {"min_span_count": 20},
    }
    result = _make_result()
    assert harness.score_video(entry, result, span_count=25).span_count_ok is True
    assert harness.score_video(entry, result, span_count=10).span_count_ok is False


def test_passed_property_requires_all_thresholds():
    m = harness.VideoMetrics(
        video_id="v", channel="c",
        ticker_precision=1.0, ticker_recall=1.0,
        exclusion_compliance=1.0, setup_match_rate=1.0, level_match_rate=1.0,
        narrative_ok=True, span_count_ok=True,
    )
    assert m.passed is True
    # Below threshold precision → fail.
    m.ticker_precision = 0.5
    assert m.passed is False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_aggregate_averages_metrics():
    a = harness.VideoMetrics(
        video_id="a", channel="x", ticker_precision=1.0, ticker_recall=1.0,
    )
    b = harness.VideoMetrics(
        video_id="b", channel="x", ticker_precision=0.0, ticker_recall=0.5,
    )
    agg = harness.aggregate([a, b])
    assert agg["ticker_precision"] == 0.5
    assert agg["ticker_recall"] == 0.75


def test_aggregate_empty_returns_empty_dict():
    assert harness.aggregate([]) == {}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def test_eval_skip_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    rc = harness.main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "skipped" in captured.out.lower()


def test_eval_cli_help_does_not_crash(capsys):
    with pytest.raises(SystemExit) as exc:
        harness._parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "corpus" in out
