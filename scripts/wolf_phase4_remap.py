#!/usr/bin/env python3
"""One-off (phase-4 #4): canonicalize the live mis-scoped Wolf theses.

The pre-#4 parser filed three macro names as stray ('stock', <name>) threads:
  - NAS100  -> should thread to ('market','NDX')
  - SP-500  -> should thread to ('market','SPX')
  - TRANSPORTS -> should thread to ('market','TRANSPORTS')

Re-scope rows whose canonical (scope_type,scope_key,direction) has NO active row.
Where an active canonical already exists (the partial unique index would block an
UPDATE), mark the stray 'superseded' — a status excluded from BOTH the active
query and the invalidated-scoreboard query (db.py:3074), so it neither blocks the
index nor pollutes the call scoreboard. Idempotent: re-running is a no-op.

Run as the openclaw user (DB is openclaw:openclaw; WAL ownership trap).
"""
import json
import sqlite3
import time

DB = "/home/openclaw/.openclaw/workspace/consensus.db"

# stray_key -> canonical (scope_type, scope_key)
REMAP = {
    "NAS100": ("market", "NDX"),
    "SP-500": ("market", "SPX"),
    "TRANSPORTS": ("market", "TRANSPORTS"),
}


def main() -> int:
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    now = time.time()

    strays = conn.execute(
        "SELECT * FROM macro_theses WHERE scope_type='stock' AND scope_key IN (?,?,?) "
        "AND status='active'",
        tuple(REMAP.keys()),
    ).fetchall()

    if not strays:
        print("no active mis-scoped rows — nothing to do (idempotent).")
        return 0

    # backup before any write
    backup = [dict(r) for r in strays]
    backup_path = "/home/openclaw/.openclaw/workspace/wolf-phase4-remap-backup.json"
    with open(backup_path, "w") as f:
        json.dump(backup, f, indent=2)
    print(f"backed up {len(backup)} stray rows -> {backup_path}")

    try:
        conn.execute("BEGIN")
        for r in strays:
            new_type, new_key = REMAP[r["scope_key"]]
            # is the canonical (type,key,direction) already active?
            clash = conn.execute(
                "SELECT id FROM macro_theses WHERE scope_type=? AND scope_key=? "
                "AND direction=? AND status='active' AND id<>?",
                (new_type, new_key, r["direction"], r["id"]),
            ).fetchone()
            if clash:
                # supersede the duplicate stray (frees the partial unique index;
                # excluded from active + invalidated-scoreboard queries)
                ev = json.loads(r["evidence_log_json"] or "[]")
                ev.append({"ts": now, "note": f"superseded by active canonical id {clash['id']} "
                                               f"({new_type}/{new_key}/{r['direction']}) — phase-4 #4 remap"})
                conn.execute(
                    "UPDATE macro_theses SET status='superseded', evidence_log_json=?, last_updated=? "
                    "WHERE id=?",
                    (json.dumps(ev), now, r["id"]),
                )
                print(f"id {r['id']} {r['scope_key']}/{r['direction']}: SUPERSEDED "
                      f"(active canonical id {clash['id']} exists)")
            else:
                ev = json.loads(r["evidence_log_json"] or "[]")
                ev.append({"ts": now, "note": f"re-scoped stock/{r['scope_key']} -> "
                                               f"{new_type}/{new_key} — phase-4 #4 remap"})
                conn.execute(
                    "UPDATE macro_theses SET scope_type=?, scope_key=?, evidence_log_json=?, last_updated=? "
                    "WHERE id=?",
                    (new_type, new_key, json.dumps(ev), now, r["id"]),
                )
                print(f"id {r['id']} stock/{r['scope_key']}/{r['direction']}: RE-SCOPED -> {new_type}/{new_key}")
        conn.commit()
        print("committed.")
    except Exception as exc:
        conn.rollback()
        print(f"ROLLED BACK on error: {exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
