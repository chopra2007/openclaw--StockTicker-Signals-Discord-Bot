"""TODO #96 — the extreme-PUT-flow morning shortlist, owner-only.

Three jobs, all Pacific time:

  --prepare   6:15 a.m.  Read yesterday's completed session, pick zero to four
                         stocks, save them, and post the watch card. The card
                         says plainly that nothing is valid until 6:35.
  --enter     6:35 a.m.  Get fresh Schwab prices for each stock and SPY, throw
                         out anything stale, missing, crossed or halted, record
                         the simulated equal-dollar short-stock/long-SPY entry,
                         and update the card.
  --exit      6:35 a.m.  Close any trade whose fourth session is today and post
                         the finished result.

Nothing here places an order. Every entry and exit is simulated and stored.

`--dry-run` suppresses the Discord post ONLY. It still saves rows, because the
saved plan is what the 6:35 job reads and what a replay needs to check.

    python3 scripts/put_flow_shortlist_job.py --prepare
    python3 scripts/put_flow_shortlist_job.py --enter --exit
    python3 scripts/put_flow_shortlist_job.py --prepare --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from consensus_engine import config as cfg, db  # noqa: E402
from consensus_engine.analysis import put_flow_shortlist as pfs  # noqa: E402
from consensus_engine.utils.time_context import session_dates  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
log = logging.getLogger("put_flow_shortlist")

FEATURE = "put_flow_shortlist"


def enabled() -> bool:
    return bool(cfg.get(f"{FEATURE}.enabled", False))


def channel_id() -> str:
    """Where the card goes. The briefing room is the owner's private channel."""
    return str(cfg.get(f"{FEATURE}.channel_id", "")
               or cfg.get_api_key("discord_briefing_channel_id") or "")


def owner_id() -> str:
    return str(cfg.get_api_key("discord_owner_user_id") or "")


def today_pt() -> str:
    return datetime.now(PT).date().isoformat()


def prior_session(today: str) -> str | None:
    """The last completed trading session before `today`."""
    from datetime import date
    d = date.fromisoformat(today)
    past = session_dates(d - timedelta(days=14), d - timedelta(days=1))
    return past[-1].isoformat() if past else None


# --------------------------------------------------------------------------
# the card
# --------------------------------------------------------------------------

def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def render_watch_card(signal_date: str, entry_session: str, rows: list[dict]) -> str:
    """The 6:15 a.m. card. No prices yet — nothing is tradeable until 6:35."""
    head = (f"**Morning short watch — {len(rows)} name{'' if len(rows) == 1 else 's'}**\n"
            f"From heavy PUT buying on {signal_date}. Trading day {entry_session}.\n")
    if not rows:
        return (head + "\nNo stock cleared the bar yesterday. Nothing to watch today. "
                       "That is a normal result, not a missed signal.")
    lines = [head, "\n**Not valid yet.** These are checked against fresh prices at "
                   "**6:35 a.m. Pacific**. Anything with a bad price then is dropped.\n"]
    for r in rows:
        lines.append(
            f"\n**{r['rank']}. {r['ticker']}** — short the stock, buy the same "
            f"dollar amount of SPY\n"
            f"    Yesterday's PUT burst: **{r['vol_oi_ratio']:.0f}x** "
            f"the contracts already open, {int(r['volume'] or 0):,} contracts, "
            f"${(r['premium_usd'] or 0) / 1000:,.0f}k traded\n"
            f"    Contract seen: {r.get('contract_symbol') or '—'}")
    lines.append(f"\n\nPlanned entry **6:35 a.m. Pacific**. Planned close "
                 f"**6:35 a.m. Pacific on {rows[0]['planned_exit_session']}** "
                 f"(four trading days later).")
    lines.append("\nMeasurement only — no order is placed, and this is not advice.")
    return "".join(lines)


def render_entry_card(entry_session: str, entered: list[dict],
                      rejected: list[dict]) -> str:
    head = f"**Morning short entries — {entry_session}, 6:35 a.m. Pacific**\n"
    if not entered and not rejected:
        return head + "\nNothing to enter today."
    out = [head]
    for r in entered:
        out.append(
            f"\n**{r['ticker']}** — in at **${r['entry_stock_px']:,.2f}**, "
            f"SPY at **${r['entry_spy_px']:,.2f}**\n"
            f"    Equal dollars short {r['ticker']}, long SPY. "
            f"Closes 6:35 a.m. Pacific on **{r['planned_exit_session']}**.")
    for r in rejected:
        out.append(f"\n**{r['ticker']}** — skipped: {r['reject_reason']}.")
    out.append("\n\nSimulated. No order was placed.")
    return "".join(out)


def render_result_card(rows: list[dict]) -> str:
    out = ["**Morning short results — closed today**\n"]
    for r in rows:
        verdict = "made money" if (r["net_pct"] or 0) > 0 else "lost money"
        out.append(
            f"\n**{r['ticker']}** ({r['entry_session']} → {r['planned_exit_session']}) "
            f"— **{_pct(r['net_pct'])}**, {verdict}\n"
            f"    {r['ticker']} {_pct(r['stock_ret_pct'])}, "
            f"SPY {_pct(r['spy_ret_pct'])}, "
            f"cost {r['cost_pct']:.2f}% taken off.")
    out.append("\n\nSimulated result, after costs. Borrow cost is not included.")
    return "".join(out)


async def _post(content: str, dry_run: bool) -> str | None:
    if dry_run:
        print("--- would post ---\n" + content + "\n--- end ---")
        return None
    from consensus_engine.alerts.discord import send_message
    ch = channel_id()
    if not ch:
        log.error("no channel configured; card not sent")
        return None
    return await send_message(ch, content, ping_user_id=owner_id() or None)


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

async def prepare(signal_date: str | None = None, dry_run: bool = False) -> dict:
    today = today_pt()
    signal_date = signal_date or prior_session(today)
    if not signal_date:
        return {"error": "no prior trading session found"}

    rows = await pfs.shortlist_for_date(signal_date)
    entry_session = pfs.next_session(signal_date)
    exit_session = pfs.session_plus(entry_session)
    now = time.time()

    conn = await db.get_db()
    stored = []
    for r in rows:
        await conn.execute(
            """INSERT INTO put_flow_shortlist
               (signal_date, entry_session, ticker, rank, flow_id, contract_symbol,
                vol_oi_ratio, volume, premium_usd, strike, expiry, detected_at,
                signal_spot, planned_entry_pt, planned_exit_session, planned_exit_pt,
                cost_pct, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'WATCH',?,?)
               ON CONFLICT(signal_date, ticker) DO UPDATE SET
                 rank=excluded.rank, entry_session=excluded.entry_session,
                 planned_exit_session=excluded.planned_exit_session,
                 updated_at=excluded.updated_at""",
            (signal_date, entry_session, r["ticker"], r["rank"], r["flow_id"],
             r.get("contract_symbol"), r.get("vol_oi_ratio"), r.get("volume"),
             r.get("premium_usd"), r.get("strike"), r.get("expiry"),
             r.get("detected_at"), r.get("spot"), pfs.ENTRY_TIME_PT,
             exit_session, pfs.ENTRY_TIME_PT, pfs.ROUND_TRIP_COST_PCT, now, now))
        stored.append({**r, "planned_exit_session": exit_session})
    await conn.commit()

    # Duplicate-post guard: if this signal date already has a watch card, the
    # job has run today. Save the rows again (harmless) but do not re-post.
    cur = await conn.execute(
        "SELECT watch_msg_id FROM put_flow_shortlist WHERE signal_date=? "
        "AND watch_msg_id IS NOT NULL LIMIT 1", (signal_date,))
    already = await cur.fetchone()
    if already and not dry_run:
        return {"signal_date": signal_date, "selected": len(stored),
                "posted": False, "reason": "watch card already posted"}

    msg_id = await _post(render_watch_card(signal_date, entry_session, stored), dry_run)
    if msg_id:
        await conn.execute(
            "UPDATE put_flow_shortlist SET watch_msg_id=?, updated_at=? "
            "WHERE signal_date=?", (msg_id, time.time(), signal_date))
        await conn.commit()
    return {"signal_date": signal_date, "entry_session": entry_session,
            "exit_session": exit_session, "selected": len(stored),
            "tickers": [r["ticker"] for r in stored], "posted": bool(msg_id),
            "msg_id": msg_id}


# --------------------------------------------------------------------------
# enter
# --------------------------------------------------------------------------

async def enter(dry_run: bool = False, entry_session: str | None = None) -> dict:
    from consensus_engine.scanners import schwab_client
    entry_session = entry_session or today_pt()
    conn = await db.get_db()
    # A watch row whose morning has passed was never entered — the job did not
    # run, or the machine was down. Close it out so it cannot be entered late at
    # a price that has nothing to do with its signal.
    await conn.execute(
        "UPDATE put_flow_shortlist SET status='EXPIRED', "
        "reject_reason='entry morning passed without a run', updated_at=? "
        "WHERE status='WATCH' AND entry_session < ?", (time.time(), entry_session))
    await conn.commit()
    cur = await conn.execute(
        "SELECT * FROM put_flow_shortlist WHERE entry_session=? AND status='WATCH' "
        "ORDER BY rank", (entry_session,))
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return {"entry_session": entry_session, "entered": 0, "rejected": 0,
                "reason": "nothing waiting to enter"}

    symbols = sorted({r["ticker"] for r in rows} | {pfs.BENCHMARK})
    quotes = schwab_client.get_quotes(symbols)
    now = time.time()

    max_age = int(cfg.get(f"{FEATURE}.quote_max_age_sec", 300))
    spy_q = quotes.get(pfs.BENCHMARK)
    spy_bad = pfs.quote_problem(spy_q, now, max_age_sec=max_age)
    entered, rejected = [], []
    for r in rows:
        q = quotes.get(r["ticker"])
        bad = (f"SPY price unusable ({spy_bad})" if spy_bad
               else pfs.quote_problem(q, now, max_age_sec=max_age))
        if bad:
            await conn.execute(
                "UPDATE put_flow_shortlist SET status='REJECTED', reject_reason=?, "
                "updated_at=? WHERE id=?", (bad, now, r["id"]))
            rejected.append({**r, "reject_reason": bad})
            continue
        await conn.execute(
            "UPDATE put_flow_shortlist SET status='ENTERED', entry_at=?, "
            "entry_stock_px=?, entry_spy_px=?, reject_reason=NULL, updated_at=? "
            "WHERE id=?", (now, q["c"], spy_q["c"], now, r["id"]))
        entered.append({**r, "entry_stock_px": q["c"], "entry_spy_px": spy_q["c"]})
    await conn.commit()

    cur = await conn.execute(
        "SELECT entry_msg_id FROM put_flow_shortlist WHERE entry_session=? "
        "AND entry_msg_id IS NOT NULL LIMIT 1", (entry_session,))
    if (await cur.fetchone()) and not dry_run:
        return {"entry_session": entry_session, "entered": len(entered),
                "rejected": len(rejected), "posted": False,
                "reason": "entry card already posted"}

    msg_id = await _post(render_entry_card(entry_session, entered, rejected), dry_run)
    if msg_id:
        await conn.execute(
            "UPDATE put_flow_shortlist SET entry_msg_id=?, updated_at=? "
            "WHERE entry_session=?", (msg_id, time.time(), entry_session))
        await conn.commit()
    return {"entry_session": entry_session, "entered": len(entered),
            "rejected": len(rejected),
            "entered_tickers": [r["ticker"] for r in entered],
            "rejects": {r["ticker"]: r["reject_reason"] for r in rejected},
            "posted": bool(msg_id)}


# --------------------------------------------------------------------------
# exit
# --------------------------------------------------------------------------

async def close_due(dry_run: bool = False, exit_session: str | None = None) -> dict:
    from consensus_engine.scanners import schwab_client
    exit_session = exit_session or today_pt()
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM put_flow_shortlist WHERE planned_exit_session=? "
        "AND status='ENTERED' ORDER BY entry_session, rank", (exit_session,))
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return {"exit_session": exit_session, "closed": 0,
                "reason": "nothing due to close"}

    quotes = schwab_client.get_quotes(sorted({r["ticker"] for r in rows} | {pfs.BENCHMARK}))
    now = time.time()
    max_age = int(cfg.get(f"{FEATURE}.quote_max_age_sec", 300))
    spy_q = quotes.get(pfs.BENCHMARK)
    spy_bad = pfs.quote_problem(spy_q, now, max_age_sec=max_age)
    if spy_bad:
        return {"exit_session": exit_session, "closed": 0,
                "error": f"SPY price unusable: {spy_bad}"}

    closed = []
    for r in rows:
        q = quotes.get(r["ticker"])
        bad = pfs.quote_problem(q, now, max_age_sec=max_age)
        if bad:
            log.warning("%s exit price unusable (%s) — leaving open for a retry",
                        r["ticker"], bad)
            continue
        stock_ret = 100.0 * (q["c"] / r["entry_stock_px"] - 1.0)
        spy_ret = 100.0 * (spy_q["c"] / r["entry_spy_px"] - 1.0)
        net = pfs.pair_net_pct(r["entry_stock_px"], q["c"],
                               r["entry_spy_px"], spy_q["c"],
                               cost_pct=r["cost_pct"] or pfs.ROUND_TRIP_COST_PCT)
        await conn.execute(
            "UPDATE put_flow_shortlist SET status='CLOSED', exit_at=?, "
            "exit_stock_px=?, exit_spy_px=?, stock_ret_pct=?, spy_ret_pct=?, "
            "net_pct=?, updated_at=? WHERE id=?",
            (now, q["c"], spy_q["c"], stock_ret, spy_ret, net, now, r["id"]))
        closed.append({**r, "exit_stock_px": q["c"], "exit_spy_px": spy_q["c"],
                       "stock_ret_pct": stock_ret, "spy_ret_pct": spy_ret,
                       "net_pct": net})
    await conn.commit()
    if not closed:
        return {"exit_session": exit_session, "closed": 0,
                "reason": "no usable exit price yet"}

    cur = await conn.execute(
        "SELECT result_msg_id FROM put_flow_shortlist WHERE planned_exit_session=? "
        "AND result_msg_id IS NOT NULL LIMIT 1", (exit_session,))
    if (await cur.fetchone()) and not dry_run:
        return {"exit_session": exit_session, "closed": len(closed), "posted": False,
                "reason": "result card already posted"}

    msg_id = await _post(render_result_card(closed), dry_run)
    if msg_id:
        await conn.execute(
            "UPDATE put_flow_shortlist SET result_msg_id=?, updated_at=? "
            "WHERE planned_exit_session=? AND status='CLOSED'",
            (msg_id, time.time(), exit_session))
        await conn.commit()
    return {"exit_session": exit_session, "closed": len(closed),
            "results": {r["ticker"]: round(r["net_pct"], 3) for r in closed},
            "posted": bool(msg_id)}


# --------------------------------------------------------------------------

async def run(args) -> int:
    if not enabled() and not args.force:
        print(f"{FEATURE}.enabled is off — nothing done "
              f"(use --force to run anyway)")
        return 0
    await db.init_db()
    try:
        import json
        if args.prepare:
            print(json.dumps(await prepare(args.signal_date, args.dry_run), indent=2))
        if args.exit:
            print(json.dumps(await close_due(args.dry_run, args.session), indent=2))
        if args.enter:
            print(json.dumps(await enter(args.dry_run, args.session), indent=2))
    finally:
        await db.close_db()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare", action="store_true", help="6:15 a.m. watch card")
    p.add_argument("--enter", action="store_true", help="6:35 a.m. entry")
    p.add_argument("--exit", action="store_true", help="6:35 a.m. close what is due")
    p.add_argument("--dry-run", action="store_true", help="print the card, post nothing")
    p.add_argument("--force", action="store_true", help="run even when the switch is off")
    p.add_argument("--signal-date", default=None, help="override the prior session")
    p.add_argument("--session", default=None, help="override today's session date")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (args.prepare or args.enter or args.exit):
        p.print_help()
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
