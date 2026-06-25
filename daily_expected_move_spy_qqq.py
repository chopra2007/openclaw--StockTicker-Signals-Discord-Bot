#!/usr/bin/env python3
"""
daily_expected_move_spy_qqq.py
==============================================================================
Daily Expected Move (Daily EM) calculator + charts for SPY and QQQ (or any
optionable ticker), built on options-implied volatility.

It computes, for the nearest *suitable* expiration:

  1. RAW ATM STRADDLE method   : EM = ATM_call_mid + ATM_put_mid
  2. 0.85-ADJUSTED STRADDLE    : EM = raw_straddle * 0.85   (tastytrade-style)
  3. IV method (1-day)         : EM = spot * ATM_IV * sqrt(1/252)   [trading days]
                                 EM = spot * ATM_IV * sqrt(1/365)   [calendar days]
  4. IV method (to-expiration) : EM = spot * ATM_IV * sqrt(T)

and the corresponding upper / lower expected-move levels.

------------------------------------------------------------------------------
DATA SOURCE
------------------------------------------------------------------------------
The default provider is `yfinance`, which returns *delayed, unofficial* Yahoo
Finance data (typically 15-min delayed; options greeks/IV are computed by Yahoo
and are frequently noisy). This is NOT real-time and must not be presented as
such.

The data layer is abstracted behind `OptionDataProvider`. To use a real-time /
paid feed (Tradier, Polygon, IBKR, ThetaData, ORATS, Databento, Cboe LiveVol),
subclass `OptionDataProvider`, implement `get_spot`, `list_expirations`, and
`get_chain`, and pass an instance to `run(provider=...)`. Nothing else changes.

------------------------------------------------------------------------------
IMPORTANT
------------------------------------------------------------------------------
* Expected move is a *probabilistic, non-directional* volatility range, not a
  forecast and not a guaranteed call/put target.
* Upper EM = spot + EM  (the "call side" boundary).
  Lower EM = spot - EM  (the "put side" boundary).
* If the option chain cannot be retrieved, the script stops and says exactly
  what is missing. It never invents prices, IVs, strikes, or expirations.

Usage:
    python3 daily_expected_move_spy_qqq.py
    python3 daily_expected_move_spy_qqq.py --tickers SPY QQQ --outdir ./charts
    python3 daily_expected_move_spy_qqq.py --expiration 2026-06-26
    python3 daily_expected_move_spy_qqq.py --primary iv_252
==============================================================================
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

# Headless-safe matplotlib backend (must be set before pyplot import).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    import mplfinance as mpf
    HAVE_MPF = True
except Exception:
    HAVE_MPF = False

# Constant linking the ATM straddle to the 1-standard-deviation move under
# Black-Scholes (r=q=0): straddle ~= sqrt(2/pi) * S * sigma * sqrt(T)
#                                ~= 0.7979 * (1-sigma move).
STRADDLE_TO_1SD = math.sqrt(2.0 / math.pi)  # 0.79788...
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365


# =============================================================================
# 1. DATA LAYER (swap this out for a paid/broker API)
# =============================================================================
@dataclass
class OptionQuote:
    strike: float
    bid: float
    ask: float
    last: float
    iv: float            # annualized implied vol as a decimal (0.13 = 13%)
    volume: float
    open_interest: float
    last_trade: Optional[datetime] = None

    @property
    def mid(self) -> float:
        # Mid of bid/ask; fall back to last if the book is one-sided/empty.
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0 or self.ask <= 0 or self.bid <= 0:
            return float("nan")
        return (self.ask - self.bid) / m


@dataclass
class Chain:
    expiration: str           # 'YYYY-MM-DD'
    calls: pd.DataFrame       # raw provider frame
    puts: pd.DataFrame
    spot: float
    spot_time: Optional[datetime]
    quote_time: Optional[datetime]
    price_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    history_label: str = ""


class OptionDataProvider:
    """Abstract data provider. Implement these three for any backend."""

    def get_spot(self, ticker: str) -> tuple[float, Optional[datetime], float]:
        """Return (spot_price, spot_time, previous_close)."""
        raise NotImplementedError

    def list_expirations(self, ticker: str) -> list[str]:
        """Return sorted list of 'YYYY-MM-DD' expiration strings."""
        raise NotImplementedError

    def get_chain(self, ticker: str, expiration: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (calls_df, puts_df) with columns:
        strike, bid, ask, lastPrice, impliedVolatility, volume, openInterest, lastTradeDate."""
        raise NotImplementedError

    def get_price_history(self, ticker: str) -> tuple[pd.DataFrame, str]:
        """Return (ohlcv_df, label). Index = DatetimeIndex; cols Open/High/Low/Close/Volume."""
        raise NotImplementedError


class YFinanceProvider(OptionDataProvider):
    """Delayed, unofficial Yahoo Finance data via the `yfinance` package."""

    def __init__(self):
        import yfinance as yf  # imported lazily so the module loads without it
        self._yf = yf
        self._cache: dict[str, object] = {}

    def _tk(self, ticker: str):
        if ticker not in self._cache:
            self._cache[ticker] = self._yf.Ticker(ticker)
        return self._cache[ticker]

    def get_spot(self, ticker: str):
        t = self._tk(ticker)
        fi = t.fast_info
        spot = float(fi["lastPrice"])
        prev = float(fi.get("previousClose")) if fi.get("previousClose") else float("nan")
        spot_time = None
        try:
            h = t.history(period="1d", interval="1d")
            if len(h):
                spot_time = h.index[-1].to_pydatetime()
        except Exception:
            pass
        return spot, spot_time, prev

    def list_expirations(self, ticker: str):
        return list(self._tk(ticker).options)

    def get_chain(self, ticker: str, expiration: str):
        oc = self._tk(ticker).option_chain(expiration)
        return oc.calls.copy(), oc.puts.copy()

    def get_price_history(self, ticker: str):
        """Best-effort intraday; fall back to daily. Returns (df, label)."""
        t = self._tk(ticker)
        attempts = [
            (dict(period="5d", interval="5m"),  "5-minute candles, last 5 trading days"),
            (dict(period="10d", interval="15m"), "15-minute candles, last 10 trading days"),
            (dict(period="3mo", interval="1d"),  "daily candles, last 3 months"),
        ]
        for kw, label in attempts:
            try:
                h = t.history(**kw)
                if h is not None and len(h) >= 5:
                    h = h[["Open", "High", "Low", "Close", "Volume"]].dropna()
                    if len(h) >= 5:
                        return h, label
            except Exception:
                continue
        return pd.DataFrame(), "no price history available"


# =============================================================================
# 2. TIME / EXPIRATION SELECTION
# =============================================================================
def now_eastern() -> datetime:
    """Current time in US/Eastern (handles DST if zoneinfo+tzdata present)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: assume EDT (UTC-4). Good enough for market-hours gating.
        return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))


def market_is_open(now_et: datetime) -> bool:
    """NYSE regular session 09:30-16:00 ET, Mon-Fri. Ignores holidays."""
    if now_et.weekday() >= 5:
        return False
    return time(9, 30) <= now_et.time() <= time(16, 0)


def select_expiration(expirations: list[str], now_et: datetime) -> tuple[str, str]:
    """Pick the expiration to use and a human label.

    Rule (per spec):
      * If market is open AND today is an expiration AND there is still
        meaningful time left (before ~15:30 ET) -> use today ("same-day").
      * Otherwise -> use the next listed expiration strictly after today
        ("next listed expiration / next session").
    """
    if not expirations:
        raise RuntimeError("No expirations returned by the data provider.")
    today_iso = now_et.date().isoformat()
    open_now = market_is_open(now_et)
    meaningful_time = now_et.time() <= time(15, 30)

    if today_iso in expirations and open_now and meaningful_time:
        return today_iso, "same-day to expiration (0DTE, market open)"

    for e in expirations:
        if e > today_iso:
            why = "next listed expiration / next session"
            if today_iso in expirations:
                why += " (today's expiry skipped: market closed or <30m left)"
            return e, why

    # Only past/expired expirations remain.
    return expirations[-1], "front-month fallback (no future expirations listed)"


def time_to_expiration(expiration: str, now_et: datetime) -> dict:
    """Compute calendar/trading days to expiration and year-fractions T."""
    exp_d = date.fromisoformat(expiration)
    # Expiration is at the close (16:00 ET) of exp_d.
    exp_dt = datetime.combine(exp_d, time(16, 0), tzinfo=now_et.tzinfo)
    cal_seconds = max((exp_dt - now_et).total_seconds(), 0.0)
    calendar_days = cal_seconds / 86400.0

    # Trading days: count weekdays from tomorrow through exp_d inclusive,
    # but never less than the same-day fraction.
    if exp_d <= now_et.date():
        trading_days = max(cal_seconds / 86400.0, 0.0)
    else:
        d = now_et.date() + timedelta(days=1)
        td = 0
        while d <= exp_d:
            if d.weekday() < 5:
                td += 1
            d += timedelta(days=1)
        trading_days = float(max(td, 1))

    return {
        "calendar_days": calendar_days,
        "trading_days": trading_days,
        "T_252": trading_days / TRADING_DAYS_PER_YEAR,
        "T_365": calendar_days / CALENDAR_DAYS_PER_YEAR,
    }


# =============================================================================
# 3. ATM STRIKE SELECTION
# =============================================================================
def _row_to_quote(row: pd.Series) -> OptionQuote:
    lt = row.get("lastTradeDate")
    if isinstance(lt, pd.Timestamp):
        lt = lt.to_pydatetime()
    return OptionQuote(
        strike=float(row["strike"]),
        bid=float(row.get("bid") or 0.0),
        ask=float(row.get("ask") or 0.0),
        last=float(row.get("lastPrice") or 0.0),
        iv=float(row.get("impliedVolatility") or float("nan")),
        volume=float(row.get("volume") or 0.0),
        open_interest=float(row.get("openInterest") or 0.0),
        last_trade=lt,
    )


def select_atm(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
               max_spread_pct: float = 0.20) -> tuple[OptionQuote, OptionQuote, list[str]]:
    """Choose the ATM strike (closest to spot present in both call & put books).

    If that strike is illiquid (zero bid, missing IV, or a spread wider than
    `max_spread_pct`), step to the next-closest strike and record why.
    """
    notes: list[str] = []
    common = sorted(set(calls["strike"]).intersection(set(puts["strike"])),
                    key=lambda k: abs(k - spot))
    if not common:
        raise RuntimeError("No common strikes between calls and puts.")

    def quotes_for(strike):
        c = _row_to_quote(calls[calls["strike"] == strike].iloc[0])
        p = _row_to_quote(puts[puts["strike"] == strike].iloc[0])
        return c, p

    def healthy(c: OptionQuote, p: OptionQuote) -> bool:
        for q in (c, p):
            if q.bid <= 0 or q.ask <= 0:
                return False
            if not math.isfinite(q.spread_pct) or q.spread_pct > max_spread_pct:
                return False
        return True

    chosen = common[0]
    c, p = quotes_for(chosen)
    if not healthy(c, p):
        for alt in common[1:6]:
            ca, pa = quotes_for(alt)
            if healthy(ca, pa):
                notes.append(
                    f"ATM moved from {chosen:g} to {alt:g}: nearest strike had a "
                    f"zero bid / wide spread / missing IV."
                )
                chosen, c, p = alt, ca, pa
                break
        else:
            notes.append(
                f"All near-money strikes around {chosen:g} look illiquid; "
                f"keeping closest-to-spot strike {chosen:g} and flagging it."
            )
    return c, p, notes


# =============================================================================
# 4. EXPECTED-MOVE CALCULATIONS
# =============================================================================
def implied_iv_from_straddle(straddle: float, spot: float, T: float) -> float:
    """Back out the straddle-implied annualized IV (consistency cross-check).

    Inverts straddle ~= sqrt(2/pi) * S * sigma * sqrt(T).
    """
    if spot <= 0 or T <= 0:
        return float("nan")
    return straddle / (STRADDLE_TO_1SD * spot * math.sqrt(T))


def calculate_expected_moves(spot: float, call: OptionQuote, put: OptionQuote,
                             tte: dict, straddle_multiplier: float = 0.85) -> dict:
    """All expected-move flavors + levels for one ticker."""
    call_mid, put_mid = call.mid, put.mid
    raw = call_mid + put_mid
    adj = raw * straddle_multiplier

    call_iv = call.iv if math.isfinite(call.iv) else float("nan")
    put_iv = put.iv if math.isfinite(put.iv) else float("nan")
    ivs = [v for v in (call_iv, put_iv) if math.isfinite(v)]
    atm_iv = float(np.mean(ivs)) if ivs else float("nan")

    def iv_em(T):
        return spot * atm_iv * math.sqrt(T) if math.isfinite(atm_iv) and T > 0 else float("nan")

    iv_252 = iv_em(1 / TRADING_DAYS_PER_YEAR)
    iv_365 = iv_em(1 / CALENDAR_DAYS_PER_YEAR)
    iv_to_exp = iv_em(tte["T_252"])  # default: trading-day basis

    straddle_iv = implied_iv_from_straddle(raw, spot, tte["T_252"])

    return {
        "call_mid": call_mid, "put_mid": put_mid,
        "raw_straddle_em": raw, "raw_straddle_em_pct": raw / spot,
        "adjusted_straddle_em": adj, "adjusted_straddle_em_pct": adj / spot,
        "straddle_multiplier": straddle_multiplier,
        "atm_iv": atm_iv, "call_iv": call_iv, "put_iv": put_iv,
        "straddle_implied_iv": straddle_iv,
        "iv_em_252": iv_252, "iv_em_252_pct": iv_252 / spot,
        "iv_em_365": iv_365, "iv_em_365_pct": iv_365 / spot,
        "iv_em_to_expiration": iv_to_exp, "iv_em_to_expiration_pct": iv_to_exp / spot,
    }


def em_levels(spot: float, em: float) -> tuple[float, float]:
    return spot + em, spot - em


# =============================================================================
# 5. VALIDATION / SANITY CHECKS
# =============================================================================
def validate(ticker: str, spot: float, atm_strike: float, call: OptionQuote,
             put: OptionQuote, em: dict, tte: dict, exp_label: str) -> list[str]:
    out: list[str] = []

    # 1. ATM strike closest to spot.
    out.append(f"[{'OK' if abs(atm_strike - spot) <= 2.5 else 'CHECK'}] "
               f"ATM strike {atm_strike:g} vs spot {spot:.2f} "
               f"(diff {spot - atm_strike:+.2f}).")

    # 2. Bid/ask spreads.
    for leg, q in (("call", call), ("put", put)):
        flag = "OK" if math.isfinite(q.spread_pct) and q.spread_pct <= 0.10 else "WIDE"
        out.append(f"[{flag}] {leg} spread {q.bid:.2f}/{q.ask:.2f} "
                   f"= {q.spread_pct*100:.1f}% of mid.")

    # 3. Call vs put IV closeness (put-call parity => should match at one strike).
    if math.isfinite(em["call_iv"]) and math.isfinite(em["put_iv"]):
        gap = abs(em["call_iv"] - em["put_iv"])
        flag = "OK" if gap <= 0.02 else "SKEW"
        out.append(f"[{flag}] call IV {em['call_iv']*100:.2f}% vs put IV "
                   f"{em['put_iv']*100:.2f}% (gap {gap*100:.2f} vol pts).")

    # 4 & 5. Method agreement; flag disagreement > 20%.
    methods = {"raw straddle": em["raw_straddle_em"],
               "0.85 straddle": em["adjusted_straddle_em"],
               "IV(252)": em["iv_em_252"]}
    vals = [v for v in methods.values() if math.isfinite(v)]
    if vals:
        lo, hi = min(vals), max(vals)
        spread = (hi - lo) / lo if lo else float("inf")
        flag = "OK" if spread <= 0.20 else "DISAGREE"
        out.append(f"[{flag}] method spread {spread*100:.1f}% "
                   f"(low {lo:.3f}, high {hi:.3f}).")

    # IV self-consistency cross-check.
    if math.isfinite(em["straddle_implied_iv"]) and math.isfinite(em["atm_iv"]):
        rel = abs(em["straddle_implied_iv"] - em["atm_iv"]) / em["atm_iv"]
        flag = "OK" if rel <= 0.05 else "IV-MISMATCH"
        out.append(f"[{flag}] Yahoo ATM IV {em['atm_iv']*100:.2f}% vs "
                   f"straddle-implied IV {em['straddle_implied_iv']*100:.2f}% "
                   f"({rel*100:.1f}% apart).")

    # 6. Expiration classification.
    out.append(f"[INFO] expiration basis: {exp_label}; "
               f"calendar days={tte['calendar_days']:.3f}, "
               f"trading days={tte['trading_days']:.0f}.")

    # 7. Timestamp compatibility.
    ct = call.last_trade
    if ct:
        out.append(f"[INFO] option last-trade ~{ct:%Y-%m-%d %H:%M %Z}; "
                   f"compare to spot timestamp before trusting freshness.")
    return out


# =============================================================================
# 6. CHARTING
# =============================================================================
def generate_chart(ticker: str, chain: Chain, spot: float, upper: float,
                   lower: float, em: float, method_label: str, exp: str,
                   outdir: str, data_ts: str) -> Optional[str]:
    hist = chain.price_history
    if hist is None or len(hist) < 5:
        print(f"  [chart] no price history for {ticker}; skipping chart.")
        return None

    path = f"{outdir.rstrip('/')}/{ticker}_daily_em.png"
    band = max(em * 0.18, spot * 0.0008)  # shaded-zone half-thickness
    title = (f"{ticker}  Daily Expected Move  (±${em:,.2f} / ±{em/spot*100:.2f}%)\n"
             f"data {data_ts}  |  exp {exp}  |  method: {method_label}")

    ymin = min(float(hist["Low"].min()), lower) - band * 1.5
    ymax = max(float(hist["High"].max()), upper) + band * 1.5

    if HAVE_MPF:
        mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                                   wick="inherit", volume="in")
        style = mpf.make_mpf_style(base_mpf_style="yahoo", marketcolors=mc,
                                   gridstyle=":", gridcolor="#d8d8d8")
        fig, axes = mpf.plot(hist, type="candle", style=style, figsize=(13.5, 7.2),
                             returnfig=True, volume=False, ylim=(ymin, ymax),
                             tight_layout=True, xrotation=0)
        ax = axes[0]
    else:
        fig, ax = plt.subplots(figsize=(13.5, 7.2))
        ax.plot(range(len(hist)), hist["Close"].values, color="#1f3b6f", lw=1.3)
        ax.set_ylim(ymin, ymax)
        ax.set_xlim(0, len(hist) - 1)

    # Level lines.
    ax.axhline(upper, color="#c62828", lw=1.6, ls="--", zorder=5)
    ax.axhline(lower, color="#2e7d32", lw=1.6, ls="--", zorder=5)
    ax.axhline(spot, color="#1565c0", lw=1.4, ls="-", zorder=5)

    # Shaded zones near the EM boundaries.
    ax.axhspan(upper - band, upper + band, color="#ef5350", alpha=0.13, zorder=1)
    ax.axhspan(lower - band, lower + band, color="#66bb6a", alpha=0.13, zorder=1)

    # Right-side price labels.
    def label(y, text, color):
        ax.annotate(text, xy=(1.0, y), xycoords=("axes fraction", "data"),
                    xytext=(6, 0), textcoords="offset points", va="center",
                    ha="left", fontsize=9.5, fontweight="bold", color="white",
                    bbox=dict(boxstyle="round,pad=0.3", fc=color, ec="none"),
                    annotation_clip=False, zorder=6)

    label(upper, f"Upper EM  {upper:,.2f}", "#c62828")
    label(spot,  f"Spot  {spot:,.2f}", "#1565c0")
    label(lower, f"Lower EM  {lower:,.2f}", "#2e7d32")

    ax.set_title(title, fontsize=11.5, fontweight="bold")
    ax.margins(x=0.01)
    fig.subplots_adjust(right=0.86)
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [chart] saved {path}")
    return path


# =============================================================================
# 7. SUMMARY PRINTING
# =============================================================================
def primary_em(em: dict, choice: str) -> tuple[str, float]:
    table = {
        "raw_straddle": ("Raw ATM straddle", em["raw_straddle_em"]),
        "adj_straddle": ("0.85-adjusted straddle", em["adjusted_straddle_em"]),
        "iv_252": ("IV method (252-day)", em["iv_em_252"]),
        "iv_365": ("IV method (365-day)", em["iv_em_365"]),
    }
    return table.get(choice, table["raw_straddle"])


def print_summary(ticker: str, chain: Chain, atm_strike: float, call: OptionQuote,
                  put: OptionQuote, em: dict, tte: dict, exp: str, exp_label: str,
                  checks: list[str], primary_choice: str, data_ts: str) -> dict:
    pname, pval = primary_em(em, primary_choice)
    up, lo = em_levels(chain.spot, pval)

    print("\n" + "=" * 78)
    print(f" {ticker}  —  Daily Expected Move  (source: yfinance / DELAYED, unofficial)")
    print("=" * 78)
    print(" Table 1 — Inputs & Option Pricing")
    print(" " + "-" * 60)
    rows1 = [
        ("Data timestamp", data_ts),
        ("Spot price", f"${chain.spot:,.2f}"),
        ("Selected expiration", f"{exp}  ({exp_label})"),
        ("Time to expiration", f"{tte['calendar_days']:.3f} cal days / "
                               f"{tte['trading_days']:.0f} trading day(s)"),
        ("ATM strike", f"{atm_strike:g}"),
        ("Call bid / ask / mid", f"{call.bid:.2f} / {call.ask:.2f} / {call.mid:.3f}"),
        ("Call IV", f"{em['call_iv']*100:.2f}%"),
        ("Call vol / OI", f"{call.volume:,.0f} / {call.open_interest:,.0f}"),
        ("Put bid / ask / mid", f"{put.bid:.2f} / {put.ask:.2f} / {put.mid:.3f}"),
        ("Put IV", f"{em['put_iv']*100:.2f}%"),
        ("Put vol / OI", f"{put.volume:,.0f} / {put.open_interest:,.0f}"),
    ]
    for k, v in rows1:
        print(f"   {k:<22}: {v}")

    print("\n Table 2 — Expected-Move Calculations & Levels")
    print(" " + "-" * 60)
    rows2 = [
        ("Raw ATM straddle EM", f"${em['raw_straddle_em']:.3f}  "
                                f"({em['raw_straddle_em_pct']*100:.3f}%)"),
        ("0.85 adjusted straddle EM", f"${em['adjusted_straddle_em']:.3f}  "
                                      f"({em['adjusted_straddle_em_pct']*100:.3f}%)"),
        ("IV EM — 252-day scaling", f"${em['iv_em_252']:.3f}  "
                                    f"({em['iv_em_252_pct']*100:.3f}%)"),
        ("IV EM — 365-day scaling", f"${em['iv_em_365']:.3f}  "
                                    f"({em['iv_em_365_pct']*100:.3f}%)"),
        ("IV EM — to expiration", f"${em['iv_em_to_expiration']:.3f}  "
                                  f"({em['iv_em_to_expiration_pct']*100:.3f}%)"),
        ("Blended ATM IV (Yahoo)", f"{em['atm_iv']*100:.2f}%"),
        ("Straddle-implied IV (chk)", f"{em['straddle_implied_iv']*100:.2f}%"),
        ("PRIMARY Daily EM", f"{pname}: ±${pval:.3f}  ({pval/chain.spot*100:.3f}%)"),
        ("Upper EM level", f"${up:,.2f}"),
        ("Lower EM level", f"${lo:,.2f}"),
    ]
    for k, v in rows2:
        print(f"   {k:<26}: {v}")

    print("\n Validation / sanity checks")
    print(" " + "-" * 60)
    for c in checks:
        print(f"   {c}")

    return {"ticker": ticker, "spot": chain.spot, "primary_name": pname,
            "primary_em": pval, "upper": up, "lower": lo, "exp": exp,
            "em": em, "tte": tte}


# =============================================================================
# 8. ORCHESTRATION
# =============================================================================
def analyze_ticker(provider: OptionDataProvider, ticker: str, now_et: datetime,
                   outdir: str, primary_choice: str, multiplier: float,
                   expiration_override: Optional[str]) -> Optional[dict]:
    print(f"\n>>> {ticker}: fetching data ...")
    try:
        spot, spot_time, prev_close = provider.get_spot(ticker)
    except Exception as e:
        print(f"  !! could not fetch spot for {ticker}: {e}")
        return None
    if not spot or not math.isfinite(spot):
        print(f"  !! no valid spot price for {ticker}; stopping this ticker.")
        return None

    try:
        exps = provider.list_expirations(ticker)
    except Exception as e:
        print(f"  !! could not list expirations for {ticker}: {e}")
        return None
    if not exps:
        print(f"  !! no option expirations returned for {ticker}; cannot compute EM.")
        return None

    if expiration_override:
        if expiration_override not in exps:
            print(f"  !! requested expiration {expiration_override} not listed "
                  f"for {ticker}. Available: {exps[:6]} ...")
            return None
        exp, exp_label = expiration_override, "user-specified expiration"
    else:
        exp, exp_label = select_expiration(exps, now_et)

    try:
        calls, puts = provider.get_chain(ticker, exp)
    except Exception as e:
        print(f"  !! could not fetch option chain for {ticker} {exp}: {e}")
        return None
    if calls is None or puts is None or calls.empty or puts.empty:
        print(f"  !! option chain for {ticker} {exp} is EMPTY — cannot compute EM. "
              f"(Nothing invented.)")
        return None

    call, put, atm_notes = select_atm(calls, puts, spot)
    tte = time_to_expiration(exp, now_et)
    em = calculate_expected_moves(spot, call, put, tte, multiplier)

    # Data timestamp string (label as delayed).
    qt = call.last_trade
    data_ts = (f"{qt:%Y-%m-%d %H:%M UTC}" if qt else
               (f"{spot_time:%Y-%m-%d}" if spot_time else "unknown")) + " (DELAYED)"

    hist, hist_label = provider.get_price_history(ticker)
    chain = Chain(expiration=exp, calls=calls, puts=puts, spot=spot,
                  spot_time=spot_time, quote_time=qt, price_history=hist,
                  history_label=hist_label)

    checks = validate(ticker, spot, call.strike, call, put, em, tte, exp_label)
    for n in atm_notes:
        checks.append(f"[INFO] {n}")

    result = print_summary(ticker, chain, call.strike, call, put, em, tte,
                           exp, exp_label, checks, primary_choice, data_ts)

    pname, pval = primary_em(em, primary_choice)
    up, lo = em_levels(spot, pval)
    method_label = f"{pname} (primary)"
    chart_path = generate_chart(ticker, chain, spot, up, lo, pval, method_label,
                                exp, outdir, data_ts)
    result["chart"] = chart_path
    result["history_label"] = hist_label
    return result


def run(tickers: list[str], outdir: str = ".", provider: Optional[OptionDataProvider] = None,
        primary_choice: str = "raw_straddle", multiplier: float = 0.85,
        expiration_override: Optional[str] = None) -> list[dict]:
    if provider is None:
        try:
            provider = YFinanceProvider()
        except Exception as e:
            print("FATAL: yfinance unavailable and no provider supplied. "
                  f"Install it (`pip install yfinance`) or pass a provider. ({e})")
            sys.exit(2)

    now_et = now_eastern()
    print("#" * 78)
    print(f"# Daily Expected Move  |  now (ET) = {now_et:%Y-%m-%d %H:%M %Z}  "
          f"|  market {'OPEN' if market_is_open(now_et) else 'CLOSED'}")
    print(f"# DATA IS DELAYED / UNOFFICIAL (yfinance / Yahoo). Not for execution.")
    print("#" * 78)

    results = []
    for tk in tickers:
        r = analyze_ticker(provider, tk, now_et, outdir, primary_choice,
                           multiplier, expiration_override)
        if r:
            results.append(r)

    if not results:
        print("\nNo results produced. See messages above for exactly what data was "
              "missing. Nothing was invented.")
    return results


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Daily Expected Move for SPY/QQQ (or any optionable ticker).")
    p.add_argument("--tickers", nargs="+", default=["SPY", "QQQ"])
    p.add_argument("--outdir", default=".")
    p.add_argument("--primary", default="raw_straddle",
                   choices=["raw_straddle", "adj_straddle", "iv_252", "iv_365"],
                   help="Which method to treat as the primary Daily EM (default: raw straddle).")
    p.add_argument("--multiplier", type=float, default=0.85,
                   help="Straddle shrink multiplier (default 0.85; source-dependent heuristic).")
    p.add_argument("--expiration", default=None,
                   help="Force a specific expiration YYYY-MM-DD (otherwise auto-selected).")
    return p.parse_args(argv)


if __name__ == "__main__":
    a = parse_args()
    run(a.tickers, outdir=a.outdir, primary_choice=a.primary,
        multiplier=a.multiplier, expiration_override=a.expiration)
