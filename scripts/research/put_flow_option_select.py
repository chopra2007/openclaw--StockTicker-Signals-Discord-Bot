"""Deterministic PUT-flow option contract selector (TODO #100, Phase 2).

Pure and importable. Given one entry-time option chain slice and the known
6:35 a.m. Pacific stock price, this applies the frozen research policy at
`.omc/research/put-flow-option-trade-system/frozen-policy.json`
(sha256 f284dbe96350cb16c6c4f527ab6f20b8d6ffa3d5f93aca1656f3e94e8209ffb0)
and returns either the chosen OCC contract(s) with entry ask/bid/debit, or
`NO OPTION TRADE` with an exact reason.

Rules implemented verbatim from the frozen policy:

  structures
    ATM_PUT           long PUT, strike closest to stock_entry_px
    OTM5_PUT          long PUT, strike closest to 0.95 * stock_entry_px
    PUT_DEBIT_SPREAD  long PUT closest to stock_entry_px,
                      short PUT closest to 0.95 * stock_entry_px

  expiration_rule
    earliest listed expiration with
      expiry >= planned_stock_exit_date + 7 calendar days   AND
      expiry <= entry_date            + 45 calendar days

  contract_eligibility (per leg, "NO OPTION TRADE" on any failure, never relaxed)
    standard deliverable only (non_standard falsy, multiplier == 100)
    positive bid, positive ask, two-sided quote, valid quote time
    quoted spread <= 10% of mid
    open interest >= 100

  pricing
    long put entry value      = ask         liquidation value = bid
    spread entry debit        = long_ask - short_bid
    spread liquidation value  = long_bid - short_ask
    reject zero/negative debit, crossed quote, unusable quote

  tie_break_order
    earliest qualifying expiration, then smallest |strike - target|,
    then higher open interest, then contract symbol ascending

Never uses flow_side. Uses only entry-time fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# frozen constants
# ---------------------------------------------------------------------------

MAX_DAYS_AFTER_ENTRY = 45
MIN_DAYS_AFTER_PLANNED_EXIT = 7
MAX_SPREAD_PCT_OF_MID = 0.10
MIN_OPEN_INTEREST = 100
REQUIRED_MULTIPLIER = 100
OTM_FACTOR = 0.95

STRUCTURES = ("ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD")

# per structure: list of (side, target_kind); target_kind in {"ATM", "OTM5"}
_STRUCTURE_LEGS = {
    "ATM_PUT": [("long", "ATM")],
    "OTM5_PUT": [("long", "OTM5")],
    "PUT_DEBIT_SPREAD": [("long", "ATM"), ("short", "OTM5")],
}


# ---------------------------------------------------------------------------
# input row
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainRow:
    """One entry-time option quote. Only entry-time fields are accepted."""

    contract_symbol: str
    expiry: str            # "YYYY-MM-DD"
    strike: float
    option_type: str       # "PUT" / "CALL"
    bid: Optional[float]
    ask: Optional[float]
    open_interest: Optional[float]
    volume: Optional[float] = None
    multiplier: Optional[float] = None
    non_standard: Optional[int] = None
    quote_quality: Optional[str] = None
    provider_quote_time: Optional[float] = None
    underlying_px: Optional[float] = None

    @classmethod
    def from_mapping(cls, m: dict) -> "ChainRow":
        return cls(
            contract_symbol=str(m["contract_symbol"]).strip(),
            expiry=str(m["expiry"])[:10],
            strike=float(m["strike"]),
            option_type=str(m.get("option_type", "PUT")).upper(),
            bid=_maybe_float(m.get("bid")),
            ask=_maybe_float(m.get("ask")),
            open_interest=_maybe_float(m.get("open_interest")),
            volume=_maybe_float(m.get("volume")),
            multiplier=_maybe_float(m.get("multiplier")),
            non_standard=(None if m.get("non_standard") is None else int(m["non_standard"])),
            quote_quality=(None if m.get("quote_quality") is None else str(m["quote_quality"])),
            provider_quote_time=_maybe_float(m.get("provider_quote_time")),
            underlying_px=_maybe_float(m.get("underlying_px")),
        )


def _maybe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# expiration rule
# ---------------------------------------------------------------------------

def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def expiry_window(entry_date, planned_stock_exit_date) -> tuple[date, date]:
    ed = _as_date(entry_date)
    xd = _as_date(planned_stock_exit_date)
    lo = xd + timedelta(days=MIN_DAYS_AFTER_PLANNED_EXIT)
    hi = ed + timedelta(days=MAX_DAYS_AFTER_ENTRY)
    return lo, hi


def choose_expiry(expiries: Iterable[str], entry_date, planned_stock_exit_date) -> Optional[str]:
    """Earliest listed expiration inside [exit+7, entry+45] calendar days."""
    lo, hi = expiry_window(entry_date, planned_stock_exit_date)
    ok = sorted({str(e)[:10] for e in expiries if lo <= _as_date(e) <= hi})
    return ok[0] if ok else None


# ---------------------------------------------------------------------------
# strike selection with frozen tie-breaks
# ---------------------------------------------------------------------------

def _target_strike(kind: str, stock_entry_px: float) -> float:
    if kind == "ATM":
        return stock_entry_px
    if kind == "OTM5":
        return OTM_FACTOR * stock_entry_px
    raise ValueError(kind)


def pick_row(rows: list[ChainRow], target: float) -> ChainRow:
    """Closest strike to target; tie-break higher OI then symbol ascending."""
    def key(r: ChainRow):
        return (
            abs(r.strike - target),
            -(r.open_interest or 0.0),
            r.contract_symbol,
        )
    return sorted(rows, key=key)[0]


# ---------------------------------------------------------------------------
# eligibility
# ---------------------------------------------------------------------------

def leg_eligibility_failure(r: ChainRow) -> Optional[str]:
    """Return an exact failure reason, or None if the leg passes every gate."""
    if r.non_standard:
        return f"{r.contract_symbol}: adjusted / non-standard deliverable"
    if r.multiplier is not None and r.multiplier != REQUIRED_MULTIPLIER:
        return f"{r.contract_symbol}: multiplier {r.multiplier:g} is not {REQUIRED_MULTIPLIER}"
    if r.multiplier is None:
        return f"{r.contract_symbol}: multiplier missing"
    if r.provider_quote_time is None or r.provider_quote_time <= 0:
        return f"{r.contract_symbol}: no valid quote time"
    if r.bid is None or r.bid <= 0:
        return f"{r.contract_symbol}: no positive bid"
    if r.ask is None or r.ask <= 0:
        return f"{r.contract_symbol}: no positive ask"
    if r.ask < r.bid:
        return f"{r.contract_symbol}: crossed quote (bid {r.bid:g} > ask {r.ask:g})"
    if r.quote_quality is not None and r.quote_quality.upper() == "NO_TWO_SIDED":
        return f"{r.contract_symbol}: quote not two-sided ({r.quote_quality})"
    mid = (r.bid + r.ask) / 2.0
    if mid <= 0:
        return f"{r.contract_symbol}: unusable quote (mid {mid:g})"
    spread_pct = (r.ask - r.bid) / mid
    if spread_pct > MAX_SPREAD_PCT_OF_MID + 1e-12:
        return (f"{r.contract_symbol}: quoted spread {spread_pct*100:.1f}% of mid "
                f"exceeds {MAX_SPREAD_PCT_OF_MID*100:.0f}%")
    if r.open_interest is None or r.open_interest < MIN_OPEN_INTEREST:
        oi = "missing" if r.open_interest is None else f"{r.open_interest:g}"
        return f"{r.contract_symbol}: open interest {oi} below {MIN_OPEN_INTEREST}"
    return None


# ---------------------------------------------------------------------------
# main selector
# ---------------------------------------------------------------------------

@dataclass
class Selection:
    structure: str
    result: str                       # "SELECTED" | "NO OPTION TRADE"
    reason: Optional[str] = None
    expiry: Optional[str] = None
    legs: list[dict] = field(default_factory=list)
    entry: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "structure": self.structure,
            "result": self.result,
            "reason": self.reason,
            "expiry": self.expiry,
            "legs": self.legs,
            "entry": self.entry,
        }


def _no_trade(structure: str, reason: str, expiry: Optional[str] = None) -> Selection:
    return Selection(structure=structure, result="NO OPTION TRADE", reason=reason, expiry=expiry)


def select_structure(
    chain_rows: Iterable,
    stock_entry_px: float,
    entry_date,
    planned_stock_exit_date,
    structure: str,
) -> Selection:
    if structure not in _STRUCTURE_LEGS:
        raise ValueError(f"unknown structure {structure!r}")

    rows = [r if isinstance(r, ChainRow) else ChainRow.from_mapping(r) for r in chain_rows]
    puts = [r for r in rows if r.option_type == "PUT"]
    if not puts:
        return _no_trade(structure, "chain slice has no PUT rows")

    exp = choose_expiry({r.expiry for r in puts}, entry_date, planned_stock_exit_date)
    if exp is None:
        lo, hi = expiry_window(entry_date, planned_stock_exit_date)
        return _no_trade(
            structure,
            f"no listed expiration between {lo.isoformat()} and {hi.isoformat()}",
        )

    exp_rows = [r for r in puts if r.expiry == exp]

    legs_out: list[dict] = []
    picked: dict[str, ChainRow] = {}
    for side, kind in _STRUCTURE_LEGS[structure]:
        target = _target_strike(kind, stock_entry_px)
        row = pick_row(exp_rows, target)
        picked[side] = row
        fail = leg_eligibility_failure(row)
        if fail is not None:
            return _no_trade(
                structure,
                f"{side} leg fails eligibility -> {fail}",
                expiry=exp,
            )
        legs_out.append({
            "side": side,
            "target_kind": kind,
            "target_strike": round(target, 4),
            "contract_symbol": row.contract_symbol,
            "strike": row.strike,
            "expiry": row.expiry,
            "bid": row.bid,
            "ask": row.ask,
            "open_interest": row.open_interest,
        })

    if structure == "PUT_DEBIT_SPREAD":
        lng, sht = picked["long"], picked["short"]
        if lng.strike <= sht.strike:
            return _no_trade(
                structure,
                f"degenerate spread: long strike {lng.strike:g} <= short strike {sht.strike:g}",
                expiry=exp,
            )
        entry_debit = lng.ask - sht.bid
        liq_value = lng.bid - sht.ask
        if entry_debit <= 0:
            return _no_trade(
                structure,
                f"spread entry debit {entry_debit:.2f} is zero or negative",
                expiry=exp,
            )
        entry = {
            "kind": "spread",
            "long_ask": lng.ask,
            "short_bid": sht.bid,
            "entry_debit": round(entry_debit, 4),
            "liquidation_value": round(liq_value, 4),
            "round_trip_cost_usd": 1.80,
        }
    else:
        lng = picked["long"]
        entry = {
            "kind": "long_put",
            "entry_ask": lng.ask,
            "liquidation_bid": lng.bid,
            "entry_cost_per_contract_usd": round(lng.ask * 100.0, 4),
            "round_trip_cost_usd": 0.90,
        }

    return Selection(
        structure=structure,
        result="SELECTED",
        expiry=exp,
        legs=legs_out,
        entry=entry,
    )


def select_all(
    chain_rows: Iterable,
    stock_entry_px: float,
    entry_date,
    planned_stock_exit_date,
) -> dict[str, dict]:
    out = {}
    rows = list(chain_rows)
    for s in STRUCTURES:
        out[s] = select_structure(
            rows, stock_entry_px, entry_date, planned_stock_exit_date, s
        ).to_dict()
    return out


# ---------------------------------------------------------------------------
# reconstruction (no stored entry quote): strike/expiry rule only
# ---------------------------------------------------------------------------

def occ_symbol(root: str, expiry: str, strike: float, right: str = "P") -> str:
    d = _as_date(expiry)
    milli = int(round(strike * 1000))
    return f"{root.upper()}{d:%y%m%d}{right}{milli:08d}"


def reconstruct_structure(
    expiries: Iterable[str],
    strikes: Iterable[float],
    stock_entry_px: float,
    entry_date,
    planned_stock_exit_date,
    structure: str,
    occ_root: str,
) -> dict:
    """Apply ONLY the frozen strike + expiration rule (no quote, no gates).

    Every leg is labelled RECONSTRUCTED_TRADE_BAR_ONLY: there is no stored
    entry quote for these contracts.
    """
    exp = choose_expiry(expiries, entry_date, planned_stock_exit_date)
    if exp is None:
        lo, hi = expiry_window(entry_date, planned_stock_exit_date)
        return {
            "structure": structure,
            "result": "NO OPTION TRADE",
            "reason": f"no listed expiration between {lo.isoformat()} and {hi.isoformat()}",
            "label": "RECONSTRUCTED_TRADE_BAR_ONLY",
        }
    strikes = sorted({float(s) for s in strikes})
    legs = []
    for side, kind in _STRUCTURE_LEGS[structure]:
        target = _target_strike(kind, stock_entry_px)
        strike = min(strikes, key=lambda s: (abs(s - target), s))
        legs.append({
            "side": side,
            "target_kind": kind,
            "target_strike": round(target, 4),
            "strike": strike,
            "expiry": exp,
            "occ_symbol": occ_symbol(occ_root, exp, strike),
        })
    return {
        "structure": structure,
        "result": "RECONSTRUCTED",
        "label": "RECONSTRUCTED_TRADE_BAR_ONLY",
        "expiry": exp,
        "legs": legs,
        "entry": {"note": "no stored entry quote; strike/expiry rule only"},
    }


# ---------------------------------------------------------------------------
# apply to the live DB entry slices  (runnable, still importable)
# ---------------------------------------------------------------------------

def _load_entry_slice(db_path: str, shortlist_id: int) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            """
            SELECT contract_symbol, expiry, strike, option_type, bid, ask, last, mark,
                   open_interest, volume, multiplier, non_standard, quote_quality,
                   provider_quote_time, underlying_px
              FROM put_flow_option_snapshots
             WHERE shortlist_id = ? AND stage = 'ENTRY'
            """,
            (shortlist_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def apply_to_live_db(db_path: str) -> dict:
    """Apply every structure to the four real ENTRY slices (DKS/SUI/MSTR/MARA)."""
    import sqlite3

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT id, ticker, entry_session, planned_exit_session, entry_stock_px
              FROM put_flow_shortlist
             WHERE id IN (17, 18, 19, 20)
             ORDER BY id
            """
        ).fetchall()
    finally:
        con.close()

    out = {}
    for r in rows:
        chain = _load_entry_slice(db_path, r["id"])
        out[r["ticker"]] = {
            "position_id": r["id"],
            "ticker": r["ticker"],
            "entry_session": r["entry_session"],
            "planned_exit_session": r["planned_exit_session"],
            "entry_stock_px": r["entry_stock_px"],
            "chain_rows": len(chain),
            "selections": select_all(
                chain,
                float(r["entry_stock_px"]),
                r["entry_session"],
                r["planned_exit_session"],
            ),
        }
    return out


def _main(argv=None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Apply the frozen selector to the live ENTRY slices.")
    p.add_argument("--db", default="consensus.db")
    p.add_argument("--out", default=None, help="write JSON here instead of stdout")
    a = p.parse_args(argv)

    result = apply_to_live_db(a.db)
    text = json.dumps(result, indent=2, sort_keys=True)
    if a.out:
        from pathlib import Path

        Path(a.out).write_text(text + "\n")
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
