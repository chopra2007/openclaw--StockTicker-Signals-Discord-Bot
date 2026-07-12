"""#55: grade analyst posts that carried a REAL directional catalyst — benchmark-relative.

Question this answers: when an analyst said "buy NVDA, the CES launch is the catalyst",
did NVDA actually beat SEMIS (SMH) over the next 30 days? Not "did NVDA go up" — if the
whole sector ran, the analyst called the sector, not the stock. So every score here is
BHAR: the stock's 21-session move MINUS its benchmark's over the same sessions.

Two horizons, deliberately different math:
  * SHORT catalyst (options expiry, M&A, earnings, launch, ruling) -> 30 calendar days
    ~= 21 trading sessions, weekly BHAR checkpoints, terminal bar decides the win.
  * LONG catalyst (moat, multi-year guidance ramp) -> a BET is opened and checked at
    30/60/90 sessions only. Never compounded daily; daily stats on a 90-day thesis are noise.
    A bet is opened ONLY when the classifier's likelihood clears the cutoff, so vague
    musings never cost a slot.

Posts with no catalyst are SKIPPED, not scored — that is the whole point of #55: the
existing 1h/24h scorecard grades every post, including pure news recaps, which is why it
reads near-random.

    python3 scripts/grade_analyst_catalysts.py --count      # what's eligible, no writes
    python3 scripts/grade_analyst_catalysts.py --backfill   # classify + grade everything eligible
    python3 scripts/grade_analyst_catalysts.py --backfill --nightly   # recent only, for the timer
    python3 scripts/grade_analyst_catalysts.py --report     # win-rate table + skip counters

Writes ONLY `analyst_catalyst_scores` + `long_term_catalyst_bets` (both SHADOW). Never
touches the live alert path, `source_performance`, or the promotion gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db  # noqa: E402
from consensus_engine.analysis import benchmark_grading as bg  # noqa: E402
from grade_options_flow import fetch_daily_closes  # noqa: E402  (proven cached batch fetch)

log = logging.getLogger("grade_analyst_catalysts")

MIN_N = 10          # thin-sample rule: never print a % below this
LIKELIHOOD_CUTOFF = 0.5   # a long-term bet is opened only above this
BONUS_CAP = 2.0           # margin bonus caps at +2x
BONUS_FULL_AT = 0.10      # ...reached at a 10-percentage-point BHAR margin
ELAPSED_PAD_DAYS = 31     # 21 trading sessions ~= 30 calendar days; +1 slack
NIGHTLY_LOOKBACK_D = 60   # --nightly only re-scans this far back
DEFAULT_CLASSIFY_CAP = 250   # bound the one-time LLM spend per run

# Classifications are cached on disk so a re-run costs zero LLM calls for posts it
# has already read (the same discipline as the #57 price cache).
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "catalyst_classifications.json"


# ─────────────────────────── classification cache ───────────────────────────

def _load_classifications() -> dict[str, dict]:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_classifications(blob: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(blob, indent=0))


# ─────────────────────────────── post loading ───────────────────────────────

async def load_posts(nightly: bool = False) -> list[dict]:
    """Stored analyst posts with raw text, newest first.

    Raw tweet text lives on `ticker_signals` (source_type='twitter'); the tweet's
    permalink lives on `signal_events`, written in the same breath. They share no key,
    so they are matched on (ticker, handle, second) — the pair the writer emits together.
    A post whose link cannot be matched still grades; it just carries a synthetic id.
    """
    conn = await db.get_db()
    where = "WHERE source_type='twitter' AND raw_text IS NOT NULL AND raw_text != ''"
    params: tuple = ()
    if nightly:
        where += " AND detected_at >= ?"
        params = (time.time() - NIGHTLY_LOOKBACK_D * 86400,)

    # OLDEST first, on purpose: only a post whose 30-day window has already elapsed can be
    # graded today, and those are the oldest ones. Classifying newest-first would spend the
    # whole LLM budget on posts that cannot be scored yet.
    cur = await conn.execute(
        f"SELECT id, ticker, source_detail AS handle, raw_text, detected_at "
        f"FROM ticker_signals {where} ORDER BY detected_at ASC", params
    )
    posts = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, source_detail, source_link, recorded_at FROM signal_events "
        "WHERE source_type='twitter' AND source_link IS NOT NULL"
    )
    links = {
        (r["ticker"], r["source_detail"] or "", int(r["recorded_at"] or 0)): r["source_link"]
        for r in await cur.fetchall()
    }
    for p in posts:
        key = (p["ticker"], p["handle"] or "", int(p["detected_at"] or 0))
        p["tweet_url"] = links.get(key) or f"ticker_signals:{p['id']}"
    return posts


async def classify(posts: list[dict], cap: int, use_cache: bool = True) -> tuple[list[dict], int]:
    """Attach catalyst_horizon/kind/likelihood/direction to each post. Returns (posts, n_llm_calls).

    Cached by (handle, ticker, text) so a re-run is free for posts already read. `cap`
    bounds how many NEW posts one run will send to the LLM — the one-time backfill cost
    is therefore bounded and visible, not open-ended.
    """
    from models.text_model import analyze_tweet

    cache = _load_classifications() if use_cache else {}
    calls = 0
    for p in posts:
        key = f"{p['handle']}|{p['ticker']}|{hash(p['raw_text']) & 0xffffffff}"
        hit = cache.get(key)
        if hit is None:
            if calls >= cap:
                p["catalyst_horizon"] = "uncached"   # not classified this run; retry next run
                continue
            try:
                payload = await analyze_tweet(p["raw_text"], p["handle"] or "")
            except Exception as e:                    # LLM down -> fail closed, never crash
                log.warning("classify failed for %s (%s): %s", p["ticker"], p["handle"], e)
                payload = {}
            calls += 1
            hit = {
                "catalyst_horizon": payload.get("catalyst_horizon", "none"),
                "catalyst_kind": payload.get("catalyst_kind", "none"),
                "catalyst_likelihood": float(payload.get("catalyst_likelihood") or 0.0),
                "direction": payload.get("direction", "neutral"),
            }
            cache[key] = hit
        p.update(hit)

    if use_cache and calls:
        _save_classifications(cache)
    return posts, calls


# ──────────────────────────────── grading ────────────────────────────────

def _bonus(bhar: float | None, win: int | None) -> float:
    """Credit scales with HOW FAR the call beat its benchmark, capped so one moonshot
    cannot carry an analyst's record."""
    if not win or bhar is None:
        return 0.0
    return min(BONUS_CAP, BONUS_CAP * abs(bhar) / BONUS_FULL_AT)


async def grade(posts: list[dict], limit: int | None = None) -> dict:
    """Grade every classified post. Returns the run's counters."""
    counters = {
        "short": 0, "long_bets": 0, "graded": 0, "window_open": 0,
        "skipped_unresolvable": 0, "skipped_unclassifiable": 0,
        "skipped_no_catalyst": 0, "skipped_vague_long": 0, "unclassified": 0,
        "unresolvable_tickers": set(),
    }

    scorable: list[dict] = []
    for p in posts:
        horizon = p.get("catalyst_horizon", "none")
        if horizon == "uncached":
            counters["unclassified"] += 1
            continue
        if horizon == "none":
            counters["skipped_unclassifiable"] += 1
            continue
        # Coherence guard: the classifier sometimes says "short" while also saying there is
        # no catalyst kind and zero likelihood (seen on "$SMCI target 1 acquired" — a price
        # target, not an acquisition). A horizon with no catalyst behind it is not a bet.
        if p.get("catalyst_kind", "none") == "none" or float(p.get("catalyst_likelihood") or 0.0) <= 0.0:
            counters["skipped_no_catalyst"] += 1
            continue
        direction = (p.get("direction") or "").lower()
        if direction not in ("long", "short"):
            counters["skipped_no_catalyst"] += 1
            continue
        etf = bg.resolve_benchmark(p["ticker"])
        if not etf:
            counters["skipped_unresolvable"] += 1
            counters["unresolvable_tickers"].add(p["ticker"])
            continue
        p["benchmark_etf"] = etf
        scorable.append(p)
        if limit and len(scorable) >= limit:
            break

    if not scorable:
        return counters

    # One batched, cached yfinance fetch for every ticker + benchmark in the run.
    tickers = sorted({p["ticker"] for p in scorable} | {p["benchmark_etf"] for p in scorable})
    entry_dates = [datetime.fromtimestamp(p["detected_at"], tz=timezone.utc).date()
                   for p in scorable]
    start = min(entry_dates) - timedelta(days=5)
    end = date.today()
    # Deliberately NOT the shared #57 price cache: it is keyed by ticker with no record of
    # which DATES it holds, and its nightly run leaves only a ~9-bar recent window. Reading it
    # here would hand a 21-session grader 9 bars and silently mark every post "still open".
    # The LLM classification cache (the expensive one) is the one worth keeping — see classify().
    bars = fetch_daily_closes(tickers, start, end, use_cache=False)

    conn = await db.get_db()
    now = time.time()
    for p in scorable:
        entry = datetime.fromtimestamp(p["detected_at"], tz=timezone.utc).date().isoformat()
        stock_bars = bars.get(p["ticker"], {})
        bench_bars = bars.get(p["benchmark_etf"], {})
        if not stock_bars or not bench_bars:
            counters["skipped_unresolvable"] += 1
            counters["unresolvable_tickers"].add(p["ticker"])
            continue

        if p["catalyst_horizon"] == "short":
            cps = bg.weekly_checkpoints(stock_bars, bench_bars, entry)
            terminal = cps[bg.BHAR_WINDOW_DAYS]
            win = bg.directional_win(terminal, p["direction"])
            if win is None:
                counters["window_open"] += 1
            else:
                counters["graded"] += 1
            counters["short"] += 1
            await conn.execute(
                """INSERT INTO analyst_catalyst_scores
                   (tweet_url, ticker, handle, direction, catalyst_kind, benchmark_etf,
                    entry_date, bhar_5d, bhar_10d, bhar_15d, bhar_20d, bhar_21d,
                    win, bonus, graded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(tweet_url, ticker) DO UPDATE SET
                     bhar_5d=excluded.bhar_5d, bhar_10d=excluded.bhar_10d,
                     bhar_15d=excluded.bhar_15d, bhar_20d=excluded.bhar_20d,
                     bhar_21d=excluded.bhar_21d, win=excluded.win,
                     bonus=excluded.bonus, graded_at=excluded.graded_at""",
                (p["tweet_url"], p["ticker"], p["handle"], p["direction"],
                 p.get("catalyst_kind"), p["benchmark_etf"], entry,
                 cps[5], cps[10], cps[15], cps[20], cps[21],
                 win, _bonus(terminal, win), now),
            )

        elif p["catalyst_horizon"] == "long":
            if float(p.get("catalyst_likelihood") or 0.0) < LIKELIHOOD_CUTOFF:
                counters["skipped_vague_long"] += 1   # vague -> no bet opened, no resources burned
                continue
            checks = {}
            for n in bg.LONG_TERM_CHECKPOINTS:
                checks[n] = bg.checkpoint_excess_return(stock_bars, bench_bars, entry, n)
            done = sum(1 for v in checks.values() if v is not None)
            status = "closed" if done == len(checks) else ("partial" if done else "open")
            counters["long_bets"] += 1
            await conn.execute(
                """INSERT INTO long_term_catalyst_bets
                   (tweet_url, handle, ticker, direction, catalyst_kind, likelihood,
                    benchmark_etf, entry_date, opened_at, excess_30d, excess_60d, excess_90d,
                    checkpoint_status, last_checked)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(tweet_url, ticker) DO UPDATE SET
                     excess_30d=excluded.excess_30d, excess_60d=excluded.excess_60d,
                     excess_90d=excluded.excess_90d,
                     checkpoint_status=excluded.checkpoint_status,
                     last_checked=excluded.last_checked""",
                (p["tweet_url"], p["handle"], p["ticker"], p["direction"],
                 p.get("catalyst_kind"), float(p.get("catalyst_likelihood") or 0.0),
                 p["benchmark_etf"], entry, p["detected_at"],
                 checks[30], checks[60], checks[90], status, now),
            )

    await conn.commit()
    return counters


# ──────────────────────────────── reporting ────────────────────────────────

def _rate(wins: int, n: int) -> str:
    if n == 0:
        return "—"
    if n < MIN_N:
        return f"{wins}/{n} (thin)"
    return f"{100.0 * wins / n:.1f}% ({wins}/{n})"


async def report() -> str:
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT handle, catalyst_kind, win, bhar_21d, bonus FROM analyst_catalyst_scores "
        "WHERE win IS NOT NULL"
    )
    rows = [dict(r) for r in await cur.fetchall()]
    cur = await conn.execute(
        "SELECT COUNT(*) c, SUM(win IS NULL) open FROM analyst_catalyst_scores")
    tot = dict(await cur.fetchone())
    cur = await conn.execute(
        "SELECT checkpoint_status, COUNT(*) c FROM long_term_catalyst_bets GROUP BY 1")
    bets = {r["checkpoint_status"]: r["c"] for r in await cur.fetchall()}

    out = ["# #55 catalyst scorecard (SHADOW — no live scoring reads this)", ""]
    out.append(f"Short-term rows: {tot['c'] or 0} ({tot['open'] or 0} still inside the 30-day window)")
    out.append(f"Long-term bets: {bets or '{}'}")
    out.append("")
    out.append("WIN = the stock beat its sector/peer ETF over the same 21 sessions, in the")
    out.append("direction the analyst called. Beating the market is not enough.")
    out.append("")

    by_handle: dict[str, list[dict]] = defaultdict(list)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_handle[r["handle"] or "?"].append(r)
        by_kind[r["catalyst_kind"] or "?"].append(r)

    for title, grouped in (("By analyst", by_handle), ("By catalyst kind", by_kind)):
        out += [f"## {title}", "", "| key | win rate | mean BHAR |", "|---|---|---|"]
        for key, rs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            wins = sum(int(r["win"] or 0) for r in rs)
            mean = sum(float(r["bhar_21d"] or 0.0) for r in rs) / len(rs)
            out.append(f"| {key} | {_rate(wins, len(rs))} | {100*mean:+.2f}pp |")
        out.append("")
    out.append(f"_Buckets under {MIN_N} rows show the raw count and no %, so a 2/3 never reads as 67%._")
    return "\n".join(out)


async def run(args) -> int:
    await db.init_db()

    posts = await load_posts(nightly=args.nightly)
    if args.count:
        cut = time.time() - ELAPSED_PAD_DAYS * 86400
        elapsed = [p for p in posts if p["detected_at"] < cut]
        resolvable = [p for p in elapsed if bg.resolve_benchmark(p["ticker"])]
        print(f"stored analyst posts with raw text : {len(posts)}")
        print(f"  ...30-day window fully elapsed   : {len(elapsed)}")
        print(f"  ...and ticker has a benchmark    : {len(resolvable)}  <- classifiable + gradeable now")
        print(f"  ...no benchmark (skipped)        : {len(elapsed) - len(resolvable)}")
        cached = len(_load_classifications())
        print(f"classifications already cached     : {cached} (a re-run costs no LLM calls for these)")
        return 0

    if args.report:
        text = await report()
        print(text)
        if args.out:
            Path(args.out).write_text(text)
        return 0

    if not args.backfill:
        print("nothing to do: pass --count, --backfill or --report")
        return 1

    posts, calls = await classify(posts, cap=args.classify_cap, use_cache=not args.no_cache)
    counters = await grade(posts, limit=args.limit)

    bad = sorted(counters.pop("unresolvable_tickers"))
    log.info("LLM classification calls this run: %d (cap %d)", calls, args.classify_cap)
    print(f"LLM classification calls this run : {calls} (cap {args.classify_cap})")
    for k, v in counters.items():
        print(f"{k:26s}: {v}")
    if bad:
        # Silent skips are the danger: surface exactly what got dropped, every run.
        print(f"unresolvable tickers ({len(bad)}) : {', '.join(bad[:40])}"
              + (" ..." if len(bad) > 40 else ""))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Grade analyst catalyst calls, benchmark-relative (#55).")
    p.add_argument("--backfill", action="store_true", help="classify + grade everything eligible")
    p.add_argument("--nightly", action="store_true", help="only look back NIGHTLY_LOOKBACK_D days")
    p.add_argument("--count", action="store_true", help="report eligibility, no writes, no LLM")
    p.add_argument("--report", action="store_true", help="print the win-rate table")
    p.add_argument("--limit", type=int, default=None, help="cap posts graded")
    p.add_argument("--classify-cap", type=int, default=DEFAULT_CLASSIFY_CAP,
                   dest="classify_cap", help="cap NEW LLM classification calls this run")
    p.add_argument("--no-cache", action="store_true", help="ignore the classification cache (re-ask the LLM)")
    p.add_argument("--out", type=str, default=None, help="write the report to a file too")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
