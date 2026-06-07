"""Wave 7 — options flow #5 channel routing, #17 selection_mode, #18 relative baseline gate.

All three changes are flag-gated; the flag-OFF defaults preserve current behavior.
"""
import time
import tempfile
import os
import types

import pandas as pd
import pytest

from consensus_engine import config as cfg
from consensus_engine import main as cmain
from consensus_engine import db
from consensus_engine.models import FlowHit
from consensus_engine.scanners.options import (
    _scan_chain_for_flow,
    scan_options_flow,
    _flow_relative_ratio,
)


# ---------------------------------------------------------------------------
# #5 — options-flow alerts route to their own channel (blank -> fall back to main)
# ---------------------------------------------------------------------------

class _FakeResp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    """Records the channel id from each POST url so the test can assert routing."""

    def __init__(self):
        self.posted_urls: list[str] = []

    def post(self, url, **kwargs):
        self.posted_urls.append(url)
        return _FakeResp()


@pytest.fixture
def _cfg_overrides(monkeypatch):
    """Override config getters with a dict so the test controls channel ids."""
    values: dict[str, str] = {}
    real_get = cfg.get

    def fake_get(key, default=None):
        if key in values:
            return values[key]
        return real_get(key, default)

    monkeypatch.setattr(cfg, "get", fake_get)
    monkeypatch.setattr(cfg, "get_api_key", lambda name: "TESTTOKEN")
    monkeypatch.setattr(cfg, "dry_run", False, raising=False)
    return values


async def test_options_channel_routes_to_dedicated_id(_cfg_overrides, monkeypatch):
    _cfg_overrides["api_keys.options_flow_channel_id"] = "999000111"
    _cfg_overrides["api_keys.discord_channel_id"] = "111222333"
    sess = _FakeSession()

    async def fake_session():
        return sess

    monkeypatch.setattr(cmain, "get_session", fake_session)
    await cmain._post_to_options_channel("hello flow")
    assert len(sess.posted_urls) == 1
    assert "/channels/999000111/messages" in sess.posted_urls[0]


async def test_options_channel_blank_falls_back_to_main(_cfg_overrides, monkeypatch):
    _cfg_overrides["api_keys.options_flow_channel_id"] = ""   # blank -> fall through
    _cfg_overrides["api_keys.discord_channel_id"] = "111222333"
    sess = _FakeSession()

    async def fake_session():
        return sess

    monkeypatch.setattr(cmain, "get_session", fake_session)
    await cmain._post_to_options_channel("hello flow")
    assert len(sess.posted_urls) == 1
    assert "/channels/111222333/messages" in sess.posted_urls[0]


async def test_flow_scan_calls_options_channel_not_alerts(_cfg_overrides, monkeypatch):
    """The flow-alert post must go through _post_to_options_channel, not _post_to_alerts_channel."""
    hit = FlowHit("AAPL", "CALL", 200, "2026-06-20", 5000, 500, 10.0,
                  3_000_000, time.time(), 195)

    async def fake_scan(*a, **k):
        return [hit]

    options_calls: list[str] = []
    alerts_calls: list[str] = []

    async def fake_options_post(text):
        options_calls.append(text)

    async def fake_alerts_post(text):
        alerts_calls.append(text)

    async def fake_active(min_signals=1):
        return ["AAPL"]

    async def fake_last_ts(t):
        return None

    async def fake_insert(hits, alerted_tickers=None):
        return None

    monkeypatch.setattr("consensus_engine.scanners.options.scan_options_flow", fake_scan)
    monkeypatch.setattr(cmain, "_post_to_options_channel", fake_options_post)
    monkeypatch.setattr(cmain, "_post_to_alerts_channel", fake_alerts_post)
    monkeypatch.setattr(db, "get_active_tickers", fake_active)
    monkeypatch.setattr(db, "get_last_flow_alert_ts", fake_last_ts)
    monkeypatch.setattr(db, "insert_options_flow", fake_insert)

    await cmain._run_options_flow_scan()
    assert len(options_calls) == 1 and "AAPL" in options_calls[0]
    assert alerts_calls == []


# ---------------------------------------------------------------------------
# #17 — selection_mode "relative" ranks by premium/baseline ratio
# ---------------------------------------------------------------------------

def _mk_hit(ticker, premium, vol_oi=10.0):
    return FlowHit(ticker, "CALL", 100, "2026-06-20", 5000, 500, vol_oi,
                   float(premium), time.time(), 100.0)


def test_selection_relative_outranks_megacap():
    """SPY huge raw premium but mediocre ratio; small-cap + SPY outrank MSTR under relative.

    Ratios: SPY 200M/11.5M=17.4, small-cap 3M/0.3M=10, MSTR 8M/1.16M=6.9.
    Premium order: SPY > MSTR > small-cap. Relative order: SPY > small-cap > MSTR.
    """
    spy = _mk_hit("SPY", 200_000_000)
    mstr = _mk_hit("MSTR", 8_000_000)
    small = _mk_hit("SMALL", 3_000_000)
    baselines = {"SPY": 11_500_000.0, "MSTR": 1_160_000.0, "SMALL": 300_000.0}

    spy_ratio = _flow_relative_ratio(spy, baselines)
    small_ratio = _flow_relative_ratio(small, baselines)
    mstr_ratio = _flow_relative_ratio(mstr, baselines)
    # small-cap and SPY both beat MSTR on ratio
    assert small_ratio > mstr_ratio and spy_ratio > mstr_ratio
    # SPY's baseline 11.5M < premium*0.1 (20M) so the divisor clamps to 20M -> ratio 10.0
    # (the premium*0.1 floor prevents a tiny baseline from inflating the ratio).
    assert spy_ratio == pytest.approx(200_000_000 / 20_000_000, rel=1e-6)   # 10.0
    assert mstr_ratio == pytest.approx(8_000_000 / 1_160_000, rel=1e-6)     # 6.9
    assert small_ratio == pytest.approx(3_000_000 / 300_000, rel=1e-6)      # 10.0

    # Under relative sort, the ranked order puts both small-cap and SPY above MSTR.
    ranked_relative = sorted([spy, mstr, small],
                             key=lambda h: (_flow_relative_ratio(h, baselines), h.vol_oi_ratio),
                             reverse=True)
    rel_tickers = [h.ticker for h in ranked_relative]
    assert rel_tickers.index("SPY") < rel_tickers.index("MSTR")
    assert rel_tickers.index("SMALL") < rel_tickers.index("MSTR")

    # Under premium sort (default), SPY dominates and raw premium wins.
    ranked_premium = sorted([spy, mstr, small], key=lambda h: h.premium_usd, reverse=True)
    assert [h.ticker for h in ranked_premium] == ["SPY", "MSTR", "SMALL"]


def test_selection_default_premium_unchanged():
    """Flag default 'premium' -> raw-premium sort, current behavior."""
    chain = types.SimpleNamespace(
        calls=pd.DataFrame([
            {"strike": 100, "volume": 5000, "openInterest": 500, "lastPrice": 6.0,
             "lastTradeDate": pd.Timestamp(time.time(), unit="s", tz="UTC"), "contractSymbol": "A"},
        ]),
        puts=pd.DataFrame([]),
    )
    # selection_mode defaults to "premium"; ranking by raw premium descending.
    hits_premium = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                        min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                        max_stale_sec=0, now=time.time())
    assert len(hits_premium) == 1


# ---------------------------------------------------------------------------
# #18 — relative baseline gate (flag-gated, skipped on cold-start)
# ---------------------------------------------------------------------------

def _chain_one(strike, vol, oi, last_price):
    ts = pd.Timestamp(time.time(), unit="s", tz="UTC")
    return types.SimpleNamespace(
        calls=pd.DataFrame([{"strike": strike, "volume": vol, "openInterest": oi,
                             "lastPrice": last_price, "lastTradeDate": ts,
                             "contractSymbol": "X"}]),
        puts=pd.DataFrame([]),
    )


def test_relative_gate_passes_when_premium_clears_baseline():
    """$300k premium, baseline $50k, multiplier 3x -> 300k >= 150k -> PASS."""
    chain = _chain_one(100, 5000, 500, 0.60)  # premium 5000*0.60*100 = 300_000
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                max_stale_sec=0, now=time.time(),
                                relative_baseline_enabled=True, relative_multiplier=3.0,
                                baseline=50_000.0)
    assert len(hits) == 1
    assert hits[0].premium_usd == 300_000


def test_relative_gate_fails_when_below_baseline():
    """$300k premium, baseline $5M, multiplier 3x -> 300k < 15M -> REJECT."""
    chain = _chain_one(100, 5000, 500, 0.60)  # premium 300_000
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                max_stale_sec=0, now=time.time(),
                                relative_baseline_enabled=True, relative_multiplier=3.0,
                                baseline=5_000_000.0)
    assert hits == []


def test_relative_gate_passes_on_cold_start_none_baseline():
    """baseline None (<10 rows history) -> relative gate SKIPPED -> flat floor only -> PASS."""
    chain = _chain_one(100, 5000, 500, 0.60)  # premium 300_000 clears flat $250k floor
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                max_stale_sec=0, now=time.time(),
                                relative_baseline_enabled=True, relative_multiplier=3.0,
                                baseline=None)
    assert len(hits) == 1


def test_relative_gate_off_is_unchanged():
    """Flag OFF -> relative baseline ignored even when a baseline is present."""
    chain = _chain_one(100, 5000, 500, 0.60)  # premium 300_000
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                max_stale_sec=0, now=time.time(),
                                relative_baseline_enabled=False, relative_multiplier=3.0,
                                baseline=5_000_000.0)
    assert len(hits) == 1  # would be rejected if the gate were on


# ---------------------------------------------------------------------------
# db.get_flow_premium_baseline — real schema via tmp_db fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db():
    prev = db.DB_PATH
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    try:
        os.unlink(db.DB_PATH)
    except OSError:
        pass
    db.DB_PATH = prev
    db._db = None


async def test_premium_baseline_none_below_10_rows(tmp_db):
    hits = [FlowHit("AAPL", "CALL", 200, "2026-06-20", 5000, 500, 10.0,
                    1_000_000, time.time(), 195) for _ in range(5)]
    await db.insert_options_flow(hits)
    assert await db.get_flow_premium_baseline("AAPL") is None  # <10 rows -> None


async def test_premium_baseline_mean_at_10_rows(tmp_db):
    hits = [FlowHit("NVDA", "CALL", 200, "2026-06-20", 5000, 500, 10.0,
                    2_000_000, time.time(), 195) for _ in range(10)]
    await db.insert_options_flow(hits)
    baseline = await db.get_flow_premium_baseline("NVDA")
    assert baseline == pytest.approx(2_000_000.0)


async def test_premium_baseline_unknown_ticker_none(tmp_db):
    assert await db.get_flow_premium_baseline("ZZZZ") is None
