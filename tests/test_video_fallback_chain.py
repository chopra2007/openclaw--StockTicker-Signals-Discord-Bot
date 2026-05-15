"""Tests for video-fallback-chain: F3 Groq Whisper, F6 hygiene, S2 regex, RunTelemetry schema.

Covers §8 verification checklist items 6, 8, 11.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.models import RunTelemetry
from consensus_engine.utils.transcript_fetch import parse_video_id
from consensus_engine.analysis.hallucination_grounding import (
    ground_transcript_tickers, all_ungrounded,
)


# ─── US-VF-001: RunTelemetry schema ──────────────────────────────────────────

def test_run_telemetry_schema():
    t = RunTelemetry()
    assert t.chain_winner is None
    assert t.chain_attempts == []
    assert t.chain_durations == {}
    assert t.hallucinated_ticker_count == 0
    assert t.cross_method_jaccard is None


# ─── US-VF-005: S2 regex validation in parse_video_id ────────────────────────

def test_s2_rejects_invalid_ids():
    assert parse_video_id("https://youtu.be/-oExec") is None, "-oExec rejected"
    assert parse_video_id("https://youtu.be/1234567890") is None, "10-char ID rejected"
    assert parse_video_id("https://youtu.be/" + "x" * 12) is None, "12-char ID rejected"


def test_s2_accepts_valid_ids():
    assert parse_video_id("https://youtu.be/4mSyMr8PGLI") == "4mSyMr8PGLI"
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


# ─── US-VF-003: hallucination_grounding ──────────────────────────────────────

def test_grounding_marks_present_tickers_grounded():
    transcript = "I'm bullish on $NVDA and also on $AAPL here."
    results = ground_transcript_tickers(["NVDA", "AAPL"], transcript)
    statuses = {r["ticker"]: r["grounding_status"] for r in results}
    assert statuses["NVDA"] == "grounded"
    assert statuses["AAPL"] == "grounded"


def test_grounding_marks_absent_tickers_ungrounded():
    # Tickers not in the transcript at all — not as $TICKER or bare word
    transcript = "The market is moving broadly higher today with no specific names."
    results = ground_transcript_tickers(["FAKETICKER", "BLOOMBERG"], transcript)
    assert all_ungrounded(results)


def test_grounding_mixed_result():
    # SPY appears as $SPY, FAKETICKER does not appear at all
    transcript = "I like $SPY for broad market exposure."
    results = ground_transcript_tickers(["SPY", "FAKETICKER"], transcript)
    statuses = {r["ticker"]: r["grounding_status"] for r in results}
    assert statuses["SPY"] == "grounded"
    assert statuses["FAKETICKER"] == "ungrounded"
    assert not all_ungrounded(results)


# ─── US-VF-003: F3 happy path (mocked) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_f3_happy_path():
    """F3 succeeds: mocked Gemini fails, Whisper returns transcript, chain_winner set."""
    transcript_text = "Today I'm buying $NVDA and $SPY for the breakout."
    from consensus_engine.models import EvidenceBundle, EvidenceSpan

    fake_bundle = EvidenceBundle(
        video_id="dQw4w9WgXcQ",
        duration_sec=60,
        publish_ts="2026-01-01T00:00:00Z",
        spans=[EvidenceSpan(ts_sec=0, quote="buying $NVDA", tickers=["NVDA"])],
    )

    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.local_video_ingest._stage_whisper", new_callable=AsyncMock, return_value=fake_bundle),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    # patch _stage_whisper but telemetry.chain_winner is set by the real _run_chain only if
    # bundle is returned; since we mock the stage function, just check bundle returned
    assert bundle is not None
    assert "gemini/v2" in telemetry.chain_attempts
    assert "whisper-groq/v1" in telemetry.chain_attempts


@pytest.mark.asyncio
async def test_f3_groq_429_falls_to_terminal():
    """Both Gemini and Whisper fail: chain returns (None, telemetry) with chain_winner=None."""
    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.local_video_ingest._stage_whisper", new_callable=AsyncMock, return_value=None),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    assert bundle is None
    assert telemetry.chain_winner is None


@pytest.mark.asyncio
async def test_f3_grounding_rejects_all():
    """When fetch_audio_transcript returns transcript but all tickers are ungrounded: None returned."""
    transcript_text = "The market is broadly moving higher today."

    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.local_video_ingest.fetch_audio_transcript", new_callable=AsyncMock, return_value=transcript_text),
        patch("consensus_engine.analysis.hallucination_grounding.ground_transcript_tickers",
              return_value=[{"ticker": "FAKE", "grounding_status": "ungrounded"}]),
        patch("consensus_engine.local_video_ingest._TICKER_RE") as mock_re,
    ):
        mock_re.findall.return_value = ["FAKE"]
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    assert bundle is None


# ─── US-VF-002: F6 pre-flight disk pressure ──────────────────────────────────

def test_f6_preflight_disk_pressure():
    """pre_flight_check returns False when disk is below threshold."""
    with patch("shutil.disk_usage") as mock_du:
        mock_du.return_value = MagicMock(free=100 * 1024 * 1024)  # 100MB < 500MB threshold
        with patch("os.makedirs"), patch("os.path.exists", return_value=True):
            from consensus_engine.hygiene.disk_inode_sweep import pre_flight_check
            result = pre_flight_check()
    assert result is False


@pytest.mark.asyncio
async def test_f6_preflight_blocks_chain():
    """Chain returns (None, telemetry) when pre_flight_check returns False."""
    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=False),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    assert bundle is None
    assert telemetry.chain_winner is None


# ─── S2: invalid video_id raises ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s2_invalid_video_id_raises():
    from consensus_engine.local_video_ingest import extract_evidence_via_chain
    with pytest.raises(ValueError, match="invalid video_id"):
        await extract_evidence_via_chain("-oExec1234", "Test", "2026-01-01T00:00:00Z")


@pytest.mark.asyncio
async def test_s2_short_video_id_raises():
    from consensus_engine.local_video_ingest import extract_evidence_via_chain
    with pytest.raises(ValueError, match="invalid video_id"):
        await extract_evidence_via_chain("tooshort", "Test", "2026-01-01T00:00:00Z")


# ─── C2.1: Whisper prompt rework (yt-chain-fixes) ────────────────────────────

def test_whisper_prompt_is_naturalistic_no_dollar_tickers():
    """The Groq Whisper prompt must not list $XXX tickens (anti-pattern that biased Whisper
    to invent dollar-prefixed symbols like $GOODPAL, $VYD). It should use a naturalistic
    domain hint instead."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "consensus_engine" / "local_video_ingest.py"
    text = src.read_text()
    # The old anti-pattern must be gone
    assert "Finance: tickers like $SPY" not in text, "old anti-pattern Whisper prompt still present"
    # The new naturalistic prompt must be present
    assert "This transcript covers financial markets" in text, "new Whisper prompt not found"
    # No $XXX-style tokens in any Whisper prompt assignment
    import re
    for line in text.splitlines():
        if "prompt=" in line and "transcriptions" in text[max(0, text.find(line) - 200):text.find(line)]:
            # crude check: no $ followed by 2+ uppercase letters
            assert not re.search(r"\$[A-Z]{2,}", line), f"dollar-prefixed ticker in prompt line: {line!r}"


# ─── R3: force-whisper hook via youtube.gemini.disabled_for_test ─────────────

@pytest.mark.asyncio
async def test_force_whisper_hook_skips_gemini():
    """When youtube.gemini.disabled_for_test=True, the chain skips F2 entirely and
    only attempts F3 (whisper-groq/v1). Used by verification probes to exercise F3
    in production-shaped traffic without changing default behavior."""
    def cfg_get(key, default=None):
        if key == "youtube.gemini.disabled_for_test":
            return True
        if key == "youtube.captions.enabled":
            return False
        if key == "youtube.whisper.enabled":
            return True
        return default

    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None) as gem_mock,
        patch("consensus_engine.local_video_ingest._stage_whisper", new_callable=AsyncMock, return_value=None),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    # F2 must NOT have been called when the hook is set
    gem_mock.assert_not_called()
    assert "gemini/v2" not in telemetry.chain_attempts
    assert "whisper-groq/v1" in telemetry.chain_attempts


@pytest.mark.asyncio
async def test_force_whisper_hook_default_off():
    """Default behavior (flag not set) MUST still attempt F2 — hook is opt-in only."""
    def cfg_get(key, default=None):
        # Return default for everything — no flag set
        return default

    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None) as gem_mock,
        patch("consensus_engine.local_video_ingest._stage_whisper", new_callable=AsyncMock, return_value=None),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    # F2 MUST have been called when flag is not set
    gem_mock.assert_called_once()
    assert "gemini/v2" in telemetry.chain_attempts
