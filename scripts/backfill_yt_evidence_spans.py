#!/usr/bin/env python3
"""One-shot backfill: fetch transcripts and write evidence spans for youtube_signals
rows that have no matching youtube_evidence_spans row.

Usage:
    python3 scripts/backfill_yt_evidence_spans.py [--dry-run]

--dry-run: only count candidates, no transcript fetches or DB writes.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

# Ensure the workspace root is on the path
_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_yt_evidence_spans")

# Suppress noisy sub-loggers
for _noisy in ("aiosqlite", "aiohttp.client", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_CANDIDATE_QUERY = """
SELECT DISTINCT s.video_id, s.ticker, s.channel_name
FROM youtube_signals s
WHERE NOT EXISTS (
    SELECT 1 FROM youtube_evidence_spans e
    WHERE e.video_id = s.video_id
      AND e.tickers_json LIKE '%"' || s.ticker || '"%'
)
AND s.extracted_at >= (strftime('%s','now') - 30*86400)
ORDER BY s.extracted_at DESC
LIMIT 500
"""


async def _get_candidates(conn) -> list[dict]:
    cur = await conn.execute(_CANDIDATE_QUERY)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _fetch_transcript(video_id: str) -> str | None:
    """Return transcript text from DB only — no external fetches."""
    try:
        from consensus_engine.db import get_db
        conn = await get_db()
        cursor = await conn.execute(
            "SELECT transcript_text FROM youtube_transcripts WHERE video_id = ?",
            (video_id,),
        )
        row = await cursor.fetchone()
        if row and row["transcript_text"]:
            log.debug("transcript from DB for %s (%d chars)", video_id, len(row["transcript_text"]))
            return row["transcript_text"]
    except Exception as exc:
        log.debug("DB transcript lookup failed for %s: %s", video_id, exc)

    return None


async def _process_video(
    video_id: str,
    tickers: list[str],
    channel_name: str,
) -> tuple[int, str]:
    """Fetch transcript, parse spans, write to DB.

    Returns (span_count, status_label) where status_label is 'OK(N)' or 'SKIP(reason)'.
    """
    from consensus_engine.db import create_analysis_run, insert_youtube_evidence_span, update_analysis_run
    from consensus_engine.models import RunTelemetry
    from consensus_engine.analysis.captions_llm_parser import extract_evidence_from_captions

    transcript = await _fetch_transcript(video_id)
    if not transcript:
        return 0, "SKIP (no transcript)"

    telemetry = RunTelemetry()
    bundle = await extract_evidence_from_captions(
        video_id=video_id,
        transcript=transcript,
        published_at="",
        telemetry=telemetry,
    )
    if bundle is None or not bundle.spans:
        return 0, "SKIP (no spans from LLM)"

    run_id = await create_analysis_run(video_id, parser_version="backfill/v1")
    written = 0
    for span in bundle.spans:
        await insert_youtube_evidence_span(
            run_id=run_id,
            video_id=video_id,
            ts_sec=span.ts_sec,
            quote=span.quote,
            tickers=span.tickers,
            parser_version="backfill/v1",
            chain_winner="captions-llm/backfill",
        )
        written += 1

    await update_analysis_run(run_id, status="done")
    return written, f"OK ({written} spans)"


async def main(dry_run: bool) -> None:
    # Load env so DB path / API keys are available
    from dotenv import load_dotenv
    env_path = os.path.join(_WORKSPACE, "..", ".env")
    load_dotenv(env_path, override=False)
    env_path2 = "/root/.openclaw/.env"
    if os.path.exists(env_path2):
        load_dotenv(env_path2, override=False)

    from consensus_engine.db import get_db

    conn = await get_db()
    candidates_raw = await _get_candidates(conn)

    if not candidates_raw:
        print("No candidates found — nothing to backfill.")
        return

    # Deduplicate by video_id, collecting all tickers per video
    by_video: dict[str, dict] = {}
    for row in candidates_raw:
        vid = row["video_id"]
        if vid not in by_video:
            by_video[vid] = {"tickers": [], "channel_name": row.get("channel_name", "")}
        t = row["ticker"]
        if t and t not in by_video[vid]["tickers"]:
            by_video[vid]["tickers"].append(t)

    print(f"Candidates: {len(candidates_raw)} signal rows → {len(by_video)} unique videos")

    if dry_run:
        print("--dry-run: stopping here, no fetches or DB writes.")
        return

    total_videos = len(by_video)
    ok_count = 0
    skip_count = 0
    total_spans = 0

    for idx, (video_id, meta) in enumerate(by_video.items(), 1):
        tickers = meta["tickers"]
        channel = meta["channel_name"]
        try:
            span_count, label = await _process_video(video_id, tickers, channel)
            total_spans += span_count
            if label.startswith("OK"):
                ok_count += 1
            else:
                skip_count += 1
            print(f"[{idx}/{total_videos}] {video_id}: {label}")
        except Exception as exc:
            skip_count += 1
            print(f"[{idx}/{total_videos}] {video_id}: ERROR ({exc})")

    print(
        f"\nBackfilled {ok_count} videos, {total_spans} spans written, {skip_count} skipped"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill YT evidence spans for old signals")
    parser.add_argument("--dry-run", action="store_true", help="Count candidates only, no writes")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
