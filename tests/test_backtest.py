"""Tests for scripts/backtest.py — walk-forward backtest on decision_snapshots."""
import json
import time
import pytest
from pathlib import Path

from consensus_engine import config as cfg, db


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    cfg._config["database"] = {"path": str(tmp_path / "bt.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# Helpers to seed synthetic snapshots
# ---------------------------------------------------------------------------

async def _seed_snapshots(rows: list[dict]) -> None:
    """Insert synthetic decision_snapshots directly."""
    conn = await db.get_db()
    now = time.time()
    for r in rows:
        await conn.execute(
            """INSERT INTO decision_snapshots
               (ticker, decision, final_score, contradiction_index, sources_json,
                recorded_at, outcome_price_at_alert, outcome_price_1h, outcome_price_24h)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r.get("ticker", "NVDA"),
                r.get("decision", "ALERT"),
                r.get("final_score", 70.0),
                r.get("contradiction_index", 0.1),
                r.get("sources_json", "[]"),
                r.get("recorded_at", now - 3600),
                r.get("outcome_price_at_alert"),
                r.get("outcome_price_1h"),
                r.get("outcome_price_24h"),
            ),
        )
    await conn.commit()


# ---------------------------------------------------------------------------
# Unit tests for stat helpers
# ---------------------------------------------------------------------------

def test_accuracy_stats_correct_win_rate():
    """_accuracy_stats computes win rate correctly from a synthetic row list."""
    from scripts.backtest import _accuracy_stats

    rows = [
        {"decision": "ALERT", "final_score": 75, "contradiction_index": 0.1,
         "outcome_price_at_alert": 100.0, "outcome_price_1h": 105.0, "outcome_price_24h": 108.0},
        {"decision": "ALERT", "final_score": 60, "contradiction_index": 0.2,
         "outcome_price_at_alert": 100.0, "outcome_price_1h": 98.0, "outcome_price_24h": 97.0},
        {"decision": "ALERT", "final_score": 80, "contradiction_index": 0.05,
         "outcome_price_at_alert": 50.0, "outcome_price_1h": 52.0, "outcome_price_24h": 53.0},
        {"decision": "IGNORE", "final_score": 30, "contradiction_index": 0.5,
         "outcome_price_at_alert": 100.0, "outcome_price_1h": 103.0, "outcome_price_24h": None},
    ]

    stats = _accuracy_stats(rows, "1h")
    assert stats["n"] == 3          # only ALERT rows
    assert stats["wins"] == 2       # rows 0 and 2 went up
    assert stats["accuracy"] == pytest.approx(66.67, abs=0.1)
    assert stats["avg_pnl_pct"] is not None


def test_accuracy_stats_no_data():
    """_accuracy_stats returns None accuracy when no labeled rows."""
    from scripts.backtest import _accuracy_stats

    rows = [{"decision": "ALERT", "final_score": 70, "contradiction_index": 0.1,
             "outcome_price_at_alert": None, "outcome_price_1h": None, "outcome_price_24h": None}]
    stats = _accuracy_stats(rows, "1h")
    assert stats["n"] == 0
    assert stats["accuracy"] is None


def test_calibration_data_buckets():
    """_calibration_data groups rows into score bins correctly."""
    from scripts.backtest import _calibration_data

    rows = []
    # 10 rows with score 80 — all winners (1h)
    for _ in range(10):
        rows.append({
            "decision": "ALERT", "final_score": 80, "contradiction_index": 0.1,
            "outcome_price_at_alert": 100.0, "outcome_price_1h": 105.0, "outcome_price_24h": 106.0,
        })
    # 10 rows with score 20 — all losers (1h)
    for _ in range(10):
        rows.append({
            "decision": "ALERT", "final_score": 20, "contradiction_index": 0.2,
            "outcome_price_at_alert": 100.0, "outcome_price_1h": 95.0, "outcome_price_24h": 94.0,
        })

    cal = _calibration_data(rows, "1h", n_bins=5)
    # Find the high-score bin (80 → bin 4: 80-100)
    high_bin = next((b for b in cal if "80" in b["score_range"]), None)
    assert high_bin is not None
    assert high_bin["win_rate"] == 100.0

    # Find the low-score bin (20 → bin 1: 20-40)
    low_bin = next((b for b in cal if b["score_range"].startswith("20")), None)
    assert low_bin is not None
    assert low_bin["win_rate"] == 0.0


def test_contradiction_vs_accuracy_curve():
    """_contradiction_vs_accuracy: low contradiction should have higher win rate."""
    from scripts.backtest import _contradiction_vs_accuracy

    rows = []
    # Low contradiction rows — winners
    for _ in range(10):
        rows.append({
            "decision": "ALERT", "final_score": 75, "contradiction_index": 0.05,
            "outcome_price_at_alert": 100.0, "outcome_price_1h": 103.0, "outcome_price_24h": 105.0,
        })
    # High contradiction rows — losers
    for _ in range(10):
        rows.append({
            "decision": "ALERT", "final_score": 75, "contradiction_index": 0.9,
            "outcome_price_at_alert": 100.0, "outcome_price_1h": 97.0, "outcome_price_24h": 96.0,
        })

    curve = _contradiction_vs_accuracy(rows, "1h", n_bins=2)
    assert len(curve) >= 1
    # First bucket (low contradiction) should have higher win rate than last bucket
    first_win_rate = curve[0]["win_rate"]
    last_win_rate = curve[-1]["win_rate"]
    assert first_win_rate > last_win_rate


def test_build_markdown_contains_sections():
    """_build_markdown produces markdown with all required sections."""
    from scripts.backtest import _build_markdown

    summary = {
        "generated_at": "2026-04-12T10:00:00Z",
        "lookback_days": 30,
        "total_snapshots": 100,
        "total_alerts": 45,
        "accuracy": [
            {"horizon": "1h", "n": 40, "wins": 28, "accuracy": 70.0, "avg_pnl_pct": 1.5},
            {"horizon": "24h", "n": 35, "wins": 22, "accuracy": 62.9, "avg_pnl_pct": 2.1},
        ],
        "calibration": {
            "1h": [{"score_range": "60-80", "n": 20, "win_rate": 70.0}],
            "24h": [],
        },
        "contradiction_curve": {
            "1h": [{"contradiction_range": "0.00-0.30", "n": 25, "win_rate": 76.0}],
            "24h": [],
        },
    }

    md = _build_markdown(summary)
    assert "# Walk-Forward Backtest Report" in md
    assert "Accuracy by Horizon" in md
    assert "Calibration" in md
    assert "Contradiction" in md
    assert "70.0%" in md
    assert "30 days" in md


# ---------------------------------------------------------------------------
# Integration test: run_backtest with synthetic DB data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_backtest_synthetic(test_db, tmp_path, monkeypatch):
    """run_backtest produces correct accuracy from synthetic snapshots."""
    from scripts.backtest import run_backtest

    # Seed 10 ALERT snapshots: 7 winners at 1h, 3 losers
    now = time.time()
    rows_to_seed = []
    for i in range(7):
        rows_to_seed.append({
            "ticker": "NVDA", "decision": "ALERT", "final_score": 75.0,
            "contradiction_index": 0.1, "sources_json": "[]",
            "recorded_at": now - 3600 * (i + 1),
            "outcome_price_at_alert": 100.0,
            "outcome_price_1h": 105.0,
            "outcome_price_24h": 107.0,
        })
    for i in range(3):
        rows_to_seed.append({
            "ticker": "TSLA", "decision": "ALERT", "final_score": 60.0,
            "contradiction_index": 0.4, "sources_json": "[]",
            "recorded_at": now - 3600 * (i + 8),
            "outcome_price_at_alert": 200.0,
            "outcome_price_1h": 195.0,
            "outcome_price_24h": 193.0,
        })
    await _seed_snapshots(rows_to_seed)

    # Monkeypatch the report output dir
    monkeypatch.chdir(tmp_path)
    Path(".omc/research").mkdir(parents=True, exist_ok=True)

    summary = await run_backtest(lookback_days=7, db_path="", dry_run=True)

    assert summary["total_snapshots"] == 10
    assert summary["total_alerts"] == 10

    acc_1h = next(s for s in summary["accuracy"] if s["horizon"] == "1h")
    assert acc_1h["n"] == 10
    assert acc_1h["wins"] == 7
    assert acc_1h["accuracy"] == pytest.approx(70.0)

    # Check markdown report was written
    reports = list(Path(".omc/research").glob("backtest_*.md"))
    assert len(reports) == 1
    content = reports[0].read_text()
    assert "70.0%" in content
