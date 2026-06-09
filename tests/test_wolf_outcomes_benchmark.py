"""I16 — benchmark-adjusted Wolf outcome classification.

Flag: wolf.outcomes.benchmark_adjusted (default OFF — forced OFF in conftest).
These tests force the flag ON in-body and assert:
  1. A call that rose but LAGGED SPY is NOT credited 'moved_with' under the flag.
  2. An inverse-proxy scope (e.g. SOXS bull = semis bear) is sign-aware — the
     benchmark sign is flipped so a rising SPY counts AGAINST the bear call.
  3. Both raw ('state') and benchmark-adjusted ('adjusted_state') are present in
     every result; raw is never replaced.
  4. When the flag is OFF the result dict has no 'adjusted_state' key (byte-identical
     to the existing behavior — regression guard).
  5. Benchmark fetch failure falls back to the raw state (not a crash, not 'flat').
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import config as cfg, db
from consensus_engine.analysis import wolf_outcomes

PT = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------- shared helpers

@pytest.fixture
async def bm_env(monkeypatch):
    """Isolated DB + flag forced ON for every test in this file."""
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()

    # Force the benchmark flag ON — defeats the conftest force-off fixture.
    _real = cfg.get

    def _patched(key, default=None):
        if key == "wolf.outcomes.benchmark_adjusted":
            return True
        return _real(key, default)

    monkeypatch.setattr(cfg, "get", _patched)
    yield
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def _seed(scope_type, scope_key, direction, stage, anchor_ts):
    evlog = [{"ts": anchor_ts, "to": stage}]
    return await db.insert_thesis(
        scope_type, scope_key, direction, stage, "[]", None, 0,
        json.dumps(evlog), anchor_ts,
    )


# ---------------------------------------------------------- test 1: rose but lagged SPY -> NOT moved_with

async def test_rose_but_lagged_spy_not_moved_with(monkeypatch, bm_env):
    """Stock rose +3% but SPY rose +5%: excess = -2% → NOT moved_with under the flag."""
    anchor_ts = datetime(2026, 6, 1, 10, 0, tzinfo=PT).timestamp()
    await _seed("stock", "NVDA", "bull", "acting", anchor_ts)

    def fake_series(symbol, _anchor_ts):
        if symbol == "NVDA":
            # +3% move, band 1%
            return {"anchor_close": 100.0, "latest_close": 103.0, "band_pct": 1.0}
        if symbol == "SPY":
            # SPY rose +5% — proxy LAGGED the benchmark
            return {"anchor_close": 500.0, "latest_close": 525.0, "band_pct": 1.0}
        return {}

    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
    outs = await wolf_outcomes.compute_outcomes()
    assert len(outs) == 1
    r = outs[0]
    # Raw: +3% > band → moved_with
    assert r["state"] == "moved_with"
    # Excess = +3% - +5% = -2% → negative → moved_against under adjusted
    assert "adjusted_state" in r
    assert r["adjusted_state"] != "moved_with", (
        f"Expected NOT moved_with (lagged SPY by 2%), got {r['adjusted_state']!r}"
    )
    # Both raw and adjusted are present
    assert r["state"] == "moved_with"          # raw preserved
    assert "benchmark_pct" in r


# ---------------------------------------------------------- test 2: inverse-proxy sign-aware

async def test_inverse_proxy_sign_aware(monkeypatch, bm_env):
    """SOXS bull thesis (= semis BEAR): when SPY rises +5%, the benchmark contribution
    must be sign-flipped so a rising market counts AGAINST the bear call.

    SOXS+8% (= semis down 8%) is a strong bear move.  SPY+5% in the same window means
    the macro environment helped bears — the flip makes bm_pct_signed = -5%.
    excess = pct(+8 after direction flip) - bm_pct_signed(-5) = +13 → still moved_with.

    But if SOXS only rose +1% (weak bear signal) and SPY also rose +1% (mixed environment,
    no flip adjusts: bm = -1 for a bear call via the flip), excess = +1 - (-1) = +2 → moved_with.

    The key assertion: with NO sign flip, pct=+1 and bm_raw=+1 → excess=0 → flat.
    WITH the sign flip, bm_pct_signed=-1 → excess=+2 → moved_with (correctly credits the bear).
    This proves the inverse-proxy flip is active.
    """
    anchor_ts = datetime(2026, 6, 1, 10, 0, tzinfo=PT).timestamp()
    # SOXS is in _INVERSE_PROXY: scope resolves to sector/SMH with direction flipped
    # but wolf stores it as the original parsed scope. We test using scope_key=SOXS
    # directly to exercise is_inverse_proxy(scope_key).
    await _seed("sector", "SOXS", "bull", "acting", anchor_ts)

    def fake_series(symbol, _anchor_ts):
        if symbol == "SOXS":
            # SOXS rose +1% (a weak bear signal — proxy direction matches: bull SOXS)
            return {"anchor_close": 10.0, "latest_close": 10.1, "band_pct": 0.5}
        if symbol == "SPY":
            # SPY rose +1%
            return {"anchor_close": 500.0, "latest_close": 505.0, "band_pct": 0.5}
        return {}

    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
    outs = await wolf_outcomes.compute_outcomes()
    assert len(outs) == 1
    r = outs[0]
    # With sign flip: bm_pct_signed = -(+1%) = -1%; excess = pct(+1%) - (-1%) = +2% > band(0.5%)
    # → adjusted_state = moved_with  (correctly rewards a bear call in a rising market)
    assert r["adjusted_state"] == "moved_with", (
        f"Inverse-proxy sign flip failed: expected moved_with, got {r['adjusted_state']!r}"
    )
    # Verify raw is still present and unchanged
    assert "state" in r


# ---------------------------------------------------------- test 3: raw + adjusted both present

async def test_both_raw_and_adjusted_present(monkeypatch, bm_env):
    """Both 'state' and 'adjusted_state' must be in every result when flag is ON."""
    anchor_ts = datetime(2026, 6, 1, 10, 0, tzinfo=PT).timestamp()
    await _seed("stock", "AAPL", "bull", "acting", anchor_ts)

    def fake_series(symbol, _anchor_ts):
        return {"anchor_close": 100.0, "latest_close": 110.0, "band_pct": 1.0}

    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
    outs = await wolf_outcomes.compute_outcomes()
    r = outs[0]
    assert "state" in r, "raw 'state' missing"
    assert "adjusted_state" in r, "'adjusted_state' missing when flag is ON"
    assert "benchmark_pct" in r, "'benchmark_pct' missing when flag is ON"


# ---------------------------------------------------------- test 4: flag OFF → no adjusted keys (regression guard)

async def test_flag_off_no_adjusted_keys(monkeypatch):
    """When the flag is OFF (conftest default), result has no 'adjusted_state' key — legacy shape."""
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    try:
        anchor_ts = datetime(2026, 6, 1, 10, 0, tzinfo=PT).timestamp()
        await _seed("stock", "TSLA", "bull", "acting", anchor_ts)

        def fake_series(symbol, _anchor_ts):
            return {"anchor_close": 100.0, "latest_close": 112.0, "band_pct": 1.0}

        monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
        # conftest already forces wolf.outcomes.benchmark_adjusted=False — flag is OFF
        outs = await wolf_outcomes.compute_outcomes()
        r = outs[0]
        assert "state" in r
        assert "adjusted_state" not in r, (
            "'adjusted_state' must not appear when flag is OFF"
        )
        assert "benchmark_pct" not in r
    finally:
        await db.close_db()
        db._db = None
        db.DB_PATH = None


# ---------------------------------------------------------- test 5: benchmark fetch failure → raw state, no crash

async def test_benchmark_fetch_failure_falls_back(monkeypatch, bm_env):
    """If the SPY fetch fails, adjusted_state equals raw state (graceful degradation)."""
    anchor_ts = datetime(2026, 6, 1, 10, 0, tzinfo=PT).timestamp()
    await _seed("stock", "META", "bull", "acting", anchor_ts)

    def fake_series(symbol, _anchor_ts):
        if symbol == "META":
            return {"anchor_close": 100.0, "latest_close": 108.0, "band_pct": 1.0}
        # SPY fetch fails — return empty dict
        return {}

    monkeypatch.setattr(wolf_outcomes, "_fetch_proxy_series", fake_series)
    outs = await wolf_outcomes.compute_outcomes()
    r = outs[0]
    assert "adjusted_state" in r
    # Fallback: adjusted_state must equal raw state (not a crash, not some other value)
    assert r["adjusted_state"] == r["state"], (
        f"Fallback broken: state={r['state']!r}, adjusted_state={r['adjusted_state']!r}"
    )
