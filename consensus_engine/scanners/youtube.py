"""YouTube transcript scanner.

Polls configured channel IDs via free YouTube RSS feeds, extracts auto-generated
captions via youtube-transcript-api (no API key required), and persists transcripts
to DB + JSON export files.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import aiohttp

from consensus_engine import config as cfg, db
from consensus_engine.utils.transcript_export import compute_hash, export_transcript_json

log = logging.getLogger("consensus_engine.scanner.youtube")

_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yt-transcript")


async def fetch_channel_videos_rss(
    session: aiohttp.ClientSession,
    channel_id: str,
    limit: int = 3,
) -> list[dict]:
    """Fetch latest video metadata from YouTube Atom RSS feed.

    Returns list of dicts with keys: video_id, channel_id, title, published_at.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("youtube: RSS %s returned HTTP %d", channel_id, resp.status)
                return []
            text = await resp.text()
    except Exception as e:
        log.warning("youtube: RSS fetch error for %s: %s", channel_id, e)
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.warning("youtube: RSS parse error for %s: %s", channel_id, e)
        return []

    videos = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        video_id_el = entry.find(f"{{{_YT_NS}}}videoId")
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        published_el = entry.find(f"{{{_ATOM_NS}}}published")
        if video_id_el is None:
            continue
        videos.append({
            "video_id": video_id_el.text or "",
            "channel_id": channel_id,
            "title": (title_el.text or "") if title_el is not None else "",
            "published_at": (published_el.text or "") if published_el is not None else "",
        })
        if len(videos) >= limit:
            break

    return videos


def _make_api():
    """Build a YouTubeTranscriptApi instance, optionally with cookie auth."""
    from youtube_transcript_api import YouTubeTranscriptApi
    import requests
    from http.cookiejar import MozillaCookieJar

    cookies_file = cfg.get("youtube.cookies_file", "")
    if cookies_file:
        jar = MozillaCookieJar(cookies_file)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
            session = requests.Session()
            session.cookies = jar
            log.debug("youtube: using cookies from %s", cookies_file)
            return YouTubeTranscriptApi(http_client=session)
        except Exception as e:
            log.warning("youtube: failed to load cookies from %s: %s — falling back to unauthenticated", cookies_file, e)

    return YouTubeTranscriptApi()


def _fetch_transcript_sync(video_id: str, preferred_languages: list[str]) -> tuple[str, str, bool]:
    """Blocking call to youtube-transcript-api v1.x. Returns (text, language, is_auto)."""
    api = _make_api()
    transcript_list = api.list(video_id)

    # Try preferred languages; fall back to any available transcript
    transcript = None
    try:
        transcript = transcript_list.find_transcript(preferred_languages)
    except Exception:
        for t in transcript_list:
            transcript = t
            break

    if transcript is None:
        raise ValueError(f"No transcript available for {video_id}")

    is_auto = getattr(transcript, "is_generated", True)
    lang = getattr(transcript, "language_code", "unknown")

    fetched = transcript.fetch()
    parts = []
    for seg in fetched:
        if hasattr(seg, "text"):
            parts.append(seg.text)
        elif isinstance(seg, dict):
            parts.append(seg.get("text", ""))
    text = " ".join(parts).strip()
    return text, lang, is_auto


async def fetch_transcript(
    video_id: str,
    preferred_languages: list[str],
) -> tuple[str, str, bool]:
    """Async wrapper around the blocking transcript fetch. Returns (text, lang, is_auto)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _fetch_transcript_sync,
        video_id,
        preferred_languages,
    )


async def process_video(
    video_meta: dict,
    semaphore: asyncio.Semaphore,
    preferred_languages: list[str],
    export_dir: str,
) -> None:
    """Process one video: dedup → fetch transcript → save to DB + export JSON."""
    async with semaphore:
        video_id = video_meta["video_id"]
        channel_id = video_meta["channel_id"]

        if await db.has_video_been_processed(video_id):
            log.debug("youtube: skipping already-processed %s", video_id)
            return

        await db.upsert_youtube_video(
            video_id=video_id,
            channel_id=channel_id,
            title=video_meta["title"],
            published_at=video_meta["published_at"],
            fetched_at=time.time(),
        )

        try:
            text, lang, is_auto = await fetch_transcript(video_id, preferred_languages)
        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ("disabled", "no transcript", "no captions", "not available")):
                log.info("youtube: no captions for %s (%s)", video_id, e)
                await db.mark_youtube_video_status(video_id, "missing")
            else:
                log.warning("youtube: transcript fetch failed for %s: %s", video_id, e)
                await db.mark_youtube_video_status(video_id, "failed")
            return

        h = compute_hash(text)

        try:
            path = export_transcript_json(
                channel_id=channel_id,
                video_id=video_id,
                title=video_meta["title"],
                published_at=video_meta["published_at"],
                language=lang,
                is_auto_generated=is_auto,
                transcript_text=text,
                export_dir=export_dir,
            )
        except Exception as e:
            log.error("youtube: export failed for %s: %s", video_id, e)
            await db.mark_youtube_video_status(video_id, "failed")
            return

        await db.save_youtube_transcript(video_id, text, h)
        await db.mark_youtube_video_status(
            video_id, "saved",
            language=lang,
            is_auto_generated=is_auto,
            export_path=path,
        )
        log.info(
            "youtube: saved transcript for %s (%s, auto=%s, %d chars) → %s",
            video_id, lang, is_auto, len(text), path,
        )


async def youtube_scan_once() -> None:
    """One full poll cycle: discover new videos across all configured channels."""
    channel_ids = cfg.get("youtube.channel_ids", [])
    if not channel_ids:
        log.debug("youtube: no channel_ids configured, skipping")
        return

    limit = cfg.get("youtube.max_videos_per_channel", 3)
    concurrency = cfg.get("youtube.max_concurrency", 4)
    export_dir = cfg.get("youtube.export_dir", "artifacts/transcripts")
    preferred_languages = cfg.get("youtube.preferred_languages", ["en"])

    semaphore = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": "OpenClaw/1.0 (youtube-transcript-scanner)"}

    async with aiohttp.ClientSession(headers=headers) as session:
        all_videos: list[dict] = []
        for channel_id in channel_ids:
            try:
                videos = await fetch_channel_videos_rss(session, channel_id, limit)
                log.debug("youtube: channel %s → %d videos", channel_id, len(videos))
                all_videos.extend(videos)
            except Exception as e:
                log.warning("youtube: channel %s error: %s", channel_id, e)

    if not all_videos:
        return

    await asyncio.gather(*[
        process_video(v, semaphore, preferred_languages, export_dir)
        for v in all_videos
    ])


async def youtube_poll_loop(stop_event: asyncio.Event) -> None:
    """Background loop — runs youtube_scan_once() every poll_interval_seconds."""
    if not cfg.get("youtube.enabled", False):
        log.debug("youtube: disabled, poll loop not started")
        return

    interval = cfg.get("youtube.poll_interval_seconds", 600)
    log.info("youtube: poll loop started (interval=%ds, channels=%s)",
             interval, cfg.get("youtube.channel_ids", []))

    while not stop_event.is_set():
        try:
            await youtube_scan_once()
        except Exception as e:
            log.error("youtube: scan cycle error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
