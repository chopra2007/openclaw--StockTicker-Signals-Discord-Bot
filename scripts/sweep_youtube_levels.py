"""One-time (and re-runnable) global sanity sweep of all unsuppressed youtube_levels
and youtube_setups rows.

Applies the same >=2x / <=0.5x gate from consensus_engine/analysis/level_display_sanity.py
(item C) to STORED data.  The existing gate runs at display time; this script runs it against
the database so bad values are pre-emptively removed before !all even loads them.

Index / commodity tickers (SPX, NDX, VIX, etc.) are checked against the _INDEX_RANGE bands
from level_display_sanity rather than a live equity quote.

Penny stocks (<$5 live price) are kept regardless of level magnitude, matching the
<$5 exemption in classify_level.

Usage:
    python3 scripts/sweep_youtube_levels.py            # dry-run report
    python3 scripts/sweep_youtube_levels.py --apply    # suppress wild rows in DB
    python3 scripts/sweep_youtube_levels.py --db PATH  # custom DB path
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DEFAULT_DB = _REPO / "consensus.db"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("sweep_youtube_levels")

# Mirror constants from level_display_sanity.py (kept local so script runs standalone).
_MAX_RATIO = 2.0
_PENNY_SKIP_PRICE = 5.0

_INDEX_RANGE: dict[str, tuple[float, float]] = {
    "SMH": (150, 400), "SOX": (3000, 8000), "NDX": (12000, 30000), "SPX": (3000, 8000),
    "RUT": (1500, 4000), "DJIA": (25000, 55000), "VIX": (8, 95), "OIL": (20, 160),
    "GOLD": (1000, 5000), "BONDS": (5, 200), "YIELDS": (0.5, 20), "DXY": (80, 130),
    "BTC": (10000, 250000), "IGV": (40, 250), "XLE": (40, 200), "XLF": (20, 120),
    "XLK": (100, 400), "XLV": (60, 250),
    "SPY": (300, 800), "QQQ": (250, 800), "IWM": (120, 400), "URA": (15, 80),
}
_UNBOUNDED_UP = {"BTC"}


def _is_wild_index(ticker: str, price: float) -> bool:
    rng = _INDEX_RANGE.get(ticker.upper())
    if rng is None:
        return False
    lo, hi = rng
    if price < lo:
        return True
    if price > hi:
        if ticker.upper() in _UNBOUNDED_UP:
            return price > hi * 10
        return True
    return False


def _is_wild_equity(ticker: str, price: float, live_price: float) -> bool:
    if live_price < _PENNY_SKIP_PRICE:
        return False
    ratio = price / live_price
    return ratio >= _MAX_RATIO or ratio <= 1.0 / _MAX_RATIO


def _fetch_live_prices(tickers: list[str]) -> dict[str, float | None]:
    """Batch-fetch closing prices via yfinance.  Be gentle: one call, 1-day period."""
    prices: dict[str, float | None] = {t: None for t in tickers}
    equity_tickers = [t for t in tickers if t.upper() not in _INDEX_RANGE]
    if not equity_tickers:
        return prices
    try:
        import yfinance as yf  # noqa: PLC0415
        batch = " ".join(equity_tickers)
        log.info("yfinance batch download for %d equity tickers…", len(equity_tickers))
        data = yf.download(batch, period="2d", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            log.warning("yfinance returned empty data")
            return prices
        close = data["Close"]
        for t in equity_tickers:
            try:
                series = close[t] if t in close.columns else close.get(t)
                if series is None:
                    continue
                val = series.dropna()
                if len(val) == 0:
                    continue
                prices[t] = float(val.iloc[-1])
            except Exception as exc:  # noqa: BLE001
                log.debug("price lookup failed for %s: %s", t, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance batch failed: %s", exc)
    return prices


def _classify(ticker: str, price: float, live_price: float | None) -> str:
    """Return 'wild' or 'ok'."""
    t = ticker.upper()
    if t in _INDEX_RANGE:
        return "wild" if _is_wild_index(t, price) else "ok"
    if live_price is None:
        return "unknown"  # no anchor -> fail-open (don't suppress)
    return "wild" if _is_wild_equity(t, price, live_price) else "ok"


def sweep(db_path: Path, apply: bool) -> None:
    if not db_path.exists():
        log.error("DB not found: %s", db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ── Collect all unsuppressed levels ─────────────────────────────────────
    cur = conn.execute(
        "SELECT id, ticker, price, level_type, video_id FROM youtube_levels "
        "WHERE suppressed = 0 OR suppressed IS NULL ORDER BY ticker, price"
    )
    level_rows = [dict(r) for r in cur.fetchall()]

    # ── Collect all unsuppressed setups (check targets_json entries) ─────────
    cur = conn.execute(
        "SELECT id, ticker, targets_json, entry_low, entry_high, stop_price, video_id "
        "FROM youtube_setups WHERE suppressed = 0 OR suppressed IS NULL ORDER BY ticker"
    )
    setup_rows = [dict(r) for r in cur.fetchall()]

    # ── Gather unique equity tickers needing live prices ────────────────────
    all_tickers = set()
    for r in level_rows:
        t = r["ticker"].upper()
        if t not in _INDEX_RANGE:
            all_tickers.add(t)
    for r in setup_rows:
        t = r["ticker"].upper()
        if t not in _INDEX_RANGE:
            all_tickers.add(t)

    live_prices = _fetch_live_prices(list(all_tickers))

    # ── Classify levels ──────────────────────────────────────────────────────
    wild_levels: list[dict] = []
    ok_levels = 0
    unknown_levels = 0

    for r in level_rows:
        t = r["ticker"].upper()
        price = float(r["price"])
        lp = live_prices.get(t)
        verdict = _classify(t, price, lp)
        if verdict == "wild":
            wild_levels.append({
                "id": r["id"], "ticker": t, "value": price,
                "live_price": lp, "video_id": r["video_id"],
                "level_type": r["level_type"], "source": "youtube_levels",
            })
        elif verdict == "unknown":
            unknown_levels += 1
        else:
            ok_levels += 1

    # ── Classify setup targets ───────────────────────────────────────────────
    wild_setups: list[dict] = []
    ok_setups = 0

    for r in setup_rows:
        t = r["ticker"].upper()
        lp = live_prices.get(t)
        targets: list[float] = []
        try:
            raw = json.loads(r["targets_json"] or "[]")
            targets = [float(x) for x in raw if x is not None]
        except Exception:
            pass
        # Also include entry_low, entry_high, stop_price as values to check
        candidate_vals = targets[:]
        for field in ("entry_low", "entry_high", "stop_price"):
            v = r.get(field)
            if v is not None:
                candidate_vals.append(float(v))

        setup_wild = False
        for val in candidate_vals:
            if val <= 0:
                continue
            if _classify(t, val, lp) == "wild":
                setup_wild = True
                wild_setups.append({
                    "id": r["id"], "ticker": t, "value": val,
                    "live_price": lp, "video_id": r["video_id"],
                    "source": "youtube_setups",
                })
                break  # report once per setup row
        if not setup_wild:
            ok_setups += 1

    # ── Print report ─────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print(f"SWEEP REPORT  (dry_run={not apply})")
    print("=" * 72)
    print(f"youtube_levels  unsuppressed: {len(level_rows)}  "
          f"ok: {ok_levels}  wild: {len(wild_levels)}  unknown(fail-open): {unknown_levels}")
    print(f"youtube_setups  unsuppressed: {len(setup_rows)}  "
          f"ok: {ok_setups}  wild-target: {len(wild_setups)}")
    print()

    if wild_levels:
        print("WILD LEVELS (youtube_levels) — would suppress:")
        print(f"  {'id':>6}  {'ticker':8}  {'value':>12}  {'live_price':>12}  {'video_id':15}  level_type")
        for w in sorted(wild_levels, key=lambda x: (x["ticker"], x["value"])):
            lp_s = f"{w['live_price']:.2f}" if w["live_price"] else "N/A"
            print(f"  {w['id']:>6}  {w['ticker']:8}  {w['value']:>12.2f}  {lp_s:>12}  "
                  f"{w['video_id']:15}  {w['level_type']}")
    else:
        print("WILD LEVELS: none found.")

    print()

    if wild_setups:
        print("WILD SETUPS (youtube_setups) — would suppress:")
        print(f"  {'id':>6}  {'ticker':8}  {'value':>12}  {'live_price':>12}  {'video_id':15}")
        for w in sorted(wild_setups, key=lambda x: (x["ticker"], x["value"])):
            lp_s = f"{w['live_price']:.2f}" if w["live_price"] else "N/A"
            print(f"  {w['id']:>6}  {w['ticker']:8}  {w['value']:>12.2f}  {lp_s:>12}  "
                  f"{w['video_id']:15}")
    else:
        print("WILD SETUPS: none found.")

    print()

    if not apply:
        print("DRY-RUN complete.  Re-run with --apply to suppress wild rows.")
        conn.close()
        return

    # ── Apply suppressions ───────────────────────────────────────────────────
    reason = "sweep_youtube_levels: value >=2x or <=0.5x live price"
    ts = time.time()
    level_ids = [w["id"] for w in wild_levels]
    setup_ids = [w["id"] for w in wild_setups]

    suppressed_levels = 0
    suppressed_setups = 0

    for row_id in level_ids:
        conn.execute(
            "UPDATE youtube_levels SET suppressed=1, suppression_reason=? "
            "WHERE id=? AND (suppressed=0 OR suppressed IS NULL)",
            (reason, row_id),
        )
        suppressed_levels += conn.total_changes
        conn.commit()

    for row_id in setup_ids:
        conn.execute(
            "UPDATE youtube_setups SET suppressed=1, suppression_reason=? "
            "WHERE id=? AND (suppressed=0 OR suppressed IS NULL)",
            (reason, row_id),
        )
        suppressed_setups += conn.total_changes
        conn.commit()

    # ── After-counts ─────────────────────────────────────────────────────────
    cur = conn.execute("SELECT COUNT(*) FROM youtube_levels WHERE suppressed=0 OR suppressed IS NULL")
    after_levels = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM youtube_setups WHERE suppressed=0 OR suppressed IS NULL")
    after_setups = cur.fetchone()[0]

    print(f"APPLIED: suppressed {len(level_ids)} levels, {len(setup_ids)} setups.")
    print(f"After-state: youtube_levels unsuppressed={after_levels}, "
          f"youtube_setups unsuppressed={after_setups}")
    print()
    if wild_levels:
        print("AUDIT TRAIL — levels suppressed:")
        for w in wild_levels:
            lp_s = f"{w['live_price']:.2f}" if w["live_price"] else "N/A"
            print(f"  id={w['id']} ticker={w['ticker']} value={w['value']:.2f} "
                  f"live_price={lp_s} video_id={w['video_id']}")
    if wild_setups:
        print("AUDIT TRAIL — setups suppressed:")
        for w in wild_setups:
            lp_s = f"{w['live_price']:.2f}" if w["live_price"] else "N/A"
            print(f"  id={w['id']} ticker={w['ticker']} value={w['value']:.2f} "
                  f"live_price={lp_s} video_id={w['video_id']}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Suppress wild rows (default: dry-run only)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"DB path (default: {DEFAULT_DB})")
    args = parser.parse_args()
    sweep(args.db, apply=args.apply)


if __name__ == "__main__":
    main()
