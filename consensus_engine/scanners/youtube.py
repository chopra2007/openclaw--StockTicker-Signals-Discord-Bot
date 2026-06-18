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
import re
import time
import xml.etree.ElementTree as ET

import aiohttp

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

from consensus_engine import config as cfg, db
from consensus_engine.utils.http import get_session
from consensus_engine.alerts.discord import _safe_send_kwargs
from consensus_engine.alerts._markdown import _escape_md_link_text
from consensus_engine.utils.transcript_export import compute_hash, export_transcript_json

log = logging.getLogger("consensus_engine.scanner.youtube")

_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"
_MEDIA_NS = "http://search.yahoo.com/mrss/"


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
        async with session.get(
            url,
            headers={"User-Agent": "OpenClaw/1.0 (youtube-rss-scanner)"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
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
        media_group = entry.find(f"{{{_MEDIA_NS}}}group")
        description = ""
        if media_group is not None:
            desc_el = media_group.find(f"{{{_MEDIA_NS}}}description")
            if desc_el is not None and desc_el.text:
                description = desc_el.text
        if video_id_el is None:
            continue
        videos.append({
            "video_id": video_id_el.text or "",
            "channel_id": channel_id,
            "title": (title_el.text or "") if title_el is not None else "",
            "description": description,
            "published_at": (published_el.text or "") if published_el is not None else "",
        })
        if len(videos) >= limit:
            break

    return videos


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Discord alert helper
# ---------------------------------------------------------------------------

async def _send_youtube_alert(message: str) -> None:
    """Post a plain-text YouTube signal alert to the main Discord channel."""
    if cfg.dry_run:
        log.info("[DRY-RUN] YouTube alert: %s", message)
        return
    token = cfg.get_api_key("discord_bot_token")
    channel = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel or not channel.isdigit():
        log.debug("youtube: Discord not configured, skipping alert")
        return
    try:
        session = await get_session()
        url = f"https://discord.com/api/v10/channels/{channel}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        async with session.post(
            url, headers=headers, json=_safe_send_kwargs({"content": message}),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status not in (200, 201):
                log.warning("youtube: Discord alert error (%d)", resp.status)
    except Exception as exc:
        log.warning("youtube: failed to send alert: %s", exc)


# ---------------------------------------------------------------------------
# Per-video processing
# ---------------------------------------------------------------------------

def _suppress_off_allowlist(items, allowlist: set[str], reason: str) -> int:
    """Mark items whose .ticker is not in `allowlist` as suppressed. Returns count.

    Idempotent: never re-suppresses or overwrites an already-suppressed item's
    `suppression_reason` (preserves earlier reasons like "price_sanity" or
    "near_price_dedup" so the audit trail attributes the FIRST cause).
    """
    n = 0
    for it in items:
        ticker = getattr(it, "ticker", "")
        if not ticker:
            continue
        if getattr(it, "suppressed", False):
            continue  # preserve earlier suppression_reason
        if ticker.upper() not in allowlist:
            it.suppressed = True
            it.suppression_reason = reason
            n += 1
    return n


async def _maybe_alert_chain_failure(video_id: str) -> None:
    """Send one Discord #chat alert per video per 24h when all ingest methods fail."""
    import time as _time
    # Guard: real YouTube IDs are 11 chars (letters/digits/_/-). Anything else
    # is a test fixture or malformed input — skip silently so tests can never
    # leak alerts to production #chat.
    if not _YT_ID_RE.match(video_id or ""):
        return
    try:
        row = await db.get_youtube_video(video_id)
        if row is None:
            return
        last_alerted = row.get("chain_failed_alerted_at") or 0
        if _time.time() - last_alerted < 86400:
            return
        token = cfg.get_api_key("discord_bot_token")
        channel_id_str = str(cfg.get("api_keys.discord_channel_id", ""))
        if not token or not channel_id_str or not channel_id_str.isdigit():
            log.warning("Discord not configured — skipping chain-failure alert for %s", video_id)
            return
        import aiohttp as _aiohttp
        from consensus_engine.utils.http import get_session
        from consensus_engine.alerts.discord import _safe_send_kwargs
        session = await get_session()
        url = f"https://discord.com/api/v10/channels/{channel_id_str}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        body = _safe_send_kwargs({"content": f"⚠️ All ingest methods failed for video `{video_id}` — Gemini timeout + Groq Whisper terminal failure. No evidence spans extracted."})
        async with session.post(url, headers=headers, json=body, timeout=_aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status in (200, 201):
                conn = await db.get_db()
                await conn.execute(
                    "UPDATE youtube_videos SET chain_failed_alerted_at = ? WHERE video_id = ?",
                    (_time.time(), video_id),
                )
                await conn.commit()
                log.info("Chain-failure alert sent for %s", video_id)
            else:
                log.warning("Chain-failure alert HTTP %d for %s", resp.status, video_id)
    except Exception as exc:
        log.warning("Chain-failure alert error for %s: %s", video_id, exc)


async def _process_video_two_stage(
    video_id: str,
    channel_id: str,
    display_name: str,
    published_at: str,
) -> tuple[bool, str | None]:
    """Run the v2 two-stage evidence pipeline. Returns (ok, failure_category).
    ok=True when the video was successfully analyzed and persisted (caller should skip
    fallback). On failure, failure_category is telemetry.f2_failure_category (e.g. "quota")
    so the caller can mark a quota-exhausted video 'quota_blocked' (re-queue, no attempt
    bump) vs a real failure 'failed' (bump toward the cap). Item G."""
    from consensus_engine.local_video_ingest import extract_evidence_via_chain
    from consensus_engine.analysis.video_classifier import classify_evidence
    from consensus_engine.analysis.catalyst_resolver import resolve_and_verify_catalysts

    bundle, telemetry = await extract_evidence_via_chain(
        video_id, display_name, published_at,
    )
    if bundle is None:
        return (False, telemetry.f2_failure_category)

    result = classify_evidence(bundle)
    catalysts = await resolve_and_verify_catalysts(
        result.catalyst_candidates, bundle.publish_ts,
    )

    # ── A2: file Gemini-read chart numbers as structured levels ──────────
    # The spoken-span classifier above never sees `bundle.visual_evidence`;
    # this attributes those chart prices to the video's top ticker and appends
    # them so they flow through the same allowlist/suppression + persistence.
    result.levels.extend(await _build_visual_levels(bundle, result.signals))

    # ── Video-level allowlist (Layer 3) ─────────────────────────────────
    from consensus_engine.analysis.ticker_grounding import build_video_allowlist
    video_meta_row = await db.get_youtube_video(video_id)
    title = video_meta_row.get("title", "") if video_meta_row else ""
    description = video_meta_row.get("description", "") if video_meta_row else ""
    span_quotes = [sp.quote for sp in bundle.spans]
    candidate_set = (
        {s.ticker for s in result.signals}
        | {lv.ticker for lv in result.levels}
        | {st.ticker for st in result.setups}
        | {c.ticker for c in catalysts}
    )
    allowlist = build_video_allowlist(
        video_title=title,
        video_description=description,
        span_quotes=span_quotes,
        candidate_tickers=list(candidate_set),
    )
    _suppress_off_allowlist(result.signals, allowlist, "off_allowlist")
    _suppress_off_allowlist(result.levels, allowlist, "off_allowlist")
    _suppress_off_allowlist(result.setups, allowlist, "off_allowlist")
    _suppress_off_allowlist(catalysts, allowlist, "off_allowlist")

    min_conf = float(cfg.get("youtube.classifier.min_confidence", 0.5))
    filter_drops = 0
    for sig in result.signals:
        if sig.classifier_confidence < min_conf and not sig.suppressed:
            sig.suppressed = True
            sig.suppression_reason = "low_confidence"
            filter_drops += 1
    for lv in result.levels:
        if lv.classifier_confidence < min_conf and not lv.suppressed:
            lv.suppressed = True
            lv.suppression_reason = "low_confidence"
            filter_drops += 1
    for st in result.setups:
        if st.classifier_confidence < min_conf and not st.suppressed:
            st.suppressed = True
            st.suppression_reason = "low_confidence"
            filter_drops += 1

    gemini_model = cfg.get("youtube.gemini.model", "gemini-2.5-flash")
    parser_version = f"gemini-evidence/{gemini_model}-v1"
    run_id = await db.create_analysis_run(video_id, parser_version)

    import json as _json
    macro_json = None
    if result.macro_thesis is not None:
        macro_json = _json.dumps({
            "direction": result.macro_thesis.direction.value,
            "themes": result.macro_thesis.themes,
            "timeframe": result.macro_thesis.timeframe,
            "summary": result.macro_thesis.summary,
        })

    # Persist signals
    for sig in result.signals:
        await db.insert_youtube_signal(
            video_id=video_id,
            channel_name=display_name,
            ticker=sig.ticker,
            direction=sig.direction.value,
            conviction=sig.conviction.value,
            mention_count=sig.mention_count,
            macro_thesis=macro_json,
            published_at=published_at,
            run_id=run_id,
            source_snippet=sig.context[:200] if sig.context else None,
            chunk_id=0,
            parser_version=parser_version,
            video_timestamp_sec=sig.video_timestamp_sec,
            evidence_span_ids=_json.dumps(sig.evidence_span_ids) if sig.evidence_span_ids else None,
            classifier_confidence=sig.classifier_confidence,
            suppressed=1 if sig.suppressed else 0,
            suppression_reason=sig.suppression_reason,
        )

    # Persist levels
    for lv in result.levels:
        await db.insert_youtube_level(
            video_id=video_id,
            ticker=lv.ticker,
            level_type=lv.level_type,
            price=lv.price,
            condition_text=lv.context,
            consequence_text="",
            confidence=lv.classifier_confidence,
            channel_name=display_name,
            published_at=published_at,
            run_id=run_id,
            source_snippet=lv.context[:200] if lv.context else None,
            chunk_id=0,
            parser_version=parser_version,
            video_timestamp_sec=lv.video_timestamp_sec,
            evidence_span_ids=_json.dumps(lv.evidence_span_ids) if lv.evidence_span_ids else None,
            classifier_confidence=lv.classifier_confidence,
            suppressed=1 if lv.suppressed else 0,
            suppression_reason=lv.suppression_reason,
        )

    # Persist setups
    for st in result.setups:
        await db.insert_youtube_setup(
            run_id=run_id,
            video_id=video_id,
            ticker=st.ticker,
            entry_low=st.entry_low,
            entry_high=st.entry_high,
            stop_price=st.stop,
            targets=st.targets,
            timeframe=st.timeframe,
            setup_type=st.setup_type,
            context_text=st.context,
            source_snippet=st.context[:200] if st.context else None,
            chunk_id=0,
            risk_reward=st.risk_reward,
            parser_version=parser_version,
            channel_name=display_name,
            published_at=published_at,
            video_timestamp_sec=st.video_timestamp_sec,
            evidence_span_ids=_json.dumps(st.evidence_span_ids) if st.evidence_span_ids else None,
            classifier_confidence=st.classifier_confidence,
            suppressed=1 if st.suppressed else 0,
            suppression_reason=st.suppression_reason,
        )

    # Persist catalysts
    for cat in catalysts:
        await db.insert_youtube_catalyst(
            run_id=run_id,
            video_id=video_id,
            ticker=cat.ticker,
            catalyst_type=cat.catalyst_type,
            mentioned_date=cat.mentioned_date,
            resolved_date=cat.resolved_date,
            verified=cat.verified,
            context_text=cat.context_text,
            video_timestamp_sec=cat.video_timestamp_sec,
            evidence_span_ids=(
                __import__("json").dumps(cat.evidence_span_ids)
                if cat.evidence_span_ids else None
            ),
        )

    # Persist macro
    if result.macro_thesis is not None and (
        result.macro_thesis.narrative or result.macro_thesis.summary
    ):
        await db.insert_youtube_macro(
            video_id=video_id,
            channel_id=channel_id,
            direction=result.macro_thesis.direction.value,
            themes=result.macro_thesis.themes,
            timeframe=result.macro_thesis.timeframe,
            summary=result.macro_thesis.narrative or result.macro_thesis.summary,
            confidence=0.6,
            published_at=published_at,
        )

    # Update analysis_run telemetry
    await db.update_analysis_run_metrics(
        run_id=run_id,
        input_tokens=telemetry.input_tokens or None,
        output_tokens=telemetry.output_tokens or None,
        latency_ms=telemetry.latency_ms or None,
        json_parse_ok=1 if telemetry.json_parse_ok else 0,
        span_count=telemetry.span_count,
        filter_drop_count=filter_drops,
        chain_winner=telemetry.chain_winner,
        f2_failure_category=telemetry.f2_failure_category,
    )

    await db.mark_youtube_video_status(video_id, "analyzed_gemini_v2")

    # Close the analysis-run bookkeeping row. The Gemini path records telemetry via
    # update_analysis_run_metrics (which never sets status), so without this the run row
    # stays 'running' forever even though the video is fully analyzed. Mark it complete
    # only HERE — after every signal/level/setup row is persisted and the video has
    # reached its terminal 'analyzed_gemini_v2' state — so the run is never closed early.
    await db.update_analysis_run(run_id, status="complete")

    # Partial-read detection. Gemini silently caps long videos on input (observed only
    # 18.7min of a verified 105min video, finish_reason=STOP), so the back of a long
    # livestream is never read even though the row is marked analyzed. Store the true
    # length (Invidious) alongside the length Gemini reported seeing (bundle.duration_sec)
    # and warn when Gemini saw materially less. Best-effort: a missing duration just skips
    # the check, never blocks ingestion.
    try:
        from consensus_engine.utils.transcript_fetch import fetch_youtube_duration
        true_dur = await fetch_youtube_duration(video_id)
        observed = bundle.duration_sec
        await db.set_youtube_video_durations(video_id, true_dur, observed)
        cov_floor = float(cfg.get("youtube.gemini.partial_read_coverage_floor", 0.8))
        if true_dur and observed and observed < cov_floor * true_dur:
            log.warning(
                "youtube PARTIAL READ %s: Gemini saw %.1fmin of a %.1fmin video "
                "(%.0f%%) — back of video not transcribed",
                video_id, observed / 60.0, true_dur / 60.0, 100.0 * observed / true_dur,
            )
    except Exception as e:
        log.debug("youtube: duration/coverage check failed for %s: %s", video_id, e)

    # Standalone alerts — one per (ticker) for qualifying-conviction, unsuppressed.
    if cfg.get("youtube.standalone_alerts", True):
        min_trust = cfg.get("youtube.min_trust", 0.5)
        trust = await db.get_channel_trust(channel_id)
        if trust >= min_trust:
            await _send_two_stage_alerts(
                display_name=display_name,
                signals=result.signals,
                levels=result.levels,
                setups=result.setups,
                catalysts=catalysts,
                bundle_spans=bundle.spans,
                min_confidence=min_conf,
                require_verified=bool(cfg.get("youtube.catalyst.require_verified", False)),
                video_id=video_id,
                video_title=title,
                macro_summary=(result.macro_thesis.summary if result.macro_thesis else "") or "",
            )

    log.info(
        "youtube: two-stage %s → %d spans, %d signals, %d levels, %d setups, %d catalysts",
        video_id, len(bundle.spans), len(result.signals),
        len(result.levels), len(result.setups), len(catalysts),
    )
    return (True, None)


async def _safe_live_price(ticker: str) -> float | None:
    """Return live quote price or None on any error. Logs at debug level."""
    try:
        from consensus_engine.api_adapters import get_live_quote_price
        return await get_live_quote_price(ticker)
    except Exception as e:
        log.debug("price_sanity: live quote failed for %s: %s", ticker, e)
        return None


async def _build_visual_levels(bundle, signals, get_live_price=_safe_live_price) -> list:
    """A2 glue: file Gemini-read chart price numbers as structured levels.

    Determines the video's top-mentioned ticker (Conservative attribution),
    fetches a live price anchor, and delegates to `classify_visual_levels`
    which applies the gridline/wrong-ticker band filter. Returns CandidateLevel
    objects to be appended to `result.levels` before persistence (so they pass
    through the same allowlist + low-confidence suppression as spoken levels).
    """
    if not cfg.get("youtube.visual.file_levels", True):
        return []
    visual = getattr(bundle, "visual_evidence", None) or []
    if not visual:
        return []
    live_sigs = [s for s in signals if not getattr(s, "suppressed", 0)]
    if not live_sigs:
        return []
    top = max(live_sigs, key=lambda s: getattr(s, "mention_count", 0) or 0)
    if not getattr(top, "ticker", None):
        return []
    price = await get_live_price(top.ticker)
    band = float(cfg.get("youtube.visual.proximity_band_pct", 0.10))
    conf = float(cfg.get("youtube.visual.level_confidence", 0.55))
    cap = int(cfg.get("youtube.visual.max_levels", 20))

    # B3 #13: when tagging the structured path, file each per-number-tagged
    # visual row under its OWN ticker using that ticker's live-price anchor.
    # Flag OFF -> ticker_prices stays None -> classify_visual_levels behaves
    # exactly as before (every level under top.ticker, no extra fetches).
    ticker_prices: dict[str, float | None] | None = None
    if cfg.get("youtube.visual.tag_structured_levels", False):
        tagged = {
            (row.get("ticker") or "").strip().upper()
            for row in visual
            if isinstance(row, dict)
            and (row.get("ticker") or "").strip()
            and (row.get("ticker") or "").strip().upper() != top.ticker
        }
        tagged.discard("")
        distinct = sorted(tagged)[:7]  # concurrency cap: <=7 distinct tickers
        if distinct:
            fetched = await asyncio.gather(*(get_live_price(t) for t in distinct))
            ticker_prices = dict(zip(distinct, fetched))

    from consensus_engine.analysis.video_classifier import classify_visual_levels
    levels = classify_visual_levels(
        visual, top.ticker, price, band_pct=band, confidence=conf, max_levels=cap,
        ticker_prices=ticker_prices,
    )
    if levels:
        log.info(
            "visual_levels: filed %d chart level(s) for $%s (anchor price=%s)",
            len(levels), top.ticker, price,
        )
    return levels


async def _apply_price_sanity_to_levels(levels, get_live_price=_safe_live_price) -> None:
    """Mark levels with implausible prices vs live quote as suppressed in-place.

    PR5 (B5 fix): the parser occasionally produces prices like $90,451 for a
    stock trading at $200. The setup-tier alert path (line 482-513) catches
    these but only mutates in-memory objects — the corrupt row is already in
    `youtube_levels` by then and the !all anchor pipeline picks it up. Run
    the same check at insert time so the DB row carries `suppressed=1` from
    the start; the SELECT-side filter in db.get_youtube_levels_for_ticker
    then keeps it out of `!all`.

    W1 A-T0 hardening: before the split-factor check, run the calendar-year
    filter on (price, snippet, ticker) so MSFT-$2024-class leaks die at
    insert time even when the live quote is available. The fail-closed
    branch in check_price_plausible handles the live=None case.

    Already-suppressed levels (e.g. off_allowlist) are left untouched.
    """
    from consensus_engine.analysis.price_sanity import check_price_plausible
    from consensus_engine.analysis.calendar_filter import is_calendar_year_in_context

    tickers = sorted({lv.ticker for lv in levels if getattr(lv, "ticker", None)})
    live_prices: dict[str, float | None] = {}
    for t in tickers:
        live_prices[t] = await get_live_price(t)

    for level in levels:
        if getattr(level, "suppressed", 0):
            continue
        ticker = getattr(level, "ticker", None)
        price = getattr(level, "price", None)
        if not ticker or not isinstance(price, (int, float)):
            continue
        snippet = getattr(level, "source_snippet", None)
        live = live_prices.get(ticker)
        if is_calendar_year_in_context(price, snippet, ticker, current_price=live):
            level.suppressed = 1
            level.suppression_reason = "price_sanity_calendar"
            log.warning(
                "price_sanity_calendar: suppressing level %s @ $%.2f (snippet=%r)",
                ticker, price, (snippet or "")[:80],
            )
            continue
        result = check_price_plausible(price, live, source_snippet=snippet)
        if not result.accepted:
            level.suppressed = 1
            level.suppression_reason = (
                "price_sanity_calendar"
                if result.reason == "no_live_price_year_range"
                else "price_sanity"
            )
            log.warning(
                "price_sanity: suppressing level %s @ $%.2f (live=%s reason=%s)",
                ticker, price, live, result.reason,
            )


def _youtube_timestamp_url(video_id: str, ts_sec: int | None) -> str:
    """Return a YouTube watch URL, appending ?t=<ts>s when ts_sec is not None."""
    base = f"https://www.youtube.com/watch?v={video_id}"
    if ts_sec is None:
        return base
    return f"{base}&t={ts_sec}s"


async def _send_two_stage_alerts(
    display_name: str,
    signals,
    levels,
    setups,
    catalysts,
    bundle_spans,
    min_confidence: float,
    require_verified: bool,
    video_id: str = "",
    video_title: str = "",
    macro_summary: str = "",
) -> None:
    """Fire one Discord alert per qualifying-conviction (>= youtube.alerts.standalone_min_conviction), unsuppressed ticker."""
    from consensus_engine.alerts.commands import _format_ts, _format_verified

    from consensus_engine.analysis.price_sanity import check_price_plausible

    sent: set[str] = set()
    # Standalone-alert conviction floor (configurable). Default "medium" widens
    # the gate beyond HIGH-only so more genuine long/short calls surface.
    _conv_rank = {"low": 0, "medium": 1, "high": 2}
    min_conv = str(cfg.get("youtube.alerts.standalone_min_conviction", "medium")).lower()
    min_conv_rank = _conv_rank.get(min_conv, 2)
    for sig in signals:
        if sig.suppressed or sig.ticker in sent:
            continue
        if sig.direction.value not in ("long", "short"):
            continue
        if _conv_rank.get(sig.conviction.value, 0) < min_conv_rank:
            continue
        if sig.classifier_confidence < min_confidence:
            continue

        # ── Price sanity: fetch live price ONCE per ticker, gate per-setup ──
        tkr_setups = [s for s in setups if s.ticker == sig.ticker and not s.suppressed]
        if tkr_setups:
            live_price = await _safe_live_price(sig.ticker)
            surviving_setups = []
            for s in tkr_setups:
                if s.entry_low is None:
                    surviving_setups.append(s)
                    continue
                res = check_price_plausible(s.entry_low, live_price)
                if res.accepted:
                    surviving_setups.append(s)
                else:
                    log.warning(
                        "price_sanity: suppressing setup %s entry=%.2f live=%s reason=%s",
                        sig.ticker, s.entry_low, live_price, res.reason,
                    )
                    s.suppressed = True
                    s.suppression_reason = "price_sanity"
                    for lv in levels:
                        if (
                            lv.ticker == sig.ticker
                            and lv.price == s.entry_low
                            and not lv.suppressed
                        ):
                            lv.suppressed = True
                            lv.suppression_reason = "price_sanity"
            if not surviving_setups:
                sig.suppressed = True
                sig.suppression_reason = "price_sanity"
                log.warning(
                    "price_sanity: BLOCKING alert for %s — all setups failed sanity",
                    sig.ticker,
                )
                continue
            tkr_setups = surviving_setups

        sent.add(sig.ticker)
        lines = [
            f"🎬 **${sig.ticker} [{sig.direction.value.upper()}]** — {display_name} "
            f"(conv {sig.conviction.value.upper()}, confidence {sig.classifier_confidence:.2f})"
        ]

        # 2Q: Clickable video title with timestamp deep-link
        if video_id:
            # Timestamp resolution order: setup.video_timestamp_sec → matching span.ts_sec → signal.video_timestamp_sec
            tkr_ts: int | None = None
            tmp_setups = tkr_setups if tkr_setups else [s for s in setups if s.ticker == sig.ticker and not s.suppressed]
            if tmp_setups and tmp_setups[0].video_timestamp_sec is not None:
                tkr_ts = tmp_setups[0].video_timestamp_sec
            if tkr_ts is None:
                for sp in bundle_spans:
                    if sig.ticker in sp.tickers:
                        tkr_ts = sp.ts_sec
                        break
            if tkr_ts is None and sig.video_timestamp_sec is not None:
                tkr_ts = sig.video_timestamp_sec
            title_max = int(cfg.get("youtube.alerts.video_link.title_max_chars", 80))
            raw_title = (video_title or "").strip()
            escaped_title = _escape_md_link_text(raw_title)[:title_max] if raw_title else "YouTube video"
            url = _youtube_timestamp_url(video_id, tkr_ts)
            lines.append(f"🎥 [{escaped_title}]({url})")

        # 2Q: Macro "Big picture" line
        macro_max = int(cfg.get("youtube.alerts.context.macro_max_chars", 220))
        summary = (macro_summary or "").strip()
        if summary and len(summary) >= 40:
            truncated = summary[:macro_max] + "…" if len(summary) > macro_max else summary
            lines.append(f"💡 Big picture: {truncated}")

        # Setup line (first setup for this ticker — already filtered to survivors)
        if not tkr_setups:
            tkr_setups = [s for s in setups if s.ticker == sig.ticker and not s.suppressed]
        if tkr_setups:
            s = tkr_setups[0]
            parts = []
            if s.entry_low is not None:
                parts.append(f"Entry ${s.entry_low:g}")
            ts = _format_ts(s.video_timestamp_sec) if s.video_timestamp_sec is not None else ""
            if ts:
                parts[-1] = parts[-1] + f" @ {ts}" if parts else f"@ {ts}"
            if s.stop is not None:
                parts.append(f"Stop ${s.stop:g}")
            if s.targets:
                t_str = f"Target ${s.targets[0]:g}"
                if s.risk_reward is not None:
                    t_str += f" (R/R {s.risk_reward:.1f}x)"
                parts.append(t_str)
            # Catalyst — find first matching catalyst for this ticker
            cats = [c for c in catalysts if c.ticker == sig.ticker and not c.suppressed]
            if cats:
                c = cats[0]
                if require_verified and c.verified != 1:
                    pass
                else:
                    date_str = c.resolved_date or c.mentioned_date
                    mark = _format_verified(c.verified)
                    parts.append(f"Catalyst {date_str} {c.catalyst_type} {mark}")
            if parts:
                lines.append("📐 " + " | ".join(parts))

        # Support / resistance rows (separate)
        tkr_levels = [lv for lv in levels if lv.ticker == sig.ticker and not lv.suppressed]
        support_parts = []
        resistance_parts = []
        for lv in tkr_levels:
            ts = _format_ts(lv.video_timestamp_sec) if lv.video_timestamp_sec is not None else ""
            ts_str = f" @ {ts}" if ts else ""
            fragment = f"${lv.price:g}{ts_str}"
            if lv.level_type == "support":
                support_parts.append(fragment)
            elif lv.level_type == "resistance":
                resistance_parts.append(fragment)
        if support_parts:
            lines.append("📊 Support " + " | ".join(support_parts[:4]))
        if resistance_parts:
            lines.append("📊 Resistance " + " | ".join(resistance_parts[:4]))

        # 2Q: Context quote — expanded window; optional second span when no macro + short quote
        quote_max = int(cfg.get("youtube.alerts.context.quote_max_chars", 320))
        quote = ""
        second_quote = ""
        for sp in bundle_spans:
            if sig.ticker in sp.tickers:
                if not quote:
                    quote = sp.quote
                elif not second_quote:
                    second_quote = sp.quote
                    break
        if quote:
            rendered_quote = quote[:quote_max]
            # Append second span when no macro summary and first quote is short
            if not summary and len(quote) < 120 and second_quote:
                rendered_quote = rendered_quote + " " + second_quote[:quote_max - len(rendered_quote) - 1]
            lines.append(f'> "{rendered_quote}"')

        await _send_youtube_alert("\n".join(lines))


async def process_video(
    video_meta: dict,
    semaphore: asyncio.Semaphore,
    preferred_languages: list[str],
    export_dir: str,
) -> None:
    """Dedup → two-stage (or Gemini legacy / transcript cascade) → persist. Never raises."""
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
            description=video_meta.get("description", ""),
            published_at=video_meta["published_at"],
            fetched_at=time.time(),
        )

        display_name = await db.get_channel_display_name(channel_id)
        parsed = None

        # ── v2 two-stage evidence pipeline (flag-gated) ───────────────────────
        if (
            cfg.get("youtube.use_two_stage", False)
            and cfg.get("youtube.gemini_enabled", True)
            and cfg.get("youtube.analyze", True)
        ):
            two_stage_fcat = None
            try:
                ok, two_stage_fcat = await _process_video_two_stage(
                    video_id, channel_id, display_name, video_meta["published_at"],
                )
                if ok:
                    return
            except Exception as e:
                log.warning("youtube: two-stage error for %s: %s", video_id, e)
                from consensus_engine.utils.burst_retry import classify_retry, RetryClass
                if classify_retry(exc=e) is RetryClass.QUOTA_BLOCKED:
                    two_stage_fcat = "quota"
            if not cfg.get("youtube.legacy_fallback", True):
                # Item G: a quota-exhausted video is transcribable later — re-queue forever
                # (quota_blocked, NO attempt bump) instead of burning a retry toward the cap.
                if two_stage_fcat == "quota":
                    log.info("youtube: %s quota-blocked — re-queue (no attempt bump)", video_id)
                    await db.mark_youtube_video_status(video_id, "quota_blocked")
                else:
                    await db.mark_youtube_video_status(video_id, "failed", bump_attempt=True)
                    await _maybe_alert_chain_failure(video_id)
                return

        # ── Fallback: transcript cascade + multi-pass pipeline ────────────────
        if parsed is None:
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
                    await db.mark_youtube_video_status(video_id, "failed", bump_attempt=True)
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
                await db.mark_youtube_video_status(video_id, "failed", bump_attempt=True)
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

            if cfg.get("youtube.analyze", True):
                try:
                    from consensus_engine.analysis.video_parser import parse_video_transcript
                    parsed = await parse_video_transcript(
                        video_id=video_id,
                        transcript_text=text,
                        channel_name=display_name,
                        published_at=video_meta["published_at"],
                    )
                except Exception as e:
                    log.warning("youtube: transcript analysis error for %s: %s", video_id, e)
                    return

        # ── Persist results (shared path for both Gemini and transcript) ──────
        if parsed is None:
            return

        # ── Video-level allowlist (Layer 3) — applies to both Path B and C ───
        from consensus_engine.analysis.ticker_grounding import build_video_allowlist
        candidate_set = (
            {t.get("symbol", "").upper() for t in parsed.tickers if t.get("symbol")}
            | {lv.ticker.upper() for lv in parsed.price_levels if lv.ticker}
            | {s.ticker.upper() for s in parsed.setups if s.ticker}
            | {o.ticker.upper() for o in parsed.options if o.ticker}
        )
        # Path B/C has no spans table — gather evidence from each item's context.
        evidence_texts = (
            [t.get("context", "") for t in parsed.tickers]
            + [lv.condition for lv in parsed.price_levels]
            + [s.context for s in parsed.setups]
            + [o.context for o in parsed.options]
        )
        title = video_meta.get("title", "")
        allowlist = build_video_allowlist(
            video_title=title,
            video_description=video_meta.get("description", ""),
            span_quotes=evidence_texts,
            candidate_tickers=list(candidate_set),
        )
        log.info(
            "video_allowlist (Path B/C): video=%s candidates=%s allowlist=%s",
            video_meta["video_id"], sorted(candidate_set), sorted(allowlist),
        )

        def _suppress_meta(ticker: str) -> tuple[int, str | None]:
            """Return (suppressed, reason) for an off-allowlist row; (0, None) otherwise."""
            if ticker and ticker.upper() not in allowlist:
                return 1, "off_allowlist"
            return 0, None

        # Insert signals for each ticker
        for ticker_data in parsed.tickers:
            ticker = ticker_data.get("symbol")
            if ticker:
                macro_json = None
                if parsed.macro_thesis:
                    import json
                    macro_json = json.dumps({
                        "direction": parsed.macro_thesis.direction.value,
                        "themes": parsed.macro_thesis.themes,
                        "timeframe": parsed.macro_thesis.timeframe,
                        "summary": parsed.macro_thesis.summary,
                    })

                supp, supp_reason = _suppress_meta(ticker)
                await db.insert_youtube_signal(
                    video_id=video_id,
                    channel_name=display_name,
                    ticker=ticker,
                    direction=ticker_data.get("direction", "neutral"),
                    conviction=ticker_data.get("conviction", "medium"),
                    mention_count=ticker_data.get("mention_count", 1),
                    macro_thesis=macro_json,
                    published_at=video_meta["published_at"],
                    run_id=parsed.run_id,
                    source_snippet=ticker_data.get("source_snippet"),
                    chunk_id=ticker_data.get("chunk_id", 0),
                    parser_version=parsed.parser_version,
                    suppressed=supp,
                    suppression_reason=supp_reason,
                )
                log.debug("youtube: signal created %s/%s conviction=%s", video_id, ticker, ticker_data.get("conviction"))

        # Insert price levels (PR5: pre-insert price sanity vs live quote).
        await _apply_price_sanity_to_levels(parsed.price_levels)
        for level in parsed.price_levels:
            lv_supp, lv_supp_reason = _suppress_meta(level.ticker)
            # Honor either off-allowlist (lv_supp from _suppress_meta) OR the
            # price-sanity flag set by _apply_price_sanity_to_levels above.
            if not lv_supp and getattr(level, "suppressed", 0):
                lv_supp = level.suppressed
                lv_supp_reason = getattr(level, "suppression_reason", None)
            await db.insert_youtube_level(
                video_id=video_id,
                ticker=level.ticker,
                level_type=level.level_type,
                price=level.price,
                condition_text=level.condition,
                consequence_text=level.consequence,
                confidence=level.confidence,
                channel_name=display_name,
                published_at=video_meta["published_at"],
                run_id=parsed.run_id,
                parser_version=parsed.parser_version,
                suppressed=lv_supp,
                suppression_reason=lv_supp_reason,
            )
            log.debug("youtube: level created %s %s @ %.2f", video_id, level.ticker, level.price)

        # Persist macro thesis to youtube_macro table
        if parsed.macro_thesis and parsed.macro_thesis.summary:
            await db.insert_youtube_macro(
                video_id=video_id,
                channel_id=channel_id,
                direction=parsed.macro_thesis.direction.value,
                themes=parsed.macro_thesis.themes,
                timeframe=parsed.macro_thesis.timeframe,
                summary=parsed.macro_thesis.summary,
                confidence=0.7 if parsed.overall_conviction.value == "high" else 0.5,
                published_at=video_meta["published_at"],
            )

        # Insert options ideas
        for opt in parsed.options:
            opt_supp, opt_supp_reason = _suppress_meta(opt.ticker)
            await db.insert_youtube_option(
                run_id=parsed.run_id,
                video_id=video_id,
                ticker=opt.ticker,
                option_type=opt.option_type,
                strike=opt.strike,
                expiry=opt.expiry,
                strategy=opt.strategy,
                source=opt.source,
                conviction=opt.conviction,
                context_text=opt.context,
                source_snippet=opt.source_snippet,
                chunk_id=opt.chunk_id,
                parser_version=parsed.parser_version,
                channel_name=display_name,
                published_at=video_meta["published_at"],
                suppressed=opt_supp,
                suppression_reason=opt_supp_reason,
            )
            log.debug("youtube: option created %s/%s %s", video_id, opt.ticker, opt.option_type)

        # Insert trade setups and absorb constituent levels
        for setup in parsed.setups:
            st_supp, st_supp_reason = _suppress_meta(setup.ticker)
            setup_id = await db.insert_youtube_setup(
                run_id=parsed.run_id,
                video_id=video_id,
                ticker=setup.ticker,
                entry_low=setup.entry_low,
                entry_high=setup.entry_high,
                stop_price=setup.stop,
                targets=setup.targets,
                timeframe=setup.timeframe,
                setup_type=setup.setup_type,
                context_text=setup.context,
                source_snippet=setup.source_snippet,
                chunk_id=setup.chunk_id,
                risk_reward=setup.risk_reward,
                parser_version=parsed.parser_version,
                channel_name=display_name,
                published_at=video_meta["published_at"],
                suppressed=st_supp,
                suppression_reason=st_supp_reason,
            )
            conn = await db.get_db()
            cur = await conn.execute(
                "SELECT id FROM youtube_levels WHERE video_id=? AND ticker=? AND setup_id IS NULL",
                (video_id, setup.ticker),
            )
            level_ids = [r["id"] for r in await cur.fetchall()]
            if level_ids:
                await db.mark_levels_absorbed_by_setup(level_ids, setup_id)
            log.debug("youtube: setup created %s/%s type=%s (absorbed %d levels)", video_id, setup.ticker, setup.setup_type, len(level_ids))

        # Standalone alerts for HIGH conviction non-neutral tickers
        if cfg.get("youtube.standalone_alerts", True):
            min_trust = cfg.get("youtube.min_trust", 0.5)
            trust = await db.get_channel_trust(channel_id)
            if trust >= min_trust:
                from consensus_engine.alerts.commands import (
                    _format_youtube_setup_summary,
                    _format_youtube_option_summary,
                )
                for ticker_data in parsed.tickers:
                    if (
                        ticker_data.get("conviction") == "high"
                        and ticker_data.get("direction") in ("long", "short")
                    ):
                        sym = ticker_data.get("symbol", "")

                        # Price sanity — per-setup gating (parity with Path A).
                        tkr_setups = [s for s in parsed.setups if s.ticker == sym]
                        if tkr_setups:
                            from consensus_engine.analysis.price_sanity import check_price_plausible
                            live_price = await _safe_live_price(sym)
                            survived = []
                            for s in tkr_setups:
                                if s.entry_low is None:
                                    survived.append(s)
                                    continue
                                res = check_price_plausible(s.entry_low, live_price)
                                if res.accepted:
                                    survived.append(s)
                                else:
                                    log.warning(
                                        "price_sanity: legacy suppressing setup %s entry=%.2f live=%s reason=%s",
                                        sym, s.entry_low, live_price, res.reason,
                                    )
                                    s.suppressed = True
                                    s.suppression_reason = "price_sanity"
                            if not survived:
                                log.warning(
                                    "price_sanity: BLOCKING legacy alert for %s — all setups failed sanity",
                                    sym,
                                )
                                continue
                            tkr_setups = survived

                        direction_label = ticker_data["direction"].upper()
                        lines = [f"🎬 **${sym} [{direction_label}]** — {display_name}"]

                        # 2Q: Clickable video title with timestamp deep-link
                        b_video_id = video_meta.get("video_id", "")
                        if b_video_id:
                            # Timestamp: first matching setup's video_timestamp_sec
                            b_ts: int | None = None
                            for _s in (tkr_setups if tkr_setups else []):
                                if _s.video_timestamp_sec is not None:
                                    b_ts = _s.video_timestamp_sec
                                    break
                            title_max = int(cfg.get("youtube.alerts.video_link.title_max_chars", 80))
                            raw_title = (video_meta.get("title") or "").strip()
                            escaped_title = _escape_md_link_text(raw_title)[:title_max] if raw_title else "YouTube video"
                            url = _youtube_timestamp_url(b_video_id, b_ts)
                            lines.append(f"🎥 [{escaped_title}]({url})")

                        # 2Q: Macro "Big picture" line
                        macro_max = int(cfg.get("youtube.alerts.context.macro_max_chars", 220))
                        b_summary = ""
                        if parsed.macro_thesis and parsed.macro_thesis.summary:
                            b_summary = parsed.macro_thesis.summary.strip()
                        if b_summary and len(b_summary) >= 40:
                            truncated = b_summary[:macro_max] + "…" if len(b_summary) > macro_max else b_summary
                            lines.append(f"💡 Big picture: {truncated}")

                        # Price levels (support / resistance)
                        levels = [lv for lv in parsed.price_levels if lv.ticker == sym]
                        if levels:
                            lv_parts = []
                            for lv in levels[:4]:
                                label = lv.level_type.capitalize()
                                lv_parts.append(f"{label} ${lv.price:.0f}")
                            lines.append("📊 " + " | ".join(lv_parts))

                        # Trade setups (only survivors)
                        setups = tkr_setups if tkr_setups else [s for s in parsed.setups if s.ticker == sym]
                        for s in setups[:2]:
                            lines.append(_format_youtube_setup_summary(s))

                        # Options ideas
                        opts = [o for o in parsed.options if o.ticker == sym]
                        for o in opts[:2]:
                            lines.append(_format_youtube_option_summary(o))

                        # 2Q: Context snippet — expanded quote window
                        quote_max = int(cfg.get("youtube.alerts.context.quote_max_chars", 320))
                        ctx = ticker_data.get("context", "").strip()
                        if ctx:
                            lines.append(f'> "{ctx[:quote_max]}"')

                        await _send_youtube_alert("\n".join(lines))

        log.info("youtube: parsed %s → %d tickers, %d levels", video_id, len(parsed.tickers), len(parsed.price_levels))


# ---------------------------------------------------------------------------
# Scan cycle + poll loop
# ---------------------------------------------------------------------------

# Item G: reentrancy guard. The drain now re-queues 'quota_blocked' rows forever, which
# widens the window for an overlapping --once run to double-process the same row. A module
# lock makes youtube_scan_once non-reentrant in-process; a second concurrent call returns
# immediately rather than racing the same backlog.
_scan_lock = asyncio.Lock()


async def youtube_scan_once() -> None:
    """One full poll cycle across all configured channels."""
    if _scan_lock.locked():
        log.debug("youtube: scan already in progress — skipping reentrant call")
        return
    async with _scan_lock:
        await _youtube_scan_once_locked()


async def _youtube_scan_once_locked() -> None:
    # Canonical source is youtube_channels DB table (seeded from sources.json).
    # YAML youtube.channel_ids is a legacy override; merge both so neither is lost.
    channel_ids = list(cfg.get("youtube.channel_ids", []))
    db_channels = await db.get_approved_youtube_channels()
    for ch in db_channels:
        if ch not in channel_ids:
            channel_ids.append(ch)
    if not channel_ids:
        log.debug("youtube: no channel_ids configured in DB or yaml, skipping")
        return

    limit = cfg.get("youtube.max_videos_per_channel", 3)
    concurrency = cfg.get("youtube.max_concurrency", 4)
    export_dir = cfg.get("youtube.export_dir", "artifacts/transcripts")
    preferred_languages = cfg.get("youtube.preferred_languages", ["en"])

    # Collect new videos via RSS (lightweight, no browser)
    session = await get_session()
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
    seen_ids = set()
    for v in all_videos:
        if not await db.has_video_been_processed(v["video_id"]):
            unprocessed.append(v)
            seen_ids.add(v["video_id"])

    # ITEM #7: drain the DB backlog of failed-but-retryable videos oldest-first.
    # RSS only resurfaces the latest few per channel, so older failures would
    # otherwise never be retried.
    retry_cap = cfg.get("youtube.max_retries", 5)
    # Item G: bound a quota-misclassification — a quota_blocked video stuck with no progress
    # past the downgrade window becomes 'failed' (so the attempt cap can terminate it).
    downgrade_days = cfg.get("youtube.quota_blocked_downgrade_days", 4)
    try:
        n_dg = await db.downgrade_stale_quota_blocked(downgrade_days)
        if n_dg:
            log.warning("youtube: downgraded %d stale quota_blocked video(s) -> failed (>%sd no progress)", n_dg, downgrade_days)
    except Exception as e:
        log.debug("youtube: quota_blocked downgrade failed: %s", e)
    for v in await db.get_retryable_youtube_videos(retry_cap):
        if v["video_id"] not in seen_ids:
            unprocessed.append(v)
            seen_ids.add(v["video_id"])

    if not unprocessed:
        log.debug("youtube: all %d videos already processed", len(all_videos))
        return

    log.info("youtube: %d new videos to process", len(unprocessed))

    # Item G: paced SEQUENTIAL drain (~1 video/min) instead of gather-all. The Gemini
    # chain is already single-flight (_chain_semaphore=Semaphore(1)) so concurrency buys
    # nothing, and firing all at once is what burst-exhausted the per-minute token quota
    # (the 42-alert incident). Speed is a non-goal (user-locked). The DB queue persists
    # the backlog across cycles/days, so one cycle clearing only ~10 is fine.
    pace_s = cfg.get("youtube.pace_seconds", 60)
    semaphore = asyncio.Semaphore(concurrency)
    for i, v in enumerate(unprocessed):
        await process_video(v, semaphore, preferred_languages, export_dir)
        if i < len(unprocessed) - 1:
            await asyncio.sleep(pace_s)


_LAST_COVERAGE_DAY: str | None = None
_LAST_BACKLOG_DEPTH: int | None = None
_BACKLOG_RISING_DAYS: int = 0


async def _emit_daily_coverage() -> None:
    """C1: once per UTC day, log how many video runs got the full Gemini chart
    read (chain_winner='gemini/v2') vs fell back to captions/whisper. Free-tier
    Gemini caps ~3-4 videos/key/day, so this makes chart-read coverage visible."""
    global _LAST_COVERAGE_DAY
    import time as _t
    today = _t.strftime("%Y-%m-%d", _t.gmtime())
    if today == _LAST_COVERAGE_DAY:
        return
    counts = await db.get_youtube_coverage_counts(hours=24)
    _LAST_COVERAGE_DAY = today
    if not counts:
        return
    gemini = counts.get("gemini/v2", 0)
    total = sum(counts.values())
    log.info(
        "youtube coverage (24h): %d/%d videos got full Gemini chart read; breakdown=%s",
        gemini, total, counts,
    )

    # Item G throughput alarm: track the transcription backlog (quota_blocked +
    # retryable-failed) day-over-day. If it rises for N consecutive days, inflow is
    # outpacing capacity — the "need a 3rd key / paid tier" signal.
    global _BACKLOG_RISING_DAYS, _LAST_BACKLOG_DEPTH
    try:
        retry_cap = cfg.get("youtube.max_retries", 5)
        depth = (await db.get_youtube_backlog_depth(retry_cap)).get("total", 0)
        if _LAST_BACKLOG_DEPTH is not None and depth > _LAST_BACKLOG_DEPTH:
            _BACKLOG_RISING_DAYS += 1
        else:
            _BACKLOG_RISING_DAYS = 0
        _LAST_BACKLOG_DEPTH = depth
        log.info("youtube backlog depth: %d (rising %d day(s))", depth, _BACKLOG_RISING_DAYS)
        if _BACKLOG_RISING_DAYS >= cfg.get("youtube.backlog_alarm_days", 3):
            log.warning(
                "youtube backlog rising %d consecutive days (depth=%d) — transcription "
                "inflow may be outpacing free-tier capacity; consider a 3rd Gemini key.",
                _BACKLOG_RISING_DAYS, depth,
            )
    except Exception as e:
        log.debug("youtube: backlog alarm check failed: %s", e)


async def youtube_poll_loop(stop_event: asyncio.Event) -> None:
    """Background loop — runs youtube_scan_once() every poll_interval_seconds."""
    if not cfg.get("youtube.enabled", False):
        log.debug("youtube: disabled, poll loop not started")
        return

    interval = cfg.get("youtube.poll_interval_seconds", 600)
    db_channels = await db.get_approved_youtube_channels()
    yaml_channels = cfg.get("youtube.channel_ids", [])
    all_channels = list({*yaml_channels, *db_channels})
    log.info(
        "youtube: poll loop started (interval=%ds, channels=%s)",
        interval, all_channels,
    )

    while not stop_event.is_set():
        try:
            await youtube_scan_once()
        except Exception as e:
            log.error("youtube: scan cycle error: %s", e)
        try:
            await _emit_daily_coverage()
        except Exception as e:
            log.debug("youtube: coverage emit error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
