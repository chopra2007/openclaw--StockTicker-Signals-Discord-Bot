#!/usr/bin/env python3
"""Offline replay harness for the E2 cross-asset multiplier.

Reads consensus.db alert_history (read-only), fetches per-date VIX/VIX3M close
ratio (yfinance) and FRED HY credit OAS ratio (FRED API), applies the same
_ratio_to_multiplier logic used in production, and reports how many alerts would
cross/uncross the STRONG_ALERT threshold (high_confidence=80) under each leg and
combined — tabulated separately for calm vs stressed dates.

Stressed dates: VIX term-structure in backwardation (ratio > 1.0) OR credit
spreads wider than baseline (credit ratio > 1.0). Calm dates: both legs contango/
tighter (both ratios < 1.0) or only one leg available and it reads calm.

Usage:
  python3 scripts/backtest_e2_cross_asset.py

Results are written to .claude/discover/todo-sweep-2026-06-24/e2-replay-result.md
and also printed to stdout.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent / "consensus.db"
RESULT_PATH = (
    Path(__file__).parent.parent
    / ".claude/discover/todo-sweep-2026-06-24/e2-replay-result.md"
)
CACHE_PATH = Path("/tmp/e2_replay_cache.json")

VETO_FLOOR = 0.85
CONFIRM_CEILING = 1.15
HIGH_CONFIDENCE = 80          # STRONG_ALERT threshold
FRED_SERIES = "BAMLH0A0HYM2"  # ICE BofA US HY OAS (daily, % pts)
FRED_BASELINE_DAYS = 60
FRED_MIN_DAYS = 20
VIX_SWING = 0.15
CREDIT_SWING = 0.40

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("e2_replay")

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception as exc:
        log.warning("Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Multiplier math (mirrors cross_asset._ratio_to_multiplier exactly)
# ---------------------------------------------------------------------------


def _ratio_to_multiplier(ratio: float, reference_swing: float = VIX_SWING) -> float:
    upside = CONFIRM_CEILING - 1.0
    downside = 1.0 - VETO_FLOOR
    delta = 1.0 - ratio
    if delta >= 0:
        scale = upside / reference_swing
    else:
        scale = downside / reference_swing
    raw = 1.0 + delta * scale
    return max(VETO_FLOOR, min(CONFIRM_CEILING, raw))


# ---------------------------------------------------------------------------
# VIX term-structure: per-date close fetch (yfinance)
# ---------------------------------------------------------------------------


def _fetch_vix_ratio_for_date(d: date, cache: dict) -> Optional[float]:
    """Return VIX/VIX3M close ratio for date d, using cache to avoid re-fetching."""
    key = f"vix:{d}"
    if key in cache:
        v = cache[key]
        return None if v == "none" else float(v)

    try:
        import yfinance as yf
        # Fetch a 5-day window ending the day after d so market-close data is included
        start = d - timedelta(days=5)
        end = d + timedelta(days=2)
        vix = yf.Ticker("^VIX").history(start=start.isoformat(), end=end.isoformat())
        vix3m = yf.Ticker("^VIX3M").history(start=start.isoformat(), end=end.isoformat())

        if vix.empty or vix3m.empty:
            cache[key] = "none"
            return None

        # Find the row on or just before d
        def _closest_close(hist, target_date: date) -> Optional[float]:
            for idx in reversed(hist.index):
                idx_date = idx.date() if hasattr(idx, "date") else idx
                if idx_date <= target_date:
                    return float(hist.loc[idx, "Close"])
            return None

        v = _closest_close(vix, d)
        v3 = _closest_close(vix3m, d)
        if v is None or v3 is None or v3 <= 0:
            cache[key] = "none"
            return None

        ratio = v / v3
        cache[key] = str(ratio)
        return ratio
    except Exception as exc:
        log.debug("VIX fetch error for %s: %s", d, exc)
        cache[key] = "none"
        return None


# ---------------------------------------------------------------------------
# FRED HY credit: fetch rolling window ending each date
# ---------------------------------------------------------------------------


def _fetch_fred_obs(fred_key: str, cache: dict) -> Optional[list]:
    """Fetch all FRED observations for BAMLH0A0HYM2 (once, cached globally)."""
    cache_key = f"fred_all:{FRED_SERIES}"
    if cache_key in cache:
        raw = cache[cache_key]
        if raw == "none":
            return None
        return raw

    try:
        q = urllib.parse.urlencode({
            "series_id": FRED_SERIES,
            "api_key": fred_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": "10000",
        })
        url = f"https://api.stlouisfed.org/fred/series/observations?{q}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        obs = [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") not in (".", "", None)
        ]
        cache[cache_key] = obs
        log.info("FRED: fetched %d observations for %s", len(obs), FRED_SERIES)
        return obs
    except Exception as exc:
        log.warning("FRED bulk fetch error: %s", exc)
        cache[cache_key] = "none"
        return None


def _credit_ratio_for_date(d: date, fred_obs: list) -> Optional[float]:
    """Compute FRED credit ratio (current / 60d trailing baseline) as of date d."""
    # Find the latest observation on or before d
    available = [o for o in fred_obs if date.fromisoformat(o["date"]) <= d]
    if len(available) < FRED_MIN_DAYS + 1:
        return None
    current = available[-1]["value"]
    window = [o["value"] for o in available[-1 - FRED_BASELINE_DAYS:-1]]
    if len(window) < FRED_MIN_DAYS:
        return None
    baseline = sum(window) / len(window)
    if baseline <= 0:
        return None
    return current / baseline


# ---------------------------------------------------------------------------
# Main replay
# ---------------------------------------------------------------------------


def run_replay() -> str:
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        # Try loading from .env.service
        env_path = Path("/root/.openclaw/.env.service")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("FRED_API_KEY="):
                    fred_key = line.split("=", 1)[1].strip()
                    break
    if not fred_key:
        log.warning("FRED_API_KEY not found — credit leg will be skipped")

    cache = _load_cache()

    # Fetch FRED observations once (covers all dates)
    fred_obs: Optional[list] = None
    if fred_key:
        fred_obs = _fetch_fred_obs(fred_key, cache)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, ticker, confidence_score, alerted_at FROM alert_history ORDER BY alerted_at"
    ).fetchall()
    conn.close()

    log.info("Loaded %d alert_history rows from %s", len(rows), DB_PATH)

    # Per-date VIX/credit ratios (fetch once per calendar date)
    date_vix: dict[date, Optional[float]] = {}
    date_credit: dict[date, Optional[float]] = {}

    unique_dates = sorted({date.fromtimestamp(r["alerted_at"]) for r in rows})
    log.info("Unique alert dates: %d (%s to %s)", len(unique_dates), unique_dates[0], unique_dates[-1])

    for i, d in enumerate(unique_dates):
        if i % 10 == 0:
            log.info("Fetching market data for date %d/%d: %s", i + 1, len(unique_dates), d)
        vix_r = _fetch_vix_ratio_for_date(d, cache)
        date_vix[d] = vix_r
        if fred_obs is not None:
            date_credit[d] = _credit_ratio_for_date(d, fred_obs)
        else:
            date_credit[d] = None

    _save_cache(cache)

    # Classify each date as stressed or calm
    def _is_stressed(d: date) -> bool:
        vr = date_vix.get(d)
        cr = date_credit.get(d)
        # Stressed if backwardation OR wide credit (or both)
        if vr is not None and vr > 1.0:
            return True
        if cr is not None and cr > 1.0:
            return True
        return False

    # For each alert row, compute multiplier effect
    results = []
    for r in rows:
        d = date.fromtimestamp(r["alerted_at"])
        score = r["confidence_score"]
        if score is None:
            continue

        vix_r = date_vix.get(d)
        credit_r = date_credit.get(d)

        # Per-leg multipliers
        vix_mult = _ratio_to_multiplier(vix_r) if vix_r is not None else None
        credit_mult = (
            _ratio_to_multiplier(credit_r, reference_swing=CREDIT_SWING)
            if credit_r is not None
            else None
        )

        # Combined (same averaging logic as production)
        legs = [m for m in (vix_mult, credit_mult) if m is not None]
        if not legs:
            combined = 1.0
        elif len(legs) == 1:
            combined = legs[0]
        else:
            combined = max(VETO_FLOOR, min(CONFIRM_CEILING, sum(legs) / len(legs)))

        # Effective STRONG threshold after E2 (E2 scales the threshold, not the score)
        # Matches engine._classify: effective_high = clamp(base_high * e2_mult, base_high-10, 90)
        # Note direction: calm/contango (mult>1.0) RAISES the bar (harder to be STRONG);
        #                 stressed/backwardation (mult<1.0) LOWERS the bar (easier to be STRONG).
        base_high = HIGH_CONFIDENCE

        def _eff_high(mult: Optional[float]) -> float:
            m = mult if mult is not None else 1.0
            return max(base_high - 10, min(90, base_high * m))

        stressed = _is_stressed(d)

        results.append({
            "id": r["id"],
            "ticker": r["ticker"],
            "date": d,
            "score": score,
            "vix_ratio": vix_r,
            "credit_ratio": credit_r,
            "vix_mult": vix_mult,
            "credit_mult": credit_mult,
            "combined_mult": combined,
            "stressed": stressed,
            # Effective high under each scenario
            "eff_high_vix": _eff_high(vix_mult),
            "eff_high_credit": _eff_high(credit_mult),
            "eff_high_combined": _eff_high(combined),
            # Was STRONG baseline (no E2)?
            "strong_baseline": score >= base_high,
            # Would be STRONG under each leg?
            "strong_vix": score >= _eff_high(vix_mult),
            "strong_credit": score >= _eff_high(credit_mult),
            "strong_combined": score >= _eff_high(combined),
        })

    # -----------------------------------------------------------------------
    # Tabulate
    # -----------------------------------------------------------------------

    def _bucket(rows_list, label: str) -> dict:
        n = len(rows_list)
        if n == 0:
            return {"n": 0, "label": label}
        base_strong = sum(1 for r in rows_list if r["strong_baseline"])
        vix_strong = sum(1 for r in rows_list if r["strong_vix"])
        credit_strong = sum(1 for r in rows_list if r["strong_credit"])
        combined_strong = sum(1 for r in rows_list if r["strong_combined"])
        # Crosses (new STRONG): was NOT strong baseline, IS strong with E2 veto LOWERING bar
        # (stressed/backwardation: mult<1.0 -> effective_high drops below baseline score)
        vix_cross_up = sum(
            1 for r in rows_list
            if not r["strong_baseline"] and r["strong_vix"]
            and r["vix_mult"] is not None and r["vix_mult"] < 1.0
        )
        credit_cross_up = sum(
            1 for r in rows_list
            if not r["strong_baseline"] and r["strong_credit"]
            and r["credit_mult"] is not None and r["credit_mult"] < 1.0
        )
        combined_cross_up = sum(
            1 for r in rows_list
            if not r["strong_baseline"] and r["strong_combined"]
            and r["combined_mult"] < 1.0
        )
        # Uncrosses (lost STRONG): WAS strong baseline, NOT strong after E2 calm RAISING bar
        # (calm/contango: mult>1.0 -> effective_high raised to 90, score may fall below)
        vix_uncross = sum(
            1 for r in rows_list
            if r["strong_baseline"] and not r["strong_vix"]
            and r["vix_mult"] is not None and r["vix_mult"] > 1.0
        )
        credit_uncross = sum(
            1 for r in rows_list
            if r["strong_baseline"] and not r["strong_credit"]
            and r["credit_mult"] is not None and r["credit_mult"] > 1.0
        )
        combined_uncross = sum(
            1 for r in rows_list
            if r["strong_baseline"] and not r["strong_combined"]
            and r["combined_mult"] > 1.0
        )
        # Sample stressed dates with VIX data
        sample_dates = sorted({str(r["date"]) for r in rows_list if r["vix_ratio"] is not None})[:5]
        sample_vix = {str(r["date"]): round(r["vix_ratio"], 3) for r in rows_list if r["vix_ratio"] is not None and str(r["date"]) in sample_dates}
        return {
            "label": label,
            "n": n,
            "alerts_with_vix_data": sum(1 for r in rows_list if r["vix_ratio"] is not None),
            "alerts_with_credit_data": sum(1 for r in rows_list if r["credit_ratio"] is not None),
            "strong_baseline": base_strong,
            "strong_vix_leg": vix_strong,
            "strong_credit_leg": credit_strong,
            "strong_combined": combined_strong,
            "cross_up_vix": vix_cross_up,
            "cross_up_credit": credit_cross_up,
            "cross_up_combined": combined_cross_up,
            "uncross_vix": vix_uncross,
            "uncross_credit": credit_uncross,
            "uncross_combined": combined_uncross,
            "sample_vix_ratios": sample_vix,
        }

    calm_rows = [r for r in results if not r["stressed"]]
    stressed_rows = [r for r in results if r["stressed"]]

    calm_stats = _bucket(calm_rows, "Calm (contango / tight credit)")
    stressed_stats = _bucket(stressed_rows, "Stressed (backwardation and/or wide credit)")
    all_stats = _bucket(results, "All dates")

    # Find early-April stressed window
    apr_rows = [r for r in results if date(2026, 4, 1) <= r["date"] <= date(2026, 4, 15)]
    apr_stats = _bucket(apr_rows, "Early-April 2026 (tariff-shock window)")

    def _fmt(stats: dict) -> str:
        s = stats
        lines = [
            f"### {s['label']}",
            f"- Alerts: {s['n']}  (with VIX data: {s['alerts_with_vix_data']}, credit data: {s['alerts_with_credit_data']})",
            f"- STRONG baseline (no E2): {s['strong_baseline']}",
            "",
            "| Leg | STRONG with E2 | Cross-up (new STRONG) | Uncross (lost STRONG) |",
            "|---|---|---|---|",
            f"| VIX only | {s['strong_vix_leg']} | {s['cross_up_vix']} | {s['uncross_vix']} |",
            f"| Credit only | {s['strong_credit_leg']} | {s['cross_up_credit']} | {s['uncross_credit']} |",
            f"| Combined | {s['strong_combined']} | {s['cross_up_combined']} | {s['uncross_combined']} |",
        ]
        if s.get("sample_vix_ratios"):
            lines.append(f"\nSample VIX ratios on earliest dates: {s['sample_vix_ratios']}")
        return "\n".join(lines)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_lines = [
        "# E2 Cross-Asset Multiplier Offline Replay",
        f"",
        f"Generated: {now_str}  ",
        f"DB: {DB_PATH} ({len(rows)} rows, {unique_dates[0]} – {unique_dates[-1]})  ",
        f"Threshold: STRONG at score >= {HIGH_CONFIDENCE} (effective_high = clamp(80 × multiplier, 70, 90))  ",
        f"VIX swing: {VIX_SWING}, Credit swing: {CREDIT_SWING}  ",
        f"Bounds: veto_floor={VETO_FLOOR}, confirm_ceiling={CONFIRM_CEILING}",
        f"",
        "## Summary",
        "",
        _fmt(all_stats),
        "",
        _fmt(calm_stats),
        "",
        _fmt(stressed_stats),
        "",
        _fmt(apr_stats),
        "",
        "## Interpretation",
        "",
        "- E2 **scales the STRONG threshold** (not the score): `effective_high = clamp(80 × multiplier, 70, 90)`.",
        "- Calm/contango (multiplier > 1.0): effective_high → 90 (ceiling) — **harder** to reach STRONG.",
        "- Stressed/backwardation (multiplier < 1.0): effective_high → 70 (floor) — **easier** to reach STRONG.",
        "- **Cross-up (new STRONG)**: alert below STRONG baseline whose score ≥ lowered effective_high in stressed regime.",
        "- **Uncross (lost STRONG)**: alert above STRONG baseline whose score < raised effective_high (90) in calm regime.",
        "- Combined leg averages VIX + credit and re-clamps, matching production logic.",
        "- A None leg (unavailable data) is dropped; it never weakens a live leg.",
    ]
    report = "\n".join(report_lines)
    print(report)

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(report)
    log.info("Report written to %s", RESULT_PATH)
    return report


if __name__ == "__main__":
    run_replay()
