"""Multi-tier YouTube transcript fetcher.

Cascade (all free, works from datacenter IPs):
  1. Supadata API  — 100 free credits/month, most reliable
  2. Invidious API — public instances, no key, failover across multiple
  3. youtube-transcript-api — direct library call
  4. Playwright stealth — existing browser-based fallback

Each tier is tried in order; first success wins.
"""

import asyncio
import html as html_module
import logging
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs

import aiohttp

from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.utils.transcript_fetch")

# Public Invidious instances with API access (tried in order)
_INVIDIOUS_INSTANCES = [
    "https://inv.thepixora.com",
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
]


def parse_video_id(url: str) -> str | None:
    """Extract video ID from any YouTube URL format."""
    u = urlparse(url)
    host = u.netloc.lower().replace("www.", "")
    path = u.path.strip("/")

    if "youtu.be" in host:
        return path.split("/")[0].split("?")[0] or None
    if "youtube.com" in host:
        if path.startswith("shorts/"):
            return path.split("/", 1)[1].split("?")[0] or None
        if path.startswith("embed/"):
            return path.split("/", 1)[1].split("?")[0] or None
        if path in ("watch", "watch/"):
            v = parse_qs(u.query).get("v", [""])[0]
            return v or None
    return None


def _vtt_to_text(vtt: str) -> str:
    """Convert WebVTT subtitle content to plain text."""
    lines = []
    seen = set()
    for raw in vtt.splitlines():
        line = raw.strip()
        # Skip VTT headers, timestamps, sequence numbers
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        # Strip VTT tags like <c> </c> <00:01:02.345>
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if not clean:
            continue
        # Deduplicate repeated lines (common in auto-generated subs)
        if clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return " ".join(lines).strip()


# ---------------------------------------------------------------------------
# Tier 1: Supadata API
# ---------------------------------------------------------------------------

async def _fetch_via_supadata(video_id: str, lang: str = "en") -> tuple[str, str, bool] | None:
    """Fetch transcript via Supadata free API (100 credits/month)."""
    api_key = os.environ.get("SUPADATA_API_KEY", "")
    if not api_key:
        log.debug("transcript: Supadata API key not configured, skipping")
        return None

    url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&lang={lang}"
    try:
        session = await get_session()
        async with session.get(
            url,
            headers={"x-api-key": api_key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.debug("transcript: Supadata returned HTTP %d for %s", resp.status, video_id)
                return None
            data = await resp.json()

        content = data.get("content")
        if not content:
            log.debug("transcript: Supadata returned empty content for %s", video_id)
            return None

        # content is a list of segments with text/offset/duration
        if isinstance(content, list):
            text = " ".join(seg.get("text", "") for seg in content).strip()
        else:
            text = str(content).strip()

        if not text:
            return None

        detected_lang = data.get("lang", lang)
        log.info("transcript: Supadata success for %s (%d chars)", video_id, len(text))
        return text, detected_lang, True  # Supadata doesn't distinguish auto vs manual

    except Exception as e:
        log.debug("transcript: Supadata error for %s: %s", video_id, e)
        return None


# ---------------------------------------------------------------------------
# Tier 2: Invidious API
# ---------------------------------------------------------------------------

async def _fetch_via_invidious(video_id: str, lang: str = "en") -> tuple[str, str, bool] | None:
    """Try multiple Invidious instances for captions."""
    session = await get_session()

    for instance in _INVIDIOUS_INSTANCES:
        try:
            # Step 1: Get available caption tracks
            captions_url = f"{instance}/api/v1/captions/{video_id}"
            async with session.get(
                captions_url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()

            tracks = data.get("captions", [])
            if not tracks:
                log.debug("transcript: Invidious %s has no captions for %s", instance, video_id)
                continue

            # Pick best track: prefer requested lang, then any
            track = None
            for t in tracks:
                if t.get("languageCode", "").startswith(lang):
                    track = t
                    break
            if not track:
                track = tracks[0]

            label = track.get("label", "")
            lang_code = track.get("languageCode", "unknown")

            # Step 2: Fetch the actual caption content (VTT format)
            caption_url = f"{instance}/api/v1/captions/{video_id}?label={label}"
            async with session.get(
                caption_url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    continue
                vtt_text = await resp.text()

            text = _vtt_to_text(vtt_text)
            if not text:
                continue

            is_auto = "auto" in label.lower()
            log.info(
                "transcript: Invidious (%s) success for %s (%d chars)",
                instance, video_id, len(text),
            )
            return text, lang_code, is_auto

        except Exception as e:
            log.debug("transcript: Invidious %s error for %s: %s", instance, video_id, e)
            continue

    return None


# ---------------------------------------------------------------------------
# Tier 3: youtube-transcript-api library
# ---------------------------------------------------------------------------

async def _fetch_via_yt_transcript_api(
    video_id: str, lang: str = "en",
) -> tuple[str, str, bool] | None:
    """Fetch via youtube-transcript-api (direct to YouTube, may be blocked)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        log.debug("transcript: youtube-transcript-api not installed, skipping")
        return None

    def _sync_fetch():
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=[lang, "en"])
        parts = [snippet.text for snippet in transcript.snippets]
        text = " ".join(parts).strip()
        detected_lang = transcript.language
        is_auto = transcript.is_generated
        return text, detected_lang, is_auto

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _sync_fetch)
        if result and result[0]:
            log.info("transcript: yt-transcript-api success for %s (%d chars)", video_id, len(result[0]))
            return result
        return None
    except Exception as e:
        log.debug("transcript: yt-transcript-api error for %s: %s", video_id, e)
        return None


# ---------------------------------------------------------------------------
# Tier 4: Playwright stealth (existing browser path)
# ---------------------------------------------------------------------------

async def _fetch_via_playwright(
    video_id: str, preferred_languages: list[str],
) -> tuple[str, str, bool] | None:
    """Fetch via Playwright stealth browser (existing path)."""
    try:
        from consensus_engine.scanners.youtube import fetch_transcript
        text, lang, is_auto = await fetch_transcript(video_id, preferred_languages)
        if text:
            log.info("transcript: Playwright success for %s (%d chars)", video_id, len(text))
            return text, lang, is_auto
        return None
    except Exception as e:
        log.debug("transcript: Playwright error for %s: %s", video_id, e)
        return None


# ---------------------------------------------------------------------------
# Public API: cascade fetch
# ---------------------------------------------------------------------------

async def fetch_transcript_cascade(
    video_id: str,
    preferred_languages: list[str] | None = None,
) -> tuple[str, str, bool]:
    """Fetch transcript using multi-tier cascade. Raises ValueError on total failure.

    Returns (transcript_text, language_code, is_auto_generated).
    """
    if preferred_languages is None:
        preferred_languages = ["en"]
    lang = preferred_languages[0] if preferred_languages else "en"

    # Each entry is (name, callable, timeout_seconds).
    # Callables are used (not pre-created coroutines) so we only invoke
    # the next tier if all previous ones failed.
    tiers: list[tuple[str, object, int]] = [
        ("Supadata", lambda: _fetch_via_supadata(video_id, lang), 20),
        ("Invidious", lambda: _fetch_via_invidious(video_id, lang), 30),
        ("yt-transcript-api", lambda: _fetch_via_yt_transcript_api(video_id, lang), 20),
        ("Playwright", lambda: _fetch_via_playwright(video_id, preferred_languages), 45),
    ]

    for name, factory, timeout in tiers:
        try:
            log.debug("transcript: trying %s for %s", name, video_id)
            result = await asyncio.wait_for(factory(), timeout=timeout)
            if result and result[0]:
                return result
        except asyncio.TimeoutError:
            log.debug("transcript: tier %s timed out for %s", name, video_id)
        except Exception as e:
            log.debug("transcript: tier %s failed for %s: %s", name, video_id, e)

    raise ValueError(
        f"All transcript sources failed for {video_id}. "
        "The video may have no captions, or all services are unavailable."
    )
