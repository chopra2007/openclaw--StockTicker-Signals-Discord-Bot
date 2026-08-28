"""TODO #100 Phase 2 — selector + Yahoo option-history downloader.

No network. Every Yahoo response is a hand-built fixture.
Covers: cache idempotence, selector tie-breaks, NO OPTION TRADE on failed
liquidity gates, spread entry-debit math, Pacific timestamp conversion.
"""

from __future__ import annotations

import json

import pytest

from scripts.research import put_flow_option_history_fetch as fetch
from scripts.research import put_flow_option_select as sel


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _chart_json(symbol: str, start_epoch: int, closes, volumes):
    ts = [start_epoch + 60 * i for i in range(len(closes))]
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"symbol": symbol, "range": "7d", "dataGranularity": "1m"},
                    "timestamp": ts,
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": closes,
                                "low": closes,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ],
        }
    }


def _put_row(symbol, strike, bid, ask, oi, *, expiry="2026-09-18",
             non_standard=0, multiplier=100.0, qq="OK", pqt=1_787_751_303.0):
    return {
        "contract_symbol": symbol,
        "expiry": expiry,
        "strike": strike,
        "option_type": "PUT",
        "bid": bid,
        "ask": ask,
        "open_interest": oi,
        "volume": 10.0,
        "multiplier": multiplier,
        "non_standard": non_standard,
        "quote_quality": qq,
        "provider_quote_time": pqt,
        "underlying_px": 122.0,
    }


# ---------------------------------------------------------------------------
# 1. cache idempotence
# ---------------------------------------------------------------------------

def test_identical_response_not_rewritten(tmp_path):
    body = json.dumps(_chart_json("XYZ", 1_787_000_000, [1.0, 1.1], [5, 0]))

    first = fetch._store_raw("XYZ", "7d", body, tmp_path)
    assert first["rewritten"] is True
    files_after_first = sorted(tmp_path.glob("XYZ__7d__*.json"))
    assert len(files_after_first) == 1

    second = fetch._store_raw("XYZ", "7d", body, tmp_path)
    assert second["rewritten"] is False
    assert second["path"] == first["path"]
    assert sorted(tmp_path.glob("XYZ__7d__*.json")) == files_after_first


def test_changed_response_makes_new_revision(tmp_path):
    body_a = json.dumps(_chart_json("XYZ", 1_787_000_000, [1.0, 1.1], [5, 0]))
    body_b = json.dumps(_chart_json("XYZ", 1_787_000_000, [1.0, 1.2], [5, 3]))

    r_a = fetch._store_raw("XYZ", "7d", body_a, tmp_path)
    r_b = fetch._store_raw("XYZ", "7d", body_b, tmp_path)

    assert r_a["rewritten"] and r_b["rewritten"]
    assert r_a["path"] != r_b["path"]
    assert r_a["sha256"] != r_b["sha256"]
    assert len(sorted(tmp_path.glob("XYZ__7d__*.json"))) == 2
    # original revision is untouched
    assert json.loads(open(r_a["path"]).read()) == json.loads(body_a)


# ---------------------------------------------------------------------------
# 2. Pacific timestamp conversion
# ---------------------------------------------------------------------------

def test_pacific_conversion_is_pacific_clock():
    # 2026-08-26 13:35:03 UTC  ->  06:35:03 Pacific (PDT, -07:00)
    iso = fetch.to_pacific_iso(1_787_751_303)
    assert iso.startswith("2026-08-26T06:35:03")
    assert iso.endswith("-07:00")


def test_summarize_span_and_fields():
    raw = _chart_json("XYZ", 1_787_751_303, [1.0, 1.1, 1.2], [0, 4, 0])
    s = fetch.summarize(raw)
    assert s["rows"] == 3
    assert s["positive_volume_rows"] == 1
    assert s["has_bid_ask"] is False
    assert set(s["fields_present"]) == {"open", "high", "low", "close", "volume"}
    assert s["earliest_ts_pacific"].startswith("2026-08-26T06:35:03")
    assert s["latest_ts_pacific"].startswith("2026-08-26T06:37:03")


def test_summarize_counts_intraday_gap():
    raw = _chart_json("XYZ", 1_787_751_303, [1, 2, 3], [1, 1, 1])
    # punch a 10-minute hole between bar 1 and bar 2
    raw["chart"]["result"][0]["timestamp"][2] += 600
    assert fetch.summarize(raw)["gap_count"] == 1


def test_quality_tier_zero_volume_is_no_trades():
    rec = {"ok": True, "has_bid_ask": False, "positive_volume_rows": 0, "gap_count": 0}
    assert fetch.quality_tier(rec) == "NO_TRADES"
    rec2 = {"ok": True, "has_bid_ask": False, "positive_volume_rows": 20, "gap_count": 0}
    assert fetch.quality_tier(rec2) == "TRADE_BAR_ONLY"
    assert fetch.quality_tier({"ok": False}) == "MISSING"


# ---------------------------------------------------------------------------
# 3. selector — expiration rule + tie-breaks
# ---------------------------------------------------------------------------

def test_choose_expiry_takes_earliest_in_window():
    # entry 2026-08-26, planned stock exit 2026-09-01
    # window = [2026-09-08, 2026-10-10]
    exps = ["2026-09-04", "2026-09-11", "2026-09-18", "2026-10-16"]
    assert sel.choose_expiry(exps, "2026-08-26", "2026-09-01") == "2026-09-11"


def test_choose_expiry_none_when_window_empty():
    assert sel.choose_expiry(["2026-09-04", "2026-11-20"], "2026-08-26", "2026-09-01") is None


def test_strike_tie_break_prefers_higher_oi_then_symbol():
    # target exactly between 120 and 122 -> equal distance; higher OI wins
    rows = [
        sel.ChainRow.from_mapping(_put_row("AAA260918P00120000", 120.0, 4.9, 5.1, 200)),
        sel.ChainRow.from_mapping(_put_row("AAA260918P00122000", 122.0, 4.9, 5.1, 900)),
    ]
    picked = sel.pick_row(rows, target=121.0)
    assert picked.contract_symbol == "AAA260918P00122000"

    # equal distance AND equal OI -> contract symbol ascending
    rows2 = [
        sel.ChainRow.from_mapping(_put_row("BBB260918P00122000", 122.0, 4.9, 5.1, 300)),
        sel.ChainRow.from_mapping(_put_row("AAA260918P00120000", 120.0, 4.9, 5.1, 300)),
    ]
    assert sel.pick_row(rows2, target=121.0).contract_symbol == "AAA260918P00120000"


def test_atm_put_selected_with_entry_ask():
    rows = [
        _put_row("DKS260918P00115000", 115.0, 2.7, 3.0, 2798),
        _put_row("DKS260918P00120000", 120.0, 4.9, 5.1, 3158),
        _put_row("DKS260918P00125000", 125.0, 7.7, 8.2, 2677),
    ]
    out = sel.select_structure(rows, 121.9771, "2026-08-26", "2026-09-01", "ATM_PUT")
    assert out.result == "SELECTED"
    assert out.expiry == "2026-09-18"
    assert out.legs[0]["contract_symbol"] == "DKS260918P00120000"
    assert out.entry["entry_ask"] == 5.1
    assert out.entry["liquidation_bid"] == 4.9
    assert out.entry["entry_cost_per_contract_usd"] == pytest.approx(510.0)


# ---------------------------------------------------------------------------
# 4. NO OPTION TRADE when liquidity gates fail
# ---------------------------------------------------------------------------

def test_no_trade_when_open_interest_below_100():
    rows = [_put_row("QQQ260918P00120000", 120.0, 4.9, 5.1, 42)]
    out = sel.select_structure(rows, 120.0, "2026-08-26", "2026-09-01", "ATM_PUT")
    assert out.result == "NO OPTION TRADE"
    assert "open interest 42 below 100" in out.reason


def test_no_trade_when_spread_exceeds_10pct_of_mid():
    # mid 2.85, spread 0.30 -> 10.5%
    rows = [_put_row("QQQ260918P00115000", 115.0, 2.70, 3.00, 5000)]
    out = sel.select_structure(rows, 121.05, "2026-08-26", "2026-09-01", "OTM5_PUT")
    assert out.result == "NO OPTION TRADE"
    assert "exceeds 10%" in out.reason


def test_no_trade_when_not_two_sided():
    rows = [_put_row("QQQ260918P00120000", 120.0, 0.0, 0.6, 5000, qq="NO_TWO_SIDED")]
    out = sel.select_structure(rows, 120.0, "2026-08-26", "2026-09-01", "ATM_PUT")
    assert out.result == "NO OPTION TRADE"
    assert "no positive bid" in out.reason


def test_no_trade_when_non_standard():
    rows = [_put_row("QQQ1260918P00120000", 120.0, 4.9, 5.1, 5000, non_standard=1)]
    out = sel.select_structure(rows, 120.0, "2026-08-26", "2026-09-01", "ATM_PUT")
    assert out.result == "NO OPTION TRADE"
    assert "non-standard" in out.reason


# ---------------------------------------------------------------------------
# 5. spread entry-debit math
# ---------------------------------------------------------------------------

def test_put_debit_spread_entry_debit_math():
    rows = [
        _put_row("MM260918P00120000", 120.0, 4.90, 5.10, 3000),  # long (ATM)
        _put_row("MM260918P00114000", 114.0, 2.60, 2.80, 3000),  # short (OTM5 of 120)
    ]
    out = sel.select_structure(rows, 120.0, "2026-08-26", "2026-09-01", "PUT_DEBIT_SPREAD")
    assert out.result == "SELECTED"
    # entry debit = long ask - short bid = 5.10 - 2.60
    assert out.entry["entry_debit"] == pytest.approx(2.50)
    # liquidation value = long bid - short ask = 4.90 - 2.80
    assert out.entry["liquidation_value"] == pytest.approx(2.10)
    sides = {l["side"]: l["contract_symbol"] for l in out.legs}
    assert sides["long"] == "MM260918P00120000"
    assert sides["short"] == "MM260918P00114000"


def test_spread_no_trade_when_a_leg_fails_gate():
    rows = [
        _put_row("MM260918P00120000", 120.0, 4.90, 5.10, 3000),
        _put_row("MM260918P00114000", 114.0, 2.60, 2.80, 50),   # short leg OI too low
    ]
    out = sel.select_structure(rows, 120.0, "2026-08-26", "2026-09-01", "PUT_DEBIT_SPREAD")
    assert out.result == "NO OPTION TRADE"
    assert "short leg" in out.reason and "below 100" in out.reason


def test_select_all_returns_three_structures():
    rows = [
        _put_row("MM260918P00114000", 114.0, 2.60, 2.80, 3000),
        _put_row("MM260918P00120000", 120.0, 4.90, 5.10, 3000),
    ]
    allsel = sel.select_all(rows, 120.0, "2026-08-26", "2026-09-01")
    assert set(allsel) == {"ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD"}
    assert allsel["ATM_PUT"]["result"] == "SELECTED"


# ---------------------------------------------------------------------------
# reconstruction (strike/expiry rule only, no quote)
# ---------------------------------------------------------------------------

def test_reconstruct_uses_strike_and_expiry_rule_only():
    exps = ["2026-09-04", "2026-09-11", "2026-09-18"]
    strikes = [250.0, 255.0, 260.0, 262.5, 265.0]
    out = sel.reconstruct_structure(
        exps, strikes, 262.365, "2026-08-25", "2026-08-31", "PUT_DEBIT_SPREAD", "AMZN"
    )
    assert out["label"] == "RECONSTRUCTED_TRADE_BAR_ONLY"
    assert out["expiry"] == "2026-09-11"
    legs = {l["side"]: l["occ_symbol"] for l in out["legs"]}
    assert legs["long"] == "AMZN260911P00262500"       # closest to 262.365
    assert legs["short"] == "AMZN260911P00250000"       # closest to 0.95*262.365 = 249.25


def test_occ_symbol_format():
    assert sel.occ_symbol("MARA", "2026-09-11", 11.5) == "MARA260911P00011500"
    assert sel.occ_symbol("DKS", "2026-09-18", 120.0) == "DKS260918P00120000"
