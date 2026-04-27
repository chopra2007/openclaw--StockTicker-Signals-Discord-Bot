"""Feature-flag helpers for runtime state reads and audit logging.

Flip workflow is YAML-only: change config/consensus.yaml features.<name>.enabled,
then restart the service. This module provides read access + audit trail.
"""
import logging
import time

from consensus_engine import config as cfg, db

log = logging.getLogger(__name__)

KNOWN_FEATURES = [
    "contradiction_penalty",
    "regime_classifier",
    "form4_cluster",
    "sector_confirmation",
    "analyst_herding",
    "cross_source_consolidation",
]


async def read_feature_state(name: str) -> bool:
    """Return current enabled state for feature `name` from config."""
    return bool(cfg.get(f"features.{name}.enabled", False))


async def flip_feature(name: str, new_state: bool, reason: str = "") -> None:
    """Write an audit row. Does NOT change config — YAML-only workflow.

    Call this after manually updating config/consensus.yaml to record the
    operator intent. The runtime picks up config on next read (no restart needed
    for audit; restart needed for the actual enable/disable to take effect).
    """
    conn = await db.get_db()
    prior = await read_feature_state(name)
    await conn.execute(
        """INSERT INTO feature_flag_audit
           (feature, prior_state, new_state, reason, flipped_by, flipped_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, int(prior), int(new_state), reason, "system", time.time()),
    )
    await conn.commit()
    log.info("feature_flag_audit: %s %s→%s reason=%r", name, prior, new_state, reason)


async def audit_history(limit: int = 20) -> list[dict]:
    """Return last `limit` audit rows as dicts."""
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM feature_flag_audit ORDER BY flipped_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows] if rows else []
