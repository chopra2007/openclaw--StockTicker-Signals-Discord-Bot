"""One-shot catch-up: fetch + transcribe the latest video from every followed channel.

Bypasses the normal dedup check so newly-added channels are processed even if
a video was previously seen. Existing transcripts are not overwritten (export
uses the video_id as filename, so a re-run is safe).

Usage:
    python3 scripts/catchup_transcripts.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import json
import logging
import time

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("catchup_transcripts")

SOURCES_PATH = "/root/.openclaw/sources.json"
EXPORT_DIR = "artifacts/transcripts"
PREFERRED_LANGS = ["en"]
RSS_TIMEOUT = 15
CONCURRENCY = 3  # browser slots — keep low to avoid memory pressure


def load_channels() -> list[dict]:
    with open(SOURCES_PATH) as f:
        data = json.load(f)
    return data.get("youtube_channels", [])


async def fetch_latest_video(
    session: aiohttp.ClientSession, channel: dict
) -> dict | None:
    """Return metadata for the single most recent video on the channel RSS feed."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    ATOM_NS = "http://www.w3.org/2005/Atom"
    YT_NS = "http://www.youtube.com/xml/schemas/2015"

    channel_id = channel["channel_id"]
    display_name = channel["display_name"]
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=RSS_TIMEOUT)) as resp:
            if resp.status != 200:
                log.warning("RSS %d for %s (%s)", resp.status, display_name, channel_id)
                return None
            text = await resp.text()
    except Exception as e:
        log.warning("RSS error for %s: %s", display_name, e)
        return None

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.warning("RSS parse error for %s: %s", display_name, e)
        return None

    entry = root.find(f"{{{ATOM_NS}}}entry")
    if entry is None:
        log.warning("No entries in RSS for %s", display_name)
        return None

    video_id_el = entry.find(f"{{{YT_NS}}}videoId")
    title_el = entry.find(f"{{{ATOM_NS}}}title")
    published_el = entry.find(f"{{{ATOM_NS}}}published")

    if video_id_el is None:
        return None

    return {
        "video_id": video_id_el.text or "",
        "channel_id": channel_id,
        "display_name": display_name,
        "title": (title_el.text or "") if title_el is not None else "",
        "published_at": (published_el.text or "") if published_el is not None else "",
    }


async def transcribe_video(video: dict, semaphore: asyncio.Semaphore) -> bool:
    """Fetch transcript + export JSON. Returns True on success."""
    from consensus_engine.utils.transcript_fetch import fetch_transcript_cascade
    from consensus_engine.utils.transcript_export import compute_hash, export_transcript_json

    video_id = video["video_id"]
    display_name = video["display_name"]

    async with semaphore:
        log.info("Transcribing: [%s] %s  (%s)", display_name, video["title"], video_id)
        try:
            text, lang, is_auto = await fetch_transcript_cascade(video_id, PREFERRED_LANGS)
        except ValueError as e:
            log.warning("No transcript for %s/%s: %s", display_name, video_id, e)
            return False
        except Exception as e:
            log.error("Transcript error for %s/%s: %s", display_name, video_id, e)
            return False

        try:
            path = export_transcript_json(
                channel_id=video["channel_id"],
                video_id=video_id,
                title=video["title"],
                published_at=video["published_at"],
                language=lang,
                is_auto_generated=is_auto,
                transcript_text=text,
                export_dir=EXPORT_DIR,
            )
        except Exception as e:
            log.error("Export error for %s/%s: %s", display_name, video_id, e)
            return False

        log.info(
            "  Saved: %s  (%s, auto=%s, %d chars)",
            path, lang, is_auto, len(text),
        )
        return True


async def main():
    channels = load_channels()
    if not channels:
        log.error("No channels found in %s", SOURCES_PATH)
        return

    log.info("Loaded %d channels from sources.json", len(channels))

    headers = {"User-Agent": "OpenClaw/1.0 (catchup-transcripts)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        log.info("Fetching latest video from each channel via RSS...")
        rss_tasks = [fetch_latest_video(session, ch) for ch in channels]
        videos = await asyncio.gather(*rss_tasks)

    videos = [v for v in videos if v]
    log.info("Found %d videos to transcribe", len(videos))

    for v in videos:
        log.info("  [%s] %s  →  %s", v["display_name"], v["title"], v["video_id"])

    semaphore = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    results = await asyncio.gather(*[transcribe_video(v, semaphore) for v in videos])

    ok = sum(results)
    fail = len(results) - ok
    elapsed = time.time() - t0
    log.info(
        "Done in %.1fs — %d transcribed, %d failed/no-captions",
        elapsed, ok, fail,
    )

    if fail:
        log.info("Failed channels:")
        for v, r in zip(videos, results):
            if not r:
                log.info("  [%s] %s", v["display_name"], v["video_id"])


if __name__ == "__main__":
    asyncio.run(main())
