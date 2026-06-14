"""Tests for the Wolf thesis staleness sweep (TODO #26).

Covers: the real-reaffirmation clock (ignores weak mentions), stage-split age caps,
polarity-normalized contradiction, demote-not-delete to 'stale_review', the ingest
revival rule (explicit reaffirmation only), and dry-run safety.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.analysis import wolf_staleness as ws
from consensus_engine.analysis import wolf_theses

DAY = 86400.0


@pytest.fixture
async def stale_env():
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def _mk(scope_type, scope_key, direction, stage, evlog, created_at):
    return await db.insert_thesis(scope_type, scope_key, direction, stage, "[]", None, 0,
                                  json.dumps(evlog), created_at)


# ---------------------------------------------------------------- pure unit
def test_real_reaffirm_clock_ignores_weak_mentions():
    now = 1_000_000.0
    evlog = [
        {"ts": now - 40 * DAY, "to": "acting", "intent": "started"},   # real reaffirm
        {"ts": now - 5 * DAY, "to": "forming", "intent": "watching"},  # weak — must NOT reset
        {"ts": now - 2 * DAY, "to": "forming", "intent": "none"},      # weak — must NOT reset
    ]
    ts = ws._real_reaffirm_ts(evlog, now - 60 * DAY)
    assert ts == now - 40 * DAY  # the last EXPLICIT reaffirmation, not the recent weak ones


def test_real_reaffirm_clock_falls_back_to_first_ts():
    now = 1_000_000.0
    evlog = [{"ts": now - 12 * DAY, "to": "forming", "intent": "watching"}]
    assert ws._real_reaffirm_ts(evlog, now - 99 * DAY) == now - 12 * DAY  # earliest evidence ts


def test_polarity_normalization_vix_vs_uvxy():
    # VIX bear (vol down = market up) and UVXY bull (vol up = market down) are OPPOSITE
    # market views -> opposite normalized signs despite both being long-ish words.
    vix = ws._normalized_dirs("VIX", "bear")["volatility"]
    uvxy = ws._normalized_dirs("UVXY", "bull")["volatility"]
    assert vix == -uvxy and vix != 0


# ---------------------------------------------------------------- sweep behaviour
async def test_age_cap_demotes_stale_forming(stale_env):
    now = time.time()
    tid = await _mk("sector", "KWEB", "bull", "forming",
                    [{"ts": now - 31 * DAY, "to": "forming"}], now - 31 * DAY)
    summary = await ws.run_staleness_sweep(now=now)
    assert any(d["id"] == tid for d in summary["demoted"])
    # demote-not-delete: row preserved, status flipped, dropped from active
    assert await db.get_active_thesis("sector", "KWEB", "bull") is None
    stale = await db.get_stale_review_thesis("sector", "KWEB", "bull")
    assert stale is not None and stale["status"] == "stale_review"


async def test_imminent_has_shorter_cap_than_forming(stale_env):
    now = time.time()
    # 20 days: past the 18d imminent cap, but under the 30d forming cap
    imm = await _mk("asset", "OIL", "bear", "imminent",
                    [{"ts": now - 20 * DAY, "to": "imminent"}], now - 20 * DAY)
    frm = await _mk("asset", "GOLD", "bull", "forming",
                    [{"ts": now - 20 * DAY, "to": "forming"}], now - 20 * DAY)
    summary = await ws.run_staleness_sweep(now=now)
    ids = {d["id"] for d in summary["demoted"]}
    assert imm in ids        # imminent aged out at 18d
    assert frm not in ids     # forming still within 30d


async def test_fresh_thesis_not_demoted(stale_env):
    now = time.time()
    tid = await _mk("market", "SPX", "bull", "forming",
                    [{"ts": now - 2 * DAY, "to": "forming"}], now - 2 * DAY)
    summary = await ws.run_staleness_sweep(now=now)
    assert all(d["id"] != tid for d in summary["demoted"])
    assert await db.get_active_thesis("market", "SPX", "bull") is not None


async def test_weak_reaffirmation_does_not_keep_dead_thesis_fresh(stale_env):
    """A misread/weak mention (forming) must not reset the staleness clock — the dead
    thesis still ages out (the IGV-style bad-reaffirmation guard)."""
    now = time.time()
    tid = await _mk("sector", "IGV", "bull", "forming",
                    [{"ts": now - 40 * DAY, "to": "forming", "intent": "watching"},
                     {"ts": now - 1 * DAY, "to": "forming", "intent": "watching"}],
                    now - 40 * DAY)
    summary = await ws.run_staleness_sweep(now=now)
    assert any(d["id"] == tid for d in summary["demoted"])  # demoted despite the recent weak entry


async def test_contradiction_demotes_stale_side(stale_env):
    now = time.time()
    # SMH bear acting (high conviction) contradicts a stale IGV bull (same semis_tech complex)
    await _mk("sector", "SMH", "bear", "acting",
              [{"ts": now - 1 * DAY, "to": "acting", "intent": "adding"}], now - 1 * DAY)
    igv = await _mk("sector", "IGV", "bull", "forming",
                    [{"ts": now - 16 * DAY, "to": "forming"}], now - 16 * DAY)  # 16d: <30d age, >=14d contra
    summary = await ws.run_staleness_sweep(now=now)
    demoted = {d["id"]: d for d in summary["demoted"]}
    assert igv in demoted and "contradicted by SMH bear" in demoted[igv]["reason"]


async def test_dry_run_makes_no_writes(stale_env):
    now = time.time()
    tid = await _mk("sector", "KWEB", "bull", "forming",
                    [{"ts": now - 31 * DAY, "to": "forming"}], now - 31 * DAY)
    summary = await ws.run_staleness_sweep(now=now, dry_run=True)
    assert any(d["id"] == tid for d in summary["demoted"])
    # dry-run: thesis is still active, nothing demoted on disk
    assert await db.get_active_thesis("sector", "KWEB", "bull") is not None


# ---------------------------------------------------------------- ingest revival
async def test_ingest_revives_stale_on_explicit_reaffirmation(stale_env):
    now = time.time()
    tid = await _mk("sector", "KWEB", "bull", "forming",
                    [{"ts": now - 31 * DAY, "to": "forming"}], now - 31 * DAY)
    await ws.run_staleness_sweep(now=now)
    assert await db.get_active_thesis("sector", "KWEB", "bull") is None  # demoted

    # an explicit reaffirmation (acting + adding) should revive the SAME thread
    extraction = {"ts": now, "subject": "reaffirm", "theses": [
        {"scope_type": "sector", "scope_key": "KWEB", "direction": "bull",
         "stage": "acting", "position_intent": "adding", "levels": [],
         "snippet": "adding to my KWEB long", "timeframes": []},
    ]}
    await wolf_theses.ingest(extraction, source_id="rev1")
    revived = await db.get_active_thesis("sector", "KWEB", "bull")
    assert revived is not None and revived["id"] == tid  # reused, not a new row
    assert await db.get_stale_review_thesis("sector", "KWEB", "bull") is None


async def test_ingest_does_not_revive_on_weak_mention(stale_env):
    now = time.time()
    tid = await _mk("sector", "KWEB", "bull", "forming",
                    [{"ts": now - 31 * DAY, "to": "forming"}], now - 31 * DAY)
    await ws.run_staleness_sweep(now=now)
    assert await db.get_active_thesis("sector", "KWEB", "bull") is None

    extraction = {"ts": now, "subject": "weak", "theses": [
        {"scope_type": "sector", "scope_key": "KWEB", "direction": "bull",
         "stage": "forming", "position_intent": "watching", "levels": [],
         "snippet": "still watching KWEB", "timeframes": []},
    ]}
    await wolf_theses.ingest(extraction, source_id="weak1")
    # weak mention: stays stale_review, NOT resurrected, and no duplicate active row
    assert await db.get_active_thesis("sector", "KWEB", "bull") is None
    assert await db.get_stale_review_thesis("sector", "KWEB", "bull") is not None
