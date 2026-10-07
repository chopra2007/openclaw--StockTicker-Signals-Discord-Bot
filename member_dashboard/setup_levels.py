"""Trade plan levels for recent bot alerts (Trade setups page, owner request 2026-10-06).

The bot stores no entry/stop/target for its alerts. When the compute worker is idle it runs the
same study as Custom Stock Analysis (no AI write-up) for the newest alert ticker without fresh
levels and saves its buy zone, stop and targets in `setup_levels`, so both pages show one plan.
"""
import time
import json

WINDOW = 7 * 86400       # Setups older than this are not shown, so not computed.
REFRESH = 6 * 3600       # Levels come from daily candles; recompute at most every 6 hours.
_DIRECTIONS = {'BULLISH': 'long', 'BEARISH': 'short', 'NEUTRAL': 'neutral'}


def next_ticker(con, now, context_due=False):
    """Newest active setup ticker whose levels are missing, older than REFRESH, or older than the alert."""
    row = con.execute(
        "SELECT p.ticker FROM publication_heads h JOIN publications p ON p.id=h.publication_id "
        "LEFT JOIN setup_levels l ON l.ticker=p.ticker "
        "WHERE h.feature='setups' AND h.active=1 AND h.source_id='alert_history' AND p.observed_at>? "
        "AND (l.ticker IS NULL OR l.computed_at<? OR (l.computed_at<p.observed_at AND l.computed_at<?) "
        "OR (l.price IS NULL AND l.computed_at<?) OR (? AND l.price IS NOT NULL AND l.context_json IS NULL AND l.computed_at<?)) "
        "ORDER BY p.observed_at DESC LIMIT 1", (now - WINDOW, now - REFRESH, now - 600, now - 600, context_due, now - 600)).fetchone()
    return row[0] if row else None


async def refresh_one(store, collector, clock=time.time, retain_context=lambda:False):
    """Compute and save one ticker's levels. Returns the ticker, or None when nothing is due."""
    retain=retain_context()
    with store.transaction() as con:
        if not retain: con.execute('UPDATE setup_levels SET context_json=NULL WHERE context_json IS NOT NULL')
        # Members first: the dashboard's Schwab share is small, so skip while anyone is researching.
        if con.execute('SELECT 1 FROM web_jobs WHERE created_at>? LIMIT 1', (clock() - 120,)).fetchone():
            return None
        ticker = next_ticker(con, clock(),context_due=retain)
    if ticker is None:
        return None
    try:
        study = await collector.study(ticker)
        s, plan = study.result.structured, (study.facts or {}).get('trade_plan')
        targets = [t['price'] for t in plan['targets']] + [None] * 3 if plan else [None] * 3
        display = getattr(study,'display',None)
        # Only Schwab daily closes belong to this cache; other display metadata
        # can have different sources and retention permissions.
        context = {'chart':display['chart']} if display and display.get('chart') and retain_context() else None
        values = (ticker, clock(), _DIRECTIONS.get(s.direction, 'neutral'), study.facts['price'] if study.facts else s.current_price,
                  plan and plan['entry_low'], plan and plan['entry_high'], plan and plan['stop'], *targets[:3], json.dumps(context,allow_nan=False) if context else None)
    except Exception:
        # Data briefly unavailable: save an empty row (no price) that is retried in 10 minutes,
        # so one failing ticker never blocks the others.
        values = (ticker, clock(), 'neutral', None, None, None, None, None, None, None, None)
    with store.transaction() as con:
        con.execute('INSERT INTO setup_levels(ticker,computed_at,direction,price,entry_low,entry_high,stop,target1,'
                    'target2,target3,context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET '
                    'computed_at=excluded.computed_at,direction=excluded.direction,price=excluded.price,'
                    'entry_low=excluded.entry_low,entry_high=excluded.entry_high,stop=excluded.stop,'
                    'target1=excluded.target1,target2=excluded.target2,target3=excluded.target3,context_json=excluded.context_json', values)
    return ticker
