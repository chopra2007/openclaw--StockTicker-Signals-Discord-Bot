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

def _f3_only_cfg(key, default=None):
    # Force F1 off + F3 on so tests of F3 behavior aren't pre-empted by the
    # production default (youtube.captions.enabled=true) reaching real network.
    if key == "youtube.captions.enabled":
        return False
    if key == "youtube.whisper.enabled":
        return True
    return default


@pytest.mark.asyncio
async def test_chain_propagates_gemini_quota_category():
    """Item G (deep-dive-2026-06-08): when Gemini fails on quota and the captions
    backup also fails (here: captions disabled), the chain's returned telemetry must
    carry f2_failure_category='quota' so the scanner marks the video 'quota_blocked'
    (carry over), not 'failed' (burn a retry). Regression guard for the _stage_gemini
    propagation bug. (_f3_only_cfg disables captions, so nothing runs after Gemini.)"""
    gem_tel = RunTelemetry()
    gem_tel.f2_failure_category = "quota"

    with (
        patch("consensus_engine.config.get", side_effect=_f3_only_cfg),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.analysis.gemini_video_parser.extract_evidence_with_gemini",
              new_callable=AsyncMock, return_value=(None, gem_tel)),
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    assert bundle is None
    assert telemetry.f2_failure_category == "quota"


# REMOVED 2026-06-09: test_f3_happy_path, test_f3_groq_429_falls_to_terminal,
# test_f3_grounding_rejects_all — they tested the F3 yt-dlp+Whisper stage, which was
# deleted (yt-dlp is IP-blocked on this VPS so the stage never worked here).


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


# REMOVED 2026-06-09: test_whisper_prompt_is_naturalistic_no_dollar_tickers — it
# asserted on the Groq Whisper prompt, which was deleted with the F3 stage.


# ─── R3: disabled_for_test hook via youtube.gemini.disabled_for_test ─────────

@pytest.mark.asyncio
async def test_disabled_for_test_hook_skips_gemini():
    """When youtube.gemini.disabled_for_test=True, the chain skips F2 (Gemini). With
    captions also disabled here, nothing runs and it returns None. (The hook used to
    force the old F3 whisper stage; whisper is gone, so it just skips Gemini now.)"""
    def cfg_get(key, default=None):
        if key == "youtube.gemini.disabled_for_test":
            return True
        if key == "youtube.captions.enabled":
            return False
        return default

    with (
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch("consensus_engine.local_video_ingest._stage_gemini", new_callable=AsyncMock, return_value=None) as gem_mock,
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    # F2 must NOT have been called when the hook is set
    gem_mock.assert_not_called()
    assert "gemini/v2" not in telemetry.chain_attempts
    assert bundle is None


@pytest.mark.asyncio
async def test_fetch_captions_disabled_returns_none():
    """When youtube.captions.enabled=False, fetch_captions returns None immediately
    without calling either ytapi or Supadata."""
    def cfg_get(key, default=None):
        if key == "youtube.captions.enabled":
            return False
        return default

    with patch("consensus_engine.config.get", side_effect=cfg_get):
        from consensus_engine.local_video_ingest import fetch_captions
        result = await fetch_captions("dQw4w9WgXcQ")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_captions_via_supadata():
    """fetch_captions is Supadata-only now (the youtube_transcript_api tier was removed
    2026-06-09 — IP-blocked). It returns Supadata's transcript when present."""
    def cfg_get(key, default=None):
        if key == "youtube.captions.enabled":
            return True
        return default

    supadata_result = ("This is a Supadata-sourced transcript.", "en", True)

    with (
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch(
            "consensus_engine.utils.transcript_fetch._fetch_via_supadata",
            new_callable=AsyncMock,
            return_value=supadata_result,
        ),
    ):
        from consensus_engine.local_video_ingest import fetch_captions
        result = await fetch_captions("dQw4w9WgXcQ")

    assert result == "This is a Supadata-sourced transcript."


@pytest.mark.asyncio
async def test_fetch_captions_supadata_fail_returns_none():
    """When Supadata (the only source) fails, fetch_captions returns None so the chain
    falls through (back to F2, or to terminal)."""
    def cfg_get(key, default=None):
        if key == "youtube.captions.enabled":
            return True
        return default

    with (
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch(
            "consensus_engine.utils.transcript_fetch._fetch_via_supadata",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        from consensus_engine.local_video_ingest import fetch_captions
        result = await fetch_captions("dQw4w9WgXcQ")
    assert result is None


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
    ):
        from consensus_engine.local_video_ingest import _run_chain
        bundle, telemetry = await _run_chain("dQw4w9WgXcQ", "Test Channel", "2026-01-01T00:00:00Z")

    # F2 MUST have been called when flag is not set
    gem_mock.assert_called_once()
    assert "gemini/v2" in telemetry.chain_attempts


# ─── F1 → captions_llm_parser wiring (yt-chain-fixes) ────────────────────────

@pytest.mark.asyncio
async def test_stage_captions_routes_text_to_llm_parser():
    """F1 _stage_captions fetches caption text and hands it to
    extract_evidence_from_captions (the LLM-based ticker extractor). Auto-captions
    are natural language ("Apple", "Tesla") not $XXX markup, so a regex extractor
    catches almost nothing — the LLM is what resolves company name → ticker."""
    from consensus_engine.models import EvidenceBundle, EvidenceSpan
    fake_bundle = EvidenceBundle(
        video_id="dQw4w9WgXcQ",
        duration_sec=60,
        publish_ts="2026-01-01T00:00:00Z",
        spans=[
            EvidenceSpan(ts_sec=0, quote="Look at Apple and Tesla.", tickers=["AAPL", "TSLA"]),
            EvidenceSpan(ts_sec=30, quote="Micron looks weak.", tickers=["MU"]),
        ],
    )

    async def fake_fetch(video_id):
        return "Look at Apple and Tesla. Micron looks weak."

    async def fake_extract(video_id, text, published_at, telemetry):
        telemetry.span_count = len(fake_bundle.spans)
        return fake_bundle

    with (
        patch("consensus_engine.local_video_ingest.fetch_captions", side_effect=fake_fetch),
        patch(
            "consensus_engine.analysis.captions_llm_parser.extract_evidence_from_captions",
            side_effect=fake_extract,
        ),
    ):
        from consensus_engine.local_video_ingest import _stage_captions
        tel = RunTelemetry()
        bundle = await _stage_captions("dQw4w9WgXcQ", tel, "2026-01-01T00:00:00Z")

    assert bundle is fake_bundle
    assert tel.chain_winner == "ytdlp-captions/v1"
    assert tel.span_count == 2
    span_tickers = {t for span in bundle.spans for t in span.tickers}
    assert span_tickers == {"AAPL", "TSLA", "MU"}


@pytest.mark.asyncio
async def test_stage_captions_returns_none_when_llm_yields_nothing():
    """If the LLM extractor returns None (chain exhausted, no usable spans), the
    chain must fall through to F2 — not produce an empty bundle that would
    short-circuit to zero-signal classification (the prod regression we just rolled back)."""

    async def fake_fetch(video_id):
        return "Some unrelated transcript with no finance content at all."

    async def fake_extract(video_id, text, published_at, telemetry):
        return None  # LLM returned no usable spans

    with (
        patch("consensus_engine.local_video_ingest.fetch_captions", side_effect=fake_fetch),
        patch(
            "consensus_engine.analysis.captions_llm_parser.extract_evidence_from_captions",
            side_effect=fake_extract,
        ),
    ):
        from consensus_engine.local_video_ingest import _stage_captions
        tel = RunTelemetry()
        bundle = await _stage_captions("dQw4w9WgXcQ", tel, "")

    assert bundle is None
    assert tel.chain_winner is None
