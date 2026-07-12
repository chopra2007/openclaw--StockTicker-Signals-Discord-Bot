"""#20: does waiting for independent sources to agree BEAT acting on Wolf's raw call?

This is the one measurement that decides whether the timing gate ever goes live.

For every Wolf thesis that ever became actionable (reached imminent/acting), we compare
two entries into the SAME trade:

  RAW   — enter the moment Wolf's thesis turned actionable (today's behaviour).
  GATED — enter only on the day the independent buckets first said "act"
          (>= 2 independent source families agree, >= 1 of them a fast mover).

The gated entry is RECONSTRUCTED, not read from the live table: we replay each day of
the thesis's life, gather only the source rows that existed on or before that day, and
run the real scoring function (wolf_confluence.score_timing). No lookahead.

Both entries are then graded the same way: the proxy's move MINUS its benchmark's over
the same 5 and 20 trading sessions (analysis/benchmark_grading). Excess return, not raw
return — otherwise a rising market flatters whichever entry was earlier.

Honest-negative clause: if GATED does not beat RAW, the gate stays OFF permanently. This
script is run ONCE and its answer is taken. It does not tune the threshold until it passes.

    python3 scripts/wolf_timing_backtest.py            # the A/B table
    python3 scripts/wolf_timing_backtest.py --out report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db  # noqa: E402
from consensus_engine.analysis import benchmark_grading as bg  # noqa: E402
from consensus_engine.analysis import wolf_confluence as wc  # noqa: E402
from consensus_engine.analysis.wolf_outcomes import _anchor_from_evidence  # noqa: E402
from consensus_engine.analysis.wolf_scope import proxy_symbol  # noqa: E402
from grade_options_flow import fetch_daily_closes  # noqa: E402

log = logging.getLogger("wolf_timing_backtest")

MIN_N = 10            # thin-sample rule: never print a mean below this
HORIZONS = (5, 20)    # trading days after entry
WINDOW_DAYS = 21      # the confluence look-back, same as live
MAX_WAIT_DAYS = 30    # if the gate never fires within this, the thesis is "never gated"


async def load_actionable_theses() -> list[dict]:
    """Every thesis that EVER reached imminent/acting — including invalidated ones.

    Invalidated theses are kept on purpose: dropping them would only score the calls that
    survived, which flatters the strategy (survivorship bias) and is exactly how a
    backtest lies.
    """
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT id, scope_type, scope_key, direction, stage, status, has_levels, "
        "created_at, evidence_log_json FROM macro_theses"
    )
    out = []
    for r in await cur.fetchall():
        th = dict(r)
        try:
            evlog = json.loads(th["evidence_log_json"] or "[]")
        except json.JSONDecodeError:
            evlog = []
        anchor_ts, stage = _anchor_from_evidence(evlog)
        if anchor_ts is None:
            continue                      # never became a tradeable call -> not scored
        th["raw_anchor_ts"] = anchor_ts
        th["anchor_stage"] = stage
        out.append(th)
    return out


async def load_history() -> dict[str, list[dict]]:
    """Every roster row with a timestamp, ONCE. The replay then filters this in memory.

    Same source families and the same direction mapping as db.get_confluence_stances
    (wide=True); pulled without a `now` cutoff so any past day can be reconstructed.
    """
    conn = await db.get_db()
    hist: dict[str, list[dict]] = {}

    cur = await conn.execute(
        "SELECT ticker, direction, recorded_at FROM signal_events "
        "WHERE source_type='twitter' AND direction IN ('long','short')")
    hist["twitter"] = [{"ticker": r["ticker"], "dir": r["direction"], "as_of": r["recorded_at"]}
                       for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, direction, extracted_at FROM youtube_signals "
        "WHERE direction IN ('long','short') AND COALESCE(suppressed,0)=0")
    hist["youtube"] = [{"ticker": r["ticker"], "dir": r["direction"], "as_of": r["extracted_at"]}
                       for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, side, COALESCE(last_trade_ts, detected_at) AS as_of FROM options_flow")
    hist["options"] = [{"ticker": r["ticker"], "dir": r["side"], "as_of": r["as_of"]}
                       for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, sentiment, detected_at FROM ticker_signals "
        "WHERE source_type='sec_filing' AND sentiment='bullish'")
    hist["sec"] = [{"ticker": r["ticker"], "dir": r["sentiment"], "as_of": r["detected_at"]}
                   for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, put_call_vol_ratio, captured_at FROM schwab_options_snapshots")
    rows = []
    for r in await cur.fetchall():
        pcr = r["put_call_vol_ratio"]
        if pcr is None:
            continue
        side = "long" if pcr < 0.9 else ("short" if pcr > 1.1 else None)
        if side:
            rows.append({"ticker": r["ticker"], "dir": side, "as_of": r["captured_at"]})
    hist["schwab_options"] = rows

    cur = await conn.execute("SELECT ticker, alerted_at FROM form4_clusters")
    hist["form4"] = [{"ticker": r["ticker"], "dir": "bullish", "as_of": r["alerted_at"]}
                     for r in await cur.fetchall()]

    cur = await conn.execute("SELECT etf, quadrant, computed_at FROM sector_rs_daily")
    rows = []
    for r in await cur.fetchall():
        q = (r["quadrant"] or "").lower()
        side = "long" if q in ("leading", "improving") else ("short" if q in ("lagging", "weakening") else None)
        if side:
            rows.append({"ticker": r["etf"], "dir": side, "as_of": r["computed_at"]})
    hist["sector_rs"] = rows

    return hist


def as_of_rows(hist: dict[str, list[dict]], at_ts: float) -> dict[str, list[dict]]:
    """The roster exactly as it looked at `at_ts` — nothing from the future, nothing stale."""
    lo = at_ts - WINDOW_DAYS * 86400
    return {
        key: [r for r in rows if r["as_of"] and lo <= float(r["as_of"]) <= at_ts]
        for key, rows in hist.items()
    }


def find_gated_anchor(thesis: dict, hist: dict[str, list[dict]]) -> float | None:
    """First timestamp the buckets would have said 'act', walking forward one day at a time.

    Returns None when the gate never fired within MAX_WAIT_DAYS — that thesis is a trade
    the gated strategy simply never takes, which is itself part of the answer.
    """
    start = float(thesis["raw_anchor_ts"])
    for day in range(MAX_WAIT_DAYS + 1):
        at = start + day * 86400
        if at > time.time():
            return None
        verdict, _, _, _ = wc.score_timing(thesis, as_of_rows(hist, at))
        if verdict == "act":
            return at
    return None


def excess_at(bars: dict, proxy: str, bench: str, anchor_ts: float, n: int) -> float | None:
    """Proxy minus benchmark over the n trading sessions after the anchor date."""
    entry = datetime.fromtimestamp(anchor_ts, tz=timezone.utc).date().isoformat()
    return bg.buy_and_hold_abnormal_return(bars.get(proxy, {}), bars.get(bench, {}), entry, n)


def _signed(x: float | None, direction: str) -> float | None:
    """Flip the sign for a bear thesis so 'positive = the call worked' in both directions."""
    if x is None:
        return None
    return x if (direction or "").lower() == "bull" else -x


def _fmt(vals: list[float]) -> str:
    if len(vals) < MIN_N:
        return f"n={len(vals)} (thin — no mean shown)"
    return f"{100*statistics.fmean(vals):+.2f}pp (n={len(vals)})"


async def run(out_path: str | None) -> int:
    await db.init_db()
    theses = await load_actionable_theses()
    hist = await load_history()
    log.info("actionable theses: %d", len(theses))

    rows = []
    for th in theses:
        proxy = proxy_symbol(th["scope_type"], th["scope_key"])
        if not proxy:
            continue
        bench = await bg.resolve_benchmark_dynamic(proxy) or "SPY"
        if bench == proxy:
            bench = "SPY"          # an ETF thesis is graded against the market
        if proxy == "SPY":
            continue               # nothing to be excess OF
        gated_ts = find_gated_anchor(th, hist)
        rows.append({
            "id": th["id"], "scope": f'{th["scope_type"]}:{th["scope_key"]}',
            "dir": th["direction"], "proxy": proxy, "bench": bench,
            "raw_ts": th["raw_anchor_ts"], "gated_ts": gated_ts,
        })

    if not rows:
        print("no actionable theses with a tradeable proxy — nothing to measure")
        return 0

    tickers = sorted({r["proxy"] for r in rows} | {r["bench"] for r in rows})
    start = datetime.fromtimestamp(min(r["raw_ts"] for r in rows), tz=timezone.utc).date() \
        - timedelta(days=5)
    # use_cache=False is REQUIRED, not an optimisation. #57's shared price cache is keyed by
    # ticker with no record of WHICH dates it holds, and its nightly run stores only a ~9-bar
    # recent window. Reusing it here silently returned 9 bars per ticker, so every 20-session
    # window came back "not elapsed yet" and the whole backtest read n=0. Always fetch fresh.
    bars = fetch_daily_closes(tickers, start, date.today(), use_cache=False)

    raw: dict[int, list[float]] = {n: [] for n in HORIZONS}
    gated: dict[int, list[float]] = {n: [] for n in HORIZONS}
    paired: dict[int, list[tuple[float, float]]] = {n: [] for n in HORIZONS}
    n_gated = sum(1 for r in rows if r["gated_ts"])

    for r in rows:
        for n in HORIZONS:
            rv = _signed(excess_at(bars, r["proxy"], r["bench"], r["raw_ts"], n), r["dir"])
            gv = (_signed(excess_at(bars, r["proxy"], r["bench"], r["gated_ts"], n), r["dir"])
                  if r["gated_ts"] else None)
            if rv is not None:
                raw[n].append(rv)
            if gv is not None:
                gated[n].append(gv)
            if rv is not None and gv is not None:
                paired[n].append((rv, gv))   # same thesis, both entries -> the fair comparison

    lines = ["# #20 timing backtest — raw-Wolf entry vs confluence-gated entry", ""]
    lines.append(f"Theses that ever became actionable : {len(rows)}")
    lines.append(f"...where the gate ever said 'act'  : {n_gated}"
                 f"  ({len(rows)-n_gated} trades the gated strategy never takes)")
    lines.append("")
    lines.append("Numbers are EXCESS return: the proxy's move minus its benchmark's over the")
    lines.append("same sessions, sign-flipped for bear theses so positive always = the call worked.")
    lines.append("")
    lines.append("| horizon | raw-Wolf entry | confluence-gated entry | gated − raw (same theses) |")
    lines.append("|---|---|---|---|")
    for n in HORIZONS:
        if len(paired[n]) < MIN_N:
            delta = f"n={len(paired[n])} (thin)"
        else:
            d = statistics.fmean([g - rr for rr, g in paired[n]])
            delta = f"{100*d:+.2f}pp (n={len(paired[n])})"
        lines.append(f"| {n}d | {_fmt(raw[n])} | {_fmt(gated[n])} | {delta} |")
    lines.append("")
    lines.append(f"_Under {MIN_N} paired theses nothing is averaged — a 2-of-3 must never read as 67%._")
    lines.append("")
    lines.append("**Decision rule (pre-registered):** the gate goes live ONLY if `gated − raw` is")
    lines.append("positive at n >= 10. Otherwise `wolf.confluence.timing.enabled` stays OFF")
    lines.append("permanently and this negative result is the outcome. No threshold re-tuning.")

    text = "\n".join(lines)
    print(text)
    if out_path:
        Path(out_path).write_text(text)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="#20: is the confluence-gated entry better than Wolf's raw call?")
    p.add_argument("--out", type=str, default=None, help="also write the report here")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
