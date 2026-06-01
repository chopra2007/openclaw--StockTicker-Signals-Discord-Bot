"""Stateful thesis tracker for the Wolf macro-brain (TODO #20, phase 1).

Ingests a validated WolfExtraction and maintains `macro_theses`:
  - match an existing active thesis (same scope + direction) or create a new one
  - advance the stage (forming -> diverging -> imminent -> acting), with DOWNGRADE
    allowed and an explicit "Wolf dropped it" -> invalidate path
  - an opposite-direction call on the same instrument invalidates the old one (flip)
  - level-less theses are capped to the 'surface' tier (no @-ping / no confluence)
  - sprawl caps per scope_type: when full, evict the oldest least-recently-updated

Emits stage-change / new-thesis events for the alert layer. NO key-level-break
price monitoring in phase 1 (deferred — no Wolf price-watcher yet).
"""
from __future__ import annotations

import json
import logging
import time

from consensus_engine import config as cfg, db

log = logging.getLogger(__name__)

_STAGE_ORDER = ["forming", "diverging", "imminent", "acting"]

# Per-scope active-thesis sprawl caps.
_DEFAULT_CAPS = {"market": 10, "sector": 20, "stock": 30, "asset": 12}


def _stage_rank(stage: str) -> int:
    return _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else 0


def _caps() -> dict:
    return cfg.get("wolf.sprawl_caps", _DEFAULT_CAPS) or _DEFAULT_CAPS


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


def _merge_levels(existing_json: str, new_levels: list[dict]) -> tuple[str, int]:
    """Merge new levels into existing (dedupe by rounded price). Returns (json, has_levels)."""
    try:
        existing = json.loads(existing_json) if existing_json else []
    except Exception:
        existing = []
    have = {round(float(l["price"]), 2) for l in existing if "price" in l}
    for lv in new_levels:
        p = round(float(lv["price"]), 2)
        if p not in have:
            existing.append(lv)
            have.add(p)
    return json.dumps(existing), (1 if existing else 0)


async def ingest(extraction: dict) -> list[dict]:
    """Ingest one WolfExtraction. Returns a list of events for the alert layer:

        {"kind": "new"|"stage_change", "thesis_id", "scope_type", "scope_key",
         "direction", "old_stage"|None, "stage", "has_levels", "snippet"}
    """
    now = float(extraction.get("ts") or time.time())
    events: list[dict] = []

    for th in extraction.get("theses", []):
        scope_type = th["scope_type"]
        scope_key = th["scope_key"]
        direction = th["direction"]
        stage = th["stage"]
        new_levels = th.get("levels", [])
        snippet = th.get("snippet", "")

        # 1. Opposite-direction active thesis on the same instrument => flip (invalidate old).
        opposite = "bear" if direction == "bull" else "bull"
        opp = await db.get_active_thesis(scope_type, scope_key, opposite)
        if opp:
            await db.invalidate_thesis(opp["id"], now)
            log.info("wolf_theses: flip — invalidated %s %s %s (#%d), now %s",
                     scope_type, scope_key, opposite, opp["id"], direction)

        existing = await db.get_active_thesis(scope_type, scope_key, direction)

        if existing:
            old_stage = existing["stage"]
            # Allow forward AND downgrade; pick the incoming stage (Wolf's latest read).
            new_stage = stage
            levels_json, has_levels = _merge_levels(existing["key_levels_json"], new_levels)
            # append evidence
            try:
                evlog = json.loads(existing["evidence_log_json"]) if existing["evidence_log_json"] else []
            except Exception:
                evlog = []
            evlog.append({"ts": now, "from": old_stage, "to": new_stage, "snippet": snippet})
            evlog = evlog[-20:]  # cap history
            await db.update_thesis(existing["id"], new_stage, levels_json, has_levels,
                                   json.dumps(evlog), now)
            if new_stage != old_stage:
                events.append({
                    "kind": "stage_change", "thesis_id": existing["id"],
                    "scope_type": scope_type, "scope_key": scope_key, "direction": direction,
                    "old_stage": old_stage, "stage": new_stage,
                    "has_levels": has_levels, "snippet": snippet,
                })
        else:
            # 2. New thesis — enforce sprawl cap first.
            await _enforce_sprawl_cap(scope_type, now)
            levels_json = json.dumps(new_levels)
            has_levels = 1 if new_levels else 0
            evlog = json.dumps([{"ts": now, "from": None, "to": stage, "snippet": snippet}])
            tid = await db.insert_thesis(
                scope_type, scope_key, direction, stage, levels_json,
                None, has_levels, evlog, now,
            )
            events.append({
                "kind": "new", "thesis_id": tid,
                "scope_type": scope_type, "scope_key": scope_key, "direction": direction,
                "old_stage": None, "stage": stage,
                "has_levels": has_levels, "snippet": snippet,
            })

    return events
