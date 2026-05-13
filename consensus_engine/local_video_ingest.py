"""F2-F3-F1-F4 multi-method YouTube evidence chain.

Sequential gating: F1 (captions, disabled) → F2 (Gemini) → F3 (yt-dlp + Groq Whisper, load-bearing) → F4 (FFmpeg frames, disabled).
Short-circuits on first viable bundle. F6 hygiene runs at entry and in finally:.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from pathlib import Path

from consensus_engine.models import EvidenceBundle, EvidenceSpan, RunTelemetry
from consensus_engine.hygiene.disk_inode_sweep import pre_flight_check, cleanup_run_workspace

log = logging.getLogger("consensus_engine.local_video_ingest")

_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")

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
    """F1: fetch auto-captions via yt-dlp. Returns None when disabled or unavailable."""
    from consensus_engine.config import get as cfg
    if not cfg("youtube.captions.enabled", False):
        return None
    # Phase 3: BGUtil POT-backed caption fetch goes here.
    return None


async def fetch_audio_transcript(video_id: str, run_dir: str) -> str | None:
    """F3: download audio with yt-dlp and transcribe with Groq Whisper."""
    audio_path = await _download_audio(video_id, run_dir)
    if audio_path is None:
        return None
    return await _transcribe_with_groq(audio_path, run_dir)


async def extract_frames(video_id: str, mode: str = "scene-change") -> list:
    """F4: extract scene frames with FFmpeg. Returns [] when disabled."""
    from consensus_engine.config import get as cfg
    if not cfg("youtube.vision.enabled", False):
        return []
    # Phase 2: FFmpeg scene-change extraction goes here.
    return []


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

        # F1: captions (disabled Phase 1)
        if cfg("youtube.captions.enabled", False):
            telemetry.chain_attempts.append("ytdlp-captions/v1")
            bundle = await _stage_captions(video_id, telemetry)
            if bundle is not None:
                return bundle, telemetry

        # F2: Gemini Part.from_uri (existing path)
        telemetry.chain_attempts.append("gemini/v2")
        bundle = await _stage_gemini(video_id, display_name, published_at, telemetry)
        if bundle is not None:
            return bundle, telemetry

        # F3: yt-dlp audio + Groq Whisper (load-bearing)
        if cfg("youtube.whisper.enabled", True):
            telemetry.chain_attempts.append("whisper-groq/v1")
            bundle = await _stage_whisper(video_id, display_name, published_at, run_id, telemetry)
            if bundle is not None:
                return bundle, telemetry

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
) -> EvidenceBundle | None:
    t0 = time.monotonic()
    try:
        text = await fetch_captions(video_id)
        if text is None:
            return None
        bundle = _transcript_to_bundle(video_id, "", text, [])
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
        if bundle is not None:
            telemetry.chain_winner = "gemini/v2"
        return bundle
    except Exception as exc:
        log.warning("F2 Gemini error for %s: %s", video_id, exc)
        return None
    finally:
        telemetry.chain_durations["gemini/v2"] = int((time.monotonic() - t0) * 1000)


async def _stage_whisper(
    video_id: str,
    display_name: str,
    published_at: str,
    run_id: str,
    telemetry: RunTelemetry,
) -> EvidenceBundle | None:
    t0 = time.monotonic()
    from consensus_engine.config import get as cfg
    workspace = cfg("youtube.hygiene.workspace_root", "/var/tmp/video-fallback")
    run_dir = os.path.join(workspace, run_id)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    try:
        transcript = await fetch_audio_transcript(video_id, run_dir)
        if transcript is None:
            return None

        from consensus_engine.analysis.hallucination_grounding import (
            ground_transcript_tickers, all_ungrounded,
        )
        raw_tickers = list(dict.fromkeys(_TICKER_RE.findall(transcript)))
        grounded_results = ground_transcript_tickers(raw_tickers, transcript)
        telemetry.hallucinated_ticker_count = sum(
            1 for r in grounded_results if r["grounding_status"] == "ungrounded"
        )

        if raw_tickers and all_ungrounded(grounded_results):
            log.warning(
                "F3 grounding rejected all %d tickers for %s — terminal failure",
                len(raw_tickers), video_id,
            )
            return None

        grounded_tickers = [r["ticker"] for r in grounded_results if r["grounding_status"] == "grounded"]
        bundle = _transcript_to_bundle(video_id, published_at, transcript, grounded_tickers)
        telemetry.chain_winner = "whisper-groq/v1"
        telemetry.span_count = len(bundle.spans)
        log.info(
            "F3 Whisper succeeded for %s: %d spans, tickers=%s",
            video_id, len(bundle.spans), grounded_tickers,
        )
        return bundle

    except Exception as exc:
        log.warning("F3 Whisper terminal failure for %s: %s", video_id, exc)
        return None
    finally:
        telemetry.chain_durations["whisper-groq/v1"] = int((time.monotonic() - t0) * 1000)


# ─── Audio download + transcription ──────────────────────────────────────────

async def _download_audio(video_id: str, run_dir: str) -> str | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_template = os.path.join(run_dir, "audio.%(ext)s")
    cmd = [
        "yt-dlp", "--",
        url,
        "-x", "--audio-format", "mp3", "--audio-quality", "5",
        "-o", out_template,
        "--no-playlist", "--quiet",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            log.warning("yt-dlp failed for %s: %s", video_id, stderr.decode(errors="replace")[:300])
            return None
    except asyncio.TimeoutError:
        log.warning("yt-dlp timed out for %s", video_id)
        return None
    except Exception as exc:
        log.warning("yt-dlp error for %s: %s", video_id, exc)
        return None

    for ext in ("mp3", "m4a", "opus", "webm", "ogg"):
        candidate = os.path.join(run_dir, f"audio.{ext}")
        if os.path.exists(candidate):
            return candidate
    log.warning("yt-dlp: no audio file found in %s for %s", run_dir, video_id)
    return None


async def _transcribe_with_groq(audio_path: str, run_dir: str) -> str | None:
    """Transcribe audio file via Groq Whisper. Splits files > 24MB."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.error("GROQ_API_KEY not set — F3 unavailable")
        return None

    try:
        import groq as _groq
    except ImportError:
        log.error("groq package not installed — F3 unavailable")
        return None

    max_mb = 24
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    chunks = await _split_audio(audio_path, run_dir) if file_size_mb > max_mb else [audio_path]

    client = _groq.Groq(api_key=api_key)
    parts: list[str] = []
    for chunk_path in chunks:
        try:
            with open(chunk_path, "rb") as f:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda _f=f: client.audio.transcriptions.create(
                        model="whisper-large-v3",
                        file=_f,
                        response_format="text",
                        prompt="Finance: tickers like $SPY $NVDA $AAPL $TSLA $QQQ $BTC",
                    ),
                )
            parts.append(str(result))
        except _groq.RateLimitError as exc:
            log.warning("Groq 429 for chunk %s: %s", chunk_path, exc)
            return None
        except Exception as exc:
            log.warning("Groq transcription error for %s: %s", chunk_path, exc)
            return None

    return " ".join(parts) if parts else None


async def _split_audio(audio_path: str, run_dir: str, chunk_sec: int = 600) -> list[str]:
    """Split audio into ~10-min chunks using ffmpeg. Returns chunk paths."""
    pattern = os.path.join(run_dir, "chunk%03d.mp3")
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-f", "segment", "-segment_time", str(chunk_sec),
        "-c", "copy", pattern,
        "-y", "-loglevel", "error",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
    except Exception as exc:
        log.warning("ffmpeg split failed: %s — using full file", exc)
        return [audio_path]

    chunks = sorted(str(p) for p in Path(run_dir).glob("chunk*.mp3") if p.stat().st_size > 0)
    return chunks if chunks else [audio_path]


# ─── Bundle builder ───────────────────────────────────────────────────────────

def _transcript_to_bundle(
    video_id: str,
    published_at: str,
    transcript: str,
    grounded_tickers: list[str],
) -> EvidenceBundle:
    """Convert a flat transcript string into an EvidenceBundle with word-chunk spans."""
    words = transcript.split()
    chunk_size = 80
    spans: list[EvidenceSpan] = []
    ts_sec = 0
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if not chunk.strip():
            continue
        tickers_here = [t for t in grounded_tickers if f"${t}" in chunk or re.search(rf"\b{re.escape(t)}\b", chunk)]
        spans.append(EvidenceSpan(ts_sec=ts_sec, quote=chunk[:500], tickers=tickers_here))
        ts_sec += 30

    return EvidenceBundle(
        video_id=video_id,
        duration_sec=ts_sec,
        publish_ts=published_at,
        segments=[{"text": transcript[:5000]}],
        spans=spans,
    )
