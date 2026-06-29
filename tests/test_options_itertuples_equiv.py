"""C8 (reliability-hardening): replace pandas .iterrows() with .itertuples() in
the options row loops (faster, lower per-row overhead). This is a pure refactor
— output MUST be byte-identical. These characterization tests pin the exact
current behavior (incl. NaN volume/OI guards and a missing column) so the
refactor is provably equivalent. They pass on the pre-refactor code and must
stay green after."""
from types import SimpleNamespace

import pandas as pd

from consensus_engine.scanners import options


def _chain(calls_rows, puts_rows):
    calls = pd.DataFrame(calls_rows) if calls_rows else pd.DataFrame()
    puts = pd.DataFrame(puts_rows) if puts_rows else pd.DataFrame()
    return SimpleNamespace(calls=calls, puts=puts)


def test_detect_unusual_activity_equivalence():
    ts = pd.Timestamp("2026-06-27 19:55:00", tz="UTC")
    calls = [
        {"contractSymbol": "C_A", "strike": 100.0, "volume": 5000.0,
         "openInterest": 1000.0, "lastPrice": 2.0, "lastTradeDate": ts},
        {"contractSymbol": "C_B", "strike": 110.0, "volume": float("nan"),
         "openInterest": 500.0, "lastPrice": 1.0, "lastTradeDate": ts},
        {"contractSymbol": "C_C", "strike": 120.0, "volume": 200.0,
         "openInterest": float("nan"), "lastPrice": 1.0, "lastTradeDate": ts},
    ]
    puts = [
        {"contractSymbol": "P_D", "strike": 90.0, "volume": 300.0,
         "openInterest": 100.0, "lastPrice": 1.5, "lastTradeDate": ts},
    ]
    r = options._detect_unusual_activity(_chain(calls, puts))
    assert r.unusual_calls is True
    assert r.unusual_puts is True
    assert r.max_call_ratio == 5.0
    assert r.max_put_ratio == 3.0
    assert r.top_contract == "C_A"
    assert r.total_call_vol == 5200.0  # 5000 + 0(NaN) + 200
    assert r.total_put_vol == 300.0
    assert r.put_call_ratio == round(300.0 / 5200.0, 2)
    assert r.dominant_side == "call"
    assert r.premium_notional == round(2.0 * 5000.0 * 100.0, 2)


def test_detect_unusual_handles_missing_contractsymbol_column():
    """A frame lacking the contractSymbol column must not raise (old code used
    row.get with a default); top_contract falls back to empty string."""
    calls = [{"strike": 100.0, "volume": 5000.0, "openInterest": 1000.0,
              "lastPrice": 2.0, "lastTradeDate": pd.Timestamp("2026-06-27", tz="UTC")}]
    r = options._detect_unusual_activity(_chain(calls, []))
    assert r.unusual_calls is True
    assert r.top_contract == ""


def test_scan_chain_for_flow_equivalence():
    ts = pd.Timestamp("2026-06-27 19:55:00", tz="UTC")
    now = ts.timestamp() + 60  # 1 min after the trade -> fresh
    calls = [
        # qualifies: ratio 10x, vol 1000, premium 5*1000*100 = 500k
        {"contractSymbol": "C_A", "strike": 100.0, "volume": 1000.0,
         "openInterest": 100.0, "lastPrice": 5.0, "lastTradeDate": ts},
        # disqualified: NaN openInterest -> oi 0 -> skip
        {"contractSymbol": "C_B", "strike": 105.0, "volume": 1000.0,
         "openInterest": float("nan"), "lastPrice": 5.0, "lastTradeDate": ts},
    ]
    chain = _chain(calls, [])
    hits = options._scan_chain_for_flow(
        "AAPL", chain, "2026-07-03", 99.0,
        min_vol_oi=5.0, min_volume=500, min_premium=250_000.0,
        max_stale_sec=3600, now=now,
    )
    assert len(hits) == 1
    h = hits[0]
    assert h.ticker == "AAPL"
    assert h.side == "CALL"
    assert h.strike == 100.0
    assert h.volume == 1000
    assert h.open_interest == 100
    assert h.vol_oi_ratio == 10.0
    assert h.premium_usd == 500_000.0
    assert h.contract_symbol == "C_A"


def test_scan_chain_for_flow_stale_skipped():
    ts = pd.Timestamp("2026-06-20 19:55:00", tz="UTC")  # a week old
    now = pd.Timestamp("2026-06-27 19:55:00", tz="UTC").timestamp()
    calls = [{"contractSymbol": "C_A", "strike": 100.0, "volume": 1000.0,
              "openInterest": 100.0, "lastPrice": 5.0, "lastTradeDate": ts}]
    hits = options._scan_chain_for_flow(
        "AAPL", _chain(calls, []), "2026-07-03", 99.0,
        min_vol_oi=5.0, min_volume=500, min_premium=250_000.0,
        max_stale_sec=3600, now=now,
    )
    assert hits == []  # stale -> skipped
