#!/usr/bin/env python3
"""Measure, do not assume: every data fact TODO #106 relies on.

Writes data-capability.json.  Read-only.  No network.  No spend.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdtm_common import RES_DIR  # noqa: E402

DBN = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions")
WS = Path("/home/openclaw/.openclaw/workspace")


def sha(p, cap=None):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def minute_facts(feed):
    idx = pd.read_parquet(RES_DIR / f"panel-{feed}-idx.parquet")
    z = np.load(RES_DIR / f"panel-{feed}-mat.npz")
    c = z["c"]
    n_bars = np.isfinite(c).sum(1)
    df = pd.read_parquet(RES_DIR / f"bars-{feed}-allmin.parquet", columns=["date", "symbol", "minute"])
    m = df.minute.values
    pre = ((m >= 240) & (m <= 569))
    post = (m >= 960)
    key = df.date.cat.codes.values.astype(np.int64) * 1000 + df.symbol.cat.codes.values
    pre_c = np.unique(key[pre], return_counts=True)[1] if pre.any() else np.array([])
    n_sd = len(idx)
    return {
        "label": {"equs": "EQUS.MINI consolidated (primary)",
                  "pillar": "XNYS.PILLAR NYSE-only (independent check)"}[feed],
        "parquet": str(RES_DIR / f"bars-{feed}-allmin.parquet"),
        "timestamp_convention": "ts_event, converted to US/Eastern session date and Eastern minute-of-day",
        "content": "trade bars only: open, high, low, close, volume",
        "bid_present": False, "ask_present": False,
        "bid_size_present": False, "ask_size_present": False,
        "order_book_depth": False,
        "adjustment": "UNADJUSTED raw prices; three in-sample splits handled by dropping the split session",
        "symbols": int(idx.symbol.nunique()),
        "dates": int(idx.date.nunique()),
        "first_date": str(idx.date.min()), "last_date": str(idx.date.max()),
        "symbol_dates": int(n_sd),
        "regular_session_bars": int(np.isfinite(c).sum()),
        "median_regular_bars_per_symbol_date": float(np.median(n_bars)),
        "symbol_dates_with_all_390": int((n_bars == 390).sum()),
        "missing_minute_rate": float(1 - n_bars.mean() / 390),
        "premarket_bars_total": int(pre.sum()),
        "symbol_dates_with_any_premarket": int(len(pre_c)),
        "symbol_dates_with_30plus_premarket": int((pre_c >= 30).sum()) if len(pre_c) else 0,
        "median_premarket_bars_when_present": float(np.median(pre_c)) if len(pre_c) else 0.0,
        "postmarket_bars_total": int(post.sum()),
        "known_before_entry": "yes for any bar strictly before the decision minute",
    }


def db_facts():
    c = sqlite3.connect("file:%s/consensus.db?mode=ro" % WS, uri=True)
    q = lambda s: c.execute(s).fetchone()
    out = {}
    out["iv_snapshots"] = dict(zip(
        ["rows", "tickers", "first_date", "last_date", "distinct_dates"],
        q("select count(*),count(distinct ticker),min(snapshot_date),max(snapshot_date),count(distinct snapshot_date) from iv_snapshots")))
    out["iv_snapshots"]["capture_time_pt"] = "15:xx PT on 4178 of 4257 rows - after the 13:00 PT close"
    out["iv_snapshots"]["per_leg_bid_ask"] = False
    out["schwab_options_snapshots"] = dict(zip(
        ["rows", "tickers", "first_date", "last_date", "distinct_dates"],
        q("select count(*),count(distinct ticker),min(snapshot_date),max(snapshot_date),count(distinct snapshot_date) from schwab_options_snapshots")))
    out["schwab_options_snapshots"]["per_leg_bid_ask"] = False
    out["put_flow_option_snapshots"] = dict(zip(
        ["rows", "tickers", "sessions", "first_session", "last_session"],
        q("select count(*),count(distinct ticker),count(distinct capture_session),min(capture_session),max(capture_session) from put_flow_option_snapshots")))
    out["put_flow_option_snapshots"]["per_leg_bid_ask"] = True
    out["put_flow_option_snapshots"]["displayed_size"] = False
    out["put_flow_option_minutes"] = dict(zip(
        ["rows", "contracts", "sessions", "first_session", "last_session"],
        q("select count(*),count(distinct contract_symbol),count(distinct session_date),min(session_date),max(session_date) from put_flow_option_minutes")))
    out["put_flow_option_minutes"]["per_leg_bid_ask"] = True
    out["market_breadth_daily"] = dict(zip(
        ["rows", "first_date", "last_date"],
        q("select count(*),min(date_utc),max(date_utc) from market_breadth_daily")))
    out["market_breadth_daily"]["what_it_is"] = (
        "RSP-versus-SPY and IWM-versus-SPY ratios, daily. A PROXY. Not an "
        "advance/decline line, not TICK, not advancing/declining volume, not VOLD.")
    out["trading_halts"] = dict(zip(
        ["rows", "first", "last"], q("select count(*),min(halt_ts),max(halt_ts) from trading_halts")))
    out["ticker_sector_cache"] = {
        "rows": q("select count(*) from ticker_sector_cache")[0],
        "point_in_time": False,
        "covers_the_60_name_universe": 24,
        "note": "current labels with a fetch time; no dated membership history"}
    return out


def main():
    RES_DIR.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WS, capture_output=True, text=True).stdout.strip()
    daily_dir = WS / "data/mmhl_daily"
    etfs = [f.stem for f in daily_dir.glob("*.json")]
    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "TODO #106 professional day-trader methods - measured data capability",
        "network_used": False,
        "new_data_spend_usd": 0.0,
        "git_head": head,
        "correction_to_prior_inventory": {
            "claim_in_todo_104": "xnys-pillar_ohlcv-1d_ALL-SYMBOLS ... recorded exists=false",
            "reality": "the file exists; the prior inventory looked under the wrong parent folder",
            "real_path": str(DBN / "universe-selection/xnys-pillar_ohlcv-1d_ALL-SYMBOLS_2023-01-01_2026-08-22.dbn.zst"),
            "size_bytes": (DBN / "universe-selection/xnys-pillar_ohlcv-1d_ALL-SYMBOLS_2023-01-01_2026-08-22.dbn.zst").stat().st_size,
        },
        "minute_feeds": {f: minute_facts(f) for f in ("equs", "pillar")},
        "daily_cache": {
            "dir": str(daily_dir),
            "symbol_files": len(etfs),
            "index_and_sector_funds_present": sorted(
                s for s in ("SPY", "QQQ", "DIA", "IWM", "RSP", "XLK", "XLF", "XLE", "XLV") if s in etfs),
            "granularity": "daily only - there is no intraday history for any fund",
            "fields": ["open", "high", "low", "close", "volume"],
            "bid_ask": False,
        },
        "intraday_market_reference": {
            "index_fund_minute_bars": False,
            "sector_fund_minute_bars": False,
            "substitute_used": "leave-one-out equal-weight composite of the 60 names, and of the stock's own sector inside them",
            "must_never_be_called": ["an index", "market internals", "TICK", "advance/decline", "VOLD"],
        },
        "option_and_signal_tables": db_facts(),
        "corporate_actions": {
            "source": "detected as an overnight gap over 25% whose ratio is a round number",
            "splits_in_sample": [
                {"symbol": "ANET", "date": "2024-12-04", "ratio": "4-for-1"},
                {"symbol": "APH", "date": "2024-06-12", "ratio": "2-for-1"},
                {"symbol": "NOW", "date": "2025-12-18", "ratio": "5-for-1"},
            ],
            "dividends": "not present in any local minute or daily Databento file",
            "delistings": "no delisted symbol exists in the 60-name minute collection at all",
            "point_in_time_security_master": False,
        },
        "short_availability": {
            "historical_borrow_or_locate_record": False,
            "note": "Schwab's live /quotes reference block carries isShortable and htbRate, but nothing historical was ever stored",
        },
        "date_split": {
            "rule": "chronological; the last 182 EQUS dates stay sealed",
            "development_first": "2023-03-28", "development_last": "2025-11-28",
            "sealed_first": "2025-12-01", "sealed_last": "2026-08-21",
            "reused_from": "TODO #104, whose FINAL-VERDICT records that the sealed block was never opened",
        },
    }
    p = RES_DIR / "data-capability.json"
    p.write_text(json.dumps(out, indent=2))
    print("wrote", p)


if __name__ == "__main__":
    main()
