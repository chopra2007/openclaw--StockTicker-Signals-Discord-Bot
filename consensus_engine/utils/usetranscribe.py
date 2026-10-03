"""Usetranscribe's public API; source transcripts stay separate from AI summaries.

Check the shared cache before creating a job. Keep a local copy of timestamps,
section insights, suggested questions and the permalink. Persist cooldowns so a
service restart cannot repeatedly hit the provider's daily limit.
"""
from __future__ import annotations

import asyncio
import codecs
import json
import logging
import math
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session

log = logging.getLogger(__name__)
BASE = "https://www.usetranscribe.io"
_job_lock: asyncio.Semaphore | None = None
_PERMANENT_ERRORS = {"too_long", "unsupported_url", "auth_required"}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary names also support the catch-up script's parallel callers.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem, suffix=".tmp", delete=False) as f:
        temporary = Path(f.name)
        json.dump(data, f, ensure_ascii=False)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _record(data: dict, video_id: str, streamed: bool = False) -> dict:
    """Normalize the two documented shapes without substituting generated text."""
    if not isinstance(data, dict):
        raise ValueError("invalid transcript object")
    if not streamed and (data.get("external_id") != video_id or data.get("platform") != "youtube"):
        raise ValueError("transcript belongs to another video")
    permalink = data.get("permalink") or f"{BASE}/yt/{video_id}"
    parsed = urlparse(permalink)
    if (parsed.netloc and parsed.netloc != "www.usetranscribe.io") or not re.match(
        rf"^/yt/{re.escape(video_id)}(?:/|$)", parsed.path
    ):
        raise ValueError("invalid transcript permalink")
    transcript = data if streamed else data.get("transcript", {})
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("no transcript segments")
    previous = -1.0
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("invalid transcript segment")
        start, end = segment.get("start"), segment.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (start, end)) or not 0 <= start <= end or start < previous:
            raise ValueError("invalid segment timestamps")
        previous = start
    if not any(s["text"].strip() for s in segments):
        raise ValueError("empty transcript")
    metadata = data.get("metadata", {}) if streamed else data
    return {
        "provider": "usetranscribe", "platform": "youtube", "external_id": video_id,
        "permalink": BASE + permalink if permalink.startswith("/") else permalink,
        "title": metadata.get("title"), "creator": metadata.get("creator"),
        "duration_seconds": metadata.get("duration_seconds"),
        "pipeline_version": data.get("pipeline_version"), "source": data.get("source"),
        "fetched_at": time.time(),
        "transcript": {
            "language": transcript.get("language") or "en", "segments": segments,
            "sections": transcript.get("sections", []),
            "chat_pills": transcript.get("chat_pills", []),
        },
        "summary": data.get("summary_md" if streamed else "summary", ""),
    }


def _text(record: dict, lang: str) -> tuple[str, str, bool] | None:
    transcript = record["transcript"]
    detected = transcript["language"]
    if not isinstance(detected, str) or detected.split("-")[0] != lang.split("-")[0]:
        return None
    # Caption provenance is not always supplied by cached responses. Conservatively
    # mark machine text as automatic, as the existing Supadata adapter does.
    return " ".join(s["text"].strip() for s in transcript["segments"] if s["text"].strip()), detected, True


async def _rate_limit(resp, directory: Path) -> None:
    try:
        data = await resp.json()
    except (ValueError, aiohttp.ContentTypeError):
        data = {}
    scope = data.get("scope", "ip")
    delay = 60 if scope == "ip_concurrent" else 86400
    try:
        delay = max(delay, float(resp.headers.get("Retry-After", "0")))
    except (TypeError, ValueError):
        pass
    _write(directory / "cooldown.json", {"until": time.time() + delay, "scope": scope})
    log.info("Usetranscribe rate limit (%s); new jobs paused for %.0f seconds", scope, delay)


async def _events(resp):
    """Read complete SSE events, including multiline data and final unblanked events."""
    event, data, size, pending = "", [], 0, ""
    decoder = codecs.getincrementaldecoder("utf-8")()
    async for raw in resp.content.iter_chunked(16384):
        size += len(raw)
        if size > 8 * 1024 * 1024:
            raise ValueError("transcript stream exceeds size limit")
        pending += decoder.decode(raw)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if data:
                    yield event, json.loads("\n".join(data))
                event, data = "", []
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
    pending += decoder.decode(b"", final=True)
    if pending:
        line = pending.rstrip("\r")
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, json.loads("\n".join(data))


async def fetch_usetranscribe(video_id: str, lang: str = "en") -> tuple[str, str, bool] | None:
    """Best-effort free transcript source; None lets Supadata take over."""
    if not cfg.get("youtube.usetranscribe.enabled", False):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    directory = Path(cfg.get("youtube.usetranscribe.cache_dir", "artifacts/transcripts/usetranscribe"))
    try:
        return await _fetch(video_id, lang, directory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("Usetranscribe unavailable for %s: %s", video_id, exc)
        return None


def get_cached_permalink(video_id: str) -> str | None:
    """Link to the archived provider features without another network request."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    directory = Path(cfg.get("youtube.usetranscribe.cache_dir", "artifacts/transcripts/usetranscribe"))
    try:
        return _record(_read(directory / f"{video_id}.json"), video_id)["permalink"]
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


async def _fetch(video_id: str, lang: str, directory: Path) -> tuple[str, str, bool] | None:
    local = _read(directory / f"{video_id}.json")
    if local:
        try:
            result = _text(_record(local, video_id), lang)
            if result:
                return result
        except (ValueError, TypeError, KeyError, AttributeError):
            pass  # a bad local file must not disable the remaining sources
    session = await get_session()
    headers = {"User-Agent": "OpenClaw-YouTube/1.0"}
    async with session.get(BASE + "/api/check", params={"platform": "youtube", "id": video_id},
                           headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status == 429:
            await _rate_limit(resp, directory)
            return None
        if resp.status != 200:
            return None
        cached = (await resp.json()).get("cached") is True
    if cached:
        # Fixed URL: never follow a URL suggested inside an untrusted payload.
        async with session.get(f"{BASE}/yt/{video_id}", params={"format": "json"},
                               headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 429:
                await _rate_limit(resp, directory)
                return None
            if resp.status != 200:
                return None
            record = _record(await resp.json(), video_id)
    else:
        record = await _transcribe(session, headers, video_id, lang, directory)
        if record is None:
            return None
    result = _text(record, lang)
    if result:
        _write(directory / f"{video_id}.json", record)
        log.info("Usetranscribe transcript saved for %s (%d chars)", video_id, len(result[0]))
    return result


async def _transcribe(session, headers: dict, video_id: str, lang: str, directory: Path) -> dict | None:
    if not _can_start(video_id, lang, directory):
        return None
    global _job_lock
    if _job_lock is None:
        _job_lock = asyncio.Semaphore(1)  # below the provider's two-job cap
    async with _job_lock:
        # A queued caller may already have been satisfied by the preceding job.
        local = _read(directory / f"{video_id}.json")
        if local:
            try:
                record = _record(local, video_id)
                if _text(record, lang):
                    return record
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
        if not _can_start(video_id, lang, directory):
            return None
        timeout = min(600, max(30, float(cfg.get("youtube.usetranscribe.timeout_seconds", 360))))
        async with session.get(BASE + "/transcribe", params={
            "url": f"https://www.youtube.com/watch?v={video_id}", "summarize": "1",
        }, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 429:
                await _rate_limit(resp, directory)
                return None
            if resp.status != 200:
                return None
            record = None
            async for event, data in _events(resp):
                if event == "done":
                    record = _record(data, video_id, streamed=True)
                    break
                if event == "error":
                    code = data.get("code", "unknown")
                    if code in _PERMANENT_ERRORS:
                        _write(directory / f"{video_id}.failure.json", {"code": code})
                    else:
                        state = _read(directory / "cooldown.json")
                        delay = min(900, max(30, state.get("transient_delay", 15) * 2))
                        _write(directory / "cooldown.json", {"until": time.time() + delay, "transient_delay": delay})
                    log.warning("Usetranscribe job failed for %s: %s", video_id, code)
                    return None
            if record is None:
                return None
            # Publish inside the lock so the next waiting caller can reuse it.
            if _text(record, lang):
                _write(directory / f"{video_id}.json", record)
            return record


def _can_start(video_id: str, lang: str, directory: Path) -> bool:
    # Read before and after queueing: cooldown/permanent failures must not wait
    # behind someone else's slow job, and another caller can change the state.
    return (
        lang.split("-")[0] == "en"
        and _read(directory / "cooldown.json").get("until", 0) <= time.time()
        and _read(directory / f"{video_id}.failure.json").get("code") not in _PERMANENT_ERRORS
    )
