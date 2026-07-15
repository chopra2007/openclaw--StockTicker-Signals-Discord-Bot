"""F4 (#76 menu) — hedge-vs-directional options-flow classifier (SHADOW ONLY).

The live flow scanner classifies a contract by side and size alone, so a
protective put on a long book looks identical to an outright bearish bet. This
module adds two shadow-only reads on top of the SAME FlowHits the live scan
produced:

  1. delta-weighted notional = premium_usd * |delta| — the real directional
     exposure of the leg (a deep-OTM lotto ticket carries far less than its
     premium implies).
  2. leg pairing within one scan cycle: same ticker + same expiry + opposite
     side + comparable delta-weighted notional -> "paired" (likely a spread or
     a hedge, not a clean directional bet).

`classify()` emits one `flow_shadow` log line per hit and returns the rows for
`scripts/flow_hedge_shadow_review.py` to compare against realized
`options_flow_outcomes`. It NEVER modifies the live alert — `format_flow_alert`
does not call this module, and a unit test locks its output byte-for-byte.
Delta is only present on the Schwab real-time chain; on the yfinance path it is
None and the verdict is `delta_unknown` (never guessed).
"""
from __future__ import annotations

import logging

from consensus_engine import config as cfg

log = logging.getLogger(__name__)


def classify(hits: list, *, pair_notional_ratio: float | None = None) -> list[dict]:
    """Shadow-classify each FlowHit. Returns one dict per hit; logs each.

    pair_notional_ratio (default features.flow_hedge_discount.pair_notional_ratio,
    0.5): two opposite-side legs on the same ticker+expiry are called "paired"
    when the smaller delta-weighted notional is at least this fraction of the
    larger — i.e. the two legs are of comparable size, the signature of a spread
    or hedge rather than one dominant directional bet.
    """
    if pair_notional_ratio is None:
        pair_notional_ratio = float(
            cfg.get("features.flow_hedge_discount.pair_notional_ratio", 0.5))

    rows: list[dict] = []
    for h in hits:
        delta = getattr(h, "delta", None)
        dwn = None if delta is None else round(h.premium_usd * abs(delta), 2)
        rows.append({
            "ticker": h.ticker,
            "side": h.side,
            "expiry": h.expiry,
            "strike": h.strike,
            "premium_usd": h.premium_usd,
            "delta": delta,
            "delta_weighted_notional": dwn,
            # directional until proven paired; delta_unknown when no greeks
            "verdict": "delta_unknown" if delta is None else "directional",
        })

    # Pairing pass: mark comparable opposite-side legs on the same ticker+expiry.
    for i, a in enumerate(rows):
        if a["verdict"] == "delta_unknown":
            continue
        na = a["delta_weighted_notional"]
        if not na or na <= 0:
            continue
        for j, b in enumerate(rows):
            if j == i or b["verdict"] == "delta_unknown":
                continue
            if a["ticker"] != b["ticker"] or a["expiry"] != b["expiry"]:
                continue
            if a["side"] == b["side"]:
                continue
            nb = b["delta_weighted_notional"]
            if not nb or nb <= 0:
                continue
            if min(na, nb) / max(na, nb) >= pair_notional_ratio:
                a["verdict"] = "paired"
                b["verdict"] = "paired"

    for r in rows:
        log.info(
            "flow_shadow: %s %s exp=%s prem=$%.0f delta=%s dw_notional=%s verdict=%s",
            r["ticker"], r["side"], r["expiry"], r["premium_usd"],
            "None" if r["delta"] is None else f"{r['delta']:.3f}",
            "None" if r["delta_weighted_notional"] is None else f"{r['delta_weighted_notional']:.0f}",
            r["verdict"],
        )
    return rows
