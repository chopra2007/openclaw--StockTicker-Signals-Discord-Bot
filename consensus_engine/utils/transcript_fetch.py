"""YouTube transcript fetcher — Supadata only.

From this VPS, Supadata (paid managed API, fetches via its own residential network)
is the ONLY caption source that works. The free-tier direct sources that used to be
in this cascade — Invidious-captions, youtube-transcript-api, Playwright — were all
REMOVED 2026-06-09 because YouTube has blacklisted this server's IP and never served
them captions. DO NOT re-add them (see the REMOVED note further down, and TODO #17).
Supadata's free plan has limited monthly credits, so it is a final backup, not a
first choice — the primary YouTube path is Gemini watching the video directly.

`fetch_youtube_duration` still uses the Invidious mirrors — but only for video
LENGTH (metadata), which they DO still serve. That is unrelated to captions.
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

# All configured Supadata keys, in slot order. Round-robin pointer spreads
# traffic across every key so the limited monthly credits split evenly; on a
# 429 (plan limit) we fail over to the next key in the rotation.
_SUPADATA_KEY_ENV_NAMES = ("SUPADATA_API_KEY", "SUPADATA_API_KEY2", "SUPADATA_API_KEY3")
_supadata_rotation_idx = 0

# Public Invidious mirrors — used ONLY by fetch_youtube_duration for video LENGTH
# (metadata still works). NOT for captions (YouTube stopped serving caption tracks
# to Invidious — see the REMOVED note below). Tried in order.
_INVIDIOUS_INSTANCES = [
    "https://inv.thepixora.com",
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
]


def _valid_vid(raw: str) -> str | None:
    """Return raw if it is a valid 11-char YouTube video ID, else None."""
    return raw if raw and re.fullmatch(r"[A-Za-z0-9_-]{11}", raw) else None


def parse_video_id(url: str) -> str | None:
    """Extract video ID from any YouTube URL format."""
    u = urlparse(url)
    host = u.netloc.lower().replace("www.", "")
    path = u.path.strip("/")

    if "youtu.be" in host:
        return _valid_vid(path.split("/")[0].split("?")[0])
    if "youtube.com" in host:
        if path.startswith("shorts/"):
            return _valid_vid(path.split("/", 1)[1].split("?")[0])
        if path.startswith("embed/"):
            return _valid_vid(path.split("/", 1)[1].split("?")[0])
        if path in ("watch", "watch/"):
            v = parse_qs(u.query).get("v", [""])[0]
            return _valid_vid(v)
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
    """Fetch transcript via Supadata API. Round-robins across every configured
    key (SUPADATA_API_KEY / _KEY2 / _KEY3) to split monthly credits, then fails
    over to the remaining keys on a 429 (plan limit)."""
    all_keys = [
        (name, os.environ.get(name, ""))
        for name in _SUPADATA_KEY_ENV_NAMES
    ]
    all_keys = [(name, k) for name, k in all_keys if k]
    if not all_keys:
        log.debug("transcript: no Supadata API key in env, skipping")
        return None

    global _supadata_rotation_idx
    n = len(all_keys)
    start = _supadata_rotation_idx % n
    _supadata_rotation_idx += 1
    keys = [all_keys[(start + i) % n] for i in range(n)]

    url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&lang={lang}"
    session = await get_session()

    for name, api_key in keys:
        try:
            async with session.get(
                url,
                headers={"x-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 429:
                    log.info("transcript: Supadata %s rate/plan-limited for %s, trying next key", name, video_id)
                    continue
                if resp.status != 200:
                    log.debug("transcript: Supadata %s HTTP %d for %s", name, resp.status, video_id)
                    return None
                data = await resp.json()
        except Exception as e:
            log.debug("transcript: Supadata %s error for %s: %s", name, video_id, e)
            continue

        content = data.get("content")
        if not content:
            log.debug("transcript: Supadata %s empty content for %s", name, video_id)
            return None

        # content is a list of segments with text/offset/duration
        if isinstance(content, list):
            text = " ".join(seg.get("text", "") for seg in content).strip()
        else:
            text = str(content).strip()

        if not text:
            return None

        detected_lang = data.get("lang", lang)
        log.info("transcript: Supadata success via %s for %s (%d chars)", name, video_id, len(text))
        return text, detected_lang, True  # Supadata doesn't distinguish auto vs manual

    return None


# ---------------------------------------------------------------------------
# REMOVED 2026-06-09 — DO NOT RE-ADD these caption sources. They never worked
# from this VPS and only wasted time/log-noise on every video:
#   • Invidious captions (`_fetch_via_invidious`): the public mirrors reach YouTube
#     for video METADATA (that's why fetch_youtube_duration below still works) but
#     YouTube no longer serves the caption/subtitle track to Invidious instances —
#     the captions endpoint returns `{"captions":[]}` (live-confirmed 2026-06-09),
#     or the instance's API is 403/disabled. Empty since day one.
#   • youtube-transcript-api (`_fetch_via_yt_transcript_api`): hits YouTube directly
#     from our IP, which YouTube has BLACKLISTED (IpBlocked / "confirm you're not a
#     bot"). Cookies don't help — it's the datacenter IP, not auth.
# Supadata is the ONLY caption source that works here (it fetches via its own
# residential network), so it is the sole remaining tier. See TODO #17.
# ---------------------------------------------------------------------------


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

    # Supadata is the ONLY working caption source from this VPS (see the REMOVED
    # note above — Invidious-captions + youtube-transcript-api are dead on our
    # blacklisted IP). It's the paid managed API (limited free credits), so treat it
    # as the final backup, not a first choice.
    tiers: list[tuple[str, object, int]] = [
        ("Supadata", lambda: _fetch_via_supadata(video_id, lang), 20),
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


async def fetch_youtube_duration(video_id: str) -> int | None:
    """Return a video's true length in seconds via an Invidious mirror, or None.

    YouTube blocks this datacenter IP directly (HTTP 429 / "confirm you're not a bot"),
    so the public Invidious instances are the working source here. Best-effort: the first
    instance that answers wins; all-failed returns None (caller skips the coverage check).
    """
    session = await get_session()
    for instance in _INVIDIOUS_INSTANCES:
        try:
            async with session.get(
                f"{instance}/api/v1/videos/{video_id}?fields=lengthSeconds",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    continue
                length = (await resp.json()).get("lengthSeconds")
            if isinstance(length, int) and length > 0:
                return length
        except Exception as e:
            log.debug("duration: Invidious %s failed for %s: %s", instance, video_id, e)
    return None
