#!/usr/bin/env python3
"""Stage 1 data-capability audit for the event-reaction short-duration research lane.

Read-only against consensus.db (never written to) and against the Schwab /
Finnhub live APIs, with a bounded number of calls. Writes raw API responses to
/tmp/event-reaction-audit/ (gitignored scratch, outside the repo's tracked
tree) and prints a JSON summary to stdout that the caller redirects to
data-capability-audit.json.

Covers audit items 1, 2, 3, 4, 6, 7 mechanically. Items 5 (event-ness spot
check) and 8 (per-lane event-count judgement) are written by hand into the
narrative .md after reading the cached raw JSON this script produces.

Usage: python3 scripts/research/audit_data_capability.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine import config as cfg  # noqa: E402
from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
SCRATCH = Path("/tmp/event-reaction-audit")
SCRATCH.mkdir(exist_ok=True)

PRICE_TICKERS = ["SPY", "AAPL", "MU", "ROKU", "MRNA", "VRTX", "IONQ", "GME"]
NEWS_TICKERS = ["AAPL", "MRNA", "ROKU", "GME"]

TODAY = datetime.now(PT).date()
MONTH_WINDOWS = [
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
    ("2026-08-01", TODAY.isoformat()),
]

FINNHUB_KEY = cfg.get_api_key("finnhub")


# ---------------------------------------------------------------------------
# Item 1 + 2: Schwab extended-hours price history reach, missing-bar rate,
# and 30m-vs-sum-of-1m volume cross-check.
# ---------------------------------------------------------------------------
def audit_price_history() -> dict:
    out = {}
    for ticker in PRICE_TICKERS:
        print(f"[price] {ticker} ...", file=sys.stderr)
        ticker_out = {}
        frames = {}
        for interval in ["1m", "5m", "30m"]:
            try:
                df = schwab_client.get_price_history(
                    ticker, interval=interval,
                    start=datetime.now(ET) - timedelta(days=400),
                    end=datetime.now(ET),
                    extended_hours=True,
                )
            except Exception as e:
                ticker_out[interval] = {"error": f"{type(e).__name__}: {e}"}
                continue
            if df is None or df.empty:
                ticker_out[interval] = {"error": "no data returned"}
                continue
            frames[interval] = df
            oldest = df.index.min()
            newest = df.index.max()
            # Premarket window 06:00-06:29 Pacific == 09:00-09:29 Eastern.
            pt_idx = df.index.tz_convert(PT)
            premkt = df[(pt_idx.time >= datetime(2000, 1, 1, 6, 0).time()) &
                        (pt_idx.time <= datetime(2000, 1, 1, 6, 29, 59).time())]
            trading_days = sorted({d.date() for d in premkt.index.tz_convert(PT)})
            recent_days = trading_days[-20:] if len(trading_days) >= 20 else trading_days
            expected = {"1m": 30, "5m": 6, "30m": 1}[interval]
            day_counts = []
            for d in recent_days:
                day_bars = premkt[premkt.index.tz_convert(PT).map(lambda ts: ts.date()) == d]
                day_counts.append(len(day_bars))
            total_expected = expected * len(recent_days)
            total_actual = sum(day_counts)
            missing_rate = (
                1.0 - (total_actual / total_expected) if total_expected else None
            )
            ticker_out[interval] = {
                "oldest_bar_pacific": oldest.tz_convert(PT).isoformat(),
                "newest_bar_pacific": newest.tz_convert(PT).isoformat(),
                "recent_premarket_trading_days_sampled": len(recent_days),
                "expected_bars_per_day_in_0600_0629_PT": expected,
                "total_expected_bars": total_expected,
                "total_actual_bars": total_actual,
                "missing_bar_rate": round(missing_rate, 4) if missing_rate is not None else None,
            }
            time.sleep(0.3)

        # Item 2: 30m bar volume vs sum of 1m bars, per recent ticker-day.
        vol_checks = []
        if "1m" in frames and "30m" in frames:
            df1 = frames["1m"]
            df30 = frames["30m"]
            pt1 = df1.index.tz_convert(PT)
            pt30 = df30.index.tz_convert(PT)
            days30 = sorted({d.date() for d in pt30 if
                             d.time() >= datetime(2000, 1, 1, 6, 0).time() and
                             d.time() <= datetime(2000, 1, 1, 6, 29, 59).time()})[-10:]
            for d in days30:
                bar30 = df30[(pt30.map(lambda ts: ts.date()) == d) &
                             (pt30.time == datetime(2000, 1, 1, 6, 0).time())]
                bars1 = df1[(pt1.map(lambda ts: ts.date()) == d) &
                            (pt1.time >= datetime(2000, 1, 1, 6, 0).time()) &
                            (pt1.time <= datetime(2000, 1, 1, 6, 29, 59).time())]
                if bar30.empty:
                    continue
                v30 = float(bar30["Volume"].iloc[0])
                v1sum = float(bars1["Volume"].sum())
                vol_checks.append({
                    "date": d.isoformat(),
                    "vol_30m_bar": v30,
                    "sum_of_1m_bars": v1sum,
                    "n_1m_bars_found": len(bars1),
                    "match": v30 == v1sum,
                    "diff": v30 - v1sum,
                })
        ticker_out["volume_cross_check_30m_vs_sum_1m"] = vol_checks
        out[ticker] = ticker_out
    return out


# ---------------------------------------------------------------------------
# Item 3 + 4: Finnhub company-news coverage + duplicate rate.
# ---------------------------------------------------------------------------
def _normalize_headline(h: str) -> str:
    return "".join(c.lower() for c in h if c.isalnum() or c.isspace()).split()


def audit_news_coverage() -> dict:
    if not FINNHUB_KEY:
        return {"error": "FINNHUB_API_KEY not set — no calls made"}
    out = {}
    all_rows_cache = {}
    for ticker in NEWS_TICKERS:
        out[ticker] = {}
        all_rows_cache[ticker] = []
        for (frm, to) in MONTH_WINDOWS:
            month_key = frm[:7]
            print(f"[news] {ticker} {month_key} ...", file=sys.stderr)
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={"symbol": ticker, "from": frm, "to": to, "token": FINNHUB_KEY},
                    timeout=15,
                )
                if resp.status_code != 200:
                    out[ticker][month_key] = {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                    continue
                rows = resp.json()
                if not isinstance(rows, list):
                    out[ticker][month_key] = {"error": f"unexpected body: {str(rows)[:200]}"}
                    continue
                out[ticker][month_key] = {
                    "row_count": len(rows),
                    "near_cap_flag": len(rows) >= 245,
                }
                all_rows_cache[ticker].extend(rows)
            except Exception as e:
                out[ticker][month_key] = {"error": f"{type(e).__name__}: {e}"}
            time.sleep(0.5)

        # Cache raw rows for manual item-5 spot check + item-4 dedup below.
        cache_path = SCRATCH / f"news_{ticker}.json"
        with open(cache_path, "w") as f:
            json.dump(all_rows_cache[ticker], f)

        # Item 4: dedup — same normalized headline, or same headline within 2h.
        rows = all_rows_cache[ticker]
        seen = {}
        dup_count = 0
        for r in rows:
            headline = (r.get("headline") or "").strip()
            ts = r.get("datetime", 0)
            norm = " ".join(_normalize_headline(headline))
            key = norm
            if key in seen and any(abs(ts - t) <= 7200 for t in seen[key]):
                dup_count += 1
            seen.setdefault(key, []).append(ts)
        total = len(rows)
        out[ticker]["dedup"] = {
            "total_rows_across_window": total,
            "near_duplicate_rows": dup_count,
            "near_duplicate_rate": round(dup_count / total, 4) if total else None,
        }
    return out


# ---------------------------------------------------------------------------
# Item 6: earnings-calendar field point-in-time-ness.
# ---------------------------------------------------------------------------
def audit_earnings_calendar() -> dict:
    if not FINNHUB_KEY:
        return {"error": "FINNHUB_API_KEY not set — no calls made"}
    out = {}
    # (a) /calendar/earnings over a window straddling a known-past earnings date.
    frm = "2026-04-01"
    to = "2026-04-30"
    print("[earnings] /calendar/earnings 2026-04 window ...", file=sys.stderr)
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": frm, "to": to, "token": FINNHUB_KEY},
            timeout=15,
        )
        cal = resp.json().get("earningsCalendar", []) if resp.status_code == 200 else []
        out["calendar_endpoint"] = {
            "window": [frm, to],
            "row_count": len(cal),
            "sample_row": cal[0] if cal else None,
            "fields_present": sorted(cal[0].keys()) if cal else [],
        }
    except Exception as e:
        out["calendar_endpoint"] = {"error": f"{type(e).__name__}: {e}"}
    time.sleep(0.5)

    # (b) /stock/earnings per-ticker EPS history — check whether old-quarter
    # `estimate` values look frozen (no way to prove without a stored
    # snapshot; report what's returned and flag the gap explicitly).
    for ticker in ["AAPL", "MRNA"]:
        print(f"[earnings] /stock/earnings {ticker} ...", file=sys.stderr)
        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/stock/earnings",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=15,
            )
            data = resp.json() if resp.status_code == 200 else []
            out[f"stock_earnings_{ticker}"] = {
                "row_count": len(data) if isinstance(data, list) else 0,
                "fields_present": sorted(data[0].keys()) if data else [],
                "sample_rows": data[:3] if isinstance(data, list) else data,
            }
        except Exception as e:
            out[f"stock_earnings_{ticker}"] = {"error": f"{type(e).__name__}: {e}"}
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------------------
# Item 7: FDA/clinical-event calendar coverage.
# ---------------------------------------------------------------------------
def audit_fda_coverage() -> dict:
    # No dedicated FDA/clinical-event API client exists in consensus_engine/
    # (verified: grep -rli "fda" only hits catalyst-label keyword lists and a
    # ticker false-positive guard, no HTTP client). Report that finding plus
    # how many of the already-pulled MRNA/VRTX-adjacent news rows carry an
    # FDA-pattern headline, as the closest thing the project currently has.
    cache_path = SCRATCH / "news_MRNA.json"
    fda_hits = 0
    total = 0
    if cache_path.exists():
        rows = json.loads(cache_path.read_text())
        total = len(rows)
        patterns = ["fda approv", "fda clear", "drug approv", "fda reject", "fda deny", "clinical fail", "pdufa", "advisory committee"]
        for r in rows:
            text = ((r.get("headline") or "") + " " + (r.get("summary") or "")).lower()
            if any(p in text for p in patterns):
                fda_hits += 1
    return {
        "dedicated_fda_calendar_client": False,
        "note": "grep -rli 'fda' across consensus_engine/ finds only catalyst-label "
                "keyword lists (news.py's _CATALYST_PATTERNS) and a ticker-collision "
                "guard (utils/tickers.py) — no HTTP client for an FDA advisory-committee "
                "or PDUFA calendar exists anywhere in the codebase.",
        "closest_existing_mechanism": "keyword match on Finnhub/Google-RSS/Brave "
                                       "headline+summary text against FDA-shaped phrases",
        "mrna_news_rows_sampled": total,
        "mrna_news_rows_fda_pattern_hit": fda_hits,
        "ticker_mapping_success_rate": "N/A — no dedicated source to map from",
    }


def main():
    result = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "item1_and_2_price_history": audit_price_history(),
        "item3_and_4_news_coverage": audit_news_coverage(),
        "item6_earnings_calendar": audit_earnings_calendar(),
        "item7_fda_coverage": audit_fda_coverage(),
    }
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
