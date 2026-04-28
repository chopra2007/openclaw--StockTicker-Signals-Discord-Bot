"""One-shot backfill: mark previously-persisted YouTube rows as suppressed when
the row's ticker is not grounded in any of the video's evidence text.

Run AFTER the grounding code lands in production. Idempotent — re-running
won't re-suppress already-suppressed rows or re-touch rows that pass.

Usage:
    python3 scripts/backfill_youtube_grounding.py --dry-run    # preview
    python3 scripts/backfill_youtube_grounding.py              # apply
    python3 scripts/backfill_youtube_grounding.py --video vkqchQQnm88  # one video
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on path so `consensus_engine` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.analysis.ticker_grounding import (
    is_ticker_grounded,
    build_video_allowlist,
)

log = logging.getLogger("backfill")
SUPPRESSION_REASON = "hallucination_backfill"


async def _evidence_pool_for_video(video_id: str) -> tuple[str, list[str]]:
    """Return (title, evidence_texts) for a video.

    evidence_texts is the union of every span quote, every level/setup
    context_text, every signal source_snippet, and every option context_text.
    """
    conn = await db.get_db()

    title_row = await (await conn.execute(
        "SELECT title FROM youtube_videos WHERE video_id = ?", (video_id,)
    )).fetchone()
    title = title_row["title"] if title_row else ""

    pool: list[str] = []

    cur = await conn.execute(
        "SELECT quote FROM youtube_evidence_spans WHERE video_id = ?", (video_id,)
    )
    pool.extend(r["quote"] for r in await cur.fetchall())

    cur = await conn.execute(
        "SELECT context_text FROM youtube_setups WHERE video_id = ?", (video_id,)
    )
    pool.extend(r["context_text"] or "" for r in await cur.fetchall())

    cur = await conn.execute(
        "SELECT condition_text FROM youtube_levels WHERE video_id = ?", (video_id,)
    )
    pool.extend(r["condition_text"] or "" for r in await cur.fetchall())

    cur = await conn.execute(
        "SELECT source_snippet FROM youtube_signals WHERE video_id = ?", (video_id,)
    )
    pool.extend(r["source_snippet"] or "" for r in await cur.fetchall())

    cur = await conn.execute(
        "SELECT context_text FROM youtube_options WHERE video_id = ?", (video_id,)
    )
    pool.extend(r["context_text"] or "" for r in await cur.fetchall())

    return title, pool


async def _candidate_tickers(video_id: str) -> set[str]:
    """All tickers persisted for this video across signals/levels/setups/options."""
    conn = await db.get_db()
    out: set[str] = set()
    for table in ("youtube_signals", "youtube_levels", "youtube_setups", "youtube_options"):
        cur = await conn.execute(f"SELECT DISTINCT ticker FROM {table} WHERE video_id = ?", (video_id,))
        out.update(r["ticker"] for r in await cur.fetchall() if r["ticker"])
    return out


async def _all_video_ids() -> list[str]:
    conn = await db.get_db()
    cur = await conn.execute("SELECT video_id FROM youtube_videos")
    return [r["video_id"] for r in await cur.fetchall()]


async def _suppress_off_allowlist(
    video_id: str, allowlist: set[str], dry_run: bool,
) -> dict:
    """Mark rows in signals/levels/setups/options whose ticker not in allowlist as suppressed.

    Returns counts: {table: count}.

    All four target tables already carry `suppressed` and `suppression_reason`
    columns (db.py:1422-1696). This helper updates whichever rows have an
    off-allowlist ticker and a current suppressed=0 (idempotent).
    """
    conn = await db.get_db()
    counts = {}
    for table in ("youtube_signals", "youtube_levels", "youtube_setups", "youtube_options"):
        cur = await conn.execute(
            f"SELECT id, ticker FROM {table} "
            f"WHERE video_id = ? AND COALESCE(suppressed, 0) = 0",
            (video_id,),
        )
        rows = await cur.fetchall()
        ids_to_suppress = [
            r["id"] for r in rows
            if r["ticker"] and r["ticker"].upper() not in allowlist
        ]
        counts[table] = len(ids_to_suppress)
        if not ids_to_suppress or dry_run:
            continue
        # Batch update.
        placeholders = ",".join("?" * len(ids_to_suppress))
        await conn.execute(
            f"UPDATE {table} SET suppressed = 1, suppression_reason = ? "
            f"WHERE id IN ({placeholders})",
            [SUPPRESSION_REASON, *ids_to_suppress],
        )
    if not dry_run:
        await conn.commit()
    return counts


async def main(dry_run: bool, video_filter: str | None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    await db.init_db()

    video_ids = [video_filter] if video_filter else await _all_video_ids()
    log.info("backfill: scanning %d videos (dry_run=%s)", len(video_ids), dry_run)

    total_dropped = {
        "youtube_signals": 0,
        "youtube_levels": 0,
        "youtube_setups": 0,
        "youtube_options": 0,
    }
    affected_videos = 0

    for vid in video_ids:
        title, pool = await _evidence_pool_for_video(vid)
        if not pool and not title:
            log.debug("backfill: %s no evidence pool, skipping", vid)
            continue
        candidates = await _candidate_tickers(vid)
        if not candidates:
            continue
        allowlist = build_video_allowlist(
            video_title=title,
            span_quotes=pool,
            candidate_tickers=list(candidates),
        )
        off = candidates - allowlist
        if not off:
            continue
        affected_videos += 1
        log.info(
            "backfill: video=%s title=%r candidates=%s off_allowlist=%s",
            vid, title[:60], sorted(candidates), sorted(off),
        )
        counts = await _suppress_off_allowlist(vid, allowlist, dry_run)
        for k, v in counts.items():
            total_dropped[k] += v

    log.info(
        "backfill: complete — videos_affected=%d signals=%d levels=%d setups=%d options=%d (dry_run=%s)",
        affected_videos,
        total_dropped["youtube_signals"], total_dropped["youtube_levels"],
        total_dropped["youtube_setups"], total_dropped["youtube_options"], dry_run,
    )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="report only, no DB writes")
    p.add_argument("--video", default=None, help="restrict to one video_id")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.video)))
