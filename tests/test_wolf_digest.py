"""Tests for the Phase-3 digest scheduler + composer + outcome scorer.

Discord is mocked (wolf_news._send_news), yfinance is mocked (wolf_outcomes
._fetch_proxy_series). These exercise: the cross-midnight window contract, the
backfill-contamination guarantee (Codex BLOCKER-1), trigger staleness, honest
outcome scoring (Codex BLOCKER-2), dedup, Sunday-recap restart-safety, and quiet-day.
"""

import json
import sys
import tempfile
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.analysis import wolf_scope, wolf_outcomes
from consensus_engine.alerts import wolf_news, wolf_digest

PT = ZoneInfo("America/Los_Angeles")


# ============================================================ pure unit tests
def test_pt_window_anchor_cross_midnight_shares_date():
    a = datetime(2026, 6, 6, 19, 30, tzinfo=PT)   # Sat 7:30pm
    b = datetime(2026, 6, 7, 1, 30, tzinfo=PT)    # Sun 1:30am — same Wrap
    inA, dA = wolf_digest.pt_window_anchor(a, "19:00", "02:00")
    inB, dB = wolf_digest.pt_window_anchor(b, "19:00", "02:00")
    assert inA and inB
    assert dA == dB == date(2026, 6, 6)           # both anchor to the day it OPENED


def test_pt_window_anchor_outside_and_midday():
    assert wolf_digest.pt_window_anchor(datetime(2026, 6, 6, 15, 0, tzinfo=PT), "19:00", "02:00") == (False, None)
    inM, dM = wolf_digest.pt_window_anchor(datetime(2026, 6, 6, 12, 30, tzinfo=PT), "12:00", "13:05")
    assert inM and dM == date(2026, 6, 6)
    # just past the midday close
    assert wolf_digest.pt_window_anchor(datetime(2026, 6, 6, 13, 6, tzinfo=PT), "12:00", "13:05") == (False, None)


def test_pt_window_anchor_dst_transition():
    # US spring-forward 2026-03-08: 2am PST -> 3am PDT. Window math must not crash and
    # epoch conversion must stay sane (ZoneInfo handles the gap).
    d = date(2026, 3, 8)
    inW, anchor = wolf_digest.pt_window_anchor(datetime(2026, 3, 8, 12, 30, tzinfo=PT), "12:00", "13:05")
    assert inW and anchor == d
    lo = wolf_digest._pt_epoch(d, "12:00")
    hi = wolf_digest._pt_epoch(d, "13:05")
    assert hi > lo and (hi - lo) == 65 * 60     # 65-minute window, DST gap is earlier in the day


def test_proxy_symbol_covers_scopes():
    assert wolf_scope.proxy_symbol("market", "SPX") == "SPY"
    assert wolf_scope.proxy_symbol("market", "NDX") == "QQQ"
    assert wolf_scope.proxy_symbol("asset", "OIL") == "USO"
    assert wolf_scope.proxy_symbol("asset", "BTC") == "BTC-USD"
    assert wolf_scope.proxy_symbol("sector", "XLE") == "XLE"
    assert wolf_scope.proxy_symbol("stock", "NVDA") == "NVDA"
    assert wolf_scope.proxy_symbol("asset", "NOTAMAP") is None     # -> inconclusive, never scored
    # index/macro aliases score even when the parser mis-scopes them as 'stock'
    assert wolf_scope.proxy_symbol("stock", "NAS100") == "QQQ"
    assert wolf_scope.proxy_symbol("stock", "TRANSPORTS") == "IYT"


def test_format_digest_caps_long_bucket_with_more():
    items = [{"scope_key": f"T{i}", "direction": "bull", "stage": "imminent"} for i in range(11)]
    payload = {"variant": "midday", "imminent": items, "acting": [], "watchlist": [], "scoreboard": []}
    e = wolf_news.format_digest("midday", payload)
    imm = [f for f in e["fields"] if f["name"].startswith("⏳")][0]["value"]
    assert "…and 3 more" in imm        # 11 - 8 cap = 3 hidden
    assert "T7" in imm and "T8" not in imm   # first 8 shown, rest hidden


# ============================================================ DB-backed fixture
@pytest.fixture
async def digest_env(monkeypatch):
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()

    sent = []

    async def fake_send(content=None, embed=None, ping_user_id=None):
        sent.append({"content": content, "embed": embed})
        return "fake_msg_id"

    monkeypatch.setattr(wolf_news, "_send_news", fake_send)
    yield sent
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def _seed_email(msg_id, received_at):
    await db.record_wolf_email(msg_id, "h", "i", "ok", None, 1, received_at + 0.5,
                               received_at=received_at)


async def _seed_thesis(scope_type, scope_key, direction, stage, anchor_ts=None, status="active"):
    evlog = [{"ts": anchor_ts or 1000.0, "to": stage}]
    tid = await db.insert_thesis(scope_type, scope_key, direction, stage, "[]", None, 0,
                                 json.dumps(evlog), anchor_ts or 1000.0)
    if status == "invalidated":
        await db.invalidate_thesis(tid, (anchor_ts or 1000.0) + 100)
    return tid


# ============================================================ scheduler tests
async def test_backfill_contamination_no_fire(digest_env):
    """Codex BLOCKER-1: 76 backfilled emails with OLD received_at trigger NOTHING."""
    # simulate backfill rows: received weeks ago
    old_base = datetime(2026, 4, 30, 12, 0, tzinfo=PT).timestamp()
    for i in range(76):
        await _seed_email(f"bf{i}", old_base + i * 3600)
    await _seed_thesis("stock", "NVDA", "bull", "acting", anchor_ts=old_base)

    # now = a midday window TODAY — backfill rows are way out of window
    now_pt = datetime(2026, 6, 1, 12, 30, tzinfo=PT)
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert digest_env == []                                    # nothing sent
    assert await db.get_wolf_alert(f"digest|midday|{now_pt.date()}") is None


async def test_fresh_email_fires_midday(digest_env):
    now_pt = datetime(2026, 6, 1, 12, 30, tzinfo=PT)
    await _seed_email("fresh1", datetime(2026, 6, 1, 12, 1, tzinfo=PT).timestamp())
    await _seed_thesis("stock", "NVDA", "bull", "acting", anchor_ts=now_pt.timestamp() - 100)
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert len(digest_env) == 1
    assert await db.get_wolf_alert(f"digest|midday|{now_pt.date()}") is not None


async def test_dedup_second_tick_no_double_post(digest_env):
    now_pt = datetime(2026, 6, 1, 12, 30, tzinfo=PT)
    await _seed_email("fresh1", datetime(2026, 6, 1, 12, 1, tzinfo=PT).timestamp())
    await _seed_thesis("stock", "NVDA", "bull", "acting")
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())  # poll again
    assert len(digest_env) == 1                               # dedupe_key blocked the 2nd


async def test_mid_window_restart_still_fires(digest_env):
    """Codex MINOR-1 fix: a restart 2h into the 7h nightly window must STILL post the
    Wrap — the old 90-min grace bound would have silently eaten it."""
    now_pt = datetime(2026, 6, 3, 21, 30, tzinfo=PT)          # Wed, 2.5h into nightly window
    await _seed_email("wrap1", datetime(2026, 6, 3, 19, 5, tzinfo=PT).timestamp())
    await _seed_thesis("market", "SPX", "bear", "imminent")
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert len(digest_env) == 1
    assert await db.get_wolf_alert(f"digest|nightly|{date(2026,6,3)}") is not None


async def test_email_before_window_open_no_fire(digest_env):
    """An email received BEFORE the window opened is not this window's trigger."""
    now_pt = datetime(2026, 6, 3, 19, 30, tzinfo=PT)          # Wed, nightly window open
    await _seed_email("early", datetime(2026, 6, 3, 18, 0, tzinfo=PT).timestamp())  # 18:00 < 19:00
    await _seed_thesis("market", "SPX", "bear", "imminent")
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert digest_env == []


async def test_retry_after_failed_send(digest_env, monkeypatch):
    """Codex MAJOR-1: a failed Discord send is retried on a later tick, not dropped forever."""
    now_pt = datetime(2026, 6, 1, 12, 30, tzinfo=PT)          # Mon midday
    await _seed_email("fresh1", datetime(2026, 6, 1, 12, 1, tzinfo=PT).timestamp())
    await _seed_thesis("stock", "NVDA", "bull", "acting")

    fail = [True]

    async def maybe_fail(content=None, embed=None, ping_user_id=None):
        if fail[0]:
            return None
        digest_env.append({"embed": embed})
        return "ok_id"

    monkeypatch.setattr(wolf_news, "_send_news", maybe_fail)
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    row = await db.get_wolf_alert(f"digest|midday|{now_pt.date()}")
    assert row is not None and row["status"] == "failed"      # failed, NOT posted
    assert digest_env == []

    fail[0] = False                                            # Discord recovers
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    row = await db.get_wolf_alert(f"digest|midday|{now_pt.date()}")
    assert row["status"] == "posted"
    assert len(digest_env) == 1                                # posted exactly once on retry


async def test_failed_recap_retries_not_addon(digest_env, monkeypatch):
    """Codex MAJOR-2: a failed Sunday recap is RETRIED as a recap, never mis-branched
    into the add-on path just because a (failed) row exists."""
    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series",
                        lambda s, a: {"anchor_close": 100.0, "latest_close": 105.0, "band_pct": 1.0})
    sunday = datetime(2026, 6, 7, 10, 30, tzinfo=PT)
    await _seed_email("wk1", datetime(2026, 6, 5, 12, 0, tzinfo=PT).timestamp())
    await _seed_thesis("stock", "NVDA", "bull", "acting", anchor_ts=sunday.timestamp() - 86400)

    fail = [True]

    async def maybe_fail(content=None, embed=None, ping_user_id=None):
        if fail[0]:
            return None
        digest_env.append({"embed": embed})
        return "ok"

    monkeypatch.setattr(wolf_news, "_send_news", maybe_fail)
    await wolf_digest._digest_tick(now_pt=sunday, now_epoch=sunday.timestamp())
    row = await db.get_wolf_alert(f"digest|sunday|{date(2026,6,7)}")
    assert row is not None and row["status"] == "failed"
    assert await db.get_wolf_alert(f"digest|sunday-addon|{date(2026,6,7)}") is None   # NOT mis-branched
    assert await wolf_digest.recap_fired_today(date(2026, 6, 7)) is False

    fail[0] = False                                            # Discord recovers
    await wolf_digest._digest_tick(now_pt=sunday, now_epoch=sunday.timestamp())
    row = await db.get_wolf_alert(f"digest|sunday|{date(2026,6,7)}")
    assert row["status"] == "posted"
    assert await db.get_wolf_alert(f"digest|sunday-addon|{date(2026,6,7)}") is None
    assert len(digest_env) == 1


async def test_nightly_fires_when_fresh(digest_env):
    # Wednesday (NOT a Sunday) so only the nightly variant can fire
    now_pt = datetime(2026, 6, 3, 19, 30, tzinfo=PT)
    await _seed_email("wrap1", datetime(2026, 6, 3, 19, 5, tzinfo=PT).timestamp())
    await _seed_thesis("market", "SPX", "bear", "imminent")
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert len(digest_env) == 1
    assert await db.get_wolf_alert(f"digest|nightly|{date(2026,6,3)}") is not None


async def test_quiet_day_no_digest(digest_env):
    # active thesis exists but NO email arrived in any window today
    await _seed_thesis("stock", "NVDA", "bull", "acting")
    now_pt = datetime(2026, 6, 1, 12, 30, tzinfo=PT)
    await wolf_digest._digest_tick(now_pt=now_pt, now_epoch=now_pt.timestamp())
    assert digest_env == []


async def test_sunday_recap_and_addon_restart_safe(digest_env):
    """Sunday >=10am with week activity -> recap. recap_fired_today reads the persistent
    outbox (survives 'restart'). A later Sunday email -> a single add-on."""
    sunday = datetime(2026, 6, 7, 10, 30, tzinfo=PT)          # 2026-06-07 is a Sunday
    await _seed_email("wk1", datetime(2026, 6, 5, 12, 0, tzinfo=PT).timestamp())  # within last 7d
    await _seed_thesis("stock", "NVDA", "bull", "acting", anchor_ts=sunday.timestamp() - 86400)

    await wolf_digest._digest_tick(now_pt=sunday, now_epoch=sunday.timestamp())
    assert await db.get_wolf_alert(f"digest|sunday|{date(2026,6,7)}") is not None
    n_after_recap = len(digest_env)

    # simulate a restart: nothing in-memory; recap_fired_today must still be True
    assert await wolf_digest.recap_fired_today(date(2026, 6, 7)) is True
    # a fresh Sunday email lands AFTER the recap -> add-on fires once
    await _seed_email("sun_late", datetime(2026, 6, 7, 11, 0, tzinfo=PT).timestamp())
    later = datetime(2026, 6, 7, 11, 5, tzinfo=PT)
    await wolf_digest._digest_tick(now_pt=later, now_epoch=later.timestamp())
    await wolf_digest._digest_tick(now_pt=later, now_epoch=later.timestamp())  # dedup add-on
    assert await db.get_wolf_alert(f"digest|sunday-addon|{date(2026,6,7)}") is not None
    assert len(digest_env) == n_after_recap + 1               # exactly one add-on


# ============================================================ outcome scorer
async def test_outcomes_only_score_actionable(digest_env, monkeypatch):
    """Forming-only thesis is NOT scored; actionable one IS; unmapped -> inconclusive."""
    def fake_series(symbol, anchor_ts):
        # NVDA rose, USO (bear OIL) rose too (=against)
        return {"NVDA": {"anchor_close": 100.0, "latest_close": 110.0, "band_pct": 1.0},
                "USO":  {"anchor_close": 50.0,  "latest_close": 55.0,  "band_pct": 1.0}}.get(symbol, {})

    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)

    now = datetime(2026, 6, 7, 10, 0, tzinfo=PT).timestamp()
    await _seed_thesis("stock", "NVDA", "bull", "acting", anchor_ts=now - 3 * 86400)
    await _seed_thesis("asset", "OIL", "bear", "imminent", anchor_ts=now - 3 * 86400)
    await _seed_thesis("stock", "TSLA", "bull", "forming", anchor_ts=now - 3 * 86400)   # never actionable
    await _seed_thesis("asset", "NOTAMAP", "bull", "acting", anchor_ts=now - 3 * 86400)  # no proxy

    outs = await wolf_outcomes.compute_outcomes(lookback_days=7)
    by_key = {o["scope_key"]: o for o in outs}
    assert "TSLA" not in by_key                               # forming -> not scored
    assert by_key["NVDA"]["state"] == "moved_with"            # +10% bull
    assert by_key["OIL"]["state"] == "moved_against"          # USO +10% but Wolf is bear
    assert by_key["NOTAMAP"]["state"] == "inconclusive"       # unmapped, never a false win
    # persisted
    rows = await db.get_call_outcomes()
    assert {r["scope_key"] for r in rows} == {"NVDA", "OIL", "NOTAMAP"}


async def test_outcome_flat_within_band(digest_env, monkeypatch):
    def fake_series(symbol, anchor_ts):
        return {"anchor_close": 100.0, "latest_close": 100.3, "band_pct": 1.0}  # +0.3% < band(0.5..1)
    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=PT).timestamp()
    await _seed_thesis("stock", "AAPL", "bull", "acting", anchor_ts=now - 86400)
    outs = await wolf_outcomes.compute_outcomes()
    assert outs[0]["state"] == "flat"


async def test_outcome_invalidated_state(digest_env, monkeypatch):
    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series",
                        lambda s, a: {"anchor_close": 100.0, "latest_close": 130.0, "band_pct": 1.0})
    now = datetime(2026, 6, 7, 10, 0, tzinfo=PT).timestamp()
    await _seed_thesis("stock", "META", "bull", "acting", anchor_ts=now - 86400, status="invalidated")
    outs = await wolf_outcomes.compute_outcomes()
    # even though price rose, an abandoned call is reported as invalidated (not a fake win)
    assert outs[0]["state"] == "invalidated"
