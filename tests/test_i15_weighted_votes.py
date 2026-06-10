"""I15 (signal-features-2026-06-09) — recency + size weighting in Wolf confluence.

Asserts that when wolf.confluence.weighted_votes_enabled is ON:
  (a) A stale row decays toward-but-not-to zero (DECAY_FLOOR) rather than voting at full weight.
  (b) A huge options premium is percentile-capped so it cannot dominate small-size rows.
  (c) A leg whose as_of is outside the common-recency-window cap is excluded entirely.
  (d) Critical escalation is blocked when ONLY actor-controllable sources agree; adding one
      unplanned SEC leg (non-actor-controllable) unblocks it.

With the flag OFF (e):
  (e) Votes and tier are byte-identical to the legacy path for the same inputs.

All tests force the flag in-body via monkeypatch on wc.cfg (wolf_confluence's cfg reference),
matching the pattern used by other dedicated feature tests (test_i5_sec_graduated_scoring.py,
test_wolf_confluence.py::_force_flags).
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from consensus_engine import config as cfg
from consensus_engine.analysis import wolf_confluence as wc


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_ts() -> float:
    return time.time()


def _iso(offset_hours: float = 0.0) -> str:
    """ISO-8601 UTC string offset_hours from now (negative = in the past)."""
    dt = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _thesis(scope_type="stock", scope_key="NVDA", direction="bull", has_levels=1):
    return {"scope_type": scope_type, "scope_key": scope_key,
            "direction": direction, "has_levels": has_levels}


def _flag_on(monkeypatch, extra: dict | None = None):
    """Force wolf.confluence.weighted_votes_enabled ON; everything else defaults.

    Pass `extra` to override additional keys (e.g. recency_window caps).
    """
    overrides = {"wolf.confluence.weighted_votes_enabled": True}
    if extra:
        overrides.update(extra)
    real_get = cfg.get
    monkeypatch.setattr(
        wc.cfg, "get",
        lambda k, d=None: overrides.get(k, real_get(k, d)),
    )


# ── (a) stale row decays toward-but-not-to DECAY_FLOOR ───────────────────────

def test_stale_row_decays_toward_floor_not_zero(monkeypatch):
    """A 20-day-old tweet has age-decay weight = DECAY_FLOOR, not 0.

    Concretely: with only one stale BULL row, net_vote_weighted still returns BULL
    (the floor weight > 0), but the weight is strictly less than a fresh row's weight.
    """
    _flag_on(monkeypatch)

    # 20 days = 480 hours ago
    stale_as_of = _iso(-480)
    fresh_as_of = _iso(-0.5)   # 30 min ago

    now = datetime.now(timezone.utc)

    stale_decay = wc._age_decay(stale_as_of, now)
    fresh_decay = wc._age_decay(fresh_as_of, now)

    # Floor is DECAY_FLOOR (0.20), not 0.
    assert stale_decay == pytest.approx(wc._DECAY_FLOOR, abs=0.005), (
        f"stale decay {stale_decay} must equal DECAY_FLOOR {wc._DECAY_FLOOR}")
    # Fresh row is heavier than the stale floor.
    assert fresh_decay > wc._DECAY_FLOOR
    # Stale row still votes (floor > 0): net_vote_weighted returns BULL with one row.
    assert wc.net_vote_weighted([("BULL", stale_decay)], min_dominance=0.6) == "BULL"


def test_age_decay_formula_monotone(monkeypatch):
    """Decay is monotonically decreasing with age, floored at DECAY_FLOOR."""
    _flag_on(monkeypatch)
    now = datetime.now(timezone.utc)
    ages_h = [0, 1, 24, 168, 504]  # 0h, 1h, 1d, 7d, 21d
    decays = [wc._age_decay(_iso(-h), now) for h in ages_h]
    # monotone non-increasing
    for i in range(len(decays) - 1):
        assert decays[i] >= decays[i + 1], f"decay not monotone at index {i}: {decays}"
    # all at or above floor
    for d in decays:
        assert d >= wc._DECAY_FLOOR


# ── (b) huge options premium is percentile-capped ────────────────────────────

def test_size_norm_caps_outlier():
    """_size_norm clips the top 5% outlier to 1.0; other values scale linearly."""
    sizes = [100.0, 200.0, 300.0, 400.0, 5_000_000.0]  # last is the $5M outlier
    norms = wc._size_norm(sizes)
    # The giant value is capped at 1.0.
    assert norms[-1] == pytest.approx(1.0)
    # Normal values are below 1.0.
    assert all(n <= 1.0 for n in norms)
    # Smaller values map to smaller norms.
    assert norms[0] < norms[1] < norms[2]


def test_large_options_premium_cannot_dominate_channel_count(monkeypatch):
    """With size capping ON, a $5M options row does not push agree_count beyond the
    real source count — each source still casts exactly ONE weighted vote."""
    _flag_on(monkeypatch)

    # One options row with a giant premium, and one YouTube row with 2 channels.
    rows = {
        "options": [{"ticker": "NVDA", "dir": "CALL", "as_of": _iso(-1),
                     "size": 5_000_000.0}],
        "youtube": [{"ticker": "NVDA", "dir": "long", "channel": "TA Guy",
                     "as_of": _iso(-2), "size": 2.0}],
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # agree_count is still 2 (one vote per source type, not inflated by size).
    assert r.agree_count == 2


# ── (c) stale leg outside recency-window cap is excluded entirely ─────────────

def test_stale_leg_outside_window_excluded(monkeypatch):
    """A leg older than the confluence WINDOW itself (wolf.confluence.window_days)
    is dropped entirely — not even a floor-weight vote. In-window staleness is
    handled by smooth age-decay, NOT the global minutes-scale recency caps
    (Wolf confluence is deliberately an over-time feature — first live run
    2026-06-10 proved the global caps deleted every vote)."""
    _flag_on(monkeypatch)

    stale_tweet = {"ticker": "NVDA", "dir": "long",
                   "as_of": _iso(-30 * 24)}  # 30 days ago — beyond the 21-day window
    rows = {"twitter": [stale_tweet]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # The beyond-window leg is excluded entirely — no vote cast.
    assert r.agree_count == 0
    assert r.tier == "surface"


def test_null_timestamp_leg_excluded(monkeypatch):
    """A weighted-path leg with no usable as_of is stale by the I1 rule and is
    dropped (real producer rows always carry as_of after the 2026-06-10 fix)."""
    _flag_on(monkeypatch)

    rows = {"twitter": [{"ticker": "NVDA", "dir": "long"}]}  # no as_of
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 0


def test_in_window_stale_leg_kept_but_decayed(monkeypatch):
    """A 3-day-old tweet is INSIDE the window: it still votes (decayed), it is
    not hard-dropped — the regression the first live run exposed."""
    _flag_on(monkeypatch)

    rows = {"twitter": [{"ticker": "NVDA", "dir": "long", "as_of": _iso(-3 * 24)}]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 1


def test_fresh_leg_inside_recency_cap_kept(monkeypatch):
    """A tweet within the cap passes filter_fresh and contributes its vote."""
    _flag_on(monkeypatch, extra={
        "features.recency_window.enabled": True,
        "features.recency_window.max_age_min.tweet": 120,
    })

    fresh_tweet = {"ticker": "NVDA", "dir": "long", "as_of": _iso(-0.5)}  # 30 min ago
    rows = {"twitter": [fresh_tweet]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    assert r.agree_count == 1
    assert r.tier == "high"


# ── (d) critical escalation: actor-controllable sources alone are blocked ──────

def test_critical_blocked_with_only_actor_controllable_sources(monkeypatch):
    """Options + Twitter are both actor-controllable. With require_nonactor_for_critical=True
    (the default), two such agreeing sources must NOT escalate to critical."""
    _flag_on(monkeypatch, extra={
        "wolf.confluence.require_nonactor_for_critical": True,
    })

    rows = {
        "options": [{"ticker": "NVDA", "dir": "CALL", "as_of": _iso(-1)}],
        "twitter": [{"ticker": "NVDA", "dir": "long", "as_of": _iso(-0.5)}],
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Two agreeing sources, but both actor-controllable → demoted from critical to high.
    assert r.agree_count == 2
    assert r.tier == "high", f"expected high, got {r.tier}"


def test_critical_unblocked_by_sec_leg(monkeypatch):
    """Adding one unplanned SEC (non-actor-controllable) leg on top of two actor-
    controllable agrees unblocks escalation to critical."""
    _flag_on(monkeypatch, extra={
        "wolf.confluence.require_nonactor_for_critical": True,
    })

    rows = {
        "options": [{"ticker": "NVDA", "dir": "CALL", "as_of": _iso(-1)}],
        "twitter": [{"ticker": "NVDA", "dir": "long", "as_of": _iso(-0.5)}],
        "sec":     [{"ticker": "NVDA", "dir": "bullish", "as_of": _iso(-2),
                     "is_planned": False}],
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Three agrees including one non-actor-controllable → critical is now permitted.
    assert r.agree_count == 3
    assert r.tier == "critical", f"expected critical, got {r.tier}"


def test_critical_still_blocked_when_sec_is_planned(monkeypatch):
    """A 10b5-1 / pre-arranged SEC row (is_planned=True) does NOT count as a
    non-actor-controllable source — critical escalation stays blocked."""
    _flag_on(monkeypatch, extra={
        "wolf.confluence.require_nonactor_for_critical": True,
    })

    rows = {
        "options": [{"ticker": "NVDA", "dir": "CALL", "as_of": _iso(-1)}],
        "twitter": [{"ticker": "NVDA", "dir": "long", "as_of": _iso(-0.5)}],
        "sec":     [{"ticker": "NVDA", "dir": "bullish", "as_of": _iso(-2),
                     "is_planned": True}],   # 10b5-1
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Three source-type votes, but the only non-actor one is planned → still blocked.
    assert r.agree_count == 3
    assert r.tier == "high", f"expected high (planned SEC doesn't unblock), got {r.tier}"


# ── (e) flag-OFF: byte-identical to legacy for same inputs ───────────────────

def test_flag_off_votes_identical_to_legacy(monkeypatch):
    """With weighted_votes_enabled=False (the conftest default), score_confluence
    produces the same tier/agree_count as it did before I15."""
    # Explicitly ensure flag is OFF (the conftest already forces this, but be explicit).
    real_get = cfg.get
    monkeypatch.setattr(
        wc.cfg, "get",
        lambda k, d=None: False if k == "wolf.confluence.weighted_votes_enabled"
        else real_get(k, d),
    )

    rows = {
        "twitter": [{"ticker": "NVDA", "dir": "long"}],
        "youtube": [{"ticker": "NVDA", "dir": "long", "channel": "TA Guy"}],
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Legacy behavior: 2 agree → critical (with has_levels=1).
    assert r.tier == "critical"
    assert r.agree_count == 2


def test_flag_off_no_recency_filtering(monkeypatch):
    """With weighted_votes_enabled=False, stale rows are NOT filtered even if
    recency_window would normally exclude them — legacy behavior preserved."""
    real_get = cfg.get
    monkeypatch.setattr(
        wc.cfg, "get",
        lambda k, d=None: False if k == "wolf.confluence.weighted_votes_enabled"
        else real_get(k, d),
    )

    # 10-day-old tweet — would be excluded by recency_window if flag were on.
    stale_tweet = {"ticker": "NVDA", "dir": "long", "as_of": _iso(-240)}
    rows = {"twitter": [stale_tweet]}
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Legacy: stale row still votes (no recency filtering in legacy path).
    assert r.agree_count == 1
    assert r.tier == "high"


def test_flag_off_nonactor_gate_not_applied(monkeypatch):
    """With weighted_votes_enabled=False, two actor-controllable sources CAN reach
    critical — the nonactor gate is only active inside the weighted path."""
    real_get = cfg.get
    monkeypatch.setattr(
        wc.cfg, "get",
        lambda k, d=None: False if k == "wolf.confluence.weighted_votes_enabled"
        else real_get(k, d),
    )

    rows = {
        "options": [{"ticker": "NVDA", "dir": "CALL"}],
        "twitter": [{"ticker": "NVDA", "dir": "long"}],
    }
    r = wc.score_confluence(_thesis(direction="bull"), rows)
    # Legacy: 2 agrees → critical, no nonactor check.
    assert r.tier == "critical"
    assert r.agree_count == 2
