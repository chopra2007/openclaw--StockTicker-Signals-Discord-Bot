"""Phase-3 (TODO #20): weekend-safe scheduled #news digests for the Wolf macro-brain.

Three variants, composed from EXISTING data (theses+stage, confluence scoreboard,
Wolf's market lean, and — Sunday only — how his actionable calls have moved):
  - midday   : event-triggered ~1 min after Wolf's ~12:00-13:05 PT email
  - nightly  : event-triggered after the long evening Wrap (19:00-02:00 PT, crosses midnight)
  - sunday   : clock-based weekly recap (Sun >= 10:00 PT) + a 'sunday-addon' if a Sunday
               email lands AFTER the recap posted

Triggers key off wolf_emails_processed.received_at (the email's true Gmail receive
time), never processed_at — so the backfill's old rows can never fire a digest
(Codex BLOCKER-1). All window math uses ZoneInfo('America/Los_Angeles') (DST-correct).
Dedupe is the outbox dedupe_key (digest|<variant>|<PT-date>) — idempotent across
restarts and concurrent polls. Gated OFF by wolf.digests.enabled.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg, db
from consensus_engine.alerts import wolf_news
from consensus_engine.analysis import wolf_outcomes
from consensus_engine.analysis.regime import lookup_regime

log = logging.getLogger(__name__)

_PT = ZoneInfo("America/Los_Angeles")


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)


def pt_window_anchor(now_pt: datetime, start_hm: str, end_hm: str) -> tuple[bool, "object"]:
    """Return (in_window, anchor_pt_date). anchor_pt_date is the PT calendar date the
    window OPENED — so a cross-midnight window (start>end) keys the post-midnight hours
    to the PREVIOUS day. 19:30 PT and 01:30 PT of one evening Wrap therefore share ONE
    anchor date (and thus one dedupe key). Returns (False, None) when outside the window.
    """
    sh, sm = _parse_hm(start_hm)
    eh, em = _parse_hm(end_hm)
    cur = now_pt.hour * 60 + now_pt.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return (start <= cur <= end), (now_pt.date() if start <= cur <= end else None)
    # crosses midnight: [start, 24:00) U [0, end]
    if cur >= start:
        return True, now_pt.date()                          # evening side: today opened it
    if cur <= end:
        return True, (now_pt - timedelta(days=1)).date()    # post-midnight: yesterday opened it
    return False, None


def _pt_epoch(pt_date, hm: str) -> float:
    """Epoch seconds for `hm` PT on `pt_date` (DST-correct via ZoneInfo)."""
    h, m = _parse_hm(hm)
    return datetime(pt_date.year, pt_date.month, pt_date.day, h, m, tzinfo=_PT).timestamp()


async def gather_digest(variant: str) -> dict:
    """Pull current Wolf state into a renderable payload. No posting, no side effects.
    Lists are passed in FULL; format_digest caps each field and adds a '+N more' line."""
    theses = await db.get_active_theses()

    acting, imminent, watchlist, scoreboard = [], [], [], []
    bull_mkt = bear_mkt = 0
    for t in theses:
        entry = {"scope_type": t["scope_type"], "scope_key": t["scope_key"],
                 "direction": t["direction"], "stage": t["stage"]}
        stage = t["stage"]
        if stage == "acting":
            acting.append(entry)
        elif stage == "imminent":
            imminent.append(entry)
        elif stage in ("forming", "diverging"):
            watchlist.append(entry)
        if t["scope_type"] == "market":
            if t["direction"] == "bull":
                bull_mkt += 1
            elif t["direction"] == "bear":
                bear_mkt += 1
        confl = await db.get_confluence_check(t["id"])
        if confl and (confl.get("combined_tier") in ("high", "critical")
                      or (cfg.get("wolf.confluence.board_show_levelless", False)
                          and confl.get("agree_count", 0) >= 2)):
            scoreboard.append({"scope_key": t["scope_key"], "direction": t["direction"],
                               "combined_tier": confl["combined_tier"],
                               "agree": confl.get("agree_count", 0),
                               "disagree": confl.get("disagree_count", 0)})

    if bull_mkt or bear_mkt:
        if bull_mkt > bear_mkt:
            lean = f"Wolf's market lean: leaning bullish ({bull_mkt} bull / {bear_mkt} bear broad-market call(s))"
        elif bear_mkt > bull_mkt:
            lean = f"Wolf's market lean: leaning bearish ({bear_mkt} bear / {bull_mkt} bull broad-market call(s))"
        else:
            lean = f"Wolf's market lean: mixed ({bull_mkt} bull / {bear_mkt} bear broad-market call(s))"
    else:
        lean = "Wolf's market lean: no active broad-market call"

    reg = await lookup_regime()
    if getattr(reg, "cold_start", True):
        regime_clause = "Market regime: still calibrating (needs ~30 days of price data)"
    else:
        regime_clause = f"Market regime: {reg.label}"

    # Phase-4 #2: inferred beneficiary LONGs (the bot's read, NOT Wolf's picks). Only when
    # BOTH flags are on (enabled gates precompute; surface_in_digest gates the post — the
    # OFF period is the shadow-run). Attach to the prominent macro/sector theses (acting/
    # imminent), reading precomputed rows that pass a freshness gate (stale => omitted).
    beneficiaries: list[dict] = []
    if (cfg.get("wolf.beneficiaries.enabled", False)
            and cfg.get("wolf.beneficiaries.surface_in_digest", False)):
        max_age = float(cfg.get("wolf.beneficiaries.digest_max_age_sec", 7200))
        now_ts = datetime.now(_PT).timestamp()
        for t in theses:
            if t["scope_type"] == "stock" or t["stage"] not in ("acting", "imminent"):
                continue
            fresh = [r for r in await db.get_beneficiaries(t["id"])
                     if (now_ts - float(r.get("computed_at", 0) or 0)) <= max_age]
            if fresh:
                beneficiaries.append({
                    "scope_key": t["scope_key"], "direction": t["direction"],
                    "scope_type": t["scope_type"],
                    "picks": [{"ticker": r["ticker"], "side": r["side"],
                               "tier": r["tier"], "reason": r["reason"]} for r in fresh],
                })

    payload = {
        "variant": variant,
        "generated_at_pt": datetime.now(_PT).strftime("%a %b %-d, %-I:%M %p PT"),
        "lean": lean,
        "regime_clause": regime_clause,
        "acting": acting,
        "imminent": imminent,
        "watchlist": watchlist,
        "scoreboard": scoreboard,
        "beneficiaries": beneficiaries,
    }
    if variant in ("sunday", "sunday-addon"):
        payload["outcomes"] = await wolf_outcomes.compute_outcomes(
            int(cfg.get("wolf.digests.outcome_lookback_days", 7))
        )
    return payload


async def post_digest(variant: str, anchor_date) -> bool:
    """Compose + post one digest. Idempotent via the outbox dedupe_key."""
    payload = await gather_digest(variant)
    event = {"kind": "digest", "variant": variant,
             "dedupe_key": f"digest|{variant}|{anchor_date}", "payload": payload}
    return await wolf_news.post_event(event)


async def recap_fired_today(anchor_date) -> bool:
    """Persistent check (survives restart): has the Sunday recap for this date actually
    POSTED? Keys on status, not mere row existence — a failed send leaves a non-posted
    row that must still be retried, not treated as done."""
    row = await db.get_wolf_alert(f"digest|sunday|{anchor_date}")
    return row is not None and row.get("status") == "posted"


async def _digest_tick(now_pt: datetime | None = None, now_epoch: float | None = None) -> None:
    """One scheduler evaluation. now_pt/now_epoch are injectable for tests."""
    if now_pt is None:
        now_pt = datetime.now(_PT)
    if now_epoch is None:
        now_epoch = now_pt.timestamp()

    # An email is a valid trigger iff its received_at falls within the CURRENT open PT
    # window [lo, hi]. pt_window_anchor already rejects a reboot that lands outside the
    # window, so no extra staleness/grace bound is needed — and a restart *inside* a long
    # window must still post the digest (a 90-min grace would eat the 7-hour nightly Wrap).
    # Dedup (dedupe_key) makes a re-post after a successful one a no-op.

    # --- midday (same-day window) ---
    mw = cfg.get("wolf.digests.midday_window_pt", ["12:00", "13:05"])
    in_mid, mid_anchor = pt_window_anchor(now_pt, mw[0], mw[1])
    if in_mid:
        lo, hi = _pt_epoch(mid_anchor, mw[0]), _pt_epoch(mid_anchor, mw[1])
        if await db.count_wolf_emails_received_between(lo, hi) >= 1:
            await post_digest("midday", mid_anchor)

    # --- nightly (cross-midnight window) ---
    nw = cfg.get("wolf.digests.nightly_window_pt", ["19:00", "02:00"])
    in_night, night_anchor = pt_window_anchor(now_pt, nw[0], nw[1])
    if in_night:
        lo = _pt_epoch(night_anchor, nw[0])
        hi = _pt_epoch(night_anchor + timedelta(days=1), nw[1])
        if await db.count_wolf_emails_received_between(lo, hi) >= 1:
            await post_digest("nightly", night_anchor)

    # --- sunday recap + add-on (clock-based) ---
    if now_pt.weekday() == 6:  # Sunday
        recap_hm = cfg.get("wolf.digests.sunday_recap_pt", "10:00")
        rh, rm = _parse_hm(recap_hm)
        today = now_pt.date()
        if now_pt.hour * 60 + now_pt.minute >= rh * 60 + rm:
            recap_row = await db.get_wolf_alert(f"digest|sunday|{today}")
            recap_posted = recap_row is not None and recap_row.get("status") == "posted"
            if not recap_posted:
                # post the recap — or RETRY a previously-failed one. Do NOT fall through to
                # the add-on branch just because a (failed) row exists (Codex MAJOR-2).
                week_lo = now_epoch - 7 * 86400
                if await db.count_wolf_emails_received_between(week_lo, now_epoch) >= 1:
                    await post_digest("sunday", today)
            else:
                # add-on: a Sunday email arrived AFTER the recap actually posted
                posted_at = recap_row.get("posted_at") or recap_row.get("created_at") or 0.0
                if await db.count_wolf_emails_received_between(posted_at, now_epoch) >= 1:
                    await post_digest("sunday-addon", today)


async def wolf_digest_loop(stop_event: asyncio.Event) -> None:
    """Background loop: post scheduled #news digests. Gated on wolf.digests.enabled,
    runs on stop_event (NOT the weekend pause) so the nightly/weekend Wraps still fire,
    crash-isolated so it can never take down run_live. Polls every 60s on PT windows."""
    if not cfg.get("wolf.digests.enabled", False):
        log.info("wolf_digest_loop: disabled (wolf.digests.enabled=false); not running")
        return
    log.info("wolf_digest_loop: armed (poll 60s, PT windows, triggers key off received_at)")
    while not stop_event.is_set():
        try:
            await _digest_tick()
        except Exception as exc:
            log.error("wolf_digest_loop: tick error: %s", exc, exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
