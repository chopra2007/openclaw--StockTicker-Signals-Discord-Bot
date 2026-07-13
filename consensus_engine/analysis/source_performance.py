"""#55 Build C — analyst track-record producer (SHADOW table only).

Grades each analyst handle's directional accuracy from labeled `alert_history`
rows and writes the result to `source_performance_shadow` — the shadow twin of
`source_performance`.

CRITICAL SAFETY INVARIANT
-------------------------
This producer writes ONLY to `source_performance_shadow`. It NEVER touches the
live `source_performance` table. The four live readers of `source_performance`
(`get_analyst_precision`, `get_analyst_precision_lb`, the Bayesian consolidation
prior, and the herding swarm detector) therefore stay cold-start, so populating
the shadow table changes ZERO live alerts. Promotion to the live table is a
separate, soak-gated decision in a future session.

Grading (sign-adjusted by catalyst_type)
-----------------------------------------
A handle is "right" when the price moved in the direction the catalyst implied:
  - bearish catalyst (Analyst Downgrade / Earnings Miss / FDA Rejection):
      hit when price_later < price_at_alert (the stock fell, as implied)
  - otherwise (bullish / neutral catalyst):
      hit when price_later > price_at_alert (the stock rose)

Per `(handle, horizon)` for horizons '1h' (price_1h_later) and '24h'
(price_24h_later): rolling_accuracy = hits / count, sample_count = count.

Horizon honesty: 1h outcomes are near-random; the table stores 1h AND 24h, but
24h is the primary horizon. Never promote on 1h alone.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("consensus_engine.analysis.source_performance")

# Catalyst types whose thesis is that the stock should FALL. A hit for these is a
# downward move. Everything else (bullish or neutral) grades upward = hit.
BEARISH_CATALYSTS: frozenset[str] = frozenset(
    {"Analyst Downgrade", "Earnings Miss", "FDA Rejection"}
)

# (horizon label, alert_history column carrying that horizon's later price)
_HORIZONS: tuple[tuple[str, str], ...] = (
    ("1h", "price_1h_later"),
    ("24h", "price_24h_later"),
)


def _parse_handles(raw: str | None) -> list[str]:
    """Parse the analyst_mentions JSON array into a list of non-empty handles.

    Returns [] for NULL / '' / '[]' / malformed JSON / a non-list payload, so a
    bad row is skipped rather than crashing the producer.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [h for h in parsed if isinstance(h, str) and h.strip()]


def _is_hit(price_at_alert: float, price_later: float, bearish: bool) -> bool:
    """Sign-adjusted directional hit. Bearish thesis → down move is a hit."""
    if bearish:
        return price_later < price_at_alert
    return price_later > price_at_alert


async def compute_source_performance_shadow(conn=None) -> dict:
    """Grade analyst handles from labeled alert_history and upsert the SHADOW table.

    Reads every `alert_history` row that has a non-empty `analyst_mentions` array
    and a valid `price_at_alert`, grades each present horizon (1h/24h) sign-adjusted
    by `catalyst_type`, aggregates per `(handle, horizon)`, and INSERT-OR-REPLACEs
    into `source_performance_shadow`.

    Writes ONLY to `source_performance_shadow`. Returns a coverage summary:
        {"rows_scanned", "handles", "shadow_rows_written", "by_horizon": {...}}
    """
    from consensus_engine.db import get_db

    if conn is None:
        conn = await get_db()

    cur = await conn.execute(
        """SELECT analyst_mentions, catalyst_type, price_at_alert,
                  price_1h_later, price_24h_later
             FROM alert_history
            WHERE analyst_mentions IS NOT NULL
              AND analyst_mentions != ''
              AND analyst_mentions != '[]'
              AND price_at_alert IS NOT NULL
              AND price_at_alert > 0"""
    )
    rows = await cur.fetchall()

    # (handle, horizon) -> [hits, count]
    agg: dict[tuple[str, str], list[int]] = {}
    rows_scanned = 0
    for row in rows:
        handles = _parse_handles(row["analyst_mentions"])
        if not handles:
            continue
        entry = row["price_at_alert"]
        if entry is None or entry <= 0:
            continue
        rows_scanned += 1
        bearish = (row["catalyst_type"] or "") in BEARISH_CATALYSTS
        for horizon, col in _HORIZONS:
            later = row[col]
            if later is None or later <= 0:
                continue
            hit = 1 if _is_hit(float(entry), float(later), bearish) else 0
            for handle in handles:
                slot = agg.setdefault((handle, horizon), [0, 0])
                slot[0] += hit
                slot[1] += 1

    now = time.time()
    by_horizon: dict[str, int] = {}
    for (handle, horizon), (hits, count) in agg.items():
        if count <= 0:
            continue
        accuracy = hits / count
        await conn.execute(
            """INSERT OR REPLACE INTO source_performance_shadow
               (entity_id, horizon, rolling_accuracy, sample_count, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (handle, horizon, accuracy, count, now),
        )
        by_horizon[horizon] = by_horizon.get(horizon, 0) + 1
    await conn.commit()

    handles_total = len({h for (h, _) in agg})
    summary = {
        "rows_scanned": rows_scanned,
        "handles": handles_total,
        "shadow_rows_written": len(agg),
        "by_horizon": by_horizon,
    }
    log.info(
        "[#55 source_performance_shadow] scanned=%d handles=%d shadow_rows=%d by_horizon=%s",
        rows_scanned, handles_total, len(agg), by_horizon,
    )
    return summary


# ---------------------------------------------------------------------------
# #62: the LIVE producer
# ---------------------------------------------------------------------------
# Horizons written to the live `source_performance` table. Deliberately NOT '1h':
# an analyst call graded one hour later measures market noise, and #55 benched the
# scorer at exactly that wrong horizon. 5d needs `alert_history.price_5d_later`,
# added in the same change and filled by the price-outcome loop.
_LIVE_HORIZONS: tuple[tuple[str, str], ...] = (
    ("24h", "price_24h_later"),
    ("5d", "price_5d_later"),
)


async def compute_source_performance_live(conn=None) -> dict:
    """#62: grade analysts at 24h and 5d into the LIVE `source_performance` table.

    Why this is safe to run while alerts are on:

    Every live reader of this table asks for the horizon returned by
    `db.analyst_horizon()`, which is '1h' until `scoring.analyst_accuracy_weight
    .enabled` is flipped. This producer never writes a '1h' row. So the table fills
    with 24h/5d track records while every reader keeps missing and staying
    cold-start — alerts are byte-for-byte unchanged. Flipping that one flag (which
    the auto-flip engine does only after >=1 analyst clears n>=90, Wilson-LB>0.50
    and BH-FDR q<=0.10) is what puts the data to work.

    Same grading rule as the shadow producer: a handle is right when the price moved
    the way its catalyst implied.

    Returns {"rows_scanned", "handles", "rows_written", "by_horizon"}.
    """
    from consensus_engine.db import get_db

    if conn is None:
        conn = await get_db()

    cur = await conn.execute(
        """SELECT analyst_mentions, catalyst_type, price_at_alert,
                  price_24h_later, price_5d_later
             FROM alert_history
            WHERE analyst_mentions IS NOT NULL
              AND analyst_mentions != ''
              AND analyst_mentions != '[]'
              AND price_at_alert IS NOT NULL
              AND price_at_alert > 0"""
    )
    rows = await cur.fetchall()

    agg: dict[tuple[str, str], list[int]] = {}
    rows_scanned = 0
    for row in rows:
        handles = _parse_handles(row["analyst_mentions"])
        if not handles:
            continue
        entry = row["price_at_alert"]
        if entry is None or entry <= 0:
            continue
        rows_scanned += 1
        bearish = (row["catalyst_type"] or "") in BEARISH_CATALYSTS
        for horizon, col in _LIVE_HORIZONS:
            later = row[col]
            if later is None or later <= 0:
                continue
            hit = 1 if _is_hit(float(entry), float(later), bearish) else 0
            for handle in handles:
                slot = agg.setdefault((handle, horizon), [0, 0])
                slot[0] += hit
                slot[1] += 1

    now = time.time()
    by_horizon: dict[str, int] = {}
    for (handle, horizon), (hits, count) in agg.items():
        if count <= 0:
            continue
        assert horizon != "1h", "the live table must never carry a 1h row"
        await conn.execute(
            """INSERT OR REPLACE INTO source_performance
               (entity_id, horizon, rolling_accuracy, sample_count, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (handle, horizon, hits / count, count, now),
        )
        by_horizon[horizon] = by_horizon.get(horizon, 0) + 1
    await conn.commit()

    handles_total = len({h for (h, _) in agg})
    log.info(
        "[#62 source_performance LIVE] scanned=%d handles=%d rows=%d by_horizon=%s",
        rows_scanned, handles_total, len(agg), by_horizon,
    )
    return {
        "rows_scanned": rows_scanned,
        "handles": handles_total,
        "rows_written": len(agg),
        "by_horizon": by_horizon,
    }
