"""Atlas: leased-queue research worker.

Drains `research_jobs`, fans out to source adapters, preserves last-good
content on failure, and renders a per-ticker markdown note into the vault.
"""
from __future__ import annotations

import asyncio
import logging
import time

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.research import sources, vault

log = logging.getLogger("consensus_engine.research.atlas")

def _enabled_sources() -> list[str]:
    toggles = cfg.get("atlas.sources", {}) or {}
    return [s for s in ("analyst", "sec", "news") if toggles.get(s, True)]


def _is_fresh(section: dict | None, cache_days: int, reason: str) -> bool:
    # Alerts always refresh analyst regardless of freshness.
    if not section:
        return False
    last = section.get("last_good_at") or 0
    if not last:
        return False
    return (time.time() - last) < (cache_days * 86400)


async def _run_source(ticker: str, source: str) -> None:
    fetcher = getattr(sources, f"fetch_{source}_section")
    try:
        content = await fetcher(ticker)
    except Exception as exc:
        log.warning("Atlas %s/%s fetch raised: %s", ticker, source, exc)
        await db.upsert_research_section(ticker, source, None, "failed")
        return
    if content is None:
        await db.upsert_research_section(ticker, source, None, "skipped")
    else:
        await db.upsert_research_section(ticker, source, content, "ok")


async def _process_job(job: dict) -> None:
    ticker = job["ticker"]
    reason = job["reason"]
    cache_days = int(cfg.get("atlas.cache_days", 7))
    existing = await db.get_research_sections(ticker)

    tasks = []
    for source in _enabled_sources():
        if reason == "alert" and source == "analyst":
            tasks.append(_run_source(ticker, source))
            continue
        if _is_fresh(existing.get(source), cache_days, reason):
            log.info("Atlas %s/%s fresh, skipping", ticker, source)
            continue
        tasks.append(_run_source(ticker, source))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=False)

    sections = await db.get_research_sections(ticker)
    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")
    try:
        await vault.write_ticker_vault(ticker, sections, vault_path)
        await db.finish_atlas_job(job["id"], "done")
    except Exception as exc:
        log.error("Atlas vault write failed for %s: %s", ticker, exc)
        await db.finish_atlas_job(job["id"], "failed")


async def atlas_worker_loop(stop_event: asyncio.Event) -> None:
    if not cfg.get("atlas.enabled", False):
        log.info("Atlas disabled; worker loop exiting")
        return
    lease_ttl = int(cfg.get("atlas.lease_ttl_seconds", 1800))
    idle_sleep = 30
    while not stop_event.is_set():
        try:
            job = await db.acquire_atlas_lease(lease_ttl)
            if job:
                log.info("Atlas processing %s (%s)", job["ticker"], job["reason"])
                await _process_job(job)
                continue
        except Exception as exc:
            log.error("Atlas worker loop error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=idle_sleep)
        except asyncio.TimeoutError:
            pass


async def run_one_job() -> bool:
    """Verification helper: drain one job synchronously. Returns True if a job ran."""
    job = await db.acquire_atlas_lease(int(cfg.get("atlas.lease_ttl_seconds", 1800)))
    if not job:
        return False
    await _process_job(job)
    return True


async def enqueue_atlas_job(ticker: str, reason: str) -> int | None:
    """Public API: enqueue a research job. Coalesces duplicate tickers."""
    return await db.enqueue_atlas_job(ticker, reason)


async def _ticker_is_fresh(ticker: str, cache_days: int) -> bool:
    sections = await db.get_research_sections(ticker)
    if not sections:
        return False
    for s in sections.values():
        last = s.get("last_good_at") or 0
        if last and (time.time() - last) < cache_days * 86400:
            return True
    return False


async def _sweep_once(session_start_utc: float, session_end_utc: float) -> int:
    """Enqueue top-N tickers from the session. Returns count enqueued."""
    max_n = int(cfg.get("atlas.max_tickers_sweep", 10))
    cache_days = int(cfg.get("atlas.cache_days", 7))
    tickers = await db.get_top_tickers_session(session_start_utc, session_end_utc, limit=max_n * 2)
    enqueued = 0
    for t in tickers:
        if await _ticker_is_fresh(t, cache_days):
            continue
        if await db.enqueue_atlas_job(t, "sweep") is not None:
            enqueued += 1
            if enqueued >= max_n:
                break
    log.info("Atlas sweep enqueued %d tickers", enqueued)
    return enqueued


async def atlas_sweep_loop(stop_event: asyncio.Event) -> None:
    """Fire a sweep once per trading day at atlas.sweep_time_et."""
    from consensus_engine.research.sessions import current_et_session, is_market_holiday
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

    if not cfg.get("atlas.enabled", False):
        log.info("Atlas disabled; sweep loop exiting")
        return

    fired_key: str | None = None
    while not stop_event.is_set():
        now = datetime.now(tz=ET)
        sweep_hhmm = str(cfg.get("atlas.sweep_time_et", "08:00"))
        hh, mm = [int(x) for x in sweep_hhmm.split(":")]
        is_trading = now.weekday() < 5 and not is_market_holiday(now)
        at_or_past = (now.hour, now.minute) >= (hh, mm)
        today_key = now.strftime("%Y-%m-%d")
        if is_trading and at_or_past and fired_key != today_key:
            start, end, _ = current_et_session(now)
            try:
                await _sweep_once(start, end)
            except Exception as exc:
                log.error("Atlas sweep failed: %s", exc)
            fired_key = today_key
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
