"""TODO #100 — forward option-trade OBSERVER for the TODO #96 put-flow pairs.

Plain words: TODO #98 started saving the whole option-chain slice at each
6:35 a.m. Pacific entry. This module is the next step. It does two things and
nothing else:

  1. select_for_position() — at entry, pick ONE contract (or one two-leg
     spread) out of the slice that was already stored at 06:35, using only the
     frozen rule in
     `.omc/research/put-flow-option-trade-system/frozen-policy.json` and only
     fields that were knowable at entry. It writes one row to
     `put_flow_option_selections`: SELECTED with a full plan, or
     NO_OPTION_TRADE with an exact reason. A rejected morning stays visible in
     the counts, it never disappears.

  2. run_session() — from just before 06:35 to just after 13:00 Pacific, poll
     Schwab ONCE per 15 seconds for EVERY open option leg in a single batched
     /quotes call, summarise the ticks into one row per contract per Pacific
     minute in `put_flow_option_minutes`, and write an immutable event to
     `put_flow_option_events` the first time the position's liquidation value
     touches its target or its stop, or when its frozen time-exit date is
     reached.

This is an OBSERVER. It never places an order. It never picks, ranks or
rejects a STOCK. A Schwab error, an auth failure or any exception here is
logged and swallowed — it can never raise into, delay, cancel or change the
stock-pair path. It never renders or logs a raw option chain: every function
here returns counts and one already-chosen contract, never the slice.

Target / stop are measured on LIQUIDATION value:
  * long PUT  -> the long bid
  * spread    -> long bid minus short ask
If target and stop are both true in the same poll, the STOP is recorded
(the conservative assumption).

The frozen rule is obeyed literally and is never changed here. The shared
research selector (`scripts/research/put_flow_option_select.py`) does not
exist, so the rule is re-implemented in this module — production must not
import research code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.analysis.put_flow_option_capture import (
    option_mark as _option_mark,
    quote_quality as _quote_quality,
)
from consensus_engine.utils.time_context import session_bounds, session_dates

log = logging.getLogger(__name__)

PT = ZoneInfo("America/Los_Angeles")

# ── the frozen rule, transcribed from frozen-policy.json (never change these) ──

_CFG = "put_flow_shortlist.option_trade"

_POLICY_PATH = (Path(__file__).resolve().parents[2]
                / ".omc/research/put-flow-option-trade-system/frozen-policy.json")

_DEFAULT_FINGERPRINT = "f284dbe96350cb16c6c4f527ab6f20b8d6ffa3d5f93aca1656f3e94e8209ffb0"


def _rule_fingerprint() -> str:
    """The frozen-policy fingerprint the lead pinned in config; falls back to the
    sha256 of the policy file, then to the known constant. Read-only."""
    pinned = cfg.get(f"{_CFG}.rule_fingerprint", None)
    if pinned:
        return str(pinned)
    try:
        return hashlib.sha256(_POLICY_PATH.read_bytes()).hexdigest()
    except OSError:
        return _DEFAULT_FINGERPRINT


def _rule_version() -> str:
    return str(cfg.get(f"{_CFG}.rule_version", "v1"))


# Kept as module attributes so tests and other modules can reference them.
RULE_FINGERPRINT = _rule_fingerprint()
RULE_VERSION = _rule_version()

STRUCTURES = ("ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD")
EXIT_POLICIES = ("TIME_ONLY", "PT25_SL35", "PT50_SL35")

# exit policy id -> (target_pct, stop_pct) on liquidation value vs entry cost
_EXIT_PCTS = {
    "TIME_ONLY": (None, None),
    "PT25_SL35": (0.25, -0.35),
    "PT50_SL35": (0.50, -0.35),
}

# contract eligibility. The multiplier and expiration bounds are frozen; the OI
# floor, the spread ceiling and the commission are read from config so the lead
# owns them, defaulting to the frozen values.
_MULTIPLIER_REQUIRED = 100
_MAX_DAYS_AFTER_ENTRY = 45
_MIN_DAYS_AFTER_STOCK_EXIT = 7

_QUALITY_RANK = {"MISSING": 0, "NO_TWO_SIDED": 1, "STALE": 2, "OK": 3}

# ── config ──────────────────────────────────────────────────────────────────


def select_enabled() -> bool:
    return bool(cfg.get(f"{_CFG}.select_enabled", False))


def monitor_enabled() -> bool:
    return bool(cfg.get(f"{_CFG}.monitor_enabled", False))


def _min_oi() -> float:
    return float(cfg.get(f"{_CFG}.min_open_interest", 100))


def _max_spread_pct() -> float:
    return float(cfg.get(f"{_CFG}.max_spread_pct_of_mid", 0.10))


def _commission_side() -> float:
    return float(cfg.get(f"{_CFG}.commission_per_contract_side_usd", 0.45))


def _poll_interval() -> float:
    return float(cfg.get(f"{_CFG}.poll_seconds", 15))


def _quote_max_age() -> int:
    return int(cfg.get(f"{_CFG}.quote_max_age_sec", 120))


def _start_pt() -> str:
    return str(cfg.get(f"{_CFG}.start_pt", "06:30"))


def _stop_pt() -> str:
    return str(cfg.get(f"{_CFG}.stop_pt", "13:05"))


def _max_legs() -> int:
    return int(cfg.get(f"{_CFG}.max_legs", 32))


# ── small time helpers (Pacific only) ───────────────────────────────────────

def _now(now: float | None) -> float:
    return time.time() if now is None else now


def _ptdt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, PT)


def pacific_date(ts: float) -> str:
    return _ptdt(ts).date().isoformat()


def pacific_minute(ts: float) -> str:
    return _ptdt(ts).strftime("%H:%M")


def _pt_epoch(session_date: str, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    d = date.fromisoformat(session_date)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=PT).timestamp()


def is_trading_day(session_date: str) -> bool:
    d = date.fromisoformat(session_date)
    return len(session_dates(d, d)) == 1


# ── writers: a dry run is STRUCTURALLY unable to touch the database ──────────

class _Writer:
    """Real writes. Used only when dry_run is False."""

    def __init__(self, conn):
        self._conn = conn

    async def exec(self, sql: str, params=()):
        return await self._conn.execute(sql, params)

    async def commit(self):
        await self._conn.commit()


class _NullWriter:
    """dry-run writer: every mutation is a no-op. There is no code path from
    dry_run=True to a live INSERT/UPDATE."""

    async def exec(self, sql: str, params=()):
        return None

    async def commit(self):
        return None


# ── selection ──────────────────────────────────────────────────────────────

_SEL_COLS = (
    "shortlist_id", "ticker", "signal_date", "entry_session", "rule_version",
    "rule_fingerprint", "structure", "long_symbol", "short_symbol", "expiry",
    "long_strike", "short_strike", "entry_stock_px", "long_entry_ask",
    "long_entry_bid", "short_entry_bid", "short_entry_ask", "entry_cost",
    "entry_commission", "target_liq_value", "stop_liq_value", "max_exit_session",
    "max_exit_pt", "exit_policy", "long_open_interest", "short_open_interest",
    "selection_status", "reject_reason", "proof_tier", "structures_collapsed",
    "created_at", "updated_at",
)

_SEL_UPSERT = (
    "INSERT INTO put_flow_option_selections (" + ",".join(_SEL_COLS) + ") "
    "VALUES (" + ",".join("?" for _ in _SEL_COLS) + ") "
    "ON CONFLICT(shortlist_id, rule_fingerprint, structure, exit_policy) DO UPDATE SET "
    + ",".join(f"{c}=excluded.{c}" for c in _SEL_COLS
               if c not in ("shortlist_id", "rule_fingerprint", "structure",
                             "exit_policy", "created_at"))
)


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


_NORMAL_DELIVERABLE = re.compile(r"100\s+[A-Z][A-Z0-9.\-]*")


def _eligibility_reasons(c: dict) -> list[str]:
    """Every frozen reason this ONE contract cannot be traded, from entry-known
    fields only. Empty list = eligible."""
    out: list[str] = []
    mult = _finite(c.get("multiplier"))
    if mult != _MULTIPLIER_REQUIRED:
        out.append(f"multiplier {c.get('multiplier')} is not {_MULTIPLIER_REQUIRED}")
    if c.get("non_standard"):
        out.append("adjusted / non-standard contract")
    # `deliverable_note` is present on EVERY contract, standard ones included --
    # a normal put reads "100 DKS". It only signals an adjusted contract when it
    # describes something other than a plain 100 shares of the underlying, e.g.
    # a merger leaving "100 XYZ + $50 cash". A blank note is Schwab not saying,
    # which is unknown, and unknown never vetoes on its own.
    note = (c.get("deliverable_note") or "").strip()
    if note and not _NORMAL_DELIVERABLE.fullmatch(note):
        out.append(f"non-standard deliverable ({note})")
    b, a = _finite(c.get("bid")), _finite(c.get("ask"))
    if b is None or b <= 0:
        out.append("bid is not positive")
    if a is None or a <= 0:
        out.append("ask is not positive")
    if b is not None and a is not None and a < b:
        out.append("crossed quote (bid above ask)")
    if (c.get("quote_quality") or "") != "OK":
        out.append(f"quote is {c.get('quote_quality') or 'unknown'}, not a fresh two-sided price")
    max_spread = _max_spread_pct()
    if b and a and b > 0 and a > 0:
        mid = (a + b) / 2.0
        if mid > 0 and (a - b) / mid > max_spread:
            out.append(f"bid/ask spread is {100 * (a - b) / mid:.0f}% of mid, "
                       f"over the {max_spread * 100:.0f}% limit")
    min_oi = _min_oi()
    oi = _finite(c.get("open_interest")) or 0.0
    if oi < min_oi:
        out.append(f"open interest {int(oi)} is below {int(min_oi)}")
    return out


def _pick_leg(rows: list[dict], target_strike: float) -> tuple[dict | None, str | None]:
    """The one contract for a leg.

    Clarification C3: the STRIKE is chosen first and the liquidity tests can
    only veto it. Pick the listed strike closest to the target, then test it.
    If that one contract fails, the answer is no trade -- we never step outward
    to the next strike that happens to pass. Choosing among only the strikes
    that already passed would let the rule hunt until something qualified,
    which quietly turns "at the money" into "whatever was liquid today" and can
    only ever flatter the result.

    Ties between two equally-distant strikes fall back to the frozen tie-break:
    higher open interest, then contract symbol ascending. Returns
    (contract, None) or (None, reason).
    """
    listed = [c for c in rows if _finite(c.get("strike")) is not None]
    if not listed:
        return None, "no contracts listed at this expiration"
    listed.sort(key=lambda c: (
        abs(_finite(c.get("strike")) - target_strike),
        -(_finite(c.get("open_interest")) or 0.0),
        c.get("contract_symbol") or "",
    ))
    nearest = listed[0]
    reasons = _eligibility_reasons(nearest)
    if reasons:
        return None, "; ".join(reasons)
    return nearest, None


def _plan_targets(structure: str, stock_px: float) -> list[tuple[str, float]]:
    if structure == "ATM_PUT":
        return [("LONG", stock_px)]
    if structure == "OTM5_PUT":
        return [("LONG", 0.95 * stock_px)]
    if structure == "PUT_DEBIT_SPREAD":
        return [("LONG", stock_px), ("SHORT", 0.95 * stock_px)]
    raise ValueError(f"unknown structure {structure!r}")


async def select_for_position(shortlist_id: int, *, structure: str, exit_policy: str,
                              now: float | None = None, dry_run: bool = False) -> dict:
    """Pick the contract for one (position, structure, exit policy) from the
    stored ENTRY slice and write one put_flow_option_selections row.

    Fail-soft: never raises. Any problem comes back as status='ERROR' with the
    message, so an inline caller's stock trade is never affected.
    """
    now = _now(now)
    result = {"shortlist_id": shortlist_id, "structure": structure,
              "exit_policy": exit_policy, "status": "ERROR",
              "reject_reason": None, "selection_id": None, "plan": None,
              "error": None}
    if structure not in STRUCTURES:
        result["error"] = f"unknown structure {structure!r}"
        return result
    if exit_policy not in EXIT_POLICIES:
        result["error"] = f"unknown exit policy {exit_policy!r}"
        return result
    try:
        conn = await db.get_db()
        writer = _NullWriter() if dry_run else _Writer(conn)

        cur = await conn.execute("SELECT * FROM put_flow_shortlist WHERE id=?",
                                 (shortlist_id,))
        row = await cur.fetchone()
        if row is None:
            result["error"] = "shortlist row not found"
            return result
        row = dict(row)
        result["ticker"] = row["ticker"]

        cur = await conn.execute(
            "SELECT contract_symbol, expiry, strike, bid, ask, last, mark, "
            "open_interest, multiplier, non_standard, deliverable_note, "
            "quote_quality, underlying_px "
            "FROM put_flow_option_snapshots "
            "WHERE shortlist_id=? AND stage='ENTRY'", (shortlist_id,))
        slice_rows = [dict(r) for r in await cur.fetchall()]

        reject = None
        plan = None
        if not slice_rows:
            reject = "no ENTRY option-chain slice was stored for this position"
        else:
            stock_px = _finite(row.get("entry_stock_px"))
            if not stock_px or stock_px <= 0:
                stock_px = next((_finite(r.get("underlying_px")) for r in slice_rows
                                 if _finite(r.get("underlying_px"))), None)
            if not stock_px or stock_px <= 0:
                reject = "no entry stock price to choose a strike from"
            else:
                plan, reject = _build_plan(structure, exit_policy, stock_px,
                                           slice_rows, row)

        status = "SELECTED" if plan else "NO_OPTION_TRADE"
        result["status"] = status
        result["reject_reason"] = reject
        result["plan"] = plan

        vals = _selection_values(row, structure, exit_policy, status, reject,
                                 plan, now)
        cur = await writer.exec(_SEL_UPSERT, tuple(vals[c] for c in _SEL_COLS))
        await writer.commit()
        if cur is not None:
            sid_cur = await conn.execute(
                "SELECT id FROM put_flow_option_selections WHERE shortlist_id=? "
                "AND rule_fingerprint=? AND structure=? AND exit_policy=?",
                (shortlist_id, _rule_fingerprint(), structure, exit_policy))
            got = await sid_cur.fetchone()
            result["selection_id"] = got["id"] if got else None
        if status == "NO_OPTION_TRADE":
            log.info("put_flow_option_monitor: %s %s/%s -> NO_OPTION_TRADE (%s)",
                     row["ticker"], structure, exit_policy, reject)
        else:
            log.info("put_flow_option_monitor: %s %s/%s -> SELECTED %s exp %s",
                     row["ticker"], structure, exit_policy,
                     plan["long_symbol"], plan["expiry"])
    except Exception as e:  # noqa: BLE001 — observer: never raise into a caller
        log.warning("put_flow_option_monitor.select_for_position(%s) failed: %s",
                    shortlist_id, e)
        result["status"] = "ERROR"
        result["error"] = str(e)
    return result


def _build_plan(structure: str, exit_policy: str, stock_px: float,
                slice_rows: list[dict], row: dict) -> tuple[dict | None, str | None]:
    """Returns (plan, None) when a contract qualifies, else (None, reason)."""
    is_spread = structure == "PUT_DEBIT_SPREAD"

    expiries = sorted({r["expiry"] for r in slice_rows if r.get("expiry")})
    from_d = (date.fromisoformat(row["planned_exit_session"])
              + timedelta(days=_MIN_DAYS_AFTER_STOCK_EXIT)).isoformat()
    to_d = (date.fromisoformat(row["entry_session"])
            + timedelta(days=_MAX_DAYS_AFTER_ENTRY)).isoformat()
    qualifying = [e for e in expiries if from_d <= e <= to_d]
    if not qualifying:
        return None, (f"no listed expiration between {from_d} and {to_d}; the "
                      f"slice offered {len(expiries)} expiration(s), none in range")
    chosen_expiry = qualifying[0]
    in_exp = [r for r in slice_rows if r.get("expiry") == chosen_expiry]

    targets = _plan_targets(structure, stock_px)
    long_target = next(t for lg, t in targets if lg == "LONG")
    long_c, why = _pick_leg(in_exp, long_target)
    if long_c is None:
        return None, f"long leg (target strike ~{long_target:.2f}): {why}"

    short_c = None
    if is_spread:
        short_target = next(t for lg, t in targets if lg == "SHORT")
        # Clarification C1: pick the short leg's nearest strike from the FULL
        # slice — never step past a strike to keep the two legs apart. If the
        # nearest short and the nearest long are the same contract, that is
        # NO_OPTION_TRADE, not a reason to widen anything.
        short_c, why = _pick_leg(in_exp, short_target)
        if short_c is None:
            return None, f"short leg (target strike ~{short_target:.2f}): {why}"
        if short_c["contract_symbol"] == long_c["contract_symbol"]:
            return None, "spread legs resolved to the same contract"

    long_ask = _finite(long_c.get("ask"))
    long_bid = _finite(long_c.get("bid"))
    short_bid = _finite(short_c.get("bid")) if short_c else None
    short_ask = _finite(short_c.get("ask")) if short_c else None

    entry_cost = long_ask - short_bid if is_spread else long_ask
    if entry_cost is None or entry_cost <= 0:
        return None, f"entry debit is zero or negative ({entry_cost})"

    tp, sp = _EXIT_PCTS[exit_policy]
    n_legs = 2 if is_spread else 1
    plan = {
        "structure": structure,
        "exit_policy": exit_policy,
        "expiry": chosen_expiry,
        "long_symbol": long_c["contract_symbol"],
        "short_symbol": short_c["contract_symbol"] if short_c else None,
        "long_strike": _finite(long_c.get("strike")),
        "short_strike": _finite(short_c.get("strike")) if short_c else None,
        "long_entry_ask": long_ask,
        "long_entry_bid": long_bid,
        "short_entry_bid": short_bid,
        "short_entry_ask": short_ask,
        "long_open_interest": _finite(long_c.get("open_interest")),
        "short_open_interest": _finite(short_c.get("open_interest")) if short_c else None,
        "entry_stock_px": stock_px,
        "entry_cost": entry_cost,
        "entry_commission": _commission_side() * n_legs,
        "target_liq_value": entry_cost * (1.0 + tp) if tp is not None else None,
        "stop_liq_value": entry_cost * (1.0 + sp) if sp is not None else None,
        "is_spread": is_spread,
        "n_legs": n_legs,
    }
    return plan, None


def _selection_values(row: dict, structure: str, exit_policy: str, status: str,
                      reject: str | None, plan: dict | None, now: float) -> dict:
    p = plan or {}
    return {
        "shortlist_id": row["id"], "ticker": row["ticker"],
        "signal_date": row["signal_date"], "entry_session": row["entry_session"],
        "rule_version": _rule_version(), "rule_fingerprint": _rule_fingerprint(),
        "structure": structure,
        "long_symbol": p.get("long_symbol"), "short_symbol": p.get("short_symbol"),
        "expiry": p.get("expiry"),
        "long_strike": p.get("long_strike"), "short_strike": p.get("short_strike"),
        "entry_stock_px": p.get("entry_stock_px", _finite(row.get("entry_stock_px"))),
        "long_entry_ask": p.get("long_entry_ask"),
        "long_entry_bid": p.get("long_entry_bid"),
        "short_entry_bid": p.get("short_entry_bid"),
        "short_entry_ask": p.get("short_entry_ask"),
        "entry_cost": p.get("entry_cost"),
        "entry_commission": p.get("entry_commission"),
        "target_liq_value": p.get("target_liq_value"),
        "stop_liq_value": p.get("stop_liq_value"),
        "max_exit_session": row["planned_exit_session"],
        "max_exit_pt": "06:35",
        "exit_policy": exit_policy,
        "long_open_interest": p.get("long_open_interest"),
        "short_open_interest": p.get("short_open_interest"),
        "selection_status": status,
        "reject_reason": reject,
        "proof_tier": "EXACT_BID_ASK" if status == "SELECTED" else None,
        # C2: set to 1 by a post-pass when ATM_PUT and OTM5_PUT for this
        # position resolved to the very same contract, so downstream never
        # counts them as two independent results.
        "structures_collapsed": 0,
        "created_at": now, "updated_at": now,
    }


async def _select_all_combos(shortlist_id: int, now: float, dry_run: bool) -> list[dict]:
    """Every structure x every exit policy for ONE position — all nine
    candidates, always. The config `structure`/`exit_policy` keys name only
    which one a card would DISPLAY; every combination is still recorded so the
    forward evidence exists for all nine."""
    results = []
    for st in STRUCTURES:
        for ex in EXIT_POLICIES:
            results.append(await select_for_position(
                shortlist_id, structure=st, exit_policy=ex,
                now=now, dry_run=dry_run))
    await _mark_structures_collapsed(shortlist_id, now, dry_run=dry_run)
    return results


async def _mark_structures_collapsed(shortlist_id: int, now: float, *,
                                     dry_run: bool = False) -> None:
    """C2: when ATM_PUT and OTM5_PUT for this position resolved to the exact
    same contract, flag every ATM_PUT/OTM5_PUT row so a later reader does not
    treat them as two independent results. PUT_DEBIT_SPREAD is untouched.

    A dry run writes nothing — the guard lives here, not only at the call site,
    so a future caller cannot bypass it."""
    if dry_run:
        return
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT structure, long_symbol FROM put_flow_option_selections "
        "WHERE shortlist_id=? AND rule_fingerprint=? AND selection_status='SELECTED' "
        "AND structure IN ('ATM_PUT','OTM5_PUT')",
        (shortlist_id, _rule_fingerprint()))
    got = {r["structure"]: r["long_symbol"] for r in await cur.fetchall()}
    collapsed = (got.get("ATM_PUT") is not None
                 and got.get("ATM_PUT") == got.get("OTM5_PUT"))
    await conn.execute(
        "UPDATE put_flow_option_selections SET structures_collapsed=?, updated_at=? "
        "WHERE shortlist_id=? AND rule_fingerprint=? "
        "AND structure IN ('ATM_PUT','OTM5_PUT')",
        (1 if collapsed else 0, now, shortlist_id, _rule_fingerprint()))
    await conn.commit()


async def select_for_shortlist(shortlist_id: int, *, now: float | None = None,
                               dry_run: bool = False) -> list[dict]:
    """All nine candidates for ONE position, then hand back the stored rows so
    the owner-only card can render them without a second query. Used by the 6:35
    entry job right after the chain slice is saved."""
    now = _now(now)
    await _select_all_combos(shortlist_id, now, dry_run)
    if dry_run:
        return []
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM put_flow_option_selections WHERE shortlist_id=? "
        "AND rule_fingerprint=?", (shortlist_id, _rule_fingerprint()))
    return [dict(r) for r in await cur.fetchall()]


async def select_open_positions(session: str | None = None, dry_run: bool = False,
                                now: float | None = None) -> dict:
    """All nine candidates for every ENTERED shortlist position. A position with
    no stored ENTRY slice is still recorded, with a reject reason distinct from
    any liquidity refusal, rather than silently skipped."""
    now = _now(now)
    conn = await db.get_db()

    cur = await conn.execute(
        "SELECT id FROM put_flow_shortlist WHERE status='ENTERED'"
        + (" AND entry_session <= ?" if session else "") + " ORDER BY id",
        ((session,) if session else ()))
    ids = [r["id"] for r in await cur.fetchall()]

    out = {"session": session, "positions": len(ids), "selected": 0,
           "no_option_trade": 0, "no_entry_slice": 0, "errors": 0, "rows": []}
    for sid in ids:
        for r in await _select_all_combos(sid, now, dry_run):
            no_slice = (r["status"] == "NO_OPTION_TRADE"
                        and (r["reject_reason"] or "").startswith("no ENTRY option-chain"))
            out["rows"].append({"shortlist_id": sid, "structure": r["structure"],
                                "exit_policy": r["exit_policy"], "status": r["status"],
                                "reject_reason": r["reject_reason"],
                                "error": r["error"]})
            if r["status"] == "SELECTED":
                out["selected"] += 1
            elif no_slice:
                out["no_entry_slice"] += 1
            elif r["status"] == "NO_OPTION_TRADE":
                out["no_option_trade"] += 1
            else:
                out["errors"] += 1
    return out


# ── the live monitor session ───────────────────────────────────────────────

class _MinuteAgg:
    """One CONTRACT's ticks for one Pacific minute. Keyed by contract symbol,
    NEVER by selection — three exit policies watching the same put share one
    quote, so one row. `sel_id`/`leg` are carried for provenance only (the first
    selection that referenced the contract this minute)."""

    __slots__ = ("sel_id", "leg", "minute_pt", "minute_epoch", "bid", "ask",
                 "last", "mark", "volume", "open_interest", "poll_count",
                 "usable_polls", "stale_polls", "first_at", "last_at",
                 "provider_quote_time", "max_age", "quality")

    def __init__(self, leg: str, minute_pt: str, minute_epoch: float,
                 sel_id: int | None = None):
        self.sel_id = sel_id
        self.leg = leg
        self.minute_pt = minute_pt
        self.minute_epoch = minute_epoch
        self.bid = [None, None, None, None]
        self.ask = [None, None, None, None]
        self.last = [None, None, None, None]
        self.mark = [None, None, None, None]
        self.volume = None
        self.open_interest = None
        self.poll_count = 0
        self.usable_polls = 0
        self.stale_polls = 0
        self.first_at = None
        self.last_at = None
        self.provider_quote_time = None
        self.max_age = None
        self.quality = "MISSING"

    def observe(self, *, bid, ask, last, mark, volume, oi, quote_time, age,
                quality, at):
        self.poll_count += 1
        if quality == "OK":
            self.usable_polls += 1
        elif quality == "STALE":
            self.stale_polls += 1
        for slot, val in ((self.bid, bid), (self.ask, ask), (self.last, last),
                          (self.mark, mark)):
            if val is None:
                continue
            slot[0] = val if slot[0] is None else slot[0]
            slot[1] = val if slot[1] is None else max(slot[1], val)
            slot[2] = val if slot[2] is None else min(slot[2], val)
            slot[3] = val
        if volume is not None:
            self.volume = volume
        if oi is not None:
            self.open_interest = oi
        if quote_time:
            self.provider_quote_time = quote_time
        if age is not None:
            self.max_age = age if self.max_age is None else max(self.max_age, age)
        if _QUALITY_RANK[quality] > _QUALITY_RANK[self.quality]:
            self.quality = quality
        if self.first_at is None:
            self.first_at = at
        self.last_at = at


_MIN_COLS = (
    "selection_id", "contract_symbol", "leg", "session_date", "minute_pt",
    "minute_epoch", "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close", "last_open", "last_high",
    "last_low", "last_close", "mark_open", "mark_high", "mark_low", "mark_close",
    "volume", "open_interest", "poll_count", "usable_polls", "stale_polls",
    "first_observed_at", "last_observed_at", "provider_quote_time",
    "max_quote_age_sec", "quote_quality", "created_at",
)
# UNIQUE(contract_symbol, session_date, minute_pt): one row per contract per
# minute. A repeat within the same run (or a restart re-touching the minute)
# updates that row with the latest in-memory aggregate rather than piling on
# duplicates.
_MIN_INSERT = (
    "INSERT INTO put_flow_option_minutes (" + ",".join(_MIN_COLS) + ") "
    "VALUES (" + ",".join("?" for _ in _MIN_COLS) + ") "
    "ON CONFLICT(contract_symbol, session_date, minute_pt) DO UPDATE SET "
    + ",".join(f"{c}=excluded.{c}" for c in _MIN_COLS
               if c not in ("contract_symbol", "session_date", "minute_pt",
                             "created_at"))
)

_EV_COLS = (
    "selection_id", "event_type", "event_seq", "session_date", "minute_pt",
    "observed_at", "liq_value", "long_bid", "long_ask", "short_bid", "short_ask",
    "entry_cost", "gross_pnl_usd", "commission_usd", "net_pnl_usd", "net_pct",
    "proof_tier", "quote_quality", "gap_start_pt", "gap_end_pt",
    "supersedes_event_id", "note", "created_at",
)
_EV_INSERT = (
    "INSERT OR IGNORE INTO put_flow_option_events (" + ",".join(_EV_COLS) + ") "
    "VALUES (" + ",".join("?" for _ in _EV_COLS) + ")"
)


class _SelState:
    """In-memory monitor state for one selection during a run."""

    def __init__(self, sel: dict):
        self.id = sel["id"]
        self.ticker = sel["ticker"]
        self.structure = sel["structure"]
        self.exit_policy = sel["exit_policy"]
        self.is_spread = sel["structure"] == "PUT_DEBIT_SPREAD"
        self.long_symbol = sel["long_symbol"]
        self.short_symbol = sel["short_symbol"]
        self.entry_cost = _finite(sel["entry_cost"])
        self.target_liq_value = _finite(sel["target_liq_value"])
        self.stop_liq_value = _finite(sel["stop_liq_value"])
        self.max_exit_session = sel["max_exit_session"]
        self.n_legs = 2 if self.is_spread else 1
        self.resolved = bool(sel.get("_resolved"))
        # first usable liquidation value seen at or after 06:35 (for TIME_EXIT)
        self.first_obs = None

    @property
    def symbols(self) -> list[str]:
        return [s for s in (self.long_symbol, self.short_symbol) if s]

    def liquidation(self, legq: dict) -> float | None:
        """Position liquidation value from this poll's leg quotes, or None when
        a needed leg is not a fresh two-sided quote."""
        lq = legq.get(self.long_symbol)
        if not lq or lq["quality"] != "OK" or lq["bid"] is None:
            return None
        if not self.is_spread:
            return lq["bid"]
        sq = legq.get(self.short_symbol)
        if not sq or sq["quality"] != "OK" or sq["ask"] is None:
            return None
        return lq["bid"] - sq["ask"]

    def pnl(self, exit_liq: float | None) -> dict:
        if exit_liq is None or self.entry_cost is None or self.entry_cost <= 0:
            return {"gross": None, "commission": None, "net": None, "pct": None}
        mult = 100.0
        gross = (exit_liq - self.entry_cost) * mult
        commission = _commission_side() * 2 * self.n_legs
        net = gross - commission
        return {"gross": gross, "commission": commission, "net": net,
                "pct": 100.0 * net / (self.entry_cost * mult)}


def _map_leg_quote(q: dict | None, now: float, max_age: int) -> dict:
    """One leg's usable numbers from a Schwab /quotes entry (or a MISSING stub)."""
    if not q:
        return {"bid": None, "ask": None, "last": None, "mark": None,
                "volume": None, "oi": None, "quote_time": None, "age": None,
                "quality": "MISSING"}
    bid = _finite(q.get("bid"))
    ask = _finite(q.get("ask"))
    last = _finite(q.get("c"))
    qt = _finite(q.get("quote_time")) or _finite(q.get("t"))
    age = (now - qt) if qt else None
    return {
        "bid": bid, "ask": ask, "last": last,
        "mark": _option_mark(bid, ask),
        "volume": _finite(q.get("v")), "oi": None,
        "quote_time": qt, "age": age,
        "quality": _quote_quality(bid, ask, qt, now, max_age),
    }


async def _load_active(conn, session: str) -> list[dict]:
    """SELECTED rows entered on/before `session` with no TARGET/STOP/TIME_EXIT
    event yet. This is also exactly the restart-resume set."""
    cur = await conn.execute(
        "SELECT s.* FROM put_flow_option_selections s "
        "WHERE s.selection_status='SELECTED' AND s.entry_session <= ? "
        "AND NOT EXISTS (SELECT 1 FROM put_flow_option_events e "
        "  WHERE e.selection_id = s.id "
        "  AND e.event_type IN ('TARGET','STOP','TIME_EXIT')) "
        "ORDER BY s.id", (session,))
    return [dict(r) for r in await cur.fetchall()]


async def _next_seq(conn, selection_id: int, event_type: str) -> int:
    cur = await conn.execute(
        "SELECT COALESCE(MAX(event_seq), 0) AS m FROM put_flow_option_events "
        "WHERE selection_id=? AND event_type=?", (selection_id, event_type))
    return int((await cur.fetchone())["m"]) + 1


async def _has_exit_event(conn, selection_id: int) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM put_flow_option_events WHERE selection_id=? "
        "AND event_type IN ('TARGET','STOP','TIME_EXIT') LIMIT 1", (selection_id,))
    return (await cur.fetchone()) is not None


async def run_session(session: str | None = None, *, dry_run: bool = False,
                      once: bool = False, quote_fn=None, sleep_fn=None,
                      clock=None) -> dict:
    """Poll every open option leg once per 15 s from just before 06:35 to just
    after 13:00 Pacific, writing one minute row per contract and an immutable
    event on the first target/stop touch or the frozen time-exit.

    Injectables (tests): quote_fn(list[str])->dict, sleep_fn(sec) coroutine,
    clock()->epoch seconds.

    Never raises. A dry run cannot write to the database.
    """
    clock = clock or time.time
    if sleep_fn is None:
        import asyncio
        sleep_fn = asyncio.sleep
    if quote_fn is None:
        from consensus_engine.scanners import schwab_client
        quote_fn = schwab_client.get_quotes

    started = clock()
    session = session or pacific_date(started)
    res = {"session": session, "dry_run": dry_run, "started_at": started,
           "finished_at": None, "selections_expected": 0, "selections_monitored": 0,
           "quote_batches": 0, "usable_observations": 0, "stale_observations": 0,
           "missing_observations": 0, "minutes_written": 0, "events_written": 0,
           "restart": False, "restart_count": 0, "skipped": None, "error": None}

    if not is_trading_day(session):
        res["skipped"] = "not a trading day"
        log.info("put_flow_option_monitor: %s is not a trading day — nothing to do",
                 session)
        return res

    writer = None
    conn = None
    errors: list[str] = []
    try:
        conn = await db.get_db()
        writer = _NullWriter() if dry_run else _Writer(conn)

        # restart detection + audit row
        cur = await conn.execute(
            "SELECT restart_count FROM put_flow_option_monitor_runs WHERE session_date=?",
            (session,))
        prior = await cur.fetchone()
        is_restart = prior is not None
        res["restart"] = is_restart

        active_rows = await _load_active(conn, session)
        res["selections_expected"] = len(active_rows)
        state: dict[int, _SelState] = {r["id"]: _SelState(r) for r in active_rows}

        # The session window comes from the exchange calendar, NEVER from the
        # `start_pt` config key — that key can be overridden, and a gap record
        # anchored to a moved value flip-flopped between "06:30", "00:00" and
        # "16:58" for one selection on one day (D5).
        bounds = session_bounds(date.fromisoformat(session))
        session_open_epoch = (bounds[0].timestamp() if bounds
                              else _pt_epoch(session, "06:30"))
        session_open_pt = pacific_minute(session_open_epoch)

        if not dry_run:
            await _upsert_run_row(writer, session, started, len(active_rows),
                                  is_restart)
        if is_restart and not dry_run:
            res["restart_count"] = int(prior["restart_count"]) + 1
            await _record_restart_gaps(conn, writer, session, state, clock(),
                                       session_open_pt)
        elif not dry_run and state and (clock() - session_open_epoch) > 120:
            # A session the monitor never ran AT ALL leaves no prior row, so the
            # restart path above never fires and the missed hours vanish. That
            # happened on 2026-08-27: the service died on startup, six
            # selections went unwatched from 06:30 to 16:58, and nothing
            # recorded it. If this first start is already late, the hole between
            # the session open and now is real and must be visible (D3).
            await _record_restart_gaps(conn, writer, session, state, clock(),
                                       session_open_pt, late_first_start=True)

        max_age = _quote_max_age()
        interval = _poll_interval()
        start_epoch = _pt_epoch(session, _start_pt())
        stop_epoch = _pt_epoch(session, _stop_pt())
        entry_epoch = _pt_epoch(session, "06:35")
        if bounds:
            stop_epoch = min(stop_epoch, bounds[1].timestamp() + 60)

        # current-minute aggregation buckets, keyed by CONTRACT SYMBOL only —
        # one row per contract per minute no matter how many selections watch it
        buckets: dict[str, _MinuteAgg] = {}
        cur_minute = None
        max_legs = _max_legs()
        over_cap_warned = False

        if not once:
            while clock() < start_epoch:
                await sleep_fn(min(interval, max(0.0, start_epoch - clock())))

        while True:
            t0 = clock()
            if not once and t0 >= stop_epoch:
                break

            # pick up selections created after this run started (e.g. today's
            # own entry a few minutes ago) without dropping in-flight state
            for r in await _load_active(conn, session):
                if r["id"] not in state:
                    state[r["id"]] = _SelState(r)
                    res["selections_expected"] = max(res["selections_expected"],
                                                     len(state))

            live = [s for s in state.values()
                    if not s.resolved and s.max_exit_session >= session]

            # distinct contracts across every live selection, plus the first
            # (selection, leg) that names each — provenance only
            prov: dict[str, tuple[int, str]] = {}
            for s in live:
                for leg_name, sym in (("LONG", s.long_symbol),
                                      ("SHORT", s.short_symbol)):
                    if sym:
                        prov.setdefault(sym, (s.id, leg_name))
            symbols = sorted(prov)
            if len(symbols) > max_legs:
                if not over_cap_warned:
                    log.warning("put_flow_option_monitor: %d open legs exceeds the "
                                "%d-leg cap; watching the first %d",
                                len(symbols), max_legs, max_legs)
                    over_cap_warned = True
                symbols = symbols[:max_legs]

            minute_pt = pacific_minute(t0)
            if cur_minute is not None and minute_pt != cur_minute:
                res["minutes_written"] += await _flush(writer, buckets, session)
                buckets.clear()
            cur_minute = minute_pt

            quotes: dict[str, dict] = {}
            if symbols:
                res["quote_batches"] += 1
                try:
                    quotes = quote_fn(symbols) or {}
                except Exception as e:  # noqa: BLE001 — Schwab problem, stay soft
                    errors.append(f"{minute_pt} quote batch: {e}")
                    log.warning("put_flow_option_monitor: quote batch failed: %s", e)
                    quotes = {}

            # map each distinct contract ONCE, aggregate it ONCE
            mapped_by_sym: dict[str, dict] = {}
            for sym in symbols:
                mapped = _map_leg_quote(quotes.get(sym), t0, max_age)
                mapped_by_sym[sym] = mapped
                agg = buckets.get(sym)
                if agg is None:
                    sel_id, leg_name = prov[sym]
                    agg = _MinuteAgg(leg_name, minute_pt, t0, sel_id)
                    buckets[sym] = agg
                agg.observe(bid=mapped["bid"], ask=mapped["ask"],
                            last=mapped["last"], mark=mapped["mark"],
                            volume=mapped["volume"], oi=mapped["oi"],
                            quote_time=mapped["quote_time"], age=mapped["age"],
                            quality=mapped["quality"], at=t0)
                if mapped["quality"] == "OK":
                    res["usable_observations"] += 1
                elif mapped["quality"] == "STALE":
                    res["stale_observations"] += 1
                else:
                    res["missing_observations"] += 1

            # every selection reads the SAME per-contract quote; only the sign of
            # each leg's use differs (a contract can be one selection's long leg
            # and another's short leg)
            legq_by_sel: dict[int, dict] = {
                s.id: {sym: mapped_by_sym[sym] for sym in s.symbols
                       if sym in mapped_by_sym}
                for s in live
            }

            # events: first target/stop touch wins; same poll -> STOP
            at_or_after_entry = t0 >= entry_epoch
            for s in live:
                liq = s.liquidation(legq_by_sel.get(s.id, {}))
                if at_or_after_entry and s.first_obs is None and liq is not None:
                    s.first_obs = {"liq": liq, "minute_pt": minute_pt, "at": t0,
                                   "legq": legq_by_sel.get(s.id, {})}
                if liq is None:
                    continue
                stop_hit = (s.stop_liq_value is not None and liq <= s.stop_liq_value)
                target_hit = (s.target_liq_value is not None and liq >= s.target_liq_value)
                if not (stop_hit or target_hit):
                    continue
                etype = "STOP" if stop_hit else "TARGET"
                if await _record_exit(conn, writer, s, etype, liq, minute_pt, t0,
                                      legq_by_sel.get(s.id, {}), session):
                    res["events_written"] += 1
                s.resolved = True

            if once:
                break
            spent = clock() - t0
            await sleep_fn(max(0.0, interval - spent))

        # flush the final partial minute
        res["minutes_written"] += await _flush(writer, buckets, session)

        # time-exit sweep: due or overdue, still unresolved
        for s in state.values():
            if s.resolved or s.max_exit_session > session:
                continue
            if await _has_exit_event(conn, s.id):
                continue
            late = s.max_exit_session < session
            obs = s.first_obs
            liq = obs["liq"] if obs else None
            legq = obs["legq"] if obs else {}
            mpt = obs["minute_pt"] if obs else None
            at = obs["at"] if obs else clock()
            note = "frozen fourth-session time exit"
            if late:
                note = (f"time exit recorded late; frozen exit date was "
                        f"{s.max_exit_session}, monitored on {session}")
            if await _record_exit(conn, writer, s, "TIME_EXIT", liq, mpt, at,
                                  legq, session, note=note,
                                  quality=("MISSING" if liq is None else "OK")):
                res["events_written"] += 1
            s.resolved = True

        res["finished_at"] = clock()
        if not dry_run:
            await _health(session, res)
    except Exception as e:  # noqa: BLE001 — observer must never raise
        log.warning("put_flow_option_monitor.run_session failed: %s", e)
        res["error"] = str(e)
        res["finished_at"] = res["finished_at"] or (clock() if clock else time.time())
    finally:
        # The audit row is written HERE, not in the try, so a run that throws
        # still records what it actually managed to store. Left in the try it
        # produced a row claiming 0 minutes and 0 events while the tables held
        # 2 minutes and 36 events -- an audit row that lies is worse than none.
        if not dry_run and writer is not None:
            try:
                # minutes are keyed by contract, so a selection counts as
                # monitored when at least one of its contracts got a stored
                # minute row -- computed here so even a crashed run reports it
                _c = await conn.execute(
                    "SELECT DISTINCT contract_symbol FROM put_flow_option_minutes "
                    "WHERE session_date=?", (session,))
                seen = {r["contract_symbol"] for r in await _c.fetchall()}
                st = locals().get("state") or {}
                res["selections_monitored"] = sum(
                    1 for s in st.values()
                    if any(sym in seen for sym in s.symbols))
            except Exception:  # noqa: BLE001
                pass
            try:
                await _finalize_run_row(writer, session, res, errors)
            except Exception:  # noqa: BLE001
                log.warning("could not finalize the monitor run row for %s", session)
        # The health alert (and nothing else here) can open the shared aiohttp
        # session. Close it so a 6.5-hour run does not leave "Unclosed client
        # session" behind; get_session() re-creates it on next use.
        try:
            from consensus_engine.utils.http import close_session
            await close_session()
        except Exception:  # noqa: BLE001
            pass
    return res


async def _flush(writer, buckets: dict, session: str) -> int:
    written = 0
    now = time.time()
    for sym, a in buckets.items():
        vals = {
            "selection_id": a.sel_id, "contract_symbol": sym, "leg": a.leg,
            "session_date": session, "minute_pt": a.minute_pt,
            "minute_epoch": a.minute_epoch,
            "bid_open": a.bid[0], "bid_high": a.bid[1], "bid_low": a.bid[2], "bid_close": a.bid[3],
            "ask_open": a.ask[0], "ask_high": a.ask[1], "ask_low": a.ask[2], "ask_close": a.ask[3],
            "last_open": a.last[0], "last_high": a.last[1], "last_low": a.last[2], "last_close": a.last[3],
            "mark_open": a.mark[0], "mark_high": a.mark[1], "mark_low": a.mark[2], "mark_close": a.mark[3],
            "volume": a.volume, "open_interest": a.open_interest,
            "poll_count": a.poll_count, "usable_polls": a.usable_polls,
            "stale_polls": a.stale_polls, "first_observed_at": a.first_at,
            "last_observed_at": a.last_at, "provider_quote_time": a.provider_quote_time,
            "max_quote_age_sec": a.max_age, "quote_quality": a.quality,
            "created_at": now,
        }
        cur = await writer.exec(_MIN_INSERT, tuple(vals[c] for c in _MIN_COLS))
        if cur is not None and getattr(cur, "rowcount", 0):
            written += 1
    return written


async def _record_exit(conn, writer, s: "_SelState", etype: str,
                       liq: float | None, minute_pt: str | None, at: float,
                       legq: dict, session: str, *, note: str | None = None,
                       quality: str = "OK") -> bool:
    """Write one immutable exit event. First of TARGET/STOP/TIME_EXIT wins."""
    if await _has_exit_event(conn, s.id):
        return False
    lq = legq.get(s.long_symbol) or {}
    sq = legq.get(s.short_symbol) or {} if s.is_spread else {}
    pnl = s.pnl(liq)
    vals = {
        "selection_id": s.id, "event_type": etype,
        "event_seq": await _next_seq(conn, s.id, etype),
        "session_date": session, "minute_pt": minute_pt, "observed_at": at,
        "liq_value": liq,
        "long_bid": lq.get("bid"), "long_ask": lq.get("ask"),
        "short_bid": sq.get("bid"), "short_ask": sq.get("ask"),
        "entry_cost": s.entry_cost,
        "gross_pnl_usd": pnl["gross"], "commission_usd": pnl["commission"],
        "net_pnl_usd": pnl["net"], "net_pct": pnl["pct"],
        "proof_tier": "EXACT_BID_ASK" if liq is not None else "UNKNOWN",
        "quote_quality": quality,
        "gap_start_pt": None, "gap_end_pt": None, "supersedes_event_id": None,
        "note": note, "created_at": time.time(),
    }
    await writer.exec(_EV_INSERT, tuple(vals[c] for c in _EV_COLS))
    # a mirrored FINAL_RESULT summary row (immutable, seq 1)
    fr = dict(vals)
    fr["event_type"] = "FINAL_RESULT"
    fr["event_seq"] = await _next_seq(conn, s.id, "FINAL_RESULT")
    fr["note"] = f"final result via {etype}"
    await writer.exec(_EV_INSERT, tuple(fr[c] for c in _EV_COLS))
    await writer.commit()
    return True


async def _record_restart_gaps(conn, writer, session: str,
                               state: dict, now: float, session_open_pt: str,
                               late_first_start: bool = False) -> None:
    """A visible QUOTE_GAP for the interval nobody watched, plus (on a genuine
    restart) one MONITOR_RESTART event per active selection.

    The gap start is the last minute actually observed for that selection's
    CONTRACT(s); with nothing observed it falls back to `session_open_pt`, the
    calendar's real open — never a config value (D5).

    `late_first_start` marks the case where this is the FIRST run of the day and
    it is already late -- the monitor never started on time (D3), so nothing
    "restarted"; only the QUOTE_GAP is written.
    """
    end_pt = pacific_minute(now)
    for s in state.values():
        syms = s.symbols or [""]
        cur = await conn.execute(
            "SELECT MAX(minute_pt) AS m FROM put_flow_option_minutes "
            "WHERE session_date=? AND contract_symbol IN (%s)"
            % ",".join("?" for _ in syms),
            (session, *syms))
        last_seen = (await cur.fetchone())["m"]
        gap_start = last_seen or session_open_pt
        # A well-formed gap runs forward. If the recorded end is not after the
        # start (a clock that jumped backwards, a restart before the first
        # poll), do NOT dress it up as a normal interval — mark it an anomaly.
        backwards = end_pt <= gap_start
        gap_note = (f"CLOCK ANOMALY: gap end {end_pt} is not after start "
                    f"{gap_start} Pacific — unobserved interval cannot be trusted"
                    if backwards else
                    f"no observations {gap_start}–{end_pt} Pacific "
                    + ("(monitor never started for this session)"
                       if late_first_start else "(monitor was not running)"))
        etypes = (("QUOTE_GAP", {"gap_start_pt": gap_start, "gap_end_pt": end_pt}),)
        if not late_first_start:
            etypes = (("MONITOR_RESTART", {}),) + etypes
        for etype, extra in etypes:
            vals = {c: None for c in _EV_COLS}
            vals.update({
                "selection_id": s.id, "event_type": etype,
                "event_seq": await _next_seq(conn, s.id, etype),
                "session_date": session, "minute_pt": end_pt, "observed_at": now,
                "quote_quality": "MISSING",
                "note": ("monitor restarted mid-session" if etype == "MONITOR_RESTART"
                         else gap_note),
                "created_at": time.time(),
            })
            vals.update(extra)
            await writer.exec(_EV_INSERT, tuple(vals[c] for c in _EV_COLS))
    await writer.commit()


async def _upsert_run_row(writer, session: str, started: float,
                          expected: int, is_restart: bool) -> None:
    await writer.exec(
        "INSERT INTO put_flow_option_monitor_runs "
        "(session_date, started_at, selections_expected, restart_count) "
        "VALUES (?,?,?,0) "
        "ON CONFLICT(session_date) DO UPDATE SET "
        "  selections_expected=excluded.selections_expected, "
        "  restart_count=put_flow_option_monitor_runs.restart_count + 1",
        (session, started, expected))
    await writer.commit()


async def _finalize_run_row(writer, session: str, res: dict,
                            errors: list[str]) -> None:
    await writer.exec(
        "UPDATE put_flow_option_monitor_runs SET finished_at=?, "
        "selections_monitored=?, quote_batches=?, usable_observations=?, "
        "stale_observations=?, missing_observations=?, minutes_written=?, "
        "events_written=?, errors_json=? WHERE session_date=?",
        (res["finished_at"], res["selections_monitored"], res["quote_batches"],
         res["usable_observations"], res["stale_observations"],
         res["missing_observations"], res["minutes_written"], res["events_written"],
         json.dumps(errors) if errors else None, session))
    await writer.commit()


_HEALTH_KEY = "put_flow_option_monitor"


async def _health(session: str, res: dict) -> None:
    """Silent when healthy. One #errors alert when selections were expected but
    zero usable observations landed, and one recovery when healthy again."""
    if res["selections_expected"] <= 0:
        return
    healthy = res["usable_observations"] > 0
    try:
        from consensus_engine.alerts.ops_alert import report_ops_state
        await report_ops_state(
            _HEALTH_KEY,
            down=not healthy,
            failure_class="no_usable_observations",
            title="Put-flow option monitor stored no usable option quotes",
            detail=(f"{res['selections_expected']} option selection(s) were open on "
                    f"{session}, but the monitor stored zero usable quote "
                    f"observations. The stock-pair trades are unaffected — only the "
                    f"option measurement is missing for this day."),
            fix="Check the put-flow-option-monitor-run timer log and Schwab auth.",
            confirm_after_s=0,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("put_flow_option_monitor: health alert failed: %s", e)


# ── owner-facing text (counts only, never a raw chain) ──────────────────────

def summarize_selection(result: dict) -> str:
    p = result.get("plan")
    tk = result.get("ticker") or f"#{result.get('shortlist_id')}"
    head = f"{tk} · {result.get('structure')}/{result.get('exit_policy')}: {result.get('status')}"
    if result.get("status") == "SELECTED" and p:
        legs = p["long_symbol"] + (f" / {p['short_symbol']}" if p.get("short_symbol") else "")
        if p.get("target_liq_value") is not None:
            tail = (f"target liq ${p['target_liq_value']:.2f}, "
                    f"stop liq ${p['stop_liq_value']:.2f}")
        else:
            tail = "time exit only"
        return (f"{head}\n  {legs}  exp {p['expiry']}\n"
                f"  entry debit ${p['entry_cost']:.2f}/share, {tail}")
    if result.get("status") == "NO_OPTION_TRADE":
        return f"{head}\n  reason: {result.get('reject_reason')}"
    return f"{head}\n  error: {result.get('error')}"


def summarize_run(res: dict) -> str:
    if res.get("skipped"):
        return f"{res['session']}: {res['skipped']}"
    return (f"{res['session']}: {res['selections_expected']} selection(s) expected, "
            f"{res['selections_monitored']} observed, {res['quote_batches']} quote "
            f"batches, {res['minutes_written']} minute rows, {res['events_written']} "
            f"event(s), {res['usable_observations']} usable / "
            f"{res['stale_observations']} stale / {res['missing_observations']} missing "
            f"observations"
            + (f", RESTART x{res['restart_count']}" if res.get("restart") else ""))
