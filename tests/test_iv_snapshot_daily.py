"""#55 Build B — iv_snapshot_daily.py tests (no network — compute_em is mocked).

Covers:
  * universe building: explicit --tickers override, and core ∪ active watchlist,
  * row extraction from the frozen expected_move result,
  * fail-soft per ticker (EMUnavailable / unexpected error -> skip),
  * write_rows upsert (one row per ticker/day) + retention prune,
  * --dry-run computes but writes nothing,
  * _clean drops NaN/inf.
"""
from __future__ import annotations

import math
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Project root on sys.path so ``import scripts.iv_snapshot_daily`` resolves.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import scripts.iv_snapshot_daily as iv  # noqa: E402


def _fake_result(ticker, spot=100.0, atm_iv=0.25, straddle=3.5, iv_em=7.0,
                 expiry="2026-07-03"):
    return SimpleNamespace(
        ticker=ticker.upper(), spot=spot, expiration=expiry,
        em={"atm_iv": atm_iv, "raw_straddle_em": straddle,
            "iv_em_to_expiration": iv_em},
    )


def test_clean_drops_nan_and_inf():
    assert iv._clean(0.25) == pytest.approx(0.25)
    assert iv._clean(None) is None
    assert iv._clean(float("nan")) is None
    assert iv._clean(float("inf")) is None
    assert iv._clean("notnum") is None


def test_explicit_tickers_override(tmp_path):
    db_path = str(tmp_path / "x.db")  # does not exist -> watchlist empty anyway
    universe = iv.build_universe("spy, qqq ,NVDA,nvda", db_path)
    assert universe == ["SPY", "QQQ", "NVDA"], "explicit list overrides, upper+dedup"


def test_universe_unions_core_and_watchlist(tmp_path):
    db_path = str(tmp_path / "wl.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ticker_signals (ticker TEXT, expires_at REAL)"
    )
    future = time.time() + 3600
    past = time.time() - 3600
    conn.executemany(
        "INSERT INTO ticker_signals (ticker, expires_at) VALUES (?, ?)",
        [("PLTR", future), ("PLTR", future), ("SOFI", future), ("EXPIRED", past)],
    )
    conn.commit()
    conn.close()

    universe = iv.build_universe(None, db_path)
    # core preserved, watchlist (unexpired) added, expired excluded, no dupes.
    assert universe[: len(iv.LIQUID_CORE)] == list(iv.LIQUID_CORE)
    assert "PLTR" in universe and "SOFI" in universe
    assert "EXPIRED" not in universe
    assert len(universe) == len(set(universe))


async def test_compute_rows_extracts_fields(monkeypatch):
    async def fake_em(ticker, executor=None):
        return _fake_result(ticker)

    monkeypatch.setattr(iv.em, "compute_em", fake_em)
    rows = await iv.compute_rows(["SPY", "QQQ"], "2026-06-29", sleep_s=0)
    assert len(rows) == 2
    r = rows[0]
    assert r["ticker"] == "SPY"
    assert r["snapshot_date"] == "2026-06-29"
    assert r["spot"] == pytest.approx(100.0)
    assert r["atm_iv"] == pytest.approx(0.25)
    assert r["straddle_em"] == pytest.approx(3.5)
    assert r["iv_em_to_expiry"] == pytest.approx(7.0)
    assert r["expiry"] == "2026-07-03"
    assert r["captured_at"] > 0


async def test_compute_rows_fail_soft_skips_bad_ticker(monkeypatch):
    async def fake_em(ticker, executor=None):
        if ticker == "BAD":
            raise iv.em.EMUnavailable("no options listed")
        if ticker == "BOOM":
            raise RuntimeError("yfinance blew up")
        return _fake_result(ticker)

    monkeypatch.setattr(iv.em, "compute_em", fake_em)
    rows = await iv.compute_rows(["SPY", "BAD", "BOOM", "QQQ"], "2026-06-29", sleep_s=0)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"SPY", "QQQ"}, "bad/erroring tickers are skipped, run continues"


def test_write_rows_upsert_and_prune(tmp_path):
    db_path = str(tmp_path / "iv.db")

    rows = [
        {"snapshot_date": "2026-06-29", "ticker": "SPY", "spot": 100.0,
         "atm_iv": 0.25, "straddle_em": 3.5, "iv_em_to_expiry": 7.0,
         "expiry": "2026-07-03", "captured_at": time.time()},
    ]
    assert iv.write_rows(db_path, rows) == 1

    # Re-write same ticker/day with a changed value -> upsert (no duplicate).
    rows[0]["atm_iv"] = 0.30
    iv.write_rows(db_path, rows)

    conn = sqlite3.connect(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM iv_snapshots WHERE ticker='SPY' AND snapshot_date='2026-06-29'"
        ).fetchone()[0]
        assert cnt == 1
        iv_val = conn.execute(
            "SELECT atm_iv FROM iv_snapshots WHERE ticker='SPY'"
        ).fetchone()[0]
        assert iv_val == pytest.approx(0.30)

        # Insert a stale row beyond retention, then prune via a fresh write.
        conn.execute(
            "INSERT OR REPLACE INTO iv_snapshots "
            "(snapshot_date, ticker, spot, atm_iv, straddle_em, iv_em_to_expiry, expiry, captured_at) "
            "VALUES ('2000-01-01', 'OLD', 1, 1, 1, 1, '2000-01-08', 0)"
        )
        conn.commit()
    finally:
        conn.close()

    fresh = [{"snapshot_date": "2026-06-29", "ticker": "QQQ", "spot": 50.0,
              "atm_iv": 0.2, "straddle_em": 1.0, "iv_em_to_expiry": 2.0,
              "expiry": "2026-07-03", "captured_at": time.time()}]
    iv.write_rows(db_path, fresh, retention_days=750)

    conn = sqlite3.connect(db_path)
    try:
        old = conn.execute(
            "SELECT COUNT(*) FROM iv_snapshots WHERE ticker='OLD'"
        ).fetchone()[0]
        assert old == 0, "rows older than retention_days must be pruned"
    finally:
        conn.close()


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "dry.db")

    async def fake_em(ticker, executor=None):
        return _fake_result(ticker)

    monkeypatch.setattr(iv.em, "compute_em", fake_em)
    summary = iv.run(db_path=db_path, tickers="SPY,QQQ", dry_run=True, sleep_s=0)
    assert summary["computed"] == 2
    assert summary["written"] == 0
    assert not Path(db_path).exists(), "dry-run must not create/write the db"
