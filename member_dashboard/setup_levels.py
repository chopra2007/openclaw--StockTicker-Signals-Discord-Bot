"""Trade plan levels for recent bot alerts (Trade setups page, owner request 2026-10-06).

The bot stores no entry/stop/target for its alerts; `!all` derives them live. When the compute
worker is idle it runs the same research calculation (no AI write-up) for the newest alert
ticker without fresh levels and saves buy zone, stop and targets in `setup_levels`.
"""
import dataclasses
import time

WINDOW = 7 * 86400       # Setups older than this are not shown, so not computed.
REFRESH = 6 * 3600       # Levels come from daily candles; recompute at most every 6 hours.
_DIRECTIONS = {'BULLISH': 'long', 'BEARISH': 'short', 'NEUTRAL': 'neutral'}


def next_ticker(con, now):
    """Newest active setup ticker whose levels are missing, older than REFRESH, or older than the alert."""
    row = con.execute(
        "SELECT p.ticker FROM publication_heads h JOIN publications p ON p.id=h.publication_id "
        "LEFT JOIN setup_levels l ON l.ticker=p.ticker "
        "WHERE h.feature='setups' AND h.active=1 AND h.source_id='alert_history' AND p.observed_at>? "
        "AND (l.ticker IS NULL OR l.computed_at<? OR (l.computed_at<p.observed_at AND l.computed_at<?) "
        "OR (l.price IS NULL AND l.computed_at<?)) "  # price is NULL only on a failed attempt
        "ORDER BY p.observed_at DESC LIMIT 1", (now - WINDOW, now - REFRESH, now - 600, now - 600)).fetchone()
    return row[0] if row else None


async def _no_write_up(request):
    return ''


async def refresh_one(store, collector, clock=time.time):
    """Compute and save one ticker's levels. Returns the ticker, or None when nothing is due."""
    from consensus_engine.analysis.research_compute import compute_research
    with store.transaction() as con:
        # Members first: the dashboard's Schwab share is small, so skip while anyone is researching.
        if con.execute('SELECT 1 FROM web_jobs WHERE created_at>? LIMIT 1', (clock() - 120,)).fetchone():
            return None
        ticker = next_ticker(con, clock())
    if ticker is None:
        return None
    try:
        inputs = await collector(ticker)
        services = dataclasses.replace(collector.services(), synthesis=_no_write_up)
        s = (await compute_research(ticker, inputs, services)).structured
        values = (ticker, clock(), _DIRECTIONS.get(s.direction, 'neutral'), s.current_price, s.buy_zone_low,
                  s.buy_zone_high, s.sl, s.tp1, s.tp2, s.tp3)
    except Exception:
        # Data briefly unavailable: save an empty row (no price) that is retried in 10 minutes,
        # so one failing ticker never blocks the others.
        values = (ticker, clock(), 'neutral', None, None, None, None, None, None, None)
    with store.transaction() as con:
        con.execute('INSERT INTO setup_levels(ticker,computed_at,direction,price,entry_low,entry_high,stop,target1,'
                    'target2,target3) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET '
                    'computed_at=excluded.computed_at,direction=excluded.direction,price=excluded.price,'
                    'entry_low=excluded.entry_low,entry_high=excluded.entry_high,stop=excluded.stop,'
                    'target1=excluded.target1,target2=excluded.target2,target3=excluded.target3', values)
    return ticker
