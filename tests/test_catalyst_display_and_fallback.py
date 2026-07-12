"""Tests for the three #55/#20 leftover-gap fixes.

1. Display wiring: `!catalysts` renders the shadow catalyst scorecard with
   EB-shrunk ("adjusted") rates, and `!leaderboard` gains an adjusted 24h column.
2. Nightly-safe grader: content-only classification cache key (built-in hash()
   is salted per process and can never match across runs) and the LLM-outage
   guard (an unanswered call is retried, never cached as "no catalyst").
3. Dynamic benchmark fallback: a long-tail ticker resolves to its sector ETF via
   the shared Yahoo sector path instead of being skipped.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import db, config as cfg
from consensus_engine.analysis import benchmark_grading as bg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import grade_analyst_catalysts as gac  # noqa: E402


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test_catalyst.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# 2. Grader: stable cache key + outage guard
# ---------------------------------------------------------------------------

def test_class_key_is_stable_and_content_only():
    """The key must be derivable from content alone — never built-in hash()."""
    digest = hashlib.sha1("h|NVDA|buy the dip".encode()).hexdigest()[:16]
    key = gac._class_key("h", "NVDA", "buy the dip")
    assert key == f"h|NVDA|{digest}"
    assert gac._class_key("h", "NVDA", "other text") != key


async def test_llm_exception_is_not_cached(tmp_path, monkeypatch):
    import models.text_model as tm
    monkeypatch.setattr(gac, "CACHE_PATH", tmp_path / "cache.json")

    async def boom(text, handle):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(tm, "analyze_tweet", boom)

    posts = [{"handle": "h", "ticker": "NVDA", "raw_text": "CES catalyst"}]
    posts, calls, unanswered = await gac.classify(posts, cap=10)
    assert (calls, unanswered) == (1, 1)
    assert posts[0]["catalyst_horizon"] == "uncached"      # retried next run
    assert not (tmp_path / "cache.json").exists()          # poison never cached


async def test_unanswered_shell_vs_real_no_catalyst(tmp_path, monkeypatch):
    """Outage default (horizon none + empty summary) is retried; a genuine
    "no catalyst" reading (summary present) IS cached as none."""
    import models.text_model as tm
    monkeypatch.setattr(gac, "CACHE_PATH", tmp_path / "cache.json")

    shell = {"catalyst_horizon": "none", "catalyst_kind": "none",
             "catalyst_likelihood": 0.0, "direction": "neutral", "summary": ""}
    real = dict(shell, summary="pure chart commentary, no catalyst")
    payloads = iter([shell, real])

    async def fake(text, handle):
        return next(payloads)
    monkeypatch.setattr(tm, "analyze_tweet", fake)

    posts = [{"handle": "a", "ticker": "T1", "raw_text": "x"},
             {"handle": "b", "ticker": "T2", "raw_text": "y"}]
    posts, calls, unanswered = await gac.classify(posts, cap=10)
    assert (calls, unanswered) == (2, 1)
    assert posts[0]["catalyst_horizon"] == "uncached"
    assert posts[1]["catalyst_horizon"] == "none"
    blob = json.loads((tmp_path / "cache.json").read_text())
    assert len(blob) == 1                                  # only the real reading


# ---------------------------------------------------------------------------
# 3. Dynamic benchmark fallback
# ---------------------------------------------------------------------------

async def test_dynamic_fallback_uses_sector_etf(monkeypatch):
    import consensus_engine.analysis.peer_comparison as pc

    async def fake_resolve(t):
        assert t == "RKLB"
        return {"group": "Industrials", "peers": [], "benchmark_etf": "XLI",
                "source": "dynamic_etf"}
    monkeypatch.setattr(pc, "resolve_peers", fake_resolve)
    assert await bg.resolve_benchmark_dynamic("RKLB") == "XLI"


async def test_dynamic_resolver_short_circuits_on_curated(monkeypatch):
    import consensus_engine.analysis.peer_comparison as pc

    async def explode(t):
        raise AssertionError("network path must not run for curated tickers")
    monkeypatch.setattr(pc, "resolve_peers", explode)
    assert await bg.resolve_benchmark_dynamic("NVDA") == "SMH"


async def test_dynamic_resolver_still_skips_unknown(monkeypatch):
    import consensus_engine.analysis.peer_comparison as pc

    async def nothing(t):
        return {"group": None, "peers": [], "benchmark_etf": None, "source": "none"}
    monkeypatch.setattr(pc, "resolve_peers", nothing)
    assert await bg.resolve_benchmark_dynamic("ZZZZ") is None


async def test_dynamic_resolver_degrades_to_skip_on_error(monkeypatch):
    import consensus_engine.analysis.peer_comparison as pc

    async def boom(t):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(pc, "resolve_peers", boom)
    assert await bg.resolve_benchmark_dynamic("ZZZZ") is None


# ---------------------------------------------------------------------------
# 1. Display wiring
# ---------------------------------------------------------------------------

_CARD = {
    "analysts": [
        {"handle": "CheddarFlow", "n": 7, "wins": 2, "mean_bhar": -0.01},
        {"handle": "ripster47", "n": 4, "wins": 1, "mean_bhar": 0.02},
        {"handle": "EliteOptions2", "n": 4, "wins": 2, "mean_bhar": 0.01},
    ],
    "kinds": [{"kind": "options", "n": 14, "wins": 6, "mean_bhar": 0.0034}],
    "bets": {"open": 8, "partial": 6},
    "total_rows": 43,
    "open_short": 15,
    "last_graded_at": time.time(),
}


async def test_catalysts_command_renders_ratios_and_adjusted():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply",
               new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_catalyst_scorecard",
               new_callable=AsyncMock, return_value=_CARD), \
         patch("consensus_engine.db.eb_shrunk_precision",
               new_callable=AsyncMock, return_value=0.54):
        await route_command("catalysts", [], "chan1", "msg1")
        content = mock_send.call_args[0][2]
    assert "2 of 7" in content            # raw ratio always shown for thin samples
    assert "adjusted" in content          # eb_shrink wired
    assert "all calls: 54%" in content    # eb_shrunk_precision wired
    assert "options" in content and "6 of 14" in content
    assert "does not change alerts" in content


async def test_catalysts_command_empty_table():
    from consensus_engine.alerts.commands import route_command
    card = {"analysts": [], "kinds": [], "bets": {}, "total_rows": 0,
            "open_short": 0, "last_graded_at": 0.0}
    with patch("consensus_engine.alerts.commands.send_command_reply",
               new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_catalyst_scorecard",
               new_callable=AsyncMock, return_value=card):
        await route_command("catalysts", [], "chan1", "msg1")
        content = mock_send.call_args[0][2]
    assert "No catalyst-graded calls yet" in content


async def test_leaderboard_shows_adjusted_24h():
    from consensus_engine.alerts.commands import route_command
    stats = [
        {"analyst": "vet", "total_alerts": 40, "wins_1h": 20, "win_rate_1h": 50.0,
         "wins_24h": 22, "win_rate_24h": 55.0, "avg_pnl_1h": 0.2},
        {"analyst": "newbie", "total_alerts": 5, "wins_1h": 3, "win_rate_1h": 60.0,
         "wins_24h": 3, "win_rate_24h": 60.0, "avg_pnl_1h": 0.5},
    ]
    with patch("consensus_engine.alerts.commands.send_command_reply",
               new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_analyst_performance_stats",
               new_callable=AsyncMock, return_value=stats):
        await route_command("leaderboard", [], "chan1", "msg1")
        content = mock_send.call_args[0][2]
    assert "adj 24h:" in content
    newbie_line = next(l for l in content.splitlines() if "newbie" in l)
    adj = int(re.search(r"adj 24h: (\d+)%", newbie_line).group(1))
    assert adj < 60        # 3-of-5 no longer reads as a flat 60%
    assert "5 alerts" in newbie_line and "24h: 60%" in newbie_line


async def test_get_catalyst_scorecard_aggregates(test_db):
    """Real-db shape check: grouped counts, NULL-win rows counted as open."""
    conn = test_db
    rows = [
        # (tweet_url, ticker, handle, direction, kind, etf, entry, win, graded_at)
        ("u1", "NVDA", "alpha", "long", "options", "SMH", "2026-06-01", 1),
        ("u2", "AMD", "alpha", "long", "options", "SMH", "2026-06-02", 0),
        ("u3", "MSFT", "beta", "short", "M&A", "IGV", "2026-06-03", 1),
        ("u4", "META", "beta", "long", "options", "XLC", "2026-07-10", None),  # window open
    ]
    for url, tk, h, d, kind, etf, entry, win in rows:
        await conn.execute(
            "INSERT INTO analyst_catalyst_scores (tweet_url, ticker, handle, direction,"
            " catalyst_kind, benchmark_etf, entry_date, bhar_21d, win, bonus, graded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (url, tk, h, d, kind, etf, entry, 0.01, win, 0.0, time.time()))
    await conn.execute(
        "INSERT INTO long_term_catalyst_bets (tweet_url, handle, ticker, direction,"
        " catalyst_kind, likelihood, benchmark_etf, entry_date, opened_at,"
        " checkpoint_status, last_checked) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("u5", "alpha", "AAPL", "long", "moat", 0.8, "XLK", "2026-06-01",
         time.time(), "open", time.time()))
    await conn.commit()

    card = await db.get_catalyst_scorecard()
    assert card["total_rows"] == 4
    assert card["open_short"] == 1
    by_handle = {a["handle"]: a for a in card["analysts"]}
    assert by_handle["alpha"]["n"] == 2 and by_handle["alpha"]["wins"] == 1
    by_kind = {k["kind"]: k for k in card["kinds"]}
    assert by_kind["options"]["n"] == 2                    # NULL-win row excluded
    assert card["bets"] == {"open": 1}
    assert card["last_graded_at"] > 0
