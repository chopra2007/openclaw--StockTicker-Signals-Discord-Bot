"""Daily market-context orchestrator (scripts/market_daily.py) — TDD tests.

The orchestrator is the single cron entrypoint that computes and persists the
daily market-context rows (sector_rs_daily / factor_rs_daily / trend_daily) by
calling the FROZEN analysis modules, reading point-in-time closes from the cached
Parquet store (data/market_store) and writing into a NON-live SQLite db passed via
``--db`` (here a pytest tmp_path).

These tests:
  * seed a temp db from the cached parquet store (run with a small --days window),
  * assert all three tables get populated with sane rows,
  * assert the built-in correctness gate ran (no exception),
  * assert re-running is idempotent (INSERT OR REPLACE — row counts unchanged).
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

# Project root on sys.path so ``import scripts.market_daily`` resolves.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import scripts.market_daily as md  # noqa: E402
from consensus_engine.analysis import sector_rotation as sr  # noqa: E402
from consensus_engine.analysis import factor_rotation as fr  # noqa: E402

_STORE = _ROOT / "data" / "market_store"

pytestmark = pytest.mark.skipif(
    not (_STORE / "SPY.parquet").exists(),
    reason="cached parquet store (data/market_store) not present",
)


def _counts(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        out = {}
        for t in ("sector_rs_daily", "factor_rs_daily", "trend_daily"):
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out
    finally:
        conn.close()


def test_orchestrator_populates_all_three_tables(tmp_path):
    db_path = str(tmp_path / "market.db")

    summary = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE), download=False)

    # run() reports what it wrote.
    assert summary["sector_rs_daily"] > 0
    assert summary["factor_rs_daily"] > 0
    assert summary["trend_daily"] > 0

    counts = _counts(db_path)
    assert counts["sector_rs_daily"] == summary["sector_rs_daily"]
    assert counts["factor_rs_daily"] == summary["factor_rs_daily"]
    assert counts["trend_daily"] == summary["trend_daily"]


def test_rows_are_sane(tmp_path):
    db_path = str(tmp_path / "market.db")
    md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE), download=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # --- sector_rs_daily ---
        srows = conn.execute("SELECT * FROM sector_rs_daily").fetchall()
        assert srows, "no sector rows seeded"
        etfs_seen = set()
        for r in srows:
            assert r["etf"] in sr.SECTOR_ETFS
            etfs_seen.add(r["etf"])
            assert r["quadrant"] in ("leading", "weakening", "lagging", "improving")
            assert r["inflection"] in (0, 1)
            assert r["rs_ratio"] == r["rs_ratio"]      # not NaN
            assert r["rs_momentum"] == r["rs_momentum"]
            assert r["n_window"] > 0 and r["k_window"] > 0
            assert r["computed_at"] > 0
        # most of the 13-ETF universe should be present on a 20-day window
        assert len(etfs_seen) >= 10

        # --- factor_rs_daily ---
        frows = conn.execute("SELECT * FROM factor_rs_daily").fetchall()
        assert frows, "no factor rows seeded"
        for r in frows:
            assert r["factor_etf"] in fr.FACTOR_ETFS
            assert r["leading"] in (0, 1)
            assert r["accelerating"] in (0, 1, None)
            assert r["rs_vs_spy"] == r["rs_vs_spy"]
            assert r["rs_momentum"] == r["rs_momentum"]

        # --- trend_daily ---
        trows = conn.execute("SELECT * FROM trend_daily").fetchall()
        assert trows, "no trend rows seeded"
        for r in trows:
            assert r["index_symbol"] == "SPY"
            assert r["trend_state"] in ("green", "yellow", "red")
            assert r["close"] > 0 and r["sma_200"] > 0 and r["sma_50"] > 0
    finally:
        conn.close()


def test_rerun_is_idempotent(tmp_path):
    db_path = str(tmp_path / "market.db")
    first = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE), download=False)
    before = _counts(db_path)

    second = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE), download=False)
    after = _counts(db_path)

    assert before == after, "re-running changed row counts (not idempotent)"
    assert first == second


def test_dry_run_writes_nothing(tmp_path):
    db_path = str(tmp_path / "market.db")
    summary = md.run(db_path=db_path, days=20, dry_run=True, store_dir=str(_STORE), download=False)
    # dry-run still computes (counts reported) but creates no db file / no rows.
    assert summary["sector_rs_daily"] > 0
    assert not Path(db_path).exists(), "dry-run must not create the db"


# ---------------------------------------------------------------------------
# Daily refresh (yfinance merge into the Parquet store) — TDD
# ---------------------------------------------------------------------------

def test_download_false_skips_fetch_and_uses_cache(tmp_path, monkeypatch):
    """download=False must NOT hit yfinance; it computes from the cached store."""
    called = {"n": 0}

    def _must_not_call(*a, **k):
        called["n"] += 1
        raise AssertionError("_download_recent called with download=False")

    monkeypatch.setattr(md, "_download_recent", _must_not_call)

    db_path = str(tmp_path / "market.db")
    summary = md.run(db_path=db_path, days=20, dry_run=False,
                     store_dir=str(_STORE), download=False)

    assert called["n"] == 0
    assert summary["sector_rs_daily"] > 0
    assert summary["factor_rs_daily"] > 0
    assert summary["trend_daily"] > 0


def test_refresh_merge_adds_new_row_keeps_history(tmp_path, monkeypatch):
    """A mocked fresh fetch adds a new date and overwrites the overlap, never
    dropping the older history."""
    store_dir = tmp_path / "store"
    store = md._get_store(store_dir)

    hist_idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    hist = pd.DataFrame(
        {"open": [1.0, 2.0, 3.0], "high": [1.0, 2.0, 3.0],
         "low": [1.0, 2.0, 3.0], "close": [10.0, 11.0, 12.0],
         "volume": [100, 100, 100]},
        index=hist_idx,
    )
    store.write_series("SPY", hist, source="seed", adjusted=False)

    # mocked yfinance: overlaps the last stored day (2024-01-04) + one NEW day.
    fresh_idx = pd.to_datetime(["2024-01-04", "2024-01-05"])
    fresh = pd.DataFrame(
        {"open": [3.0, 4.0], "high": [3.0, 4.0], "low": [3.0, 4.0],
         "close": [99.0, 13.0], "volume": [200, 200]},
        index=fresh_idx,
    )
    monkeypatch.setattr(md, "_REFRESH_SYMBOLS", ("SPY",))
    monkeypatch.setattr(md, "_download_recent",
                        lambda sym, period=md._REFRESH_PERIOD: fresh)

    n = md.refresh_store(store_dir=str(store_dir))
    assert n == 1

    out = store.read_series("SPY")
    # old history retained
    assert pd.Timestamp("2024-01-02") in out.index
    assert pd.Timestamp("2024-01-03") in out.index
    # new day appended
    assert pd.Timestamp("2024-01-05") in out.index
    assert float(out.loc["2024-01-05", "close"]) == 13.0
    # overlapping day overwritten by the fresh value (keep="last")
    assert float(out.loc["2024-01-04", "close"]) == 99.0
    assert len(out) == 4


def test_fetch_exception_is_swallowed_and_compute_proceeds(tmp_path, monkeypatch):
    """If yfinance raises, the refresh is skipped (history intact) and the run
    still computes from the cached store."""
    store_copy = tmp_path / "store"
    shutil.copytree(_STORE, store_copy)
    spy_len_before = len(md._get_store(store_copy).read_series("SPY"))

    def _raise(*a, **k):
        raise RuntimeError("simulated yfinance outage")

    monkeypatch.setattr(md, "_download_recent", _raise)

    db_path = str(tmp_path / "market.db")
    summary = md.run(db_path=db_path, days=20, dry_run=False,
                     store_dir=str(store_copy), download=True)

    # computation proceeded despite the fetch failure
    assert summary["sector_rs_daily"] > 0
    assert summary["factor_rs_daily"] > 0
    assert summary["trend_daily"] > 0
    # the cached history was NOT wiped by the failed refresh
    spy_len_after = len(md._get_store(store_copy).read_series("SPY"))
    assert spy_len_after == spy_len_before
    assert spy_len_after > 200
