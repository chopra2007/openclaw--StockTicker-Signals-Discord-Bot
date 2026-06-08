"""One-shot backfill: re-read Wolf's older Gmail through the LIVE Phase-1 reader
to seed `macro_theses` with reconstructed historical theses, so the Phase-3
digests have real content.

Reuses the exact live seam (gmail_watcher._build_service/_decode_body/_strip_quoted
-> wolf_email_parser.parse_email -> wolf_theses.ingest -> db.record_wolf_email) but
in CHRONOLOGICAL order (oldest first), passing each email's Gmail internalDate as
the clock, and SKIPPING wolf_news.post_events (no historical Discord spam).

MUST run with the live engine STOPPED — the DB sits behind an in-process asyncio
lock that does NOT serialize a separate process (see final-plan.md section 6):

    sudo systemctl stop consensus-engine
    python3 scripts/backfill_wolf.py --dry-run      # preview: list emails, NO parse, NO writes
    python3 scripts/backfill_wolf.py                # real seed (needs GEMINI keys in env)
    sudo systemctl start consensus-engine

Idempotent/resumable: emails already in wolf_emails_processed are skipped; a crash
mid-run re-ingests to a no-op (wolf_theses.ingest dedups on source message id).

Usage:
    python3 scripts/backfill_wolf.py --dry-run
    python3 scripts/backfill_wolf.py --max-emails 5
    python3 scripts/backfill_wolf.py --since 2026-05-01
    python3 scripts/backfill_wolf.py --rebuild        # back up + clear Wolf tables, full replay
"""

import argparse
import asyncio
import hashlib
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path so `consensus_engine` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import config as cfg, db
from consensus_engine.scanners import gmail_watcher
from consensus_engine.analysis import wolf_email_parser, wolf_theses

log = logging.getLogger("backfill_wolf")

# Wolf-table rows cleared by --rebuild (Wolf isolation: NEVER ticker_signals etc.).
_REBUILD_CLEAR = [
    "DELETE FROM macro_theses",
    "DELETE FROM wolf_beneficiaries",  # else the macro_theses id-renumber orphans these rows
    "DELETE FROM wolf_confluence_checks",
    "DELETE FROM wolf_call_outcomes",
    "DELETE FROM wolf_news_alerts",
    "DELETE FROM wolf_emails_processed WHERE message_id IN "
    "(SELECT message_id FROM wolf_emails_processed)",  # all Wolf ledger rows
]


def _wolf_sender() -> str:
    # phase-4 #5: read the split lists (allowed_emails first, then a domain),
    # falling back to the legacy combined list, so the Gmail query is never empty.
    emails = cfg.get("gmail_watcher.allowed_emails", []) or []
    if emails:
        return emails[0]
    domains = cfg.get("gmail_watcher.allowed_domains", []) or []
    if domains:
        return domains[0].lstrip("*").lstrip("@")
    legacy = cfg.get("gmail_watcher.sender_allowlist", []) or []
    if legacy:
        return legacy[0]
    return "support@wolf-on-wallstreet.com"


def _gmail_query(since: str | None) -> str:
    q = f"from:{_wolf_sender()}"
    if since:
        # Gmail wants after:YYYY/MM/DD
        q += " after:" + since.replace("-", "/")
    return q


async def _list_all_message_ids(service, query: str) -> list[str]:
    """Paginate the full All-Mail result for the Wolf sender."""
    loop = asyncio.get_running_loop()
    ids: list[str] = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        result = await loop.run_in_executor(
            None, lambda k=dict(kwargs): service.users().messages().list(**k).execute()
        )
        ids.extend(m["id"] for m in result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return ids


async def _fetch_meta(service, msg_id: str) -> dict:
    """messages().get(full) for one id."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: service.users().messages().get(userId="me", id=msg_id, format="full").execute(),
    )


async def _check_precondition(unseen_received: list[float], rebuild: bool) -> bool:
    """Empty-state precondition (Codex MAJOR-4): refuse to replay OLD emails into
    theses already advanced by NEWER (live) emails — that scrambles stage/evidence
    order. Allowed when the Wolf tables are empty, when every active thesis is
    older than the oldest email we're about to replay (clean resume), or --rebuild.
    """
    if rebuild or not unseen_received:
        return True
    conn = await db.get_db()
    cur = await conn.execute("SELECT MAX(last_updated) AS mx FROM macro_theses")
    row = await cur.fetchone()
    max_lu = row["mx"] if row else None
    if max_lu is None:
        return True  # empty -> clean seed
    oldest_unseen = min(unseen_received)
    if max_lu > oldest_unseen:
        log.error(
            "ABORT: an existing thesis was updated (%.0f) AFTER the oldest email to "
            "replay (%.0f). Replaying now would scramble stage order. Re-run with "
            "--rebuild to back up + clear the Wolf tables and replay from scratch.",
            max_lu, oldest_unseen,
        )
        return False
    return True


async def _do_rebuild() -> None:
    db_path = db.DB_PATH or cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{db_path}.bak.pre-wolf-rebuild-{stamp}"
    shutil.copy2(db_path, backup)
    log.info("--rebuild: backed up DB -> %s", backup)
    conn = await db.get_db()
    for stmt in _REBUILD_CLEAR:
        await conn.execute(stmt)
    await conn.commit()
    log.info("--rebuild: cleared Wolf tables (macro_theses/confluence/outcomes/alerts/ledger)")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill Wolf Gmail history into macro_theses.")
    ap.add_argument("--dry-run", action="store_true", help="list emails only; no parse, no writes")
    ap.add_argument("--max-emails", type=int, default=0, help="cap emails processed (0 = all)")
    ap.add_argument("--since", type=str, default=None, help="only emails after YYYY-MM-DD")
    ap.add_argument("--rebuild", action="store_true", help="back up + clear Wolf tables, then full replay")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    await db.init_db()
    if args.rebuild and not args.dry_run:
        await _do_rebuild()

    sender = _wolf_sender()
    query = _gmail_query(args.since)
    log.info("Wolf backfill: query=%r dry_run=%s max=%s", query, args.dry_run, args.max_emails or "all")

    service = gmail_watcher._build_service()
    all_ids = await _list_all_message_ids(service, query)
    log.info("Gmail returned %d messages for the Wolf sender", len(all_ids))
    if not all_ids:
        log.warning("No Wolf emails found — nothing to backfill.")
        return 0

    # Fetch metadata, build (internalDate, msg_id) records, sort ascending (stable).
    records = []
    for mid in all_ids:
        try:
            msg = await _fetch_meta(service, mid)
        except Exception as exc:
            log.warning("messages.get(%s) failed: %s", mid, exc)
            continue
        try:
            received_at = float(msg.get("internalDate", 0)) / 1000.0
        except (TypeError, ValueError):
            received_at = 0.0
        records.append((received_at, mid, msg))
    records.sort(key=lambda r: (r[0], r[1]))  # ascending, stable on same-minute ties

    # Determine unseen set (for resume + precondition).
    unseen = []
    for received_at, mid, msg in records:
        if await db.wolf_email_seen(mid):
            continue
        unseen.append((received_at, mid, msg))

    if not unseen:
        log.info("All %d Wolf emails already processed — nothing to do (idempotent).", len(records))
        return 0

    if not await _check_precondition([r[0] for r in unseen], args.rebuild):
        return 2  # precondition failed

    if args.max_emails and args.max_emails > 0:
        unseen = unseen[: args.max_emails]

    oldest = datetime.fromtimestamp(unseen[0][0], tz=timezone.utc).date()
    newest = datetime.fromtimestamp(unseen[-1][0], tz=timezone.utc).date()
    log.info("Processing %d unseen email(s), %s -> %s (ascending).", len(unseen), oldest, newest)

    if args.dry_run:
        for received_at, mid, msg in unseen:
            d = datetime.fromtimestamp(received_at, tz=timezone.utc)
            headers = msg.get("payload", {}).get("headers", [])
            subj = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
            log.info("  [dry] %s  %s  %s", d.strftime("%Y-%m-%d %H:%M"), mid, subj[:70])
        log.info("DRY-RUN complete: %d email(s) would be ingested. No parse, no writes.", len(unseen))
        return 0

    # Real seed.
    theses_before = len(await db.get_active_theses())
    processed = 0
    for received_at, mid, msg in unseen:
        text, html = gmail_watcher._decode_body(msg.get("payload", {}))
        text = gmail_watcher._strip_quoted(text)
        html_sha1 = hashlib.sha1((html or text).encode()).hexdigest()
        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
        now = received_at  # the email's true clock — reconstructs stages in order

        parse_status, error, events, image_urls_sha1 = "ok", None, [], ""
        try:
            extraction = await wolf_email_parser.parse_email(text, html, subject, sender, now)
            img_urls = [c.get("source_url", "") for c in extraction.get("chart_reads", [])]
            image_urls_sha1 = hashlib.sha1("|".join(img_urls).encode()).hexdigest()
            events = await wolf_theses.ingest(extraction, source_id=mid)
            # NOTE: deliberately NO wolf_news.post_events — historical, not live.
        except Exception as exc:
            parse_status, error = "error", str(exc)[:200]
            log.error("parse/ingest error for %s: %s", mid, exc, exc_info=True)

        await db.record_wolf_email(
            mid, html_sha1, image_urls_sha1, parse_status, error, len(events),
            processed_at=time.time(), received_at=received_at,
        )
        processed += 1
        if processed % 10 == 0 or events:
            log.info("  [%d/%d] %s -> %d event(s)", processed, len(unseen), subject[:50], len(events))

    theses_after = len(await db.get_active_theses())
    log.info(
        "BACKFILL complete: %d email(s) processed, active theses %d -> %d (+%d).",
        processed, theses_before, theses_after, theses_after - theses_before,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
