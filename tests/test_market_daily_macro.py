"""r22 (macro-fred) — build_macro_rows producer tests (scripts/market_daily.py).

Fills the pre-existing descriptive F4 shell (macro_legs_daily) from FRED daily series.
DESCRIPTIVE/shadow ONLY — never wired into cross_asset (E2).

Coverage:
  * all-legs row: curve_t10y2y/curve_t10y3m/real_yield_10y populated, dxy_roc computed,
    non-NULL macro_multiplier inside the bounds, legs_used_json lists the survivors, and
    the yfinance-ETF columns (copper_gold_roc/semis_rs/cyc_def_div) are left NULL.
  * drop-None + clamp discipline: an unavailable leg (too little history) is dropped, not
    averaged in — macro_multiplier still non-NULL from the surviving leg.
  * no FRED data at all -> no row.
  * seed() writes the row (incl. real_yield_10y, NULL ETF cols) into a temp db.
  * _ensure_schema defensively adds real_yield_10y to a pre-existing (v21) table.

All FRED calls are mocked via md._fetch_fred_obs — no live network.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import scripts.market_daily as md  # noqa: E402

_TODAY = "2026-07-08"


def _full_fred(series_id: str, limit: int):
    """Mocked FRED: enough history on every series so both ROC legs survive."""
    if series_id == "T10Y2Y":
        return [(_TODAY, 0.45), ("2026-07-07", 0.44)]
    if series_id == "T10Y3M":
        return [(_TODAY, 0.80), ("2026-07-07", 0.79)]
    if series_id == "DTWEXBGS":
        obs = [(_TODAY, 100.0)] + [("2026-06-15", 99.0)] * 20 + [("2026-06-01", 98.0)]
        return obs  # newest-first; value 21 obs ago = 98.0 -> roc = 100/98 - 1
    if series_id == "DFII10":
        obs = [(_TODAY, 2.10)] + [("2026-06-15", 2.05)] * 20 + [("2026-06-01", 2.00)]
        return obs  # value 21 obs ago = 2.00 -> roc = 2.10/2.00 - 1 = 0.05
    return []


def test_all_legs_row(monkeypatch):
    monkeypatch.setattr(md, "_fetch_fred_obs", _full_fred)
    rows = md.build_macro_rows()
    assert len(rows) == 1
    r = rows[0]

    assert r["date_utc"] == _TODAY
    assert r["curve_t10y2y"] == pytest.approx(0.45)
    assert r["curve_t10y3m"] == pytest.approx(0.80)
    assert r["real_yield_10y"] == pytest.approx(2.10)
    assert r["dxy_roc"] == pytest.approx(100.0 / 98.0 - 1.0, abs=1e-9)

    # macro_multiplier is non-NULL and inside the descriptive bounds
    assert r["macro_multiplier"] is not None
    assert md._MACRO_FLOOR <= r["macro_multiplier"] <= md._MACRO_CEIL
    # both directional legs survived
    assert json.loads(r["legs_used_json"]) == ["dxy_roc", "real_yield_roc"]

    # yfinance-ETF-derived columns are out of r22's FRED scope -> NULL
    assert r["copper_gold_roc"] is None
    assert r["semis_rs"] is None
    assert r["cyc_def_div"] is None


def test_drop_none_then_clamp(monkeypatch):
    """DTWEXBGS returns too little history -> dxy_roc None -> dropped (not averaged in as
    1.0). macro_multiplier is still non-NULL, computed from the surviving real_yield leg."""
    def _partial(series_id, limit):
        if series_id == "DTWEXBGS":
            return [(_TODAY, 100.0)]  # < window+1 -> ROC None
        return _full_fred(series_id, limit)

    monkeypatch.setattr(md, "_fetch_fred_obs", _partial)
    rows = md.build_macro_rows()
    assert len(rows) == 1
    r = rows[0]

    assert r["dxy_roc"] is None
    assert json.loads(r["legs_used_json"]) == ["real_yield_roc"]
    # single surviving leg: 1 - 0.05*_MACRO_RY_K
    expected = 1.0 - 0.05 * md._MACRO_RY_K
    assert r["macro_multiplier"] == pytest.approx(expected, abs=1e-9)
    assert r["real_yield_10y"] == pytest.approx(2.10)


def test_no_fred_data_returns_empty(monkeypatch):
    monkeypatch.setattr(md, "_fetch_fred_obs", lambda s, n: [])
    assert md.build_macro_rows() == []


def test_seed_writes_macro_row(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "_fetch_fred_obs", _full_fred)
    macro_rows = md.build_macro_rows()

    db_path = str(tmp_path / "macro.db")
    conn = md._connect(db_path)
    try:
        md._ensure_schema(conn)
        md.seed(conn, [], [], [], None, macro_rows)
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        got = conn.execute("SELECT * FROM macro_legs_daily").fetchall()
        assert len(got) == 1
        row = got[0]
        assert row["date_utc"] == _TODAY
        assert row["macro_multiplier"] is not None
        assert row["real_yield_10y"] == pytest.approx(2.10)
        assert row["curve_t10y2y"] == pytest.approx(0.45)
        assert json.loads(row["legs_used_json"]) == ["dxy_roc", "real_yield_roc"]
        # NULL ETF-derived columns
        assert row["copper_gold_roc"] is None
        assert row["semis_rs"] is None
        assert row["cyc_def_div"] is None
    finally:
        conn.close()


def test_ensure_schema_adds_real_yield_to_legacy_table(tmp_path):
    """A pre-existing (schema v21) macro_legs_daily lacks real_yield_10y; _ensure_schema
    must add it defensively so the plain-sqlite3 producer can INSERT it on the live db."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    try:
        # v21 DDL (no real_yield_10y column)
        conn.execute(
            """CREATE TABLE macro_legs_daily (
                   date_utc TEXT PRIMARY KEY,
                   copper_gold_roc REAL, dxy_roc REAL, semis_rs REAL, cyc_def_div REAL,
                   curve_t10y2y REAL, curve_t10y3m REAL,
                   macro_multiplier REAL NOT NULL, legs_used_json TEXT,
                   computed_at REAL NOT NULL)"""
        )
        conn.commit()
        cols_before = {r[1] for r in conn.execute("PRAGMA table_info(macro_legs_daily)").fetchall()}
        assert "real_yield_10y" not in cols_before

        md._ensure_schema(conn)

        cols_after = {r[1] for r in conn.execute("PRAGMA table_info(macro_legs_daily)").fetchall()}
        assert "real_yield_10y" in cols_after
    finally:
        conn.close()
