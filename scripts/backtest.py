#!/usr/bin/env python3
"""Walk-forward backtest — replay decision_snapshots against actual price outcomes.

Pulls decision_snapshots from the SQLite DB, fetches any missing price outcomes
via yfinance, then computes per-horizon accuracy, calibration (reliability diagram),
and a contradiction-index-vs-accuracy curve.

Outputs:
  - JSON summary printed to stdout
  - Markdown report written to .omc/research/backtest_<timestamp>.md

Usage:
    python3 scripts/backtest.py [--lookback-days N] [--db PATH] [--dry-run]
"""

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure workspace is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backtest")

ALERT_LABELS = {"STRONG_ALERT", "WATCHLIST"}


# ---------------------------------------------------------------------------
# yfinance price fetching (blocking — called via executor)
# ---------------------------------------------------------------------------

def _fetch_price_yf(ticker: str, at_ts: float, horizon: str) -> Optional[float]:
    """Fetch the price at (at_ts + horizon_seconds) using yfinance history.

    Returns None on any error or if data isn't available.
    """
    horizon_sec = {"1h": 3600, "24h": 86400}.get(horizon, 3600)
    target_ts = at_ts + horizon_sec

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        # Pull recent daily history — enough to cover the target date
        days_back = max(int((time.time() - at_ts) / 86400) + 5, 10)
        hist = stock.history(period=f"{days_back}d", interval="1d")
        if hist is None or hist.empty:
            return None

        # Find the row closest to the target timestamp
        import pandas as pd
        target_dt = pd.Timestamp(target_ts, unit="s", tz="UTC")
        closes = hist["Close"].dropna()
        if closes.empty:
            return None

        # Pick the row on or after target_dt
        closes_utc = closes.copy()
        closes_utc.index = closes_utc.index.tz_convert("UTC")
        after = closes_utc[closes_utc.index >= target_dt]
        if after.empty:
            return float(closes_utc.iloc[-1])
        return float(after.iloc[0])
    except Exception as e:
        log.debug("yfinance price fetch failed for %s @%s horizon=%s: %s", ticker, at_ts, horizon, e)
        return None


# ---------------------------------------------------------------------------
# Accuracy stats helpers
# ---------------------------------------------------------------------------

def _accuracy_stats(rows: list[dict], horizon: str) -> dict:
    """Compute win-rate accuracy for ALERT decisions at a given horizon."""
    price_col = f"outcome_price_{horizon.replace('h', 'h').replace('24h', '24h')}"
    # normalise to "outcome_price_1h" or "outcome_price_24h"
    price_col = "outcome_price_1h" if horizon == "1h" else "outcome_price_24h"

    alert_rows = [r for r in rows if r["decision"] in ALERT_LABELS]
    labeled = [
        r for r in alert_rows
        if r["outcome_price_at_alert"] and r[price_col]
        and r["outcome_price_at_alert"] > 0 and r[price_col] > 0
    ]
    if not labeled:
        return {"horizon": horizon, "n": 0, "wins": 0, "accuracy": None, "avg_pnl_pct": None}

    wins = sum(1 for r in labeled if r[price_col] > r["outcome_price_at_alert"])
    pnls = [
        (r[price_col] - r["outcome_price_at_alert"]) / r["outcome_price_at_alert"] * 100
        for r in labeled
    ]
    return {
        "horizon": horizon,
        "n": len(labeled),
        "wins": wins,
        "accuracy": round(wins / len(labeled) * 100, 2),
        "avg_pnl_pct": round(sum(pnls) / len(pnls), 3),
    }


def _calibration_data(rows: list[dict], horizon: str, n_bins: int = 5) -> list[dict]:
    """Reliability diagram data: bucket final_score into bins, compute actual win rate per bin."""
    price_col = "outcome_price_1h" if horizon == "1h" else "outcome_price_24h"
    labeled = [
        r for r in rows
        if r["outcome_price_at_alert"] and r[price_col]
        and r["outcome_price_at_alert"] > 0 and r[price_col] > 0
    ]
    if not labeled:
        return []

    bin_size = 100.0 / n_bins
    bins: dict[int, list[int]] = {i: [] for i in range(n_bins)}
    for r in labeled:
        score = float(r["final_score"])
        bin_idx = min(int(score / bin_size), n_bins - 1)
        bins[bin_idx].append(1 if r[price_col] > r["outcome_price_at_alert"] else 0)

    result = []
    for i in range(n_bins):
        low = i * bin_size
        high = (i + 1) * bin_size
        outcomes = bins[i]
        if not outcomes:
            continue
        result.append({
            "score_range": f"{low:.0f}-{high:.0f}",
            "n": len(outcomes),
            "win_rate": round(sum(outcomes) / len(outcomes) * 100, 2),
        })
    return result


def _contradiction_vs_accuracy(rows: list[dict], horizon: str, n_bins: int = 4) -> list[dict]:
    """Group rows by contradiction_index quartile, compute accuracy per group."""
    price_col = "outcome_price_1h" if horizon == "1h" else "outcome_price_24h"
    alert_rows = [
        r for r in rows
        if r["decision"] in ALERT_LABELS
        and r["outcome_price_at_alert"] and r[price_col]
        and r["outcome_price_at_alert"] > 0 and r[price_col] > 0
    ]
    if not alert_rows:
        return []

    # Sort by contradiction index
    alert_rows_sorted = sorted(alert_rows, key=lambda r: r["contradiction_index"] or 0.0)
    chunk = max(len(alert_rows_sorted) // n_bins, 1)
    result = []
    for i in range(0, len(alert_rows_sorted), chunk):
        group = alert_rows_sorted[i:i + chunk]
        if not group:
            continue
        contra_vals = [r["contradiction_index"] or 0.0 for r in group]
        outcomes = [1 if r[price_col] > r["outcome_price_at_alert"] else 0 for r in group]
        result.append({
            "contradiction_range": f"{min(contra_vals):.2f}-{max(contra_vals):.2f}",
            "n": len(group),
            "win_rate": round(sum(outcomes) / len(outcomes) * 100, 2),
        })
    return result


# ---------------------------------------------------------------------------
# Markdown report formatter
# ---------------------------------------------------------------------------

def _build_markdown(summary: dict) -> str:
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Walk-Forward Backtest Report",
        f"",
        f"**Generated:** {now_str}  ",
        f"**Lookback:** {summary['lookback_days']} days  ",
        f"**Snapshots loaded:** {summary['total_snapshots']}  ",
        f"**ALERT decisions:** {summary['total_alerts']}  ",
        f"**Note:** Win = price went up (long-only / direction-blind).  ",
        f"",
        f"---",
        f"",
        f"## Accuracy by Horizon",
        f"",
    ]

    for stat in summary["accuracy"]:
        h = stat["horizon"]
        if stat["n"] == 0:
            lines.append(f"**{h}:** No labeled data")
        else:
            acc = stat["accuracy"]
            pnl = stat["avg_pnl_pct"]
            sign = "+" if pnl and pnl >= 0 else ""
            lines.append(
                f"**{h}:** {acc:.1f}% win rate ({stat['wins']}/{stat['n']} alerts)"
                + (f" | avg P&L {sign}{pnl:.2f}%" if pnl is not None else "")
            )

    lines += ["", "---", "", "## Calibration (Reliability Diagram)", ""]

    for horizon in ("1h", "24h"):
        cal = summary["calibration"].get(horizon, [])
        if not cal:
            lines.append(f"**{horizon}:** No calibration data")
            continue
        lines.append(f"**{horizon}:**")
        lines.append("")
        lines.append("| Score Range | N | Win Rate |")
        lines.append("|---|---|---|")
        for b in cal:
            lines.append(f"| {b['score_range']} | {b['n']} | {b['win_rate']:.1f}% |")
        lines.append("")

    lines += ["---", "", "## Contradiction Index vs Accuracy", ""]

    for horizon in ("1h", "24h"):
        curve = summary["contradiction_curve"].get(horizon, [])
        if not curve:
            lines.append(f"**{horizon}:** No data")
            continue
        lines.append(f"**{horizon}:**")
        lines.append("")
        lines.append("| Contradiction Range | N | Win Rate |")
        lines.append("|---|---|---|")
        for row in curve:
            lines.append(f"| {row['contradiction_range']} | {row['n']} | {row['win_rate']:.1f}% |")
        lines.append("")

    lines += [
        "---",
        "",
        f"_Report generated by `scripts/backtest.py`_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main async runner
# ---------------------------------------------------------------------------

async def run_backtest(lookback_days: int, db_path: str, dry_run: bool) -> dict:
    """Load snapshots, fill missing prices, compute stats, write report."""
    from consensus_engine import config as cfg, db as dbmod

    # Override DB path if provided
    if db_path:
        cfg._config = cfg._config or {}
        cfg._config.setdefault("database", {})["path"] = db_path

    conn = await dbmod.init_db()

    cutoff = time.time() - lookback_days * 86400
    cursor = await conn.execute(
        """SELECT id, ticker, decision, final_score, contradiction_index,
                  sources_json, recorded_at,
                  outcome_price_at_alert, outcome_price_1h, outcome_price_24h
           FROM decision_snapshots
           WHERE recorded_at >= ?
           ORDER BY recorded_at DESC""",
        (cutoff,),
    )
    rows = [dict(r) for r in await cursor.fetchall()]

    if not rows:
        log.warning("No decision_snapshots found within the last %d days", lookback_days)

    log.info("Loaded %d decision_snapshots (last %d days)", len(rows), lookback_days)

    # Backfill missing price outcomes via yfinance
    import concurrent.futures
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="bt-yf")

    if not dry_run:
        for r in rows:
            if not r["outcome_price_at_alert"] or r["outcome_price_at_alert"] <= 0:
                continue
            for horizon, col in [("1h", "outcome_price_1h"), ("24h", "outcome_price_24h")]:
                if r[col] is None or r[col] <= 0:
                    price = await loop.run_in_executor(
                        executor, _fetch_price_yf, r["ticker"], r["recorded_at"], horizon
                    )
                    if price:
                        r[col] = price
                        await dbmod.update_snapshot_outcomes(r["id"], r["outcome_price_1h"], r["outcome_price_24h"])

    executor.shutdown(wait=False)

    # Compute stats
    total_alerts = sum(1 for r in rows if r["decision"] in ALERT_LABELS)
    accuracy_stats = [_accuracy_stats(rows, "1h"), _accuracy_stats(rows, "24h")]
    calibration = {
        "1h": _calibration_data(rows, "1h"),
        "24h": _calibration_data(rows, "24h"),
    }
    contradiction_curve = {
        "1h": _contradiction_vs_accuracy(rows, "1h"),
        "24h": _contradiction_vs_accuracy(rows, "24h"),
    }

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "lookback_days": lookback_days,
        "total_snapshots": len(rows),
        "total_alerts": total_alerts,
        "accuracy": accuracy_stats,
        "calibration": calibration,
        "contradiction_curve": contradiction_curve,
    }

    # Output JSON
    print(json.dumps(summary, indent=2))

    # Write markdown report
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = Path(".omc/research") / f"backtest_{ts}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_build_markdown(summary))
    log.info("Report written to %s", report_path)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest on decision_snapshots")
    parser.add_argument("--lookback-days", type=int, default=30, help="Days of history to include (default: 30)")
    parser.add_argument("--db", default="", help="Path to SQLite DB (default: from config)")
    parser.add_argument("--dry-run", action="store_true", help="Skip yfinance price backfill")
    args = parser.parse_args()

    asyncio.run(run_backtest(args.lookback_days, args.db, args.dry_run))


if __name__ == "__main__":
    main()
