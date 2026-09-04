"""TODO #111 tournament — the shared midpoint-fill engine.

Every one of the 58 frozen tests (`.omc/research/todo-111-tournament/FROZEN-MATRIX.md`)
is built out of the functions in this file: read a whole-chain snapshot, pick
an expiry, find the strike reference, build a structure's legs, read a
minute-quote file, and walk it with the midpoint-fill exit engine. No side
effects on import — every function is pure given its file paths.

Fill convention (frozen 0.6): every buy and every sell, entry and exit, fills
at the midpoint of the bid and ask. This is the ONE convention this whole
library uses; it is not the bid/ask convention in `todo_111_condor_backtest.py`
(that script predates the owner's midpoint rule).

`value()` is signed as what a BUYER of the structure pays: a short (sold) leg
has qty -1, a long (bought) leg has qty +1, and `value = sum(qty * mid(leg))`.
A credit structure therefore has a negative value; the credit collected is
`-value`. This one convention is what lets `run_trade` compute profit the
same way for credit, debit, and net structures: dollar profit per contract is
always `100 * (exit_value - entry_value)`, regardless of which side the
trader is on (see `run_trade`'s docstring for the algebra).
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict, namedtuple
from datetime import date, datetime
from zoneinfo import ZoneInfo

import databento as db

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = (9, 30), (16, 0)
WING = 5.0                       # every credit-spread wing is $5 (frozen 0.4)
MAX_SPREAD_FRACTION = 0.25       # frozen 0.5 liquidity gate
COMMISSION_PER_CONTRACT_SIDE = 0.45

# A single leg's quote: bid/ask/size at one minute, plus its raw OSI symbol.
Quote = namedtuple("Quote", "bid ask bid_size ask_size symbol")

# Mirrors parse_osi() in todo_111_condor_pull.py — same OSI raw-symbol shape,
# duplicated here (not imported) so this file has no import-time dependency
# on the pull script.
_OSI = re.compile(r"^(?P<root>.{6})(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})"
                   r"(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_osi(sym: str):
    """raw OSI symbol -> (expiration_iso, 'C'|'P', strike) or None."""
    m = _OSI.match(sym)
    if not m:
        return None
    return (f"20{m['y']}-{m['m']}-{m['d']}", m["cp"], int(m["strike"]) / 1000.0)


def osi(root: str, exp: str, cp: str, strike: float) -> str:
    """Build the raw OSI symbol exactly as todo_111_condor_pull.py does."""
    y, m, d = exp.split("-")
    return f"{root}{y[2:]}{m}{d}{cp}{int(round(strike * 1000)):08d}"


def chain_root(chain_or_quotes, exp: str):
    """Recover the 6-character OSI root for expiry `exp`.

    Accepts either a full chain (as returned by load_chain: expiration ->
    strike -> 'C'/'P' -> Quote) or a flat {raw_symbol: Quote-or-tuple}
    snapshot (as todo_111_condor_pull.snapshot_quotes returns).
    """
    strikes = chain_or_quotes.get(exp) if isinstance(chain_or_quotes, dict) else None
    if isinstance(strikes, dict):
        for cps in strikes.values():
            for q in cps.values():
                sym = q.symbol if isinstance(q, Quote) else q[-1]
                return sym[:6]
        return None
    for sym in chain_or_quotes:
        p = parse_osi(sym)
        if p and p[0] == exp:
            return sym[:6]
    return None


# ---------------------------------------------------------------- chain I/O

def load_chain(path: str) -> dict:
    """Read a chain_YYYY-MM-DD.dbn.zst whole-chain snapshot.

    Keeps only the FIRST timestamp in the file (every snapshot download is a
    single minute already, but this is the frozen safeguard). Drops any
    contract with ask <= 0; a 0.00 bid is a real quote and is kept.

    Returns {expiration: {strike: {"C": Quote, "P": Quote}}}. No day-window
    filtering happens here — that is pick_expiry's job.
    """
    df = db.DBNStore.from_file(path).to_df()
    if df.empty:
        return {}
    first = df.index.min()
    df = df[df.index == first]
    chain: dict = {}
    for sym, b, a, bs, asz in zip(df["symbol"], df["bid_px_00"], df["ask_px_00"],
                                   df["bid_sz_00"], df["ask_sz_00"]):
        a = float(a)
        if a <= 0:
            continue
        p = parse_osi(sym)
        if not p:
            continue
        exp, cp, k = p
        chain.setdefault(exp, {}).setdefault(k, {})[cp] = \
            Quote(float(b), a, int(bs), int(asz), sym)
    return chain


def pick_expiry(chain: dict, entry_day: str, dte_lo: int, dte_hi: int,
                 dte_target: int):
    """Same rule as choose_legs() in todo_111_condor_pull.py: among expiries
    whose CALENDAR-day distance from entry_day is in [dte_lo, dte_hi], pick
    the one with the most listed strikes; ties go to the expiry closest to
    dte_target."""
    ed = date.fromisoformat(entry_day)
    candidates = {e: s for e, s in chain.items()
                  if dte_lo <= (date.fromisoformat(e) - ed).days <= dte_hi}
    if not candidates:
        return None
    return max(candidates, key=lambda e: (
        len(candidates[e]),
        -abs((date.fromisoformat(e) - ed).days - dte_target)))


def mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def reference(chain: dict, exp: str):
    """Spot (put-call parity), ATM strike, and expected move for expiry exp.

    Returns None if no strike on this expiry has both a call and a put quote
    — parity spot cannot be computed.
    """
    strikes = chain.get(exp, {})
    both = {k: v for k, v in strikes.items() if "C" in v and "P" in v}
    if not both:
        return None
    m = lambda q: mid(q.bid, q.ask)
    k_par = min(both, key=lambda k: abs(m(both[k]["C"]) - m(both[k]["P"])))
    spot = k_par + m(both[k_par]["C"]) - m(both[k_par]["P"])
    k_atm = min(both, key=lambda k: abs(k - spot))
    em = m(both[k_atm]["C"]) + m(both[k_atm]["P"])
    return {"spot": spot, "atm_strike": k_atm, "expected_move": em}


def boundary_strike(chain: dict, exp: str, ref: dict, m: float, side: str):
    """side='put': highest listed put strike at or below spot - m*EM.
    side='call': lowest listed call strike at or above spot + m*EM.
    None if no listed strike qualifies."""
    strikes = chain.get(exp, {})
    spot, em = ref["spot"], ref["expected_move"]
    if side == "put":
        target = spot - m * em
        below = [k for k in strikes if k <= target and "P" in strikes[k]]
        return max(below) if below else None
    if side == "call":
        target = spot + m * em
        above = [k for k in strikes if k >= target and "C" in strikes[k]]
        return min(above) if above else None
    raise ValueError(f"side must be 'put' or 'call', got {side!r}")


# ------------------------------------------------------------ structures

_PAREN = re.compile(r"^([A-Z_]+)\(([^)]+)\)$")


def build_structure(chain: dict, exp: str, ref: dict, spec: str):
    """Build the legs for one structure code (frozen matrix 0.11).

    Returns a dict {code, expiration, legs, width, kind, max_risk_rule} or a
    string explaining why the structure cannot be built on this chain/expiry
    (a required strike is not listed).

    legs: list of {symbol, strike, cp, qty, role}. qty is +1 for a bought
    leg, -1 for a sold leg.
    width: the $5 wing width for PCS/CCS/IC, else None (CDS/PDS/STRANG use a
    boundary-to-ATM width that is not fixed at $5).
    kind: 'credit' | 'debit' | 'net'.
    """
    strikes = chain.get(exp, {})
    root = chain_root(chain, exp)
    atm = ref["atm_strike"]

    def has(k, cp):
        return k in strikes and cp in strikes[k]

    def leg(k, cp, qty, role):
        return {"symbol": osi(root, exp, cp, k), "strike": k, "cp": cp,
                "qty": qty, "role": role}

    def pcs(m):
        sp = boundary_strike(chain, exp, ref, m, "put")
        if sp is None:
            return f"PCS({m}): put boundary strike not listed"
        lp = sp - WING
        if not has(lp, "P"):
            return f"PCS({m}): long put {lp} not listed"
        return [leg(sp, "P", -1, "short_put"), leg(lp, "P", +1, "long_put")]

    def ccs(m):
        sc = boundary_strike(chain, exp, ref, m, "call")
        if sc is None:
            return f"CCS({m}): call boundary strike not listed"
        lc = sc + WING
        if not has(lc, "C"):
            return f"CCS({m}): long call {lc} not listed"
        return [leg(sc, "C", -1, "short_call"), leg(lc, "C", +1, "long_call")]

    def cds():
        if not has(atm, "C"):
            return "CDS: ATM call not listed"
        sc = boundary_strike(chain, exp, ref, 0.6, "call")
        if sc is None:
            return "CDS: call boundary(0.6) not listed"
        return [leg(atm, "C", +1, "long_call"), leg(sc, "C", -1, "short_call")]

    def pds():
        if not has(atm, "P"):
            return "PDS: ATM put not listed"
        sp = boundary_strike(chain, exp, ref, 0.6, "put")
        if sp is None:
            return "PDS: put boundary(0.6) not listed"
        return [leg(atm, "P", +1, "long_put"), leg(sp, "P", -1, "short_put")]

    def wrap(legs, width, kind, rule):
        return {"code": spec, "expiration": exp, "legs": legs, "width": width,
                "kind": kind, "max_risk_rule": rule}

    if spec == "STRAD":
        if not (has(atm, "C") and has(atm, "P")):
            return "STRAD: ATM strike missing a call or a put"
        legs = [leg(atm, "C", +1, "long_call"), leg(atm, "P", +1, "long_put")]
        return wrap(legs, None, "debit", "debit paid")

    if spec == "CDS":
        legs = cds()
        if isinstance(legs, str):
            return legs
        return wrap(legs, None, "debit", "debit paid")

    if spec == "PDS":
        legs = pds()
        if isinstance(legs, str):
            return legs
        return wrap(legs, None, "debit", "debit paid")

    if spec == "RR+":
        put_legs = pcs(1.0)
        if isinstance(put_legs, str):
            return f"RR+: {put_legs}"
        call_legs = cds()
        if isinstance(call_legs, str):
            return f"RR+: {call_legs}"
        return wrap(put_legs + call_legs, None, "net",
                    "worst expiry value is the PCS(1.0) wing's -$5 "
                    "(the CDS leg's payoff is always >= 0); "
                    "max_risk = entry_cash_flow + 5.0")

    if spec == "RR-":
        call_legs = ccs(1.0)
        if isinstance(call_legs, str):
            return f"RR-: {call_legs}"
        put_legs = pds()
        if isinstance(put_legs, str):
            return f"RR-: {put_legs}"
        return wrap(call_legs + put_legs, None, "net",
                    "worst expiry value is the CCS(1.0) wing's -$5 "
                    "(the PDS leg's payoff is always >= 0); "
                    "max_risk = entry_cash_flow + 5.0")

    m = _PAREN.match(spec)
    if not m:
        raise ValueError(f"unknown structure code {spec!r}")
    head, arg = m.group(1), m.group(2)

    if head == "PCS":
        legs = pcs(float(arg))
        if isinstance(legs, str):
            return legs
        return wrap(legs, WING, "credit", "width - credit")

    if head == "CCS":
        legs = ccs(float(arg))
        if isinstance(legs, str):
            return legs
        return wrap(legs, WING, "credit", "width - credit")

    if head == "IC":
        put_legs = pcs(float(arg))
        if isinstance(put_legs, str):
            return f"IC({arg}): {put_legs}"
        call_legs = ccs(float(arg))
        if isinstance(call_legs, str):
            return f"IC({arg}): {call_legs}"
        return wrap(put_legs + call_legs, WING, "credit",
                    "width - credit (equal $5 wings, only one side can "
                    "finish in the money)")

    if head == "STRANG":
        mv = float(arg)
        sc = boundary_strike(chain, exp, ref, mv, "call")
        sp = boundary_strike(chain, exp, ref, mv, "put")
        if sc is None or sp is None:
            return f"STRANG({mv}): boundary strike not listed"
        legs = [leg(sc, "C", +1, "long_call"), leg(sp, "P", +1, "long_put")]
        return wrap(legs, None, "debit", "debit paid")

    if head == "LONG_PUT":
        if arg == "atm":
            if not has(atm, "P"):
                return "LONG_PUT(atm): ATM put not listed"
            legs = [leg(atm, "P", +1, "long_put")]
        else:
            mv = float(arg)
            k = boundary_strike(chain, exp, ref, mv, "put")
            if k is None:
                return f"LONG_PUT({mv}): put boundary strike not listed"
            legs = [leg(k, "P", +1, "long_put")]
        return wrap(legs, None, "debit", "debit paid")

    raise ValueError(f"unknown structure code {spec!r}")


# --------------------------------------------------------------- minutes

def load_minutes(path: str, symbols) -> dict:
    """{exchange_local_datetime: {symbol: (bid, ask, bid_size, ask_size)}}
    for the regular session (09:30-16:00 America/New_York inclusive), for
    just the given symbols. Records with ask <= 0 are dropped."""
    df = db.DBNStore.from_file(path).to_df()
    want = set(symbols)
    book = defaultdict(dict)
    for ts, sym, b, a, bs, asz in zip(df.index, df["symbol"], df["bid_px_00"],
                                       df["ask_px_00"], df["bid_sz_00"], df["ask_sz_00"]):
        a = float(a)
        if sym not in want or a <= 0:
            continue
        local = ts.astimezone(NY)
        t = (local.hour, local.minute)
        if OPEN <= t <= CLOSE:
            book[local][sym] = (float(b), a, int(bs), int(asz))
    return dict(book)


# ----------------------------------------------------------- the engine

def entry_gate(book_minute: dict, structure: dict):
    """Frozen liquidity gate (0.5) on every leg. None on pass, else the
    reason string for the first leg that fails."""
    for l in structure["legs"]:
        q = book_minute.get(l["symbol"])
        if q is None:
            return f"{l['symbol']} unquoted at entry"
        b, a, bs, asz = q
        if not (b > 0 and a > 0 and bs >= 1 and asz >= 1):
            return f"{l['symbol']} fails the bid/ask/size gate ({q})"
        m = mid(b, a)
        if m <= 0 or (a - b) / m > MAX_SPREAD_FRACTION:
            return f"{l['symbol']} spread too wide ((ask-bid)/mid > 0.25)"
    return None


def value(book_minute: dict, structure: dict):
    """Midpoint value of the position as what a BUYER pays:
    sum(qty * mid(leg)). None if any leg is unquoted in this minute."""
    total = 0.0
    for l in structure["legs"]:
        q = book_minute.get(l["symbol"])
        if q is None:
            return None
        b, a = q[0], q[1]
        total += l["qty"] * mid(b, a)
    return total


def max_risk(structure: dict, entry_cash: float) -> float:
    """entry_cash is value(entry) — the signed midpoint value at entry
    (negative for a credit structure, positive for a debit one).

    - credit (PCS/CCS/IC): width - credit. IC's two wings are both $5, but
      only one side can finish in the money, so the risk is one wing's
      width, same formula as a single spread.
    - debit (STRAD/STRANG/CDS/PDS/LONG_PUT): the debit paid.
    - net (RR+/RR-): the worst possible combined value at expiry is the
      credit-spread leg-pair's max loss, -$5 (its accompanying debit
      leg-pair's payoff is always >= 0 at expiry), so
      max_risk = entry_cash - (-5) = entry_cash + 5.0.
    """
    kind = structure["kind"]
    if kind == "credit":
        credit = -entry_cash
        return structure["width"] - credit
    if kind == "debit":
        return entry_cash
    return entry_cash + WING


def commission(structure: dict, contracts: int = 1) -> float:
    return COMMISSION_PER_CONTRACT_SIDE * len(structure["legs"]) * 2 * contracts


def run_trade(minutes: dict, structure: dict, entry_day: str, exit_rule: dict,
              last_trading_day: str) -> dict:
    """Walk one trade with the midpoint-fill engine.

    exit_rule: {"target": float|None, "stop": float|None}, a fraction of the
    entry credit (credit structures), entry debit (debit structures), or
    max_risk (net structures) — see the return-formula notes below.
    last_trading_day: ISO date, the cap day supplied by the caller (already
    computed as entry_day + 14 trading days, or 7 for the short-cap exit
    sets). Inclusive.

    Returns {"skipped": reason} if the entry minute is incomplete or fails
    the liquidity gate, or {"skipped": "no complete minute after entry
    within cap"} if no later minute has every leg quoted before the cap.

    Otherwise returns a full trade row: entry_ts, exit_ts, exit_reason
    ("target touched" / "stop touched" / "time cap"), entry_value,
    exit_value, credit_or_debit, ret, max_risk, session_minutes,
    complete_minutes, entry_spread_pct, entry_bid_size, entry_ask_size,
    n_legs, gap_through_stop.

    Return formula:
      credit structures: R = (C - X) / C, X = -value(minute) (cost to close).
      debit structures:  R = (V - D) / D, V = value(minute).
      net structures:    R = (value(minute) - value(entry)) / max_risk.
    In every case dollar profit per contract is 100*(exit_value - entry_value)
    — see this module's docstring for why that one formula covers all three.
    """
    stamps = sorted(minutes)
    entry = next((t for t in stamps if str(t.date()) == entry_day
                  and t.hour == 10 and t.minute == 0), None)
    if entry is None:
        return {"skipped": "entry minute incomplete"}
    book_entry = minutes[entry]
    if len(book_entry) < len(structure["legs"]) or \
       not all(l["symbol"] in book_entry for l in structure["legs"]):
        return {"skipped": "entry minute incomplete"}
    reason = entry_gate(book_entry, structure)
    if reason:
        return {"skipped": reason}

    entry_val = value(book_entry, structure)
    kind = structure["kind"]
    if kind == "credit" and -entry_val <= 0:
        return {"skipped": "credit is zero or negative"}
    if kind == "debit" and entry_val <= 0:
        return {"skipped": "debit is zero or negative"}

    mr = max_risk(structure, entry_val)
    credit_or_debit = -entry_val if kind == "credit" else \
        (entry_val if kind == "debit" else entry_val)

    cutoff = date.fromisoformat(last_trading_day)
    complete = [t for t in stamps if t > entry and t.date() <= cutoff
                and all(l["symbol"] in minutes[t] for l in structure["legs"])]

    def ret_at(t):
        v = value(minutes[t], structure)
        if kind == "credit":
            return (credit_or_debit - (-v)) / credit_or_debit, v
        if kind == "debit":
            return (v - credit_or_debit) / credit_or_debit, v
        return (v - entry_val) / mr, v

    target, stop = exit_rule.get("target"), exit_rule.get("stop")
    exit_ts = exit_reason = ret = exit_val = None
    for t in complete:
        r, v = ret_at(t)
        if target is not None and r >= target:
            exit_ts, exit_reason, ret, exit_val = t, "target touched", r, v
            break
        if stop is not None and r <= stop:
            exit_ts, exit_reason, ret, exit_val = t, "stop touched", r, v
            break
    else:
        if complete:
            t = complete[-1]
            r, v = ret_at(t)
            exit_ts, exit_reason, ret, exit_val = t, "time cap", r, v
        else:
            return {"skipped": "no complete minute after entry within cap"}

    spreads, bid_sizes, ask_sizes = [], [], []
    for l in structure["legs"]:
        b, a, bs, asz = book_entry[l["symbol"]]
        spreads.append((a - b) / mid(b, a))
        bid_sizes.append(bs)
        ask_sizes.append(asz)

    gap_through_stop = (stop is not None and ret is not None and
                         ret <= stop - 0.05)

    return {
        "entry_ts": str(entry), "exit_ts": str(exit_ts), "exit_reason": exit_reason,
        "entry_value": entry_val, "exit_value": exit_val,
        "credit_or_debit": credit_or_debit, "ret": ret, "max_risk": mr,
        "session_minutes": len([t for t in stamps if t > entry]),
        "complete_minutes": len(complete),
        "entry_spread_pct": statistics.median(spreads),
        "entry_bid_size": min(bid_sizes), "entry_ask_size": min(ask_sizes),
        "n_legs": len(structure["legs"]), "gap_through_stop": gap_through_stop,
    }


# --------------------------------------------------------------- metrics

def _wilson(k: int, n: int, z: float = 1.959963984540054):
    """95% Wilson score interval for a win rate k/n."""
    if n == 0:
        return None, None
    phat = k / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    adj = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (center - adj) / denom), min(1.0, (center + adj) / denom)


def summarise(rows, structure_kind: str, dates=None) -> dict:
    """Compute section 8's statistical fields from a set of run_trade() rows.

    Row shape expected in `rows`: each element is either
    - a completed trade: run_trade()'s return dict, with the caller having
      added 'date' (the entry day, ISO) and 'period'
      ('discovery'|'confirmation'|'sealed'); or
    - a skip: {'skipped': reason, 'date': ..., 'period': ...}.
    `dates`: the full eligible date grid this test ran the trigger check
    against (used for eligible_weeks); if omitted, len(rows) is used.

    This function computes every field of section 8 that is derivable from
    `rows` alone. The caller (the test runner, which knows its own row of
    the frozen matrix) must still merge in: test_id, mechanism, trigger,
    structure, expiry_window, strikes_rule, exit_rule, databento_cost_usd,
    verdict — none of those come from the trades themselves.
    """
    trades = [r for r in rows if "ret" in r]
    skips = [r for r in rows if "skipped" in r]
    skip_reasons: dict = defaultdict(int)
    for r in skips:
        skip_reasons[r["skipped"]] += 1

    for r in trades:
        r["_commission"] = commission({"legs": [None] * r["n_legs"]})
        r["_profit_usd"] = 100 * (r["exit_value"] - r["entry_value"]) - r["_commission"]
        denom = r["max_risk"] if structure_kind == "net" else r["credit_or_debit"]
        r["_ret_after_commission"] = r["ret"] - r["_commission"] / (100 * denom) \
            if denom else None
        r["_ret_on_max_risk"] = r["_profit_usd"] / (100 * r["max_risk"]) \
            if r["max_risk"] else None

    n = len(trades)
    wins = [r for r in trades if r["_profit_usd"] > 0]
    losses = [r for r in trades if r["_profit_usd"] <= 0]
    win_lo, win_hi = _wilson(len(wins), n)

    def period_rows(p):
        return [r for r in trades if r.get("period") == p]

    def year_block(rs):
        if not rs:
            return {"trades": 0, "win_rate": None, "avg_after_commission": None,
                    "total_profit": 0.0}
        w = [r for r in rs if r["_profit_usd"] > 0]
        return {"trades": len(rs), "win_rate": len(w) / len(rs),
                "avg_after_commission": statistics.mean(r["_ret_after_commission"] for r in rs),
                "total_profit": sum(r["_profit_usd"] for r in rs)}

    win_dollars = sum(r["_profit_usd"] for r in wins)
    loss_dollars = -sum(r["_profit_usd"] for r in losses if r["_profit_usd"] < 0)
    profit_factor = (win_dollars / loss_dollars) if loss_dollars > 0 else \
        (float("inf") if win_dollars > 0 else None)

    def by_key(key_fn):
        g: dict = defaultdict(float)
        for r in trades:
            g[key_fn(r)] += r["_profit_usd"]
        return g

    yearly = defaultdict(list)
    for r in trades:
        yearly[date.fromisoformat(r["date"]).year].append(r)
    yearly_results = {y: year_block(rs) for y, rs in sorted(yearly.items())}

    positive_total = sum(p for p in (r["_profit_usd"] for r in trades) if p > 0)
    def share(x):
        return (x / positive_total) if positive_total > 0 else None

    best_trade = max(trades, key=lambda r: r["_profit_usd"]) if trades else None
    worst_trade = min(trades, key=lambda r: r["_profit_usd"]) if trades else None
    top5 = sorted((r["_profit_usd"] for r in trades), reverse=True)[:5]
    by_date = by_key(lambda r: r["date"])
    by_year = by_key(lambda r: date.fromisoformat(r["date"]).year)

    # running drawdown on the commission-adjusted dollar profit, trades in
    # date order
    ordered = sorted(trades, key=lambda r: r["date"])
    running = peak = max_dd = 0.0
    for r in ordered:
        running += r["_profit_usd"]
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    # max simultaneous max_risk open on any one calendar day
    daily_risk: dict = defaultdict(float)
    for r in trades:
        d0 = date.fromisoformat(r["entry_ts"][:10])
        d1 = date.fromisoformat(r["exit_ts"][:10])
        d = d0
        while d <= d1:
            daily_risk[d] += 100 * r["max_risk"]
            d = date.fromordinal(d.toordinal() + 1)
    max_simultaneous_risk = max(daily_risk.values()) if daily_risk else 0.0

    exit_counts = defaultdict(int)
    for r in trades:
        exit_counts[r["exit_reason"]] += 1

    return {
        "eligible_weeks": len(dates) if dates is not None else len(rows),
        "skipped_weeks": len(skips), "skip_reasons": dict(skip_reasons),
        "dev_trades": len(period_rows("discovery")) + len(period_rows("confirmation")),
        "discovery_trades": len(period_rows("discovery")),
        "confirmation_trades": len(period_rows("confirmation")),
        "sealed_trades": len(period_rows("sealed")),
        "win_rate": len(wins) / n if n else None,
        "win_rate_ci_low": win_lo, "win_rate_ci_high": win_hi,
        "avg_gross_return": statistics.mean(r["ret"] for r in trades) if n else None,
        "median_gross_return": statistics.median(r["ret"] for r in trades) if n else None,
        "avg_return_after_commission": statistics.mean(r["_ret_after_commission"] for r in trades) if n else None,
        "avg_return_on_credit_or_debit": (statistics.mean(r["ret"] for r in trades)
            if n and structure_kind in ("credit", "debit") else None),
        "avg_return_on_max_risk": statistics.mean(r["_ret_on_max_risk"] for r in trades) if n else None,
        "profit_factor": profit_factor,
        "total_profit_usd": sum(r["_profit_usd"] for r in trades),
        "max_drawdown_usd": max_dd,
        "max_simultaneous_risk_usd": max_simultaneous_risk,
        "best_trade": {"date": best_trade["date"], "profit_usd": best_trade["_profit_usd"],
                       "ret": best_trade["ret"]} if best_trade else None,
        "worst_trade": {"date": worst_trade["date"], "profit_usd": worst_trade["_profit_usd"],
                        "ret": worst_trade["ret"]} if worst_trade else None,
        "n_target_exits": exit_counts.get("target touched", 0),
        "n_stop_exits": exit_counts.get("stop touched", 0),
        "n_time_exits": exit_counts.get("time cap", 0),
        "n_overnight_gap_through_stop": sum(1 for r in trades if r["gap_through_stop"]),
        "yearly_results": yearly_results,
        "discovery_vs_confirmation": {"discovery": year_block(period_rows("discovery")),
                                       "confirmation": year_block(period_rows("confirmation"))},
        "profit_share_best_trade": share(best_trade["_profit_usd"]) if best_trade else None,
        "profit_share_best_5_trades": share(sum(top5)) if top5 else None,
        "profit_share_best_date": share(max(by_date.values())) if by_date else None,
        "profit_share_best_year": share(max(by_year.values())) if by_year else None,
        "entry_median_spread_pct": statistics.median(r["entry_spread_pct"] for r in trades) if n else None,
        "entry_median_bid_size": statistics.median(r["entry_bid_size"] for r in trades) if n else None,
        "entry_median_ask_size": statistics.median(r["entry_ask_size"] for r in trades) if n else None,
    }
