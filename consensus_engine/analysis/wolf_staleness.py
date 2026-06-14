"""Nightly staleness sweep for Wolf macro theses (TODO #26).

A thesis stays 'active' forever today unless an opposite-direction call flips it or the
sprawl cap evicts it. Nothing retires a thesis when Wolf simply goes quiet on it — so
stale calls keep feeding the digest / confluence / beneficiaries. This sweep DEMOTES
(never deletes) such theses to a 'stale_review' state.

Demote when ANY of:
  - AGE CAP exceeded (stage-split: `imminent` short, `forming`/`diverging` medium,
    `acting` long). An `imminent` call gone quiet for weeks is itself a signal it
    didn't pan out; an `acting` call (Wolf is in the trade) gets a long leash.
  - TARGET REACHED and no real reaffirmation for N days (the clean-target case).
  - CONTRADICTED by a higher-conviction opposite thesis on the SAME instrument complex,
    and stale for N days.

Codex-hardened correctness points:
  * the staleness CLOCK is "days since the last EXPLICIT same-direction reaffirmation"
    (an evidence entry reaching stage imminent/acting, or intent started/adding) — NOT
    last_updated. A misread "reaffirmation" (e.g. the IGV bull-target misread) reaches
    only forming/watching, so it cannot keep a dead thesis perpetually fresh.
  * contradiction is computed on POLARITY-NORMALIZED direction — VIX vs UVXY/VXX are
    inverse instruments, so a naive "same complex + opposite label = contradiction" is
    backwards. Each complex member carries an explicit polarity sign.
  * demote-not-delete + a 'stale_review' state revivable by a genuine reaffirmation
    (handled in wolf_theses.ingest) or a manual override (revive_stale_thesis()).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from consensus_engine import config as cfg, db
from consensus_engine.analysis.wolf_scope import proxy_symbol

log = logging.getLogger(__name__)

_DAY = 86400.0
_STAGE_RANK = {"forming": 0, "diverging": 1, "imminent": 2, "acting": 3}

# Default stage-split age caps (days). Overridable via wolf.staleness.cap_days.*
_DEFAULT_CAPS = {"forming": 30, "diverging": 30, "imminent": 18, "acting": 90}

# Instrument complexes with a polarity sign per member. polarity * (+1 bull / -1 bear)
# yields a normalized "underlying" direction; two active theses in the same complex
# CONTRADICT when their normalized directions have opposite sign. Hand-maintained and
# deliberately small (do NOT reuse the coarse sector_map.yaml).
_COMPLEX_POLARITY = {
    "equity_market": {"SPX": 1, "NDX": 1, "DJIA": 1, "RUT": 1, "SPY": 1, "QQQ": 1},
    "semis_tech": {"SMH": 1, "SOX": 1, "IGV": 1, "NVDA": 1, "MU": 1, "AVGO": 1,
                   "SMCI": 1, "AMD": 1, "TECHNOLOGY": 1},
    "volatility": {"VIX": -1, "UVXY": -1, "VXX": -1, "UVIX": -1, "SVXY": 1},
    "rates": {"YIELDS": 1, "TNX": 1, "BONDS": -1, "TLT": -1},
}


def _enabled() -> bool:
    return bool(cfg.get("wolf.staleness.enabled", False))


def _cap_days(stage: str) -> float:
    caps = cfg.get("wolf.staleness.cap_days", _DEFAULT_CAPS) or _DEFAULT_CAPS
    return float(caps.get(stage, _DEFAULT_CAPS.get(stage, 30)))


def _real_reaffirm_ts(evlog: list[dict], created_at: float) -> float:
    """Timestamp of the last EXPLICIT same-direction reaffirmation in the evidence log.

    "Explicit" = the entry reached stage imminent/acting OR carried intent started/adding.
    Routine forming/watching mentions (and misreads) do NOT count, so they cannot keep a
    dead thesis fresh. Falls back to the earliest evidence ts, else created_at."""
    real = [e.get("ts") for e in evlog
            if isinstance(e.get("ts"), (int, float))
            and (e.get("to") in ("imminent", "acting")
                 or e.get("intent") in ("started", "adding"))]
    if real:
        return max(real)
    all_ts = [e.get("ts") for e in evlog if isinstance(e.get("ts"), (int, float))]
    return min(all_ts) if all_ts else created_at


def _normalized_dirs(scope_key: str, direction: str) -> dict[str, int]:
    """Return {complex_name: normalized_sign} for every complex this scope belongs to.
    normalized_sign = polarity * (+1 bull / -1 bear)."""
    side = 1 if direction == "bull" else -1
    out: dict[str, int] = {}
    for cx, members in _COMPLEX_POLARITY.items():
        if scope_key in members:
            out[cx] = members[scope_key] * side
    return out


def _has_higher_conviction_contradiction(thesis: dict, actives: list[dict]) -> str | None:
    """If a HIGHER-conviction (imminent/acting) active thesis in the same complex holds the
    opposite polarity-normalized direction, return a short reason string, else None."""
    my_norm = _normalized_dirs(thesis["scope_key"], thesis["direction"])
    if not my_norm:
        return None
    for other in actives:
        if other["id"] == thesis["id"]:
            continue
        if _STAGE_RANK.get(other.get("stage", "forming"), 0) < _STAGE_RANK["imminent"]:
            continue  # only a higher-conviction thesis can contradict
        other_norm = _normalized_dirs(other["scope_key"], other["direction"])
        for cx, sign in my_norm.items():
            if cx in other_norm and other_norm[cx] == -sign:
                return f"contradicted by {other['scope_key']} {other['direction']} ({cx})"
    return None


def _target_reached(thesis: dict) -> bool:
    """True if the thesis has a price 'target' the proxy has crossed in its favor.
    Blocking yfinance fetch (run in an executor by the caller)."""
    try:
        levels = json.loads(thesis.get("key_levels_json") or "[]")
    except Exception:
        return False
    targets = [float(lv["price"]) for lv in levels
               if isinstance(lv, dict) and lv.get("role") == "target" and "price" in lv]
    if not targets:
        return False
    sym = proxy_symbol(thesis["scope_type"], thesis["scope_key"])
    if not sym:
        return False
    from consensus_engine.analysis.wolf_outcomes import _fetch_proxy_series
    try:
        evlog = json.loads(thesis.get("evidence_log_json") or "[]")
    except Exception:
        evlog = []
    anchor_ts = _real_reaffirm_ts(evlog, thesis.get("created_at", time.time()))
    series = _fetch_proxy_series(sym, anchor_ts)
    if not series or not series.get("latest_close"):
        return False
    last = float(series["latest_close"])
    if thesis["direction"] == "bull":
        return any(last >= t for t in targets)
    return any(last <= t for t in targets)


async def run_staleness_sweep(now: float | None = None, dry_run: bool = False) -> dict:
    """Evaluate every active thesis; demote stale ones to 'stale_review'.

    Returns {"checked": n, "demoted": [ {id, scope_key, direction, stage, reason,
    age_days} ... ]}. With dry_run=True no DB writes happen (validation against history)."""
    now = now or time.time()
    actives = await db.get_active_theses()
    target_stale_days = float(cfg.get("wolf.staleness.target_reached_stale_days", 7))
    contra_stale_days = float(cfg.get("wolf.staleness.contradiction_stale_days", 14))
    contra_enabled = bool(cfg.get("wolf.staleness.contradiction_enabled", True))
    loop = asyncio.get_running_loop()

    demoted: list[dict] = []
    for t in actives:
        try:
            evlog = json.loads(t.get("evidence_log_json") or "[]")
        except Exception:
            evlog = []
        reaffirm_ts = _real_reaffirm_ts(evlog, t.get("created_at", now))
        age_days = (now - reaffirm_ts) / _DAY
        stage = t.get("stage", "forming")

        reason: str | None = None
        if age_days >= _cap_days(stage):
            reason = f"age_cap {age_days:.0f}d > {_cap_days(stage):.0f}d ({stage})"
        elif contra_enabled and age_days >= contra_stale_days:
            c = _has_higher_conviction_contradiction(t, actives)
            if c:
                reason = f"{c}, stale {age_days:.0f}d"
        if reason is None and age_days >= target_stale_days:
            try:
                if await loop.run_in_executor(None, _target_reached, t):
                    reason = f"target reached, stale {age_days:.0f}d"
            except Exception as e:
                log.debug("staleness: target check failed for #%s: %s", t.get("id"), e)

        if reason is None:
            continue

        demoted.append({"id": t["id"], "scope_key": t["scope_key"],
                        "direction": t["direction"], "stage": stage,
                        "reason": reason, "age_days": round(age_days, 1)})
        if dry_run:
            continue
        marker = {"ts": now, "kind": "stale_review", "reason": reason,
                  "age_days": round(age_days, 1), "by": "sweep"}
        evlog.append(marker)
        await db.demote_thesis_stale(t["id"], now, json.dumps(evlog[-20:]))
        log.info("wolf_staleness: demoted #%d %s %s -> stale_review (%s)",
                 t["id"], t["scope_key"], t["direction"], reason)

    # Drop beneficiary rows now orphaned by the demotions (demoted theses are no longer
    # status='active', so prune covers them alongside flipped/invalidated ones).
    if demoted and not dry_run:
        try:
            await db.prune_beneficiary_orphans()
        except Exception as e:
            log.debug("staleness: beneficiary prune skipped: %s", e)

    return {"checked": len(actives), "demoted": demoted}


async def revive_stale_thesis(thesis_id: int, now: float | None = None) -> bool:
    """Manual override: bring a stale_review thesis back to active. Returns True on success."""
    now = now or time.time()
    rows = await db.get_stale_review_theses()
    row = next((r for r in rows if r["id"] == thesis_id), None)
    if not row:
        return False
    try:
        evlog = json.loads(row.get("evidence_log_json") or "[]")
    except Exception:
        evlog = []
    evlog.append({"ts": now, "kind": "revived", "by": "manual"})
    await db.revive_thesis(thesis_id, now, json.dumps(evlog[-20:]))
    log.info("wolf_staleness: manually revived #%d %s %s",
             thesis_id, row["scope_key"], row["direction"])
    return True


async def staleness_sweep_loop(stop_event) -> None:
    """Daily background loop. No-op while wolf.staleness.enabled is false."""
    interval = int(cfg.get("intervals.wolf_staleness_loop", 86400))
    while not stop_event.is_set():
        try:
            if _enabled():
                summary = await run_staleness_sweep()
                if summary["demoted"]:
                    log.info("wolf_staleness sweep: demoted %d/%d theses",
                             len(summary["demoted"]), summary["checked"])
        except Exception as e:
            log.error("staleness_sweep_loop error: %s", e, exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
