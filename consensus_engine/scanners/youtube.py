"""YouTube transcript scanner.

Polls configured channel IDs via free YouTube RSS feeds, then extracts
transcripts via a Playwright stealth browser (no API key, no cookies, no
maintenance required). One browser context is shared per scan cycle.

Why Playwright instead of youtube-transcript-api:
  youtube-transcript-api makes bare HTTP requests that YouTube blocks on
  cloud/server IPs. Playwright with playwright-stealth looks like a real
  browser and is not blocked.
"""

import asyncio
import html as html_module
import logging
import time
import xml.etree.ElementTree as ET

import aiohttp

from consensus_engine import config as cfg, db
from consensus_engine.utils.browser import create_stealth_browser, stealth_page, safe_goto
from consensus_engine.utils.transcript_export import compute_hash, export_transcript_json

log = logging.getLogger("consensus_engine.scanner.youtube")

_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"


# ---------------------------------------------------------------------------
# RSS feed polling
# ---------------------------------------------------------------------------

async def fetch_channel_videos_rss(
    session: aiohttp.ClientSession,
    channel_id: str,
    limit: int = 3,
) -> list[dict]:
    """Fetch latest video metadata from YouTube Atom RSS feed (free, no auth).

    Returns list of dicts: {video_id, channel_id, title, published_at}.
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


# ---------------------------------------------------------------------------
# Transcript extraction via stealth browser
# ---------------------------------------------------------------------------

async def fetch_transcript(
    video_id: str,
    preferred_languages: list[str],
    browser_context=None,
) -> tuple[str, str, bool]:
    """Fetch transcript for a video via Playwright stealth browser.

    Opens a page (reusing browser_context if provided), extracts
    ytInitialPlayerResponse, picks the best caption track, and fetches
    the timed text XML via the browser's own fetch() — inheriting its
    fingerprint and session so YouTube doesn't block it.

    Returns (transcript_text, language_code, is_auto_generated).
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    async def _extract(context) -> tuple[str, str, bool]:
        page = await stealth_page(context)
        try:
            ok = await safe_goto(page, url, wait_until="domcontentloaded")
            if not ok:
                raise ValueError(f"Page load failed for {video_id}")

            player_response = await page.evaluate(
                "() => window.ytInitialPlayerResponse || null"
            )
            if not player_response:
                raise ValueError(f"No ytInitialPlayerResponse for {video_id}")

            captions = player_response.get("captions", {})
            tracklist = captions.get("playerCaptionsTracklistRenderer", {})
            tracks = tracklist.get("captionTracks", [])

            if not tracks:
                raise ValueError(f"No caption tracks for {video_id}")

            # Pick preferred language, fall back to first available
            track = None
            for lang in preferred_languages:
                for t in tracks:
                    if t.get("languageCode", "").startswith(lang):
                        track = t
                        break
                if track:
                    break
            if not track:
                track = tracks[0]

            base_url = track.get("baseUrl", "")
            lang_code = track.get("languageCode", "unknown")
            is_auto = track.get("kind", "") == "asr"

            if not base_url:
                raise ValueError(f"Empty caption baseUrl for {video_id}")

            # Fetch timed text XML via browser fetch() — uses browser session
            caption_xml = await page.evaluate(
                """async (url) => {
                    const resp = await fetch(url);
                    if (!resp.ok) throw new Error('caption fetch ' + resp.status);
                    return await resp.text();
                }""",
                base_url,
            )

            root = ET.fromstring(caption_xml)
            parts = [
                html_module.unescape(el.text or "")
                for el in root.findall(".//text")
            ]
            text = " ".join(parts).strip()
            return text, lang_code, is_auto
        finally:
            await page.close()

    if browser_context is not None:
        return await _extract(browser_context)

    # No shared context — open a dedicated browser (fallback / standalone use)
    async with create_stealth_browser() as (_, context):
        return await _extract(context)


# ---------------------------------------------------------------------------
# Per-video processing
# ---------------------------------------------------------------------------

async def process_video(
    video_meta: dict,
    semaphore: asyncio.Semaphore,
    preferred_languages: list[str],
    export_dir: str,
    browser_context=None,
) -> None:
    """Dedup → fetch transcript → persist to DB + JSON export. Never raises."""
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
            from consensus_engine.utils.transcript_fetch import fetch_transcript_cascade
            text, lang, is_auto = await fetch_transcript_cascade(
                video_id, preferred_languages
            )
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("no caption", "caption track", "disabled", "not available", "all transcript")):
                log.info("youtube: no captions for %s (%s)", video_id, e)
                await db.mark_youtube_video_status(video_id, "missing")
            else:
                log.warning("youtube: transcript failed for %s: %s", video_id, e)
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
            "youtube: saved %s (%s, auto=%s, %d chars) → %s",
            video_id, lang, is_auto, len(text), path,
        )


# ---------------------------------------------------------------------------
# Scan cycle + poll loop
# ---------------------------------------------------------------------------

async def youtube_scan_once() -> None:
    """One full poll cycle across all configured channels."""
    channel_ids = cfg.get("youtube.channel_ids", [])
    if not channel_ids:
        log.debug("youtube: no channel_ids configured, skipping")
        return

    limit = cfg.get("youtube.max_videos_per_channel", 3)
    concurrency = cfg.get("youtube.max_concurrency", 4)
    export_dir = cfg.get("youtube.export_dir", "artifacts/transcripts")
    preferred_languages = cfg.get("youtube.preferred_languages", ["en"])

    # Collect new videos via RSS (lightweight, no browser)
    headers = {"User-Agent": "OpenClaw/1.0 (youtube-rss-scanner)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        all_videos: list[dict] = []
        for channel_id in channel_ids:
            try:
                videos = await fetch_channel_videos_rss(session, channel_id, limit)
                log.debug("youtube: channel %s → %d videos", channel_id, len(videos))
                all_videos.extend(videos)
            except Exception as e:
                log.warning("youtube: channel %s RSS error: %s", channel_id, e)

    if not all_videos:
        return

    # Filter to unprocessed videos before launching the browser
    unprocessed = []
    for v in all_videos:
        if not await db.has_video_been_processed(v["video_id"]):
            unprocessed.append(v)

    if not unprocessed:
        log.debug("youtube: all %d videos already processed", len(all_videos))
        return

    log.info("youtube: %d new videos to process", len(unprocessed))

    # Open ONE shared stealth browser for the whole batch
    semaphore = asyncio.Semaphore(concurrency)
    async with create_stealth_browser() as (_, context):
        await asyncio.gather(*[
            process_video(v, semaphore, preferred_languages, export_dir, context)
            for v in unprocessed
        ])


async def youtube_poll_loop(stop_event: asyncio.Event) -> None:
    """Background loop — runs youtube_scan_once() every poll_interval_seconds."""
    if not cfg.get("youtube.enabled", False):
        log.debug("youtube: disabled, poll loop not started")
        return

    interval = cfg.get("youtube.poll_interval_seconds", 600)
    log.info(
        "youtube: poll loop started (interval=%ds, channels=%s)",
        interval, cfg.get("youtube.channel_ids", []),
    )

    while not stop_event.is_set():
        try:
            await youtube_scan_once()
        except Exception as e:
            log.error("youtube: scan cycle error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
