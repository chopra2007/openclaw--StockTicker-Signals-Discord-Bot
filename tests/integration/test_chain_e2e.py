"""End-to-end coverage of `extract_evidence_via_chain` orchestration.

Two layers:
- **Mocked (default)**: cover the chain's orchestration contract — stage
  short-circuiting, force-whisper hook, semaphore serialization, cleanup
  invariants, telemetry completeness. No network. Runs every `pytest`.
- **Live (`@pytest.mark.live`)**: real call against real videos when
  `OMC_LIVE_TESTS=1` is set AND required keys are present in env. Skipped
  by default (pytest.ini addopts `-m "not live"`).

Locks in regression coverage now that F1 (captions+LLM) and F2 (Gemini
video) both work end-to-end — see commit d3cf2be for the F1 wiring.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.models import EvidenceBundle, EvidenceSpan, RunTelemetry


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_bundle(video_id: str, tickers: list[str], quote: str = "sample") -> EvidenceBundle:
    return EvidenceBundle(
        video_id=video_id,
        duration_sec=60,
        publish_ts="2026-05-15T00:00:00Z",
        segments=[{"text": quote}],
        spans=[EvidenceSpan(ts_sec=0, quote=quote, tickers=tickers)],
    )


def _cfg_factory(**overrides):
    """Return a cfg.get side-effect that returns overrides for matching keys,
    None (acting like missing) otherwise."""
    def _get(key, default=None):
        if key in overrides:
            return overrides[key]
        return default
    return _get


def _patch_chain_env(*, captions_enabled=False, gemini_disabled=False, whisper_enabled=True):
    """Standard patch stack for non-live chain tests — pre_flight passes,
    cleanup is observable, config is fully controlled."""
    cfg_get = _cfg_factory(**{
        "youtube.captions.enabled": captions_enabled,
        "youtube.gemini.disabled_for_test": gemini_disabled,
        "youtube.whisper.enabled": whisper_enabled,
    })
    return [
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
    ]


# ─── Mocked orchestration tests (default) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_chain_f1_captions_fallback_via_supadata():
    """Gemini (F2) is now PRIMARY. When it returns None (e.g. 503/quota), the
    chain falls back to F1 captions via Supadata → captions_llm_parser returns
    the bundle. F3 whisper must NOT be reached."""
    fake_bundle = _make_bundle("dQw4w9WgXcQ", ["SPY", "QQQ"], "S&P leading, Q's same.")

    cfg_get = _cfg_factory(**{"youtube.captions.enabled": True})

    async def fake_extract(video_id, text, published_at, tel):
        tel.span_count = 1
        return fake_bundle

    with (
        patch("consensus_engine.config.get", side_effect=cfg_get),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch(
            "consensus_engine.local_video_ingest.fetch_captions",
            new_callable=AsyncMock, return_value="real caption text",
        ),
        patch(
            "consensus_engine.analysis.captions_llm_parser.extract_evidence_from_captions",
            side_effect=fake_extract,
        ),
        patch(
            "consensus_engine.local_video_ingest._stage_gemini",
            new_callable=AsyncMock, return_value=None,
        ) as gem_mock,
        patch(
            "consensus_engine.local_video_ingest._stage_whisper",
            new_callable=AsyncMock,
        ) as whisper_mock,
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, tel = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test Channel", "2026-05-15T00:00:00Z",
        )

    assert bundle is fake_bundle
    assert tel.chain_winner == "ytdlp-captions/v1"
    # Gemini (primary) is attempted first, returns None, then captions wins.
    assert tel.chain_attempts == ["gemini/v2", "ytdlp-captions/v1"]
    gem_mock.assert_called_once()
    whisper_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chain_f2_wins_when_f1_disabled():
    """Default chain (F1 off) → F2 returns bundle → F3 not invoked."""
    fake_bundle = _make_bundle("dQw4w9WgXcQ", ["NVDA"])

    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini",
              new_callable=AsyncMock, return_value=fake_bundle),
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock) as whisper_mock,
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, tel = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test Channel", "2026-05-15T00:00:00Z",
        )

    assert bundle is fake_bundle
    assert "gemini/v2" in tel.chain_attempts
    assert "whisper-groq/v1" not in tel.chain_attempts
    whisper_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chain_force_whisper_via_config_skips_gemini():
    """`youtube.gemini.disabled_for_test=True` → F2 skipped, F3 attempted."""
    fake_bundle = _make_bundle("dQw4w9WgXcQ", ["TSLA"])

    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{
                  "youtube.captions.enabled": False,
                  "youtube.gemini.disabled_for_test": True,
                  "youtube.whisper.enabled": True,
              })),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini",
              new_callable=AsyncMock) as gem_mock,
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock, return_value=fake_bundle),
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, tel = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test Channel", "2026-05-15T00:00:00Z",
        )

    assert bundle is fake_bundle
    gem_mock.assert_not_called()
    assert "gemini/v2" not in tel.chain_attempts
    assert "whisper-groq/v1" in tel.chain_attempts


@pytest.mark.asyncio
async def test_chain_semaphore_serializes_concurrent_calls():
    """Two concurrent chain calls must NOT overlap inside _run_chain.
    The module-level semaphore (X-1) is the only thing enforcing this."""
    enter_log: list[tuple[str, float]] = []
    exit_log: list[tuple[str, float]] = []

    async def slow_gemini(video_id, display_name, published_at, tel):
        enter_log.append((video_id, asyncio.get_event_loop().time()))
        await asyncio.sleep(0.15)
        exit_log.append((video_id, asyncio.get_event_loop().time()))
        return _make_bundle(video_id, ["X"])

    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini", side_effect=slow_gemini),
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock),
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        await asyncio.gather(
            extract_evidence_via_chain("AAAAAAAAAAA", "ChA", "2026-05-15T00:00:00Z"),
            extract_evidence_via_chain("BBBBBBBBBBB", "ChB", "2026-05-15T00:00:00Z"),
            extract_evidence_via_chain("CCCCCCCCCCC", "ChC", "2026-05-15T00:00:00Z"),
        )

    # If serialized, every exit precedes the next enter (with floating slack).
    assert len(enter_log) == 3 and len(exit_log) == 3
    for i in range(len(enter_log) - 1):
        next_enter_ts = enter_log[i + 1][1]
        this_exit_ts = exit_log[i][1]
        assert next_enter_ts >= this_exit_ts - 0.01, (
            f"chain calls overlapped: enter[{i+1}]={next_enter_ts} "
            f"before exit[{i}]={this_exit_ts}"
        )


@pytest.mark.asyncio
async def test_chain_cleanup_runs_after_success():
    """cleanup_run_workspace must fire even on the success path."""
    fake_bundle = _make_bundle("dQw4w9WgXcQ", ["NVDA"])
    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace") as cleanup_mock,
        patch("consensus_engine.local_video_ingest._stage_gemini",
              new_callable=AsyncMock, return_value=fake_bundle),
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock),
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        await extract_evidence_via_chain("dQw4w9WgXcQ", "Test", "2026-05-15T00:00:00Z")
    cleanup_mock.assert_called_once()


@pytest.mark.asyncio
async def test_chain_cleanup_runs_after_failure():
    """cleanup_run_workspace must fire even when every stage returns None."""
    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace") as cleanup_mock,
        patch("consensus_engine.local_video_ingest._stage_gemini",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock, return_value=None),
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, _ = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test", "2026-05-15T00:00:00Z",
        )
    assert bundle is None
    cleanup_mock.assert_called_once()


@pytest.mark.asyncio
async def test_chain_telemetry_complete_after_run():
    """Telemetry must carry chain_winner, chain_attempts, chain_durations
    (including 'total_ms') after a successful chain — these are the fields
    persistence + observability rely on. Mock _stage_gemini to mirror the
    real function's contract: set chain_winner='gemini/v2' on success."""
    fake_bundle = _make_bundle("dQw4w9WgXcQ", ["AAPL"])

    async def gemini_like(video_id, display_name, published_at, tel):
        tel.chain_winner = "gemini/v2"
        tel.span_count = 1
        return fake_bundle

    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=True),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini", side_effect=gemini_like),
        patch("consensus_engine.local_video_ingest._stage_whisper",
              new_callable=AsyncMock),
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        _, tel = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test", "2026-05-15T00:00:00Z",
        )
    assert tel.chain_winner == "gemini/v2"
    assert tel.chain_attempts == ["gemini/v2"]
    assert "total_ms" in tel.chain_durations
    assert tel.chain_durations["total_ms"] >= 0


@pytest.mark.asyncio
async def test_chain_rejects_invalid_video_id():
    """S2 regex must reject IDs that don't match `[A-Za-z0-9_-]{11}`."""
    from consensus_engine.local_video_ingest import extract_evidence_via_chain
    with pytest.raises(ValueError, match="invalid video_id"):
        await extract_evidence_via_chain("../bad", "Test", "2026-05-15T00:00:00Z")
    with pytest.raises(ValueError, match="invalid video_id"):
        await extract_evidence_via_chain("tooshort", "Test", "2026-05-15T00:00:00Z")


@pytest.mark.asyncio
async def test_chain_preflight_failure_returns_none():
    """When F6 pre_flight_check fails, chain returns (None, telemetry)
    without running any stage."""
    with (
        patch("consensus_engine.config.get",
              side_effect=_cfg_factory(**{"youtube.captions.enabled": False, "youtube.whisper.enabled": True})),
        patch("consensus_engine.local_video_ingest.pre_flight_check", return_value=False),
        patch("consensus_engine.local_video_ingest.cleanup_run_workspace"),
        patch("consensus_engine.local_video_ingest._stage_gemini",
              new_callable=AsyncMock) as gem_mock,
    ):
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, tel = await extract_evidence_via_chain(
            "dQw4w9WgXcQ", "Test", "2026-05-15T00:00:00Z",
        )
    assert bundle is None
    assert tel.chain_winner is None
    gem_mock.assert_not_called()


# ─── Live tests (opt-in: OMC_LIVE_TESTS=1 + pytest -m live) ───────────────────
#
# These hit real Supadata + OpenRouter (Gemini Flash for caption LLM). Skipped
# by default via pytest.ini addopts. Run with:
#   OMC_LIVE_TESTS=1 python3 -m pytest -q -m live tests/integration/test_chain_e2e.py

_LIVE_VIDEO_ID = os.environ.get("OMC_LIVE_VIDEO_ID", "dhK-Wdz0gzo")  # SPX analysis, ~25k chars
_LIVE_PUBLISHED_AT = "2026-05-13T00:00:00+00:00"


def _live_skip_reason() -> str | None:
    if os.environ.get("OMC_LIVE_TESTS") != "1":
        return "OMC_LIVE_TESTS!=1"
    if not os.environ.get("SUPADATA_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        return "no SUPADATA_API_KEY / OPENROUTER_API_KEY in env"
    return None


@pytest.mark.live
@pytest.mark.asyncio
async def test_chain_live_f1_real_video():
    """Real F1 chain on a real video. Verifies the production wiring end-to-end.
    Forces F1 on + F2 off so we observe F1 in isolation."""
    skip = _live_skip_reason()
    if skip:
        pytest.skip(skip)

    import consensus_engine.config as c
    orig = c.get

    def patched(key, default=None):
        if key == "youtube.captions.enabled":
            return True
        if key == "youtube.gemini.disabled_for_test":
            return True
        return orig(key, default)

    c.get = patched
    try:
        from consensus_engine.local_video_ingest import extract_evidence_via_chain
        bundle, tel = await asyncio.wait_for(
            extract_evidence_via_chain(_LIVE_VIDEO_ID, "live test", _LIVE_PUBLISHED_AT),
            timeout=180,
        )
    finally:
        c.get = orig

    assert bundle is not None, "F1 chain returned no bundle on a known-good video"
    assert tel.chain_winner == "ytdlp-captions/v1"
    assert bundle.spans, "bundle has no spans"
    spans_with_tickers = [sp for sp in bundle.spans if sp.tickers]
    assert spans_with_tickers, (
        "F1 bundle has spans but no tickers — captions_llm_parser regression"
    )
