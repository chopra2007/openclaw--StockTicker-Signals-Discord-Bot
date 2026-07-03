"""Daily Expected Move (!em command).

Computes the options-implied 1-day expected move for an allowed ticker from the
ATM straddle and ATM implied volatility, picks the right expiration based on
market hours (today's expiry while the market is open, next session once it has
closed), renders a candlestick chart with the expected-move band, and builds a
compact Discord embed.

Data source is yfinance — delayed (~15 min), unofficial. yfinance is blocking,
so all network work runs in a ThreadPoolExecutor (same pattern as
``scanners.options``). Nothing here is presented as real-time.

Public surface used by the !em command handler:
    compute_em(ticker, exec)   -> ExpectedMoveResult            (async; raises EMUnavailable)
    render_chart(result)       -> bytes | None                  (PNG; lazy matplotlib)
    build_em_embed(result)     -> dict                          (Discord embed)
    chart_filename(ticker)     -> str
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from consensus_engine import config as _cfg
from consensus_engine.utils import prices  # #57 OHLCV choke-point (Schwab primary)

from consensus_engine import config as cfg

log = logging.getLogger("consensus_engine.scanners.expected_move")

# Constant linking the ATM straddle to the 1-standard-deviation move under
# Black-Scholes (r=q=0): straddle ~= sqrt(2/pi) * S * sigma * sqrt(T) ~= 0.8 * 1SD.
STRADDLE_TO_1SD = math.sqrt(2.0 / math.pi)  # 0.79788...
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365


class EMUnavailable(Exception):
    """Raised when the expected move cannot be computed. The message is
    user-facing (already friendly) and gets sent straight to Discord."""


@dataclass
class OptionQuote:
    strike: float
    bid: float
    ask: float
    last: float
    iv: float            # annualized implied vol, decimal (0.13 == 13%)
    volume: float
    open_interest: float
    last_trade: Optional[datetime] = None

    @property
    def mid(self) -> float:
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
class ExpectedMoveResult:
    ticker: str
    spot: float
    expiration: str
    session_label: str            # "Today (market open)" / "Next session" ...
    market_open: bool
    atm_strike: float
    call: OptionQuote
    put: OptionQuote
    em: dict                      # all expected-move flavors (see calculate_expected_moves)
    primary_em: float             # raw straddle (headline)
    upper: float
    lower: float
    iv_band_upper: float          # IV 1-SD (252) band
    iv_band_lower: float
    tte: dict
    quote_ts: Optional[datetime]  # ATM option last-trade time (UTC)
    history: pd.DataFrame
    history_label: str
    source: str = "yfinance"      # #57: feed that served this chain — "schwab" (real-time) or "yfinance" (delayed)


# ---------------------------------------------------------------------------
# Time / expiration selection
# ---------------------------------------------------------------------------
def now_eastern() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: assume EDT (UTC-4). Enough for market-hours gating.
        return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))


def market_is_open(now_et: datetime) -> bool:
    """True if the NYSE regular session is open at now_et — holiday- and
    early-close-aware, via the shared calendar in utils.time_context."""
    from consensus_engine.utils.time_context import nyse_open_now
    return nyse_open_now(now_et)


def select_expiration(expirations: list[str], now_et: datetime) -> tuple[str, str]:
    """Pick the expiration + a human session label.

    Market open and today is an expiration with meaningful time left (before
    ~15:30 ET) -> today's expiry. Otherwise -> next listed expiration after
    today.
    """
    if not expirations:
        raise EMUnavailable("No option expirations are listed for this ticker.")
    today_iso = now_et.date().isoformat()
    open_now = market_is_open(now_et)

    if today_iso in expirations and open_now and now_et.time() <= time(15, 30):
        return today_iso, "Today (market open)"

    for e in expirations:
        if e > today_iso:
            label = "Next session" if open_now else (
                "Next session (market closed)" if now_et.weekday() < 5
                else "Next session (weekend)")
            return e, label

    return expirations[-1], "Front-month (no future expirations listed)"


def time_to_expiration(expiration: str, now_et: datetime) -> dict:
    exp_d = date.fromisoformat(expiration)
    exp_dt = datetime.combine(exp_d, time(16, 0), tzinfo=now_et.tzinfo)
    cal_seconds = max((exp_dt - now_et).total_seconds(), 0.0)
    calendar_days = cal_seconds / 86400.0

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


# ---------------------------------------------------------------------------
# ATM strike selection
# ---------------------------------------------------------------------------
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
               max_spread_pct: float = 0.25,
               min_open_interest: float = 0.0) -> tuple[OptionQuote, OptionQuote]:
    """Closest-to-spot strike present in both books; step out if it is illiquid
    (zero bid, missing IV, wide spread, or below the OI floor)."""
    common = sorted(set(calls["strike"]).intersection(set(puts["strike"])),
                    key=lambda k: abs(k - spot))
    if not common:
        raise EMUnavailable("No matching call/put strikes for this expiration.")

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
            if q.open_interest < min_open_interest:
                return False
        return True

    for strike in common[:6]:
        c, p = quotes_for(strike)
        if healthy(c, p):
            return c, p

    # Nothing clean — surface the closest strike's problem rather than guessing.
    raise EMUnavailable(
        "Options for this ticker/expiration are too illiquid for a reliable "
        "expected move (zero bids, wide spreads, or thin open interest)."
    )


# ---------------------------------------------------------------------------
# Expected-move math
# ---------------------------------------------------------------------------
def implied_iv_from_straddle(straddle: float, spot: float, T: float) -> float:
    """Back out the straddle-implied annualized IV (consistency cross-check)."""
    if spot <= 0 or T <= 0:
        return float("nan")
    return straddle / (STRADDLE_TO_1SD * spot * math.sqrt(T))


def calculate_expected_moves(spot: float, call: OptionQuote, put: OptionQuote,
                             tte: dict, multiplier: float = 0.85) -> dict:
    raw = call.mid + put.mid
    adj = raw * multiplier

    ivs = [v for v in (call.iv, put.iv) if math.isfinite(v)]
    atm_iv = float(np.mean(ivs)) if ivs else float("nan")

    def iv_em(T):
        return spot * atm_iv * math.sqrt(T) if math.isfinite(atm_iv) and T > 0 else float("nan")

    return {
        "raw_straddle_em": raw, "raw_straddle_em_pct": raw / spot,
        "adjusted_straddle_em": adj, "adjusted_straddle_em_pct": adj / spot,
        "multiplier": multiplier,
        "atm_iv": atm_iv,
        "straddle_implied_iv": implied_iv_from_straddle(raw, spot, tte["T_252"]),
        "iv_em_252": iv_em(1 / TRADING_DAYS_PER_YEAR),
        "iv_em_365": iv_em(1 / CALENDAR_DAYS_PER_YEAR),
        "iv_em_to_expiration": iv_em(tte["T_252"]),
    }


# ---------------------------------------------------------------------------
# Data fetch (blocking yfinance, runs in executor)
# ---------------------------------------------------------------------------
def _schwab_bundle(ticker: str, now_et: datetime) -> Optional[dict]:
    """#57: Schwab real-time version of _fetch_bundle. Returns the SAME dict shape
    or None on any failure (caller falls back to yfinance). The chain DataFrames
    carry yfinance columns incl. impliedVolatility as a FRACTION (already ÷100 in
    the client), so select_atm / _row_to_quote work unchanged."""
    try:
        from consensus_engine.scanners import schwab_client
        ch = schwab_client.get_option_chain(ticker)
    except Exception as e:
        log.debug("em schwab chain fetch failed for %s: %s", ticker, e)
        return None
    if ch is None or not ch.expirations:
        return None
    spot = ch.underlying_price
    if not spot or not math.isfinite(spot):
        return None
    exp, session_label = select_expiration(ch.expirations, now_et)
    be = ch.by_expiry(exp)
    calls, puts = be.calls.copy(), be.puts.copy()
    if calls is None or puts is None or calls.empty or puts.empty:
        return None
    history, history_label = _fetch_history(ticker)
    return {
        "spot": spot, "expiration": exp, "session_label": session_label,
        "calls": calls, "puts": puts,
        "history": history, "history_label": history_label,
        "source": "schwab",
    }


def _fetch_bundle(ticker: str, now_et: datetime) -> dict:
    """Blocking: spot, chosen expiration, that chain, and price history."""
    # #57: Schwab real-time chain PRIMARY (native greeks + IV); yfinance fallback.
    if _cfg.get("features.schwab_options.enabled", False):
        bundle = _schwab_bundle(ticker, now_et)
        if bundle is not None:
            return bundle

    import yfinance as yf
    t = yf.Ticker(ticker)

    try:
        spot = float(t.fast_info["lastPrice"])
    except Exception as e:
        raise EMUnavailable(f"Could not fetch a price for `${ticker}`.") from e
    if not spot or not math.isfinite(spot):
        raise EMUnavailable(f"No valid price for `${ticker}`.")

    exps = list(t.options or [])
    if not exps:
        raise EMUnavailable(
            f"`${ticker}` has no listed options, so an options-implied "
            f"expected move can't be computed."
        )
    exp, session_label = select_expiration(exps, now_et)

    try:
        oc = t.option_chain(exp)
        calls, puts = oc.calls.copy(), oc.puts.copy()
    except Exception as e:
        raise EMUnavailable(f"Could not fetch the option chain for `${ticker}` {exp}.") from e
    if calls is None or puts is None or calls.empty or puts.empty:
        raise EMUnavailable(f"The option chain for `${ticker}` {exp} came back empty.")

    history, history_label = _fetch_history(ticker)

    return {
        "spot": spot, "expiration": exp, "session_label": session_label,
        "calls": calls, "puts": puts,
        "history": history, "history_label": history_label,
        "source": "yfinance",
    }


def _fetch_history(ticker: str) -> tuple[pd.DataFrame, str]:
    """Best-effort intraday candles; fall back to daily. #57: routed through the
    OHLCV choke-point (Schwab primary, yfinance fallback) — same shape either way."""
    attempts = [
        (dict(period="5d", interval="5m"),  "5-minute candles · last 5 sessions"),
        (dict(period="10d", interval="15m"), "15-minute candles · last 10 sessions"),
        (dict(period="3mo", interval="1d"),  "daily candles · last 3 months"),
    ]
    for kw, label in attempts:
        try:
            h = prices.fetch_history(ticker, **kw)
            if h is not None and len(h) >= 5:
                h = h[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(h) >= 5:
                    return h, label
        except Exception:
            continue
    return pd.DataFrame(), "no price history"


async def compute_em(ticker: str, executor=None) -> ExpectedMoveResult:
    """Compute the expected move for any optionable ticker. Raises EMUnavailable
    (user-facing message) when it can't — no options listed, empty chain, or
    options too illiquid (the open-interest floor is the only liquidity gate)."""
    ticker = ticker.upper()
    now_et = now_eastern()
    loop = asyncio.get_running_loop()
    bundle = await loop.run_in_executor(executor, _fetch_bundle, ticker, now_et)

    spot = bundle["spot"]
    min_oi = float(cfg.get("expected_move.min_atm_open_interest", 100))
    multiplier = float(cfg.get("expected_move.multiplier", 0.85))

    call, put = select_atm(bundle["calls"], bundle["puts"], spot,
                           min_open_interest=min_oi)
    tte = time_to_expiration(bundle["expiration"], now_et)
    em = calculate_expected_moves(spot, call, put, tte, multiplier)

    primary = em["raw_straddle_em"]
    iv252 = em["iv_em_252"]

    return ExpectedMoveResult(
        ticker=ticker, spot=spot, expiration=bundle["expiration"],
        session_label=bundle["session_label"],
        market_open=market_is_open(now_et),
        atm_strike=call.strike, call=call, put=put, em=em,
        primary_em=primary, upper=spot + primary, lower=spot - primary,
        iv_band_upper=spot + iv252 if math.isfinite(iv252) else spot + primary,
        iv_band_lower=spot - iv252 if math.isfinite(iv252) else spot - primary,
        tte=tte, quote_ts=call.last_trade,
        history=bundle["history"], history_label=bundle["history_label"],
        source=bundle.get("source", "yfinance"),
    )


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def chart_filename(ticker: str) -> str:
    return f"{ticker.upper()}_em.png"


def render_chart(result: ExpectedMoveResult) -> Optional[bytes]:
    """Render a candlestick chart with the expected-move band to PNG bytes.
    Returns None if there is no usable price history. matplotlib is imported
    lazily so the module loads (and the calc path runs) without it."""
    hist = result.history
    if hist is None or len(hist) < 5:
        return None

    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        import mplfinance as mpf
        have_mpf = True
    except Exception:
        have_mpf = False

    spot, upper, lower, em = result.spot, result.upper, result.lower, result.primary_em
    band = max(em * 0.18, spot * 0.0008)
    title = (f"{result.ticker}  Daily Expected Move  "
             f"(±${em:,.2f} / ±{em / spot * 100:.2f}%)\n"
             f"exp {result.expiration} · {result.session_label} · ATM straddle")
    ymin = min(float(hist["Low"].min()), lower) - band * 1.5
    ymax = max(float(hist["High"].max()), upper) + band * 1.5

    if have_mpf:
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

    ax.set_ylabel("")  # drop default "Price" label so right-edge labels read clean
    ax.axhline(upper, color="#c62828", lw=1.6, ls="--", zorder=5)
    ax.axhline(lower, color="#2e7d32", lw=1.6, ls="--", zorder=5)
    ax.axhline(spot, color="#1565c0", lw=1.4, ls="-", zorder=5)
    ax.axhspan(upper - band, upper + band, color="#ef5350", alpha=0.13, zorder=1)
    ax.axhspan(lower - band, lower + band, color="#66bb6a", alpha=0.13, zorder=1)

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

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------
def _fmt_quote_time(result: ExpectedMoveResult) -> str:
    """Quiet, factual provenance for the footer (no warning icon). #57: the Schwab
    feed is real-time and yfinance is ~15-min delayed — label whichever actually
    served THIS result's chain, so real-time data is never mislabelled 'delayed'."""
    ts = result.quote_ts
    schwab = getattr(result, "source", "yfinance") == "schwab"
    if not ts:
        return "Schwab · real-time quotes" if schwab else "yfinance · delayed quotes"
    try:
        from zoneinfo import ZoneInfo
        pt = ts.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        pt = ts
    if schwab:
        return f"Schwab · real-time · quote {pt:%-I:%M %p %Z}"
    return f"yfinance · quotes {pt:%-I:%M %p %Z} · delayed"


def build_em_embed(result: ExpectedMoveResult, with_image: bool = True) -> dict:
    """Compact, non-directional expected-move embed."""
    em = result.em
    move_val = f"**±${result.primary_em:,.2f}**\n±{em['raw_straddle_em_pct'] * 100:.2f}%"
    levels_val = f"🔴 {result.upper:,.2f}\n🟢 {result.lower:,.2f}"
    spot_val = f"${result.spot:,.2f}\nATM {result.atm_strike:g}"

    iv_band = (f"~68% (1σ) IV band: **{result.iv_band_lower:,.2f} – "
               f"{result.iv_band_upper:,.2f}**")
    if math.isfinite(em.get("atm_iv", float("nan"))):
        iv_band += f"  ·  ATM IV {em['atm_iv'] * 100:.1f}%"

    embed = {
        "title": f"📊  {result.ticker} — Daily Expected Move",
        "description": f"**{result.session_label}** · expiration `{result.expiration}`",
        "color": 0xFEE75C,  # neutral — expected move is non-directional
        "fields": [
            {"name": "Expected move", "value": move_val, "inline": True},
            {"name": "Upper / Lower", "value": levels_val, "inline": True},
            {"name": "Spot", "value": spot_val, "inline": True},
            {"name": "Reference", "value": iv_band, "inline": False},
        ],
        "footer": {"text": _fmt_quote_time(result)},
    }
    if with_image:
        embed["image"] = {"url": f"attachment://{chart_filename(result.ticker)}"}
    return embed
