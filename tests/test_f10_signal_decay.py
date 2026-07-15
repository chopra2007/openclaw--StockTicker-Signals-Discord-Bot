"""F10 (#76 menu) — backtest-to-live decay tracker.

Builds a synthetic DB with an OLD (baseline) window and a RECENT (live) window,
then checks the tracker's verdicts:
  * a signal that used to hit 70% and now hits 20% -> DECAY
  * a stable signal with a large live sample -> OK
  * a signal with < min_live_n recent rows -> INSUFFICIENT
  * the options_flow_outcomes source (win_1d) is picked up
  * the table prints a raw ratio (no %) on a thin sample
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from scripts import signal_decay_check as dc

_NOW = time.time()
_DAY = 86400


def _mkdb(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE decision_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER, ticker TEXT,
            decision TEXT, final_score REAL, recorded_at REAL,
            outcome_price_at_alert REAL, outcome_price_1h REAL, outcome_price_24h REAL,
            outcome_price_5d REAL, outcome_price_20d REAL, feature_vector_json TEXT);
        CREATE TABLE alert_history (id INTEGER PRIMARY KEY AUTOINCREMENT, catalyst_type TEXT);
        CREATE TABLE options_flow_outcomes (
            flow_id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, market_date TEXT,
            detected_at REAL, entry_spot REAL, win_1d INTEGER, graded_at REAL);
        """
    )
    return conn


def _add_snaps(conn, decision, n, hit_rate, days_ago):
    ts = _NOW - days_ago * _DAY
    hits = int(round(n * hit_rate))
    for i in range(n):
        won = 1 if i < hits else 0
        conn.execute(
            "INSERT INTO decision_snapshots(ticker, decision, final_score, recorded_at, "
            "outcome_price_at_alert, outcome_price_24h) VALUES (?,?,?,?,?,?)",
            ("T", decision, 50.0, ts, 100.0, 110.0 if won else 90.0))


def _add_flow(conn, side, n, win_rate, days_ago):
    ts = _NOW - days_ago * _DAY
    wins = int(round(n * win_rate))
    for i in range(n):
        conn.execute(
            "INSERT INTO options_flow_outcomes(ticker, side, market_date, detected_at, "
            "entry_spot, win_1d, graded_at) VALUES (?,?,?,?,?,?,?)",
            ("T", side, "2026-07-01", ts, 100.0, 1 if i < wins else 0, ts))


@pytest.fixture
def dbs(tmp_path):
    live = str(tmp_path / "live.db")
    conn = _mkdb(live)
    # DECAY: 200 old rows at 70%, 40 recent at 20%
    _add_snaps(conn, "STRONG_ALERT", 200, 0.70, days_ago=180)
    _add_snaps(conn, "STRONG_ALERT", 40, 0.20, days_ago=5)
    # OK: 300 old at 50%, 300 recent at 50% (big live sample -> Wilson LB close to p)
    _add_snaps(conn, "WATCHLIST", 300, 0.50, days_ago=120)
    _add_snaps(conn, "WATCHLIST", 300, 0.50, days_ago=5)
    # INSUFFICIENT: enough to freeze (40 old) but only 20 recent (< min_live_n 30)
    _add_snaps(conn, "IGNORE", 40, 0.50, days_ago=120)
    _add_snaps(conn, "IGNORE", 20, 0.50, days_ago=5)
    # flow source
    _add_flow(conn, "CALL", 100, 0.45, days_ago=120)
    _add_flow(conn, "CALL", 100, 0.45, days_ago=5)
    conn.commit()
    conn.close()
    baselines = str(tmp_path / "baselines.db")
    return live, baselines


def test_freeze_writes_baselines(dbs):
    live, baselines = dbs
    written = dc.freeze_baselines(live, baselines, horizon="24h", source_label="stored-history")
    keys = {w["signal_key"] for w in written}
    assert "tier=STRONG_ALERT" in keys
    assert "tier=WATCHLIST" in keys
    assert "flow:side=CALL" in keys
    row = sqlite3.connect(baselines).execute(
        "SELECT baseline_rate, baseline_n FROM signal_baselines WHERE signal_key='tier=STRONG_ALERT'"
    ).fetchone()
    # 200*.70 + 40*.20 = 148 hits over 240 -> ~0.617
    assert row[1] == 240
    assert 0.60 < row[0] < 0.63


def test_compare_verdicts(dbs):
    live, baselines = dbs
    dc.freeze_baselines(live, baselines, horizon="24h", source_label="stored-history")
    results = {r["signal_key"]: r for r in dc.compare(
        live, baselines, lookback_days=60, tolerance=0.10, min_live_n=30)}
    assert results["tier=STRONG_ALERT"]["verdict"] == "DECAY"
    assert results["tier=WATCHLIST"]["verdict"] == "OK"
    assert results["tier=IGNORE"]["verdict"] == "INSUFFICIENT"
    # flow picked up and evaluated (win_1d horizon)
    assert "flow:side=CALL" in results


def test_thin_live_sample_is_insufficient_not_a_number(dbs):
    live, baselines = dbs
    dc.freeze_baselines(live, baselines, horizon="24h", source_label="stored-history")
    results = dc.compare(live, baselines, lookback_days=60, tolerance=0.10, min_live_n=30)
    ins = next(r for r in results if r["signal_key"] == "tier=IGNORE")
    assert ins["live_wlb"] is None  # no Wilson LB computed on a thin sample
    table = dc.format_table(results)
    # the thin row shows a raw ratio and n/a, never a fabricated Wilson number
    assert "20/20" not in table  # live_n=20 recent IGNORE rows -> "10/20"
    assert "n/a" in table


def test_no_baselines_message():
    assert "No baselines found" in dc.format_table([])
