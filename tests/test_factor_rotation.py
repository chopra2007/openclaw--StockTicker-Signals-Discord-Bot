"""F2 factor/style-rotation engine tests (TDD: written before the impl was wired in).

Covers, on deterministic synthetic price series:
  * compute_factor_rows matches an INDEPENDENT pandas .shift re-computation
    (anti-circular: the module uses hand-rolled trailing lookbacks, the test uses
    pandas) for rs_vs_spy / rs_momentum / leading / accelerating;
  * a hand-constructed set of factors yields a KNOWN leader ordering
    (MTUM > IWF > QUAL by trailing relative-strength return) and a KNOWN
    accelerating factor (MTUM, IWF accelerating; QUAL, VLUE fading; VLUE not a
    leader);
  * point-in-time truncation: value(full)[t] == value(prefix-to-t) (no look-ahead);
  * lookup_factor_leadership reads the persisted table and cold-starts on
    flag-off / stale / missing.

Definition under test (returns-based, point-in-time):
  rs[t]          = 100 * etf_close[t] / spy_close[t]
  rs_vs_spy[t]   = 100 * (rs[t] / rs[t - rs_window]  - 1)   # short RS return vs SPY
  rs_momentum[t] = 100 * (rs[t] / rs[t - mom_window] - 1)   # long  RS return vs SPY
  leading        = rs_vs_spy > 0
  accelerating   = (rs_vs_spy / rs_window) > (rs_momentum / mom_window)  -> True
                                          <  -> False (fading) ; == -> None (flat)
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from consensus_engine.analysis import factor_rotation as fr


_RW, _MW = 5, 10  # small windows so the synthetic 24-bar series is computable

# ---------------------------------------------------------------------------
# Synthetic fixtures (24 bars each). SPY constant -> rs == factor price, so the
# trailing RS returns are just the factors' own trailing price returns.
#   MTUM: flat then a sharp late acceleration  -> biggest rs_vs_spy, accelerating
#   IWF:  flat then a moderate late rise        -> middle rs_vs_spy,  accelerating
#   QUAL: steady linear rise                     -> small  rs_vs_spy, fading (% decel)
#   VLUE: steady decline                         -> negative rs_vs_spy (NOT leading), fading
# ---------------------------------------------------------------------------
_MTUM = [100.0] * 15 + [103, 107, 112, 118, 125, 133, 142, 152, 163]   # 24
_IWF = [100.0] * 18 + [102, 104, 107, 111, 116, 122]                    # 24
_QUAL = [100.0 + 1.5 * i for i in range(24)]                            # 24
_VLUE = [130.0 - 1.2 * i for i in range(24)]                            # 24

EXPECTED_LEADER_ORDER = ["MTUM", "IWF", "QUAL"]   # rs_vs_spy descending, leading only
EXPECTED_ACCELERATING = ["MTUM", "IWF"]           # short rate > long rate
EXPECTED_FADING = ["QUAL", "VLUE"]                # short rate < long rate


def _df(cols: dict[str, list[float]], spy: list[float] | None = None) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    spy = spy if spy is not None else [100.0] * n
    idx = pd.bdate_range("2024-01-01", periods=n)
    data = {"SPY": spy, **cols}
    return pd.DataFrame(data, index=idx)


def _all_factors() -> dict[str, list[float]]:
    return {"MTUM": _MTUM, "IWF": _IWF, "QUAL": _QUAL, "VLUE": _VLUE}


def _pandas_recompute(df: pd.DataFrame, etf: str, rw: int, mw: int):
    """Independent (pandas .shift) recompute of one factor's last-bar values."""
    rs = 100.0 * df[etf].astype(float) / df["SPY"].astype(float)
    rsv = 100.0 * (rs / rs.shift(rw) - 1.0)
    rmo = 100.0 * (rs / rs.shift(mw) - 1.0)
    last = len(df) - 1
    rs_vs_spy = float(rsv.iloc[last])
    rs_momentum = float(rmo.iloc[last])
    leading = 1 if rs_vs_spy > 0 else 0
    short_rate = rs_vs_spy / rw
    long_rate = rs_momentum / mw
    if short_rate > long_rate:
        accel = 1
    elif short_rate < long_rate:
        accel = 0
    else:
        accel = None
    return rs_vs_spy, rs_momentum, leading, accel


def _row_for(rows: list[dict], etf: str) -> dict:
    matches = [r for r in rows if r["factor_etf"] == etf]
    assert len(matches) == 1, f"expected exactly one row for {etf}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. compute_factor_rows == independent pandas recompute (varying SPY)
# ---------------------------------------------------------------------------

def test_compute_factor_rows_matches_independent_recompute():
    spy = [100.0 + 0.3 * i for i in range(24)]   # genuinely varying SPY
    df = _df(_all_factors(), spy)

    rows = fr.compute_factor_rows(df, rs_window=_RW, mom_window=_MW)
    last = len(df) - 1
    expected_date = str(df.index[last])[:10]

    for etf in ("MTUM", "IWF", "QUAL", "VLUE"):
        row = _row_for(rows, etf)
        rs_vs_spy, rs_momentum, leading, accel = _pandas_recompute(df, etf, _RW, _MW)
        assert row["date_utc"] == expected_date
        assert row["rs_vs_spy"] == pytest.approx(rs_vs_spy, abs=1e-9)
        assert row["rs_momentum"] == pytest.approx(rs_momentum, abs=1e-9)
        assert row["leading"] == leading
        assert row["accelerating"] == accel


# ---------------------------------------------------------------------------
# 2. Known leader ordering + known accelerating factor
# ---------------------------------------------------------------------------

def test_known_leader_ordering_and_acceleration():
    df = _df(_all_factors())   # SPY constant -> rs == price
    rows = fr.compute_factor_rows(df, rs_window=_RW, mom_window=_MW)
    last_date = str(df.index[-1])[:10]

    lead = fr.build_leadership(rows, last_date, cold_start=False)

    # Leaders are exactly the positive-rs_vs_spy factors, ranked high->low.
    assert [c.factor_etf for c in lead.leaders] == EXPECTED_LEADER_ORDER
    # VLUE is NOT a leader (negative trailing RS return).
    assert "VLUE" not in [c.factor_etf for c in lead.leaders]
    assert _row_for(rows, "VLUE")["leading"] == 0

    # Accelerating vs fading split.
    assert lead.accelerating == EXPECTED_ACCELERATING
    assert lead.fading == EXPECTED_FADING

    # rs_vs_spy strictly decreasing across the leader ranking.
    vals = [c.rs_vs_spy for c in lead.leaders]
    assert vals == sorted(vals, reverse=True)
    assert vals[0] > vals[1] > vals[2]


# ---------------------------------------------------------------------------
# 3. Point-in-time truncation: value(full)[t] == value(prefix-to-t)
# ---------------------------------------------------------------------------

def test_point_in_time_truncation():
    df = _df(_all_factors())
    full = fr.compute_factor_series(df, _RW, _MW)["MTUM"]

    for t in (12, 18, 23):   # all >= max(rw, mw) == 10
        full_cell = full[t]
        assert full_cell is not None
        prefix_rows = fr.compute_factor_rows(
            df.iloc[: t + 1], rs_window=_RW, mom_window=_MW
        )
        row = _row_for(prefix_rows, "MTUM")
        assert row["rs_vs_spy"] == pytest.approx(full_cell["rs_vs_spy"], abs=1e-12)
        assert row["rs_momentum"] == pytest.approx(full_cell["rs_momentum"], abs=1e-12)
        assert row["leading"] == (1 if full_cell["leading"] else 0)
        full_accel = full_cell["accelerating"]
        assert row["accelerating"] == (
            None if full_accel is None else (1 if full_accel else 0)
        )


def test_series_is_none_before_enough_history():
    df = _df(_all_factors())
    series = fr.compute_factor_series(df, _RW, _MW)
    # No cell can exist before index max(rw, mw) == 10 (needs rs[t-mw]).
    for etf, cells in series.items():
        for t in range(_MW):
            assert cells[t] is None, f"{etf}[{t}] should be None (insufficient history)"
        assert cells[_MW] is not None, f"{etf}[{_MW}] should be computable"


# ---------------------------------------------------------------------------
# 4. lookup_factor_leadership: reads persisted table; cold-starts appropriately
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    from consensus_engine import db
    prev = db.DB_PATH
    db.DB_PATH = str(tmp_path / "factor.db")
    await db.init_db()
    try:
        yield db
    finally:
        await db.close_db()
        db.DB_PATH = prev


async def _insert(db, *, factor, rs_vs_spy, rs_momentum, leading, accelerating,
                  date="2024-02-08", computed_at=None):
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO factor_rs_daily
           (date_utc, factor_etf, rs_vs_spy, rs_momentum, leading, accelerating,
            computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date, factor, rs_vs_spy, rs_momentum, leading, accelerating,
         computed_at if computed_at is not None else time.time()),
    )
    await conn.commit()


def _enable_flag(monkeypatch, enabled=True):
    prev = fr.cfg.get

    def _patched(key, default=None):
        if key == "features.factor_rotation.enabled":
            return enabled
        return prev(key, default)

    monkeypatch.setattr(fr.cfg, "get", _patched)


async def _seed_three(db, computed_at=None):
    await _insert(db, factor="MTUM", rs_vs_spy=30.0, rs_momentum=20.0,
                  leading=1, accelerating=1, computed_at=computed_at)
    await _insert(db, factor="QUAL", rs_vs_spy=8.0, rs_momentum=12.0,
                  leading=1, accelerating=0, computed_at=computed_at)
    await _insert(db, factor="VLUE", rs_vs_spy=-5.0, rs_momentum=-3.0,
                  leading=0, accelerating=0, computed_at=computed_at)


async def test_lookup_reads_fresh_rows(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    await _seed_three(tmp_db)

    lead = await fr.lookup_factor_leadership()
    assert lead.cold_start is False
    assert lead.as_of_date == "2024-02-08"
    assert [c.factor_etf for c in lead.leaders] == ["MTUM", "QUAL"]
    assert lead.leaders[0].rs_vs_spy == pytest.approx(30.0)
    assert lead.leaders[0].accelerating is True
    assert lead.accelerating == ["MTUM"]
    assert lead.fading == ["QUAL", "VLUE"]


async def test_lookup_cold_start_when_flag_off(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, False)
    await _seed_three(tmp_db)
    lead = await fr.lookup_factor_leadership()
    assert lead.cold_start is True
    assert lead.leaders == []
    assert lead.accelerating == []
    assert lead.fading == []


async def test_lookup_cold_start_when_stale(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    await _seed_three(tmp_db, computed_at=time.time() - 10 * 86400)  # 10d old
    lead = await fr.lookup_factor_leadership()
    assert lead.cold_start is True


async def test_lookup_cold_start_when_missing(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    lead = await fr.lookup_factor_leadership()   # nothing inserted
    assert lead.cold_start is True
