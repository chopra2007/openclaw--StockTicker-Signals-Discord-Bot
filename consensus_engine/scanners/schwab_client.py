"""Schwab Trader API market-data client (TODO #57).

Real-time option chains (with native greeks), quotes, and price history from the
user's funded Charles Schwab account — the official, real-time replacement for the
free ~15-min-delayed yfinance/Finnhub feeds.

Design (see .claude/discover/schwab-options-realtime/final-plan.md):
- Thin, synchronous `requests` client (zero new deps). Co-located with the
  blocking consumers (options.py, expected_move.py, snapshot.py) that already run
  inside a ThreadPoolExecutor, so it drops straight into those call-sites.
- PRIMARY only. Every public method may raise freely; the CALLER catches and
  falls back to the existing yfinance/Finnhub path so the bot NEVER goes dark.
- Token refresh is BOTH thread-safe (threading.Lock, within-process) and
  process-safe (fcntl.flock on a sidecar lock file, across the engine and the
  separate daily-snapshot process) — BLOCK-4.
- A synchronous, thread-safe token-bucket rate limiter + post-429 cooldown caps
  us under Schwab's ~120 req/min across all sync consumers — BLOCK-3.
- OAuth: access token lives 30 min (auto-refreshed). The refresh token lives
  ~7 days from the ORIGINAL browser login and refreshing does NOT extend it
  (proven live: refresh returns the SAME refresh_token). So the 7-day wall is
  anchored to a frozen `_refresh_created`, and `SchwabRefreshTokenExpired` is the
  single signal that fires the weekly re-auth reminder.

Personal-use handling: Schwab support confirmed to the owner that raw chains
may be stored locally for personal testing. Never post or publish a raw
per-strike chain; user-facing callers render derived summaries only.
"""

import datetime
import fcntl
import gzip
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from consensus_engine import config

log = logging.getLogger("consensus_engine.scanner.schwab")

# --- endpoints / constants -------------------------------------------------
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MD_BASE = "https://api.schwabapi.com/marketdata/v1"
TOKEN_PATH = "/home/openclaw/.openclaw/schwab_token.json"
LOCK_PATH = "/home/openclaw/.openclaw/schwab_token.lock"
REAUTH_MARKER = "/home/openclaw/.openclaw/schwab_reauth_needed"

ACCESS_TTL_DEFAULT = 1800          # access-token life (expires_in), seconds
REFRESH_EARLY = 60                 # refresh this many seconds before access expiry
REFRESH_TTL = 7 * 24 * 3600        # refresh-token hard wall (~7 days from ORIGINAL login)
HTTP_TIMEOUT = 15                  # per-request timeout, seconds (bounded chains are <3s)

# Rate limiter: Schwab allows ~120 req/min; keep headroom.
_RATE_PER_MIN = 110
_COOLDOWN_AFTER_429 = 60.0         # skip Schwab for this long after a 429


class SchwabError(Exception):
    """Any Schwab client failure. Callers catch this (or Exception) and fall back."""


class SchwabRefreshTokenExpired(SchwabError):
    """The 7-day refresh token is dead — a human browser re-login is required.
    The single signal the weekly re-auth reminder listens for."""


# ---------------------------------------------------------------------------
# Synchronous, thread-safe token-bucket rate limiter (+ post-429 cooldown).
# Shared across all executor threads in one process (BLOCK-3). The separate
# daily-logger process has its own bucket but runs off-hours (22:50 UTC),
# staggered from the engine, so cross-process bursts don't overlap.
# ---------------------------------------------------------------------------
class _RateBucket:
    def __init__(self, per_min: int):
        self._capacity = float(per_min)
        self._tokens = float(per_min)
        self._refill_per_sec = per_min / 60.0
        self._last = time.monotonic()
        self._cooldown_until = 0.0
        self._lock = threading.Lock()

    def in_cooldown(self) -> bool:
        with self._lock:
            return time.monotonic() < self._cooldown_until

    def trip_cooldown(self, seconds: float = _COOLDOWN_AFTER_429) -> None:
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def acquire(self) -> None:
        """Block (briefly) until a request slot is free. Raises if in cooldown."""
        deadline = time.monotonic() + 30.0  # never wait forever inside an executor
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._cooldown_until:
                    raise SchwabError("schwab rate-limit cooldown active")
                # refill
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._refill_per_sec
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                need = (1.0 - self._tokens) / self._refill_per_sec
            if time.monotonic() >= deadline:
                raise SchwabError("schwab rate-limit wait exceeded 30s")
            time.sleep(min(need, 1.0))


_bucket = _RateBucket(_RATE_PER_MIN)
_refresh_lock = threading.Lock()   # within-process refresh serialization


# ---------------------------------------------------------------------------
# Credentials + token management
# ---------------------------------------------------------------------------
def _creds() -> tuple[str, str]:
    key = config.get_api_key("schwab_app_key") or os.environ.get("SCHWAB_APP_KEY", "")
    secret = config.get_api_key("schwab_app_secret") or os.environ.get("SCHWAB_APP_SECRET", "")
    if not key or not secret:
        raise SchwabError("SCHWAB_APP_KEY / SCHWAB_APP_SECRET not set")
    return key, secret


def _decode_body(resp: requests.Response) -> str:
    """gzip-on-error gotcha: Schwab sometimes returns a gzip body without a
    Content-Encoding header, so requests won't auto-inflate. Sniff the magic."""
    raw = resp.content
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw).decode("utf-8", "replace")
        except Exception:
            pass
    return resp.text


def _load_token() -> dict:
    with open(TOKEN_PATH) as f:
        return json.load(f)


def _atomic_write_token(doc: dict) -> None:
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKEN_PATH)


def _needs_refresh(doc: dict) -> bool:
    tok = doc.get("token", {})
    ttl = tok.get("expires_in", ACCESS_TTL_DEFAULT)
    return time.time() >= doc.get("creation_timestamp", 0) + ttl - REFRESH_EARLY


def _refresh_created(doc: dict) -> float:
    # The ORIGINAL browser-login time, frozen across refreshes. The current
    # on-disk file has only creation_timestamp (== original login); the first
    # refresh seeds _refresh_created from it.
    return float(doc.get("_refresh_created", doc.get("creation_timestamp", 0)))


def reauth_days_left() -> float:
    """Days until the 7-day refresh token expires (from the frozen original login)."""
    try:
        doc = _load_token()
    except Exception:
        return -1.0
    return (_refresh_created(doc) + REFRESH_TTL - time.time()) / 86400.0


def note_reauth_needed(reason: str = "") -> None:
    """Best-effort marker that a browser re-login is due. Read by the daily
    reminder script and surfaced at session start. Never raises."""
    try:
        with open(REAUTH_MARKER, "w") as f:
            f.write(json.dumps({"ts": int(time.time()), "reason": reason}))
        os.chmod(REAUTH_MARKER, 0o600)
    except Exception:
        pass


def clear_reauth_marker() -> None:
    try:
        os.remove(REAUTH_MARKER)
    except Exception:
        pass


def get_access_token() -> str:
    """Return a valid access token, refreshing under a thread+process lock if
    needed. Raises SchwabRefreshTokenExpired when the 7-day wall is breached."""
    with _refresh_lock:  # within-process
        doc = _load_token()
        if not _needs_refresh(doc):
            return doc["token"]["access_token"]

        # Process-safe section: another process (daily logger) may refresh too.
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # Re-read: another process may have just refreshed while we waited.
            doc = _load_token()
            if not _needs_refresh(doc):
                return doc["token"]["access_token"]

            if time.time() >= _refresh_created(doc) + REFRESH_TTL:
                note_reauth_needed("7-day refresh token expired")
                raise SchwabRefreshTokenExpired(
                    "Schwab refresh token past its 7-day wall — browser re-login required"
                )

            refresh_token = doc["token"]["refresh_token"]
            key, secret = _creds()
            resp = requests.post(
                TOKEN_URL,
                auth=(key, secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                timeout=30,
            )
            body = _decode_body(resp)
            if resp.status_code != 200:
                # invalid_grant / 4xx => refresh token dead. Fire the reminder.
                if resp.status_code < 500 or "invalid_grant" in body:
                    note_reauth_needed(f"refresh failed {resp.status_code}: {body[:120]}")
                    raise SchwabRefreshTokenExpired(f"refresh failed: {resp.status_code} {body[:200]}")
                raise SchwabError(f"token refresh HTTP {resp.status_code}: {body[:200]}")

            new_tok = json.loads(body)
            frozen = _refresh_created(doc)            # freeze the 7-day clock
            doc["token"] = new_tok
            doc["creation_timestamp"] = int(time.time())   # reset access clock
            doc["_refresh_created"] = frozen
            _atomic_write_token(doc)
            clear_reauth_marker()
            log.info("Schwab access token refreshed (7-day wall in %.1fd)",
                     (frozen + REFRESH_TTL - time.time()) / 86400.0)
            return new_tok["access_token"]
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get(path: str, params: dict | None = None) -> dict:
    if _bucket.in_cooldown():
        raise SchwabError("schwab cooldown active (recent 429)")
    _bucket.acquire()
    token = get_access_token()
    resp = requests.get(
        f"{MD_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params or {},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code == 429:
        _bucket.trip_cooldown()
        raise SchwabError("schwab 429 rate limited")
    if resp.status_code != 200:
        raise SchwabError(f"schwab GET {path} HTTP {resp.status_code}: {_decode_body(resp)[:200]}")
    return resp.json()


# ---------------------------------------------------------------------------
# Symbol translation (yfinance/Finnhub symbology -> Schwab)
# ---------------------------------------------------------------------------
def to_schwab_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    if s == "SPX":
        return "$SPX"
    if s.startswith("^"):
        return "$" + s[1:]        # ^VIX -> $VIX (index symbology)
    return s.replace(".", "/")    # BRK.B -> BRK/B


def is_probably_unsupported(sym: str) -> bool:
    """Indices/futures we don't confidently map — let the caller skip Schwab."""
    s = (sym or "").strip().upper()
    return s.startswith("^") or s.startswith("$") or "=" in s or s.endswith("F")


# ---------------------------------------------------------------------------
# Option chains -> yfinance-shaped DataFrames
# ---------------------------------------------------------------------------
def _iv_from_pct(v) -> float:
    """Schwab `volatility` is a percent (34.066); yfinance impliedVolatility is a
    fraction (0.34066). -999 / <=0 are Schwab's 'no data' sentinels -> NaN."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    if f <= 0 or f <= -998:
        return float("nan")
    return f / 100.0


def _chain_map_to_df(exp_map: dict):
    """Flatten a Schwab callExpDateMap/putExpDateMap into one yfinance-column
    DataFrame with a per-row `expiry` column."""
    import pandas as pd

    rows = []
    for exp_key, strikes in (exp_map or {}).items():
        exp = exp_key.split(":")[0]          # "2026-07-01:1" -> "2026-07-01"
        for _strike, contracts in (strikes or {}).items():
            for c in contracts:
                tt = c.get("tradeTimeInLong") or 0
                qt = c.get("quoteTimeInLong") or 0
                rows.append({
                    "contractSymbol": c.get("symbol", ""),
                    "strike": _num(c.get("strikePrice")),
                    "lastPrice": _num(c.get("last")),
                    "bid": _num(c.get("bid")),
                    "ask": _num(c.get("ask")),
                    # TODO #98: Schwab's own mark and the two quote sizes. Kept
                    # so a stored option snapshot can be audited against what
                    # the provider actually sent, instead of only a midpoint we
                    # computed ourselves. Additive: no existing caller reads them.
                    "mark": _num(c.get("mark")),
                    "bidSize": _num(c.get("bidSize")),
                    "askSize": _num(c.get("askSize")),
                    "volume": _num(c.get("totalVolume")),
                    "openInterest": _num(c.get("openInterest")),
                    "impliedVolatility": _iv_from_pct(c.get("volatility")),
                    "tradeTimeInLong": tt,
                    "providerQuoteTime": qt,
                    "multiplier": _num(c.get("multiplier")),
                    "nonStandard": bool(c.get("nonStandard", False)),
                    "deliverableNote": str(c.get("deliverableNote", "") or ""),
                    "expiry": exp,
                    "delta": _num(c.get("delta")),
                    "gamma": _num(c.get("gamma")),
                    "theta": _num(c.get("theta")),
                    "vega": _num(c.get("vega")),
                    "rho": _num(c.get("rho")),
                })
    if not rows:
        return pd.DataFrame(columns=[
            "contractSymbol", "strike", "lastPrice", "bid", "ask", "mark",
            "bidSize", "askSize", "volume",
            "openInterest", "impliedVolatility", "lastTradeDate", "expiry",
            "providerQuoteTime", "multiplier", "nonStandard", "deliverableNote",
            "delta", "gamma", "theta", "vega", "rho",
        ])
    df = pd.DataFrame(rows)
    # lastTradeDate: epoch-ms -> tz-aware America/New_York Timestamp (NaT if 0).
    ms = pd.to_numeric(df.pop("tradeTimeInLong"), errors="coerce")
    try:
        ts = pd.to_datetime(ms.where(ms > 0), unit="ms", utc=True, errors="coerce")
    except Exception:
        # Fail-soft: pandas' internal ms->ns cast (cast_from_unit_vectorized)
        # can spuriously raise (numpy "overflow encountered in multiply") on
        # some large, liquid chains (observed live on NVDA/AMD/META/GOOGL/
        # MSFT/QQQ/etc, ~15-20% of tickers) even though every tradeTimeInLong
        # value is a normal epoch-ms timestamp -- errors="coerce" alone
        # doesn't catch this numpy-level exception. Give up on lastTradeDate
        # for this chain (NaT = "unverifiable", already a handled case
        # downstream) rather than aborting the whole fetch.
        ts = pd.Series(pd.NaT, index=ms.index, dtype="datetime64[ns, UTC]")
    df["lastTradeDate"] = ts.dt.tz_convert("America/New_York")
    return df


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    # Schwab uses -999 as a 'no data' sentinel for greeks/vol on illiquid rows.
    # Also treat absurd magnitudes (glitch ticks) as NaN so a bad value can't
    # overflow downstream numpy math (e.g. the max-pain payout matrix).
    if f <= -998 or abs(f) > 1e12:
        return float("nan")
    return f


@dataclass
class Chain:
    calls: "object"                       # pandas DataFrame (yfinance columns) across all expiries
    puts: "object"
    underlying_price: float
    is_delayed: bool
    expirations: list = field(default_factory=list)

    def by_expiry(self, exp: str):
        """Return a yfinance-option_chain-shaped namespace for one expiry."""
        c = self.calls[self.calls["expiry"] == exp] if not self.calls.empty else self.calls
        p = self.puts[self.puts["expiry"] == exp] if not self.puts.empty else self.puts
        return SimpleNamespace(calls=c, puts=p)


def get_option_chain(symbol: str, *, nearest: Optional[int] = None,
                     contract_type: str = "ALL",
                     strike_count: Optional[int] = None,
                     from_date: Optional[str] = None,
                     to_date: Optional[str] = None) -> Optional[Chain]:
    """Real-time option chain for `symbol`. Returns None on empty/no-data.
    Raises on transport/auth errors (caller falls back).

    `nearest`: bound the fetch to the soonest N expirations (resolves `to_date`
    from the cheap /expirationchain). REQUIRED for high-expiration tickers — a
    full SPY/QQQ chain (34 daily expirations) 502s from Schwab itself. Callers
    that only look at the front expirations MUST pass nearest (or an explicit
    to_date) so the payload stays small."""
    # Safety net: never fetch a fully-unbounded chain (Schwab 502s on SPY/QQQ).
    if nearest is None and not to_date and not from_date:
        nearest = 8
    if nearest and not to_date:
        try:
            exps = get_expirations(symbol)
        except Exception:
            exps = []
        # Schwab keeps listing today's expiry after the Eastern day has rolled over
        # (any time past midnight ET), but /chains then 400s on that date as being in
        # the past. Dropping already-past expirations keeps nearest=1 (the default in
        # scanners/options.py) working overnight instead of erroring the whole fetch.
        today_et = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        exps = [e for e in exps if e >= today_et]
        if exps:
            to_date = exps[min(int(nearest), len(exps)) - 1]
    params = {"symbol": to_schwab_symbol(symbol), "contractType": contract_type}
    if strike_count:
        params["strikeCount"] = strike_count
    if from_date:
        params["fromDate"] = from_date
    if to_date:
        params["toDate"] = to_date
    d = _get("/chains", params)
    if d.get("status") not in ("SUCCESS", None) or d.get("numberOfContracts", 0) == 0:
        return None
    calls = _chain_map_to_df(d.get("callExpDateMap", {}))
    puts = _chain_map_to_df(d.get("putExpDateMap", {}))
    if calls.empty and puts.empty:
        return None
    exps = sorted(set(calls.get("expiry", [])).union(set(puts.get("expiry", []))))
    return Chain(
        calls=calls, puts=puts,
        underlying_price=_num(d.get("underlyingPrice")),
        is_delayed=bool(d.get("isDelayed", True)),
        expirations=exps,
    )


def get_expirations(symbol: str) -> list[str]:
    d = _get("/expirationchain", {"symbol": to_schwab_symbol(symbol)})
    lst = d.get("expirationList", []) or []
    return sorted({it.get("expirationDate") for it in lst if it.get("expirationDate")})


# ---------------------------------------------------------------------------
# Quotes -> Finnhub-shaped dict {c,pc,dp,o,h,l,v,t}
# ---------------------------------------------------------------------------
def _bool_or_none(v):
    """True/False only when Schwab actually said so. Anything else is None.

    A missing field means "Schwab did not tell us", which is not the same as
    "you cannot short it". Callers must never treat None as a No.
    """
    return v if isinstance(v, bool) else None


def _map_quote(entry: dict) -> dict:
    q = entry.get("quote", {}) or {}
    reg = entry.get("regular", {}) or {}
    ref = entry.get("reference", {}) or {}
    # `c` = current/last regular price (matches yfinance fast_info lastPrice and
    # the chain's underlyingPrice); regularMarketLastPrice is stable across RTH
    # and after-hours. Fall back to quote.lastPrice.
    c = reg.get("regularMarketLastPrice", q.get("lastPrice"))
    dp = reg.get("regularMarketPercentChange", q.get("netPercentChange"))
    trade_time = q.get("tradeTime") or 0
    quote_time = q.get("quoteTime") or 0
    return {
        "c": _num(c),
        "bid": _num(q.get("bidPrice")),
        "ask": _num(q.get("askPrice")),
        "bid_size": _num(q.get("bidSize")),
        "ask_size": _num(q.get("askSize")),
        "pc": _num(q.get("closePrice")),
        "dp": _num(dp),
        "o": _num(q.get("openPrice")),
        "h": _num(q.get("highPrice")),
        "l": _num(q.get("lowPrice")),
        "v": _num(q.get("totalVolume")),          # Finnhub free tier always left this 0
        "t": int(trade_time / 1000),              # epoch-ms -> epoch-seconds
        "quote_time": int(quote_time / 1000),
        "halt_status": str(q.get("securityStatus") or "unknown").lower(),
        # TODO #96: Schwab's own point-in-time short availability, from the
        # quote's `reference` block. `shortable` False means Schwab says you
        # cannot short it right now; None means Schwab did not say. `htb_rate`
        # is the hard-to-borrow annual rate Schwab quotes, 0.0 when easy.
        "shortable": _bool_or_none(ref.get("isShortable")),
        "hard_to_borrow": _bool_or_none(ref.get("isHardToBorrow")),
        "htb_rate": _num(ref.get("htbRate")) if ref.get("htbRate") is not None else None,
    }


def get_quote(symbol: str) -> Optional[dict]:
    d = _get(f"/{to_schwab_symbol(symbol)}/quotes")
    entry = d.get(to_schwab_symbol(symbol)) or (next(iter(d.values()), None) if d else None)
    if not entry:
        return None
    return _map_quote(entry)


def get_quotes(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    schwab_syms = [to_schwab_symbol(s) for s in symbols]
    d = _get("/quotes", {"symbols": ",".join(schwab_syms)})
    out = {}
    for orig, ss in zip(symbols, schwab_syms):
        entry = d.get(ss)
        if entry:
            out[orig] = _map_quote(entry)
    return out


# ---------------------------------------------------------------------------
# Price history -> yfinance-compatible DataFrame (tz-aware America/New_York)
# ---------------------------------------------------------------------------
_PERIOD_MAP = {
    "1d": ("day", 1), "2d": ("day", 2), "5d": ("day", 5), "10d": ("day", 10),
    "1mo": ("month", 1), "3mo": ("month", 3), "6mo": ("month", 6),
    "1y": ("year", 1), "2y": ("year", 2), "5y": ("year", 5),
    "10y": ("year", 10), "ytd": ("ytd", 1),
}
_FREQ_MAP = {
    "1m": ("minute", 1), "5m": ("minute", 5), "10m": ("minute", 10),
    "15m": ("minute", 15), "30m": ("minute", 30),
    "1d": ("daily", 1), "1wk": ("weekly", 1), "1mo": ("monthly", 1),
}


def _to_ms(dt) -> Optional[int]:
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        return int(dt if dt > 1e12 else dt * 1000)   # accept sec or ms
    try:
        import pandas as pd
        return int(pd.Timestamp(dt).tz_localize("UTC").timestamp() * 1000) if pd.Timestamp(dt).tzinfo is None \
            else int(pd.Timestamp(dt).timestamp() * 1000)
    except Exception:
        return None


def _period_to_calendar_days(period: Optional[str]) -> int:
    """Calendar-day span for a yfinance-style period string (pad for weekends)."""
    import re
    if not period:
        return 40
    m = re.fullmatch(r"(\d+)d", period)
    if m:
        return int(m.group(1)) + 5
    table = {"1mo": 40, "3mo": 100, "6mo": 190, "1y": 380, "2y": 740,
             "5y": 1840, "10y": 3660, "ytd": 380}
    return table.get(period, 40)


def get_price_history(symbol: str, *, period: Optional[str] = None,
                      interval: str = "1d", start=None, end=None,
                      extended_hours: bool = False) -> Optional["object"]:
    """OHLCV bars as a yfinance-compatible DataFrame:
    columns [Open, High, Low, Close, Volume], tz-aware America/New_York index.

    extended_hours: when True, includes premarket/after-hours bars (only
    meaningful for intraday `interval`s -- Schwab ignores it for daily+).
    Default False preserves the prior regular-session-only behavior."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    freq_type, freq = _FREQ_MAP.get(interval, ("daily", 1))
    params = {"symbol": to_schwab_symbol(symbol),
              "frequencyType": freq_type, "frequency": freq,
              "needExtendedHoursData": "true" if extended_hours else "false"}
    start_ms, end_ms = _to_ms(start), _to_ms(end)

    if freq_type in ("daily", "weekly", "monthly"):
        # Daily+: ALWAYS use a startDate/endDate window — sidesteps Schwab's
        # periodType/period combo limits (e.g. `day` period maxes at 10), so any
        # yfinance-style period ("2d", "15d", "2y", ...) maps cleanly.
        if not start_ms:
            start_ms = int((datetime.now(timezone.utc)
                            - timedelta(days=_period_to_calendar_days(period))).timestamp() * 1000)
        params["periodType"] = "year"
        params["startDate"] = start_ms
        if end_ms:
            params["endDate"] = end_ms
    else:
        # Intraday (minute): needs periodType=day (period ≤ 10) or a date window.
        params["periodType"] = "day"
        if start_ms or end_ms:
            if start_ms:
                params["startDate"] = start_ms
            if end_ms:
                params["endDate"] = end_ms
        else:
            p_type, p_val = _PERIOD_MAP.get(period or "5d", ("day", 5))
            params["period"] = p_val if p_type == "day" else 10

    d = _get("/pricehistory", params)
    candles = d.get("candles", []) or []
    if not candles:
        return None
    df = pd.DataFrame(candles)
    idx = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.set_index(idx)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep]
    df.index.name = "Date"
    return df
