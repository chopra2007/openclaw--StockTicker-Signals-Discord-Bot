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
  --preflight 6:10 a.m.  Is everything in place for the 6:35 entry? Silent when
                         it is; one owner-visible error when it is not.
  --proof     6:40 a.m.  Did the 6:35 entry actually happen, correctly? Silent
                         when it did. Never repairs anything.

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


def _age(seconds: float) -> str:
    """How long ago, in words a person can read at a glance."""
    if seconds < 5400:
        return f"{int(seconds / 60)} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def _borrow_note(r: dict) -> str:
    """One short clause about borrowing the stock, only when Schwab said so.

    Silent when Schwab did not answer. Saying nothing is honest; inventing an
    "easy to borrow" would not be.
    """
    if r.get("hard_to_borrow") is None:
        return ""
    if not r.get("hard_to_borrow"):
        return " · easy to borrow (Schwab)"
    rate = r.get("htb_rate")
    rate_txt = f" at about {rate:.1f}% a year" if rate else ""
    return f" · **hard to borrow**{rate_txt} (Schwab)"


# The one thing the card must never let the reader confuse. The pair is bearish
# because of the SIZE of yesterday's PUT trading, not because anyone was proved
# to be buying puts. A PUT SELL is not a bearish bet, and it is not why the
# stock is on this list.
SIDE_FOOTNOTE = (
    "**Why these names:** the whole rule is that yesterday's PUT trading was "
    "extreme for that contract. Shorting the stock against SPY is the bearish "
    "side because extreme PUT activity has been followed by the stock lagging "
    "SPY.\n"
    "**The option side above** describes that one print, not the stock. It does "
    "not pick or rank these names, and PUT SELL is not a bearish bet."
)


def render_watch_card(signal_date: str, entry_session: str, rows: list[dict]) -> str:
    """The 6:15 a.m. card. No prices yet — nothing is tradeable until 6:35.

    Two different facts have to stay separate on this card, and it says both:
      1. The stock/SPY pair leans bearish because extreme PUT ACTIVITY has
         historically been followed by the stock lagging SPY.
      2. The option-side label describes that one option print. It is not what
         picked the stock, and a PUT SELL is not a bearish bet.
    """
    head = (f"**Morning short watch — {len(rows)} name{'' if len(rows) == 1 else 's'}**\n"
            f"From extreme PUT activity on {signal_date}. Trading day {entry_session}.\n")
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
            f"    Contract seen: {r.get('contract_symbol') or '—'}\n"
            f"    Option side: "
            f"{pfs.side_label(r.get('flow_side'), r.get('flow_side_note'))}")
    lines.append(f"\n\nPlanned entry **6:35 a.m. Pacific**. Planned close "
                 f"**6:35 a.m. Pacific on {rows[0]['planned_exit_session']}** "
                 f"(four trading days later).")
    lines.append("\n\n" + SIDE_FOOTNOTE)
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
            f"Closes 6:35 a.m. Pacific on **{r['planned_exit_session']}**.\n"
            f"    Option side: "
            f"{pfs.side_label(r.get('flow_side'), r.get('flow_side_note'))}"
            f"{_borrow_note(r)}")
    for r in rejected:
        out.append(f"\n**{r['ticker']}** — skipped: {r['reject_reason']}.")
    out.append("\n\n" + SIDE_FOOTNOTE)
    out.append("\nSimulated. No order was placed.")
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
            f"cost {r['cost_pct']:.2f}% taken off.\n"
            f"    Option side at the time: "
            f"{pfs.side_label(r.get('flow_side'), r.get('flow_side_note'))}")
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
                cost_pct, flow_side, flow_side_note, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'WATCH',?,?)
               ON CONFLICT(signal_date, ticker) DO UPDATE SET
                 rank=excluded.rank, entry_session=excluded.entry_session,
                 planned_exit_session=excluded.planned_exit_session,
                 updated_at=excluded.updated_at""",
            (signal_date, entry_session, r["ticker"], r["rank"], r["flow_id"],
             r.get("contract_symbol"), r.get("vol_oi_ratio"), r.get("volume"),
             r.get("premium_usd"), r.get("strike"), r.get("expiry"),
             r.get("detected_at"), r.get("spot"), pfs.ENTRY_TIME_PT,
             exit_session, pfs.ENTRY_TIME_PT, pfs.ROUND_TRIP_COST_PCT,
             # Frozen once, at pick time, straight from the source flow row. The
             # ON CONFLICT branch deliberately leaves it alone: a rerun must not
             # rewrite what the already-posted card said.
             r.get("flow_side"), r.get("flow_side_note") or None, now, now))
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
        # Order matters: a bad price is the older, better-tested reason, and a
        # stock we cannot short is not tradeable at any price.
        bad = (f"SPY price unusable ({spy_bad})" if spy_bad
               else pfs.quote_problem(q, now, max_age_sec=max_age)
               or pfs.short_problem(q))
        if bad:
            await conn.execute(
                "UPDATE put_flow_shortlist SET status='REJECTED', reject_reason=?, "
                "updated_at=? WHERE id=?", (bad, now, r["id"]))
            rejected.append({**r, "reject_reason": bad})
            continue
        # Schwab's own point-in-time answer, stored with the entry so a later
        # reader can see what was true at 6:35 rather than what is true now.
        htb = q.get("hard_to_borrow")
        await conn.execute(
            "UPDATE put_flow_shortlist SET status='ENTERED', entry_at=?, "
            "entry_stock_px=?, entry_spy_px=?, reject_reason=NULL, "
            "shortable=?, hard_to_borrow=?, htb_rate=?, updated_at=? "
            "WHERE id=?",
            (now, q["c"], spy_q["c"],
             None if q.get("shortable") is None else int(q["shortable"]),
             None if htb is None else int(htb), q.get("htb_rate"),
             now, r["id"]))
        entered.append({**r, "entry_stock_px": q["c"], "entry_spy_px": spy_q["c"],
                        "shortable": q.get("shortable"), "hard_to_borrow": htb,
                        "htb_rate": q.get("htb_rate")})
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
# the two morning checks
#
# Both follow the same rule: a normal morning says NOTHING. A real problem posts
# ONE message, and the existing ops-alert machinery keeps it to one — it fires on
# the change, not on the state, remembers across runs in the database, and only
# speaks again if the *kind* of failure changes. Neither check ever repairs a row
# or invents a price to make itself pass.
# --------------------------------------------------------------------------

# The proof runs at 6:40 for a 6:35 entry. Anything older than this was not
# taken this morning — it was back-filled, replayed, or left over from a rerun.
STALE_ENTRY_SEC = 30 * 60

PREFLIGHT_KEY = "put_flow_shortlist_preflight"
PROOF_KEY = "put_flow_shortlist_entry_proof"


async def _announce(alert_key: str, failures: list[tuple[str, str]],
                    title: str, fix: str, dry_run: bool) -> dict:
    """Post one owner-visible error, or stay silent when nothing is wrong.

    `failures` is a list of (check_id, plain sentence). The FIRST check to fail
    becomes the failure class, so a different problem tomorrow re-alerts instead
    of being swallowed as "same outage".
    """
    ok = not failures
    result = {"ok": ok, "failed": [f[0] for f in failures],
              "detail": [f[1] for f in failures]}
    if dry_run:
        result["posted"] = False
        if failures:
            print("--- would alert ---\n" + title + "\n"
                  + "\n".join(f"- {d}" for _, d in failures) + "\n--- end ---")
        return result
    from consensus_engine.alerts.ops_alert import report_ops_state
    detail = " ".join(d if d.endswith(".") else d + "." for _, d in failures)
    result["posted"] = await report_ops_state(
        alert_key, down=bool(failures),
        failure_class=(failures[0][0] if failures else None),
        title=title, detail=detail, fix=fix,
        # This runs once a day. A confirmation window would wait for a second
        # check that never comes, so the alert would never reach anyone.
        confirm_after_s=0,
    )
    return result


async def _timer_ready(unit: str, session: str) -> tuple[bool, str]:
    """Is this timer armed, and is its next run today's session?"""
    import subprocess
    try:
        active = subprocess.run(["systemctl", "is-active", unit],
                                capture_output=True, text=True, timeout=15)
        if active.stdout.strip() != "active":
            return False, f"the {unit} timer is not running"
        shown = subprocess.run(
            ["systemctl", "show", unit, "-p", "NextElapseUSecRealtime"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        raw = (shown.split("=", 1)[1] if "=" in shown else "").strip()
        if not raw or raw in ("0", "n/a", "infinity"):
            return False, f"the {unit} timer has no next run scheduled"
        # systemd prints this either as raw microseconds or as a human date,
        # depending on the version. Accept both rather than guess.
        if raw.isdigit():
            nxt = datetime.fromtimestamp(int(raw) / 1_000_000, PT).date().isoformat()
        else:
            # e.g. "Tue 2026-08-25 06:15:00 PDT" — the date is what matters.
            parts = raw.split()
            nxt = next((x for x in parts if len(x) == 10 and x[4] == "-"), "")
            if not nxt:
                return False, f"could not read when the {unit} timer next runs"
        if nxt != session:
            return False, (f"the {unit} timer next runs on {nxt}, "
                           f"not today's trading day {session}")
        return True, ""
    except Exception as e:                      # noqa: BLE001 - never crash a check
        return False, f"could not read the {unit} timer ({e})"


async def preflight(session: str | None = None, dry_run: bool = False) -> dict:
    """6:10 a.m. Pacific — is everything in place for the 6:35 entry?

    This checks ACCESS and RECORDS, not prices. The market is not open at 6:10,
    so a stale quote here is normal and is not a failure.

    KNOWN LIMIT, worth understanding before trusting a silent pass: the watch job
    that CREATES today's rows runs at 6:15, five minutes after this. So on a
    normal morning there are no rows here yet, and the row checks below have
    nothing to look at — what this proves is access: the switch, the three
    timers, the private room, and Schwab answering for SPY. The row checks only
    bite when the card was posted the previous evening (as it was for
    2026-08-25). `waiting` in the returned JSON says which case this run was.
    The rows are fully checked after entry by `entry_proof` at 6:40.
    """
    session = session or today_pt()
    fails: list[tuple[str, str]] = []

    if not enabled():
        fails.append(("disabled", "the morning shortlist switch is off"))
    if not cfg.get(f"{FEATURE}.owner_only", False):
        fails.append(("not_owner_only", "the feature is no longer owner-only"))

    for unit in ("put-flow-shortlist-watch.timer", "put-flow-shortlist-trade.timer",
                 "put-flow-shortlist-proof.timer"):
        ok, why = await _timer_ready(unit, session)
        if not ok:
            fails.append(("timer", why))

    ch = channel_id()
    if not ch or not ch.isdigit():
        fails.append(("no_channel", "the private room for these cards is not configured"))
    elif not dry_run:
        from consensus_engine.alerts.discord import fetch_channel
        if not await fetch_channel(ch):
            fails.append(("channel_unreachable",
                          "the private room for these cards could not be reached"))

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM put_flow_shortlist WHERE entry_session=? ORDER BY rank",
        (session,))
    rows = [dict(r) for r in await cur.fetchall()]
    waiting = [r for r in rows if r["status"] == "WATCH"]
    done_early = [r for r in rows if r["status"] in ("ENTERED", "REJECTED", "CLOSED")]

    if done_early:
        fails.append(("already_traded",
                      "these names were already dealt with before the market opened: "
                      + ", ".join(f"{r['ticker']} ({r['status'].lower()})"
                                  for r in done_early)))
    if len(waiting) > pfs.MAX_PER_DATE:
        fails.append(("too_many",
                      f"{len(waiting)} names are waiting; the rule allows at most "
                      f"{pfs.MAX_PER_DATE}"))
    ranks = [r["rank"] for r in waiting]
    if len(set(ranks)) != len(ranks):
        fails.append(("duplicate_rank", "two waiting names share the same position"))
    for r in waiting:
        if r["entry_session"] != session:
            fails.append(("wrong_entry_day",
                          f"{r['ticker']} is set to start on {r['entry_session']}, "
                          f"not today"))
        expected_exit = pfs.session_plus(session)
        if r["planned_exit_session"] != expected_exit:
            fails.append(("wrong_exit_day",
                          f"{r['ticker']} is set to close on "
                          f"{r['planned_exit_session']}, but four trading days "
                          f"from today is {expected_exit}"))

    # Access proof: Schwab must answer for SPY and for every waiting name. The
    # PRICE does not have to be fresh — the market is shut.
    symbols = sorted({r["ticker"] for r in waiting} | {pfs.BENCHMARK})
    if not dry_run:
        try:
            from consensus_engine.scanners import schwab_client
            quotes = schwab_client.get_quotes(symbols)
            missing = [s for s in symbols if not (quotes.get(s) or {}).get("c")]
            if missing:
                fails.append(("no_quote",
                              "Schwab returned no price for " + ", ".join(missing)))
        except Exception as e:                  # noqa: BLE001
            fails.append(("schwab_down", f"Schwab could not be reached ({e})"))

    out = await _announce(
        PREFLIGHT_KEY, fails,
        title="Morning short watch readiness",
        fix="Check the failed item below before 6:35 a.m. Pacific. "
            "Nothing is entered automatically if the timer cannot run.",
        dry_run=dry_run)
    out.update({"session": session, "waiting": len(waiting),
                "tickers": [r["ticker"] for r in waiting]})
    return out


async def entry_proof(session: str | None = None, dry_run: bool = False) -> dict:
    """6:40 a.m. Pacific — did the 6:35 entry actually happen, correctly?

    Never fixes anything. A price that was not taken at 6:35 cannot be invented
    at 6:40, so this reports the mismatch and stops.
    """
    session = session or today_pt()
    fails: list[tuple[str, str]] = []

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM put_flow_shortlist WHERE entry_session=? ORDER BY rank",
        (session,))
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        # A morning with no names is normal, and there is nothing to prove.
        out = await _announce(PROOF_KEY, [], title="", fix="", dry_run=dry_run)
        out.update({"session": session, "rows": 0, "reason": "no names today"})
        return out

    entered = [r for r in rows if r["status"] == "ENTERED"]
    rejected = [r for r in rows if r["status"] == "REJECTED"]
    stuck = [r for r in rows if r["status"] not in ("ENTERED", "REJECTED")]

    if stuck:
        fails.append(("not_processed",
                      "the 6:35 job left these names unresolved: "
                      + ", ".join(f"{r['ticker']} ({r['status'].lower()})"
                                  for r in stuck)))
    tickers = [r["ticker"] for r in rows]
    if len(set(tickers)) != len(tickers):
        fails.append(("duplicate_ticker", "the same stock appears twice today"))
    ranks = [r["rank"] for r in rows]
    if len(set(ranks)) != len(ranks):
        fails.append(("duplicate_rank", "two names share the same position"))
    card_ids = {r["entry_msg_id"] for r in rows if r["entry_msg_id"]}
    if len(card_ids) > 1:
        fails.append(("duplicate_card",
                      f"{len(card_ids)} different entry cards were posted today"))

    for r in entered:
        if not r["entry_stock_px"] or r["entry_stock_px"] <= 0:
            fails.append(("no_entry_price", f"{r['ticker']} was entered with no price"))
        if not r["entry_spy_px"] or r["entry_spy_px"] <= 0:
            fails.append(("no_spy_price", f"{r['ticker']} was entered with no SPY price"))
        if not r["entry_at"]:
            fails.append(("no_entry_time", f"{r['ticker']} has no entry time"))
        elif time.time() - float(r["entry_at"]) > STALE_ENTRY_SEC:
            fails.append(("stale_entry",
                          f"{r['ticker']}'s entry price was taken "
                          f"{_age(time.time() - float(r['entry_at']))} ago, "
                          f"not at this morning's 6:35"))
        if not r["entry_msg_id"]:
            fails.append(("no_entry_card", f"{r['ticker']} has no entry card"))
    for r in rejected:
        if not (r["reject_reason"] or "").strip():
            fails.append(("no_reason", f"{r['ticker']} was skipped with no reason given"))

    # The card the owner can actually see must match the stored rows.
    if entered or rejected:
        if not card_ids:
            fails.append(("card_missing", "no entry card was posted this morning"))
        elif not dry_run:
            from consensus_engine.alerts.discord import fetch_message
            msg = await fetch_message(channel_id(), sorted(card_ids)[0])
            if not msg:
                fails.append(("card_unreadable",
                              "the entry card could not be read back from Discord"))
            else:
                seen = msg.get("content") or ""
                for r in entered:
                    if f"${r['entry_stock_px']:,.2f}" not in seen:
                        fails.append(("card_mismatch",
                                      f"the card does not show {r['ticker']}'s stored "
                                      f"entry price of ${r['entry_stock_px']:,.2f}"))
                for r in rejected:
                    if r["ticker"] not in seen:
                        fails.append(("card_mismatch",
                                      f"the card does not mention {r['ticker']}, "
                                      f"which was skipped"))

    out = await _announce(
        PROOF_KEY, fails,
        title="Morning short entry check",
        fix="Look at today's rows in put_flow_shortlist. Do NOT back-fill a "
            "price after the fact — a missed morning stays missed.",
        dry_run=dry_run)
    out.update({"session": session, "entered": len(entered),
                "rejected": len(rejected), "unresolved": len(stuck)})
    return out


# --------------------------------------------------------------------------
# results, split by option side
# --------------------------------------------------------------------------

async def side_report() -> dict:
    """Closed results grouped by the option-side label, so BUY, SELL, side-unclear
    and not-recorded accumulate separately.

    This counts. It does not decide. Turning any of this into a filter needs the
    statistical work that TODO #80 owns.
    """
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT flow_side, net_pct FROM put_flow_shortlist WHERE status='CLOSED' "
        "AND net_pct IS NOT NULL")
    buckets: dict[str, list[float]] = {b: [] for b in pfs.SIDE_BUCKETS}
    for r in await cur.fetchall():
        buckets[pfs.side_bucket(r["flow_side"])].append(float(r["net_pct"]))
    out = {}
    for name, vals in buckets.items():
        out[name] = {
            "trades": len(vals),
            "won": sum(1 for v in vals if v > 0),
            "avg_pct": round(sum(vals) / len(vals), 3) if vals else None,
        }
    return out


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
        if args.preflight:
            print(json.dumps(await preflight(args.session, args.dry_run), indent=2))
        if args.proof:
            print(json.dumps(await entry_proof(args.session, args.dry_run), indent=2))
        if args.side_report:
            print(json.dumps(await side_report(), indent=2))
    finally:
        await db.close_db()
        # These jobs are one-shot. The Discord helpers open a shared HTTP
        # session; leaving it open logs an "Unclosed client session" error on
        # exit, which looks like a failure in the journal and is not one.
        try:
            from consensus_engine.utils.http import close_session
            await close_session()
        except Exception:                       # noqa: BLE001
            pass
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare", action="store_true", help="6:15 a.m. watch card")
    p.add_argument("--enter", action="store_true", help="6:35 a.m. entry")
    p.add_argument("--exit", action="store_true", help="6:35 a.m. close what is due")
    p.add_argument("--preflight", action="store_true",
                   help="6:10 a.m. readiness check; silent unless something is wrong")
    p.add_argument("--proof", action="store_true",
                   help="6:40 a.m. entry proof; silent unless something is wrong")
    p.add_argument("--side-report", action="store_true",
                   help="closed results split by PUT BUY / PUT SELL / unclear / not recorded")
    p.add_argument("--dry-run", action="store_true", help="print the card, post nothing")
    p.add_argument("--force", action="store_true", help="run even when the switch is off")
    p.add_argument("--signal-date", default=None, help="override the prior session")
    p.add_argument("--session", default=None, help="override today's session date")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (args.prepare or args.enter or args.exit
            or args.preflight or args.proof or args.side_report):
        p.print_help()
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
