"""Phase-3 Sunday-recap outcomes: did Wolf's ACTIONABLE calls move his way?

Honest by construction (Codex BLOCKER-2): only theses that reached `imminent` or
`acting` are scored, anchored at the FIRST evidence-log timestamp the thesis entered
that stage — NOT created_at (a `forming` idea was never a tradeable call, and
price_at_creation is always NULL anyway). A coarse proxy-price move from that anchor
to the latest close, sign-adjusted toward Wolf's direction, with a volatility-scaled
dead-band so noisy instruments (OIL/BTC) don't earn false credit. Classification only —
the humble public wording lives in wolf_news.format_digest.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg, db
from consensus_engine.analysis.wolf_scope import is_inverse_proxy, proxy_symbol

log = logging.getLogger(__name__)

_ACTIONABLE = ("imminent", "acting")
_MIN_BAND_PCT = 0.5   # floor for the dead-band, in %


def _anchor_from_evidence(evlog: list[dict]) -> tuple[float | None, str | None]:
    """First evidence entry that ENTERED imminent/acting -> (ts, stage). None if never."""
    best: tuple[float, str] | None = None
    for e in evlog:
        to = e.get("to")
        ts = e.get("ts")
        if to in _ACTIONABLE and ts is not None:
            if best is None or float(ts) < best[0]:
                best = (float(ts), to)
    return best if best else (None, None)


def _fetch_proxy_series(symbol: str, anchor_ts: float) -> dict:
    """BLOCKING yfinance fetch. Returns {anchor_close, latest_close, band_pct} or {}.

    anchor_close = last daily close on/before the anchor date (walks back over
    weekends/holidays); band_pct = stdev of the last ~20 daily % returns.
    """
    try:
        import yfinance as yf

        # Anchor on the US MARKET (Eastern) trading date, not UTC: an evening (~7pm PT)
        # Wolf Wrap is next-day in UTC, which would mis-match yfinance's ET daily bars
        # and start the % move a day late (Codex MINOR-2).
        anchor_date = datetime.fromtimestamp(anchor_ts, tz=ZoneInfo("America/New_York")).date()
        start = (anchor_date - timedelta(days=45)).isoformat()
        # #57: DELIBERATELY stays on yfinance (NOT the Schwab OHLCV feed). These
        # 5d/20d outcome labels feed calibration built on yfinance's dividend-
        # ADJUSTED daily close; Schwab /pricehistory is split-only, so mixing the
        # two would put unadjusted rows next to historical adjusted ones (RISK-5).
        # Purely historical read — no real-time benefit from switching.
        hist = yf.Ticker(symbol).history(start=start, interval="1d")
        if hist is None or hist.empty:
            return {}
        close = hist["Close"].dropna()
        if close.empty:
            return {}

        rets = close.pct_change().dropna()
        band_pct = float(rets.tail(20).std() * 100.0) if not rets.empty else 0.0

        anchor_close = None
        for idx, val in close.items():
            try:
                d = idx.date()
            except Exception:
                continue
            if d <= anchor_date:
                anchor_close = float(val)
            else:
                break
        if anchor_close is None:
            anchor_close = float(close.iloc[0])   # all data is after the anchor; use earliest
        latest_close = float(close.iloc[-1])
        return {"anchor_close": anchor_close, "latest_close": latest_close, "band_pct": band_pct}
    except Exception as exc:
        log.debug("wolf_outcomes: proxy fetch failed for %s: %s", symbol, exc)
        return {}


def _classify(status: str, pct: float, band: float) -> str:
    if status == "invalidated":
        return "invalidated"
    if abs(pct) <= band:
        return "flat"
    return "moved_with" if pct > 0 else "moved_against"


_BENCHMARK_SPY = "SPY"

# I16: scope-aware benchmark symbol — sector scope benchmarks against SPY (the broad
# market); single-name (stock) scope also benchmarks against SPY.  Inverse-proxy scopes
# require a sign flip (handled in compute_outcomes below).
def _benchmark_symbol(scope_type: str, scope_key: str) -> str:
    """Return the benchmark symbol for a given scope.

    Both 'stock' and 'sector' scopes benchmark against SPY (the proxy IS the
    sector ETF for sector scopes, so comparing it to SPY measures sector-vs-market
    relative strength). 'market' and 'asset' scopes are rare in this path but also
    default to SPY — no meaningful alternative available from free feeds.
    """
    return _BENCHMARK_SPY


def _classify_adjusted(status: str, excess_pct: float, band: float) -> str:
    """Classify based on excess return (proxy_pct - benchmark_pct) rather than raw pct.

    'moved_with' only when the proxy BEAT the benchmark by more than the band.
    """
    if status == "invalidated":
        return "invalidated"
    if abs(excess_pct) <= band:
        return "flat"
    return "moved_with" if excess_pct > 0 else "moved_against"


async def compute_outcomes(lookback_days: int = 7) -> list[dict]:
    """Score Wolf's actionable calls and UPSERT wolf_call_outcomes. Returns a list of
    outcome dicts (for the digest renderer). Never raises on a single bad fetch."""
    now = time.time()
    since = now - lookback_days * 86400
    k = float(cfg.get("wolf.digests.outcome_band_k", 1.0))

    actives = await db.get_active_theses()
    invalid = await db.get_invalidated_theses_since(since)
    seen: set[int] = set()
    candidates: list[dict] = []
    for t in actives + invalid:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        candidates.append(t)

    loop = asyncio.get_running_loop()
    results: list[dict] = []
    for t in candidates:
        try:
            evlog = json.loads(t["evidence_log_json"]) if t["evidence_log_json"] else []
        except Exception:
            evlog = []
        anchor_ts, anchor_stage = _anchor_from_evidence(evlog)
        if anchor_ts is None:
            continue   # never actionable -> not a tradeable call -> not scored

        scope_type, scope_key, direction = t["scope_type"], t["scope_key"], t["direction"]
        sym = proxy_symbol(scope_type, scope_key)

        if sym is None:
            await db.record_call_outcome(t["id"], scope_type, scope_key, direction, None,
                                         anchor_stage, anchor_ts, None, None, None, None,
                                         "inconclusive", now)
            results.append({"thesis_id": t["id"], "scope_type": scope_type, "scope_key": scope_key,
                            "direction": direction, "proxy_symbol": None, "anchor_stage": anchor_stage,
                            "pct_move": None, "band": None, "state": "inconclusive"})
            continue

        series = await loop.run_in_executor(None, _fetch_proxy_series, sym, anchor_ts)
        if not series or not series.get("anchor_close"):
            await db.record_call_outcome(t["id"], scope_type, scope_key, direction, sym,
                                         anchor_stage, anchor_ts, None, None, None, None,
                                         "inconclusive", now)
            results.append({"thesis_id": t["id"], "scope_type": scope_type, "scope_key": scope_key,
                            "direction": direction, "proxy_symbol": sym, "anchor_stage": anchor_stage,
                            "pct_move": None, "band": None, "state": "inconclusive"})
            continue

        anchor_close = series["anchor_close"]
        latest_close = series["latest_close"]
        band = max(_MIN_BAND_PCT, k * series["band_pct"])
        raw_pct = (latest_close - anchor_close) / anchor_close * 100.0
        pct = raw_pct if direction == "bull" else -raw_pct   # +ve = moved Wolf's way
        state = _classify(t["status"], pct, band)

        # I16: benchmark-adjusted state (flag wolf.outcomes.benchmark_adjusted).
        # Surface BOTH raw and adjusted; never replace raw (honors thin-sample memory).
        # On benchmark fetch failure fall back to the raw state.
        adjusted_state: str | None = None
        benchmark_pct_value: float | None = None
        if cfg.get("wolf.outcomes.benchmark_adjusted", False):
            bm_sym = _benchmark_symbol(scope_type, scope_key)
            bm_series = await loop.run_in_executor(None, _fetch_proxy_series, bm_sym, anchor_ts)
            if bm_series and bm_series.get("anchor_close"):
                bm_ac = bm_series["anchor_close"]
                bm_lc = bm_series["latest_close"]
                bm_raw_pct = (bm_lc - bm_ac) / bm_ac * 100.0
                # For inverse-proxy scopes the thesis direction is already flipped
                # (SOXS bull = semis bear), but the benchmark (SPY) move is NOT
                # inverted — so we flip the benchmark sign to match.
                is_inv = is_inverse_proxy(scope_key)
                bm_pct_signed = (-bm_raw_pct) if is_inv else bm_raw_pct
                excess = pct - bm_pct_signed
                benchmark_pct_value = bm_pct_signed
                adjusted_state = _classify_adjusted(t["status"], excess, band)
            else:
                # Benchmark fetch failed: fall back to raw classification
                log.debug("wolf_outcomes: benchmark fetch failed for %s; using raw state", bm_sym)
                adjusted_state = state

        await db.record_call_outcome(t["id"], scope_type, scope_key, direction, sym,
                                     anchor_stage, anchor_ts, anchor_close, latest_close,
                                     pct, band, state, now)
        row: dict = {"thesis_id": t["id"], "scope_type": scope_type, "scope_key": scope_key,
                     "direction": direction, "proxy_symbol": sym, "anchor_stage": anchor_stage,
                     "pct_move": pct, "band": band, "state": state}
        if adjusted_state is not None:
            row["adjusted_state"] = adjusted_state
            row["benchmark_pct"] = benchmark_pct_value
        results.append(row)
    return results
