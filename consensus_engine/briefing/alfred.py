"""Alfred: morning Discord briefing with a transactional outbox."""
from __future__ import annotations

import logging
import time

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.briefing.alfred")


async def build_briefing_data(session_start_utc: float,
                              session_end_utc: float) -> dict:
    """Gather all source data Alfred needs to synthesize a brief."""
    conn = await db.get_db()

    # Overnight alerts
    cur = await conn.execute(
        """SELECT ticker, confidence_score, catalyst, catalyst_type,
                  alerted_at, price_at_alert
           FROM alert_history
           WHERE alerted_at BETWEEN ? AND ?
           ORDER BY alerted_at DESC""",
        (session_start_utc, session_end_utc),
    )
    alerts = [dict(r) for r in await cur.fetchall()]

    # Pending youtube_levels (last 14d, not triggered)
    levels_cutoff = time.time() - 14 * 86400
    cur = await conn.execute(
        """SELECT ticker, level_type, price, condition_text, consequence_text,
                  channel_name, published_at
           FROM youtube_levels
           WHERE extracted_at >= ?
           ORDER BY extracted_at DESC LIMIT 30""",
        (levels_cutoff,),
    )
    levels = [dict(r) for r in await cur.fetchall()]

    # High-conviction youtube_signals, last 7d, directional
    yt_cutoff = time.time() - 7 * 86400
    cur = await conn.execute(
        """SELECT ticker, direction, conviction, channel_name, macro_thesis,
                  published_at
           FROM youtube_signals
           WHERE extracted_at >= ?
             AND conviction='high' AND direction != 'neutral'
           ORDER BY extracted_at DESC LIMIT 20""",
        (yt_cutoff,),
    )
    yt_signals = [dict(r) for r in await cur.fetchall()]

    # Latest macro regime
    cur = await conn.execute(
        "SELECT direction, themes, timeframe, summary, confidence, published_at "
        "FROM youtube_macro ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    macro = dict(row) if row else None

    # Top tickers (last 24h) + their research sections
    top = await db.get_top_tickers_session(session_end_utc - 86400, session_end_utc, limit=5)
    top_tickers = []
    for t in top:
        sections = await db.get_research_sections(t)
        top_tickers.append({"ticker": t, "sections": sections})

    return {
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
        "alerts": alerts,
        "levels": levels,
        "yt_signals": yt_signals,
        "macro": macro,
        "top_tickers": top_tickers,
    }
