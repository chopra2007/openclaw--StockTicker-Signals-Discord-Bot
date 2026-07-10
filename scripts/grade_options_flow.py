"""#57: grade every stored unusual-options-flow hit against what the stock did next.

Question this answers: when the scanner shouted "unusual CALL flow in $NVDA", did
NVDA actually go up? It grades DIRECTION only (calls should precede a rise, puts a
fall) at two horizons — the close 1 and 5 TRADING days after the hit — using the
`spot` recorded at detection as the entry price.

The unit of analysis is a flow EVENT: one (contract_symbol, market_date) pair,
taken at its earliest detection. The scanner re-detects a live contract on every
poll cycle, so the 123k raw rows are really ~10.7k events; grading raw rows would
let a handful of SPY/QQQ contracts decide the answer.

Prices come from yfinance daily bars, fetched ONCE per ticker for the whole span
and cached on disk, so a full backfill makes ~15 network calls instead of ~10,000.

    python3 scripts/grade_options_flow.py --count           # what's eligible, no writes
    python3 scripts/grade_options_flow.py --backfill        # grade everything eligible
    python3 scripts/grade_options_flow.py --backfill --nightly   # only recent, for the timer
    python3 scripts/grade_options_flow.py --report          # win-rate table by bucket

Writes only `options_flow_outcomes`. Never touches `options_flow`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db  # noqa: E402

log = logging.getLogger("grade_options_flow")

# Trading days after the hit. Bar 0 is the hit's own session.
HORIZONS = (1, 5)
MAX_HORIZON = max(HORIZONS)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "flow_grading_prices.json"
CACHE_TTL_SEC = 12 * 3600
CHUNK = 25            # tickers per yfinance batch call
NIGHTLY_LOOKBACK_D = 45   # --nightly only re-scans this far back
BENCHMARK = "SPY"     # market leg subtracted out to remove drift

# A hit needs MAX_HORIZON *trading* days to elapse. This calendar pad is only a
# cheap pre-filter; the real gate is the bar count in close_n_trading_days_later,
# which returns None (leaving the column NULL to refill later) if the window is
# still open. Keep it tight so the freshest usable week isn't thrown away.
ELAPSED_PAD_DAYS = MAX_HORIZON + 4


# --------------------------------------------------------------------------
# price bars
# --------------------------------------------------------------------------

def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        blob = json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if time.time() - blob.get("fetched_at", 0) > CACHE_TTL_SEC:
        return {}
    return blob.get("bars", {})


def _save_cache(bars: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"fetched_at": time.time(), "bars": bars}))


def fetch_daily_closes(tickers: list[str], start: date, end: date,
                       use_cache: bool = True) -> dict[str, dict[str, float]]:
    """{ticker: {"YYYY-MM-DD": close}} for every ticker over [start, end].

    Batched yfinance downloads with a simple retry. Tickers that fail entirely
    come back missing (not empty), and the caller just leaves those rows ungraded.
    """
    import yfinance as yf

    cached = _load_cache() if use_cache else {}
    todo = [t for t in tickers if t not in cached]
    if not todo:
        return cached

    out: dict[str, dict[str, float]] = dict(cached)
    end_exclusive = (end + timedelta(days=1)).isoformat()

    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i + CHUNK]
        frame = None
        for attempt in range(3):
            try:
                frame = yf.download(
                    batch, start=start.isoformat(), end=end_exclusive,
                    interval="1d", progress=False, auto_adjust=False,
                    threads=False, group_by="column",
                )
                break
            except Exception as e:  # network / rate limit
                wait = 2 ** attempt
                log.warning("yfinance batch %d failed (%s); retrying in %ds", i, e, wait)
                time.sleep(wait)
        if frame is None or frame.empty:
            log.warning("yfinance batch %d returned nothing for %s", i, batch)
            continue

        closes = frame["Close"]
        # A single-ticker download returns a plain Series-like column.
        cols = list(closes.columns) if hasattr(closes, "columns") else batch
        for tk in cols:
            series = closes[tk] if hasattr(closes, "columns") else closes
            bars = {
                d.strftime("%Y-%m-%d"): float(v)
                for d, v in series.items() if v == v  # drop NaN
            }
            if bars:
                out[tk] = bars
        log.info("fetched %d/%d tickers", min(i + CHUNK, len(todo)), len(todo))
        time.sleep(0.5)   # be polite to yfinance

    if use_cache:
        _save_cache(out)
    return out


def close_n_trading_days_later(bars: dict[str, float], market_date: str,
                               n: int) -> float | None:
    """The close n trading sessions after `market_date` (bar 0 = that session).

    Uses the ticker's own bar dates as the trading calendar, so weekends and
    holidays are skipped for free. Returns None when the window hasn't elapsed.
    If `market_date` itself is not a bar (hit recorded outside a session), the
    next available bar is treated as bar 0.
    """
    if not bars:
        return None
    days = sorted(bars)
    idx = bisect_left(days, market_date)
    if idx >= len(days):
        return None
    target = idx + n
    if target >= len(days):
        return None
    return bars[days[target]]


def _closes_at(bars: dict[str, float] | None, market_date: str
               ) -> tuple[float | None, float | None, float | None]:
    """(bar 0, bar 1, bar 5) closes for one ticker's calendar."""
    if not bars:
        return None, None, None
    return (close_n_trading_days_later(bars, market_date, 0),
            close_n_trading_days_later(bars, market_date, 1),
            close_n_trading_days_later(bars, market_date, 5))


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------

async def grade(nightly: bool = False, limit: int | None = None,
                use_cache: bool = True) -> dict:
    await db.init_db()
    try:
        cutoff = time.time() - ELAPSED_PAD_DAYS * 86400
        events = await db.get_flow_events(
            ungraded_only=True, max_detected_at=cutoff, limit=limit,
        )
        if nightly:
            floor = time.time() - NIGHTLY_LOOKBACK_D * 86400
            events = [e for e in events if e["detected_at"] >= floor]
        if not events:
            return {"events": 0, "graded": 0, "skipped_no_price": 0}

        tickers = sorted({e["ticker"] for e in events} | {BENCHMARK})
        first = min(e["market_date"] for e in events)
        start = date.fromisoformat(first) - timedelta(days=5)
        end = datetime.now(timezone.utc).date()
        log.info("grading %d events across %d tickers (%s → %s)",
                 len(events), len(tickers), first, end)
        bars_by_ticker = fetch_daily_closes(tickers, start, end, use_cache=use_cache)
        bench_bars = bars_by_ticker.get(BENCHMARK)
        if not bench_bars:
            log.warning("no %s bars — market-adjusted columns will be NULL", BENCHMARK)

        graded = skipped = 0
        for e in events:
            bars = bars_by_ticker.get(e["ticker"])
            if not bars:
                skipped += 1
                continue
            c0, c1, c5 = _closes_at(bars, e["market_date"])
            if c1 is None and c5 is None:
                skipped += 1
                continue
            b0, b1, b5 = _closes_at(bench_bars, e["market_date"])
            await db.upsert_flow_outcome(
                flow_id=e["flow_id"], ticker=e["ticker"], side=e["side"],
                contract_symbol=e["contract_symbol"], market_date=e["market_date"],
                detected_at=e["detected_at"], entry_spot=e["spot"],
                close_0d=c0, close_1d=c1, close_5d=c5,
                bench_close_0d=b0, bench_close_1d=b1, bench_close_5d=b5,
            )
            graded += 1
        return {"events": len(events), "graded": graded, "skipped_no_price": skipped}
    finally:
        await db.close_db()


async def count_eligible() -> dict:
    await db.init_db()
    try:
        cutoff = time.time() - ELAPSED_PAD_DAYS * 86400
        all_events = await db.get_flow_events()
        ungraded = await db.get_flow_events(ungraded_only=True, max_detected_at=cutoff)
        return {"total_events": len(all_events), "ungraded_and_elapsed": len(ungraded)}
    finally:
        await db.close_db()


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

MIN_N = 10   # thin-sample rule: never print a % below this

# Index/sector ETFs. Graded against SPY these are near-tautological (SPY vs SPY is
# a definitional zero; QQQ vs SPY is mostly noise), so they are excluded from the
# headline tables — they would drag both legs toward the same number and hide a
# real single-stock edge.
ETF_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "SOXX", "SMH", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "GLD", "SLV", "TLT", "USO", "ARKK", "VOO", "RSP", "IGV", "XLE", "XLF",
    "XLK", "XLV", "VGT", "SCHD", "KORU", "EWY",
})


def cluster_events(rows: list[dict]) -> list[dict]:
    """One row per (ticker, market_date, side), keeping the highest-vol/OI contract.

    A dozen contracts on the same name on the same day all ride ONE price move, so
    treating them as a dozen independent observations inflates every significance
    test. This is the difference between "z=3.98, definitely real" and "z=2.50,
    probably real" — it changed the answer, so it is not optional.
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["ticker"], r["market_date"], r["side"].upper())
        if k not in best or (r.get("vol_oi_ratio") or 0) > (best[k].get("vol_oi_ratio") or 0):
            best[k] = r
    return list(best.values())


def _bucket_premium(p: float) -> str:
    if p >= 1_000_000:
        return "$1M+"
    if p >= 500_000:
        return "$500k-1M"
    if p >= 250_000:
        return "$250-500k"
    return "<$250k"


def _bucket_voloi(r: float) -> str:
    if r >= 50:
        return "50+"
    if r >= 20:
        return "20-50"
    if r >= 10:
        return "10-20"
    return "<10"


def _is_0dte(expiry: str | None, market_date: str) -> bool:
    return bool(expiry) and expiry[:10] == market_date


def _fmt(wins: int, n: int) -> str:
    if n == 0:
        return "—"
    if n < MIN_N:
        return f"{wins}/{n} (thin)"
    return f"{100.0 * wins / n:.1f}% ({wins}/{n})"


def excess_move(row: dict, n: int) -> float | None:
    """Ticker's close-to-close move minus SPY's, over the same trading window.

    Both legs run bar 0 → bar n, so the market's drift over exactly those sessions
    cancels. Returns None when any leg is missing. This is the number that says
    whether the flow knew something; the raw `ret_*` columns do not.
    """
    c0, cn = row.get("close_0d"), row.get(f"close_{n}d")
    b0, bn = row.get("bench_close_0d"), row.get(f"bench_close_{n}d")
    if not all(v and v > 0 for v in (c0, cn, b0, bn)):
        return None
    return (cn / c0 - 1.0) - (bn / b0 - 1.0)


def _z_two_prop(w1: int, n1: int, w2: int, n2: int) -> float | None:
    """Two-proportion z-score for (up-rate after CALL) vs (up-rate after PUT).

    |z| >= 1.96 is the usual 'unlikely to be luck' bar. Returns None when either
    leg is too thin to say anything.
    """
    if n1 < MIN_N or n2 < MIN_N:
        return None
    p1, p2 = w1 / n1, w2 / n2
    p = (w1 + w2) / (n1 + n2)
    denom = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    if denom == 0:
        return None
    return (p1 - p2) / denom


async def report() -> str:
    await db.init_db()
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT o.*, f.premium_usd, f.vol_oi_ratio, f.volume, f.expiry, f.alerted
               FROM options_flow_outcomes o JOIN options_flow f ON f.id = o.flow_id"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close_db()

    if not rows:
        return "No graded flow events yet — run `--backfill` first."

    for r in rows:
        r["adj_1d"] = excess_move(r, 1)
        r["adj_5d"] = excess_move(r, 5)

    raw_n = len(rows)
    stocks = [r for r in rows
              if r["ticker"] not in ETF_TICKERS and r["adj_5d"] is not None]
    clustered = cluster_events(stocks)

    def section(title: str, keyfn, rows_, order=None, note: str = "") -> list[str]:
        """Per bucket: how often the stock BEAT SPY after a CALL hit vs after a PUT hit.

        Under 'the flow knows nothing' both columns equal the same base rate and the
        gap is 0. A positive gap is the only thing that would justify the alert.
        """
        agg = defaultdict(lambda: {"CALL": [0, 0], "PUT": [0, 0]})
        for r in rows_:
            if r["adj_5d"] is None:
                continue
            leg = agg[keyfn(r)][r["side"].upper()]
            leg[1] += 1
            leg[0] += 1 if r["adj_5d"] > 0 else 0
        out = [f"\n### {title}"]
        if note:
            out.append(f"\n{note}")
        out += ["",
                "| bucket | beat SPY after CALL | beat SPY after PUT | gap | luck? |",
                "|---|---|---|---|---|"]
        for k in (order or sorted(agg)):
            if k not in agg:
                continue
            cw, cn = agg[k]["CALL"]
            pw, pn = agg[k]["PUT"]
            z = _z_two_prop(cw, cn, pw, pn)
            if z is None:
                gap, verdict = "—", "too thin"
            else:
                gap = f"{100.0 * (cw / cn - pw / pn):+.1f} pp"
                verdict = "**real**" if abs(z) >= 1.96 else f"luck (z={z:+.2f})"
            out.append(f"| {k} | {_fmt(cw, cn)} | {_fmt(pw, pn)} | {gap} | {verdict} |")
        return out

    def cumulative(data: list[dict], bars: list[float]) -> list[str]:
        """What each candidate `min_vol_oi` setting would actually have bought."""
        out = ["\n### If `min_vol_oi` had been set to …", "",
               "The decision table. Each row is a candidate threshold, applied to every "
               "event at or above it.", "",
               "| min_vol_oi | events kept | beat SPY after CALL | beat SPY after PUT | gap | luck? |",
               "|---|---|---|---|---|---|"]
        for bar in bars:
            sel = [r for r in data if (r["vol_oi_ratio"] or 0) >= bar]
            cw = sum(1 for r in sel if r["side"].upper() == "CALL" and r["adj_5d"] > 0)
            cn = sum(1 for r in sel if r["side"].upper() == "CALL")
            pw = sum(1 for r in sel if r["side"].upper() == "PUT" and r["adj_5d"] > 0)
            pn = sum(1 for r in sel if r["side"].upper() == "PUT")
            z = _z_two_prop(cw, cn, pw, pn)
            if z is None:
                gap, verdict = "—", "too thin"
            else:
                gap = f"{100.0 * (cw / cn - pw / pn):+.1f} pp"
                verdict = "**real**" if abs(z) >= 1.96 else f"luck (z={z:+.2f})"
            keep = f"{len(sel)} ({100.0 * len(sel) / max(len(data), 1):.0f}%)"
            out.append(f"| ≥ {bar:g} | {keep} | {_fmt(cw, cn)} | {_fmt(pw, pn)} | {gap} | {verdict} |")
        return out

    n5 = sum(1 for r in rows if r["win_5d"] is not None)
    w5 = sum(r["win_5d"] or 0 for r in rows)
    n1 = sum(1 for r in rows if r["win_1d"] is not None)
    w1 = sum(r["win_1d"] or 0 for r in rows)
    mean_raw_5d = sum(r["ret_5d"] for r in rows if r["ret_5d"] is not None) / max(n5, 1)
    base = sum(1 for r in clustered if r["adj_5d"] > 0) / max(len(clustered), 1)

    lines = [
        "# Options-flow hit grading (#57)",
        "",
        f"_Generated by `scripts/grade_options_flow.py --report`. Window "
        f"{min(r['market_date'] for r in rows)} → {max(r['market_date'] for r in rows)}._",
        "",
        "## Read this first: the raw win rate is a lie",
        "",
        f"Raw direction wins across all **{raw_n}** graded events — CALL then the stock rose, "
        f"or PUT then it fell, measured from the spot price at detection: "
        f"**1-day {_fmt(w1, n1)}, 5-day {_fmt(w5, n5)}**. Looks like a coin flip.",
        "",
        f"It isn't even that. The average stock here moved **{100 * mean_raw_5d:+.2f}%** over "
        f"five days: the window was a falling market, so every PUT looks smart and every CALL "
        f"looks dumb for reasons that have nothing to do with options flow.",
        "",
        "## What is measured instead",
        "",
        "Every table below measures the stock's move **against SPY over the identical trading "
        "days**, and asks one question:",
        "",
        "> After a CALL hit, did the stock beat SPY more often than it did after a PUT hit?",
        "",
        "That difference is the **gap**. If the flow carries information the gap is positive. "
        "If it doesn't, both columns land on the same number and the gap is zero — no matter "
        "which way the market went.",
        "",
        "Two corrections make the gap trustworthy, and both changed the answer:",
        "",
        f"1. **One event per ticker per day per side.** A dozen contracts on the same name on "
        f"the same day all ride one price move. Counting them separately inflates every "
        f"significance test. This cuts {len(stocks)} rows down to {len(clustered)}.",
        f"2. **Index ETFs dropped.** SPY measured against SPY is a definitional zero, and QQQ "
        f"against SPY is mostly noise; leaving them in drags both columns together and hides "
        f"a real single-stock edge. This drops {raw_n - len(stocks)} rows.",
        "",
        f"**{len(clustered)} independent single-stock events remain.** Across all of them the "
        f"stock beat SPY {100 * base:.1f}% of the time whatever the side — that is the base "
        f"rate both columns should hit if the flow knows nothing.",
    ]

    lines += cumulative(clustered, [5, 10, 20, 30, 50])
    lines += section("By volume/open-interest ratio (in bands, not cumulative)",
                     lambda r: _bucket_voloi(r["vol_oi_ratio"] or 0), clustered,
                     ["<10", "10-20", "20-50", "50+"],
                     note="Read with the cumulative table above: the band 20-50 is flat on its "
                          "own, so the cumulative ≥20 edge is carried by the 50+ band.")
    lines += section("By premium size", lambda r: _bucket_premium(r["premium_usd"] or 0), clustered,
                     ["<$250k", "$250-500k", "$500k-1M", "$1M+"],
                     note="Config key `options_flow.min_premium_usd`. No edge in any bucket — "
                          "bigger premium does NOT mean better signal. Not a lever.")
    lines += section("By contract volume",
                     lambda r: ("5000+" if (r["volume"] or 0) >= 5000
                                else "2000-5000" if (r["volume"] or 0) >= 2000
                                else "1000-2000" if (r["volume"] or 0) >= 1000
                                else "500-1000"),
                     clustered, ["500-1000", "1000-2000", "2000-5000", "5000+"],
                     note="Config key `options_flow.min_volume`. Raising it would if anything "
                          "HURT — the biggest-volume bucket grades worst. Not a lever.")
    lines += section("Same-day expiry (0DTE) vs longer-dated",
                     lambda r: "0DTE" if _is_0dte(r["expiry"], r["market_date"]) else "longer-dated",
                     clustered, ["0DTE", "longer-dated"],
                     note="Before clustering this looked like a strong result (0DTE flow "
                          "predicted nothing, z=-1.29 vs +3.17). After clustering neither leg "
                          "is significant. No filter added.")
    lines += section("Ticker alerted that cycle",
                     lambda r: "alerted=1" if r["alerted"] else "alerted=0", clustered,
                     ["alerted=1", "alerted=0"],
                     note="`alerted` is set per TICKER, not per contract — it means 'this ticker "
                          "fired an alert that cycle'. A weak proxy; don't over-read it.")
    lines += [
        "",
        "## What was changed, and what was not",
        "",
        "- `min_vol_oi` **10 → 20**. The old bar sat where the gap is indistinguishable from "
        "zero. Higher bars grade better still, but this is one month of data and two of its "
        "five weeks had a negative gap, so a jump straight to 50 would be fitting noise. "
        "`flow-grading.timer` grades every night; revisit once a second month is in.",
        "- `min_premium_usd` and `min_volume` **unchanged** — measured, not levers.",
        "- `relative_baseline_enabled` **stays off**. Requiring premium ≥ 2×/3×/5× the ticker's "
        "own trailing-30d mean gave gaps of +7.1pp / -6.7pp / (n=17, too thin) — never "
        "significant, and the sample collapses.",
        "",
        f"_Buckets with fewer than {MIN_N} events in either leg show the raw win/total and no "
        f"gap. 'luck?' is a two-proportion z-test; **real** means |z| ≥ 1.96 — under 1-in-20 "
        f"odds the gap is chance. These are single-month, single-regime numbers._",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Grade stored options-flow hits (#57).")
    p.add_argument("--backfill", action="store_true", help="grade all eligible events")
    p.add_argument("--nightly", action="store_true",
                   help=f"with --backfill: only look back {NIGHTLY_LOOKBACK_D} days")
    p.add_argument("--count", action="store_true", help="report eligibility, no writes")
    p.add_argument("--report", action="store_true", help="print the win-rate table")
    p.add_argument("--limit", type=int, default=None, help="cap events graded")
    p.add_argument("--no-cache", action="store_true", help="ignore the price cache")
    p.add_argument("--out", type=str, default=None, help="write the report to a file too")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.count:
        c = asyncio.run(count_eligible())
        print(f"Flow events (contract x day): {c['total_events']}")
        print(f"Ungraded with horizon elapsed: {c['ungraded_and_elapsed']}")
        return 0

    if args.backfill:
        r = asyncio.run(grade(nightly=args.nightly, limit=args.limit,
                              use_cache=not args.no_cache))
        print(f"events={r['events']} graded={r['graded']} "
              f"skipped_no_price={r['skipped_no_price']}")

    if args.report:
        text = asyncio.run(report())
        print(text)
        if args.out:
            Path(args.out).write_text(text + "\n")
            print(f"\n(written to {args.out})", file=sys.stderr)

    if not (args.backfill or args.report or args.count):
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
