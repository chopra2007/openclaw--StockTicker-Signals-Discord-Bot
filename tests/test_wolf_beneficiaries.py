"""Tests for phase-4 #2 — Wolf beneficiary inference.

Covers: candidate-universe resolution (curated macro + derived sector + omit rules),
the v18 wolf_beneficiaries table round-trip + atomic replace, and the ranking contract:
the absolute RS floor omits weak buckets (no manufactured winners), pure-RS picks cap at
🟡, a bear-thesis long still rewards BULLISH RS (no sign-flip), >60% RS failure raises,
and run_cycle skips single-stock theses (isolation).
"""
import json
import tempfile
import types

import pytest

from consensus_engine import db
from consensus_engine.alerts import wolf_news
from consensus_engine.analysis import wolf_beneficiaries as wb


def _digest_payload(beneficiaries):
    return {"variant": "midday", "generated_at_pt": "x", "lean": "l", "regime_clause": "r",
            "acting": [], "imminent": [], "watchlist": [], "scoreboard": [],
            "beneficiaries": beneficiaries}


def test_digest_renders_beneficiaries_section():
    payload = _digest_payload([{"scope_key": "OIL", "direction": "bull", "scope_type": "asset",
        "picks": [{"ticker": "XOM", "side": "long", "tier": "green", "reason": "leads peers, bullish flow"},
                  {"ticker": "CVX", "side": "long", "tier": "yellow", "reason": "leads peers; unconfirmed"}]}])
    embed = wolf_news.format_digest("midday", payload)
    benf = [f for f in embed["fields"] if "Bot's read" in f["name"]]
    assert benf, "beneficiaries field should render"
    val = benf[0]["value"]
    assert "inferred, not Wolf's picks" in benf[0]["name"]
    assert "OIL bull" in val and "🟢 XOM" in val and "🟡 CVX" in val


def test_digest_omits_empty_beneficiaries():
    embed = wolf_news.format_digest("midday", _digest_payload([]))
    assert not any("Bot's read" in f["name"] for f in embed["fields"])


@pytest.fixture
async def fresh_db():
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield db
    await db.close_db()
    db._db = None
    db.DB_PATH = None


def _rs(delta, mode="peers"):
    async def fake(ticker, window_days=None):
        d = delta(ticker) if callable(delta) else delta
        return None if d is None else {"delta": d, "mode": mode}
    return fake


def _no_catalyst():
    async def fake(ticker):
        return None
    return fake


def _no_flow():
    async def fake(ticker, days=7):
        return []
    return fake


# ───────────────────────── universe resolution ─────────────────────────
def test_resolve_universe_rules():
    assert wb.resolve_candidate_universe("asset", "OIL", "bull")[:2] == ["XOM", "CVX"]
    assert wb.resolve_candidate_universe("market", "SPX", "bear")[:1] == ["WMT"]
    assert wb.resolve_candidate_universe("market", "SPX", "bull") == []   # no bull bucket → omit
    assert "MSFT" in wb.resolve_candidate_universe("sector", "IGV", "bull")  # derived from peer_groups
    assert wb.resolve_candidate_universe("sector", "SMH", "bear") == []   # bear sector → omit (no long; longs-only v1)
    assert wb.resolve_candidate_universe("stock", "NVDA", "bull") == []   # single-stock → omit
    assert wb.resolve_candidate_universe("asset", "ZZZ", "bull") == []    # unmapped → omit


# ───────────────────────── table round-trip ─────────────────────────
async def test_v18_table_and_atomic_replace(fresh_db):
    tid = await db.insert_thesis("asset", "OIL", "bull", "acting", "[]", None, 0, "[]", 1.0)
    rows = [{"ticker": "XOM", "side": "long", "scope_type": "asset", "scope_key": "OIL",
             "direction": "bull", "score": 0.8, "confidence": 0.7, "tier": "green",
             "reason": "leads peers", "signals_json": "{}", "computed_at": 100.0}]
    await db.replace_beneficiaries(tid, rows)
    got = await db.get_beneficiaries(tid)
    assert len(got) == 1 and got[0]["ticker"] == "XOM"
    # replace fully swaps the set
    await db.replace_beneficiaries(tid, [{**rows[0], "ticker": "CVX"}])
    got = await db.get_beneficiaries(tid)
    assert [r["ticker"] for r in got] == ["CVX"]
    # empty clears
    await db.replace_beneficiaries(tid, [])
    assert await db.get_beneficiaries(tid) == []


# ───────────────────────── ranking contract ─────────────────────────
async def test_floor_omits_weak_bucket(fresh_db, monkeypatch):
    """Every candidate below the absolute RS floor => no picks (no manufactured winner)."""
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(0.1))   # < 0.5 floor
    monkeypatch.setattr(wb, "news_cascade", _no_catalyst())
    monkeypatch.setattr(db, "get_options_flow_for_ticker", _no_flow())
    th = {"id": 1, "scope_type": "asset", "scope_key": "OIL", "direction": "bull"}
    assert await wb.rank_beneficiaries(th) == []


async def test_pure_rs_caps_yellow(fresh_db, monkeypatch):
    """A candidate with only the RS signal can never be 🟢; reason is honest."""
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(3.0))
    monkeypatch.setattr(wb, "news_cascade", _no_catalyst())
    monkeypatch.setattr(db, "get_options_flow_for_ticker", _no_flow())
    th = {"id": 1, "scope_type": "asset", "scope_key": "OIL", "direction": "bull"}
    rows = await wb.rank_beneficiaries(th)
    assert rows and all(r["tier"] == "yellow" for r in rows)
    assert all("unconfirmed" in r["reason"] for r in rows)


async def test_no_sign_flip_bear_thesis_rewards_bullish_rs(fresh_db, monkeypatch):
    """OIL/bear → airlines long. The LEADING airline (high +RS) ranks top — RS is NOT
    inverted by the bear thesis direction (Codex C1)."""
    deltas = {"DAL": 3.0, "UAL": 2.0, "AAL": 0.2, "LUV": -1.0}  # AAL/LUV below floor
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(lambda t: deltas.get(t)))
    monkeypatch.setattr(wb, "news_cascade", _no_catalyst())
    monkeypatch.setattr(db, "get_options_flow_for_ticker", _no_flow())
    th = {"id": 1, "scope_type": "asset", "scope_key": "OIL", "direction": "bear"}
    rows = await wb.rank_beneficiaries(th)
    tickers = {r["ticker"] for r in rows}
    assert rows[0]["ticker"] == "DAL"                  # the leader ranks top (RS not inverted)
    assert "AAL" not in tickers and "LUV" not in tickers   # below the RS floor → dropped
    # (UAL is the weaker of the two eligible names; with no confirmation its rank_score
    # lands below conf_floor and it is correctly dropped — thin buckets surface few names.)


async def test_confirmation_lifts_to_green(fresh_db, monkeypatch):
    """RS + aligned bullish catalyst + bullish flow => 🟢 (≥2 signals, conf≥0.65)."""
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(3.0))

    async def cat(ticker):
        return types.SimpleNamespace(catalyst_type="Earnings Beat")
    async def flow(ticker, days=7):
        return [{"side": "CALL", "premium_usd": 1_000_000}]
    monkeypatch.setattr(wb, "news_cascade", cat)
    monkeypatch.setattr(db, "get_options_flow_for_ticker", flow)
    th = {"id": 1, "scope_type": "asset", "scope_key": "OIL", "direction": "bull"}
    rows = await wb.rank_beneficiaries(th)
    assert rows[0]["tier"] == "green"
    sig = json.loads(rows[0]["signals_json"])
    assert sig["catalyst"] == "Earnings Beat" and sig["flow_bullish"] is True


async def test_mass_rs_failure_raises(fresh_db, monkeypatch):
    """>60% of candidates failing RS raises so the caller keeps prior rows."""
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(None))  # all fail
    monkeypatch.setattr(wb, "news_cascade", _no_catalyst())
    monkeypatch.setattr(db, "get_options_flow_for_ticker", _no_flow())
    th = {"id": 1, "scope_type": "asset", "scope_key": "OIL", "direction": "bull"}
    with pytest.raises(wb.BeneficiaryComputeError):
        await wb.rank_beneficiaries(th)


async def test_run_cycle_skips_stock_writes_macro(fresh_db, monkeypatch):
    """run_cycle writes beneficiaries for a macro thesis and skips a single-stock one."""
    monkeypatch.setattr(wb, "compute_relative_strength", _rs(3.0))
    monkeypatch.setattr(wb, "news_cascade", _no_catalyst())
    monkeypatch.setattr(db, "get_options_flow_for_ticker", _no_flow())
    macro = await db.insert_thesis("asset", "OIL", "bull", "acting", "[]", None, 0, "[]", 1.0)
    stock = await db.insert_thesis("stock", "NVDA", "bull", "acting", "[]", None, 0, "[]", 1.0)
    n = await wb.run_cycle()
    assert n == 1
    assert await db.get_beneficiaries(macro)            # macro got rows
    assert await db.get_beneficiaries(stock) == []       # stock skipped
