"""Regime-shift detector stub.

Detects adverse market conditions (vol spike, poor breadth, trend breaks) that
indicate signals are less reliable. When a bad regime is detected, the caller
should raise the abstain threshold (min_base_score_for_alert) to reduce false
positives during choppy or crisis markets.

This is a stub implementation: it uses recent DB signals as a proxy for breadth
and contradiction. A full implementation would incorporate VIX, advance/decline
ratio, and multi-timeframe trend data.
"""

import logging
from dataclasses import dataclass

log = logging.getLogger("consensus_engine.analysis.regime_detector")


@dataclass
class RegimeResult:
    """Result of a regime-shift check."""
    is_adverse: bool
    reason: str
    abstain_boost: int          # Extra points to add to min_base_score_for_alert
    contradiction_index: float  # 0.0 = all aligned, 1.0 = fully contradictory
    breadth_bull_pct: float     # Fraction of recent signals that are bullish


async def detect_regime() -> RegimeResult:
    """Check current market regime using recent signal data.

    Returns a RegimeResult indicating whether the regime is adverse and by
    how much the abstain threshold should be raised.

    Stub logic:
    - Pull last-hour signal sentiment mix from DB
    - Compute contradiction_index = min(bull_pct, bear_pct) * 2 (0=all-one-way, 1=50/50)
    - Breadth = bull_pct of all directional signals
    - If contradiction_index > threshold OR breadth < threshold → adverse
    """
    from consensus_engine import config as cfg, db

    enabled = cfg.get("regime_detector.enabled", True)
    if not enabled:
        return RegimeResult(
            is_adverse=False,
            reason="regime detector disabled",
            abstain_boost=0,
            contradiction_index=0.0,
            breadth_bull_pct=1.0,
        )

    vol_spike_threshold = cfg.get("regime_detector.vol_spike_threshold", 3.0)
    breadth_min_bull_pct = cfg.get("regime_detector.breadth_min_bull_pct", 0.3)
    contradiction_index_max = cfg.get("regime_detector.contradiction_index_max", 0.6)
    abstain_score_boost = cfg.get("regime_detector.abstain_score_boost", 20)

    try:
        conn = await db.get_db()
        import time
        cutoff = time.time() - 3600  # last hour

        cursor = await conn.execute(
            """SELECT sentiment, COUNT(*) as cnt FROM ticker_signals
               WHERE detected_at >= ? AND sentiment IN ('bullish', 'bearish')
               GROUP BY sentiment""",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        counts = {r["sentiment"]: r["cnt"] for r in rows}
        bull = counts.get("bullish", 0)
        bear = counts.get("bearish", 0)
        total_directional = bull + bear

        if total_directional < 5:
            # Not enough data to judge regime — assume neutral
            return RegimeResult(
                is_adverse=False,
                reason="insufficient signal data for regime assessment",
                abstain_boost=0,
                contradiction_index=0.0,
                breadth_bull_pct=0.5,
            )

        bull_pct = bull / total_directional
        bear_pct = bear / total_directional
        contradiction_index = min(bull_pct, bear_pct) * 2.0  # 0 = one-sided, 1 = 50/50

        reasons = []
        is_adverse = False

        if contradiction_index > contradiction_index_max:
            is_adverse = True
            reasons.append(f"high contradiction ({contradiction_index:.2f} > {contradiction_index_max})")

        if bull_pct < breadth_min_bull_pct:
            is_adverse = True
            reasons.append(f"poor breadth ({bull_pct:.0%} bullish < {breadth_min_bull_pct:.0%} threshold)")

        reason = "; ".join(reasons) if reasons else "regime OK"
        boost = abstain_score_boost if is_adverse else 0

        if is_adverse:
            log.warning("Adverse regime detected: %s (boost abstain by %d)", reason, boost)

        return RegimeResult(
            is_adverse=is_adverse,
            reason=reason,
            abstain_boost=boost,
            contradiction_index=contradiction_index,
            breadth_bull_pct=bull_pct,
        )

    except Exception as e:
        log.error("Regime detector error: %s", e)
        return RegimeResult(
            is_adverse=False,
            reason=f"detector error: {e}",
            abstain_boost=0,
            contradiction_index=0.0,
            breadth_bull_pct=0.5,
        )
