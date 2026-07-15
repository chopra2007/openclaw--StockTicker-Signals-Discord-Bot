"""F4 (#76 menu) — hedge-vs-directional options-flow classifier (shadow only).

Covers:
  1. FlowHit.delta is captured from a Schwab-shaped chain (has a delta column)
     and stays None on a yfinance-shaped chain (no greeks).
  2. classify(): delta-weighted notional math; directional vs paired vs
     delta_unknown verdicts.
  3. format_flow_alert output is BYTE-IDENTICAL with the new delta field — the
     live alert must not change.
  4. the shadow-review log parser round-trips a real log line.
"""
from __future__ import annotations

import time

import pandas as pd

from consensus_engine.models import FlowHit
from consensus_engine.scanners import options, flow_hedge


def _chain(has_delta: bool):
    """A namedtuple-ish chain with .calls/.puts DataFrames, one qualifying row."""
    cols = {
        "contractSymbol": ["X"], "strike": [100.0], "lastPrice": [10.0],
        "volume": [5000], "openInterest": [100],
        "lastTradeDate": [pd.Timestamp.now(tz="UTC")],
    }
    if has_delta:
        cols["delta"] = [0.55]
    calls = pd.DataFrame(cols)
    puts = pd.DataFrame({k: [] for k in cols})

    class _Ch:
        pass
    ch = _Ch()
    ch.calls, ch.puts = calls, puts
    return ch


def test_delta_captured_from_schwab_chain():
    hits = options._scan_chain_for_flow(
        "NVDA", _chain(has_delta=True), "2026-07-18", 105.0,
        min_vol_oi=5.0, min_volume=500, min_premium=250_000,
        max_stale_sec=3600, now=time.time())
    assert len(hits) == 1
    assert hits[0].delta == 0.55


def test_delta_none_on_yfinance_chain():
    hits = options._scan_chain_for_flow(
        "NVDA", _chain(has_delta=False), "2026-07-18", 105.0,
        min_vol_oi=5.0, min_volume=500, min_premium=250_000,
        max_stale_sec=3600, now=time.time())
    assert len(hits) == 1
    assert hits[0].delta is None


def _hit(ticker, side, expiry, prem, delta):
    return FlowHit(
        ticker=ticker, side=side, strike=100.0, expiry=expiry,
        volume=5000, open_interest=100, vol_oi_ratio=50.0, premium_usd=prem,
        last_trade_ts=time.time(), spot=105.0, delta=delta)


def test_classify_directional_and_notional():
    rows = flow_hedge.classify([_hit("NVDA", "CALL", "2026-07-18", 3_000_000, 0.55)])
    assert rows[0]["verdict"] == "directional"
    assert rows[0]["delta_weighted_notional"] == round(3_000_000 * 0.55, 2)


def test_classify_delta_unknown_when_no_greeks():
    rows = flow_hedge.classify([_hit("NVDA", "CALL", "2026-07-18", 3_000_000, None)])
    assert rows[0]["verdict"] == "delta_unknown"
    assert rows[0]["delta_weighted_notional"] is None


def test_classify_pairs_opposite_legs_of_comparable_size():
    # A CALL and a PUT on the same ticker+expiry with comparable delta-weighted
    # notional -> both flagged 'paired' (likely a spread/hedge, not a clean bet).
    hits = [
        _hit("NVDA", "CALL", "2026-07-18", 3_000_000, 0.55),   # dwn 1,650,000
        _hit("NVDA", "PUT", "2026-07-18", 3_200_000, 0.52),    # dwn 1,664,000
    ]
    rows = flow_hedge.classify(hits, pair_notional_ratio=0.5)
    assert {r["verdict"] for r in rows} == {"paired"}


def test_classify_does_not_pair_lopsided_legs():
    # A huge call and a tiny put -> the call stays directional (not a hedge).
    hits = [
        _hit("NVDA", "CALL", "2026-07-18", 5_000_000, 0.60),   # dwn 3,000,000
        _hit("NVDA", "PUT", "2026-07-18", 300_000, 0.20),      # dwn 60,000
    ]
    rows = flow_hedge.classify(hits, pair_notional_ratio=0.5)
    verdicts = {r["side"]: r["verdict"] for r in rows}
    assert verdicts["CALL"] == "directional"


_FIXED_HIT = FlowHit(
    ticker="TSLA", side="CALL", strike=435.0, expiry="2026-05-29",
    volume=12345, open_interest=1000, vol_oi_ratio=12.3, premium_usd=4_200_000.0,
    last_trade_ts=1_700_000_000.0, spot=430.12)


def test_format_flow_alert_byte_identical_with_delta():
    # The live alert must be unchanged by F4. Assert the exact string, and that
    # setting delta does not alter a single byte of it.
    expected = (
        "⚡ **UNUSUAL OPTIONS FLOW** — `$TSLA` 🟢 BULLISH\n"
        "**CALL** 2026-05-29 $435 strike | spot $430.12\n"
        "Volume **12,345** vs OI 1,000 (**12.3x** — fresh positioning) | premium **$4.20M**\n"
        "_Unusual-flow instant trigger._"
    )
    assert options.format_flow_alert(_FIXED_HIT) == expected
    hit_with_delta = FlowHit(**{**_FIXED_HIT.__dict__, "delta": -0.42})
    assert options.format_flow_alert(hit_with_delta) == expected


def test_shadow_review_parses_log_line(tmp_path):
    from scripts import flow_hedge_shadow_review as rev
    log = tmp_path / "eng.log"
    log.write_text(
        "2026-07-14 21:23:35,686 [INFO] consensus_engine.scanners.flow_hedge: "
        "flow_shadow: NVDA CALL exp=2026-07-18 prem=$3000000.0 delta=0.550 "
        "dw_notional=1650000 verdict=directional\n")
    rows = rev.parse_log(log, None)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["verdict"] == "directional"
    assert rows[0]["delta"] == 0.55
    out = rev.report(rows)
    assert "1 hit(s)" in out and "directional=1" in out
