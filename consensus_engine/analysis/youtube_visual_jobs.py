"""Durable visual work independent of transcript acquisition and speech analysis."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
import time

from consensus_engine import config as cfg, db
from consensus_engine.models import CandidateLevel, EvidenceBundle, EvidenceSpan, RunTelemetry
from consensus_engine.utils.usetranscribe import _read, _write
from consensus_engine.analysis.gemini_video_parser import extract_visual_evidence_with_gemini

_lock: asyncio.Lock | None = None
log = logging.getLogger(__name__)


def _directory():
    return Path(cfg.get("youtube.visual.jobs_dir", "artifacts/youtube_visual_jobs"))


def _merge_telemetry(target, source):
    target.input_tokens += source.input_tokens
    target.output_tokens += source.output_tokens
    target.chain_durations["gemini-visual/v1"] = source.latency_ms


async def queue_visuals(bundle: EvidenceBundle) -> bool:
    """Queue instantly; acquiring a transcript never waits for the visual worker."""
    path = _directory() / f"{bundle.video_id}.json"
    record = _read(path)
    if record.get("version") == 2:
        if record.get("status") in {"ready", "complete"}:
            bundle.visual_evidence = record["visual_evidence"]
            return True
        if record.get("status") == "pending":
            return False
    _write(path, {"version": 2, "status": "pending", "bundle": asdict(bundle)})
    return False


async def add_visuals(bundle: EvidenceBundle, telemetry: RunTelemetry) -> bool:
    """Save speech first; failed visuals never fail the transcript path."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        path = _directory() / f"{bundle.video_id}.json"
        record = _read(path)
        if record.get("version") == 2 and record.get("status") in {"ready", "complete"}:
            bundle.visual_evidence = record["visual_evidence"]
            return True
        if record and record.get("retry_at", 0) > time.time():
            return False
        record = {**record, "version": 2, "status": "pending", "bundle": asdict(bundle)}
        _write(path, record)
        try:
            visual, tel = await extract_visual_evidence_with_gemini(
                bundle.video_id, bundle.publish_ts, duration_sec=bundle.duration_sec,
                cache_dir=_directory() / "batches" / bundle.video_id,
            )
        except Exception:
            visual, tel = None, RunTelemetry(f2_failure_category="unknown")
        _merge_telemetry(telemetry, tel)
        if visual is None:
            attempts = record.get("attempts", 0) + 1
            record.update(attempts=attempts, failure=tel.f2_failure_category,
                          retry_at=time.time() + min(21600, 300 * 2 ** min(attempts - 1, 7)))
            _write(path, record)
            return False
        # Filter reported times against the known transcript duration, not an
        # invented visual-reader duration. Transcript metadata remains authoritative.
        bundle.visual_evidence = [v for v in visual.visual_evidence
                                  if bundle.duration_sec is None or v["ts_sec"] <= bundle.duration_sec]
        record.update(status="ready", visual_evidence=bundle.visual_evidence,
                      input_tokens=tel.input_tokens, output_tokens=tel.output_tokens)
        _write(path, record)
        return True


async def persist_visuals(bundle):
    """A restart between database writes and job completion cannot duplicate rows."""
    conn = await db.get_db()
    cursor = await conn.execute(
        "SELECT ts_sec, value, COALESCE(ticker, '') FROM youtube_visual_evidence WHERE video_id=?",
        (bundle.video_id,),
    )
    rows = await cursor.fetchall()
    existing = {(row[0], row[1], row[2]) for row in rows}
    new = [v for v in bundle.visual_evidence
           if (v["ts_sec"], v["value"], v.get("ticker") or "") not in existing]
    await db.insert_youtube_visual_evidence(bundle.video_id, new)


def mark_complete(video_id):
    path = _directory() / f"{video_id}.json"
    record = _read(path)
    if record.get("status") == "ready":
        record.update(status="complete", completed_at=time.time())
        _write(path, record)


async def retry_pending_visuals():
    """One due job per scanner poll; speech and alerts are never repeated."""
    from consensus_engine.analysis.video_classifier import classify_evidence
    from consensus_engine.analysis.ticker_grounding import build_video_allowlist
    from consensus_engine.scanners.youtube import _build_visual_levels, _apply_price_sanity_to_levels
    for path in sorted(_directory().glob("*.json")):
        record = _read(path)
        if record.get("status") not in {"pending", "ready"} or record.get("retry_at", 0) > time.time():
            continue
        data = record.get("bundle", {})
        video_id = data.get("video_id")
        meta = await db.get_youtube_video(video_id)
        if not meta:
            continue
        # Wait until initial speech persistence has finished. Failed initial
        # ingest is retried through the normal scanner, which can reuse the job.
        conn = await db.get_db()
        row = await (await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id=?", (video_id,))).fetchone()
        if not row or row[0] != "analyzed_gemini_v2":
            continue
        bundle = EvidenceBundle(**{**data, "spans": [EvidenceSpan(**s) for s in data.get("spans", [])]})
        telemetry = RunTelemetry()
        if not await add_visuals(bundle, telemetry):
            return True
        ready = _read(path)
        if "prepared_levels" in ready:
            levels = [CandidateLevel(**v) for v in ready["prepared_levels"]]
        else:
            result = classify_evidence(bundle)
            levels = await _build_visual_levels(bundle, result.signals)
            allowlist = build_video_allowlist(video_title=meta.get("title", ""),
                video_description=meta.get("description", ""), span_quotes=[s.quote for s in bundle.spans],
                candidate_tickers=[v.ticker for v in levels])
            for level in levels:
                if level.ticker not in allowlist or level.classifier_confidence < float(cfg.get("youtube.classifier.min_confidence", 0.5)):
                    level.suppressed = True
                    level.suppression_reason = "off_allowlist_or_low_confidence"
            await _apply_price_sanity_to_levels(levels)
            ready["prepared_levels"] = [asdict(v) for v in levels]
            _write(path, ready)  # freeze price-derived types before any database inserts
        await persist_visuals(bundle)
        run_id = ready.get("run_id")
        if not run_id:
            run_id = await db.create_analysis_run(video_id, "gemini-visual-only/v1")
            ready["run_id"] = run_id
            _write(path, ready)  # reuse this run after a crash during level insertion
        channel_name = await db.get_channel_display_name(meta["channel_id"])
        for level in levels:
            await db.insert_youtube_level(video_id=video_id, ticker=level.ticker,
                level_type=level.level_type, price=level.price, published_at=bundle.publish_ts,
                channel_name=channel_name, confidence=level.classifier_confidence,
                run_id=run_id, source_snippet=level.context, parser_version="gemini-visual-only/v1",
                video_timestamp_sec=level.video_timestamp_sec, classifier_confidence=level.classifier_confidence,
                suppressed=int(level.suppressed), suppression_reason=level.suppression_reason)
        await db.update_analysis_run_metrics(run_id=run_id, input_tokens=ready.get("input_tokens"),
            output_tokens=ready.get("output_tokens"), chain_winner="gemini-visual/v1", json_parse_ok=1)
        await db.update_analysis_run(run_id, status="complete")
        mark_complete(video_id)
        log.info(
            "youtube: visual job complete %s (%d observations, %d levels)", video_id, len(bundle.visual_evidence), len(levels))
        return True
    return False


async def visual_poll_loop(stop_event):
    """Drain chart jobs independently while the RSS scanner processes transcripts."""
    log.info("youtube: independent visual worker started")
    while not stop_event.is_set():
        processed = False
        try:
            processed = await retry_pending_visuals()
        except Exception as exc:
            log.warning("youtube: visual worker failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1 if processed else 30)
        except asyncio.TimeoutError:
            pass


def start_visual_worker(stop_event):
    """Both market-hours and weekend listeners own the same stoppable worker."""
    if cfg.get("youtube.enabled", False) and cfg.get("youtube.transcript_first", False):
        return asyncio.create_task(visual_poll_loop(stop_event), name="youtube-visual-worker")
    return None
