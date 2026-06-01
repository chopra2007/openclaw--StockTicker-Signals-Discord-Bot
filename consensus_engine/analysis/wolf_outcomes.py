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
from datetime import datetime, timedelta, timezone

from consensus_engine import config as cfg, db
from consensus_engine.analysis.wolf_scope import proxy_symbol

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

        anchor_date = datetime.fromtimestamp(anchor_ts, tz=timezone.utc).date()
        start = (anchor_date - timedelta(days=45)).isoformat()
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

        await db.record_call_outcome(t["id"], scope_type, scope_key, direction, sym,
                                     anchor_stage, anchor_ts, anchor_close, latest_close,
                                     pct, band, state, now)
        results.append({"thesis_id": t["id"], "scope_type": scope_type, "scope_key": scope_key,
                        "direction": direction, "proxy_symbol": sym, "anchor_stage": anchor_stage,
                        "pct_move": pct, "band": band, "state": state})
    return results
