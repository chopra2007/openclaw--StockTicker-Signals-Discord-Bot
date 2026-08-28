#!/usr/bin/env python3
"""Signal, fill, cost, portfolio and metric engine for TODO #104.

Three methods share one accounting and risk engine so no method gets a private
advantage.  Every fill rule takes the conservative answer whenever the data
cannot prove a favourable one.

Nothing here reads a result to decide anything.  All thresholds arrive from
`frozen-policy.json`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ipsf_common import METHOD1_BLOCKS, RES_DIR  # noqa: E402


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
def load_policy(path: Path | None = None) -> dict:
    p = Path(path) if path else RES_DIR / "frozen-policy.json"
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- #
# Method 1 — same-time-of-day continuation
# --------------------------------------------------------------------------- #
def m1_signals(panel: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Rows that clear the frozen tail, in the order a live trader would see."""
    m1 = policy["methods"]["M1"]
    p = panel.copy()
    p["abs_score"] = p["score"].abs()
    p = p[p["abs_score"] >= m1["score_threshold"]]
    p = p[p["risk_unit"].notna()]
    p["side"] = np.where(p["pred"] > 0, 1, -1)
    p["stop_frac"] = np.clip(p["risk_unit"] * m1["stop_risk_unit_multiple"],
                             m1["stop_frac_min"], m1["stop_frac_max"])
    p["stop_frac"] = (p["stop_frac"] * 1e4).round() / 1e4   # nearest 1 bp
    # time order: by date, then block, then strongest score first inside a block
    p = p.sort_values(["date", "block", "abs_score"],
                      ascending=[True, True, False], ignore_index=True)
    # one candidate per block: the strongest score
    p = p.groupby(["date", "block"], as_index=False, sort=False).head(1)
    # at most four entries a day, taken in time order
    p = p.groupby("date", as_index=False, sort=False).head(
        m1["max_entries_per_day"])
    return p.reset_index(drop=True)


def m1_price_trades(sig: pd.DataFrame, bars: pd.DataFrame, policy: dict,
                    entry_delay_minutes: int = 0) -> pd.DataFrame:
    """Attach the real fill path to every candidate.  No sizing yet.

    `bars` must hold every minute bar of every candidate's block.
    """
    m1 = policy["methods"]["M1"]
    hold = m1["block_minutes"]
    by_key = {k: g for k, g in bars.groupby(["date", "symbol", "block"],
                                            sort=False)}
    rows = []
    for r in sig.itertuples(index=False):
        g = by_key.get((r.date, r.symbol, r.block))
        if g is None or len(g) == 0:
            rows.append(_void(r, "no_bars"))
            continue
        g = g.sort_values("minute")
        mins = g["minute"].to_numpy()
        first_allowed = r.block + entry_delay_minutes
        idx = np.flatnonzero(mins >= first_allowed)
        if idx.size == 0:
            rows.append(_void(r, "no_entry_bar"))
            continue
        # a delayed entry uses the next bar that actually printed, but the
        # slide is bounded: past the cap the signal time no longer matches the
        # price and the trade is dropped instead of taken late.
        e = int(idx[0])
        slide = int(mins[e]) - first_allowed
        if slide > m1["max_entry_slide_minutes"]:
            rows.append(_void(r, "entry_slide_too_far"))
            continue
        entry_px = float(g["open"].to_numpy()[e])
        if not np.isfinite(entry_px) or entry_px <= 0:
            rows.append(_void(r, "bad_entry_price"))
            continue

        side = int(r.side)
        stop_px = entry_px * (1 - side * r.stop_frac)
        highs = g["high"].to_numpy()[e:]
        lows = g["low"].to_numpy()[e:]
        opens = g["open"].to_numpy()[e:]
        closes = g["close"].to_numpy()[e:]
        mm = mins[e:]
        last_ok = mm <= r.block + hold - 1
        highs, lows, opens, closes, mm = (highs[last_ok], lows[last_ok],
                                          opens[last_ok], closes[last_ok],
                                          mm[last_ok])
        if mm.size == 0:
            rows.append(_void(r, "no_bars_in_window"))
            continue

        exit_px, exit_min, reason = None, None, None
        halt_at = None
        if mm.size > 1:
            gaps = np.diff(mm)
            bad = np.flatnonzero(gaps > m1["halt_missing_minutes"])
            if bad.size:
                halt_at = int(bad[0])   # last usable bar index before the halt
        for i in range(mm.size):
            if halt_at is not None and i > halt_at:
                # a halt inside the trade: close at the last valid price
                exit_px, exit_min, reason = (float(closes[halt_at]),
                                             int(mm[halt_at]), "halt")
                break
            # a bar that OPENS through the stop exits at that open, not the stop
            if side == 1:
                gapped = opens[i] <= stop_px
                touched = lows[i] <= stop_px
            else:
                gapped = opens[i] >= stop_px
                touched = highs[i] >= stop_px
            if gapped:
                exit_px, exit_min, reason = float(opens[i]), int(mm[i]), "stop_gap"
                break
            if touched:
                # stop and the time exit in one bar: the stop counts first
                exit_px, exit_min, reason = float(stop_px), int(mm[i]), "stop"
                break
        if exit_px is None:
            exit_px, exit_min, reason = (float(closes[-1]), int(mm[-1]),
                                         "time_exit")

        gross = side * (exit_px / entry_px - 1.0)
        rows.append({
            "method": "M1", "date": r.date, "symbol": r.symbol,
            "entry_slide_minutes": slide, "halt": reason == "halt",
            "block": int(r.block), "side": side, "score": float(r.score),
            "entry_minute": int(mm[0]) if reason != "no_bars" else None,
            "entry_px": entry_px, "exit_px": exit_px, "exit_minute": exit_min,
            "exit_reason": reason, "stop_frac": float(r.stop_frac),
            "gross_return": gross,
            "prior20_window_dollar_volume": float(r.prior20_block_dollar_volume),
            "market_return": float(r.mkt) if np.isfinite(r.mkt) else 0.0,
            "hold_days": 0.0, "void": False, "void_reason": None,
            "entry_seq": (r.date, int(r.block)),
            "exit_seq": (r.date, int(exit_min)),
            "legs": 1,
        })
    return pd.DataFrame(rows)


def _void(r, why):
    return {"method": "M1", "date": r.date, "symbol": r.symbol,
            "block": int(r.block), "side": int(r.side), "score": float(r.score),
            "entry_minute": None, "entry_px": None, "exit_px": None,
            "exit_minute": None, "exit_reason": None,
            "stop_frac": float(r.stop_frac), "gross_return": np.nan,
            "prior20_window_dollar_volume": float(r.prior20_block_dollar_volume),
            "entry_slide_minutes": None, "halt": False,
            "market_return": 0.0,
            "hold_days": 0.0, "void": True, "void_reason": why,
            "entry_seq": (r.date, int(r.block)), "exit_seq": (r.date, int(r.block)),
            "legs": 1}


# --------------------------------------------------------------------------- #
# Method 2 — daily volume-conditioned continuation or reversal
# --------------------------------------------------------------------------- #
def m2_trades(daily: pd.DataFrame, liq: pd.DataFrame, spy: pd.DataFrame,
              policy: dict, dates: list[str],
              entry_at_close: bool = False) -> pd.DataFrame:
    m2 = policy["methods"]["M2"]
    d = daily.merge(spy.rename(columns={"ret": "spy_ret"})[["date", "spy_ret"]],
                    on="date", how="left")
    d["x"] = d["ret"] - d["spy_ret"]
    d = d.merge(liq, on=["date", "symbol"], how="left")
    d = d[d["liquid"].fillna(False)]

    # Frozen mapping: in this large, liquid universe a big move on unusually
    # heavy volume is hedging pressure, so it REVERSES.  Everything else is
    # no signal.  (Llorente, Michaely, Saar and Wang 2002, cross-section.)
    sig = (d["x"].abs() >= m2["move_floor"]) & (d["v"] >= m2["volume_threshold"])
    d = d[sig].copy()
    d["mapping"] = "reverse"
    d["side"] = (-np.sign(d["x"])).astype(int)
    d["abs_x"] = d["x"].abs()
    # a short needs the stricter size-and-price proxy for "was probably
    # borrowable"; we hold no historical borrow record at all
    d = d[(d["side"] == 1) | d["shortable_proxy"].fillna(False)]

    spy_open = dict(zip(spy["date"], spy["open"]))
    spy_close = dict(zip(spy["date"], spy["close"]))
    date_index = {dt: i for i, dt in enumerate(dates)}
    by_sym = {s: g.sort_values("date").reset_index(drop=True)
              for s, g in daily.groupby("symbol", sort=False)}
    sym_pos = {s: {dt: i for i, dt in enumerate(g["date"])}
               for s, g in by_sym.items()}

    rows = []
    hold = m2["max_hold_sessions"]
    for r in d.sort_values(["date", "abs_x"],
                           ascending=[True, False]).itertuples(index=False):
        if r.date not in date_index:
            continue
        g = by_sym.get(r.symbol)
        i0 = sym_pos[r.symbol].get(r.date)
        if g is None or i0 is None or i0 + 1 >= len(g):
            continue
        entry_row = g.iloc[i0 + 1]
        entry_px = float(entry_row["close" if entry_at_close else "open"])
        if not np.isfinite(entry_px) or entry_px <= 0:
            continue
        atr = float(r.atr20) if np.isfinite(r.atr20) else np.nan
        if not np.isfinite(atr):
            continue
        stop_frac = float(np.clip(
            m2["stop_atr_multiple"] * atr * np.sqrt(m2["max_hold_sessions"]),
            m2["stop_frac_min"], m2["stop_frac_max"]))
        stop_frac = round(stop_frac, 3)     # nearest 10 bps
        side = int(r.side)
        stop_px = entry_px * (1 - side * stop_frac)

        exit_px, exit_date, reason, held = None, None, None, 0
        for k in range(hold):
            j = i0 + 1 + k
            if j >= len(g):
                break
            row = g.iloc[j]
            held = k + 1
            o, hi, lo, cl = (float(row["open"]), float(row["high"]),
                             float(row["low"]), float(row["close"]))
            if k > 0 or not entry_at_close:
                gapped = (o <= stop_px) if side == 1 else (o >= stop_px)
                touched = (lo <= stop_px) if side == 1 else (hi >= stop_px)
                if k == 0 and not entry_at_close:
                    gapped = False   # the open IS the entry on day one
                if gapped:
                    exit_px, exit_date, reason = o, row["date"], "stop_gap"
                    break
                if touched:
                    exit_px, exit_date, reason = stop_px, row["date"], "stop"
                    break
            if k == hold - 1:
                exit_px, exit_date, reason = cl, row["date"], "time_exit"
        if exit_px is None:
            continue
        spy_entry = spy_open.get(entry_row["date"])
        spy_exit = (spy_close.get(exit_date) if reason == "time_exit"
                    else spy_open.get(exit_date))
        mkt = ((spy_exit / spy_entry - 1.0)
               if (spy_entry and spy_exit and spy_entry > 0) else 0.0)
        rows.append({
            "method": "M2", "date": r.date, "symbol": r.symbol,
            "market_return": float(mkt),
            "block": None, "side": side, "score": float(r.abs_x),
            "mapping": r.mapping,
            "entry_date": entry_row["date"], "entry_px": entry_px,
            "exit_px": float(exit_px), "exit_date": exit_date,
            "exit_reason": reason, "stop_frac": stop_frac,
            "gross_return": side * (float(exit_px) / entry_px - 1.0),
            "prior20_window_dollar_volume": float(r.prior60_median_dollar_volume),
            "hold_days": float(held), "void": False, "void_reason": None,
            "entry_slide_minutes": 0, "halt": False,
            "entry_seq": (entry_row["date"], 0),
            "exit_seq": (exit_date, 1),
            "legs": 1,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Method 3 — close-substitute pairs
# --------------------------------------------------------------------------- #
def m3_pairs(daily: pd.DataFrame, liq: pd.DataFrame, groups: dict,
             policy: dict, dates: list[str],
             entry_delay_sessions: int = 0) -> pd.DataFrame:
    """Close-substitute pairs.  Selection never sees a trading outcome."""
    m3 = policy["methods"]["M3"]
    form = m3["formation_sessions"]
    trade_len = m3["trading_sessions"]

    d = daily[daily["valid_session"]]
    close = d.pivot_table(index="date", columns="symbol", values="close",
                          aggfunc="last").sort_index()
    open_ = d.pivot_table(index="date", columns="symbol", values="open",
                          aggfunc="last").reindex(close.index)
    liq_w = liq.pivot_table(index="date", columns="symbol", values="liquid",
                            aggfunc="last").reindex(close.index)
    short_w = liq.pivot_table(index="date", columns="symbol",
                              values="shortable_proxy",
                              aggfunc="last").reindex(close.index)
    dv_w = liq.pivot_table(index="date", columns="symbol",
                           values="prior60_median_dollar_volume",
                           aggfunc="last").reindex(close.index)
    all_d = list(close.index)
    trade_set = set(dates)

    rows = []
    start_i = all_d.index(dates[0]) if dates[0] in all_d else form
    i = max(start_i, form)
    while i < len(all_d):
        form_dates = all_d[i - form:i]
        trade_dates = [x for x in all_d[i:i + trade_len] if x in trade_set]
        if trade_dates:
            for a, b, sigma_spread, sigma_rel in _select_pairs(
                    close, liq_w, form_dates, trade_dates[0], groups, m3):
                rows.extend(_trade_one_pair(
                    a, b, sigma_spread, sigma_rel, close, open_, dv_w, short_w,
                    form_dates, trade_dates, all_d, m3, entry_delay_sessions))
        i += trade_len
    return pd.DataFrame(rows)


def _select_pairs(close, liq_w, form_dates, first_trade_date, groups, m3):
    """The single closest pair in each industry group, then the best ten."""
    fd = close.loc[form_dates]
    best = []
    for gname, members in groups.items():
        cand = [s for s in members
                if s in fd.columns and s in liq_w.columns
                and bool(fd[s].notna().all()) and float(fd[s].iloc[0]) > 0
                and bool(liq_w.at[first_trade_date, s])]
        if len(cand) < 2:
            continue
        norm = fd[cand] / fd[cand].iloc[0]
        top = None
        for x in range(len(cand)):
            for y in range(x + 1, len(cand)):
                a, b = cand[x], cand[y]
                spread = norm[a] - norm[b]
                ssd = float((spread ** 2).sum())
                if top is None or ssd < top[0]:
                    sigma_spread = float(spread.std(ddof=1))
                    rel = (fd[a] / fd[a].shift(1) - fd[b] / fd[b].shift(1))
                    sigma_rel = float(rel.std(ddof=1))
                    top = (ssd, a, b, sigma_spread, sigma_rel)
        if top and np.isfinite(top[3]) and top[3] > 0 and np.isfinite(top[4]) \
                and top[4] > 0:
            best.append(top)
    best.sort(key=lambda t: t[0])
    return [(a, b, ss, sr) for (_, a, b, ss, sr) in best[:m3["pairs_kept"]]]


def _trade_one_pair(a, b, sigma_spread, sigma_rel, close, open_, dv_w, short_w,
                    form_dates, trade_dates, all_d, m3, delay):
    base_a = float(close.at[form_dates[-1], a])
    base_b = float(close.at[form_dates[-1], b])
    if not (np.isfinite(base_a) and np.isfinite(base_b)
            and base_a > 0 and base_b > 0):
        return []
    stop_frac = float(np.clip(
        m3["stop_rel_multiple"] * sigma_rel * np.sqrt(m3["max_hold_sessions"]),
        m3["stop_frac_min"], m3["stop_frac_max"]))
    stop_frac = round(stop_frac, 3)

    rows = []
    busy_until = -1
    for d in trade_dates:
        i = all_d.index(d)
        if i <= busy_until:
            continue
        ca, cb = close.at[d, a], close.at[d, b]
        if not (np.isfinite(ca) and np.isfinite(cb)):
            continue
        spread = (ca / base_a) - (cb / base_b)
        if abs(spread) < m3["entry_z"] * sigma_spread:
            continue
        j = i + 1 + delay
        if j >= len(all_d):
            break
        ed = all_d[j]
        ea, eb = open_.at[ed, a], open_.at[ed, b]
        if not (np.isfinite(ea) and np.isfinite(eb) and ea > 0 and eb > 0):
            continue                      # one leg unfillable -> no trade
        long_sym, short_sym = (b, a) if spread > 0 else (a, b)
        # a short we cannot even proxy as borrowable is not taken
        if short_sym in short_w.columns and not bool(short_w.at[d, short_sym]):
            continue
        long_px = float(eb if spread > 0 else ea)
        short_px = float(ea if spread > 0 else eb)

        exit_i, reason = None, None
        for h in range(1, m3["max_hold_sessions"] + 1):
            jj = j + h - 1
            if jj >= len(all_d):
                break
            dd = all_d[jj]
            la, lb = close.at[dd, long_sym], close.at[dd, short_sym]
            if not (np.isfinite(la) and np.isfinite(lb)):
                continue
            pnl = 0.5 * ((la / long_px - 1.0) - (lb / short_px - 1.0))
            if pnl <= -stop_frac:                       # money stop first
                exit_i, reason = jj + 1, "stop"
                break
            cca, ccb = close.at[dd, a], close.at[dd, b]
            sp = (cca / base_a) - (ccb / base_b)
            converged = (abs(sp) <= m3["convergence_band"] * sigma_spread
                         or sp * spread <= 0)
            if h > 1 and converged:
                exit_i, reason = jj + 1, "convergence"
                break
            if h == m3["max_hold_sessions"]:
                exit_i, reason = jj, "time_exit"
        if exit_i is None or exit_i >= len(all_d):
            continue
        xd = all_d[exit_i]
        if reason == "time_exit":
            xl, xs = close.at[xd, long_sym], close.at[xd, short_sym]
        else:
            xl, xs = open_.at[xd, long_sym], open_.at[xd, short_sym]
        if not (np.isfinite(xl) and np.isfinite(xs) and xl > 0 and xs > 0):
            continue
        gross = 0.5 * ((float(xl) / long_px - 1.0) - (float(xs) / short_px - 1.0))
        dv = np.nanmin([
            float(dv_w.at[d, a]) if a in dv_w.columns else np.nan,
            float(dv_w.at[d, b]) if b in dv_w.columns else np.nan,
        ])
        rows.append({
            "method": "M3", "date": d, "symbol": f"{long_sym}/{short_sym}",
            "long_symbol": long_sym, "short_symbol": short_sym,
            "block": None, "side": 1,
            "score": float(abs(spread) / sigma_spread),
            "entry_date": ed, "entry_px": long_px, "exit_px": float(xl),
            "exit_date": xd, "exit_reason": reason, "stop_frac": stop_frac,
            "gross_return": float(gross),
            "prior20_window_dollar_volume": dv,
            "hold_days": float(exit_i - j + 1),
            "void": False, "void_reason": None,
            "entry_slide_minutes": 0, "halt": False,
            "market_return": 0.0,
            "entry_seq": (ed, 0), "exit_seq": (xd, 1),
            "legs": 2,
        })
        busy_until = exit_i
    return rows


# --------------------------------------------------------------------------- #
# Portfolio — one $100,000 account for every method
# --------------------------------------------------------------------------- #
@dataclass
class Position:
    exit_seq: tuple
    symbols: tuple
    slots: int
    risk_dollars: float
    notional: float


def simulate(trades: pd.DataFrame, policy: dict, cost_frac: float,
             risk_scale: float = 1.0, fixed_notional: float | None = None):
    """Run the trades through the one shared account.

    `fixed_notional` puts the same dollars into every trade, so a lucky early
    run cannot buy bigger positions later.  The per-trade average and the
    profit factor are read off that path; the compounding path is what the
    account-level return and decline gates are read off.
    """
    pf = policy["portfolio"]
    short_annual = pf["short_charge_annual"]

    t = trades[~trades["void"].fillna(False)].copy()
    t = t[t["gross_return"].notna()]
    t = t.sort_values(["entry_seq", "score"], ascending=[True, False],
                      ignore_index=True)

    equity = pf["starting_capital"]
    open_pos: list[Position] = []
    taken = []
    equity_curve = []

    for r in t.itertuples(index=False):
        open_pos = [p for p in open_pos if p.exit_seq > r.entry_seq]
        slots_used = sum(p.slots for p in open_pos)
        risk_used = sum(p.risk_dollars for p in open_pos)
        gross_used = sum(p.notional for p in open_pos)
        held = {s for p in open_pos for s in p.symbols}

        syms = ((r.long_symbol, r.short_symbol) if r.legs == 2 else (r.symbol,))
        if any(s in held for s in syms):
            continue
        if slots_used + r.legs > pf["max_slots"]:
            continue

        stop_frac = float(r.stop_frac)
        if not np.isfinite(stop_frac) or stop_frac <= 0:
            continue
        # On the equal-dollar path the account's limits are held against the
        # STARTING capital.  Held against current equity, a losing run shrinks
        # the account, the exposure cap bites, and the run's own losses start
        # choosing which trades it can afford - which is the feedback loop this
        # path exists to remove.
        limit_base = (pf["starting_capital"] if fixed_notional is not None
                      else equity)
        risk_budget = pf["risk_per_position"] * risk_scale * limit_base
        if risk_used + risk_budget > pf["max_total_risk"] * limit_base:
            continue

        cap = (pf["capacity_fraction"] * float(r.prior20_window_dollar_volume)
               if np.isfinite(r.prior20_window_dollar_volume) else np.inf)
        if fixed_notional is not None:
            total_notional = min(fixed_notional * r.legs,
                                 pf["max_leg_notional"] * r.legs, cap * r.legs)
        else:
            total_notional = min(risk_budget / stop_frac,
                                 pf["max_leg_notional"] * r.legs,
                                 cap * r.legs)
        per_leg = total_notional / r.legs
        shares = int(np.floor(per_leg / float(r.entry_px)))
        if shares < pf["min_shares"]:
            continue
        per_leg = shares * float(r.entry_px)
        total_notional = per_leg * r.legs
        if gross_used + total_notional > pf["max_gross_exposure"] * limit_base:
            continue

        # short financing: a two-leg pair is half short, a short single is all
        # short.  Charged per calendar day, which also covers the dividend an
        # unadjusted price hands a short for free.
        short_share = 0.5 if r.legs == 2 else (1.0 if r.side == -1 else 0.0)
        cal_days = float(r.hold_days) * 365.0 / 252.0
        # A one-cent tick is a bigger share of a cheap stock's price, so the
        # flat cost is raised to a tick-based floor plus a 10 bp allowance.
        tick = pf["tick_size"]
        pxs = ([float(r.entry_px)] * 2 if r.legs == 2 else [float(r.entry_px)])
        # one FULL tick crossed twice, as the frozen rulebook words it. The
        # code first charged half that; the independent verifier caught it and
        # the stricter frozen wording is what stands.
        tick_cost = sum(2.0 * tick / px + pf["slippage_allowance"]
                        for px in pxs)
        cost = max(cost_frac, tick_cost)
        cost += short_annual * cal_days / 365.0 * short_share
        net_ret = float(r.gross_return) - cost
        mkt = float(getattr(r, "market_return", 0.0) or 0.0)
        exposure = 0.0 if r.legs == 2 else float(r.side)
        net_market_adj = net_ret - mkt * exposure
        pnl = net_ret * total_notional
        equity += pnl

        open_pos.append(Position(r.exit_seq, syms, r.legs, risk_budget,
                                 total_notional))
        d = r._asdict()
        d.update({"net_return": net_ret,
                  "net_market_adjusted_return": net_market_adj,
                  "cost_frac": cost,
                  "notional": total_notional, "shares": shares,
                  "pnl": pnl, "equity_after": equity})
        taken.append(d)
        equity_curve.append((r.exit_seq[0], equity))

    tk = pd.DataFrame(taken)
    eq = pd.DataFrame(equity_curve, columns=["date", "equity"])
    if len(eq):
        # trades are processed in ENTRY order but stamped with their EXIT date,
        # so the readings must be put back in date order before anything reads
        # a daily return off them
        eq = eq.sort_values("date", kind="stable")
        eq = eq.groupby("date", as_index=False)["equity"].last()
    return tk, eq
