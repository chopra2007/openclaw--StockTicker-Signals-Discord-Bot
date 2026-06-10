"""YouTube evidence chain — Gemini primary, Supadata captions as final backup.

Order: F2 (Gemini watches the video — the only reliably-working path from this VPS,
since Google fetches the video server-side, not via our blacklisted IP) → F1 (Supadata
captions, limited-credit last resort). The old F3 yt-dlp+Whisper stage was REMOVED
2026-06-09 (yt-dlp is IP-blocked here) — see the note at the bottom of this file.
Short-circuits on first viable bundle. F6 hygiene runs at entry and in finally:.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

from consensus_engine.models import EvidenceBundle, RunTelemetry
from consensus_engine.hygiene.disk_inode_sweep import pre_flight_check, cleanup_run_workspace

log = logging.getLogger("consensus_engine.local_video_ingest")

# X-1: module-scope semaphore ensures one chain per process at a time.
# Lazy init so import works before an event loop is running.
_chain_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _chain_semaphore
    if _chain_semaphore is None:
        _chain_semaphore = asyncio.Semaphore(1)
    return _chain_semaphore


async def extract_evidence_via_chain(
    video_id: str,
    display_name: str,
    published_at: str,
) -> tuple[EvidenceBundle | None, RunTelemetry]:
    """Entry point for the multi-method chain. Matches extract_evidence_with_gemini signature."""
    async with _get_semaphore():
        return await _run_chain(video_id, display_name, published_at)


# ─── Public helpers (isolated for testability) ────────────────────────────────

async def fetch_captions(video_id: str) -> str | None:
    """F1: fetch auto-captions via Supadata only. Returns None when disabled or it fails.

    REMOVED 2026-06-09: the youtube_transcript_api tier that used to run first.
    It hits YouTube directly from our IP, which YouTube has BLACKLISTED (IpBlocked /
    "confirm you're not a bot") — it never worked from this VPS and cookies don't help.
    DO NOT re-add it. Supadata fetches via its own residential network so it sidesteps
    the IP block; it's a paid API with limited free credits, so it's the final backup
    behind Gemini (the primary path that watches the video directly)."""
    from consensus_engine.config import get as cfg
    if not cfg("youtube.captions.enabled", False):
        return None

    # Supadata — fetches via their own residential infra, sidesteps the IP block.
    # SUPADATA_API_KEY in env. Helper at consensus_engine/utils/transcript_fetch.py.
    try:
        from consensus_engine.utils.transcript_fetch import _fetch_via_supadata
        result = await _fetch_via_supadata(video_id)
        if result is not None:
            text, _lang, _is_manual = result
            log.info("F1 captions via Supadata for %s: %d chars", video_id, len(text))
            return text
    except Exception as exc:
        log.warning("F1 Supadata fallback failed for %s: %s", video_id, exc)

    return None


async def extract_frames(video_id: str, mode: str = "scene-change") -> list:
    """F4: extract scene frames with FFmpeg. Returns [] when disabled."""
    from consensus_engine.config import get as cfg
    if not cfg("youtube.vision.enabled", False):
        return []
    # Phase 2: FFmpeg scene-change extraction goes here.
    return []


# ─── Transcript persistence ───────────────────────────────────────────────────

async def _save_transcript_and_trim(video_id: str, text: str) -> None:
    """Save transcript to DB and delete rows older than 30 days.

    Called after each successful caption/whisper fetch so the backfill script
    can re-parse transcripts without hitting external APIs. Old rows are trimmed
    inline to avoid unbounded disk growth.
    """
    import hashlib
    from consensus_engine import db
    try:
        h = hashlib.sha256(text.encode()).hexdigest()
        await db.save_youtube_transcript(video_id, text, h)
        conn = await db.get_db()
        await conn.execute(
            "DELETE FROM youtube_transcripts WHERE saved_at < strftime('%s','now') - 30*86400"
        )
        await conn.commit()
    except Exception as exc:
        log.debug("transcript save/trim failed for %s: %s", video_id, exc)


# ─── Chain orchestrator ───────────────────────────────────────────────────────

async def _run_chain(
    video_id: str,
    display_name: str,
    published_at: str,
) -> tuple[EvidenceBundle | None, RunTelemetry]:
    telemetry = RunTelemetry()
    run_id = str(uuid.uuid4())[:8]
    chain_start = time.monotonic()

    # S2: validate video_id before any subprocess call
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(f"invalid video_id: {video_id!r}")

    try:
        from consensus_engine.config import get as cfg

        # F6 pre-flight
        if not pre_flight_check():
            log.warning("F6 pre-flight failed — skipping chain for %s", video_id)
            return None, telemetry

        # F2: Gemini video — PRIMARY. Only path that reads on-screen chart numbers
        # (visual_evidence) AND the only path that works reliably from this VPS:
        # Google fetches the video on its own servers, sidestepping our blacklisted
        # IP. Uses gemini-flash-latest @ 0.5fps with a 503 model-fallback chain (see
        # gemini_video_parser). On 503/quota exhaustion it returns None and falls
        # through to captions. `gemini.disabled_for_test` lets probes skip F2.
        if not cfg("youtube.gemini.disabled_for_test", False):
            telemetry.chain_attempts.append("gemini/v2")
            bundle = await _stage_gemini(video_id, display_name, published_at, telemetry)
            if bundle is not None:
                return bundle, telemetry

        # F1: captions (Supadata only) → LLM ticker extraction — FINAL BACKUP when
        # Gemini is unavailable / quota-exhausted. Audio-only (no chart visuals) and
        # Supadata's free plan has limited monthly credits, so it's last-resort.
        if cfg("youtube.captions.enabled", False):
            # Label kept as the legacy "ytdlp-captions/v1" for telemetry/DB continuity
            # (matches get_youtube_coverage_counts + historical rows); it is actually
            # Supadata now — the yt-dlp path was removed.
            telemetry.chain_attempts.append("ytdlp-captions/v1")
            bundle = await _stage_captions(video_id, telemetry, published_at)
            if bundle is not None:
                return bundle, telemetry

        # REMOVED 2026-06-09 — the F3 yt-dlp-audio + Groq-Whisper stage. yt-dlp
        # downloads from YouTube via our IP, which is BLACKLISTED (429 / "confirm
        # you're not a bot") — it never worked from this VPS. DO NOT re-add a yt-dlp
        # path. (Whisper itself was fine; it just had no way to get the audio.)
        return None, telemetry

    finally:
        telemetry.chain_durations["total_ms"] = int((time.monotonic() - chain_start) * 1000)
        try:
            cleanup_run_workspace(run_id)
        except Exception as exc:
            log.debug("F6 cleanup error: %s", exc)


# ─── Stage implementations ────────────────────────────────────────────────────

async def _stage_captions(
    video_id: str,
    telemetry: RunTelemetry,
    published_at: str = "",
) -> EvidenceBundle | None:
    t0 = time.monotonic()
    try:
        text = await fetch_captions(video_id)
        if text is None:
            return None

        await _save_transcript_and_trim(video_id, text)

        # YouTube auto-captions don't markup tickers as $XXX and use natural
        # language ("apple", "tesla"). Route the text through the configured
        # LLM chain (Gemini Flash → free OpenRouter fallbacks) which can
        # resolve company-name → ticker reliably.
        from consensus_engine.analysis.captions_llm_parser import extract_evidence_from_captions
        bundle = await extract_evidence_from_captions(video_id, text, published_at, telemetry)
        if bundle is None:
            return None

        telemetry.chain_winner = "ytdlp-captions/v1"
        return bundle
    except Exception as exc:
        log.debug("F1 captions error for %s: %s", video_id, exc)
        return None
    finally:
        telemetry.chain_durations["ytdlp-captions/v1"] = int((time.monotonic() - t0) * 1000)


async def _stage_gemini(
    video_id: str,
    display_name: str,
    published_at: str,
    telemetry: RunTelemetry,
) -> EvidenceBundle | None:
    t0 = time.monotonic()
    try:
        from consensus_engine.analysis.gemini_video_parser import extract_evidence_with_gemini
        bundle, gem_tel = await extract_evidence_with_gemini(video_id, display_name, published_at)
        # Propagate Gemini telemetry fields
        telemetry.input_tokens += gem_tel.input_tokens
        telemetry.output_tokens += gem_tel.output_tokens
        telemetry.span_count = gem_tel.span_count
        telemetry.filter_drop_count = gem_tel.filter_drop_count
        telemetry.json_parse_ok = gem_tel.json_parse_ok
        # Item G: propagate the Gemini failure category (e.g. "quota") so the chain's
        # returned telemetry carries it. Without this, a quota-exhausted Gemini stage that
        # falls through to a failing whisper stage loses the "quota" signal, and the
        # scanner marks the video 'failed' (burning a retry) instead of 'quota_blocked'
        # (carry over until quota resets). Only set when present so a later success path
        # isn't given a stale category.
        if gem_tel.f2_failure_category:
            telemetry.f2_failure_category = gem_tel.f2_failure_category
        if bundle is not None:
            telemetry.chain_winner = "gemini/v2"
        return bundle
    except Exception as exc:
        log.warning("F2 Gemini error for %s: %s", video_id, exc)
        return None
    finally:
        telemetry.chain_durations["gemini/v2"] = int((time.monotonic() - t0) * 1000)


# ─── REMOVED 2026-06-09 — F3 whisper stage (yt-dlp audio + Groq Whisper) ──────
# Deleted: _stage_whisper, _download_audio, _transcribe_with_groq, _split_audio,
# _transcript_to_bundle. yt-dlp downloads audio from YouTube via our IP, which is
# BLACKLISTED (429 / "confirm you're not a bot"), so this stage NEVER worked from
# this VPS. Groq Whisper itself was fine — it just had no way to get the audio.
# DO NOT re-add a yt-dlp-based path. The only working YouTube transcription path
# from this server is Gemini watching the video directly (F2); Supadata captions
# (F1) are the limited-credit final backup. See TODO #17.
