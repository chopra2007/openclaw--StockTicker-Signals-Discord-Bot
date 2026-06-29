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

import sqlite3
import sys
from pathlib import Path

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

    summary = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE))

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
    md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE))

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
    first = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE))
    before = _counts(db_path)

    second = md.run(db_path=db_path, days=20, dry_run=False, store_dir=str(_STORE))
    after = _counts(db_path)

    assert before == after, "re-running changed row counts (not idempotent)"
    assert first == second


def test_dry_run_writes_nothing(tmp_path):
    db_path = str(tmp_path / "market.db")
    summary = md.run(db_path=db_path, days=20, dry_run=True, store_dir=str(_STORE))
    # dry-run still computes (counts reported) but creates no db file / no rows.
    assert summary["sector_rs_daily"] > 0
    assert not Path(db_path).exists(), "dry-run must not create the db"
