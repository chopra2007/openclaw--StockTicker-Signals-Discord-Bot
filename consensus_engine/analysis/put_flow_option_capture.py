"""TODO #98 — forward option-chain and borrow collection for TODO #96 positions.

Why this exists, in plain words: TODO #97 showed that every question about
option profit on this project comes back UNKNOWN forever, because no past
session ever saved the option chain at the moment of a trade. This module
starts saving it, from the next TODO #96 trade onward, so a future session can
freeze a long-put or put-spread rule and actually test it — honestly, using
only what was knowable at the time.

This module NEVER picks, ranks or rejects a stock. It NEVER places an order.
It NEVER changes TODO #96's frozen rule, timing, hold length, or 0.25% cost.
It is an OBSERVER: if it fails for one ticker, that ticker's trade still goes
through untouched — every public function here is fail-soft per ticker.

Three moments, all keyed to a TODO #96 shortlist row (`put_flow_shortlist`):

  ENTRY  — at the 6:35 a.m. Pacific entry, store the WHOLE bounded PUT slice
           for that ticker (every contract that survives the expiry/strike
           bounds — never a hand-picked "best" contract).
  MARK   — at every 6:35 a.m. Pacific morning while the pair stays open,
           re-price the SAME contract symbols stored at ENTRY. Nothing new is
           ever added at MARK or EXIT.
  EXIT   — at the pair's close, same rule as MARK.

`quote_quality` is the honesty label carried on every stored row: OK (a real,
fresh two-sided quote), STALE (two-sided but old, or of unconfirmed age),
NO_TWO_SIDED (the contract answered but bid/ask is unusable), or MISSING (the
contract did not come back at all). A STALE or MISSING row stays that way —
nothing here ever back-fills a price from `last` or from a later snapshot.

Storage is local-only. The Schwab personal-use terms (see
consensus_engine/scanners/schwab_client.py) forbid posting or publishing a raw
per-strike chain, so nothing here renders one to Discord or writes one into
the repo — `report()` returns counts and quality labels, never a raw chain.

Reuses the existing Schwab client (`consensus_engine.scanners.schwab_client`)
exclusively. No second Schwab client is added here.

Schwab's own per-contract `mark`, `bidSize` and `askSize` are mapped through
by the shared client (`_chain_map_to_df` in schwab_client.py, added for this
work). `mark` here is Schwab's own figure when it sent one, and the bid/ask
midpoint otherwise — never `last`, and never invented.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import time
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger(__name__)

PT = ZoneInfo("America/Los_Angeles")

STAGES = ("ENTRY", "MARK", "EXIT")
QUALITIES = ("OK", "STALE", "NO_TWO_SIDED", "MISSING")

# --- config reads (TODO #98 keys already live under put_flow_shortlist.option_capture) ---

_CFG_BASE = "put_flow_shortlist.option_capture"


def enabled() -> bool:
    return bool(cfg.get(f"{_CFG_BASE}.enabled", False))


def _min_days_after_stock_exit() -> int:
    return int(cfg.get(f"{_CFG_BASE}.min_days_after_stock_exit", 7))


def _max_days_after_entry() -> int:
    return int(cfg.get(f"{_CFG_BASE}.max_days_after_entry", 45))


def _strike_low_pct() -> float:
    return float(cfg.get(f"{_CFG_BASE}.strike_low_pct", 0.70))


def _strike_high_pct() -> float:
    return float(cfg.get(f"{_CFG_BASE}.strike_high_pct", 1.10))


def _quote_max_age_sec() -> int:
    return int(cfg.get(f"{_CFG_BASE}.quote_max_age_sec", 900))


def _max_contracts_per_capture() -> int:
    return int(cfg.get(f"{_CFG_BASE}.max_contracts_per_capture", 400))


# --- small helpers -----------------------------------------------------------

def _now(now: float | None) -> float:
    return time.time() if now is None else now


def pacific_session(ts: float) -> str:
    """The Pacific calendar date (YYYY-MM-DD) for an epoch-seconds timestamp."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, PT).date().isoformat()


def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def expiration_window(row: dict) -> tuple[str, str]:
    """[from_date, to_date] for the bounded PUT slice, per the frozen contract:
    from = planned stock-pair exit + `min_days_after_stock_exit` calendar days,
    to   = entry session + `max_days_after_entry` calendar days.
    """
    exit_session = row["planned_exit_session"]
    entry_session = row["entry_session"]
    from_date = date.fromisoformat(exit_session) + timedelta(days=_min_days_after_stock_exit())
    to_date = date.fromisoformat(entry_session) + timedelta(days=_max_days_after_entry())
    return from_date.isoformat(), to_date.isoformat()


def strike_window(stock_px: float) -> tuple[float, float]:
    """[low, high] PUT strike bounds for the given stock price."""
    return stock_px * _strike_low_pct(), stock_px * _strike_high_pct()


def quote_quality(bid, ask, quote_time_sec: float | None, now: float,
                  max_age_sec: int) -> str:
    """OK / STALE / NO_TWO_SIDED per the honesty rule. A missing/unusable side
    is NO_TWO_SIDED regardless of age. An unconfirmed quote time (missing or
    zero) cannot be proven fresh, so it is treated as STALE, never OK."""
    b, a = _finite(bid), _finite(ask)
    if b is None or a is None or b <= 0 or a <= 0 or a < b:
        return "NO_TWO_SIDED"
    if not quote_time_sec or quote_time_sec <= 0:
        return "STALE"
    age = now - quote_time_sec
    if age > max_age_sec:
        return "STALE"
    return "OK"


def option_mark(bid, ask, provider_mark=None) -> float | None:
    """Schwab's own mark when it sent one, else the bid/ask midpoint when both
    sides are usable, else None.

    Never `last`. Storing the provider's mark loses nothing — the midpoint is
    always recomputable from the stored bid and ask — and it keeps a real
    provider field for auditing rather than only a number we derived.
    """
    pm = _finite(provider_mark)
    if pm is not None and pm > 0:
        return pm
    b, a = _finite(bid), _finite(ask)
    if b is None or a is None or b <= 0 or a <= 0 or a < b:
        return None
    return (b + a) / 2.0


# --- writing rows --------------------------------------------------------

_OPT_COLS = (
    "shortlist_id", "ticker", "stage", "capture_session", "captured_at",
    "contract_symbol", "expiry", "strike", "option_type", "bid", "ask", "last",
    "mark", "provider_quote_time", "quote_age_sec", "volume", "open_interest",
    "implied_vol", "delta", "gamma", "theta", "vega", "rho", "multiplier",
    "non_standard", "deliverable_note", "underlying_px", "spy_px",
    "chain_underlying_px", "chain_is_delayed", "quote_quality", "created_at",
)

# Idempotency: the DB's UNIQUE(shortlist_id, stage, capture_session,
# contract_symbol) constraint is the guarantee. INSERT OR IGNORE (not an
# ON CONFLICT ... DO UPDATE) is deliberate: once a stage/session/contract is
# captured, the row must never move — a retry that saw a fresher quote must
# not silently overwrite what an earlier attempt already recorded as STALE or
# MISSING. First write for a given (shortlist_id, stage, capture_session,
# contract_symbol) wins; every re-run after that is a no-op for that row.
_OPT_INSERT_SQL = (
    "INSERT OR IGNORE INTO put_flow_option_snapshots (" + ",".join(_OPT_COLS) + ") "
    "VALUES (" + ",".join("?" for _ in _OPT_COLS) + ")"
)

_BORROW_COLS = (
    "shortlist_id", "ticker", "stage", "capture_session", "captured_at",
    "shortable", "hard_to_borrow", "htb_rate", "rate_units", "stock_px",
    "quote_time", "quote_age_sec", "quote_quality", "created_at",
)

# Same idempotency reasoning as _OPT_INSERT_SQL: UNIQUE(shortlist_id, stage,
# capture_session) on put_flow_borrow_snapshots; first write wins.
_BORROW_INSERT_SQL = (
    "INSERT OR IGNORE INTO put_flow_borrow_snapshots (" + ",".join(_BORROW_COLS) + ") "
    "VALUES (" + ",".join("?" for _ in _BORROW_COLS) + ")"
)


# A dry run must write NOTHING — not the option rows, not the borrow rows, not
# the audit row. Writing the data but skipping the audit row (the earlier
# behaviour) left the table full while the morning proof check reported that
# the collection had never run, which is worse than either extreme.
_DRY_RUN = False


@contextlib.contextmanager
def _dry_run(on: bool):
    """Hold the no-write flag for the duration of one call, and always put it
    back — even when the body raises.

    An earlier version set the flag and cleared it at the end of the function.
    Any exception in between (a bad `stage`, a database error) left it stuck on
    for the rest of the process, so later real captures reported rows they had
    silently not written. A context manager cannot leak that way.
    """
    global _DRY_RUN
    previous = _DRY_RUN
    _DRY_RUN = bool(on)
    try:
        yield
    finally:
        _DRY_RUN = previous


async def _insert_option_row(conn, values: dict) -> None:
    if _DRY_RUN:
        return
    await conn.execute(_OPT_INSERT_SQL, tuple(values.get(c) for c in _OPT_COLS))


async def _insert_borrow_row(conn, values: dict) -> None:
    if _DRY_RUN:
        return
    await conn.execute(_BORROW_INSERT_SQL, tuple(values.get(c) for c in _BORROW_COLS))


# Units of Schwab's `htbRate` are NOT proven — see the module-level note below
# and the report handed back to the lead agent. Never guess "percent".
HTB_RATE_UNITS = "UNKNOWN"


async def _capture_borrow(conn, row: dict, stage: str, capture_session: str,
                          stock_quote: dict, captured_at: float) -> None:
    now = captured_at
    quote_time = stock_quote.get("quote_time") or stock_quote.get("t") or None
    age = (now - quote_time) if quote_time else None
    # Borrow rows have no bid/ask of their own — usability here is just "did
    # Schwab answer at all, and how old was that answer".
    q = "OK" if (quote_time and age is not None and age <= _quote_max_age_sec()) \
        else ("STALE" if quote_time else "MISSING")
    await _insert_borrow_row(conn, {
        "shortlist_id": row["id"], "ticker": row["ticker"], "stage": stage,
        "capture_session": capture_session, "captured_at": now,
        "shortable": None if stock_quote.get("shortable") is None
                     else int(stock_quote["shortable"]),
        "hard_to_borrow": None if stock_quote.get("hard_to_borrow") is None
                          else int(stock_quote["hard_to_borrow"]),
        "htb_rate": stock_quote.get("htb_rate"),
        "rate_units": HTB_RATE_UNITS,
        "stock_px": stock_quote.get("c"),
        "quote_time": quote_time, "quote_age_sec": age,
        "quote_quality": q, "created_at": now,
    })


# --- shared: fetch + bound + cap a fresh PUT slice, and one contract's values ---

def _contract_row_values(c, now: float) -> tuple[dict, str]:
    """The per-contract column values (minus shortlist_id/stage/capture_session/
    captured_at/underlying_px/spy_px/chain_*/created_at, which the caller
    knows) plus the resolved quote_quality."""
    qt_ms = c.get("providerQuoteTime") or 0
    qt_sec = qt_ms / 1000.0 if qt_ms else None
    age = (now - qt_sec) if qt_sec else None
    bid, ask, last = c.get("bid"), c.get("ask"), c.get("lastPrice")
    q = quote_quality(bid, ask, qt_sec, now, _quote_max_age_sec())
    values = {
        "contract_symbol": c.get("contractSymbol"),
        "expiry": c.get("expiry"), "strike": _finite(c.get("strike")),
        "option_type": "PUT",
        "bid": _finite(bid), "ask": _finite(ask), "last": _finite(last),
        "mark": option_mark(bid, ask, c.get("mark")),
        "provider_quote_time": qt_sec, "quote_age_sec": age,
        "volume": _finite(c.get("volume")),
        "open_interest": _finite(c.get("openInterest")),
        "implied_vol": _finite(c.get("impliedVolatility")),
        "delta": _finite(c.get("delta")), "gamma": _finite(c.get("gamma")),
        "theta": _finite(c.get("theta")), "vega": _finite(c.get("vega")),
        "rho": _finite(c.get("rho")),
        "multiplier": _finite(c.get("multiplier")),
        "non_standard": int(bool(c.get("nonStandard"))),
        "deliverable_note": str(c.get("deliverableNote") or "") or None,
        "quote_quality": q,
    }
    return values, q


async def _capture_full_slice(conn, row: dict, stock_px: float, spy_quote: dict,
                              now: float, *, stage: str, capture_session: str) -> dict:
    """Fetch the WHOLE bounded PUT slice for `row` (same expiry/strike window
    rule used by an entry capture) and store every surviving contract tagged
    `stage`/`capture_session`. Never picks a "best" contract. Caps at
    `max_contracts_per_capture`, keeping the strikes nearest `stock_px`."""
    result = {"contracts_captured": 0, "usable": 0, "stale": 0, "no_two_sided": 0,
             "missing": 0, "dropped_over_cap": 0, "error": None}
    from_date, to_date = expiration_window(row)
    low, high = strike_window(stock_px)

    from consensus_engine.scanners import schwab_client
    chain = schwab_client.get_option_chain(
        row["ticker"], contract_type="PUT", from_date=from_date, to_date=to_date)
    if chain is None or chain.puts.empty:
        result["error"] = "Schwab returned no PUT chain in the bounded window"
        return result

    puts = chain.puts
    sliced = puts[(puts["strike"] >= low) & (puts["strike"] <= high)]
    cap = _max_contracts_per_capture()
    if len(sliced) > cap:
        sliced = sliced.assign(
            _dist=(sliced["strike"] - stock_px).abs()
        ).sort_values("_dist").head(cap)
        result["dropped_over_cap"] = int(len(puts[(puts["strike"] >= low) &
                                                    (puts["strike"] <= high)])) - cap

    for _, c in sliced.iterrows():
        values, q = _contract_row_values(c, now)
        await _insert_option_row(conn, {
            "shortlist_id": row["id"], "ticker": row["ticker"], "stage": stage,
            "capture_session": capture_session, "captured_at": now,
            **values,
            "underlying_px": stock_px, "spy_px": spy_quote.get("c"),
            "chain_underlying_px": chain.underlying_price,
            "chain_is_delayed": int(bool(chain.is_delayed)),
            "created_at": now,
        })
        result["contracts_captured"] += 1
        result[{"OK": "usable", "STALE": "stale", "NO_TWO_SIDED": "no_two_sided",
                "MISSING": "missing"}[q]] += 1
    return result


# --- ENTRY --------------------------------------------------------------

async def capture_entry(row: dict, *, stock_quote: dict, spy_quote: dict,
                        now: float | None = None) -> dict:
    """Store the WHOLE bounded PUT slice for `row` at its TODO #96 entry.

    Fail-soft: any Schwab error is caught, logged, and returned in `error` —
    it never raises, so it can never abort the caller's live entry.
    """
    now = _now(now)
    capture_session = row["entry_session"]
    result = {"ticker": row["ticker"], "stage": "ENTRY",
              "capture_session": capture_session, "contracts_captured": 0,
              "usable": 0, "stale": 0, "no_two_sided": 0, "missing": 0,
              "dropped_over_cap": 0, "error": None}
    if not enabled():
        result["error"] = "option_capture disabled"
        return result

    conn = await db.get_db()
    try:
        stock_px = stock_quote.get("c")
        if not stock_px or stock_px <= 0:
            result["error"] = "no usable stock price for the strike window"
            return result
        result.update(await _capture_full_slice(
            conn, row, stock_px, spy_quote, now,
            stage="ENTRY", capture_session=capture_session))
        await _capture_borrow(conn, row, "ENTRY", capture_session, stock_quote, now)
        await conn.commit()
    except Exception as e:  # noqa: BLE001 — this is an observer, never a blocker
        log.warning("put_flow_option_capture ENTRY failed for %s: %s", row.get("ticker"), e)
        result["error"] = str(e)
    return result


# --- MARK / EXIT: re-price the SAME contracts stored at ENTRY ------------
#
# Some open positions (the four TODO #96 trades already live before this
# module existed: AMZN, GOOGL, META, BMNR entered 2026-08-25) will NEVER have
# an ENTRY slice — that gap is permanent, on purpose. For those, the FIRST
# successful MARK capture establishes the tracked contract set instead,
# stored with stage='MARK' (never 'ENTRY' — that would misstate when the
# quote was actually taken). Every later MARK and the EXIT then re-price
# exactly that same set, same as a position with a real ENTRY slice.

async def _tracked_contracts(conn, shortlist_id: int) -> tuple[list[dict], str | None]:
    """The contract set later captures must re-price, and where it came from:
    'ENTRY' (a real entry slice), 'MARK' (established mid-trade, no entry
    quote ever existed), or (None) — nothing tracked yet at all."""
    cur = await conn.execute(
        "SELECT contract_symbol, expiry, strike FROM put_flow_option_snapshots "
        "WHERE shortlist_id=? AND stage='ENTRY'", (shortlist_id,))
    rows = [dict(r) for r in await cur.fetchall()]
    if rows:
        return rows, "ENTRY"
    cur = await conn.execute(
        "SELECT MIN(capture_session) AS s FROM put_flow_option_snapshots "
        "WHERE shortlist_id=? AND stage='MARK'", (shortlist_id,))
    r = await cur.fetchone()
    earliest = r["s"] if r else None
    if not earliest:
        return [], None
    cur = await conn.execute(
        "SELECT contract_symbol, expiry, strike FROM put_flow_option_snapshots "
        "WHERE shortlist_id=? AND stage='MARK' AND capture_session=?",
        (shortlist_id, earliest))
    return [dict(r) for r in await cur.fetchall()], "MARK"


async def _recapture(row: dict, stage: str, capture_session: str, *,
                     stock_quote: dict, spy_quote: dict, now: float) -> dict:
    result = {"ticker": row["ticker"], "stage": stage,
              "capture_session": capture_session, "contracts_captured": 0,
              "usable": 0, "stale": 0, "no_two_sided": 0, "missing": 0,
              "error": None, "entry_source": None, "established_mid_trade": False}
    if not enabled():
        result["error"] = "option_capture disabled"
        return result

    conn = await db.get_db()
    try:
        tracked, source_stage = await _tracked_contracts(conn, row["id"])
        result["entry_source"] = source_stage

        if not tracked:
            # No real ENTRY slice, and no prior MARK has established one
            # either — this call is the first ever for this position.
            # Establish the tracked set now, using the SAME bounded window
            # rule as a real entry capture, but anchored on TODAY's stock
            # price and the position's own planned_exit_session — never on a
            # reconstructed entry price. Always stored as stage='MARK': a
            # position that started tracking mid-trade must never look like
            # it has a real ENTRY quote.
            stock_px = stock_quote.get("c")
            if not stock_px or stock_px <= 0:
                result["error"] = "no usable stock price to establish tracking"
                return result
            result.update(await _capture_full_slice(
                conn, row, stock_px, spy_quote, now,
                stage="MARK", capture_session=capture_session))
            result["entry_source"] = "MARK"
            result["established_mid_trade"] = True
            await _capture_borrow(conn, row, stage, capture_session, stock_quote, now)
            await conn.commit()
            return result

        expiries = sorted({c["expiry"] for c in tracked if c["expiry"]})
        by_symbol: dict[str, dict] = {}
        chain_underlying_px = None
        chain_is_delayed = None
        if expiries:
            from consensus_engine.scanners import schwab_client
            # A Schwab error here is a TECHNICAL failure, not evidence the
            # contract is gone — it must not turn into a MISSING row. Let it
            # propagate to the outer except, which skips this ticker entirely
            # (no option rows, no borrow row) and records the error, same as
            # capture_entry.
            chain = schwab_client.get_option_chain(
                row["ticker"], contract_type="PUT",
                from_date=expiries[0], to_date=expiries[-1])
            if chain is not None and not chain.puts.empty:
                chain_underlying_px = chain.underlying_price
                chain_is_delayed = int(bool(chain.is_delayed))
                for _, c in chain.puts.iterrows():
                    by_symbol[c.get("contractSymbol")] = c

        for stored in tracked:
            sym = stored["contract_symbol"]
            c = by_symbol.get(sym)
            if c is None:
                q = "MISSING"
                bid = ask = last = mark = qt_sec = age = None
                volume = open_interest = implied_vol = None
                delta = gamma = theta = vega = rho = multiplier = None
                non_standard = None
                deliverable_note = None
            else:
                qt_ms = c.get("providerQuoteTime") or 0
                qt_sec = qt_ms / 1000.0 if qt_ms else None
                age = (now - qt_sec) if qt_sec else None
                bid, ask, last = c.get("bid"), c.get("ask"), c.get("lastPrice")
                mark = option_mark(bid, ask, c.get("mark"))
                q = quote_quality(bid, ask, qt_sec, now, _quote_max_age_sec())
                volume, open_interest = c.get("volume"), c.get("openInterest")
                implied_vol = c.get("impliedVolatility")
                delta, gamma, theta = c.get("delta"), c.get("gamma"), c.get("theta")
                vega, rho, multiplier = c.get("vega"), c.get("rho"), c.get("multiplier")
                non_standard = int(bool(c.get("nonStandard")))
                deliverable_note = str(c.get("deliverableNote") or "") or None

            await _insert_option_row(conn, {
                "shortlist_id": row["id"], "ticker": row["ticker"],
                "stage": stage, "capture_session": capture_session,
                "captured_at": now, "contract_symbol": sym,
                "expiry": stored["expiry"], "strike": stored["strike"],
                "option_type": "PUT",
                "bid": _finite(bid), "ask": _finite(ask), "last": _finite(last),
                "mark": mark, "provider_quote_time": qt_sec, "quote_age_sec": age,
                "volume": _finite(volume), "open_interest": _finite(open_interest),
                "implied_vol": _finite(implied_vol),
                "delta": _finite(delta), "gamma": _finite(gamma),
                "theta": _finite(theta), "vega": _finite(vega), "rho": _finite(rho),
                "multiplier": _finite(multiplier), "non_standard": non_standard,
                "deliverable_note": deliverable_note,
                "underlying_px": stock_quote.get("c"), "spy_px": spy_quote.get("c"),
                "chain_underlying_px": chain_underlying_px,
                "chain_is_delayed": chain_is_delayed,
                "quote_quality": q, "created_at": now,
            })
            result["contracts_captured"] += 1
            result[{"OK": "usable", "STALE": "stale",
                    "NO_TWO_SIDED": "no_two_sided", "MISSING": "missing"}[q]] += 1

        await _capture_borrow(conn, row, stage, capture_session, stock_quote, now)
        await conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("put_flow_option_capture %s failed for %s: %s",
                    stage, row.get("ticker"), e)
        result["error"] = result["error"] or str(e)
    return result


async def capture_mark(row: dict, *, stock_quote: dict, spy_quote: dict,
                       now: float | None = None) -> dict:
    """Re-price the contracts stored at ENTRY, at a 6:35 a.m. Pacific mark
    while the pair is still open. Adds no new contract."""
    now = _now(now)
    return await _recapture(row, "MARK", pacific_session(now),
                            stock_quote=stock_quote, spy_quote=spy_quote, now=now)


async def capture_exit(row: dict, *, stock_quote: dict, spy_quote: dict,
                       now: float | None = None) -> dict:
    """Re-price the contracts stored at ENTRY, at the pair's exit. Adds no
    new contract. Uses `row["planned_exit_session"]` as the capture session
    (not `now`'s date) so it matches the trade's own exit session exactly."""
    now = _now(now)
    return await _recapture(row, "EXIT", row["planned_exit_session"],
                            stock_quote=stock_quote, spy_quote=spy_quote, now=now)


# --- standalone daily runner: capture every currently-open position -------

async def capture_open_positions(session: str | None = None, stage: str = "MARK",
                                 dry_run: bool = False) -> dict:
    """The scheduled entrypoint: find every TODO #96 position that is open
    on `session` for `stage`, fetch fresh Schwab quotes for the whole batch,
    and capture each. Writes one `put_flow_capture_runs` audit row.

    Row selection by stage:
      MARK  — status='ENTERED', entered before `session`, not yet due to exit
              on `session` (the middle of the hold).
      EXIT  — status='ENTERED', `planned_exit_session` == `session`. Provided
              for standalone verification; the live job should prefer calling
              `capture_exit()` inline with the exact quote used for the fill.
      ENTRY — status='ENTERED', `entry_session` == `session`. Idempotent with
              an inline `capture_entry()` call, since INSERT OR IGNORE makes a
              repeat a no-op.

    Fail-soft per ticker: one Schwab error is recorded in the run row's
    `errors_json` and skips that ticker; it never aborts the batch.
    """
    with _dry_run(dry_run):
        return await _capture_open_positions(session, stage, dry_run)


async def _capture_open_positions(session: str | None, stage: str,
                                  dry_run: bool) -> dict:
    now = time.time()
    session = session or pacific_session(now)
    started_at = now
    errors: dict[str, str] = {}

    conn = await db.get_db()
    if stage == "MARK":
        cur = await conn.execute(
            "SELECT * FROM put_flow_shortlist WHERE status='ENTERED' "
            "AND entry_session < ? AND planned_exit_session > ? ORDER BY id",
            (session, session))
    elif stage == "EXIT":
        cur = await conn.execute(
            "SELECT * FROM put_flow_shortlist WHERE status='ENTERED' "
            "AND planned_exit_session = ? ORDER BY id", (session,))
    elif stage == "ENTRY":
        cur = await conn.execute(
            "SELECT * FROM put_flow_shortlist WHERE status='ENTERED' "
            "AND entry_session = ? ORDER BY id", (session,))
    else:
        raise ValueError(f"unknown stage {stage!r}")
    rows = [dict(r) for r in await cur.fetchall()]

    # `put_flow_capture_runs` (db.py) has only stale_quotes/missing_quotes
    # columns — no separate no-two-sided column — so the DB row's
    # `stale_quotes` is deliberately STALE + NO_TWO_SIDED combined. The finer
    # breakdown is never lost: `no_two_sided_quotes` below is carried on the
    # RETURNED dict only (not written to the db row), and report() always
    # keeps STALE and NO_TWO_SIDED as two separate counts, read straight from
    # put_flow_option_snapshots rather than from this audit row.
    run = {"capture_session": session, "stage": stage, "started_at": started_at,
          "finished_at": None, "positions_expected": len(rows),
          "positions_captured": 0, "contracts_captured": 0, "usable_quotes": 0,
          "stale_quotes": 0, "no_two_sided_quotes": 0, "missing_quotes": 0,
          "borrow_rows": 0}

    if not rows:
        run["finished_at"] = time.time()
        if not dry_run:
            await _write_run_row(conn, run, errors)
        return {**run, "errors": errors, "dry_run": dry_run,
                "reason": "no open positions for this stage"}

    from consensus_engine.scanners import schwab_client
    symbols = sorted({r["ticker"] for r in rows} | {"SPY"})
    try:
        quotes = schwab_client.get_quotes(symbols)
    except Exception as e:  # noqa: BLE001
        errors["__batch__"] = f"Schwab quote batch failed: {e}"
        quotes = {}
    spy_q = quotes.get("SPY") or {}

    for r in rows:
        stock_q = quotes.get(r["ticker"])
        if not stock_q:
            errors[r["ticker"]] = "no Schwab quote for the stock"
            continue
        try:
            if stage == "ENTRY":
                out = await capture_entry(r, stock_quote=stock_q, spy_quote=spy_q, now=now)
            elif stage == "MARK":
                out = await capture_mark(r, stock_quote=stock_q, spy_quote=spy_q, now=now)
            else:
                out = await capture_exit(r, stock_quote=stock_q, spy_quote=spy_q, now=now)
        except Exception as e:  # noqa: BLE001 — never abort the batch
            errors[r["ticker"]] = str(e)
            continue
        if out.get("error"):
            errors[r["ticker"]] = out["error"]
        if out.get("contracts_captured"):
            run["positions_captured"] += 1
        run["contracts_captured"] += out.get("contracts_captured", 0)
        run["usable_quotes"] += out.get("usable", 0)
        run["no_two_sided_quotes"] += out.get("no_two_sided", 0)
        # DB column combines the two (see the comment above `run = {...}`).
        run["stale_quotes"] += out.get("stale", 0) + out.get("no_two_sided", 0)
        run["missing_quotes"] += out.get("missing", 0)
        run["borrow_rows"] += 1

    run["finished_at"] = time.time()
    if not dry_run:
        await _write_run_row(conn, run, errors)
    return {**run, "errors": errors, "dry_run": dry_run}


async def _write_run_row(conn, run: dict, errors: dict) -> None:
    # put_flow_capture_runs' UNIQUE(capture_session, stage) is meant to be
    # UPDATEd on a repeated run for the same session/stage (per the table's
    # own comment in db.py), not accumulated as a second audit row.
    await conn.execute(
        """INSERT INTO put_flow_capture_runs
           (capture_session, stage, started_at, finished_at, positions_expected,
            positions_captured, contracts_captured, usable_quotes, stale_quotes,
            missing_quotes, borrow_rows, errors_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(capture_session, stage) DO UPDATE SET
             started_at=excluded.started_at, finished_at=excluded.finished_at,
             positions_expected=excluded.positions_expected,
             positions_captured=excluded.positions_captured,
             contracts_captured=excluded.contracts_captured,
             usable_quotes=excluded.usable_quotes,
             stale_quotes=excluded.stale_quotes,
             missing_quotes=excluded.missing_quotes,
             borrow_rows=excluded.borrow_rows,
             errors_json=excluded.errors_json""",
        (run["capture_session"], run["stage"], run["started_at"], run["finished_at"],
         run["positions_expected"], run["positions_captured"], run["contracts_captured"],
         run["usable_quotes"], run["stale_quotes"], run["missing_quotes"],
         run["borrow_rows"], json.dumps(errors) if errors else None))
    await conn.commit()


# --- the P&L rule (encoded, not evaluated) --------------------------------

def option_leg_pnl(entry_row: dict, exit_row: dict) -> dict:
    """Price a possible LONG option at the entry ASK and the exit BID — the
    honest, cost-bearing direction for someone who bought the option and sold
    it back. Returns status UNKNOWN (no number) whenever either side is not
    OK. This function prices ONE already-identified contract's round trip; it
    does NOT choose a contract, run an evaluator, or claim a strategy works —
    that is explicitly out of scope until a frozen evaluator exists.

    The entry side MUST be a real `stage='ENTRY'` row. A position whose
    tracking was established mid-trade (see `_recapture`) has its earliest
    price stored as `stage='MARK'` — that is a real market price, but it is
    NOT the price the trade actually entered at (no such quote exists), so it
    can never stand in for an entry ask.
    """
    if not entry_row or not exit_row:
        return {"status": "UNKNOWN", "reason": "missing entry or exit snapshot"}
    if (entry_row.get("stage") or "").upper() != "ENTRY":
        return {"status": "UNKNOWN", "reason": "no entry quote for this position"}
    if entry_row.get("quote_quality") != "OK":
        return {"status": "UNKNOWN",
                "reason": f"entry quote_quality is {entry_row.get('quote_quality')}, not OK"}
    if exit_row.get("quote_quality") != "OK":
        return {"status": "UNKNOWN",
                "reason": f"exit quote_quality is {exit_row.get('quote_quality')}, not OK"}
    entry_ask = _finite(entry_row.get("ask"))
    exit_bid = _finite(exit_row.get("bid"))
    if entry_ask is None or entry_ask <= 0 or exit_bid is None:
        return {"status": "UNKNOWN", "reason": "entry ask or exit bid unusable"}
    return {
        "status": "OK",
        "entry_ask": entry_ask, "exit_bid": exit_bid,
        "pnl_per_contract": exit_bid - entry_ask,
        "pnl_pct": 100.0 * (exit_bid - entry_ask) / entry_ask,
    }


# --- the deterministic report ---------------------------------------------

async def report(session: str | None = None) -> dict:
    """Counts, by capture stage and quote quality — the honest status of what
    has actually been collected. `session` filters to one Pacific date;
    omit it for an all-time summary."""
    conn = await db.get_db()
    where = " WHERE capture_session=?" if session else ""
    args = (session,) if session else ()

    cur = await conn.execute(
        f"SELECT stage, quote_quality, COUNT(*) AS n, "
        f"COUNT(DISTINCT shortlist_id) AS positions "
        f"FROM put_flow_option_snapshots{where} GROUP BY stage, quote_quality", args)
    opt_rows = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        f"SELECT stage, quote_quality, rate_units, COUNT(*) AS n "
        f"FROM put_flow_borrow_snapshots{where} "
        f"GROUP BY stage, quote_quality, rate_units", args)
    borrow_rows = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        f"SELECT stage, SUM(positions_expected) AS expected, "
        f"SUM(positions_captured) AS captured FROM put_flow_capture_runs{where} "
        f"GROUP BY stage", args)
    run_rows = [dict(r) for r in await cur.fetchall()]

    # Which positions have a real ENTRY quote versus which started tracking
    # mid-trade (no entry quote will ever exist for them). This is a
    # structural property of the position, not of one session, so it is
    # NOT filtered by `session` — filtering it would hide the classification
    # on every single-day report.
    cur = await conn.execute(
        "SELECT COUNT(DISTINCT shortlist_id) AS n FROM put_flow_option_snapshots "
        "WHERE stage='ENTRY'")
    with_real_entry = (await cur.fetchone())["n"] or 0
    cur = await conn.execute(
        "SELECT COUNT(DISTINCT shortlist_id) AS n FROM put_flow_option_snapshots "
        "WHERE stage='MARK' AND shortlist_id NOT IN "
        "(SELECT shortlist_id FROM put_flow_option_snapshots WHERE stage='ENTRY')")
    mid_trade_no_entry = (await cur.fetchone())["n"] or 0

    by_stage: dict[str, dict] = {s: {"positions_expected": 0, "positions_captured": 0,
                                     "contracts": {q: 0 for q in QUALITIES}}
                                 for s in STAGES}
    for r in run_rows:
        if r["stage"] in by_stage:
            by_stage[r["stage"]]["positions_expected"] = r["expected"] or 0
            by_stage[r["stage"]]["positions_captured"] = r["captured"] or 0
    for r in opt_rows:
        if r["stage"] in by_stage and r["quote_quality"] in QUALITIES:
            by_stage[r["stage"]]["contracts"][r["quote_quality"]] = r["n"]

    # The audit row is the normal source for the position counts, but it can be
    # absent — an older row written before the audit table existed, or a run
    # that died between storing rows and writing its summary. Counting the real
    # stored rows then is honest; printing "0 of 0 positions captured" next to
    # 586 stored contracts is not.
    cur = await conn.execute(
        f"SELECT stage, COUNT(DISTINCT shortlist_id) AS positions "
        f"FROM put_flow_option_snapshots{where} GROUP BY stage", args)
    for r in await cur.fetchall():
        st = r["stage"]
        if st not in by_stage:
            continue
        real = r["positions"] or 0
        by_stage[st]["positions_captured"] = max(by_stage[st]["positions_captured"], real)
        by_stage[st]["positions_expected"] = max(by_stage[st]["positions_expected"], real)

    borrow_summary = {"rows": borrow_rows,
                      "rate_units_seen": sorted({r["rate_units"] for r in borrow_rows})}

    out = {
        "session": session,
        "by_stage": by_stage,
        "borrow": borrow_summary,
        "entry_source_summary": {
            "with_real_entry": with_real_entry,
            "mid_trade_no_entry": mid_trade_no_entry,
        },
        "option_pnl_status": "UNKNOWN",
        "option_pnl_reason": ("no frozen evaluator and no complete entry/exit "
                              "quote pair yet"),
    }
    out["text"] = _render_report_text(out)
    return out


def _render_report_text(out: dict) -> str:
    scope = f"for {out['session']}" if out["session"] else "across all sessions"
    lines = [f"Option and borrow data collected {scope}, by stage:"]
    any_rows = False
    for stage in STAGES:
        s = out["by_stage"][stage]
        total = sum(s["contracts"].values())
        if s["positions_expected"] == 0 and total == 0:
            continue
        any_rows = True
        lines.append(
            f"- {stage}: {s['positions_captured']} of {s['positions_expected']} "
            f"positions captured, {total} option contracts stored "
            f"({s['contracts']['OK']} usable bid/ask, {s['contracts']['STALE']} stale, "
            f"{s['contracts']['NO_TWO_SIDED']} no two-sided price, "
            f"{s['contracts']['MISSING']} not quoted at all).")
    if not any_rows:
        lines.append("- Nothing captured yet.")
    es = out["entry_source_summary"]
    lines.append(
        f"Of the positions tracked so far: {es['with_real_entry']} have a real "
        f"entry quote (captured at the actual 6:35 a.m. Pacific entry), and "
        f"{es['mid_trade_no_entry']} are tracking started mid-trade — no entry "
        f"quote exists for those, so option profit for them can never be "
        f"measured.")
    borrow_rows = out["borrow"]["rows"]
    if borrow_rows:
        n_rows = sum(r["n"] for r in borrow_rows)
        units = out["borrow"]["rate_units_seen"]
        units_txt = ", ".join(units) if units else "none seen"
        lines.append(f"Borrow (short-availability) data: {n_rows} rows saved. "
                     f"Rate units on file: {units_txt}.")
        if units == ["UNKNOWN"]:
            lines.append("The units of Schwab's hard-to-borrow rate are not proven, "
                         "so no dollar borrow cost is calculated from it yet — "
                         "only the raw rate is stored.")
    else:
        lines.append("Borrow (short-availability) data: none saved yet.")
    lines.append(f"Option profit (buying a put or a put spread): {out['option_pnl_status']} "
                f"— {out['option_pnl_reason']}.")
    return "\n".join(lines)
