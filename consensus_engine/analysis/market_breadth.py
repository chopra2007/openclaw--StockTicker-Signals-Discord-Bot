"""Market-breadth participation proxy — r20 (standalone-scanners).

DISTINCT data from internal_breadth (the bot's OWN signal-stream net bull/bear).
This measures whole-market participation via the RSP/SPY ratio trend:

  RSP = S&P 500 EQUAL-weight ETF  (the average stock)
  SPY = S&P 500 CAP-weight ETF    (mega-cap-led)

  RSP/SPY rising  → breadth BROADENING (the average stock is participating)
  RSP/SPY falling → breadth NARROWING  (a few mega-caps carry the tape)

Optionally adds IWM/SPY (small-cap vs large-cap) as a second participation read.

Descriptive-only regime read: forward-logged into market_breadth_daily for later
edge-testing and rendered in the !market dashboard. It is NEVER wired into
cross_reference.score_ticker (matches the proven-no-edge market-context posture).

(The true-A/D upgrade via a nasdaq advancers/decliners endpoint was left as a
deferred owed-check; the equal-weight proxy meets the goal — broad vs narrow
participation — on a confirmed free feed without a fragile ~500-name fan-out.)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _ratio_trend(num_hist, den_hist, window_days: int) -> Optional[tuple[float, float]]:
    """Return (latest_ratio, pct_trend_over_window) for num/den close series, or None."""
    try:
        if num_hist is None or den_hist is None:
            return None
        if getattr(num_hist, "empty", True) or getattr(den_hist, "empty", True):
            return None
        ratio = (num_hist["Close"] / den_hist["Close"]).dropna()
        if len(ratio) < 2:
            return None
        latest = float(ratio.iloc[-1])
        idx = max(0, len(ratio) - 1 - window_days)
        start = float(ratio.iloc[idx])
        if start == 0:
            return None
        trend_pct = (latest / start - 1.0) * 100.0
        return round(latest, 4), round(trend_pct, 2)
    except Exception as exc:  # noqa: BLE001 — any shape drift → no read
        log.debug("market_breadth: ratio trend failed: %s", exc)
        return None


async def compute_market_breadth(
    *,
    window_days: int = 20,
    trend_threshold_pct: float = 0.5,
    executor=None,
) -> Optional[dict]:
    """Fetch RSP/SPY (+ IWM) and return the participation-proxy read, or None.

    Only ever called after a caller checks features.market_breadth.enabled, so the
    OFF path does zero network work. Returns None if the RSP/SPY leg is unavailable.
    """
    from consensus_engine.utils import prices

    loop = asyncio.get_event_loop()

    def _fetch(sym: str):
        try:
            return prices.fetch_history(sym, period="2mo")
        except Exception as exc:  # noqa: BLE001
            log.debug("market_breadth: fetch %s failed: %s", sym, exc)
            return None

    rsp, spy, iwm = await asyncio.gather(
        loop.run_in_executor(executor, _fetch, "RSP"),
        loop.run_in_executor(executor, _fetch, "SPY"),
        loop.run_in_executor(executor, _fetch, "IWM"),
    )

    rsp_spy = _ratio_trend(rsp, spy, window_days)
    if rsp_spy is None:
        return None
    rsp_spy_ratio, rsp_spy_trend = rsp_spy

    iwm_spy = _ratio_trend(iwm, spy, window_days)
    iwm_spy_ratio, iwm_spy_trend = (iwm_spy if iwm_spy is not None else (None, None))

    if rsp_spy_trend > trend_threshold_pct:
        state = "broadening"
    elif rsp_spy_trend < -trend_threshold_pct:
        state = "narrowing"
    else:
        state = "flat"

    return {
        "rsp_spy_ratio": rsp_spy_ratio,
        "rsp_spy_trend": rsp_spy_trend,
        "iwm_spy_ratio": iwm_spy_ratio,
        "iwm_spy_trend": iwm_spy_trend,
        "breadth_state": state,
        "window_days": window_days,
    }


async def forward_log_market_breadth(
    *,
    window_days: int = 20,
    trend_threshold_pct: float = 0.5,
    executor=None,
) -> Optional[dict]:
    """Compute the breadth read and forward-log it into market_breadth_daily.

    Returns the computed dict (also persisted) or None. Descriptive-only — the
    persisted rows accumulate for later edge-testing and feed the !market panel.
    """
    from consensus_engine import db

    read = await compute_market_breadth(
        window_days=window_days, trend_threshold_pct=trend_threshold_pct, executor=executor,
    )
    if read is None:
        return None
    date_utc = datetime.now(timezone.utc).date().isoformat()
    try:
        await db.upsert_market_breadth_daily(
            date_utc=date_utc,
            rsp_spy_ratio=read["rsp_spy_ratio"],
            rsp_spy_trend=read["rsp_spy_trend"],
            iwm_spy_ratio=read["iwm_spy_ratio"],
            iwm_spy_trend=read["iwm_spy_trend"],
            breadth_state=read["breadth_state"],
            window_days=read["window_days"],
        )
    except Exception as exc:  # noqa: BLE001 — logging failure never breaks !market
        log.debug("market_breadth: forward-log failed: %s", exc)
    return read
