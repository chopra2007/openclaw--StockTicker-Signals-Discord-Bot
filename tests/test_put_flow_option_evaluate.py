"""Unit tests for scripts/research/put_flow_option_evaluate.py (TODO #100).

No network. Small hand-built fixtures only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, date, time
from pathlib import Path

import pandas as pd
import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "research"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import put_flow_option_evaluate as ev  # noqa: E402

EMPTY_FS = {"by_sig": {}, "probe_by_contract": {}, "present": False,
            "_manifest_stats": {}}


# --------------------------------------------------------------------------- #
# Self-contained test policy + stock sample.
#
# These tests must pass on a clean checkout, so nothing here may read the
# server-only files under .omc/research/ (they are git-ignored).  The shape
# mirrors the real frozen policy; the numbers are the ones the tests assert on.
# --------------------------------------------------------------------------- #
TEST_POLICY_NAME = "put_flow_option_trade_system_test"
TEST_TODO = 100


def _mini_policy():
    return {
        "policy_name": TEST_POLICY_NAME,
        "todo": TEST_TODO,
        "authored_before_reading_any_option_outcome": True,
        "data_cut": {
            "entry_time_pacific": "06:35",
            "join_keys": ["market_date", "ticker"],
            "stock_sample_csv": "tests/fixture (in-memory)",
            "stock_sample_sha256": None,
            "underlying_entry_price_field": "stock_entry_px",
        },
        "split": {
            "method": "chronological",
            "unit": "unique signal date (market_date)",
            "development_fraction": 0.6,
            "evaluation_fraction": 0.4,
        },
        "structures": [
            {"id": "ATM_PUT", "legs": [
                {"side": "long", "type": "PUT",
                 "strike_target": "closest listed strike to stock_entry_px"}]},
            {"id": "OTM5_PUT", "legs": [
                {"side": "long", "type": "PUT",
                 "strike_target": "closest listed strike to 0.95 * stock_entry_px"}]},
            {"id": "PUT_DEBIT_SPREAD", "legs": [
                {"side": "long", "type": "PUT",
                 "strike_target": "closest listed strike to stock_entry_px"},
                {"side": "short", "type": "PUT",
                 "strike_target": "closest listed strike to 0.95 * stock_entry_px"}]},
        ],
        "exit_policies": [dict(TIME_ONLY), dict(PT25), {
            "id": "PT50_SL35", "target_pct": 0.5, "stop_pct": -0.35}],
        "development_choice_order": [
            "passes all development gates",
            "highest date-grouped conservative lower estimate of average net return",
        ],
        "gates": {
            "G1_full_sample_size": {"scope": "full eligible sample",
                                    "min_eligible_trades": 100,
                                    "min_signal_dates": 30, "min_stocks": 40},
            "G2_evaluation_size": {"scope": "untouched evaluation",
                                   "min_eligible_trades": 40,
                                   "min_signal_dates": 15, "min_stocks": 20,
                                   "on_failure": "verdict INSUFFICIENT DATA, never PASS"},
            "G3_avg_net_return_positive": {"scope": "both"},
            "G4_date_grouped_95_range_above_zero": {"scope": "both"},
            "G5_win_rate": {"scope": "both", "min_win_rate": 0.55,
                            "min_lower_95_win_rate": 0.5},
            "G6_profit_factor": {"scope": "both", "min": 1.25},
            "G7_halves_positive": {"scope": "earlier and later half inside BOTH "
                                            "development and evaluation"},
            "G8_concentration": {"max_share_of_total_profit_per_ticker": 0.1,
                                 "max_share_of_total_profit_per_signal_date": 0.1},
            "G9_portfolio": {"starting_capital_usd": 100000,
                             "max_open_positions": 16,
                             "max_premium_fraction_per_position": 0.0625,
                             "max_drawdown": 0.1,
                             "require_positive_finish": True},
            "G10_timing_sensitivity": {"entries_pacific": ["06:35", "06:40", "06:45"],
                                       "require": "frozen 06:35 passes AND at least "
                                                  "one neighbour positive with "
                                                  "profit factor > 1.0",
                                       "forbid": "moving production timing to the "
                                                 "best row"},
            "G11_overlap_suppressed": {"require": "still positive when overlapping "
                                                  "repeat signals in the same ticker "
                                                  "are suppressed"},
            "G12_proof_tier": {"require": "historical bid/ask, OR an independently "
                                          "verified conservative trade-bar model "
                                          "PLUS forward Schwab bid evidence",
                               "forbid": "PASS from a last-price-only backtest"},
        },
    }


def _write_policy(tmp_path, policy=None):
    """Write a policy file plus its correct fingerprint under tmp_path."""
    body = json.dumps(policy if policy is not None else _mini_policy(),
                      indent=2, sort_keys=True) + "\n"
    pol = tmp_path / "frozen-policy.json"
    pol.write_text(body)
    sha = tmp_path / "frozen-policy.sha256"
    sha.write_text(ev.sha256_bytes(body.encode()) + "  frozen-policy.json\n")
    return pol, sha


def _mini_stock_sample():
    """Six trades over five signal dates - enough for a chronological split."""
    rows = []
    dates = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    tick = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    for i, md in enumerate(dates + [dates[-1]]):
        rows.append({"market_date": md, "rank": 1, "ticker": tick[i],
                     "entry_date": md, "exit_date": "2026-06-12",
                     "stock_entry_px": 100.0 + i})
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _reset_globals():
    """Keep the module-level frozen-selections / entry-time globals from leaking
    between tests."""
    ev._FROZEN_SELECTIONS = dict(EMPTY_FS)
    ev.ENTRY_TIME = ev.dtime(6, 35)
    yield
    ev._FROZEN_SELECTIONS = dict(EMPTY_FS)
    ev.ENTRY_TIME = ev.dtime(6, 35)


PT25 = {"id": "PT25_SL35", "target_pct": 0.25, "stop_pct": -0.35}
TIME_ONLY = {"id": "TIME_ONLY", "target_pct": None, "stop_pct": None}

D1 = date(2026, 6, 2)   # entry day
D2 = date(2026, 6, 3)
D3 = date(2026, 6, 4)
D4 = date(2026, 6, 8)   # frozen fourth-session exit day
ENTRY_DT = datetime.combine(D1, time(6, 35), tzinfo=ev.PACIFIC)


def bar(day, hh, mm, lo, hi, vol, bid=None, ask=None):
    return {
        "dt": datetime.combine(day, time(hh, mm), tzinfo=ev.PACIFIC),
        "open": None, "high": hi, "low": lo, "close": None,
        "volume": float(vol), "bid": bid, "ask": ask,
    }


# --------------------------------------------------------------------------- #
# Frozen policy hash
# --------------------------------------------------------------------------- #
def test_frozen_policy_hash_mismatch_aborts(tmp_path):
    bad = tmp_path / "policy.json"
    bad.write_text('{"policy_name": "tampered"}')
    sha = tmp_path / "policy.sha256"
    sha.write_text("deadbeef  policy.json\n")
    with pytest.raises(SystemExit):
        ev.verify_frozen_policy(policy_path=bad, sha_path=sha)


def test_frozen_policy_verifies_a_matching_file(tmp_path):
    pol, sha = _write_policy(tmp_path)
    policy = ev.verify_frozen_policy(policy_path=pol, sha_path=sha)
    assert policy["policy_name"] == TEST_POLICY_NAME
    assert policy["todo"] == TEST_TODO


# --------------------------------------------------------------------------- #
# Split
# --------------------------------------------------------------------------- #
def test_split_keeps_whole_date_together():
    dev, evl = ev.build_split(
        ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-03",
         "2026-06-04", "2026-06-05"]
    )
    assert dev.isdisjoint(evl)
    # 5 unique dates, need >= 3.0 -> development takes the first 3
    assert dev == {"2026-06-01", "2026-06-02", "2026-06-03"}
    assert evl == {"2026-06-04", "2026-06-05"}


def test_split_assignment_consistent_per_market_date():
    sdf = pd.DataFrame([
        {"market_date": "2026-06-01", "rank": 1, "ticker": "AAA",
         "entry_date": "2026-06-02", "exit_date": "2026-06-08",
         "stock_entry_px": 100.0},
        {"market_date": "2026-06-01", "rank": 2, "ticker": "BBB",
         "entry_date": "2026-06-02", "exit_date": "2026-06-08",
         "stock_entry_px": 50.0},
        {"market_date": "2026-06-03", "rank": 1, "ticker": "CCC",
         "entry_date": "2026-06-04", "exit_date": "2026-06-10",
         "stock_entry_px": 20.0},
    ])
    rows, _ = ev.evaluate_candidate(
        "ATM_PUT", TIME_ONLY, sdf, {"2026-06-01"}, {"2026-06-03"},
        Path("/nonexistent"), None, lambda *a, **k: {"reason": "x"},
    )
    by_md = {}
    for r in rows:
        by_md.setdefault(r["market_date"], set()).add(r["split"])
    assert by_md["2026-06-01"] == {"development"}
    assert by_md["2026-06-03"] == {"evaluation"}


# --------------------------------------------------------------------------- #
# Pricing math
# --------------------------------------------------------------------------- #
def test_commissions_one_and_two_legs():
    assert ev.commission_round_trip_per_share(1) == pytest.approx(0.009)
    assert ev.commission_round_trip_per_share(2) == pytest.approx(0.018)


def test_long_put_pricing_directions_and_net_return():
    leg = ev.Leg("long", [bar(D1, 6, 35, lo=0.90, hi=1.10, vol=5)])
    pos = ev.Position([leg])
    mk = ENTRY_DT
    assert pos.n_legs == 1
    assert pos.entry_debit_at(mk) == 1.10               # long entry = ask/HIGH
    assert pos.liquidation_range_at(mk) == (0.90, 1.10)  # long liq = bid/LOW
    got = ev.net_return(1.10, 0.90, 1)
    assert got == pytest.approx((0.90 - 1.10 - 0.009) / 1.10)


def test_spread_pricing_directions():
    long_leg = ev.Leg("long", [bar(D1, 6, 35, lo=2.0, hi=2.5, vol=5)])
    short_leg = ev.Leg("short", [bar(D1, 6, 35, lo=1.0, hi=1.3, vol=5)])
    pos = ev.Position([long_leg, short_leg])
    mk = ENTRY_DT
    assert pos.n_legs == 2
    # debit = long ask - short bid = long HIGH - short LOW = 2.5 - 1.0
    assert pos.entry_debit_at(mk) == pytest.approx(1.5)
    # liquidation = long bid - short ask = (long LOW - short HIGH, long HIGH - short LOW)
    assert pos.liquidation_range_at(mk) == (pytest.approx(0.7), pytest.approx(1.5))
    assert ev.net_return(1.5, 0.7, 2) == pytest.approx((0.7 - 1.5 - 0.018) / 1.5)


# --------------------------------------------------------------------------- #
# Exit engine
# --------------------------------------------------------------------------- #
def test_target_before_stop():
    pos = ev.Position([ev.Leg("long", [
        bar(D1, 6, 35, 0.95, 1.05, 5),
        bar(D2, 9, 0, 1.30, 1.40, 5),   # LOW 1.30 >= target 1.25 -> conservative fill
    ])])
    out = ev.apply_exit_policy(pos, PT25, 1.0, ENTRY_DT, D4)
    assert out.outcome == "TARGET"
    assert out.liquidation_value == pytest.approx(1.25)
    assert out.proof_tier == ev.TIER_CONS


def test_stop_before_target():
    pos = ev.Position([ev.Leg("long", [
        bar(D1, 6, 35, 0.95, 1.05, 5),
        bar(D2, 9, 0, 0.55, 0.62, 5),   # LOW 0.55 <= stop 0.65
    ])])
    out = ev.apply_exit_policy(pos, PT25, 1.0, ENTRY_DT, D4)
    assert out.outcome == "STOP"
    assert out.liquidation_value == pytest.approx(0.65)


def test_same_bar_ambiguity_resolves_to_stop():
    pos = ev.Position([ev.Leg("long", [
        bar(D1, 6, 35, 0.95, 1.05, 5),
        bar(D2, 9, 0, 0.55, 1.45, 5),   # touches BOTH stop and target in one bar
    ])])
    out = ev.apply_exit_policy(pos, PT25, 1.0, ENTRY_DT, D4)
    assert out.outcome == "STOP"
    assert "stop" in out.note.lower()


def test_zero_volume_bar_cannot_trigger():
    pos = ev.Position([ev.Leg("long", [
        bar(D1, 6, 35, 0.95, 1.05, 5),
        bar(D2, 9, 0, 0.50, 0.60, 0),   # would stop, but zero volume
        bar(D4, 6, 36, 0.92, 0.98, 5),  # exit-window bar
    ])])
    out = ev.apply_exit_policy(pos, PT25, 1.0, ENTRY_DT, D4)
    assert out.outcome == "TIME"
    assert out.liquidation_value == pytest.approx(0.92)  # LOW of exit bar


def test_possible_touch_vs_conservative_trade_bar():
    # HIGH crosses target but LOW does not -> possible touch, not a fill
    pos = ev.Position([ev.Leg("long", [
        bar(D1, 6, 35, 0.95, 1.05, 5),
        bar(D2, 9, 0, 1.10, 1.30, 5),   # hi 1.30 >= 1.25 > lo 1.10
        bar(D4, 6, 36, 1.00, 1.05, 5),
    ])])
    out = ev.apply_exit_policy(pos, PT25, 1.0, ENTRY_DT, D4)
    assert out.outcome == "TIME"
    assert out.proof_tier == ev.TIER_POSS
    assert out.liquidation_value == pytest.approx(1.00)


def test_missing_spread_synchronization_is_unknown():
    long_leg = ev.Leg("long", [
        bar(D2, 9, 0, 2.0, 2.5, 5), bar(D3, 9, 0, 2.1, 2.6, 5),
    ])
    short_leg = ev.Leg("short", [bar(D1, 6, 35, 1.0, 1.3, 5)])  # never lines up
    pos = ev.Position([long_leg, short_leg])
    out = ev.apply_exit_policy(pos, PT25, 1.5, ENTRY_DT, D4)
    assert out.outcome == "UNKNOWN"
    assert "synchron" in out.note.lower()


# --------------------------------------------------------------------------- #
# Entry-window / pre-06:35 rejection (through evaluate_candidate)
# --------------------------------------------------------------------------- #
def test_option_bars_before_0635_are_rejected(tmp_path):
    bf = tmp_path / "XYZ.csv"
    bf.write_text(
        "minute,open,high,low,close,volume\n"
        "2026-06-02 06:30:00,1,1.20,0.90,1.00,10\n"   # pre-entry -> must drop
        "2026-06-02 06:36:00,1,1.10,1.00,1.05,10\n"   # entry bar
        "2026-06-08 06:36:00,1,0.80,0.70,0.75,10\n"   # exit bar
    )
    manifest = pd.DataFrame([{
        "market_date": "2026-06-02", "ticker": "XYZ", "structure_id": "ATM_PUT",
        "leg_side": "long", "contract_symbol": "XYZ_C", "bars_file": "XYZ.csv",
    }])
    sdf = pd.DataFrame([{
        "market_date": "2026-06-02", "rank": 1, "ticker": "XYZ",
        "entry_date": "2026-06-02", "exit_date": "2026-06-08",
        "stock_entry_px": 100.0,
    }])

    def sel(structure_id, chain_rows, px, ed, xd):
        return {"contracts": [{"contract_symbol": "XYZ_C", "side": "long",
                               "bars_file": "XYZ.csv"}]}

    rows, bits = ev.evaluate_candidate(
        "ATM_PUT", TIME_ONLY, sdf, {"2026-06-02"}, set(),
        tmp_path, manifest, sel,
    )
    assert bits["pre_entry_bars_dropped"] >= 1
    r = rows[0]
    assert r["outcome"] == "TIME"
    assert float(r["entry_debit"]) == pytest.approx(1.10)      # HIGH of 06:36 entry bar
    assert float(r["liquidation_value"]) == pytest.approx(0.70)  # LOW of exit bar


# --------------------------------------------------------------------------- #
# Portfolio (G9)
# --------------------------------------------------------------------------- #
def _g9():
    return _mini_policy()["gates"]["G9_portfolio"]


def test_portfolio_16_position_cap_and_overflow_rejection():
    rows = [{
        "proof_tier": ev.TIER_CONS, "net_return": 0.1, "entry_debit": 1.0,
        "entry_date": "2026-06-02", "exit_date": "2026-06-08", "ticker": f"T{i}",
    } for i in range(17)]
    p = ev.simulate_portfolio(rows, _g9())
    assert p["n_positions"] == 17
    assert p["n_overflow_rejections"] == 1


def test_portfolio_premium_cap_rejects_too_expensive_position():
    rows = [{
        "proof_tier": ev.TIER_CONS, "net_return": 0.1, "entry_debit": 100.0,
        "entry_date": "2026-06-02", "exit_date": "2026-06-08", "ticker": "BIG",
    }]
    p = ev.simulate_portfolio(rows, _g9())
    assert p["n_premium_cap_rejections"] == 1
    assert p["n_positions"] == 0


# --------------------------------------------------------------------------- #
# Concentration (G8)
# --------------------------------------------------------------------------- #
def test_concentration_math():
    rows = [
        {"proof_tier": ev.TIER_CONS, "net_return": 0.5,
         "market_date": "2026-06-01", "ticker": "AAA"},
        {"proof_tier": ev.TIER_CONS, "net_return": 0.5,
         "market_date": "2026-06-02", "ticker": "BBB"},
        {"proof_tier": ev.TIER_CONS, "net_return": -0.2,
         "market_date": "2026-06-03", "ticker": "AAA"},
    ]
    c = ev.concentration(rows)
    assert c["total_profit"] == pytest.approx(1.0)
    assert c["max_ticker_share"] == pytest.approx(0.5)
    assert c["max_date_share"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Selector adapter + C1 / C2 / C3 clarifications
# --------------------------------------------------------------------------- #
def _stock_one(ticker="AAPL", md="2026-06-03", entry="2026-06-04",
               exit_="2026-06-10", px=310.0):
    return pd.DataFrame([{
        "market_date": md, "rank": 1, "ticker": ticker,
        "entry_date": entry, "exit_date": exit_, "stock_entry_px": px,
    }])


def _fs_with(md, ticker, contracts_by_structure):
    """Build a frozen_selections dict with one per_trade entry."""
    return {
        "by_sig": {(md, ticker): {"signal_date": md, "ticker": ticker,
                                  "contracts": contracts_by_structure}},
        "probe_by_contract": {},
        "present": True,
        "_manifest_stats": {},
    }


def test_c1_spread_legs_same_contract_is_no_option_trade():
    fs = _fs_with("2026-06-03", "DKS", {
        "PUT_DEBIT_SPREAD": {
            "long": {"occ_symbol": "DKS260620P00120000"},
            "short": {"occ_symbol": "DKS260620P00120000"},
        }})
    rows, _ = ev.evaluate_candidate(
        "PUT_DEBIT_SPREAD", TIME_ONLY, _stock_one("DKS", px=121.98),
        {"2026-06-03"}, set(), Path("/nonexistent"), None, None,
        frozen_selections=fs,
    )
    assert rows[0]["outcome"] == "NO_OPTION_TRADE"
    assert rows[0]["reason_code"] == "spread_legs_same_contract"
    assert "same contract" in rows[0]["note"]


def test_c2_structures_collapsed_flag_when_atm_equals_otm5():
    contracts = {
        "ATM_PUT": {"long": {"occ_symbol": "AAPL260620P00310000"}},
        "OTM5_PUT": {"long": {"occ_symbol": "AAPL260620P00310000"}},
    }
    fs = _fs_with("2026-06-03", "AAPL", contracts)
    ev._FROZEN_SELECTIONS = fs
    policy = _mini_policy()
    stock = _stock_one("AAPL")
    all_rows, _ = ev.build_all_rows(
        policy, stock, {"2026-06-03"}, set(), Path("/nonexistent"), None, None,
    )
    atm = [r for r in all_rows if r["structure_id"] == "ATM_PUT"]
    otm = [r for r in all_rows if r["structure_id"] == "OTM5_PUT"]
    spr = [r for r in all_rows if r["structure_id"] == "PUT_DEBIT_SPREAD"]
    assert atm and all(r["structures_collapsed"] == "true" for r in atm)
    assert otm and all(r["structures_collapsed"] == "true" for r in otm)
    assert spr and all(r["structures_collapsed"] == "false" for r in spr)
    # C2: the collapsed pair is counted once, not twice, in metrics
    m = ev.candidate_metrics(atm)
    assert m["n_structures_collapsed"] == len(atm)


def test_c3_closest_strike_then_veto_no_step_out():
    """The evaluator surfaces a selector 'NO OPTION TRADE' verbatim and never
    reaches past the vetoed strike."""
    calls = {}

    def sel(structure_id, chain_rows, px, ed, xd):
        calls["n"] = calls.get("n", 0) + 1
        # closest strike failed liquidity; selector refuses (Reading A)
        return {"structure": structure_id, "result": "NO OPTION TRADE",
                "reason": "long leg fails eligibility -> quoted spread 12% > 10%"}

    manifest = pd.DataFrame([{
        "signal_date": "2026-06-03", "ticker": "MSTR", "structure": "ATM_PUT",
        "contract": "MSTR260620P00124000", "leg": "long",
    }])
    rows, _ = ev.evaluate_candidate(
        "ATM_PUT", TIME_ONLY, _stock_one("MSTR", px=124.06),
        {"2026-06-03"}, set(), Path("/nonexistent"), manifest, sel,
        frozen_selections=EMPTY_FS,
    )
    assert calls["n"] == 1                       # asked once, not hunting outward
    assert rows[0]["outcome"] == "NO_OPTION_TRADE"
    assert "12%" in rows[0]["note"]


def test_missing_selector_module_is_hard_abort(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "put_flow_option_select":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ev.SelectorUnavailable):
        ev.resolve_selector(None)


# --------------------------------------------------------------------------- #
# frozen-sample-selections bridge + honest join / sparsity reporting
# --------------------------------------------------------------------------- #
def test_frozen_selections_bridge_names_contract_and_expired_404_is_unknown():
    fs = {
        "by_sig": {("2026-06-03", "NVDA"): {
            "signal_date": "2026-06-03", "ticker": "NVDA",
            "contracts": {"ATM_PUT": {"long": {"occ_symbol": "NVDA260620P00200000"}}},
        }},
        "probe_by_contract": {
            "NVDA260620P00200000": {"contract": "NVDA260620P00200000",
                                    "is_404": True, "http_status": 404,
                                    "missing_reason": "expired/delisted"}},
        "present": True,
        "_manifest_stats": {},
    }
    rows, bits = ev.evaluate_candidate(
        "ATM_PUT", TIME_ONLY, _stock_one("NVDA"), {"2026-06-03"}, set(),
        Path("/nonexistent"), None, None, frozen_selections=fs,
    )
    assert rows[0]["chain_source"] == "frozen-sample-selections"
    assert rows[0]["contract_symbols"] == "NVDA260620P00200000"
    assert rows[0]["outcome"] == "UNKNOWN"
    assert rows[0]["reason_code"] == "expired_404"
    assert bits["signals_named_but_no_bars"] == 1


def test_no_stored_chain_counted_separately_from_404():
    rows, bits = ev.evaluate_candidate(
        "ATM_PUT", TIME_ONLY, _stock_one("ZZZ"), {"2026-06-03"}, set(),
        Path("/nonexistent"), None, None, frozen_selections=EMPTY_FS,
    )
    assert rows[0]["outcome"] == "UNKNOWN"
    assert rows[0]["reason_code"] == "no_stored_entry_chain"
    assert bits["signals_no_stored_chain"] == 1
    assert bits["signals_named_but_no_bars"] == 0


def test_broken_join_aborts_loudly():
    join = {"manifest_present": True, "manifest_rows": 100,
            "manifest_rows_joined": 2, "manifest_join_fraction": 0.02}
    with pytest.raises(ev.BrokenJoin):
        ev.check_join_health(join)
    # a healthy join does not raise
    ev.check_join_health({"manifest_present": True, "manifest_rows": 100,
                          "manifest_rows_joined": 90,
                          "manifest_join_fraction": 0.90})


def test_bar_sparsity_block_splits_frozen_and_live():
    manifest = pd.DataFrame([
        {"contract": "A260620P1", "ticker": "A", "http_status": "200",
         "rows": "1000", "positive_volume_rows": "27", "sample": "frozen_181"},
        {"contract": "B260620P1", "ticker": "B", "http_status": "404",
         "rows": "0", "positive_volume_rows": "0", "sample": "frozen_181"},
        {"contract": "C260620P1", "ticker": "C", "http_status": "200",
         "rows": "2000", "positive_volume_rows": "40", "sample": "live_open_8"},
    ])
    block = ev.bar_sparsity_block(manifest)
    assert set(block) == {"frozen_181", "live_open_8"}
    fz = block["frozen_181"]
    assert fz["total_one_minute_bars"] == 1000
    assert fz["positive_volume_bars"] == 27
    assert fz["positive_volume_pct"] == pytest.approx(2.7)
    assert fz["http_404"] == 1 and fz["http_200"] == 1
    assert len(fz["per_contract"]) == 2
    assert block["live_open_8"]["positive_volume_pct"] == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# Evaluation-split structural lock
# --------------------------------------------------------------------------- #
def test_evaluation_split_refused_without_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "verify_frozen_policy",
                        lambda *a, **k: _mini_policy())
    ns = argparse.Namespace(out=str(tmp_path), data_root=str(tmp_path / "nd"),
                            manifest=None)
    with pytest.raises(SystemExit):
        ev.run_evaluation(ns)


def test_evaluation_split_refused_when_chosen_is_null(tmp_path):
    out = tmp_path
    body = json.dumps({"chosen": None}) + "\n"
    (out / "chosen-development-rule.json").write_text(body)
    (out / "chosen-development-rule.json.sha256").write_text(
        ev.sha256_bytes(body.encode()) + "  chosen-development-rule.json\n")
    with pytest.raises(SystemExit):
        ev.require_evaluation_unlocked(out)


def test_tampered_fingerprint_keeps_evaluation_locked(tmp_path):
    (tmp_path / "chosen-development-rule.json").write_text('{"chosen": {"x": 1}}')
    (tmp_path / "chosen-development-rule.json.sha256").write_text(
        "0" * 64 + "  chosen-development-rule.json\n")
    with pytest.raises(SystemExit):
        ev.require_evaluation_unlocked(tmp_path)


def test_full_split_runs_without_fingerprint_and_reports_counts(tmp_path,
                                                                monkeypatch):
    """--split full needs no chosen rule; it reports real per-candidate counts."""
    monkeypatch.setattr(ev, "verify_frozen_policy",
                        lambda *a, **k: _mini_policy())
    monkeypatch.setattr(ev, "load_stock_sample",
                        lambda *a, **k: _mini_stock_sample())
    monkeypatch.setattr(ev, "FROZEN_SELECTIONS_PATH", tmp_path / "no-selections.json")
    out = tmp_path / "out"
    ns = argparse.Namespace(data_root=str(tmp_path / "nd"),
                            manifest=str(tmp_path / "no-manifest.csv"),
                            out=str(out))
    ev.run_full(ns)
    g = json.loads((out / "gates.json").read_text())
    assert g["phase"] == "full"
    assert g["chosen_rule"] is None
    assert g["verdict"] == "INSUFFICIENT DATA"
    assert len(g["candidates"]) == 9
    atm = g["candidates"]["ATM_PUT__TIME_ONLY"]
    g1 = next(x for x in atm["gates"] if x["id"] == "G1_full_sample_size")
    assert g1["verdict"] == "INSUFFICIENT DATA"
    assert g1["actual"]["eligible"] == 0
    assert g1["threshold"]["min_eligible_trades"] == 100
    dq = json.loads((out / "data-quality.json").read_text())
    assert "bar_sparsity" in dq and "chain_coverage" in dq
    # no chosen rule must be written
    assert not (out / "chosen-development-rule.json").exists()


def test_yahoo_chart_json_bars_parse(tmp_path):
    payload = {"chart": {"result": [{
        "timestamp": [1_780_000_000, 1_780_000_060],
        "indicators": {"quote": [{
            "open": [1.0, 1.1], "high": [1.2, 1.3], "low": [0.9, 1.0],
            "close": [1.1, 1.2], "volume": [10, 0]}]}}]}}
    f = tmp_path / "OCC260101P00100000.json"
    f.write_text(json.dumps(payload))
    bars = ev.load_bars(f)
    assert len(bars) == 2
    assert bars[0]["high"] == 1.2 and bars[0]["low"] == 0.9
    assert bars[0]["volume"] == 10 and bars[1]["volume"] == 0


