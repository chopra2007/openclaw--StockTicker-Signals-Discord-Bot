"""Post-earnings-announcement drift (PEAD) classifier — r17 (standalone-scanners).

Reads the last earnings print via earnings_calendar.fetch_recent_earnings_for_ticker
(eps_surprise_pct + period date), measures the REALIZED price drift since that date
from yfinance history, and classifies it as drift-consistent / faded / reversed
relative to the surprise sign.

Structurally distinct from the live earnings_magnitude bonus
(cross_reference._earnings_magnitude_bonus), which keys off surprise SIZE only
within recency_days=5 of the print. PEAD activates AFTER that window (day 5+
post-print, up to a bounded multi-week horizon) and keys off realized drift, so
the two NEVER double-count — the ≤5-day silence is enforced in ``classify_pead``.

Descriptive-only in !all by default; the optional confluence leg
(_compute_pead_pts in cross_reference) is a small capped, direction-compatible
LIFT on an already-triggered signal — never a standalone trigger.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# Provenance label (render rule): make clear this is realized post-print drift,
# a different quantity than the surprise-size magnitude bonus.
PEAD_PROVENANCE = "post-earnings drift (realized, since last print)"


def classify_pead(
    eps_surprise_pct: Optional[float],
    eps_period: Optional[str],
    dated_closes: list[tuple[str, float]],
    *,
    min_days_after: int = 5,
    max_days_after: int = 45,
    min_surprise_pct: float = 2.0,
    faded_threshold_pct: float = 2.0,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Pure PEAD core. Returns a result dict or None (never raises on bad input).

    ``dated_closes`` is a chronological list of (YYYY-MM-DD, close) pairs.

    Returns None (silent) when:
      - the surprise or period is missing/unparseable,
      - |surprise| < min_surprise_pct (near-zero surprise carries no drift signal),
      - the print is < min_days_after days old (MUTUAL EXCLUSION with the
        earnings_magnitude bonus's recency_days window — no double-count),
      - the print is > max_days_after days old (drift horizon lapsed),
      - no close is available on/after the print date, or the baseline close is 0.

    Otherwise returns:
      {classification, drift_pct, days_since, surprise_pct, direction,
       earnings_close, last_close}
      classification ∈ {"drift-consistent", "faded", "reversed"}
      direction ∈ {"long", "short"}  (continuation direction implied by the surprise)
    """
    if eps_surprise_pct is None or not eps_period:
        return None
    try:
        surprise = float(eps_surprise_pct)
    except (TypeError, ValueError):
        return None
    if abs(surprise) < min_surprise_pct:
        return None

    now = now or datetime.now(timezone.utc)
    try:
        period_dt = datetime.strptime(str(eps_period)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    days_since = (now - period_dt).days
    # ≤ min_days_after → earnings_magnitude's window owns it (silent here).
    if days_since < min_days_after or days_since > max_days_after:
        return None

    if not dated_closes:
        return None
    period_iso = period_dt.date().isoformat()
    # Baseline = first close on/after the print date; latest = last close.
    earnings_close = None
    for d, c in dated_closes:
        if d >= period_iso and c:
            earnings_close = float(c)
            break
    if not earnings_close:
        return None
    last_close = None
    for d, c in reversed(dated_closes):
        if c:
            last_close = float(c)
            break
    if not last_close:
        return None

    drift_pct = (last_close - earnings_close) / earnings_close * 100.0
    surprise_sign = 1 if surprise > 0 else -1
    continuation_dir = "long" if surprise_sign > 0 else "short"

    if abs(drift_pct) < faded_threshold_pct:
        classification = "faded"
    elif (drift_pct > 0) == (surprise_sign > 0):
        classification = "drift-consistent"
    else:
        classification = "reversed"

    return {
        "classification": classification,
        "drift_pct": round(drift_pct, 2),
        "days_since": days_since,
        "surprise_pct": round(surprise, 2),
        "direction": continuation_dir,
        "earnings_close": round(earnings_close, 4),
        "last_close": round(last_close, 4),
    }


def _dated_closes_from_history(hist) -> list[tuple[str, float]]:
    """Extract chronological (YYYY-MM-DD, close) pairs from a fetch_history DataFrame."""
    out: list[tuple[str, float]] = []
    try:
        if hist is None or getattr(hist, "empty", True):
            return out
        for ts, close in hist["Close"].items():
            try:
                d = ts.date().isoformat()
            except AttributeError:
                d = str(ts)[:10]
            try:
                out.append((d, float(close)))
            except (TypeError, ValueError):
                continue
    except Exception as exc:  # noqa: BLE001 — any shape drift → no drift signal
        log.debug("pead: could not read history closes: %s", exc)
        return []
    out.sort(key=lambda x: x[0])
    return out


async def compute_pead(
    ticker: str,
    recap: Optional[dict] = None,
    *,
    min_days_after: int = 5,
    max_days_after: int = 45,
    min_surprise_pct: float = 2.0,
    faded_threshold_pct: float = 2.0,
    executor=None,
) -> Optional[dict]:
    """Fetch inputs and return a PEAD result for ``ticker``, or None.

    ``recap`` (from earnings_calendar.fetch_recent_earnings_for_ticker) may be
    passed to avoid a second earnings fetch; when None it is fetched here. The
    daily price history is fetched via utils.prices.fetch_history in an executor
    (blocking yfinance path) — only ever called when a caller has already checked
    the features.pead.enabled flag, so the OFF path does zero network work.
    """
    from consensus_engine.scanners.earnings_calendar import fetch_recent_earnings_for_ticker
    from consensus_engine.utils import prices

    if recap is None:
        recap = await fetch_recent_earnings_for_ticker(ticker)
    if not recap:
        return None
    surprise = recap.get("eps_surprise_pct")
    period = recap.get("period")
    if surprise is None or not period:
        return None

    loop = asyncio.get_event_loop()
    try:
        hist = await loop.run_in_executor(
            executor, lambda: prices.fetch_history(ticker, period="3mo")
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("pead: price history fetch failed for %s: %s", ticker, exc)
        return None

    dated_closes = _dated_closes_from_history(hist)
    return classify_pead(
        surprise, period, dated_closes,
        min_days_after=min_days_after,
        max_days_after=max_days_after,
        min_surprise_pct=min_surprise_pct,
        faded_threshold_pct=faded_threshold_pct,
    )
