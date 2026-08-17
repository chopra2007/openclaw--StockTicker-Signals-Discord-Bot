"""Expected Move — !em (daily) and !emw (weekly).

Computes the options-implied expected move for a ticker from the ATM straddle
and ATM implied volatility, picks the right expiration for the wanted horizon
(daily: today's expiry while the market is open, next session once it has
closed; weekly: the listed expiry closest to one trading week out), renders a
candlestick chart with the expected-move band, and builds a Discord embed.

All remaining-time math runs on the real NYSE calendar (holidays and early
closes included) via utils.time_context — never a weekday count.

Data source is Schwab (real-time) when the schwab_options feature is on, with
yfinance (~15 min delayed, unofficial) as the fallback; the footer names
whichever actually served the chain. Both are blocking, so all network work
runs in a ThreadPoolExecutor (same pattern as ``scanners.options``).

Public surface used by the !em / !emw command handler:
    compute_em(ticker, exec, horizon="daily"|"weekly")
                               -> ExpectedMoveResult            (async; raises EMUnavailable)
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

# Horizons the commands support: !em -> daily, !emw -> weekly. "daily" is the
# default everywhere so the !all aggregator and scripts/iv_snapshot_daily.py
# keep their old behaviour.
HORIZONS = ("daily", "weekly")
WEEKLY_TARGET_SESSIONS = 5  # ~one trading week; the closest LISTED expiry wins


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
    iv_band_upper: Optional[float]  # 1-SD band to THIS expiration; None when IV is unusable
    iv_band_lower: Optional[float]
    tte: dict
    quote_ts: Optional[datetime]  # ATM option last-trade time (UTC)
    history: pd.DataFrame
    history_label: str
    source: str = "yfinance"      # #57: feed that served this chain — "schwab" (real-time) or "yfinance" (delayed)
    horizon: str = "daily"        # "daily" | "weekly"


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


def sessions_until(expiration: str, now_et: datetime) -> int:
    """Whole NYSE sessions from tomorrow through the expiration date, inclusive.

    Holiday-aware (shared calendar in utils.time_context) — an expiry on the
    Tuesday after a Monday holiday is 1 session away, not 2.
    """
    from consensus_engine.utils.time_context import session_dates
    exp_d = date.fromisoformat(expiration)
    if exp_d <= now_et.date():
        return 0
    return len(session_dates(now_et.date() + timedelta(days=1), exp_d))


def select_expiration(expirations: list[str], now_et: datetime,
                      horizon: str = "daily") -> tuple[str, str]:
    """Pick the expiration + a human session label for the wanted horizon.

    daily: market open and today is an expiration with meaningful time left
    (before ~15:30 ET) -> today's expiry. Otherwise -> next listed expiration
    after today.

    weekly: the LISTED expiration whose remaining-session count is closest to
    WEEKLY_TARGET_SESSIONS (ties -> the nearer one). Never invents a date: if a
    ticker only lists monthlies, the nearest monthly is chosen and the label
    states the real number of sessions.
    """
    if not expirations:
        raise EMUnavailable("No option expirations are listed for this ticker.")
    expirations = sorted(expirations)
    today_iso = now_et.date().isoformat()
    open_now = market_is_open(now_et)

    if horizon == "weekly":
        future = [e for e in expirations if e > today_iso]
        if not future:
            raise EMUnavailable(
                "No expiration is listed beyond today, so a weekly expected "
                "move can't be computed for this ticker."
            )
        best = min(future, key=lambda e: (abs(sessions_until(e, now_et)
                                              - WEEKLY_TARGET_SESSIONS), e))
        n = sessions_until(best, now_et)
        return best, f"Weekly · {n} trading session{'' if n == 1 else 's'} to expiry"

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
    """Remaining time to ``expiration``, measured on the real exchange calendar.

    trading_days = the fraction of today's session still to run (0 once it has
    closed, 1 before the open, early-close aware) plus every whole session after
    today up to and including the expiration date. Holidays are skipped, so a
    Friday->Tuesday-after-a-holiday expiry is 1 session, not 2.
    """
    from consensus_engine.utils.time_context import session_bounds
    exp_d = date.fromisoformat(expiration)
    today = now_et.date()

    # Fraction of the current session still to run.
    frac_today = 0.0
    bounds = session_bounds(today)
    if bounds is not None:
        open_t, close_t = bounds
        span = (close_t - open_t).total_seconds()
        if now_et < open_t:
            frac_today = 1.0
        elif now_et < close_t and span > 0:
            frac_today = (close_t - now_et).total_seconds() / span

    sessions_remaining = sessions_until(expiration, now_et)
    trading_days = max(frac_today + sessions_remaining, 0.0)

    # Expiry-day close: the real one (half-days close early); 16:00 if the
    # expiration date somehow is not a listed session.
    exp_bounds = session_bounds(exp_d)
    exp_dt = (exp_bounds[1] if exp_bounds
              else datetime.combine(exp_d, time(16, 0), tzinfo=now_et.tzinfo))
    cal_seconds = max((exp_dt - now_et).total_seconds(), 0.0)

    return {
        "calendar_days": cal_seconds / 86400.0,
        "trading_days": trading_days,
        "sessions_remaining": sessions_remaining,
        "session_fraction_today": frac_today,
        "T_252": trading_days / TRADING_DAYS_PER_YEAR,
        "T_365": (cal_seconds / 86400.0) / CALENDAR_DAYS_PER_YEAR,
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
               min_open_interest: float = 0.0,
               max_strike_distance_pct: float = 0.05) -> tuple[OptionQuote, OptionQuote]:
    """Closest-to-spot strike present in BOTH books, same expiration; step out
    if it is illiquid.

    A strike is rejected when either leg has a non-positive bid or ask, a
    crossed book (ask below bid), a spread wider than ``max_spread_pct`` of the
    mid, or open interest below ``min_open_interest``. Candidates further than
    ``max_strike_distance_pct`` from spot are never considered, so a thin chain
    can't quietly hand back a deep in/out-of-the-money strike.
    """
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
            if q.ask < q.bid:          # crossed book — the mid is meaningless
                return False
            if not math.isfinite(q.spread_pct) or q.spread_pct > max_spread_pct:
                return False
            if q.open_interest < min_open_interest:
                return False
        return True

    # Keep the strike near spot: the straddle is only an ATM estimate. The
    # allowance is at least one strike step, because a $3.62 stock listed in $1
    # strikes has nothing within 5% and its $4 strike IS the at-the-money one.
    steps = [b - a for a, b in zip(sorted(common), sorted(common)[1:]) if b > a]
    step = float(np.median(steps)) if steps else 0.0
    allowed = max(max_strike_distance_pct * spot, step) if spot > 0 else float("inf")
    near = [k for k in common if abs(k - spot) <= allowed]
    if not near:
        raise EMUnavailable(
            "No strike is listed close enough to the current price for a "
            "reliable at-the-money expected move."
        )

    for strike in near[:6]:
        c, p = quotes_for(strike)
        if healthy(c, p):
            return c, p

    # Nothing clean — surface the closest strike's problem rather than guessing.
    raise EMUnavailable(
        "The selected expiration does not have reliable two-sided quotes right "
        "now (missing bids/asks, wide spreads, or low open interest)."
    )


# ---------------------------------------------------------------------------
# Expected-move math
# ---------------------------------------------------------------------------
def implied_iv_from_straddle(straddle: float, spot: float, T: float) -> float:
    """Back out the straddle-implied annualized IV (consistency cross-check).

    Pass a CALENDAR-year T so the answer is comparable with the chain's own
    quoted implied vol — see calculate_expected_moves for why.
    """
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
        "straddle_implied_iv": implied_iv_from_straddle(raw, spot, tte["T_365"]),
        "iv_em_252": iv_em(1 / TRADING_DAYS_PER_YEAR),
        "iv_em_365": iv_em(1 / CALENDAR_DAYS_PER_YEAR),
        # Trading-day scaling. Kept unchanged because scripts/iv_snapshot_daily.py
        # has stored this exact quantity since 2026-06-29 — changing its meaning
        # would silently break every comparison against those rows.
        "iv_em_to_expiration": iv_em(tte["T_252"]),
        # The band the card shows. Calendar-year scaling, because the chains we
        # read (Schwab and yfinance alike) annualise implied vol on CALENDAR
        # time: over the 2026-08-15 weekend Schwab quoted SPY at 5.8% while its
        # own straddle implied 7.9% on a trading-day clock — the same 1/sqrt(0.69)
        # gap the whole stored sample shows (median ratio 0.83 at 1 calendar day,
        # 1.52 at 3). Scaling a calendar-annualised vol by a trading-day T mixes
        # the two: on the 677 stored one-session rows that mixed band covered
        # 70.6% overall but only 55.8% of the 86 weekend-crossing rows, while
        # this consistent one covered 66.8% and 67.4% — so the "about 68%" label
        # is true on both, not just on average.
        "iv_em_1sd": iv_em(tte["T_365"]),
    }


# ---------------------------------------------------------------------------
# Data fetch (blocking yfinance, runs in executor)
# ---------------------------------------------------------------------------
def _schwab_bundle(ticker: str, now_et: datetime, horizon: str = "daily") -> Optional[dict]:
    """#57: Schwab real-time version of _fetch_bundle. Returns the SAME dict shape
    or None on any failure (caller falls back to yfinance). The chain DataFrames
    carry yfinance columns incl. impliedVolatility as a FRACTION (already ÷100 in
    the client), so select_atm / _row_to_quote work unchanged."""
    try:
        from consensus_engine.scanners import schwab_client
        # Stay bounded: an unbounded SPY chain (34 daily expirations) 502s from
        # Schwab. 8 nearest expirations still reaches a ~1-week expiry, so the
        # weekly horizon needs no wider request.
        ch = schwab_client.get_option_chain(ticker, nearest=8)
    except Exception as e:
        log.debug("em schwab chain fetch failed for %s: %s", ticker, e)
        return None
    if ch is None or not ch.expirations:
        return None
    spot = ch.underlying_price
    if not spot or not math.isfinite(spot):
        return None
    exp, session_label = select_expiration(ch.expirations, now_et, horizon)
    be = ch.by_expiry(exp)
    calls, puts = be.calls.copy(), be.puts.copy()
    if calls is None or puts is None or calls.empty or puts.empty:
        return None
    history, history_label = _fetch_history(ticker, horizon)
    return {
        "spot": spot, "expiration": exp, "session_label": session_label,
        "calls": calls, "puts": puts,
        "history": history, "history_label": history_label,
        "source": "schwab",
    }


def _yfinance_bundle(ticker: str, now_et: datetime,
                     horizon: str = "daily") -> dict:
    """Blocking delayed-data fallback with the same shape as _schwab_bundle."""
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
    exp, session_label = select_expiration(exps, now_et, horizon)

    try:
        oc = t.option_chain(exp)
        calls, puts = oc.calls.copy(), oc.puts.copy()
    except Exception as e:
        raise EMUnavailable(f"Could not fetch the option chain for `${ticker}` {exp}.") from e
    if calls is None or puts is None or calls.empty or puts.empty:
        raise EMUnavailable(f"The option chain for `${ticker}` {exp} came back empty.")

    history, history_label = _fetch_history(ticker, horizon)

    return {
        "spot": spot, "expiration": exp, "session_label": session_label,
        "calls": calls, "puts": puts,
        "history": history, "history_label": history_label,
        "source": "yfinance",
    }


def _fetch_bundle(ticker: str, now_et: datetime, horizon: str = "daily") -> dict:
    """Blocking: spot, chosen expiration, that chain, and price history."""
    # #57: Schwab real-time chain PRIMARY (native greeks + IV); yfinance fallback.
    schwab_unavailable = False
    if _cfg.get("features.schwab_options.enabled", False):
        bundle = _schwab_bundle(ticker, now_et, horizon)
        if bundle is not None:
            return bundle
        schwab_unavailable = True
    bundle = _yfinance_bundle(ticker, now_et, horizon)
    if schwab_unavailable:
        bundle["_schwab_unavailable"] = True
    return bundle


def _fetch_history(ticker: str, horizon: str = "daily") -> tuple[pd.DataFrame, str]:
    """Best-effort candles for the chart, sized to the horizon: a few sessions of
    intraday for daily, about a quarter of daily bars for weekly. #57: routed
    through the OHLCV choke-point (Schwab primary, yfinance fallback)."""
    if horizon == "weekly":
        # About a month of daily bars: enough context for a one-week band
        # without squashing it into a sliver at the top of a quarter's range.
        attempts = [
            (dict(period="1mo", interval="1d"), "daily candles · last month"),
            (dict(period="3mo", interval="1d"), "daily candles · last 3 months"),
            (dict(period="10d", interval="15m"), "15-minute candles · last 10 sessions"),
        ]
    else:
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


async def compute_em(ticker: str, executor=None,
                     horizon: str = "daily") -> ExpectedMoveResult:
    """Compute the expected move for any optionable ticker. Raises EMUnavailable
    (user-facing message) when it can't — no options listed, empty chain, or
    quotes too poor for a reliable straddle (zero/crossed bids, wide spreads,
    thin open interest, no strike near spot).

    ``horizon`` defaults to "daily" so every other caller (!all's vol tag,
    scripts/iv_snapshot_daily.py) keeps its existing one-session behaviour.
    """
    ticker = ticker.upper()
    if horizon not in HORIZONS:
        raise EMUnavailable(f"Unknown horizon `{horizon}` — use daily or weekly.")
    now_et = now_eastern()
    loop = asyncio.get_running_loop()
    bundle = await loop.run_in_executor(executor, _fetch_bundle, ticker, now_et, horizon)

    spot = bundle["spot"]
    min_oi = float(cfg.get("expected_move.min_atm_open_interest", 100))
    multiplier = float(cfg.get("expected_move.multiplier", 0.85))
    max_spread = float(cfg.get("expected_move.max_atm_spread_pct", 0.25))
    max_dist = float(cfg.get("expected_move.max_atm_strike_distance_pct", 0.05))

    try:
        call, put = select_atm(bundle["calls"], bundle["puts"], spot,
                               max_spread_pct=max_spread,
                               min_open_interest=min_oi,
                               max_strike_distance_pct=max_dist)
    except EMUnavailable as schwab_error:
        # A provider can return a structurally valid chain while some quote
        # fields are temporarily unusable. That must trigger the same delayed
        # fallback as an empty/failed Schwab chain instead of falsely calling a
        # liquid ticker illiquid. Preserve the original error if the fallback
        # is unavailable or also fails its quote-quality checks.
        if bundle.get("_schwab_unavailable"):
            raise EMUnavailable(
                "Live option quotes are temporarily unavailable. Try again in "
                "a minute."
            ) from schwab_error
        if bundle.get("source") != "schwab":
            raise
        try:
            fallback = await loop.run_in_executor(
                executor, _yfinance_bundle, ticker, now_et, horizon)
            fallback_spot = fallback["spot"]
            fallback_call, fallback_put = select_atm(
                fallback["calls"], fallback["puts"], fallback_spot,
                max_spread_pct=max_spread,
                min_open_interest=min_oi,
                max_strike_distance_pct=max_dist,
            )
        except Exception as fallback_error:
            log.debug("em quote-quality fallback failed for %s: %s",
                      ticker, fallback_error)
            raise schwab_error
        bundle = fallback
        spot = fallback_spot
        call, put = fallback_call, fallback_put
    tte = time_to_expiration(bundle["expiration"], now_et)
    em = calculate_expected_moves(spot, call, put, tte, multiplier)

    primary = em["raw_straddle_em"]
    # 1-standard-deviation band for THIS expiration (not a fixed one session),
    # so the ~68% label is true for daily and weekly alike. None when the chain
    # carries no usable IV — the card then omits the band instead of relabelling
    # the straddle range as 1 sigma.
    sd = em["iv_em_1sd"]
    sd_ok = math.isfinite(sd) and sd > 0

    return ExpectedMoveResult(
        ticker=ticker, spot=spot, expiration=bundle["expiration"],
        session_label=bundle["session_label"],
        market_open=market_is_open(now_et),
        atm_strike=call.strike, call=call, put=put, em=em,
        primary_em=primary, upper=spot + primary, lower=spot - primary,
        iv_band_upper=spot + sd if sd_ok else None,
        iv_band_lower=spot - sd if sd_ok else None,
        tte=tte, quote_ts=call.last_trade,
        history=bundle["history"], history_label=bundle["history_label"],
        source=bundle.get("source", "yfinance"),
        horizon=horizon,
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

    # Pacific x-axis: the candles arrive on the exchange's own clock, but every
    # time the owner sees must be Pacific. Only intraday bars carry a real time
    # of day — converting daily bars (all stamped at one time) would just shift
    # their dates.
    try:
        idx = hist.index
        if getattr(idx, "tz", None) is not None and len(set(idx.time)) > 1:
            from zoneinfo import ZoneInfo
            hist = hist.copy()
            hist.index = idx.tz_convert(ZoneInfo("America/Los_Angeles"))
    except Exception:  # never let a chart cosmetic break the command
        pass

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
    horizon_word = "Weekly" if result.horizon == "weekly" else "Daily"
    sessions = result.tte.get("sessions_remaining")
    sess_txt = (f"{sessions} session{'' if sessions == 1 else 's'} left"
                if isinstance(sessions, int) else result.session_label)

    # Dark canvas so the chart sits inside Discord's dark card instead of
    # flashing a white block; every mark below is picked for contrast on it.
    BG, FG, GRID = "#1E1F22", "#E8EAED", "#3A3C40"
    UP_C, DOWN_C = "#3FD08A", "#FF6B6B"
    band = max(em * 0.14, spot * 0.0006)
    ymin = min(float(hist["Low"].min()), lower) - band * 2.0
    ymax = max(float(hist["High"].max()), upper) + band * 2.0

    if have_mpf:
        mc = mpf.make_marketcolors(up=UP_C, down=DOWN_C, edge="inherit",
                                   wick="inherit", volume="in")
        style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                                   facecolor=BG, figcolor=BG, edgecolor=GRID,
                                   gridstyle=":", gridcolor=GRID,
                                   rc={"axes.labelcolor": FG, "xtick.color": FG,
                                       "ytick.color": FG, "text.color": FG})
        fig, axes = mpf.plot(hist, type="candle", style=style, figsize=(13.5, 7.2),
                             returnfig=True, volume=False, ylim=(ymin, ymax),
                             tight_layout=True, xrotation=0)
        ax = axes[0]
    else:
        fig, ax = plt.subplots(figsize=(13.5, 7.2), facecolor=BG)
        ax.set_facecolor(BG)
        ax.plot(range(len(hist)), hist["Close"].values, color="#6EA8FE", lw=1.4)
        ax.set_ylim(ymin, ymax)
        ax.set_xlim(0, len(hist) - 1)
        ax.grid(color=GRID, ls=":", lw=0.7)
        ax.tick_params(colors=FG)
        for s in ax.spines.values():
            s.set_color(GRID)

    fig.patch.set_facecolor(BG)
    ax.set_ylabel("")  # drop default "Price" label so right-edge labels read clean
    # Shade the whole expected range once — one band, not two stripes, so the
    # eye reads "inside vs outside" at a glance.
    ax.axhspan(lower, upper, color="#FFFFFF", alpha=0.05, zorder=1)
    ax.axhline(upper, color=DOWN_C, lw=1.8, ls="--", zorder=5)
    ax.axhline(lower, color=UP_C, lw=1.8, ls="--", zorder=5)
    ax.axhline(spot, color="#6EA8FE", lw=1.6, ls="-", zorder=5)

    def label(y, text, color):
        ax.annotate(text, xy=(1.0, y), xycoords=("axes fraction", "data"),
                    xytext=(8, 0), textcoords="offset points", va="center",
                    ha="left", fontsize=11, fontweight="bold", color="#101114",
                    bbox=dict(boxstyle="round,pad=0.35", fc=color, ec="none"),
                    annotation_clip=False, zorder=6)

    label(upper, f"{upper:,.2f}", DOWN_C)
    label(spot,  f"{spot:,.2f}", "#6EA8FE")
    label(lower, f"{lower:,.2f}", UP_C)

    ax.set_title(
        f"{result.ticker}   {horizon_word} expected move  ±${em:,.2f}  (±{em / spot * 100:.2f}%)",
        fontsize=15, fontweight="bold", color=FG, pad=16, loc="left")
    ax.text(0.0, 1.012, f"ATM straddle · expires {result.expiration} · {sess_txt}",
            transform=ax.transAxes, fontsize=10.5, color="#A8ADB4", ha="left")
    ax.margins(x=0.01)
    fig.subplots_adjust(right=0.86)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=BG)
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


def _quote_line(q: OptionQuote) -> str:
    """Enough of one leg's quote to see where the estimate came from."""
    spread = q.spread_pct
    spread_txt = f"{spread * 100:.1f}%" if math.isfinite(spread) else "n/a"
    return (f"bid {q.bid:,.2f} / ask {q.ask:,.2f}\n"
            f"mid **${q.mid:,.2f}** · spread {spread_txt}\n"
            f"OI {q.open_interest:,.0f} · vol {q.volume:,.0f}")


def build_em_embed(result: ExpectedMoveResult, with_image: bool = True) -> dict:
    """Detailed, non-directional expected-move embed (daily or weekly)."""
    em = result.em
    horizon_word = "Weekly" if result.horizon == "weekly" else "Daily"
    sessions = result.tte.get("sessions_remaining")
    sess_txt = (f"{sessions} trading session{'' if sessions == 1 else 's'} left"
                if isinstance(sessions, int) else result.session_label)

    move_val = (f"**±${result.primary_em:,.2f}**\n"
                f"±{em['raw_straddle_em_pct'] * 100:.2f}%\n"
                f"ATM straddle price")
    range_val = (f"🔴 **{result.upper:,.2f}** upper\n"
                 f"🔵 {result.spot:,.2f} now\n"
                 f"🟢 **{result.lower:,.2f}** lower")
    price_val = (f"**${result.spot:,.2f}**\n"
                 f"ATM strike {result.atm_strike:g}\n"
                 f"{'market open' if result.market_open else 'market closed'}")
    exp_val = f"`{result.expiration}`\n{sess_txt}\n{result.session_label}"

    if result.iv_band_upper is not None and result.iv_band_lower is not None:
        ref = (f"**1 standard deviation — about 68% of the time — "
               f"{result.iv_band_lower:,.2f} to {result.iv_band_upper:,.2f}**")
        if math.isfinite(em.get("atm_iv", float("nan"))):
            ref += f"\nATM implied volatility {em['atm_iv'] * 100:.1f}% a year."
        ref += ("\nAn at-the-money straddle prices about 0.8 of one standard "
                "deviation, so the straddle range above is normally the tighter "
                "of the two.")
    else:
        ref = ("No usable implied volatility in this chain, so no 1-standard-"
               "deviation band is shown. The straddle range above still stands "
               "— it is a traded price, not a model output.")

    embed = {
        "title": f"📊  {result.ticker} — {horizon_word} Expected Move",
        "description": (
            f"**{horizon_word}** · expires `{result.expiration}` · {sess_txt}\n"
            f"How big a move the options market is paying for — not which way."
        ),
        "color": 0xFEE75C,  # neutral — expected move is non-directional
        "fields": [
            {"name": "Expected move", "value": move_val, "inline": True},
            {"name": "Expected range", "value": range_val, "inline": True},
            {"name": "Price", "value": price_val, "inline": True},
            {"name": "Expiration", "value": exp_val, "inline": True},
            {"name": f"ATM call {result.atm_strike:g}",
             "value": _quote_line(result.call), "inline": True},
            {"name": f"ATM put {result.atm_strike:g}",
             "value": _quote_line(result.put), "inline": True},
            {"name": "Reference", "value": ref, "inline": False},
        ],
        "footer": {"text": _fmt_quote_time(result)},
    }
    if with_image:
        embed["image"] = {"url": f"attachment://{chart_filename(result.ticker)}"}
    return embed
