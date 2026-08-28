#!/usr/bin/env python3
"""Historical evaluator for the put-flow option trade system (TODO #100).

This scores the 9 frozen candidates (3 structures x 3 exit policies) from
``.omc/research/put-flow-option-trade-system/frozen-policy.json`` against the
frozen 181-trade stock sample in
``.omc/research/extreme-put-flow-morning-shortlist/exact-entry-trades.csv`` and
writes every required artifact under
``.omc/research/put-flow-option-trade-system/``.

It NEVER inspects the untouched evaluation split until
``chosen-development-rule.json`` and its ``.sha256`` exist and verify.  The
``--split evaluation`` and ``--split full`` modes refuse to run without that
fingerprint file; only ``--split development`` and ``--choose`` run before it.

--------------------------------------------------------------------------------
INPUT DATA CONTRACT (all optional -- the evaluator degrades honestly)
--------------------------------------------------------------------------------
Raw data root (``--data-root``, default
``/home/openclaw/.openclaw/data/put_flow_option_history/``) may contain:

  download-manifest.csv   -- one row per candidate option contract that was
                             fetched.  Recognised columns (case-insensitive,
                             missing ones tolerated):
                               market_date, ticker, structure_id, leg_side,
                               contract_symbol, option_type, strike, expiration,
                               multiplier, open_interest, standard_deliverable,
                               adjusted, entry_bid, entry_ask, entry_quote_time,
                               bars_file
                             ``bars_file`` is a path (absolute, or relative to
                             the data root) to that contract's minute bars.

  <per-contract minute bar files>  -- CSV or JSON.  Recognised fields
                             (case-insensitive): a timestamp (minute / time /
                             timestamp / datetime / t), open, high, low, close,
                             volume, and OPTIONALLY bid, ask.  Timestamps with
                             no timezone are read as America/Los_Angeles;
                             numeric epoch seconds are accepted.

If the manifest is absent, or a contract has no bar file, or the contract
selector module is unavailable, the affected stock signals are scored UNKNOWN
-- never dropped.  With near-zero coverage the run still completes and
``gates.json`` records INSUFFICIENT DATA on G1/G2 with the real counts.

--------------------------------------------------------------------------------
CONTRACT SELECTOR
--------------------------------------------------------------------------------
Contract selection uses the shared selector in
``scripts/research/put_flow_option_select.py`` (written by another lane):

    select(structure_id, chain_rows, stock_entry_px, entry_date,
           planned_exit_date) -> Selection | Rejection

``chain_rows`` is the list of manifest rows for that (market_date, ticker,
structure_id).  A ``Selection`` exposes ``.contracts`` -- a list of dicts each
carrying at least ``contract_symbol`` and ``side`` ("long"/"short"), plus
whatever pricing fields the selector kept.  A ``Rejection`` exposes ``.reason``.
Dicts with a ``contracts`` / ``reason`` key are also accepted.  If the module
is missing, every trade is scored UNKNOWN with note "selector module
unavailable" (tests inject their own ``select_fn``).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PACIFIC = ZoneInfo("America/Los_Angeles")
WORKSPACE = Path(__file__).resolve().parents[2]
RESEARCH_DIR = WORKSPACE / ".omc" / "research" / "put-flow-option-trade-system"
POLICY_PATH = RESEARCH_DIR / "frozen-policy.json"
POLICY_SHA_PATH = RESEARCH_DIR / "frozen-policy.sha256"
STOCK_CSV = (
    WORKSPACE
    / ".omc"
    / "research"
    / "extreme-put-flow-morning-shortlist"
    / "exact-entry-trades.csv"
)
DEFAULT_DATA_ROOT = Path("/home/openclaw/.openclaw/data/put_flow_option_history/")

ENTRY_TIME = dtime(6, 35)            # 06:35 Pacific
ENTRY_WINDOW_MIN = 5                 # first positive-volume minute in 06:35-06:40
EXIT_WINDOW_MIN = 5                  # exit fill within 5 minutes of the exit time
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 20_260_827
BORDERLINE_SEEDS = [20260827, 1, 2, 3, 4, 5, 6, 7]
BORDERLINE_FRAC = 0.10

STRUCTURE_ORDER = ["ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD"]
EXIT_ORDER = ["TIME_ONLY", "PT25_SL35", "PT50_SL35"]

TIER_EXACT = "EXACT_BID_ASK"
TIER_CONS = "CONSERVATIVE_TRADE_BAR"
TIER_POSS = "POSSIBLE_TOUCH"
TIER_UNKNOWN = "UNKNOWN"
RESOLVED_TIERS = (TIER_EXACT, TIER_CONS)


# --------------------------------------------------------------------------- #
# Frozen policy + stock sample
# --------------------------------------------------------------------------- #
def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_frozen_policy(policy_path=POLICY_PATH, sha_path=POLICY_SHA_PATH) -> dict:
    """Abort unless the frozen policy file matches its recorded sha256."""
    want = Path(sha_path).read_text().split()[0].strip().lower()
    got = sha256_file(policy_path).lower()
    if want != got:
        raise SystemExit(
            f"FROZEN POLICY HASH MISMATCH -- refusing to run.\n"
            f"  expected {want}\n  actual   {got}\n  file     {policy_path}"
        )
    return json.loads(Path(policy_path).read_text())


def load_stock_sample(csv_path=STOCK_CSV, policy: dict | None = None) -> pd.DataFrame:
    df = pd.read_csv(
        csv_path,
        dtype={
            "market_date": str,
            "entry_date": str,
            "exit_date": str,
            "ticker": str,
            "contract_symbol": str,
        },
    )
    if policy is not None:
        want = policy["data_cut"]["stock_sample_sha256"]
        got = sha256_file(csv_path)
        if want != got:
            raise SystemExit(
                f"STOCK SAMPLE HASH MISMATCH -- expected {want} actual {got}"
            )
    dups = df.duplicated(["market_date", "ticker"]).sum()
    if dups:
        raise SystemExit(f"stock sample has {dups} duplicate (market_date,ticker) rows")
    return df


def build_split(dates) -> tuple[set[str], set[str]]:
    """Chronological 60/40 split by whole signal date.

    The development block takes whole dates in date order until at least
    ``development_fraction`` of the unique dates are used; the rest is the
    evaluation block.  Every trade that shares a market_date stays together.
    """
    uniq = sorted(set(dates))
    n = len(uniq)
    if n == 0:
        return set(), set()
    need = 0.60 * n
    k = n
    for i in range(n):
        if (i + 1) >= need:
            k = i + 1
            break
    return set(uniq[:k]), set(uniq[k:])


# --------------------------------------------------------------------------- #
# Pricing helpers
# --------------------------------------------------------------------------- #
def commission_round_trip_per_share(n_legs: int) -> float:
    """$0.45 / contract / side -> round-trip $ per share (contract = 100)."""
    return (0.90 if n_legs == 1 else 1.80) / 100.0


def net_return(entry_debit: float, liquidation_value: float, n_legs: int) -> float:
    """Net return on premium after round-trip commission."""
    rt = commission_round_trip_per_share(n_legs)
    return (liquidation_value - entry_debit - rt) / entry_debit


# --------------------------------------------------------------------------- #
# Bar / manifest loading
# --------------------------------------------------------------------------- #
_TIME_KEYS = ("minute", "time", "timestamp", "datetime", "t", "date_time")
_VOL_KEYS = ("volume", "vol", "v")


def _parse_dt(value) -> datetime | None:
    if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v > 1e8:  # epoch seconds
            return datetime.fromtimestamp(v, tz=timezone.utc).astimezone(PACIFIC)
        return None
    s = str(value).strip()
    if not s:
        return None
    dt = None
    for parser in (
        lambda x: datetime.fromisoformat(x),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M"),
    ):
        try:
            dt = parser(s)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=PACIFIC)
    return dt.astimezone(PACIFIC)


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def normalize_bar(raw: dict) -> dict | None:
    """Return {'dt','open','high','low','close','volume','bid','ask'} or None."""
    low = {str(k).lower(): v for k, v in raw.items()}
    dt = None
    for key in _TIME_KEYS:
        if key in low:
            dt = _parse_dt(low[key])
            if dt is not None:
                break
    if dt is None:
        return None
    vol = None
    for key in _VOL_KEYS:
        if key in low:
            vol = _num(low[key])
            break
    bar = {
        "dt": dt,
        "open": _num(low.get("open", low.get("o"))),
        "high": _num(low.get("high", low.get("h"))),
        "low": _num(low.get("low", low.get("l"))),
        "close": _num(low.get("close", low.get("c"))),
        "volume": 0.0 if vol is None else vol,
        "bid": _num(low.get("bid")),
        "ask": _num(low.get("ask")),
    }
    if bar["high"] is None or bar["low"] is None:
        return None
    return bar


def _yahoo_chart_bars(obj: dict) -> list[dict]:
    """Parse a Yahoo v8 finance/chart JSON payload -> normalized bars."""
    try:
        result = obj["chart"]["result"][0]
        stamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for i, ts in enumerate(stamps):
        bar = normalize_bar({
            "t": ts,
            "open": (q.get("open") or [None] * len(stamps))[i],
            "high": (q.get("high") or [None] * len(stamps))[i],
            "low": (q.get("low") or [None] * len(stamps))[i],
            "close": (q.get("close") or [None] * len(stamps))[i],
            "volume": (q.get("volume") or [None] * len(stamps))[i],
        })
        if bar:
            out.append(bar)
    return out


def load_bars(path: Path) -> list[dict]:
    """Load one contract's minute bars, sorted by time. Missing file -> []."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text().strip()
    if not text:
        return []
    rows: list[dict] = []
    if p.suffix.lower() == ".json" or text[0] in "[{":
        obj = json.loads(text)
        if isinstance(obj, dict) and "chart" in obj:
            rows = _yahoo_chart_bars(obj)
            rows.sort(key=lambda b: b["dt"])
            return rows
        if isinstance(obj, dict):
            for key in ("bars", "data", "results", "rows", "candles"):
                if isinstance(obj.get(key), list):
                    obj = obj[key]
                    break
            else:
                obj = [obj]
        for raw in obj:
            if isinstance(raw, dict):
                bar = normalize_bar(raw)
                if bar:
                    rows.append(bar)
    else:
        for raw in csv.DictReader(text.splitlines()):
            bar = normalize_bar(raw)
            if bar:
                rows.append(bar)
    rows.sort(key=lambda b: b["dt"])
    return rows


def load_manifest(data_root: Path, override: Path | None = None) -> pd.DataFrame | None:
    """Read the download manifest.

    Precedence: an explicit ``override`` path, else the frozen research-dir
    location ``.omc/research/put-flow-option-trade-system/download-manifest.csv``,
    else ``<data_root>/download-manifest.csv``.
    """
    candidates = []
    if override:
        candidates.append(Path(override))
    else:
        candidates.append(RESEARCH_DIR / "download-manifest.csv")
        candidates.append(Path(data_root) / "download-manifest.csv")
    for path in candidates:
        if path.exists():
            df = pd.read_csv(path, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
    return None


FROZEN_SELECTIONS_PATH = RESEARCH_DIR / "frozen-sample-selections.json"

_STRUCTURE_KEYS = ("ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD")


def load_frozen_selections(path: Path | None = None) -> dict:
    """Load the selector lane's per-trade contract bridge.

    ``frozen-sample-selections.json`` maps each frozen stock trade to the OCC
    contract symbol the frozen rule names for every structure/leg.  This is the
    join bridge: frozen stock trade (market_date == signal_date, ticker) ->
    per_trade entry -> OCC symbol -> download manifest / bar file.

    Returns ``{"by_sig": {(signal_date, ticker): entry},
               "probe_by_contract": {occ: probe_row},
               "present": bool}``.
    """
    p = Path(path) if path else FROZEN_SELECTIONS_PATH
    if not p.exists():
        return {"by_sig": {}, "probe_by_contract": {}, "present": False}
    doc = json.loads(p.read_text())
    by_sig = {}
    for entry in doc.get("per_trade", []):
        sig = (str(entry.get("signal_date")), str(entry.get("ticker")))
        by_sig[sig] = entry
    probe = {}
    for row in doc.get("probe_results", []):
        c = row.get("contract")
        if c:
            probe[str(c)] = row
    return {"by_sig": by_sig, "probe_by_contract": probe, "present": True}


def frozen_selection_contracts(entry: dict, structure_id: str):
    """Pull the OCC legs for one structure out of a per_trade entry.

    Returns a list of ``{"contract_symbol", "side"}`` dicts, or ``None`` when the
    entry names no contract for that structure.
    """
    if not entry:
        return None
    blk = (entry.get("contracts") or {}).get(structure_id)
    if not blk:
        return None
    out = []
    for side in ("long", "short"):
        leg = blk.get(side)
        if leg and leg.get("occ_symbol"):
            out.append({"contract_symbol": str(leg["occ_symbol"]), "side": side})
    return out or None


def manifest_stats_by_contract(manifest: pd.DataFrame | None) -> dict:
    """``{contract_symbol: {rows, positive_volume_rows, http_status,
    quality_tier, sample}}`` from the download manifest."""
    if manifest is None:
        return {}
    sym_col = next((c for c in ("contract", "contract_symbol", "symbol")
                    if c in manifest.columns), None)
    if sym_col is None:
        return {}
    out = {}
    for _, r in manifest.iterrows():
        sym = str(r.get(sym_col) or "")
        if not sym:
            continue
        out[sym] = {
            "rows": _num(r.get("rows")) or 0.0,
            "positive_volume_rows": _num(r.get("positive_volume_rows")) or 0.0,
            "http_status": str(r.get("http_status") or ""),
            "quality_tier": str(r.get("quality_tier") or ""),
            "sample": str(r.get("sample") or ""),
        }
    return out


_MISSING_TIERS = {"MISSING", "MISSING_EXPIRED", "EXPIRED"}

# Set once per run by set_frozen_selections(); read by evaluate_candidate when
# its frozen_selections kwarg is not supplied (mirrors the ENTRY_TIME global).
_FROZEN_SELECTIONS: dict = {"by_sig": {}, "probe_by_contract": {},
                           "present": False, "_manifest_stats": {}}


def set_frozen_selections(manifest, path: Path | None = None) -> dict:
    global _FROZEN_SELECTIONS
    fs = load_frozen_selections(path)
    fs["_manifest_stats"] = manifest_stats_by_contract(manifest)
    _FROZEN_SELECTIONS = fs
    return fs


def contract_is_missing(sym: str, mstats: dict, probe: dict) -> str | None:
    """Return a human reason if the contract has no obtainable data, else None."""
    st = mstats.get(sym) or {}
    if st.get("http_status") == "404" or st.get("quality_tier") in _MISSING_TIERS:
        return "expired contract -- HTTP 404 (Yahoo serves unexpired contracts only)"
    pr = probe.get(sym) or {}
    if pr.get("is_404") or pr.get("http_status") == 404 or \
            str(pr.get("quality_tier", "")).upper() in _MISSING_TIERS:
        return (pr.get("missing_reason")
                or "expired contract -- HTTP 404 (Yahoo serves unexpired only)")
    return None


_DATE_KEY_ALIASES = ("market_date", "signal_date", "signal_market_date")
_ENTRY_KEY_ALIASES = ("entry_date", "entry_session", "entry_session_date")


def manifest_join_view(manifest: pd.DataFrame | None):
    """Normalize the manifest's join columns.

    Returns ``(df, date_kind, symbol_col, structure_col)`` where ``df`` has a
    ``_join_date`` column and ``date_kind`` is "market_date" (join to the stock
    trade's market_date), "entry_date" (join to its entry_date), or ``None``
    (no usable date key -- the manifest cannot be joined to the frozen sample).
    """
    if manifest is None or "ticker" not in manifest.columns:
        return None, None, None, None
    sym_col = next((c for c in ("contract_symbol", "contract", "symbol")
                    if c in manifest.columns), None)
    struct_col = next((c for c in ("structure_id", "structure")
                       if c in manifest.columns), None)
    for kind, aliases in (("market_date", _DATE_KEY_ALIASES),
                          ("entry_date", _ENTRY_KEY_ALIASES)):
        col = next((c for c in aliases if c in manifest.columns), None)
        if col is not None and manifest[col].notna().any():
            df = manifest.copy()
            df["_join_date"] = df[col].astype(str)
            return df, kind, sym_col, struct_col
    return manifest, None, sym_col, struct_col


# --------------------------------------------------------------------------- #
# Selector plumbing (duck-typed against put_flow_option_select.select)
# --------------------------------------------------------------------------- #
class SelectorUnavailable(RuntimeError):
    """The shared contract selector could not be imported -- hard failure."""


def resolve_selector(explicit=None):
    """Return a ``select_fn(structure_id, chain_rows, px, entry_date,
    planned_exit_date) -> Selection`` adapter around the shared
    ``put_flow_option_select`` module.  Missing module -> SelectorUnavailable
    (never a silent no-op that would fill the run with UNKNOWN rows).
    """
    if explicit is not None:
        return explicit
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import put_flow_option_select as _S  # type: ignore
    except Exception as exc:  # pragma: no cover - environment failure
        raise SelectorUnavailable(
            "cannot import scripts/research/put_flow_option_select.py -- "
            f"{exc!r}. Refusing to run: a missing selector must abort, not "
            "produce silent UNKNOWN rows."
        )
    if hasattr(_S, "select_structure"):
        def _fn(structure_id, chain_rows, px, entry_date, planned_exit_date):
            return _S.select_structure(chain_rows, px, entry_date,
                                       planned_exit_date, structure_id)
        return _fn
    if hasattr(_S, "select"):
        return _S.select
    raise SelectorUnavailable(
        "put_flow_option_select exposes neither select_structure nor select"
    )


def normalize_selection(result):
    """-> (contracts, reason).  ``contracts`` is None on a rejection.

    Accepts a ``Selection`` dataclass, a ``reconstruct_structure`` dict, or a
    plain ``{"contracts": [...]}`` / ``{"reason": ...}`` dict.
    """
    if result is None:
        return None, "selector returned None"
    if isinstance(result, dict):
        res = result.get("result")
        legs = result.get("legs") or result.get("contracts") or []
        reason = result.get("reason") or ""
    else:
        legs = getattr(result, "legs", None) or getattr(result, "contracts", None) or []
        res = getattr(result, "result", "SELECTED" if legs else None)
        reason = getattr(result, "reason", "") or ""
    if res is not None and res not in ("SELECTED", "RECONSTRUCTED"):
        return None, (reason or str(res))
    out = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        sym = (leg.get("contract_symbol") or leg.get("occ_symbol")
               or leg.get("symbol") or leg.get("contract"))
        out.append({
            "contract_symbol": str(sym or ""),
            "side": str(leg.get("side", "long")).lower(),
            "entry_bid": leg.get("bid"),
            "entry_ask": leg.get("ask"),
        })
    return (out or None), (reason or ("no legs in selection" if not out else ""))


# --------------------------------------------------------------------------- #
# Position pricing (long / short legs in the right direction)
# --------------------------------------------------------------------------- #
class Leg:
    """One option leg: its bars keyed by minute, and whether quotes exist."""

    def __init__(self, side: str, bars: list[dict]):
        self.side = side  # "long" or "short"
        self.by_min: dict[datetime, dict] = {}
        self.has_quotes = False
        for bar in bars:
            self.by_min[bar["dt"]] = bar
            if bar["bid"] is not None and bar["ask"] is not None:
                self.has_quotes = True

    def minutes(self):
        return set(self.by_min)

    def bar(self, dt):
        return self.by_min.get(dt)


class Position:
    """A priced option position: one long leg, optionally one short leg."""

    def __init__(self, legs: list[Leg]):
        self.legs = legs
        self.long = next(l for l in legs if l.side == "long")
        self.short = next((l for l in legs if l.side == "short"), None)
        self.is_spread = self.short is not None
        self.n_legs = 2 if self.is_spread else 1
        self.has_quotes = all(l.has_quotes for l in legs)

    def all_minutes(self):
        return sorted(set().union(*(l.minutes() for l in self.legs)))

    # -- minute-level helpers ------------------------------------------------ #
    def _leg_vals(self, leg: Leg, dt):
        """Return (worst, best, vol_ok) for one leg's own price in minute dt."""
        bar = leg.bar(dt)
        if bar is None:
            return None
        vol_ok = bar["volume"] > 0
        if self.has_quotes and bar["bid"] is not None and bar["ask"] is not None:
            return (bar["bid"], bar["ask"], vol_ok)
        return (bar["low"], bar["high"], vol_ok)

    def entry_debit_at(self, dt) -> float | None:
        """Debit paid to open, using the unfavourable side of every leg.

        Long leg: pay the ASK (conservative: the bar HIGH).
        Short leg: receive the BID (conservative: the bar LOW).
        """
        lv = self._leg_vals(self.long, dt)
        if lv is None or not lv[2]:
            return None
        long_pay = lv[1]  # best->ask/high == worst case for the buyer
        if not self.is_spread:
            return long_pay
        sv = self._leg_vals(self.short, dt)
        if sv is None or not sv[2]:
            return None
        short_recv = sv[0]  # worst->bid/low == worst case for the seller
        debit = long_pay - short_recv
        return debit

    def liquidation_range_at(self, dt):
        """(low, high) liquidation value of the whole position in minute dt.

        Long leg liquidates at the BID (conservative: bar LOW..HIGH span).
        Short leg is bought back at the ASK (conservative: bar LOW..HIGH span).
        Returns None if any required leg lacks a positive-volume bar
        (spreads therefore need synchronized bars).
        """
        lv = self._leg_vals(self.long, dt)
        if lv is None or not lv[2]:
            return None
        long_lo, long_hi = lv[0], lv[1]
        if not self.is_spread:
            return (long_lo, long_hi)
        sv = self._leg_vals(self.short, dt)
        if sv is None or not sv[2]:
            return None
        short_lo, short_hi = sv[0], sv[1]
        # spread value = long - short ; buy back short at its high (worst)
        return (long_lo - short_hi, long_hi - short_lo)

    def synced_at(self, dt) -> bool:
        if not self.is_spread:
            b = self.long.bar(dt)
            return b is not None and b["volume"] > 0
        bl, bs = self.long.bar(dt), self.short.bar(dt)
        return (
            bl is not None
            and bs is not None
            and bl["volume"] > 0
            and bs["volume"] > 0
        )


# --------------------------------------------------------------------------- #
# Exit engine
# --------------------------------------------------------------------------- #
@dataclass
class TradeOutcome:
    outcome: str          # TARGET | STOP | TIME | NO_ENTRY | NO_OPTION_TRADE | UNKNOWN
    proof_tier: str
    entry_debit: float | None = None
    liquidation_value: float | None = None
    net_ret: float | None = None
    exit_minute: str | None = None
    exit_reason: str = ""
    note: str = ""


def _window_first_positive(position: Position, day_date, start: dtime, minutes: int):
    """First minute with a synced positive-volume bar in [start, start+minutes]."""
    lo = datetime.combine(day_date, start, tzinfo=PACIFIC)
    hi = lo + timedelta(minutes=minutes)
    for dt in position.all_minutes():
        if lo <= dt <= hi and position.synced_at(dt):
            return dt
    return None


def apply_exit_policy(
    position: Position,
    policy: dict,
    entry_debit: float,
    entry_dt: datetime,
    scheduled_exit_date,
) -> TradeOutcome:
    """Walk the position chronologically and apply one frozen exit policy."""
    tgt_pct = policy["target_pct"]
    stop_pct = policy["stop_pct"]
    base_tier = TIER_EXACT if position.has_quotes else TIER_CONS
    n_legs = position.n_legs

    sched_exit_dt = datetime.combine(scheduled_exit_date, ENTRY_TIME, tzinfo=PACIFIC)
    saw_synced = False
    possible_touch = False

    if tgt_pct is not None:
        target_val = entry_debit * (1.0 + tgt_pct)
        stop_val = entry_debit * (1.0 + stop_pct)
        for dt in position.all_minutes():
            if dt <= entry_dt or dt > sched_exit_dt:
                continue
            if not position.synced_at(dt):
                continue
            rng = position.liquidation_range_at(dt)
            if rng is None:
                continue
            saw_synced = True
            lo, hi = rng
            hit_stop = lo <= stop_val
            conf_target = lo >= target_val
            poss_target = (hi >= target_val) and not conf_target
            if hit_stop:
                note = (
                    "same-bar ambiguity resolved to STOP"
                    if (conf_target or poss_target)
                    else ""
                )
                return TradeOutcome(
                    "STOP", base_tier, entry_debit, stop_val,
                    net_return(entry_debit, stop_val, n_legs),
                    dt.isoformat(), "stop touched", note,
                )
            if conf_target:
                return TradeOutcome(
                    "TARGET", base_tier, entry_debit, target_val,
                    net_return(entry_debit, target_val, n_legs),
                    dt.isoformat(), "target filled (conservative)", "",
                )
            if poss_target:
                possible_touch = True
        if position.is_spread and not saw_synced:
            return TradeOutcome(
                "UNKNOWN", TIER_UNKNOWN, entry_debit, None, None, None,
                "no synchronized bars in holding window",
                "spread requires synchronized bars",
            )

    # scheduled fourth-session time exit -----------------------------------
    ex_dt = _window_first_positive(
        position, scheduled_exit_date, ENTRY_TIME, EXIT_WINDOW_MIN
    )
    if ex_dt is None:
        return TradeOutcome(
            "UNKNOWN", TIER_UNKNOWN, entry_debit, None, None, None,
            None, "no positive-volume bar in exit window",
        )
    rng = position.liquidation_range_at(ex_dt)
    if rng is None:
        return TradeOutcome(
            "UNKNOWN", TIER_UNKNOWN, entry_debit, None, None, None,
            None, "exit bar not synchronized",
        )
    exit_val = rng[0]  # LOW of the first positive-volume exit minute
    tier = TIER_POSS if possible_touch else base_tier
    reason = (
        "time exit (possible earlier target touch unconfirmed)"
        if possible_touch
        else "scheduled fourth-session time exit"
    )
    return TradeOutcome(
        "TIME", tier, entry_debit, exit_val,
        net_return(entry_debit, exit_val, n_legs),
        ex_dt.isoformat(), reason, "",
    )


# --------------------------------------------------------------------------- #
# Per-candidate evaluation
# --------------------------------------------------------------------------- #
def _contract_bars(contract: dict, data_root: Path, manifest: pd.DataFrame | None):
    """Resolve and load minute bars for one selected contract.

    Looks, in order, at an explicit ``bars_file`` on the contract, a
    ``bars_file`` column in the manifest, then ``<data_root>/<symbol>.{csv,json}``
    and ``<data_root>/yahoo/<symbol>*.json`` (the shape the capture lane writes).
    """
    sym = str(contract.get("contract_symbol") or contract.get("symbol")
              or contract.get("contract") or "")
    cand: list[Path] = []
    bf = contract.get("bars_file") or contract.get("file")
    if bf:
        bf = Path(bf)
        cand.append(bf if bf.is_absolute() else data_root / bf)
    if manifest is not None and sym:
        sym_col = next((c for c in ("contract_symbol", "contract", "symbol")
                        if c in manifest.columns), None)
        if sym_col is not None and "bars_file" in manifest.columns:
            for _, r in manifest[manifest[sym_col] == sym].iterrows():
                v = r.get("bars_file")
                if isinstance(v, str) and v:
                    p = Path(v)
                    cand.append(p if p.is_absolute() else data_root / p)
    if sym:
        cand.append(data_root / f"{sym}.csv")
        cand.append(data_root / f"{sym}.json")
        for sub in ("", "yahoo"):
            d = data_root / sub if sub else data_root
            if d.is_dir():
                cand.extend(sorted(d.glob(f"{sym}*.json")))
                cand.extend(sorted(d.glob(f"{sym}*.csv")))
    seen = set()
    for p in cand:
        if p in seen:
            continue
        seen.add(p)
        bars = load_bars(p)
        if bars:
            return bars, str(p)
    return [], (str(cand[0]) if cand else "")


def evaluate_candidate(
    structure_id: str,
    exit_policy: dict,
    stock_df: pd.DataFrame,
    dev_dates: set,
    eval_dates: set,
    data_root: Path,
    manifest: pd.DataFrame | None,
    select_fn,
    only_split: str | None = None,
    frozen_selections: dict | None = None,
    probe_index: dict | None = None,
) -> tuple[list[dict], dict]:
    """Return (rows, data_quality_bits) for one (structure, exit policy)."""
    rows: list[dict] = []
    pre_entry_dropped = 0
    n_no_chain = 0            # frozen rule cannot even NAME a contract
    n_named_no_bars = 0       # contract named, but no minute bars at all
    n_named_no_volume = 0     # bars exist but zero positive-volume minutes
    tier_counts: dict[str, int] = {t: 0 for t in
                                   (TIER_EXACT, TIER_CONS, TIER_POSS, TIER_UNKNOWN,
                                    "NO_OPTION_TRADE")}
    mf_view, mf_date_kind, mf_sym_col, mf_struct_col = manifest_join_view(manifest)
    if frozen_selections is None:
        frozen_selections = _FROZEN_SELECTIONS
    probe_index = probe_index or {}

    for _, tr in stock_df.iterrows():
        md, tkr = tr["market_date"], tr["ticker"]
        split = "development" if md in dev_dates else "evaluation"
        if only_split == "development" and split != "development":
            continue
        entry_date = datetime.strptime(tr["entry_date"], "%Y-%m-%d").date()
        exit_date = datetime.strptime(tr["exit_date"], "%Y-%m-%d").date()
        entry_dt = datetime.combine(entry_date, ENTRY_TIME, tzinfo=PACIFIC)
        row = {
            "structure_id": structure_id,
            "exit_policy": exit_policy["id"],
            "split": split,
            "market_date": md,
            "ticker": tkr,
            "rank": int(tr["rank"]),
            "entry_date": tr["entry_date"],
            "exit_date": tr["exit_date"],
            "stock_entry_px": float(tr["stock_entry_px"]),
            "contract_symbols": "",
            "n_legs": 1 if structure_id != "PUT_DEBIT_SPREAD" else 2,
            "entry_debit": "",
            "liquidation_value": "",
            "commission_round_trip": "",
            "net_return": "",
            "outcome": "",
            "exit_reason": "",
            "proof_tier": "",
            "exit_minute": "",
            "structures_collapsed": "false",
            "chain_source": "",
            "reason_code": "",
            "note": "",
        }

        # ---- name the contract(s) -------------------------------------------
        # Primary bridge: the selector lane's per-trade file, keyed on
        # (signal_date == market_date, ticker).  Fallback: a manifest that
        # actually carries a date key, fed to the shared selector.
        by_sig = frozen_selections.get("by_sig", {})
        sig_entry = by_sig.get((str(md), str(tkr)))
        contracts = None
        reject_reason = ""
        if sig_entry is not None:
            contracts = frozen_selection_contracts(sig_entry, structure_id)
            row["chain_source"] = "frozen-sample-selections"
            if not contracts:
                reject_reason = "frozen rule names no contract for this structure"
        elif mf_view is not None and mf_date_kind is not None:
            want_date = md if mf_date_kind == "market_date" else tr["entry_date"]
            sel = mf_view[(mf_view["_join_date"] == str(want_date))
                          & (mf_view["ticker"] == tkr)]
            if mf_struct_col is not None:
                sel = sel[sel[mf_struct_col].fillna("").str.contains(
                    structure_id, na=False) | sel[mf_struct_col].isna()]
            chain_rows = sel.to_dict("records")
            row["chain_source"] = "manifest+selector"
            if chain_rows:
                try:
                    result = select_fn(structure_id, chain_rows,
                                       float(tr["stock_entry_px"]),
                                       entry_date, exit_date)
                    contracts, reject_reason = normalize_selection(result)
                except Exception as exc:
                    contracts, reject_reason = None, f"selector error: {exc}"

        if sig_entry is None and row["chain_source"] != "manifest+selector":
            # No stored option chain at all -- the frozen rule cannot even name
            # a contract for this signal.  This is a different fact from a
            # contract that exists but 404s.
            n_no_chain += 1
            row.update(outcome="UNKNOWN", proof_tier=TIER_UNKNOWN,
                       chain_source="none", reason_code="no_stored_entry_chain",
                       note="no stored option chain for this signal; frozen rule "
                            "cannot name a contract")
            tier_counts[TIER_UNKNOWN] += 1
            rows.append(row)
            continue

        if not contracts:
            row.update(outcome="NO_OPTION_TRADE", proof_tier=TIER_UNKNOWN,
                       reason_code="selector_rejected",
                       note=reject_reason or "selector returned no contract")
            tier_counts["NO_OPTION_TRADE"] += 1
            rows.append(row)
            continue

        # C1: a spread whose two legs resolve to the same contract is nothing.
        if structure_id == "PUT_DEBIT_SPREAD" and len(contracts) == 2:
            a = str(contracts[0].get("contract_symbol") or contracts[0].get("symbol")
                    or contracts[0].get("contract") or "")
            b = str(contracts[1].get("contract_symbol") or contracts[1].get("symbol")
                    or contracts[1].get("contract") or "")
            if a and a == b:
                row.update(outcome="NO_OPTION_TRADE", proof_tier=TIER_UNKNOWN,
                           contract_symbols=a, reason_code="spread_legs_same_contract",
                           note="spread legs resolved to the same contract")
                tier_counts["NO_OPTION_TRADE"] += 1
                rows.append(row)
                continue

        syms_all = [str(c.get("contract_symbol") or c.get("symbol")
                        or c.get("contract") or "") for c in contracts]
        row["contract_symbols"] = "|".join(s for s in syms_all if s)

        # Contract named but provider has no data for it (expired -> HTTP 404).
        mstats = frozen_selections.get("_manifest_stats", {})
        probe = frozen_selections.get("probe_by_contract", {})
        miss_reasons = [contract_is_missing(s, mstats, probe) for s in syms_all if s]
        if any(miss_reasons):
            n_named_no_bars += 1
            row.update(outcome="UNKNOWN", proof_tier=TIER_UNKNOWN,
                       reason_code="expired_404",
                       note=next(r for r in miss_reasons if r))
            tier_counts[TIER_UNKNOWN] += 1
            rows.append(row)
            continue

        legs: list[Leg] = []
        missing = False
        for c in contracts:
            side = str(c.get("side", "long")).lower()
            bars, _ = _contract_bars(c, data_root, manifest)
            before = len(bars)
            bars = [b for b in bars if b["dt"] >= entry_dt]
            pre_entry_dropped += before - len(bars)
            if not bars:
                missing = True
            legs.append(Leg(side, bars))

        if missing or not any(l.side == "long" for l in legs):
            n_named_no_bars += 1
            row.update(outcome="UNKNOWN", proof_tier=TIER_UNKNOWN,
                       reason_code="no_bar_file",
                       note="contract named but no minute bar file found")
            tier_counts[TIER_UNKNOWN] += 1
            rows.append(row)
            continue

        position = Position(legs)
        ent_dt = _window_first_positive(
            position, entry_date, ENTRY_TIME, ENTRY_WINDOW_MIN
        )
        if ent_dt is None:
            n_named_no_volume += 1
            row.update(outcome="NO_ENTRY", proof_tier=TIER_UNKNOWN,
                       reason_code="no_positive_volume_bar",
                       note="no positive-volume bar in 06:35-06:40 entry window")
            tier_counts[TIER_UNKNOWN] += 1
            rows.append(row)
            continue
        entry_debit = position.entry_debit_at(ent_dt)
        if entry_debit is None or entry_debit <= 0:
            row.update(outcome="NO_OPTION_TRADE", proof_tier=TIER_UNKNOWN,
                       reason_code="zero_or_negative_entry_debit",
                       note="zero or negative entry debit")
            tier_counts["NO_OPTION_TRADE"] += 1
            rows.append(row)
            continue

        out = apply_exit_policy(position, exit_policy, entry_debit, ent_dt, exit_date)
        row.update(
            entry_debit=round(entry_debit, 6),
            liquidation_value=("" if out.liquidation_value is None
                               else round(out.liquidation_value, 6)),
            commission_round_trip=round(
                commission_round_trip_per_share(position.n_legs) * 100.0, 2),
            net_return=("" if out.net_ret is None else round(out.net_ret, 8)),
            outcome=out.outcome,
            exit_reason=out.exit_reason,
            proof_tier=out.proof_tier,
            exit_minute=out.exit_minute or "",
            note=out.note,
        )
        tier_counts[out.proof_tier] = tier_counts.get(out.proof_tier, 0) + 1
        rows.append(row)

    return rows, {"pre_entry_bars_dropped": pre_entry_dropped,
                  "tier_counts": tier_counts,
                  "signals_no_stored_chain": n_no_chain,
                  "signals_named_but_no_bars": n_named_no_bars,
                  "signals_named_but_no_volume": n_named_no_volume}


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def _resolved(rows: list[dict]) -> list[dict]:
    return [r for r in rows
            if r["proof_tier"] in RESOLVED_TIERS and r["net_return"] != ""]


def _by_date(rows: list[dict], key="net_return") -> dict:
    out: dict[str, list[float]] = {}
    for r in rows:
        if r[key] == "":
            continue
        out.setdefault(r["market_date"], []).append(float(r[key]))
    return out


def profit_factor(vals) -> float:
    vals = [float(v) for v in vals]
    gains = sum(v for v in vals if v > 0)
    losses = -sum(v for v in vals if v < 0)
    if losses == 0:
        return math.inf if gains > 0 else float("nan")
    return gains / losses


def date_clustered_bootstrap(values_by_date: dict, stat_fn, n=BOOTSTRAP_N,
                             seed=BOOTSTRAP_SEED):
    dates = list(values_by_date)
    if not dates:
        return (float("nan"), float("nan"), float("nan"))
    arrs = [np.asarray(values_by_date[d], dtype=float) for d in dates]
    pooled_all = np.concatenate(arrs)
    point = float(stat_fn(pooled_all))
    k = len(dates)
    rng = np.random.default_rng(seed)
    stats = np.empty(n, dtype=float)
    for i in range(n):
        pick = rng.integers(0, k, k)
        pooled = np.concatenate([arrs[j] for j in pick])
        stats[i] = stat_fn(pooled)
    lo, hi = np.nanpercentile(stats, [2.5, 97.5])
    return (float(lo), float(hi), point)


def _mean(a):
    return float(np.mean(a)) if len(a) else float("nan")


def _winrate(a):
    return float(np.mean(np.asarray(a) > 0)) if len(a) else float("nan")


def candidate_metrics(rows: list[dict], seed=BOOTSTRAP_SEED) -> dict:
    res = _resolved(rows)
    vals = [float(r["net_return"]) for r in res]
    dates = sorted({r["market_date"] for r in res})
    stocks = sorted({r["ticker"] for r in res})
    bd = _by_date(res)
    avg_lo, avg_hi, avg_pt = date_clustered_bootstrap(bd, _mean, seed=seed)
    wr_lo, wr_hi, wr_pt = date_clustered_bootstrap(bd, _winrate, seed=seed)

    halves = {"earlier": float("nan"), "later": float("nan")}
    if len(dates) >= 2:
        mid = dates[len(dates) // 2]
        early = [v for r in res if r["market_date"] < mid
                 for v in [float(r["net_return"])]]
        late = [v for r in res if r["market_date"] >= mid
                for v in [float(r["net_return"])]]
        halves = {"earlier": _mean(early) if early else float("nan"),
                  "later": _mean(late) if late else float("nan")}

    tier_counts: dict[str, int] = {}
    for r in rows:
        tier_counts[r["proof_tier"]] = tier_counts.get(r["proof_tier"], 0) + 1
    outcome_counts: dict[str, int] = {}
    for r in rows:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1

    return {
        "n_signals": len(rows),
        "n_resolved": len(res),
        "n_structures_collapsed": sum(1 for r in rows
                                      if r.get("structures_collapsed") == "true"),
        "n_signal_dates_resolved": len(dates),
        "n_stocks_resolved": len(stocks),
        "avg_net_return": avg_pt,
        "avg_net_return_ci95": [avg_lo, avg_hi],
        "win_rate": wr_pt,
        "win_rate_ci95": [wr_lo, wr_hi],
        "profit_factor": profit_factor(vals),
        "halves": halves,
        "tier_counts": tier_counts,
        "outcome_counts": outcome_counts,
        "seed": seed,
    }


# --------------------------------------------------------------------------- #
# Portfolio simulation (G9)
# --------------------------------------------------------------------------- #
def simulate_portfolio(rows: list[dict], gate: dict):
    start = float(gate["starting_capital_usd"])
    max_frac = float(gate["max_premium_fraction_per_position"])
    max_open = int(gate["max_open_positions"])
    cap_per_pos = start * max_frac

    trades = []
    for r in _resolved(rows):
        entry_debit = float(r["entry_debit"])
        contracts = int(cap_per_pos // (entry_debit * 100.0))
        if contracts < 1:
            trades.append({"date": r["entry_date"], "reject": "premium_cap_exceeded",
                           "ticker": r["ticker"]})
            continue
        trades.append({
            "ticker": r["ticker"],
            "entry_date": r["entry_date"],
            "exit_date": r["exit_date"],
            "contracts": contracts,
            "premium": contracts * entry_debit * 100.0,
            "pnl": contracts * float(r["net_return"]) * entry_debit * 100.0,
        })

    events: dict[str, dict] = {}
    overflow = []
    open_positions: list[dict] = []
    realized = 0.0
    equity_curve: list[dict] = []

    dates = sorted({t.get("entry_date") for t in trades if "entry_date" in t}
                   | {t.get("exit_date") for t in trades if "exit_date" in t}
                   | {t["date"] for t in trades if "date" in t})
    for d in dates:
        # close first
        still_open = []
        for p in open_positions:
            if p["exit_date"] <= d:
                realized += p["pnl"]
            else:
                still_open.append(p)
        open_positions = still_open
        # then open
        for t in trades:
            if t.get("entry_date") != d:
                continue
            if len(open_positions) >= max_open:
                overflow.append({"date": d, "ticker": t["ticker"],
                                 "reason": "max_open_positions"})
                continue
            open_positions.append(t)
        deployed = sum(p["premium"] for p in open_positions)
        equity = start + realized
        equity_curve.append({
            "date": d,
            "open_positions": len(open_positions),
            "deployed_premium": round(deployed, 2),
            "realized_pnl_cum": round(realized, 2),
            "equity": round(equity, 2),
        })

    # drain remaining
    for p in open_positions:
        realized += p["pnl"]
    if equity_curve:
        equity_curve.append({
            "date": "FINAL",
            "open_positions": 0,
            "deployed_premium": 0.0,
            "realized_pnl_cum": round(realized, 2),
            "equity": round(start + realized, 2),
        })

    eq = [e["equity"] for e in equity_curve]
    max_dd = 0.0
    peak = start
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak else 0.0)
    final_equity = eq[-1] if eq else start
    n_real = sum(1 for t in trades if "pnl" in t)
    return {
        "n_positions": n_real,
        "n_premium_cap_rejections": sum(1 for t in trades
                                        if t.get("reject") == "premium_cap_exceeded"),
        "n_overflow_rejections": len(overflow),
        "overflow_rejections": overflow,
        "max_drawdown": max_dd,
        "final_equity": final_equity,
        "positive_finish": final_equity > start,
        "equity_curve": equity_curve,
    }


# --------------------------------------------------------------------------- #
# Concentration (G8) + overlap-suppressed (G11) + timing (G10)
# --------------------------------------------------------------------------- #
def concentration(rows: list[dict]) -> dict:
    res = _resolved(rows)
    pos = [(r, float(r["net_return"])) for r in res if float(r["net_return"]) > 0]
    total = sum(v for _, v in pos)
    if total <= 0:
        return {"total_profit": total, "max_date_share": float("nan"),
                "max_ticker_share": float("nan"), "by_date": {}, "by_ticker": {}}
    by_date: dict[str, float] = {}
    by_ticker: dict[str, float] = {}
    for r, v in pos:
        by_date[r["market_date"]] = by_date.get(r["market_date"], 0.0) + v
        by_ticker[r["ticker"]] = by_ticker.get(r["ticker"], 0.0) + v
    ds = {k: v / total for k, v in by_date.items()}
    ts = {k: v / total for k, v in by_ticker.items()}
    return {
        "total_profit": total,
        "max_date_share": max(ds.values()),
        "max_ticker_share": max(ts.values()),
        "by_date": dict(sorted(ds.items(), key=lambda x: -x[1])),
        "by_ticker": dict(sorted(ts.items(), key=lambda x: -x[1])),
    }


def overlap_suppressed(rows: list[dict]) -> dict:
    res = sorted(_resolved(rows), key=lambda r: (r["entry_date"], r["ticker"]))
    kept, open_by_ticker = [], {}
    suppressed = 0
    for r in res:
        prev_exit = open_by_ticker.get(r["ticker"])
        if prev_exit is not None and r["entry_date"] <= prev_exit:
            suppressed += 1
            continue
        kept.append(r)
        open_by_ticker[r["ticker"]] = r["exit_date"]
    vals = [float(r["net_return"]) for r in kept]
    bd = _by_date(kept)
    lo, hi, pt = date_clustered_bootstrap(bd, _mean)
    return {
        "n_kept": len(kept),
        "n_suppressed": suppressed,
        "avg_net_return": pt,
        "avg_net_return_ci95": [lo, hi],
        "profit_factor": profit_factor(vals),
        "still_positive": (not math.isnan(pt)) and pt > 0,
    }


def timing_sensitivity(
    structure_id, exit_policy, stock_df, dev_dates, eval_dates,
    data_root, manifest, select_fn, entries=("06:35", "06:40", "06:45"),
) -> dict:
    """Re-run the candidate with the entry window starting at each time."""
    global ENTRY_TIME
    saved = ENTRY_TIME
    result = {}
    try:
        for label in entries:
            hh, mm = label.split(":")
            ENTRY_TIME = dtime(int(hh), int(mm))
            rows, _ = evaluate_candidate(
                structure_id, exit_policy, stock_df, dev_dates, eval_dates,
                data_root, manifest, select_fn,
            )
            res = _resolved(rows)
            vals = [float(r["net_return"]) for r in res]
            bd = _by_date(res)
            lo, hi, pt = date_clustered_bootstrap(bd, _mean)
            result[label] = {
                "n_resolved": len(res),
                "avg_net_return": pt,
                "avg_net_return_ci95_lo": lo,
                "profit_factor": profit_factor(vals),
                "positive": (not math.isnan(pt)) and pt > 0,
            }
    finally:
        ENTRY_TIME = saved
    base = result.get("06:35", {})
    neighbours = [v for k, v in result.items() if k != "06:35"]
    neigh_ok = any(
        nb.get("positive") and (nb.get("profit_factor") or 0) > 1.0
        for nb in neighbours
    )
    result["_summary"] = {
        "base_positive": bool(base.get("positive")),
        "base_profit_factor": base.get("profit_factor"),
        "at_least_one_neighbour_pf_gt_1": neigh_ok,
    }
    return result


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
def _fmt(x):
    if x is None:
        return None
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        if math.isinf(x):
            return "inf"
        return round(x, 8)
    return x


def _borderline(actual, threshold):
    if threshold in (0, None) or actual is None or math.isnan(actual):
        return False
    return abs(actual - threshold) / abs(threshold) <= BORDERLINE_FRAC


def _seed_spread(rows, stat, threshold_side_fn):
    bounds = []
    for s in BORDERLINE_SEEDS:
        bd = _by_date(_resolved(rows))
        lo, hi, pt = date_clustered_bootstrap(bd, stat, seed=s)
        bounds.append({"seed": s, "lo": _fmt(lo), "hi": _fmt(hi), "point": _fmt(pt)})
    los = [b["lo"] for b in bounds if isinstance(b["lo"], (int, float))]
    return {"per_seed": bounds,
            "lo_min": _fmt(min(los)) if los else None,
            "lo_max": _fmt(max(los)) if los else None}


def evaluate_gates(policy, chosen_key, dev_rows, eval_rows, full_rows,
                   dev_metrics, eval_metrics, portfolio, conc, timing, overlap):
    g = policy["gates"]
    gates = []

    def add(gid, verdict, actual, threshold, detail, extra=None):
        entry = {"id": gid, "verdict": verdict, "actual": actual,
                 "threshold": threshold, "detail": detail}
        if extra:
            entry.update(extra)
        gates.append(entry)

    full_res = _resolved(full_rows)
    n_elig = len(full_res)
    n_dates = len({r["market_date"] for r in full_res})
    n_stocks = len({r["ticker"] for r in full_res})
    g1 = g["G1_full_sample_size"]
    if n_elig == 0:
        add("G1_full_sample_size", "INSUFFICIENT DATA",
            {"eligible": 0, "signal_dates": 0, "stocks": 0},
            {"min_eligible_trades": g1["min_eligible_trades"],
             "min_signal_dates": g1["min_signal_dates"],
             "min_stocks": g1["min_stocks"]},
            "no eligible option trades in the full sample")
    else:
        ok = (n_elig >= g1["min_eligible_trades"] and n_dates >= g1["min_signal_dates"]
              and n_stocks >= g1["min_stocks"])
        add("G1_full_sample_size", "PASS" if ok else "FAIL",
            {"eligible": n_elig, "signal_dates": n_dates, "stocks": n_stocks},
            {"min_eligible_trades": g1["min_eligible_trades"],
             "min_signal_dates": g1["min_signal_dates"],
             "min_stocks": g1["min_stocks"]},
            "full eligible sample size")

    ev_res = _resolved(eval_rows)
    e_elig = len(ev_res)
    e_dates = len({r["market_date"] for r in ev_res})
    e_stocks = len({r["ticker"] for r in ev_res})
    g2 = g["G2_evaluation_size"]
    ok2 = (e_elig >= g2["min_eligible_trades"] and e_dates >= g2["min_signal_dates"]
           and e_stocks >= g2["min_stocks"])
    add("G2_evaluation_size", "PASS" if ok2 else "INSUFFICIENT DATA",
        {"eligible": e_elig, "signal_dates": e_dates, "stocks": e_stocks},
        {"min_eligible_trades": g2["min_eligible_trades"],
         "min_signal_dates": g2["min_signal_dates"],
         "min_stocks": g2["min_stocks"]},
        "untouched evaluation sample size; never PASS on failure")

    def both_present():
        return dev_metrics is not None and eval_metrics is not None

    # G3 avg net return positive (both)
    if not both_present():
        add("G3_avg_net_return_positive", "PENDING EVALUATION", None, "> 0",
            "needs both splits")
    else:
        da, ea = dev_metrics["avg_net_return"], eval_metrics["avg_net_return"]
        ok = (not math.isnan(da) and da > 0) and (not math.isnan(ea) and ea > 0)
        v = "PASS" if ok else ("INSUFFICIENT DATA" if math.isnan(da) or math.isnan(ea)
                               else "FAIL")
        add("G3_avg_net_return_positive", v,
            {"development": _fmt(da), "evaluation": _fmt(ea)}, "> 0 in both",
            "average net return positive in both splits")

    # G4 date-grouped 95% range above zero (both)
    if not both_present():
        add("G4_date_grouped_95_range_above_zero", "PENDING EVALUATION", None, "> 0",
            "needs both splits")
    else:
        dlo = dev_metrics["avg_net_return_ci95"][0]
        elo = eval_metrics["avg_net_return_ci95"][0]
        ok = (not math.isnan(dlo) and dlo > 0) and (not math.isnan(elo) and elo > 0)
        v = "PASS" if ok else ("INSUFFICIENT DATA"
                               if math.isnan(dlo) or math.isnan(elo) else "FAIL")
        extra = {}
        if _borderline(dlo, 0) or _borderline(elo, 0) or v == "FAIL":
            extra["seed_sensitivity"] = {
                "development": _seed_spread(dev_rows, _mean, None),
                "evaluation": _seed_spread(eval_rows, _mean, None),
            }
        add("G4_date_grouped_95_range_above_zero", v,
            {"development_lo95": _fmt(dlo), "evaluation_lo95": _fmt(elo)},
            "lower 95% bound > 0 in both",
            "date-clustered bootstrap lower bound above zero", extra)

    # G5 win rate (both)
    g5 = g["G5_win_rate"]
    if not both_present():
        add("G5_win_rate", "PENDING EVALUATION", None,
            {"min_win_rate": g5["min_win_rate"],
             "min_lower_95_win_rate": g5["min_lower_95_win_rate"]},
            "needs both splits")
    else:
        dwr, ewr = dev_metrics["win_rate"], eval_metrics["win_rate"]
        dlo = dev_metrics["win_rate_ci95"][0]
        elo = eval_metrics["win_rate_ci95"][0]
        ok = (all(not math.isnan(x) for x in (dwr, ewr, dlo, elo))
              and dwr >= g5["min_win_rate"] and ewr >= g5["min_win_rate"]
              and dlo >= g5["min_lower_95_win_rate"]
              and elo >= g5["min_lower_95_win_rate"])
        v = "PASS" if ok else ("INSUFFICIENT DATA"
                               if any(math.isnan(x) for x in (dwr, ewr)) else "FAIL")
        extra = {}
        if any(_borderline(x, g5["min_win_rate"]) for x in (dwr, ewr)) or \
           any(_borderline(x, g5["min_lower_95_win_rate"]) for x in (dlo, elo)):
            extra["seed_sensitivity"] = {
                "development": _seed_spread(dev_rows, _winrate, None),
                "evaluation": _seed_spread(eval_rows, _winrate, None),
            }
        add("G5_win_rate", v,
            {"development_win_rate": _fmt(dwr), "evaluation_win_rate": _fmt(ewr),
             "development_lo95": _fmt(dlo), "evaluation_lo95": _fmt(elo)},
            {"min_win_rate": g5["min_win_rate"],
             "min_lower_95_win_rate": g5["min_lower_95_win_rate"]},
            "win rate and its lower bound clear the floor in both splits", extra)

    # G6 profit factor (both)
    g6 = g["G6_profit_factor"]
    if not both_present():
        add("G6_profit_factor", "PENDING EVALUATION", None, {"min": g6["min"]},
            "needs both splits")
    else:
        dpf, epf = dev_metrics["profit_factor"], eval_metrics["profit_factor"]
        ok = (all(not math.isnan(x) for x in (dpf, epf))
              and dpf >= g6["min"] and epf >= g6["min"])
        v = "PASS" if ok else ("INSUFFICIENT DATA"
                               if any(math.isnan(x) for x in (dpf, epf)) else "FAIL")
        add("G6_profit_factor", v,
            {"development": _fmt(dpf), "evaluation": _fmt(epf)},
            {"min": g6["min"]}, "profit factor in both splits")

    # G7 halves positive (both)
    if not both_present():
        add("G7_halves_positive", "PENDING EVALUATION", None, "> 0",
            "needs both splits")
    else:
        dh, eh = dev_metrics["halves"], eval_metrics["halves"]
        vals = [dh["earlier"], dh["later"], eh["earlier"], eh["later"]]
        ok = all((not math.isnan(x)) and x > 0 for x in vals)
        v = "PASS" if ok else ("INSUFFICIENT DATA"
                               if any(math.isnan(x) for x in vals) else "FAIL")
        add("G7_halves_positive", v,
            {"development": {k: _fmt(x) for k, x in dh.items()},
             "evaluation": {k: _fmt(x) for k, x in eh.items()}},
            "> 0 in the earlier and later half of both splits",
            "both halves of both splits positive")

    # G8 concentration
    g8 = g["G8_concentration"]
    if conc is None or math.isnan(conc.get("max_date_share", float("nan"))):
        add("G8_concentration", "INSUFFICIENT DATA",
            {"max_date_share": None, "max_ticker_share": None},
            {"max_share_per_signal_date": g8["max_share_of_total_profit_per_signal_date"],
             "max_share_per_ticker": g8["max_share_of_total_profit_per_ticker"]},
            "no positive profit to concentrate")
    else:
        ok = (conc["max_date_share"] <= g8["max_share_of_total_profit_per_signal_date"]
              and conc["max_ticker_share"] <= g8["max_share_of_total_profit_per_ticker"])
        add("G8_concentration", "PASS" if ok else "FAIL",
            {"max_date_share": _fmt(conc["max_date_share"]),
             "max_ticker_share": _fmt(conc["max_ticker_share"])},
            {"max_share_per_signal_date": g8["max_share_of_total_profit_per_signal_date"],
             "max_share_per_ticker": g8["max_share_of_total_profit_per_ticker"]},
            "no single signal date or ticker owns too much of the profit")

    # G9 portfolio
    g9 = g["G9_portfolio"]
    if portfolio is None or portfolio["n_positions"] == 0:
        add("G9_portfolio", "INSUFFICIENT DATA",
            {"n_positions": 0 if portfolio is None else portfolio["n_positions"]},
            {"max_drawdown": g9["max_drawdown"],
             "max_open_positions": g9["max_open_positions"],
             "max_premium_fraction_per_position": g9["max_premium_fraction_per_position"],
             "starting_capital_usd": g9["starting_capital_usd"]},
            "no priced positions for the overlapping portfolio")
    else:
        ok = (portfolio["max_drawdown"] <= g9["max_drawdown"]
              and portfolio["positive_finish"])
        add("G9_portfolio", "PASS" if ok else "FAIL",
            {"max_drawdown": _fmt(portfolio["max_drawdown"]),
             "final_equity": _fmt(portfolio["final_equity"]),
             "positive_finish": portfolio["positive_finish"],
             "n_positions": portfolio["n_positions"],
             "n_overflow_rejections": portfolio["n_overflow_rejections"]},
            {"max_drawdown": g9["max_drawdown"],
             "max_open_positions": g9["max_open_positions"],
             "max_premium_fraction_per_position": g9["max_premium_fraction_per_position"],
             "require_positive_finish": True,
             "starting_capital_usd": g9["starting_capital_usd"]},
            "$100k overlapping portfolio stays within the drawdown cap and finishes up")

    # G10 timing sensitivity
    if timing is None or timing.get("_summary", {}).get("base_profit_factor") is None:
        add("G10_timing_sensitivity", "INSUFFICIENT DATA", None,
            "06:35 passes AND >=1 neighbour PF>1.0",
            "no resolved trades at 06:35")
    else:
        s = timing["_summary"]
        ok = s["base_positive"] and s["at_least_one_neighbour_pf_gt_1"]
        add("G10_timing_sensitivity", "PASS" if ok else "FAIL",
            {"base_positive": s["base_positive"],
             "base_profit_factor": _fmt(s["base_profit_factor"]),
             "neighbour_pf_gt_1": s["at_least_one_neighbour_pf_gt_1"],
             "rows": {k: {"avg_net_return": _fmt(v["avg_net_return"]),
                          "profit_factor": _fmt(v["profit_factor"])}
                      for k, v in timing.items() if k != "_summary"}},
            "06:35 passes AND at least one neighbour positive with PF>1.0",
            "production timing stays at 06:35 regardless of the best row")

    # G11 overlap suppressed
    if overlap is None or overlap["n_kept"] == 0:
        add("G11_overlap_suppressed", "INSUFFICIENT DATA", None, "still positive",
            "no resolved trades after suppression")
    else:
        add("G11_overlap_suppressed",
            "PASS" if overlap["still_positive"] else "FAIL",
            {"avg_net_return": _fmt(overlap["avg_net_return"]),
             "n_kept": overlap["n_kept"], "n_suppressed": overlap["n_suppressed"]},
            "average net return still > 0",
            "still positive when overlapping repeat signals in the same ticker "
            "are suppressed")

    # G12 proof tier
    tier_all: dict[str, int] = {}
    for r in full_rows:
        tier_all[r["proof_tier"]] = tier_all.get(r["proof_tier"], 0) + 1
    exact_n = tier_all.get(TIER_EXACT, 0)
    cons_n = tier_all.get(TIER_CONS, 0)
    if exact_n == 0 and cons_n == 0:
        add("G12_proof_tier", "INSUFFICIENT DATA", tier_all,
            "historical bid/ask OR verified conservative model + forward Schwab bid",
            "no resolved outcomes on any promotion-grade tier")
    elif exact_n > 0:
        add("G12_proof_tier", "PASS", tier_all,
            "historical bid/ask present",
            "outcomes rest on real historical bid/ask quotes")
    else:
        add("G12_proof_tier", "FAIL", tier_all,
            "historical bid/ask OR verified conservative model + forward Schwab bid",
            "conservative trade-bar only; needs independent verification plus "
            "forward Schwab bid evidence before PASS (verdict caps at PROVISIONAL)")

    return gates


def overall_verdict(gates: list[dict]) -> str:
    by_id = {g["id"]: g["verdict"] for g in gates}
    if by_id.get("G1_full_sample_size") == "INSUFFICIENT DATA" or \
       by_id.get("G2_evaluation_size") == "INSUFFICIENT DATA":
        return "INSUFFICIENT DATA"
    verdicts = set(by_id.values())
    if verdicts <= {"PASS"}:
        return "PASS"
    non_g12 = {k: v for k, v in by_id.items() if k != "G12_proof_tier"}
    if set(non_g12.values()) <= {"PASS"} and by_id.get("G12_proof_tier") == "FAIL":
        return "PROVISIONAL — LIVE BID CONFIRMATION REQUIRED"
    if "INSUFFICIENT DATA" in verdicts and "FAIL" not in verdicts:
        return "INSUFFICIENT DATA"
    return "REJECTED"


# --------------------------------------------------------------------------- #
# Choice + lock
# --------------------------------------------------------------------------- #
def dev_gate_pass(policy, dev_metrics, full_rows, timing, overlap) -> tuple[bool, dict]:
    """Development-side gate check used by --choose (no evaluation inspection)."""
    g = policy["gates"]
    checks = {}
    m = dev_metrics
    checks["G3_dev_avg_positive"] = (not math.isnan(m["avg_net_return"])
                                     and m["avg_net_return"] > 0)
    checks["G4_dev_lo95_above_zero"] = (not math.isnan(m["avg_net_return_ci95"][0])
                                        and m["avg_net_return_ci95"][0] > 0)
    g5 = g["G5_win_rate"]
    checks["G5_dev_win_rate"] = (not math.isnan(m["win_rate"])
                                 and m["win_rate"] >= g5["min_win_rate"]
                                 and m["win_rate_ci95"][0] >= g5["min_lower_95_win_rate"])
    checks["G6_dev_profit_factor"] = (not math.isnan(m["profit_factor"])
                                      and m["profit_factor"] >= g["G6_profit_factor"]["min"])
    h = m["halves"]
    checks["G7_dev_halves"] = all((not math.isnan(x)) and x > 0
                                  for x in (h["earlier"], h["later"]))
    conc = concentration(full_rows)
    g8 = g["G8_concentration"]
    checks["G8_concentration"] = (
        not math.isnan(conc.get("max_date_share", float("nan")))
        and conc["max_date_share"] <= g8["max_share_of_total_profit_per_signal_date"]
        and conc["max_ticker_share"] <= g8["max_share_of_total_profit_per_ticker"]
    )
    if timing is not None and timing.get("_summary", {}).get("base_profit_factor") \
            is not None:
        s = timing["_summary"]
        checks["G10_timing"] = bool(s["base_positive"]
                                    and s["at_least_one_neighbour_pf_gt_1"])
    else:
        checks["G10_timing"] = False
    checks["G11_overlap"] = bool(overlap and overlap["still_positive"])
    return all(checks.values()), checks


def choose_rule(policy, dev_summary: dict) -> dict:
    """Apply the frozen development_choice_order to the dev-passing candidates."""
    trace = []
    pool = [k for k, v in dev_summary.items() if v["passes_all_dev_gates"]]
    trace.append({"step": "passes all development gates",
                  "remaining": sorted(pool)})
    if not pool:
        return {"chosen": None, "selection_trace": trace,
                "reason": "no candidate passes every development gate"}

    def struct_rank(key):
        return STRUCTURE_ORDER.index(dev_summary[key]["structure_id"])

    def exit_rank(key):
        return EXIT_ORDER.index(dev_summary[key]["exit_policy"])

    # 2. highest date-grouped conservative lower estimate of avg net return
    best = max(dev_summary[k]["metrics"]["avg_net_return_ci95"][0] for k in pool)
    pool = [k for k in pool
            if math.isclose(dev_summary[k]["metrics"]["avg_net_return_ci95"][0], best,
                            rel_tol=0, abs_tol=1e-12)]
    trace.append({"step": "highest date-grouped lower estimate of avg net return",
                  "value": _fmt(best), "remaining": sorted(pool)})
    if len(pool) > 1:
        best = max(dev_summary[k]["metrics"]["win_rate_ci95"][0] for k in pool)
        pool = [k for k in pool
                if math.isclose(dev_summary[k]["metrics"]["win_rate_ci95"][0], best,
                                rel_tol=0, abs_tol=1e-12)]
        trace.append({"step": "higher conservative lower estimate of win rate",
                      "value": _fmt(best), "remaining": sorted(pool)})
    if len(pool) > 1:
        best = max(dev_summary[k]["metrics"]["profit_factor"] for k in pool)
        pool = [k for k in pool
                if math.isclose(dev_summary[k]["metrics"]["profit_factor"], best,
                                rel_tol=0, abs_tol=1e-12)]
        trace.append({"step": "higher profit factor", "value": _fmt(best),
                      "remaining": sorted(pool)})
    if len(pool) > 1:
        r = min(struct_rank(k) for k in pool)
        pool = [k for k in pool if struct_rank(k) == r]
        trace.append({"step": "simpler structure: long PUT before spread",
                      "remaining": sorted(pool)})
    if len(pool) > 1:
        r = min(exit_rank(k) for k in pool)
        pool = [k for k in pool if exit_rank(k) == r]
        trace.append({"step": "simpler exit: TIME_ONLY, then PT25_SL35, then PT50_SL35",
                      "remaining": sorted(pool)})
    chosen_key = sorted(pool)[0]
    return {
        "chosen": {
            "structure_id": dev_summary[chosen_key]["structure_id"],
            "exit_policy_id": dev_summary[chosen_key]["exit_policy"],
            "candidate_key": chosen_key,
        },
        "selection_trace": trace,
    }


def candidate_key(structure_id, exit_policy_id):
    return f"{structure_id}__{exit_policy_id}"


CHOSEN_FILE = "chosen-development-rule.json"


def require_evaluation_unlocked(out_dir: Path) -> dict:
    crj = out_dir / CHOSEN_FILE
    sha = out_dir / (CHOSEN_FILE + ".sha256")
    if not crj.exists() or not sha.exists():
        raise SystemExit(
            "EVALUATION SPLIT LOCKED: "
            f"{CHOSEN_FILE} and its .sha256 must both exist first "
            "(run --choose). Refusing to inspect the evaluation split."
        )
    want = sha.read_text().split()[0].strip().lower()
    got = sha256_file(crj).lower()
    if want != got:
        raise SystemExit(
            f"EVALUATION SPLIT LOCKED: {CHOSEN_FILE} does not match its .sha256 "
            f"(expected {want}, actual {got}). Refusing to proceed."
        )
    doc = json.loads(crj.read_text())
    if doc.get("chosen") in (None, {}, ""):
        raise SystemExit(
            f"EVALUATION SPLIT LOCKED: {CHOSEN_FILE} has chosen=null -- no "
            "development rule was promoted, so the untouched evaluation split "
            "stays closed. (Use --split full for the full-sample gate counts.)"
        )
    return doc


# --------------------------------------------------------------------------- #
# Join proof / data quality
# --------------------------------------------------------------------------- #
class BrokenJoin(RuntimeError):
    """The download manifest could not be joined to the frozen sample."""


def prove_join(stock_df: pd.DataFrame, manifest: pd.DataFrame | None,
               frozen_selections: dict | None = None) -> dict:
    """Join the download manifest to the frozen stock trades via
    frozen-sample-selections.json and report the coverage honestly.

    Bridge: frozen stock trade (market_date == signal_date, ticker)
            -> per_trade entry -> OCC symbol -> manifest contract row.
    """
    fs = frozen_selections if frozen_selections is not None else _FROZEN_SELECTIONS
    by_sig = fs.get("by_sig", {})
    mstats = fs.get("_manifest_stats", {})
    probe = fs.get("probe_by_contract", {})
    stock_keys = set(zip(stock_df["market_date"].astype(str),
                         stock_df["ticker"].astype(str)))

    out = {
        "stock_trades": int(len(stock_df)),
        "bridge_file": FROZEN_SELECTIONS_PATH.name,
        "bridge_present": bool(fs.get("present")),
        "manifest_present": manifest is not None,
        "manifest_rows": 0 if manifest is None else int(len(manifest)),
        "one_to_one_ok": True,
    }

    # Which frozen stock trades did the bridge name a contract for?
    bridged = [k for k in stock_keys if k in by_sig]
    unbridged = [k for k in stock_keys if k not in by_sig]
    out["matched_groups"] = len(bridged)
    out["bridged_signal_dates"] = len({d for d, _ in bridged})
    out["bridged_stocks"] = len({t for _, t in bridged})

    # Every OCC symbol the bridge names for a bridged trade.
    bridged_occ = set()
    for k in bridged:
        for blk in (by_sig[k].get("contracts") or {}).values():
            for leg in blk.values():
                if leg.get("occ_symbol"):
                    bridged_occ.add(str(leg["occ_symbol"]))

    # Reason split for the trades that yield no usable option.
    reason_split = {"no_stored_entry_chain": len(unbridged),
                    "expired_404": 0, "has_data": 0}
    for k in bridged:
        occ = set()
        for blk in (by_sig[k].get("contracts") or {}).values():
            for leg in blk.values():
                if leg.get("occ_symbol"):
                    occ.add(str(leg["occ_symbol"]))
        any_missing = any(contract_is_missing(s, mstats, probe) for s in occ)
        if occ and any_missing:
            reason_split["expired_404"] += 1
        elif occ:
            reason_split["has_data"] += 1
    out["unjoined_reason_split"] = reason_split

    # Manifest-row join rate (the loud-failure guard).
    if manifest is not None:
        sym_col = next((c for c in ("contract", "contract_symbol", "symbol")
                        if c in manifest.columns), None)
        if sym_col is not None:
            m_syms = manifest[sym_col].dropna().astype(str)
            joined = int(m_syms.isin(bridged_occ).sum())
            out["manifest_rows_joined"] = joined
            out["manifest_join_fraction"] = round(
                joined / max(len(m_syms), 1), 4)
    return out


def check_join_health(join: dict, min_fraction: float = 0.05) -> None:
    """Abort loudly if the manifest exists but almost nothing joins -- a broken
    join and a genuinely empty result look identical in the output otherwise."""
    if not join.get("manifest_present") or not join.get("manifest_rows"):
        return
    frac = join.get("manifest_join_fraction")
    if frac is not None and frac < min_fraction:
        raise BrokenJoin(
            f"only {join.get('manifest_rows_joined', 0)} of "
            f"{join['manifest_rows']} manifest rows join to the frozen sample "
            f"({frac:.1%} < {min_fraction:.0%}). The join is broken, not empty. "
            f"Check the frozen-sample-selections.json bridge and the manifest "
            f"contract column."
        )


_RTH_MINUTES = 390  # a regular 06:30-13:00 Pacific session


def bar_sparsity_block(manifest: pd.DataFrame | None) -> dict:
    """Per-group (frozen sample vs live positions) bar-sparsity numbers.

    This is the real reason the conservative trade-bar model cannot be used for
    promotion: a target/stop is only testable in a minute that actually traded,
    and only ~2-3% of captured minutes did.
    """
    if manifest is None:
        return {"note": "no download manifest"}
    m = manifest.copy()
    m.columns = [c.lower() for c in m.columns]
    for c in ("rows", "positive_volume_rows"):
        m[c] = pd.to_numeric(m.get(c), errors="coerce").fillna(0.0)
    sym_col = next((c for c in ("contract", "contract_symbol", "symbol")
                    if c in m.columns), None)
    grp_col = "sample" if "sample" in m.columns else None

    def _block(sub: pd.DataFrame, label: str) -> dict:
        tot = float(sub["rows"].sum())
        pv = float(sub["positive_volume_rows"].sum())
        http = sub["http_status"].astype(str) if "http_status" in sub else None
        with_data = sub[http != "404"] if http is not None else sub
        per = []
        for _, r in sub.iterrows():
            rr = float(r["rows"])
            pvr = float(r["positive_volume_rows"])
            per.append({
                "contract": str(r.get(sym_col) or ""),
                "ticker": str(r.get("ticker") or ""),
                "http_status": str(r.get("http_status") or ""),
                "one_minute_bars": int(rr),
                "positive_volume_bars": int(pvr),
                "traded_minute_pct": round(100 * pvr / rr, 2) if rr else 0.0,
                "sessions_captured": round(rr / _RTH_MINUTES, 1) if rr else 0.0,
            })
        dens = [p["traded_minute_pct"] for p in per if p["one_minute_bars"]]
        return {
            "label": label,
            "contracts": int(len(sub)),
            "contracts_with_returned_data": int(len(with_data)),
            "tickers": int(sub["ticker"].nunique()) if "ticker" in sub else None,
            "tickers_with_returned_data": (int(with_data["ticker"].nunique())
                                           if "ticker" in with_data else None),
            "http_200": int((http == "200").sum()) if http is not None else None,
            "http_404": int((http == "404").sum()) if http is not None else None,
            "total_one_minute_bars": int(tot),
            "positive_volume_bars": int(pv),
            "positive_volume_pct": round(100 * pv / tot, 2) if tot else 0.0,
            "mean_traded_minute_pct_per_contract": (round(sum(dens) / len(dens), 2)
                                                    if dens else 0.0),
            "observable_fraction_of_390min_session": (
                round(pv / tot, 4) if tot else 0.0),
            "per_contract": per,
        }

    out = {}
    if grp_col:
        for s, sub in m.groupby(grp_col):
            out[str(s)] = _block(sub, str(s))
    else:
        out["all"] = _block(m, "all")
    return out


def build_data_quality(phase: str, stock_df, manifest, dq_bits, join,
                       data_root, frozen_selections) -> dict:
    fs = frozen_selections or _FROZEN_SELECTIONS
    agg_no_chain = agg_no_bars = agg_no_vol = 0
    for v in dq_bits.values():
        agg_no_chain = max(agg_no_chain, v.get("signals_no_stored_chain", 0))
        agg_no_bars += v.get("signals_named_but_no_bars", 0)
        agg_no_vol += v.get("signals_named_but_no_volume", 0)
    return {
        "phase": phase,
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "selector": "put_flow_option_select.select_structure",
        "data_root": str(data_root),
        "bridge_file": str(FROZEN_SELECTIONS_PATH),
        "bridge_present": bool(fs.get("present")),
        "join_proof": join,
        "chain_coverage": {
            "frozen_stock_trades": int(len(stock_df)),
            "signals_with_named_contract": join.get("matched_groups", 0),
            "signals_with_no_stored_chain": join.get("stock_trades", 0)
            - join.get("matched_groups", 0),
            "of_named__all_contracts_expired_404":
                join.get("unjoined_reason_split", {}).get("expired_404", 0),
            "of_named__at_least_one_contract_has_data":
                join.get("unjoined_reason_split", {}).get("has_data", 0),
            "per_candidate_named_but_no_bars": {
                k: v.get("signals_named_but_no_bars", 0)
                for k, v in dq_bits.items()},
            "per_candidate_named_but_no_positive_volume": {
                k: v.get("signals_named_but_no_volume", 0)
                for k, v in dq_bits.items()},
            "note": "two distinct failures: (a) no stored option chain at all -- "
                    "the frozen rule cannot even name a contract; (b) a contract "
                    "is named but the provider returns HTTP 404 because it has "
                    "expired. Yahoo serves unexpired contracts only.",
        },
        "bar_sparsity": bar_sparsity_block(manifest),
        "pre_entry_bars_dropped": {k: v["pre_entry_bars_dropped"]
                                   for k, v in dq_bits.items()},
        "tier_counts": {k: v["tier_counts"] for k, v in dq_bits.items()},
        "note": "06:35 Pacific entry enforced; earlier option bars rejected. "
                "No historical intraday bid/ask exists for this sample; the "
                "conservative trade-bar model is unusable at ~2-3% traded-minute "
                "density, so no rule can be promoted.",
    }


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #
CANDIDATE_COLS = [
    "structure_id", "exit_policy", "split", "market_date", "ticker", "rank",
    "entry_date", "exit_date", "stock_entry_px", "contract_symbols", "n_legs",
    "entry_debit", "liquidation_value", "commission_round_trip", "net_return",
    "outcome", "exit_reason", "proof_tier", "exit_minute", "structures_collapsed",
    "chain_source", "reason_code", "note",
]


def write_candidate_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CANDIDATE_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CANDIDATE_COLS})


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build_all_rows(policy, stock_df, dev_dates, eval_dates, data_root, manifest,
                   select_fn, only_split=None):
    all_rows: list[dict] = []
    dq_bits: dict[str, dict] = {}
    for structure in policy["structures"]:
        for exit_policy in policy["exit_policies"]:
            rows, bits = evaluate_candidate(
                structure["id"], exit_policy, stock_df, dev_dates, eval_dates,
                data_root, manifest, select_fn, only_split=only_split,
            )
            all_rows.extend(rows)
            dq_bits[candidate_key(structure["id"], exit_policy["id"])] = bits
    _flag_structures_collapsed(all_rows)
    return all_rows, dq_bits


def _flag_structures_collapsed(all_rows: list[dict]) -> None:
    """C2: mark rows where ATM_PUT and OTM5_PUT resolved to the same contract.

    Such a pair is one trade, not two -- callers must not count it as two
    independent observations in any gate, bootstrap cluster, or concentration
    figure.  Both rows are still kept, just flagged.
    """
    by_sig: dict[tuple, dict[str, str]] = {}
    for r in all_rows:
        if r["structure_id"] in ("ATM_PUT", "OTM5_PUT") and r["contract_symbols"]:
            by_sig.setdefault((r["market_date"], r["ticker"]), {})[
                r["structure_id"]] = r["contract_symbols"]
    collapsed = {
        sig for sig, m in by_sig.items()
        if m.get("ATM_PUT") and m.get("ATM_PUT") == m.get("OTM5_PUT")
    }
    for r in all_rows:
        if (r["market_date"], r["ticker"]) in collapsed and \
                r["structure_id"] in ("ATM_PUT", "OTM5_PUT"):
            r["structures_collapsed"] = "true"


def rows_for(all_rows, structure_id, exit_policy_id, split=None):
    out = [r for r in all_rows
           if r["structure_id"] == structure_id and r["exit_policy"] == exit_policy_id]
    if split:
        out = [r for r in out if r["split"] == split]
    return out


def run_development(args):
    policy = verify_frozen_policy()
    stock_df = load_stock_sample(policy=policy)
    dev_dates, eval_dates = build_split(stock_df["market_date"])
    data_root = Path(args.data_root)
    manifest = load_manifest(data_root, args.manifest)
    select_fn = resolve_selector(getattr(args, "select_fn", None))
    fs = set_frozen_selections(manifest)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows, dq_bits = build_all_rows(
        policy, stock_df, dev_dates, eval_dates, data_root, manifest, select_fn,
        only_split="development",
    )
    write_candidate_csv(out_dir / "candidate-results.csv", all_rows)
    check_join_health(prove_join(stock_df, manifest, fs))

    summary = {}
    for structure in policy["structures"]:
        for exit_policy in policy["exit_policies"]:
            sid, eid = structure["id"], exit_policy["id"]
            key = candidate_key(sid, eid)
            drows = rows_for(all_rows, sid, eid, "development")
            metrics = candidate_metrics(drows)
            timing = timing_sensitivity(
                sid, exit_policy, stock_df[stock_df["market_date"].isin(dev_dates)],
                dev_dates, eval_dates, data_root, manifest, select_fn,
            )
            overlap = overlap_suppressed(drows)
            passed, checks = dev_gate_pass(policy, metrics, drows, timing, overlap)
            summary[key] = {
                "structure_id": sid,
                "exit_policy": eid,
                "metrics": metrics,
                "dev_gate_checks": checks,
                "passes_all_dev_gates": passed,
                "timing_summary": timing.get("_summary"),
                "overlap_suppressed": overlap,
            }

    write_json(out_dir / "development-results.json", {
        "policy_name": policy["policy_name"],
        "todo": policy["todo"],
        "frozen_policy_sha256": sha256_file(POLICY_PATH),
        "stock_sample_sha256": sha256_file(STOCK_CSV),
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "split": {
            "development_dates": sorted(dev_dates),
            "evaluation_dates_count": len(eval_dates),
            "note": "evaluation dates are NOT listed and NOT scored in this file",
        },
        "candidates": summary,
    })

    join = prove_join(stock_df, manifest, fs)
    write_json(out_dir / "data-quality.json",
               build_data_quality("development", stock_df, manifest, dq_bits,
                                  join, data_root, fs))
    print(f"[development] wrote candidate-results.csv, development-results.json, "
          f"data-quality.json to {out_dir}")
    print(f"[development] join: matched_groups={join.get('matched_groups')} "
          f"of {join.get('stock_trades')} stock trades; manifest join fraction "
          f"{join.get('manifest_join_fraction')}")
    n_pass = sum(1 for v in summary.values() if v["passes_all_dev_gates"])
    print(f"[development] {n_pass}/9 candidates pass every development gate")


def run_choose(args):
    policy = verify_frozen_policy()
    out_dir = Path(args.out)
    dev_path = out_dir / "development-results.json"
    if not dev_path.exists():
        raise SystemExit("run --split development before --choose "
                         "(development-results.json missing)")
    dev = json.loads(dev_path.read_text())
    dev_summary = dev["candidates"]
    decision = choose_rule(policy, dev_summary)

    payload = {
        "policy_name": policy["policy_name"],
        "todo": policy["todo"],
        "frozen_policy_sha256": sha256_file(POLICY_PATH),
        "stock_sample_sha256": sha256_file(STOCK_CSV),
        "development_choice_order": policy["development_choice_order"],
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "chosen": decision["chosen"],
        "selection_trace": decision["selection_trace"],
        "development_metrics": (
            dev_summary[decision["chosen"]["candidate_key"]]["metrics"]
            if decision["chosen"] else None),
        "development_gate_checks": (
            dev_summary[decision["chosen"]["candidate_key"]]["dev_gate_checks"]
            if decision["chosen"] else None),
        "note": "Written by --choose from the frozen development_choice_order. "
                "The evaluation split unlocks ONLY against this file plus its "
                ".sha256 fingerprint.",
    }
    body = json.dumps(payload, indent=2, default=str) + "\n"
    crj = out_dir / CHOSEN_FILE
    crj.write_text(body)
    digest = sha256_bytes(body.encode())
    (out_dir / (CHOSEN_FILE + ".sha256")).write_text(f"{digest}  {CHOSEN_FILE}\n")
    if decision["chosen"]:
        print(f"[choose] chosen rule: {decision['chosen']['candidate_key']}")
    else:
        print("[choose] NO candidate passed every development gate "
              "(chosen = null); evaluation may still be unlocked to report "
              "INSUFFICIENT DATA / REJECTED.")
    print(f"[choose] wrote {CHOSEN_FILE} + .sha256 ({digest[:12]}...)")


def run_evaluation(args):
    """Score the CHOSEN rule on the untouched evaluation split.

    Refuses to run unless chosen-development-rule.json exists, verifies against
    its .sha256, AND names a non-null rule.
    """
    policy = verify_frozen_policy()
    out_dir = Path(args.out)
    chosen_doc = require_evaluation_unlocked(out_dir)  # aborts on null / missing
    stock_df = load_stock_sample(policy=policy)
    dev_dates, eval_dates = build_split(stock_df["market_date"])
    data_root = Path(args.data_root)
    manifest = load_manifest(data_root, args.manifest)
    select_fn = resolve_selector(getattr(args, "select_fn", None))
    fs = set_frozen_selections(manifest)

    all_rows, dq_bits = build_all_rows(
        policy, stock_df, dev_dates, eval_dates, data_root, manifest, select_fn,
    )
    write_candidate_csv(out_dir / "candidate-results.csv", all_rows)

    chosen = chosen_doc["chosen"]
    sid, eid = chosen["structure_id"], chosen["exit_policy_id"]
    exit_policy = next(p for p in policy["exit_policies"] if p["id"] == eid)

    dev_rows = rows_for(all_rows, sid, eid, "development")
    eval_rows = rows_for(all_rows, sid, eid, "evaluation")
    full_rows = rows_for(all_rows, sid, eid)
    dev_metrics = candidate_metrics(dev_rows)
    eval_metrics = candidate_metrics(eval_rows)
    full_metrics = candidate_metrics(full_rows)
    portfolio = simulate_portfolio(full_rows, policy["gates"]["G9_portfolio"])
    conc = concentration(full_rows)
    overlap = overlap_suppressed(full_rows)
    timing = timing_sensitivity(sid, exit_policy, stock_df, dev_dates, eval_dates,
                                data_root, manifest, select_fn)
    gates = evaluate_gates(policy, candidate_key(sid, eid), dev_rows, eval_rows,
                           full_rows, dev_metrics, eval_metrics, portfolio, conc,
                           timing, overlap)
    verdict = overall_verdict(gates)

    with open(out_dir / "portfolio-equity.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "date", "open_positions", "deployed_premium", "realized_pnl_cum",
            "equity"])
        w.writeheader()
        for e in portfolio["equity_curve"]:
            w.writerow(e)
    write_json(out_dir / "timing-sensitivity.json", timing)
    write_json(out_dir / "concentration.json", conc)
    write_json(out_dir / "gates.json", {
        "phase": "evaluation",
        "chosen_rule": {"structure_id": sid, "exit_policy_id": eid},
        "verdict": verdict,
        "gates_may_not_be_weakened_after_results": True,
        "gates": gates,
    })
    write_json(out_dir / "evaluation-results.json", {
        "chosen_rule": {"structure_id": sid, "exit_policy_id": eid},
        "frozen_policy_sha256": sha256_file(POLICY_PATH),
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "development_metrics": dev_metrics,
        "evaluation_metrics": eval_metrics,
        "full_metrics": full_metrics,
        "portfolio": {k: v for k, v in portfolio.items() if k != "equity_curve"},
        "concentration": conc,
        "overlap_suppressed": overlap,
        "verdict": verdict,
        "tier_reporting": "each proof tier reported separately; never blended",
    })
    join = prove_join(stock_df, manifest, fs)
    write_json(out_dir / "data-quality.json",
               build_data_quality("evaluation", stock_df, manifest, dq_bits,
                                  join, data_root, fs))
    print(f"[evaluation] verdict: {verdict}")
    for g in gates:
        print(f"    {g['id']}: {g['verdict']}")


def run_full(args):
    """Full-sample report over ALL 9 candidates.  No rule is chosen or promoted;
    this exists to publish the real G1/G2 eligible counts against the thresholds.
    """
    policy = verify_frozen_policy()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stock_df = load_stock_sample(policy=policy)
    dev_dates, eval_dates = build_split(stock_df["market_date"])
    data_root = Path(args.data_root)
    manifest = load_manifest(data_root, args.manifest)
    select_fn = resolve_selector(getattr(args, "select_fn", None))
    fs = set_frozen_selections(manifest)

    all_rows, dq_bits = build_all_rows(
        policy, stock_df, dev_dates, eval_dates, data_root, manifest, select_fn,
    )
    write_candidate_csv(out_dir / "candidate-results.csv", all_rows)
    join = prove_join(stock_df, manifest, fs)
    check_join_health(join)

    per_candidate = {}
    per_timing = {}
    per_conc = {}
    worst = "PASS"
    rank = {"PASS": 0, "PENDING EVALUATION": 1, "FAIL": 2, "INSUFFICIENT DATA": 3}
    for structure in policy["structures"]:
        for exit_policy in policy["exit_policies"]:
            sid, eid = structure["id"], exit_policy["id"]
            key = candidate_key(sid, eid)
            dev_rows = rows_for(all_rows, sid, eid, "development")
            eval_rows = rows_for(all_rows, sid, eid, "evaluation")
            full_rows = rows_for(all_rows, sid, eid)
            dev_m = candidate_metrics(dev_rows)
            eval_m = candidate_metrics(eval_rows)
            full_m = candidate_metrics(full_rows)
            portfolio = simulate_portfolio(full_rows,
                                           policy["gates"]["G9_portfolio"])
            conc = concentration(full_rows)
            overlap = overlap_suppressed(full_rows)
            timing = timing_sensitivity(sid, exit_policy, stock_df, dev_dates,
                                        eval_dates, data_root, manifest, select_fn)
            gates = evaluate_gates(policy, key, dev_rows, eval_rows, full_rows,
                                   dev_m, eval_m, portfolio, conc, timing, overlap)
            v = overall_verdict(gates)
            if rank.get(v, 3) > rank.get(worst, 0):
                worst = v
            per_candidate[key] = {
                "structure_id": sid, "exit_policy_id": eid,
                "verdict": v,
                "eligible_full": {
                    "trades": full_m["n_resolved"],
                    "signal_dates": full_m["n_signal_dates_resolved"],
                    "stocks": full_m["n_stocks_resolved"]},
                "eligible_evaluation": {
                    "trades": eval_m["n_resolved"],
                    "signal_dates": eval_m["n_signal_dates_resolved"],
                    "stocks": eval_m["n_stocks_resolved"]},
                "outcome_counts": full_m["outcome_counts"],
                "tier_counts": full_m["tier_counts"],
                "gates": gates,
            }
            per_timing[key] = timing
            per_conc[key] = conc

    write_json(out_dir / "gates.json", {
        "phase": "full",
        "chosen_rule": None,
        "verdict": worst,
        "gates_may_not_be_weakened_after_results": True,
        "thresholds": {
            "G1_full": policy["gates"]["G1_full_sample_size"],
            "G2_evaluation": policy["gates"]["G2_evaluation_size"]},
        "candidates": per_candidate,
        "note": "No rule chosen or promoted. Per-candidate gates over the full "
                "181-trade sample; G1/G2 carry the real eligible counts.",
    })
    write_json(out_dir / "timing-sensitivity.json", {"per_candidate": per_timing})
    write_json(out_dir / "concentration.json", {"per_candidate": per_conc})
    with open(out_dir / "portfolio-equity.csv", "w", newline="") as fh:
        csv.DictWriter(fh, fieldnames=[
            "date", "open_positions", "deployed_premium", "realized_pnl_cum",
            "equity"]).writeheader()
    write_json(out_dir / "evaluation-results.json", {
        "chosen_rule": None,
        "verdict": worst,
        "note": "no rule chosen; --split full is a reporting pass only",
        "per_candidate_eligible_full": {
            k: v["eligible_full"] for k, v in per_candidate.items()},
    })
    write_json(out_dir / "data-quality.json",
               build_data_quality("full", stock_df, manifest, dq_bits, join,
                                  data_root, fs))

    print(f"[full] verdict: {worst}")
    print(f"[full] join: matched_groups={join.get('matched_groups')} of "
          f"{join.get('stock_trades')}; reason split "
          f"{join.get('unjoined_reason_split')}")
    ex = per_candidate[candidate_key('ATM_PUT', 'TIME_ONLY')]
    g1 = policy["gates"]["G1_full_sample_size"]
    g2 = policy["gates"]["G2_evaluation_size"]
    print(f"[full] G1 (ATM_PUT/TIME_ONLY) eligible {ex['eligible_full']} "
          f"vs required trades>={g1['min_eligible_trades']}, "
          f"dates>={g1['min_signal_dates']}, stocks>={g1['min_stocks']}")
    print(f"[full] G2 (ATM_PUT/TIME_ONLY) eligible {ex['eligible_evaluation']} "
          f"vs required trades>={g2['min_eligible_trades']}, "
          f"dates>={g2['min_signal_dates']}, stocks>={g2['min_stocks']}")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", choices=["development", "evaluation", "full"])
    p.add_argument("--choose", action="store_true",
                   help="apply the frozen development_choice_order and write "
                        "chosen-development-rule.json + .sha256")
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--manifest", default=None,
                   help="override path to download-manifest.csv")
    p.add_argument("--out", default=str(RESEARCH_DIR))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.choose:
        run_choose(args)
        return
    if args.split == "development":
        run_development(args)
    elif args.split == "evaluation":
        run_evaluation(args)
    elif args.split == "full":
        run_full(args)
    else:
        raise SystemExit("specify --split {development|evaluation|full} or --choose")


if __name__ == "__main__":
    main()
