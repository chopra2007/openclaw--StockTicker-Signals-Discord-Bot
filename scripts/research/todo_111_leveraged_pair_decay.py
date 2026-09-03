#!/usr/bin/env python3
"""TODO #111 candidate 2 — short both legs of a leveraged fund pair for one month.

Implements frozen-rule-candidate-2.md exactly. No tuning, no parameter search.
Run:  python3 scripts/research/todo_111_leveraged_pair_decay.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

import pandas as pd
import yfinance as yf

CACHE = "/home/openclaw/.openclaw/research-data/todo-111/leveraged"
OUT = "/home/openclaw/.openclaw/workspace/.omc/research/todo-111-proven-trading-edge"

# Frozen pairs: (up fund, inverse fund)
PAIRS = [
    ("TQQQ", "SQQQ"), ("UPRO", "SPXU"), ("TNA", "TZA"), ("SOXL", "SOXS"),
    ("ERX", "ERY"), ("FAS", "FAZ"), ("NUGT", "DUST"), ("TMF", "TMV"),
    ("JNUG", "JDST"), ("UGAZ", "DGAZ"),
]
TICKERS = [t for p in PAIRS for t in p]

NOTIONAL = 10_000.0          # per leg
SLIP_BP = 10.0               # per leg per side, on notional
COMMISSION = 1.0             # per leg per side
BORROW_UP = 0.06             # per year, up-fund leg
BORROW_INV = 0.20            # per year, inverse-fund leg
MIN_HISTORY = 60             # prior trading sessions required per leg

DEV_START = pd.Timestamp("2010-01-01")
DEV_END = pd.Timestamp("2018-12-31")   # HARD SEAL: nothing after this is read


def fetch(ticker: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{ticker}.csv")
    if not os.path.exists(path):
        df = yf.Ticker(ticker).history(period="max", auto_adjust=False)
        if df.empty:
            raise SystemExit(f"no data for {ticker}")
        df.to_csv(path)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_localize(None).normalize()
    return df


def seal(df: pd.DataFrame) -> pd.DataFrame:
    """Drop everything after the development end date, immediately and everywhere."""
    return df[df.index <= DEV_END]


def verify_reverse_splits(data: dict[str, pd.DataFrame]) -> list[dict]:
    """Confirm the adjusted series has no fake jump on a reverse-split date.

    A reverse split with a correctly adjusted series shows an ordinary daily move.
    An unadjusted series would show a jump of the split ratio (e.g. +300% on a 1:4).
    """
    findings = []
    for t in ("SQQQ", "TZA"):
        df = data[t]
        if "Stock Splits" not in df.columns:
            findings.append({"ticker": t, "error": "no Stock Splits column"})
            continue
        splits = df[df["Stock Splits"] != 0]["Stock Splits"]
        adj = df["Adj Close"]
        raw = df["Close"]
        ret_adj = adj.pct_change()
        ret_raw = raw.pct_change()
        for dt, ratio in splits.items():
            if dt not in ret_adj.index:
                continue
            findings.append({
                "ticker": t,
                "date": dt.strftime("%Y-%m-%d"),
                "splitFactor": float(ratio),
                "impliedJumpIfUnadjustedPct": round((1.0 / float(ratio) - 1) * 100, 2),
                "adjCloseDayReturnPct": round(float(ret_adj.loc[dt]) * 100, 3),
                "closeDayReturnPct": round(float(ret_raw.loc[dt]) * 100, 3),
            })
    return findings


def month_calendar(all_days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """First trading day of each month, from the union of days actually present."""
    s = pd.Series(all_days, index=all_days)
    firsts = s.groupby([all_days.year, all_days.month]).min()
    return sorted(firsts.tolist())


def main() -> None:
    data = {}
    for t in TICKERS:
        df = fetch(t)
        data[t] = seal(df)
        print(f"{t}: {len(df)} rows raw, {len(data[t])} rows through {DEV_END.date()}",
              file=sys.stderr)

    split_findings = verify_reverse_splits({t: seal(fetch(t)) for t in ("SQQQ", "TZA")})

    union = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in data.values()])))
    union = union[(union >= DEV_START) & (union <= DEV_END)]
    firsts = month_calendar(union)

    adj = {t: data[t]["Adj Close"].dropna() for t in TICKERS}
    last_traded = {t: adj[t].index.max() for t in TICKERS}

    trades = []
    notes = []
    for i in range(len(firsts) - 1):
        entry, exit_target = firsts[i], firsts[i + 1]
        for up, inv in PAIRS:
            legs = {}
            ok = True
            for t in (up, inv):
                s = adj[t]
                prior = s.index[s.index < entry]
                if len(prior) < MIN_HISTORY or entry not in s.index:
                    ok = False
                    break
                # exit: the target date, or the fund's last traded price if it stopped
                if exit_target in s.index:
                    xd, xp, halted = exit_target, float(s.loc[exit_target]), False
                else:
                    avail = s.index[(s.index > entry) & (s.index <= exit_target)]
                    if len(avail) == 0:
                        ok = False
                        break
                    xd, xp, halted = avail.max(), float(s.loc[avail.max()]), True
                legs[t] = (float(s.loc[entry]), xp, xd, halted)
            if not ok:
                continue

            days = (exit_target - entry).days
            row = {"pair": f"{up}/{inv}", "entry_date": entry.strftime("%Y-%m-%d"),
                   "exit_date": exit_target.strftime("%Y-%m-%d"), "calendar_days": days}
            buyback = 0.0
            slip = commission = borrow = gross = 0.0
            for t, rate in ((up, BORROW_UP), (inv, BORROW_INV)):
                ep, xp, xd, halted = legs[t]
                shares = NOTIONAL / ep
                val_out = shares * xp
                buyback += val_out
                gross += NOTIONAL - val_out
                slip += 2 * NOTIONAL * SLIP_BP / 10_000.0
                commission += 2 * COMMISSION
                borrow += NOTIONAL * rate * days / 365.0
                tag = "up" if t == up else "inv"
                row[f"{tag}_ticker"] = t
                row[f"{tag}_entry_px"] = round(ep, 6)
                row[f"{tag}_exit_px"] = round(xp, 6)
                row[f"{tag}_exit_px_date"] = xd.strftime("%Y-%m-%d")
                row[f"{tag}_halted_early"] = halted
                row[f"{tag}_gross_pnl"] = round(NOTIONAL - val_out, 2)
                if halted:
                    notes.append(f"{t} {entry.date()}: exited at last traded price {xd.date()}")
            costs = slip + commission + borrow
            net = gross - costs
            row.update({
                "gross_pnl": round(gross, 2), "slippage": round(slip, 2),
                "commission": round(commission, 2), "borrow": round(borrow, 2),
                "total_costs": round(costs, 2), "net_pnl": round(net, 2),
                "return_pct": round(net / (2 * NOTIONAL) * 100, 4),
                "return_pct_before_costs": round(gross / (2 * NOTIONAL) * 100, 4),
                "return_pct_excl_borrow": round((gross - slip - commission) / (2 * NOTIONAL) * 100, 4),
            })
            trades.append(row)

    tr = pd.DataFrame(trades)
    tr = tr.sort_values(["entry_date", "pair"])
    tr.to_csv(os.path.join(OUT, "trades-development-c2.csv"), index=False)

    def agg(g):
        return {"trades": int(len(g)), "avgReturnPct": round(float(g["return_pct"].mean()), 4)}

    r = tr["return_pct"]
    result = {
        "instrument": "shares",
        "period": "2010-01-01..2018-12-31",
        "tradeCount": int(len(tr)),
        "avgReturnPctAfterCosts": round(float(r.mean()), 4),
        "winRatePct": round(float((r > 0).mean() * 100), 2),
        "medianReturnPct": round(float(r.median()), 4),
        "worstReturnPct": round(float(r.min()), 4),
        "bestReturnPct": round(float(r.max()), 4),
        "totalNetProfitUsd": round(float(tr["net_pnl"].sum()), 2),
        "distinctPairs": int(tr["pair"].nunique()),
        "byPair": {k: agg(g) for k, g in tr.groupby("pair")},
        "byYear": {str(k): agg(g) for k, g in tr.groupby(tr["entry_date"].str[:4])},
        "avgReturnPctBeforeCosts": round(float(tr["return_pct_before_costs"].mean()), 4),
        "avgReturnPctExcludingBorrow": round(float(tr["return_pct_excl_borrow"].mean()), 4),
        "reverseSplitVerification": split_findings,
        "haltedLegNotes": notes,
        "barAvgReturnPct": 1.0,
        "minTrades": 200,
    }
    # single best pair removed, as the bar demands
    best = max(result["byPair"], key=lambda k: result["byPair"][k]["avgReturnPct"])
    sub = tr[tr["pair"] != best]
    result["bestPair"] = best
    result["exBestPair"] = {"trades": int(len(sub)),
                            "avgReturnPct": round(float(sub["return_pct"].mean()), 4)}

    with open(os.path.join(OUT, "development-result-c2.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
