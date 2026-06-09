"""Stateful thesis tracker for the Wolf macro-brain (TODO #20, phase 1).

Ingests a validated WolfExtraction and maintains `macro_theses`:
  - collapse same-thread sub-theses in ONE email into one merged thesis (R2),
  - match an existing active thesis (same scope + direction) or create a new one,
  - advance the stage (forming -> diverging -> imminent -> acting), with DOWNGRADE
    allowed and an explicit "Wolf dropped it" -> invalidate path,
  - an opposite-direction call on the same instrument invalidates the old one (flip),
  - roll a conviction history onto evidence_log_json (six derived keys, no schema bump),
  - emit a `conviction_update` event ONLY on a material STRUCTURAL escalation (R4/R5);
    first sighting emits `new`; routine reaffirmation / downgrade is QUIET (no event).

The event vocabulary is `new` | `conviction_update` (the bare `stage_change` is gone
for tracked threads — R4). NO key-level-break price monitoring in phase 1.
"""
from __future__ import annotations

import json
import logging
import time

from consensus_engine import config as cfg, db
from consensus_engine.analysis import wolf_conviction as conv

log = logging.getLogger(__name__)

_STAGE_ORDER = ["forming", "diverging", "imminent", "acting"]
_INTENT_ORDER = ["none", "watching", "looking", "started", "adding"]

# Per-scope active-thesis sprawl caps.
_DEFAULT_CAPS = {"market": 10, "sector": 20, "stock": 30, "asset": 12}

_DAY_SECONDS = 86400.0


def _stage_rank(stage: str) -> int:
    return _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else 0


def _intent_rank(intent: str) -> int:
    return _INTENT_ORDER.index(intent) if intent in _INTENT_ORDER else 0


def _caps() -> dict:
    return cfg.get("wolf.sprawl_caps", _DEFAULT_CAPS) or _DEFAULT_CAPS


def _window_days() -> int:
    return int(cfg.get("wolf.conviction.window_days", 10) or 10)


def _traj_threshold() -> int:
    """Config-tunable score-delta threshold for the 'stable' band (absent a structural
    change). Wired from wolf.conviction.trajectory_threshold."""
    return int(cfg.get("wolf.conviction.trajectory_threshold", 8) or 8)


async def _enforce_sprawl_cap(scope_type: str, now: float) -> None:
    """If a scope is at its active cap, evict the oldest least-recently-updated thesis."""
    cap = _caps().get(scope_type, 20)
    count = await db.count_active_theses(scope_type)
    if count >= cap:
        oldest = await db.get_oldest_active_thesis(scope_type)
        if oldest:
            await db.invalidate_thesis(oldest["id"], now)
            log.info("wolf_theses: sprawl cap hit for %s (%d) — evicted oldest thesis #%d (%s %s)",
                     scope_type, count, oldest["id"], oldest["scope_key"], oldest["direction"])


async def _merge_levels(existing_json: str, new_levels: list[dict], scope_key: str) -> tuple[str, int]:
    """Merge new levels into existing (dedupe by rounded price). Returns (json, has_levels).

    Item C (deep-dive-2026-06-08): DROP an out-of-range new level at the door (NVDA 850 on a
    $208 stock) so a poisoned level is never stored — it would re-leak on every later display
    and feed conviction scoring. Existing stored levels are left as-is (already filtered at
    display); only NEW appends are gated."""
    from consensus_engine.analysis.level_display_sanity import classify_level, LevelVerdict
    try:
        existing = json.loads(existing_json) if existing_json else []
    except Exception:
        existing = []
    have = {round(float(l["price"]), 2) for l in existing if "price" in l}
    for lv in new_levels:
        # classify_level fetches+caches the quote per ticker (60s TTL), shared with display.
        if await classify_level(scope_key, lv["price"]) is LevelVerdict.DROP:
            continue
        p = round(float(lv["price"]), 2)
        if p not in have:
            existing.append(lv)
            have.add(p)
    return json.dumps(existing), (1 if existing else 0)


def _collapse_theses(theses: list[dict]) -> list[dict]:
    """R2: collapse same-thread sub-theses (same scope_type/scope_key/direction) into
    ONE merged thesis so one email = at most one evidence entry per thread.

    stage = MAX rank; intent = MAX rank; timeframes = UNION; levels = merged+deduped;
    snippet/conviction_phrase = from the MAX-stage sub-thesis.
    """
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for th in theses:
        key = (th["scope_type"], th["scope_key"], th["direction"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(th)

    merged: list[dict] = []
    for key in order:
        group = groups[key]
        # the MAX-stage sub-thesis (ties → first) provides snippet/phrase
        top = max(group, key=lambda t: _stage_rank(t.get("stage", "forming")))
        best_stage = max(_stage_rank(t.get("stage", "forming")) for t in group)
        best_intent = max(_intent_rank(t.get("position_intent", "none")) for t in group)
        tf_raw: list[str] = []
        chart_tf_raw: list[str] = []
        for t in group:
            tf_raw.extend(t.get("timeframes", []) or [])
            chart_tf_raw.extend(t.get("chart_timeframes", []) or [])
        levels: list[dict] = []
        have: set[float] = set()
        for t in group:
            for lv in t.get("levels", []) or []:
                try:
                    p = round(float(lv["price"]), 2)
                except (KeyError, TypeError, ValueError):
                    continue
                if p not in have:
                    levels.append(lv)
                    have.add(p)
        merged.append({
            "scope_type": key[0],
            "scope_key": key[1],
            "direction": key[2],
            "stage": _STAGE_ORDER[best_stage],
            "position_intent": _INTENT_ORDER[best_intent],
            "timeframes": tf_raw,
            "chart_timeframes": chart_tf_raw,
            "levels": levels,
            "snippet": top.get("snippet", ""),
            "conviction_phrase": top.get("conviction_phrase"),
            # the trade setup from the top sub-thesis, else any sub-thesis that has one
            "setup": next((t.get("setup") for t in [top, *group] if t.get("setup")), None),
        })
    return merged


def _distinct_day_count(evlog: list[dict], now: float, window_days: int) -> int:
    """Distinct calendar-ish days (by floor(ts/86400)) with an entry in the trailing
    window, INCLUDING the current entry's day (R5: mention frequency = distinct days)."""
    cutoff = now - window_days * _DAY_SECONDS
    days = {int(e["ts"] // _DAY_SECONDS) for e in evlog if e.get("ts", 0) >= cutoff}
    days.add(int(now // _DAY_SECONDS))
    return len(days)


async def ingest(extraction: dict, source_id: str | None = None) -> list[dict]:
    """Ingest one WolfExtraction. Returns a list of events for the alert layer:

        {"kind": "new"|"conviction_update", "thesis_id", "scope_type", "scope_key",
         "direction", "old_stage"|None, "stage", "has_levels", "snippet",
         "tf", "intent", "conv", "traj", "phrase"}

    `source_id` (the source Gmail message id) makes ingest idempotent per source
    email: each evidence_log entry is stamped with its `src`, and a thesis that
    already carries an entry for this `source_id` is skipped. A crash between
    ingest and the wolf_emails_processed ledger write therefore re-ingests to a
    true no-op (Codex BLOCKER-3). When None (legacy callers/tests), no stamping
    or dedup happens — exact prior behaviour.
    """
    now = float(extraction.get("ts") or time.time())
    subject = str(extraction.get("subject") or "")[:120]
    events: list[dict] = []

    merged_theses = _collapse_theses(extraction.get("theses", []))

    for th in merged_theses:
        scope_type = th["scope_type"]
        scope_key = th["scope_key"]
        direction = th["direction"]
        stage = th["stage"]
        intent = th.get("position_intent", "none")
        new_levels = th.get("levels", [])
        snippet = th.get("snippet", "")
        phrase = th.get("conviction_phrase")
        tf = conv.normalize_timeframes(th.get("timeframes", []), th.get("chart_timeframes", []))

        # 1. Opposite-direction active thesis on the same instrument => flip (invalidate old).
        opposite = "bear" if direction == "bull" else "bull"
        opp = await db.get_active_thesis(scope_type, scope_key, opposite)
        flipped = opp is not None
        if opp:
            await db.invalidate_thesis(opp["id"], now)
            log.info("wolf_theses: flip — invalidated %s %s %s (#%d), now %s",
                     scope_type, scope_key, opposite, opp["id"], direction)

        existing = await db.get_active_thesis(scope_type, scope_key, direction)

        if existing:
            old_stage = existing["stage"]
            new_stage = stage  # allow forward AND downgrade (Wolf's latest read)
            levels_json, has_levels = await _merge_levels(existing["key_levels_json"], new_levels, scope_key)

            try:
                evlog = json.loads(existing["evidence_log_json"]) if existing["evidence_log_json"] else []
            except Exception:
                evlog = []

            # Idempotence (Codex BLOCKER-3): this source email already contributed
            # an evidence entry to this thesis → re-ingest is a no-op.
            if source_id is not None and any(e.get("src") == source_id for e in evlog):
                continue

            prior = evlog[-1] if evlog else {}
            prior_tf = prior.get("tf", []) or []
            prior_intent = prior.get("intent", "none")
            prior_convs = [e.get("conv", 0) for e in evlog if isinstance(e.get("conv"), int)]

            # structural deltas (R5) — never score/cadence
            stage_up = _stage_rank(new_stage) > _stage_rank(old_stage)
            stage_down = _stage_rank(new_stage) < _stage_rank(old_stage)
            tf_widened = conv.tf_widened(prior_tf, tf)
            intent_up = _intent_rank(intent) > _intent_rank(prior_intent)
            intent_down = _intent_rank(intent) < _intent_rank(prior_intent)

            day_count = _distinct_day_count(evlog, now, _window_days())
            score = conv.conviction_score(new_stage, tf, intent, day_count, json.loads(levels_json))
            traj = conv.trajectory(score, prior_convs, stage_up, stage_down,
                                   intent_up, intent_down, flipped,
                                   threshold=_traj_threshold())

            entry = {
                "ts": now, "from": old_stage, "to": new_stage, "snippet": snippet,
                "subject": subject, "tf": tf, "conv": score, "traj": traj,
                "intent": intent, "phrase": phrase,
            }
            if source_id is not None:
                entry["src"] = source_id
            evlog.append(entry)
            evlog = evlog[-20:]  # cap history
            # Update the trade idea only when this email framed one (latest wins);
            # otherwise leave the thesis's existing setup untouched.
            new_setup = th.get("setup")
            await db.update_thesis(
                existing["id"], new_stage, levels_json, has_levels,
                json.dumps(evlog), now,
                trade_setup_json=json.dumps(new_setup) if new_setup else db._KEEP,
            )

            material = conv.is_material_escalation(stage_up, stage_down, tf_widened,
                                                   intent_up, flipped)
            if material:
                events.append({
                    "kind": "conviction_update", "thesis_id": existing["id"],
                    "scope_type": scope_type, "scope_key": scope_key, "direction": direction,
                    "old_stage": old_stage, "stage": new_stage,
                    "has_levels": has_levels, "snippet": snippet,
                    "tf": tf, "intent": intent, "conv": score, "traj": traj, "phrase": phrase,
                })
            # else QUIET — evidence appended, no post.
        else:
            # 2. New thesis — enforce sprawl cap first.
            await _enforce_sprawl_cap(scope_type, now)
            levels_json = json.dumps(new_levels)
            has_levels = 1 if new_levels else 0
            day_count = 1
            score = conv.conviction_score(stage, tf, intent, day_count, new_levels)
            traj = conv.trajectory(score, [], False, False, False, False, False)  # first → building
            first_entry = {
                "ts": now, "from": None, "to": stage, "snippet": snippet,
                "subject": subject, "tf": tf, "conv": score, "traj": traj,
                "intent": intent, "phrase": phrase,
            }
            if source_id is not None:
                first_entry["src"] = source_id
            evlog = json.dumps([first_entry])
            new_setup = th.get("setup")
            tid = await db.insert_thesis(
                scope_type, scope_key, direction, stage, levels_json,
                None, has_levels, evlog, now,
                trade_setup_json=json.dumps(new_setup) if new_setup else None,
            )
            events.append({
                "kind": "new", "thesis_id": tid,
                "scope_type": scope_type, "scope_key": scope_key, "direction": direction,
                "old_stage": None, "stage": stage,
                "has_levels": has_levels, "snippet": snippet,
                "tf": tf, "intent": intent, "conv": score, "traj": traj, "phrase": phrase,
            })

    return events
