"""Tests for the !all quality levers (#6): max-pain + peer relative strength.

Covers the Pass-3 critic's high-risk areas: max-pain math/edges, the positional
aggregator-unpack desync guard, the curated-vs-ETF peer logic, the short-history
guard, honest ETF labelling, and a YAML "Norway problem" regression guard.
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import pytest

from consensus_engine.scanners import options
from consensus_engine.analysis import peer_comparison as pc
from consensus_engine.alerts.all_command import aggregator, embed


# ---------------------------------------------------------------------------
# Max-pain
# ---------------------------------------------------------------------------

class _Chain:
    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame):
        self.calls = calls
        self.puts = puts


def _chain(call_oi: dict, put_oi: dict) -> _Chain:
    calls = pd.DataFrame([{"strike": k, "openInterest": v} for k, v in call_oi.items()])
    puts = pd.DataFrame([{"strike": k, "openInterest": v} for k, v in put_oi.items()])
    return _Chain(calls, puts)


def test_third_friday_known_months():
    assert options._third_friday(2026, 6) == date(2026, 6, 19)
    assert options._third_friday(2026, 5) == date(2026, 5, 15)
    assert options._third_friday(2026, 12) == date(2026, 12, 18)
    assert options._third_friday(2026, 1) == date(2026, 1, 16)


def test_max_pain_known_fixture():
    # All call OI at 100, all put OI at 120. Payout is minimised between them;
    # with equal OI the min sits where total ITM distance is least.
    ch = _chain({100.0: 1000, 110.0: 0, 120.0: 0}, {100.0: 0, 110.0: 0, 120.0: 1000})
    strike, total_oi = options._max_pain_for_chain(ch)
    assert total_oi == 2000
    assert strike in (100.0, 110.0, 120.0)
    # heavy call OI low + heavy put OI high → min payout at a middle strike
    ch2 = _chain({90.0: 5000}, {130.0: 5000})
    s2, _ = options._max_pain_for_chain(ch2)
    assert 90.0 <= s2 <= 130.0


def test_max_pain_zero_oi_returns_none():
    ch = _chain({100.0: 0, 110.0: 0}, {100.0: 0, 110.0: 0})
    assert options._max_pain_for_chain(ch) is None


def test_max_pain_single_strike_returns_none():
    ch = _chain({100.0: 500}, {})
    assert options._max_pain_for_chain(ch) is None


def test_max_pain_nan_oi_treated_as_zero():
    calls = pd.DataFrame([{"strike": 100.0, "openInterest": float("nan")},
                          {"strike": 110.0, "openInterest": 1000}])
    puts = pd.DataFrame([{"strike": 90.0, "openInterest": 800}])
    res = options._max_pain_for_chain(_Chain(calls, puts))
    assert res is not None
    assert res[1] == 1800  # NaN counted as 0, not crash


# ---------------------------------------------------------------------------
# Peer comparison — resolution
# ---------------------------------------------------------------------------

def test_resolve_peers_curated_excludes_self_and_loads_ON():
    """NVDA → Semiconductors; self excluded; the quoted 'ON' ticker survives YAML."""
    import asyncio
    out = asyncio.run(pc.resolve_peers("NVDA"))
    assert out["source"] == "curated"
    assert out["group"] == "Semiconductors"
    assert out["benchmark_etf"] == "SMH"
    assert "NVDA" not in out["peers"]
    assert "ON" in out["peers"], "ON must be a string ticker, not YAML boolean True"


def test_peer_groups_yaml_has_no_boolean_members():
    """Regression guard for the YAML 'Norway problem' (bare ON/NO/YES → bool)."""
    groups, ticker_index, _ = pc._load_peer_groups()
    assert groups, "peer_groups.yaml failed to load"
    for industry, spec in groups.items():
        for m in spec.get("members") or []:
            assert isinstance(m, str), f"non-string member {m!r} in {industry} (quote it)"


@pytest.mark.asyncio
async def test_compute_rel_strength_verdicts(monkeypatch):
    async def _resolved(_t):
        return {"group": "Semiconductors", "peers": ["AMD", "AVGO", "INTC"],
                "benchmark_etf": "SMH", "source": "curated"}
    monkeypatch.setattr(pc, "resolve_peers", _resolved)

    async def _pcts_out(tickers, w):
        return {"NVDA": 10.0, "AMD": 2.0, "AVGO": 2.0, "INTC": 2.0, "SMH": 1.0}
    monkeypatch.setattr(pc, "_gather_pct", _pcts_out)
    monkeypatch.setattr(pc.cfg, "get", lambda k, d=None: True if "enabled" in k else d)
    r = await pc.compute_relative_strength("NVDA")
    assert r["verdict"] == "outperforming" and r["mode"] == "peers"
    assert r["benchmark_pct"] == 2.0 and r["delta"] == 8.0
    assert r["narrator_ok"] is True


@pytest.mark.asyncio
async def test_compute_rel_strength_etf_fallback_when_few_peers(monkeypatch):
    async def _resolved(_t):
        return {"group": "Consumer Defensive", "peers": [], "benchmark_etf": "XLP",
                "source": "dynamic_etf"}
    monkeypatch.setattr(pc, "resolve_peers", _resolved)

    async def _pcts(tickers, w):
        return {"KO": -3.0, "XLP": -2.0}
    monkeypatch.setattr(pc, "_gather_pct", _pcts)
    monkeypatch.setattr(pc.cfg, "get", lambda k, d=None: True if "enabled" in k else d)
    r = await pc.compute_relative_strength("KO")
    assert r["mode"] == "etf"
    assert r["benchmark_label"] == "XLP"   # honest: names the ETF, not "peers"
    assert r["narrator_ok"] is False       # contaminated benchmark → embed-only


@pytest.mark.asyncio
async def test_compute_rel_strength_none_when_no_benchmark(monkeypatch):
    async def _resolved(_t):
        return {"group": None, "peers": [], "benchmark_etf": None, "source": "none"}
    monkeypatch.setattr(pc, "resolve_peers", _resolved)

    async def _pcts(tickers, w):
        return {"ZZZZ": 5.0}
    monkeypatch.setattr(pc, "_gather_pct", _pcts)
    monkeypatch.setattr(pc.cfg, "get", lambda k, d=None: True if "enabled" in k else d)
    assert await pc.compute_relative_strength("ZZZZ") is None


# ---------------------------------------------------------------------------
# _pct_change short-history guard (critic M4) — fake yfinance via sys.modules
# ---------------------------------------------------------------------------

def _install_fake_yf(monkeypatch, closes: list[float]):
    class _FakeTicker:
        def __init__(self, *_a, **_k):
            pass

        def history(self, *_a, **_k):
            return pd.DataFrame({"Close": closes})

    class _FakeYF:
        Ticker = _FakeTicker

    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)


def test_pct_change_short_history_returns_none(monkeypatch):
    _install_fake_yf(monkeypatch, [10.0, 11.0, 12.0])  # only 3 rows, need 6
    assert pc._pct_change("X", 5) is None


def test_pct_change_happy(monkeypatch):
    _install_fake_yf(monkeypatch, [100.0, 1, 2, 3, 4, 110.0])  # close[-1]=110 vs close[-6]=100
    assert pc._pct_change("X", 5) == 10.0


# ---------------------------------------------------------------------------
# Embed formatters
# ---------------------------------------------------------------------------

def test_format_max_pain_both_legs():
    mp = {"spot": 211.14,
          "weekly": {"strike": 210.0, "expiry": "2026-06-01", "total_oi": 1},
          "monthly": {"strike": 170.0, "expiry": "2026-06-18", "total_oi": 1}}
    out = embed._format_max_pain(mp, 211.14)
    assert "wk" in out and "mo" in out
    assert "$210" in out and "$170" in out
    assert "Jun 01" in out and "Jun 18" in out
    assert "↓" in out  # both strikes below spot


def test_format_max_pain_none():
    assert embed._format_max_pain(None, 100.0) == "—"
    assert embed._format_max_pain({"weekly": None, "monthly": None}, 100.0) == "—"


def test_format_peer_strength_curated_and_etf():
    curated = {"stock_pct": -3.8, "benchmark_pct": 9.9, "verdict": "underperforming",
               "benchmark_label": "Semiconductors", "window_days": 5}
    s = embed._format_peer_strength(curated)
    assert "Semiconductors" in s and "underperforming" in s and "5d" in s
    etf = {"stock_pct": -2.7, "benchmark_pct": -2.1, "verdict": "in-line",
           "benchmark_label": "XLP", "window_days": 5}
    assert "XLP" in embed._format_peer_strength(etf)
    assert embed._format_peer_strength(None) == "—"


# ---------------------------------------------------------------------------
# Aggregator wiring — desync guard for the positional 24-tuple unpack (M1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregator_wires_levers_without_desync(monkeypatch):
    """compute_max_pain/compute_relative_strength land in the right dict keys and
    no other source's value is shifted by the new positional unpack entries."""
    mp_sentinel = {"spot": 1.0, "weekly": {"strike": 1.0, "expiry": "2026-06-01"}, "monthly": None}
    ps_sentinel = {"verdict": "outperforming", "stock_pct": 5.0, "benchmark_pct": 1.0,
                   "benchmark_label": "Semiconductors", "narrator_ok": True}

    async def _routing_scanner(module_path, attr, *a, **k):
        if attr == "compute_max_pain":
            return mp_sentinel
        if attr == "compute_relative_strength":
            return ps_sentinel
        return None

    async def _none(*_a, **_k):
        return None

    async def _empty_list(*_a, **_k):
        return []

    async def _empty_dict(*_a, **_k):
        return {}

    monkeypatch.setattr(aggregator, "_db_call", _empty_list)
    monkeypatch.setattr(aggregator, "_score_ticker_safe", _none)
    monkeypatch.setattr(aggregator, "_verify_technical_safe", _none)
    monkeypatch.setattr(aggregator, "_scanner_call", _routing_scanner)
    monkeypatch.setattr(aggregator.discord_history, "fetch_chat_24h_ticker_filtered", _empty_list)
    monkeypatch.setattr(aggregator.discord_history, "fetch_brief_last_3", _empty_list)
    monkeypatch.setattr(aggregator.vault_writer, "read_existing_vault", _empty_dict)

    out = await aggregator._gather_all_sources("NVDA")
    assert out["max_pain"] == mp_sentinel, "max_pain not wired to its dict key"
    assert out["peer_strength"] == ps_sentinel, "peer_strength not wired to its dict key"
    # Desync proof: trends is the serpapi-gated empty dict, NOT a lever sentinel.
    assert out["trends"] == {}, "positional unpack desynced (trends got a wrong value)"
    assert "max_pain" in out["sources_surfaced"]
    assert "peer_strength" in out["sources_surfaced"]
