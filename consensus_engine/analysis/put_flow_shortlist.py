"""Extreme PUT-flow morning shortlist (TODO #96) — the frozen selection rule.

What this is, in plain words: yesterday the options scanner saw a burst of PUT
trading in some stocks that was huge compared with how many of those contracts
were already open. That burst — extreme PUT ACTIVITY, whoever was on which side
of it — has measured predictive value. This module turns yesterday's bursts into
at most four names to watch this morning.

The measured edge is activity, NOT proven PUT buying. Whether a particular print
was bought or sold is recorded and shown, but it does not pick the candidates.

The trade it supports is a PAIR: equal dollars SHORT the stock and LONG SPY,
entered at the first print at or after 6:35 a.m. Pacific and closed at the first
print at or after 6:35 a.m. Pacific four trading sessions later.

The rule below is FROZEN. It is the exact rule that was tested on stored data
(see .omc/research/extreme-put-flow-morning-shortlist/). Changing a number here
invalidates that test, so do not tune it without redoing the test.

Evidence, 2026-06-01 → 2026-08-14, 181 trades after costs:
  average +1.83%, 65.2% of trades made money, profit factor 2.01.
"""

from __future__ import annotations

import logging

from consensus_engine import db
from consensus_engine import config as cfg

log = logging.getLogger(__name__)

# --- the frozen rule -------------------------------------------------------
MIN_VOL_OI = 50.0            # day volume divided by open interest
MIN_VOLUME = 500             # contracts traded that day
MIN_PREMIUM_USD = 250_000.0  # dollars that changed hands
MAX_PER_DATE = 4             # a maximum, never a target — zero is allowed
HOLD_SESSIONS = 4            # trading sessions from entry to exit
ROUND_TRIP_COST_PCT = 0.25   # conservative cost for the whole round trip
ENTRY_TIME_PT = "06:35"      # five minutes after the market opens
WATCH_TIME_PT = "06:15"

# Index and sector funds. Shorting one of these against SPY is not the trade
# this was measured on, so they never appear on the shortlist. This is the
# project's existing fund list (scripts/grade_options_flow.py).
FUND_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "SOXX", "SMH", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "GLD", "SLV", "TLT", "USO", "ARKK", "VOO", "RSP", "IGV", "XLE", "XLF",
    "XLK", "XLV", "VGT", "SCHD", "KORU", "EWY",
})

BENCHMARK = "SPY"

# One row per (contract, market date), taken at its EARLIEST detection — the
# scanner re-sees a live contract every poll cycle, so raw rows over-count the
# same burst about twelve times. `market_date` uses the same fixed -5h offset as
# the rest of the flow tables so the live job and the stored test agree exactly.
_EVENTS_SQL = """
SELECT f.id AS flow_id, f.ticker, f.side, f.contract_symbol, f.strike, f.expiry,
       f.volume, f.open_interest, f.vol_oi_ratio, f.premium_usd, f.spot,
       f.detected_at, f.flow_side, f.flow_side_note,
       date(f.detected_at, 'unixepoch', '-5 hours') AS market_date
FROM options_flow f
JOIN (
    SELECT contract_symbol,
           date(detected_at, 'unixepoch', '-5 hours') AS md,
           MIN(detected_at) AS first_ts
    FROM options_flow
    GROUP BY contract_symbol, md
) first ON f.contract_symbol = first.contract_symbol
       AND f.detected_at = first.first_ts
WHERE f.spot > 0
  AND date(f.detected_at, 'unixepoch', '-5 hours') = ?
"""


def sort_key(row: dict) -> tuple:
    """Biggest burst first. Ticker, then contract, then row id break ties, so the
    same stored rows always produce the same shortlist in the same order."""
    return (-(row.get("vol_oi_ratio") or 0.0),
            row.get("ticker") or "",
            row.get("contract_symbol") or "",
            row.get("flow_id") or 0)


def qualifies(row: dict) -> bool:
    """Does one flow event clear every frozen gate?

    The newer BUY/SELL tag is deliberately NOT used. Its history is too short to
    trust as a filter, and the tested rule did not use it.
    """
    return ((row.get("side") or "").upper() == "PUT"
            and (row.get("ticker") or "").upper() not in FUND_TICKERS
            and (row.get("vol_oi_ratio") or 0.0) >= MIN_VOL_OI
            and (row.get("volume") or 0) >= MIN_VOLUME
            and (row.get("premium_usd") or 0.0) >= MIN_PREMIUM_USD)


# --- the buy/sell label (display and measurement only) ---------------------
# These are the four values the shortlist ever stores. They come straight from
# the #options-flow scanner's classify_flow_side(), which is the ONLY classifier
# in this project. Nothing here re-decides a side.
SIDE_BUCKETS = ("BUY", "SELL", "AMBIGUOUS", "MISSING")


def side_bucket(flow_side: str | None) -> str:
    """Which of the four reporting buckets a stored label belongs to.

    A row collected before the label existed has no label. It is MISSING, and it
    stays MISSING — it is never turned into BUY, SELL, or AMBIGUOUS by guessing.
    """
    v = (flow_side or "").strip().upper()
    return v if v in ("BUY", "SELL", "AMBIGUOUS") else "MISSING"


def side_label(flow_side: str | None, flow_side_note: str | None = None) -> str:
    """The plain-words option-side label shown on a card.

    BUY  = the trade printed at or near the ask, or above it.
    SELL = the trade printed at or near the bid, or below it.
    AMBIGUOUS = the price did not clearly identify a side.
    MISSING   = this burst was recorded before the label existed.
    """
    bucket = side_bucket(flow_side)
    note = (flow_side_note or "").strip()
    tail = f" ({note})" if note else ""
    if bucket == "BUY":
        return f"PUT BUY — printed at or above the ask{tail}"
    if bucket == "SELL":
        return f"PUT SELL — printed at or below the bid{tail}"
    if bucket == "AMBIGUOUS":
        return "side unclear — the price did not say which"
    return "side not recorded — older than the label"


def short_problem(q: dict | None) -> str:
    """Why this stock must not be shorted — or "" when Schwab raised no objection.

    Only an explicit "no" from Schwab rejects. A missing field means Schwab did
    not answer, and an unanswered question is never treated as a No.
    """
    if not q:
        return ""
    if q.get("shortable") is False:
        return "Schwab says the stock is not shortable"
    return ""


def select(events: list[dict], max_per_date: int = MAX_PER_DATE) -> list[dict]:
    """Apply the frozen rule to one signal date's flow events.

    Returns zero to `max_per_date` rows, each carrying `rank` (1 is the biggest
    burst). Zero is a normal, expected answer on a quiet day.
    """
    pool = [e for e in events if qualifies(e)]

    # One event per stock: a stock with six qualifying contracts still gets one
    # vote, and it is its biggest burst that votes.
    best: dict[str, dict] = {}
    for e in pool:
        tk = e["ticker"]
        if tk not in best or sort_key(e) < sort_key(best[tk]):
            best[tk] = e

    ranked = sorted(best.values(), key=sort_key)[:max_per_date]
    return [{**e, "rank": i} for i, e in enumerate(ranked, start=1)]


async def events_for_date(signal_date: str) -> list[dict]:
    """Every distinct flow burst recorded on one market date."""
    conn = await db.get_db()
    cur = await conn.execute(_EVENTS_SQL, (signal_date,))
    return [dict(r) for r in await cur.fetchall()]


async def shortlist_for_date(signal_date: str,
                             max_per_date: int | None = None) -> list[dict]:
    """The frozen shortlist for one completed session. Reads stored rows only."""
    if max_per_date is None:
        max_per_date = int(cfg.get("put_flow_shortlist.max_per_date", MAX_PER_DATE))
    return select(await events_for_date(signal_date), max_per_date=max_per_date)


def next_session(signal_date: str) -> str:
    """The first trading session AFTER `signal_date`.

    Holiday- and weekend-aware, so a Friday signal enters on Monday and a signal
    before a market holiday skips it.
    """
    from datetime import date, timedelta
    from consensus_engine.utils.time_context import session_dates
    d = date.fromisoformat(signal_date)
    for s in session_dates(d + timedelta(days=1), d + timedelta(days=14)):
        return s.isoformat()
    raise ValueError(f"no trading session found after {signal_date}")


def session_plus(entry_session: str, n: int = HOLD_SESSIONS) -> str:
    """The session `n` trading days after `entry_session`."""
    from datetime import date, timedelta
    from consensus_engine.utils.time_context import session_dates
    d = date.fromisoformat(entry_session)
    ahead = session_dates(d + timedelta(days=1), d + timedelta(days=n * 3 + 21))
    if len(ahead) < n:
        raise ValueError(f"cannot find {n} sessions after {entry_session}")
    return ahead[n - 1].isoformat()


def quote_problem(q: dict | None, now_ts: float,
                  max_age_sec: int = 300) -> str:
    """Why this quote must not be traded on — or "" when it is usable.

    Four ways a quote is unusable: it is missing, its last trade is old, the bid
    is above the ask (a crossed, nonsense market), or the stock is halted.
    """
    if not q:
        return "no quote returned"
    price = q.get("c")
    if not price or price <= 0:
        return "no usable price"
    status = str(q.get("halt_status") or "unknown").lower()
    if status not in ("normal", "unknown"):
        return f"stock is {status}"
    ts = q.get("t") or 0
    if not ts:
        return "quote has no trade time"
    age = now_ts - ts
    if age > max_age_sec:
        return f"quote is {int(age)}s old"
    bid, ask = q.get("bid") or 0.0, q.get("ask") or 0.0
    if bid > 0 and ask > 0 and bid > ask:
        return "crossed market (bid above ask)"
    return ""


def pair_net_pct(stock_entry: float, stock_exit: float,
                 spy_entry: float, spy_exit: float,
                 cost_pct: float = ROUND_TRIP_COST_PCT) -> float:
    """Result of the equal-dollar pair, in percent, after costs.

    Short the stock, long SPY. If the stock falls further than SPY the number is
    positive. The cost is subtracted, so it always makes the result worse.
    """
    stock_ret = stock_exit / stock_entry - 1.0
    spy_ret = spy_exit / spy_entry - 1.0
    return 100.0 * (spy_ret - stock_ret) - cost_pct
