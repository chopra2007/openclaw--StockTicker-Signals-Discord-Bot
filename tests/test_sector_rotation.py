"""F1 sector-rotation engine tests (TDD: written before the impl was wired in).

Covers, on deterministic synthetic price series:
  * compute_rotation matches an INDEPENDENT pandas .rolling re-computation
    (anti-circular: module uses hand-rolled trailing windows, test uses pandas);
  * a hand-constructed V-shape produces the expected quadrant sequence and a
    known lagging->improving inflection that honours distance + persistence;
  * point-in-time truncation: the value on the full series == the value on the
    prefix-to-t for several sampled dates (no look-ahead);
  * lookup_rotation reads the persisted table and cold-starts on flag-off / stale.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from consensus_engine.analysis import sector_rotation as sr


# ---------------------------------------------------------------------------
# Synthetic fixture: a clear V — gentle decline, an accelerating drop into the
# trough (-> lagging), then a gentle staircase recovery (-> improving). With
# N=20 the trailing mean stays high through the early recovery so the ETF is
# still BELOW its mean (rs_ratio<100) while momentum turns up (rs_momentum>100)
# = the lagging->improving setup. Verified by prototype:
#   t=25,26 -> lagging ; t=27,28 -> improving (2-day run) ; inflection @ t=28 (P=2)
# ---------------------------------------------------------------------------
_GENTLE = list(range(140, 104, -2))      # 18 pts, slow decline (keeps 20-mean high)
_ACCEL = [101, 95, 87, 77, 66]           # accelerating drop -> rr falls -> lagging
_RECOVERY = [67, 69, 72, 76, 81, 87, 94] # gentle recovery -> rr still < mean, rm up
_ETF_PATH = _GENTLE + _ACCEL + _RECOVERY  # 30 points
_N, _K, _D, _P = 20, 3, 0.5, 2

LAG_DAYS = (25, 26)
IMPROVE_RUN = (27, 28)
INFLECTION_DAY = 28


def _df(etf_path: list[float], spy_path: list[float] | None = None) -> pd.DataFrame:
    """Build a date-indexed closes DataFrame with SPY + a single ETF column."""
    n = len(etf_path)
    spy_path = spy_path if spy_path is not None else [100.0] * n
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"SPY": spy_path, "XLK": etf_path}, index=idx)


def _pandas_recompute(df: pd.DataFrame, n: int, k: int):
    """Independent (pandas .rolling) recompute of rs_ratio / rs_momentum / quadrant."""
    spy = df["SPY"].astype(float)
    rs = 100.0 * df["XLK"].astype(float) / spy
    mean = rs.rolling(n).mean()
    std = rs.rolling(n).std(ddof=0)
    rs_ratio = 100.0 + ((rs - mean) / std).where(std > 0, 0.0)
    roc = rs_ratio.diff(1)
    rmean = roc.rolling(k).mean()
    rstd = roc.rolling(k).std(ddof=0)
    rs_mom = 100.0 + ((roc - rmean) / rstd).where(rstd > 0, 0.0)

    def quad(rr, rm):
        if pd.isna(rr) or pd.isna(rm):
            return None
        if rr >= 100 and rm >= 100:
            return "leading"
        if rr >= 100 and rm < 100:
            return "weakening"
        if rr < 100 and rm < 100:
            return "lagging"
        return "improving"

    quads = [quad(rs_ratio.iloc[i], rs_mom.iloc[i]) for i in range(len(df))]
    return rs_ratio, rs_mom, quads


# ---------------------------------------------------------------------------
# 1. compute_rotation == independent pandas recompute (varying SPY)
# ---------------------------------------------------------------------------

def test_compute_rotation_matches_independent_recompute():
    # A genuinely varying SPY so the rs = etf/spy division is exercised.
    spy = [100.0 + 0.3 * i for i in range(len(_ETF_PATH))]
    df = _df(_ETF_PATH, spy)

    rows = sr.compute_rotation(df, n_window=_N, k_window=_K, distance=_D, persistence=_P)
    assert len(rows) == 1
    row = rows[0]
    assert row["etf"] == "XLK"
    assert row["n_window"] == _N and row["k_window"] == _K

    rs_ratio, rs_mom, quads = _pandas_recompute(df, _N, _K)
    last = len(df) - 1
    assert row["rs_ratio"] == pytest.approx(float(rs_ratio.iloc[last]), abs=1e-9)
    assert row["rs_momentum"] == pytest.approx(float(rs_mom.iloc[last]), abs=1e-9)
    assert row["quadrant"] == quads[last]
    assert row["date_utc"] == str(df.index[last])[:10]


# ---------------------------------------------------------------------------
# 2. Hand-constructed quadrants + known lagging->improving inflection
# ---------------------------------------------------------------------------

def _row_for_prefix(df, upto, **params):
    rows = sr.compute_rotation(df.iloc[: upto + 1], **params)
    assert len(rows) == 1
    return rows[0]


def test_known_quadrants_and_inflection():
    df = _df(_ETF_PATH)  # SPY constant -> rs == etf price

    # The two pre-transition days are 'lagging' (weak level + decelerating).
    for t in LAG_DAYS:
        r = _row_for_prefix(df, t, n_window=_N, k_window=_K, distance=_D, persistence=_P)
        assert r["quadrant"] == "lagging", f"t={t} expected lagging, got {r['quadrant']}"
        assert r["inflection"] == 0

    # The recovery days are 'improving' (still weak level, momentum turned up).
    for t in IMPROVE_RUN:
        r = _row_for_prefix(df, t, n_window=_N, k_window=_K, distance=_D, persistence=_P)
        assert r["quadrant"] == "improving", f"t={t} expected improving, got {r['quadrant']}"

    # persistence=2: inflection fires on the SECOND improving day, not the first.
    first = _row_for_prefix(df, IMPROVE_RUN[0], n_window=_N, k_window=_K,
                            distance=_D, persistence=2)
    second = _row_for_prefix(df, IMPROVE_RUN[1], n_window=_N, k_window=_K,
                             distance=_D, persistence=2)
    assert first["inflection"] == 0   # only 1 improving day so far -> not persisted
    assert second["inflection"] == 1  # lagging->improving confirmed @ t=28
    assert second["rs_momentum"] - 100.0 > _D

    # persistence=1: it fires on the first improving day too.
    first_p1 = _row_for_prefix(df, IMPROVE_RUN[0], n_window=_N, k_window=_K,
                               distance=_D, persistence=1)
    assert first_p1["inflection"] == 1

    # distance gate: a very high D suppresses the inflection even when persisted.
    second_hiD = _row_for_prefix(df, IMPROVE_RUN[1], n_window=_N, k_window=_K,
                                 distance=10.0, persistence=2)
    assert second_hiD["inflection"] == 0


# ---------------------------------------------------------------------------
# 3. Point-in-time truncation: value(full)[t] == value(prefix-to-t)
# ---------------------------------------------------------------------------

def test_point_in_time_truncation():
    df = _df(_ETF_PATH)
    full = sr.compute_series(df, _N, _K, _D, _P)["XLK"]

    sampled = [24, 27, 28]  # >= 3 dates, all with computable cells
    for t in sampled:
        full_cell = full[t]
        assert full_cell is not None
        prefix_row = _row_for_prefix(df, t, n_window=_N, k_window=_K,
                                     distance=_D, persistence=_P)
        assert prefix_row["rs_ratio"] == pytest.approx(full_cell["rs_ratio"], abs=1e-12)
        assert prefix_row["rs_momentum"] == pytest.approx(full_cell["rs_momentum"], abs=1e-12)
        assert prefix_row["quadrant"] == full_cell["quadrant"]
        assert bool(prefix_row["inflection"]) == bool(full_cell["inflection"])


# ---------------------------------------------------------------------------
# 4. lookup_rotation: reads persisted table; cold-starts on flag-off / stale
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    from consensus_engine import db
    prev = db.DB_PATH
    db.DB_PATH = str(tmp_path / "rotation.db")
    await db.init_db()
    try:
        yield db
    finally:
        await db.close_db()
        db.DB_PATH = prev


async def _insert_row(db, *, etf="XLK", quadrant="improving", inflection=1,
                      computed_at=None):
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO sector_rs_daily
           (date_utc, etf, rs_ratio, rs_momentum, quadrant, inflection,
            n_window, k_window, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("2024-02-08", etf, 99.5, 101.3, quadrant, inflection, 20, 3,
         computed_at if computed_at is not None else time.time()),
    )
    await conn.commit()


def _enable_flag(monkeypatch, enabled=True):
    prev = sr.cfg.get

    def _patched(key, default=None):
        if key == "features.sector_rotation.enabled":
            return enabled
        return prev(key, default)

    monkeypatch.setattr(sr.cfg, "get", _patched)


async def test_lookup_rotation_reads_fresh_row(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    await _insert_row(tmp_db, quadrant="improving", inflection=1)

    ctx = await sr.lookup_rotation("XLK")
    assert ctx.cold_start is False
    assert ctx.etf == "XLK"
    assert ctx.quadrant == "improving"
    assert ctx.inflection is True
    assert ctx.as_of_date == "2024-02-08"
    assert ctx.rs_ratio == pytest.approx(99.5)
    assert ctx.rs_momentum == pytest.approx(101.3)


async def test_lookup_rotation_cold_start_when_flag_off(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, False)
    await _insert_row(tmp_db)
    ctx = await sr.lookup_rotation("XLK")
    assert ctx.cold_start is True
    assert ctx.quadrant == ""


async def test_lookup_rotation_cold_start_when_stale(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    # 10 days old -> beyond market_panel's 7-day staleness horizon.
    await _insert_row(tmp_db, computed_at=time.time() - 10 * 86400)
    ctx = await sr.lookup_rotation("XLK")
    assert ctx.cold_start is True


async def test_lookup_rotation_cold_start_when_missing(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    ctx = await sr.lookup_rotation("XLK")  # nothing inserted
    assert ctx.cold_start is True
