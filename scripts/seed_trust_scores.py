"""Apply editorial trust scores from config/channel_trust_seed.yaml to youtube_channels.

CEF-1 backfill (W2): per the discover plan, production `youtube_channels.trust_score`
is uniformly 1.0 across 13 seeded channels, so the C-C3 curated predicate
`trust_score >= 0.7 AND approved = 1` is operationally inert until the operator
differentiates. This script reads the YAML file (operator-authored) and writes
the resulting scores to the live DB. Idempotent.

Usage:
    python3 -m scripts.seed_trust_scores [--db PATH] [--config PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent

DEFAULT_DB = _REPO / "consensus.db"
DEFAULT_CONFIG = _REPO / "config" / "channel_trust_seed.yaml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_trust_scores")


def apply_seed(db_path: Path, config_path: Path, dry_run: bool) -> int:
    if not db_path.exists():
        log.error("db not found: %s", db_path)
        return 0
    if not config_path.exists():
        log.error("config not found: %s", config_path)
        return 0

    with config_path.open() as f:
        seed = yaml.safe_load(f) or {}
    channels = seed.get("channels", [])
    if not channels:
        log.warning("no channels in seed file %s", config_path)
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        existing = {
            row["channel_id"]: float(row["trust_score"])
            for row in conn.execute(
                "SELECT channel_id, trust_score FROM youtube_channels"
            )
        }
        updates: list[tuple[float, str]] = []
        for entry in channels:
            cid = (entry.get("channel_id") or "").strip()
            if not cid:
                continue
            target = float(entry.get("trust_score", seed.get("default_trust", 1.0)))
            current = existing.get(cid)
            if current is None:
                log.warning("channel %s not registered — skipping", cid)
                continue
            if abs(current - target) < 1e-9:
                continue
            updates.append((target, cid))
            log.info("  %s: %.2f → %.2f", cid, current, target)

        log.info("planned updates: %d", len(updates))
        if dry_run:
            log.info("dry-run: no writes")
            return len(updates)
        if updates:
            conn.executemany(
                "UPDATE youtube_channels SET trust_score = ? WHERE channel_id = ?",
                updates,
            )
            conn.commit()
            log.info("applied %d trust-score updates", len(updates))
        return len(updates)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    n = apply_seed(args.db, args.config, args.dry_run)
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
