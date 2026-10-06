#!/usr/bin/env python3
"""Daily watch on the member dashboard's database size (TODO #121).

Alerts #errors (on change only) when the dashboard database is over 300 MB, grew more
than 50 MB since the last check, or the disk drops under 15% free. Each run appends one
line to the size log so growth can be read back later.
"""
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WEB = Path('/var/lib/member-dashboard/web/web.sqlite3')
LOG = Path('/home/openclaw/.openclaw/state/member-dashboard-size.jsonl')
MAX_MB, MAX_DAY_GROWTH_MB, MIN_FREE_PCT = 300, 50, 15
ALERT_KEY = 'member_dashboard_db_size'


def last_size_mb():
    try:
        return json.loads(LOG.read_text().strip().splitlines()[-1])['db_mb']
    except (OSError, IndexError, ValueError, KeyError):
        return None


def main():
    # The folder is traverse-only for this user: stat the files by name, never list it.
    db_mb = sum(p.stat().st_size for p in (WEB, Path(f'{WEB}-wal'), Path(f'{WEB}-shm')) if p.exists()) / 1048576
    disk = shutil.disk_usage('/')
    free_pct = 100 * disk.free / disk.total
    previous = last_size_mb()
    growth = None if previous is None else db_mb - previous
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as out:
        out.write(json.dumps({'ts': int(time.time()), 'db_mb': round(db_mb, 1), 'free_pct': round(free_pct, 1)}) + '\n')
    problems = []
    if db_mb > MAX_MB: problems.append(f'the dashboard database is {db_mb:.0f} MB (limit {MAX_MB} MB)')
    if growth is not None and growth > MAX_DAY_GROWTH_MB:
        problems.append(f'it grew {growth:.0f} MB since yesterday (limit {MAX_DAY_GROWTH_MB} MB)')
    if free_pct < MIN_FREE_PCT: problems.append(f'the server disk is only {free_pct:.0f}% free (minimum {MIN_FREE_PCT}%)')
    print(f'dashboard db {db_mb:.1f} MB, growth {growth if growth is None else round(growth, 1)} MB, disk free {free_pct:.0f}%')

    async def report():
        from consensus_engine import db
        from consensus_engine.alerts.ops_alert import report_ops_state
        await db.init_db()
        try:
            await report_ops_state(
                ALERT_KEY, down=bool(problems), title='Member dashboard disk use',
                detail='; '.join(problems).capitalize() + '.' if problems else '',
                fix='Claude: find which dashboard table is growing (scripts/member_dashboard_size_check.py).',
                confirm_after_s=0)  # Once-a-day check: alert on the first bad reading.
        finally:
            await db.close_db()

    asyncio.run(report())


if __name__ == '__main__':
    main()
