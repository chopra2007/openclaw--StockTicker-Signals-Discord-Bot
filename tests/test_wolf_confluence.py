"""Tests for the Wolf macro-brain phase-2 cross-source confluence (TODO #20, Type-2).

Covers the pure scoring logic (normalize / scope-match / net-vote / tier / combine),
the embed field, the DB gather+upsert+prune, and an end-to-end cycle incl. hysteresis
and the no-pollution guarantee.
"""
import json
import tempfile
import time

import pytest

from consensus_engine import db, main
from consensus_engine.analysis import wolf_confluence as wc
from consensus_engine.alerts import wolf_news


# ───────────────────────── normalize_source_stance ─────────────────────────

@pytest.mark.parametrize("ticker,raw,expected", [
    ("NVDA", "long", ("stock", "NVDA", "BULL")),
    ("NVDA", "short", ("stock", "NVDA", "BEAR")),
    ("NVDA", "CALL", ("stock", "NVDA", "BULL")),
    ("NVDA", "PUT", ("stock", "NVDA", "BEAR")),
    ("AAPL", "bullish", ("stock", "AAPL", "BULL")),
    ("AAPL", "buy", ("stock", "AAPL", "BULL")),
    ("AAPL", "sell", ("stock", "AAPL", "BEAR")),
    ("QQQ", "long", ("market", "NDX", "BULL")),
    ("USO", "short", ("asset", "OIL", "BEAR")),
    # inverse ETFs flip: long the inverse = bearish the base
    ("SOXS", "long", ("sector", "SMH", "BEAR")),
    ("SQQQ", "long", ("market", "NDX", "BEAR")),
    ("SOXL", "long", ("sector", "SMH", "BULL")),  # leveraged-LONG, not inverse → no flip
])
def test_normalize_source_stance(ticker, raw, expected):
    assert wc.normalize_source_stance(ticker, raw) == expected


@pytest.mark.parametrize("ticker,raw", [
    ("NVDA", "neutral"), ("NVDA", ""), ("NVDA", "hold"),
    ("VIX", "long"), ("UVXY", "short"), ("VXX", "long"), ("SVXY", "put"),
])
def test_normalize_skips(ticker, raw):
    assert wc.normalize_source_stance(ticker, raw) is None


# ───────────────────────── scope_matches ─────────────────────────

def test_scope_match_stock():
    assert wc.scope_matches("stock", "NVDA", "stock", "NVDA", "NVDA")
    assert not wc.scope_matches("stock", "NVDA", "stock", "MU", "MU")


def test_scope_match_market():
    # QQQ resolves to ('market','NDX') → matches an NDX thesis
    assert wc.scope_matches("market", "NDX", "market", "NDX", "QQQ")
    assert not wc.scope_matches("market", "SPX", "market", "NDX", "QQQ")


def test_scope_match_asset_no_two_hop():
    assert wc.scope_matches("asset", "OIL", "asset", "OIL", "USO")
    # XOM is a stock(XLE), NOT an oil proxy → must NOT match an OIL asset thesis
    assert not wc.scope_matches("asset", "OIL", "stock", "XOM", "XOM")


def test_scope_match_sector_broad_spdr_uses_sector_map():
    # NVDA → XLK via sector_map → matches an XLK (broad SPDR) thesis
    assert wc.scope_matches("sector", "XLK", "stock", "NVDA", "NVDA")
    # a non-XLK stock does not
    assert not wc.scope_matches("sector", "XLK", "stock", "XOM", "XOM")


def test_scope_match_sector_subindustry_uses_peer_groups():
    # NVDA is in the Semiconductors peer group → matches an SMH thesis
    assert wc.scope_matches("sector", "SMH", "stock", "NVDA", "NVDA")
    # direct semis ETF also matches (SOXX resolves to sector SMH)
    assert wc.scope_matches("sector", "SMH", "sector", "SMH", "SOXX")


def test_scope_no_double_count_across_buckets():
    """NVDA legitimately votes on BOTH an XLK thesis and an SMH thesis (different theses),
    but within EACH it matches via exactly one map — never twice in one thesis."""
    assert wc.scope_matches("sector", "XLK", "stock", "NVDA", "NVDA")   # via sector_map
    assert wc.scope_matches("sector", "SMH", "stock", "NVDA", "NVDA")   # via peer_groups
    # MU maps to XLK in sector_map; it must NOT match XLK only because peer_groups put it in SMH
    assert wc.scope_matches("sector", "XLK", "stock", "MU", "MU")


# ───────────────────────── net_vote ─────────────────────────

def test_net_vote():
    assert wc.net_vote(["BULL", "BULL", "BULL"]) == "BULL"
    assert wc.net_vote(["BEAR", "BEAR"]) == "BEAR"
    assert wc.net_vote([]) is None
    # 60/40 exactly → dominant side wins at the boundary
    assert wc.net_vote(["BULL", "BULL", "BULL", "BEAR", "BEAR"], 0.6) == "BULL"  # 3/5=0.6
    # 50/50 → too split → None
    assert wc.net_vote(["BULL", "BEAR"]) is None
    # 4 bull / 3 bear = 0.571 < 0.6 → None
    assert wc.net_vote(["BULL"] * 4 + ["BEAR"] * 3, 0.6) is None


# ───────────────────────── score_confluence + tiers ─────────────────────────

def _thesis(scope_type="stock", scope_key="NVDA", direction="bull", has_levels=1):
    return {"scope_type": scope_type, "scope_key": scope_key,
            "direction": direction, "has_levels": has_levels}


def test_score_surface_when_alone():
    r = wc.score_confluence(_thesis(), {})
    assert r.tier == "surface" and r.agree_count == 0


def test_score_high_one_agree():
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.tier == "high" and r.agree_count == 1


def test_score_critical_two_agree():
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}],
            "youtube": [{"ticker": "NVDA", "dir": "long", "channel": "TA Guy"}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.tier == "critical" and r.agree_count == 2


def test_score_levelless_capped_to_surface():
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}],
            "youtube": [{"ticker": "NVDA", "dir": "long", "channel": "x"}]}
    r = wc.score_confluence(_thesis(has_levels=0), rows)
    assert r.tier == "surface" and r.agree_count == 2  # still counts, but no tier-up


def test_score_divided():
    # Wolf bear NVDA; two sources bull → divided, no tier-up
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}],
            "options": [{"ticker": "NVDA", "dir": "CALL"}]}
    r = wc.score_confluence(_thesis(direction="bear"), rows)
    assert r.divided and r.agree_count == 0 and r.disagree_count == 2


def test_score_mixed_source_no_vote():
    # twitter internally split 1/1 on NVDA → no net vote → no agree
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}, {"ticker": "NVDA", "dir": "short"}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 0 and r.tier == "surface"


def test_youtube_channel_count():
    rows = {"youtube": [
        {"ticker": "NVDA", "dir": "long", "channel": "A"},
        {"ticker": "NVDA", "dir": "long", "channel": "B"},
        {"ticker": "NVDA", "dir": "long", "channel": "A"},
    ]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree[0].n_channels == 2 and r.agree[0].n_rows == 3


def test_sec_bearish_does_not_help_a_bull_but_score_uses_given_rows():
    # score() trusts the gather to pass buys-only; if a bearish sec row is passed it is a BEAR
    # vote (disagree on a bull thesis), never a free bull agree.
    rows = {"sec": [{"ticker": "NVDA", "dir": "bearish"}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 0 and r.disagree_count == 1


def test_divided_caps_critical_to_high():
    # 2 agree + 2 disagree (4 sources) → divided → must NOT reach critical/@-ping.
    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}],
            "youtube": [{"ticker": "NVDA", "dir": "long", "channel": "a"}],
            "options": [{"ticker": "NVDA", "dir": "PUT"}],
            "sec": [{"ticker": "NVDA", "dir": "bearish"}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 2 and r.disagree_count == 2 and r.divided
    assert r.tier == "high"   # capped down from critical


def test_combined_tier_only_up():
    assert wc.combined_tier("surface", "critical") == "critical"
    assert wc.combined_tier("high", "surface") == "high"
    assert wc.combined_tier("high", "critical") == "critical"
    assert wc.combined_tier("surface", "surface") == "surface"


# ───────────────────────── embed field ─────────────────────────

def test_confluence_field_none_when_empty():
    assert wolf_news._confluence_field(None) is None
    assert wolf_news._confluence_field({"agree_count": 0, "disagree_count": 0}) is None


def test_confluence_field_agree():
    row = {"agree_count": 2, "disagree_count": 0, "divided": 0, "direction": "bull",
           "agree_sources_json": json.dumps([
               {"source_type": "youtube", "net_dir": "BULL", "n_rows": 3, "n_channels": 2,
                "sample_tickers": ["NVDA"]},
               {"source_type": "options", "net_dir": "BULL", "n_rows": 1, "sample_tickers": ["NVDA"]}]),
           "disagree_sources_json": "[]"}
    f = wolf_news._confluence_field(row)
    assert "2 sources agree" in f["value"] and "YouTube (2 ch" in f["value"]


def test_confluence_field_divided():
    row = {"agree_count": 0, "disagree_count": 1, "divided": 1, "direction": "bear",
           "agree_sources_json": "[]",
           "disagree_sources_json": json.dumps([
               {"source_type": "twitter", "net_dir": "BULL", "n_rows": 5, "sample_tickers": ["NVDA"]}])}
    f = wolf_news._confluence_field(row)
    assert "divided" in f["value"].lower() and "Twitter" in f["value"]


# ───────────────────────── DB: gather / upsert / prune ─────────────────────────

@pytest.fixture
async def fresh_db():
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield db
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def _ins(table, cols, vals):
    conn = await db.get_db()
    ph = ",".join("?" * len(vals))
    await conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})", vals)
    await conn.commit()


async def test_gather_filters(fresh_db):
    now = time.time()
    old = now - 30 * 86400
    # twitter: one fresh long, one too-old
    await _ins("signal_events", ["source_type", "ticker", "direction", "recorded_at"],
               ["twitter", "NVDA", "long", now])
    await _ins("signal_events", ["source_type", "ticker", "direction", "recorded_at"],
               ["twitter", "OLD", "long", old])
    # youtube: fresh long (not suppressed) + a suppressed one
    await _ins("youtube_signals",
               ["video_id", "channel_name", "ticker", "direction", "conviction", "parsed_at", "extracted_at", "suppressed"],
               ["v1", "ChA", "NVDA", "long", "high", now, now, 0])
    await _ins("youtube_signals",
               ["video_id", "channel_name", "ticker", "direction", "conviction", "parsed_at", "extracted_at", "suppressed"],
               ["v2", "ChB", "SUP", "long", "high", now, now, 1])
    # options
    await _ins("options_flow", ["ticker", "side", "detected_at"], ["NVDA", "CALL", now])
    # SEC: a buy (kept) + a sell (dropped by buys-only filter)
    await _ins("ticker_signals", ["ticker", "source_type", "sentiment", "detected_at", "expires_at"],
               ["NVDA", "sec_filing", "bullish", now, now + 7200])
    await _ins("ticker_signals", ["ticker", "source_type", "sentiment", "detected_at", "expires_at"],
               ["AMZN", "sec_filing", "bearish", now, now + 7200])

    g = await db.get_confluence_stances(window_days=21)
    assert [r["ticker"] for r in g["twitter"]] == ["NVDA"]           # old dropped
    assert [r["ticker"] for r in g["youtube"]] == ["NVDA"]           # suppressed dropped
    assert g["youtube"][0]["channel"] == "ChA"
    assert [r["ticker"] for r in g["options"]] == ["NVDA"]
    assert [r["ticker"] for r in g["sec"]] == ["NVDA"]               # only the BUY
    assert all(r["dir"] == "bullish" for r in g["sec"])


async def test_confluence_upsert_one_row(fresh_db):
    for tier in ("surface", "high", "critical"):
        await db.record_confluence_check(7, "stock", "NVDA", "bull", time.time(), 21,
                                         1, 0, tier, tier, 0, "[]", "[]", "surface")
    row = await db.get_confluence_check(7)
    assert row["tier"] == "critical"  # last write wins (upsert, one row)
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) c FROM wolf_confluence_checks")
    assert (await cur.fetchone())["c"] == 1


async def test_prune_orphans(fresh_db):
    tid = await db.insert_thesis("stock", "NVDA", "bull", "forming", "[]", None, 1, "[]", time.time())
    await db.record_confluence_check(tid, "stock", "NVDA", "bull", time.time(), 21,
                                     0, 0, "surface", "surface", 0, "[]", "[]", "surface")
    await db.record_confluence_check(999, "stock", "DEAD", "bull", time.time(), 21,
                                     0, 0, "surface", "surface", 0, "[]", "[]", "surface")
    deleted = await db.prune_confluence_orphans()
    assert deleted == 1                                    # the orphan (999) gone
    assert await db.get_confluence_check(tid) is not None  # the live one kept
    assert await db.get_confluence_check(999) is None


# ───────────────────────── end-to-end cycle ─────────────────────────

def _dryrun_cfg(monkeypatch):
    """Make post_event dry-run + critical-ping off so the cycle never hits Discord."""
    real = wolf_news.cfg.get
    monkeypatch.setattr(wolf_news.cfg, "get",
                        lambda k, d=None: True if k == "wolf.dry_run" else
                        (False if k == "wolf.enable_critical_ping" else real(k, d)))


async def test_cycle_tier_up_then_hysteresis(fresh_db, monkeypatch):
    _dryrun_cfg(monkeypatch)
    now = time.time()
    tid = await db.insert_thesis("stock", "NVDA", "bull", "forming", '[{"price":100}]', None, 1, "[]", now)
    # two sources agree → critical
    await _ins("signal_events", ["source_type", "ticker", "direction", "recorded_at"],
               ["twitter", "NVDA", "long", now])
    await _ins("youtube_signals",
               ["video_id", "channel_name", "ticker", "direction", "conviction", "parsed_at", "extracted_at"],
               ["v1", "ChA", "NVDA", "long", "high", now, now])

    await main._run_confluence_cycle(window_days=21, min_dom=0.6)
    row = await db.get_confluence_check(tid)
    assert row["combined_tier"] == "critical" and row["agree_count"] == 2
    assert row["alerted_tier"] == "critical"   # we posted

    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) c FROM wolf_news_alerts WHERE status='posted'")
    assert (await cur.fetchone())["c"] == 1     # exactly one confluence alert

    # second cycle, nothing new → NO second alert (hysteresis)
    await main._run_confluence_cycle(window_days=21, min_dom=0.6)
    cur = await conn.execute("SELECT COUNT(*) c FROM wolf_news_alerts")
    assert (await cur.fetchone())["c"] == 1


async def test_cycle_no_pollution(fresh_db, monkeypatch):
    _dryrun_cfg(monkeypatch)
    now = time.time()
    await db.insert_thesis("stock", "NVDA", "bull", "acting", '[{"price":100}]', None, 1, "[]", now)
    await _ins("signal_events", ["source_type", "ticker", "direction", "recorded_at"],
               ["twitter", "NVDA", "long", now])
    conn = await db.get_db()
    before_se = (await (await conn.execute("SELECT COUNT(*) c FROM signal_events")).fetchone())["c"]
    before_ts = (await (await conn.execute("SELECT COUNT(*) c FROM ticker_signals")).fetchone())["c"]

    await main._run_confluence_cycle(window_days=21, min_dom=0.6)

    after_se = (await (await conn.execute("SELECT COUNT(*) c FROM signal_events")).fetchone())["c"]
    after_ts = (await (await conn.execute("SELECT COUNT(*) c FROM ticker_signals")).fetchone())["c"]
    assert after_se == before_se and after_ts == before_ts   # confluence never writes source tables
