#!/usr/bin/env python3
"""Read-only E6 backtest — how often the manufactured-agreement gate would fire, with
EVENT-TIME corroboration ordering (per Codex review).

E6 (cross_reference.py:1574-1629) only acts when consensus_boost > 0 AND a near-duplicate
analyst burst (Jaccard>=0.6, >=2 distinct accounts, 300s window) has NO independent
corroborator (sec / news catalyst / options). It then zeroes consensus_boost (dampening-only).

This replays stored `source_type='twitter'` signals, slides the 300s window per ticker, and for
every detected burst classifies the SEC corroborator by event time:
   (a) sec_filing present at/before burst time  -> gate LIFTED (correct)
   (b) sec_filing present only AFTER burst time  -> would have gated live (late corroborator)
   (d) no sec_filing for the ticker ever         -> gate depends on news/options (unknown here)

Honest limits (stated, not hidden): news_catalyst + options corroboration are NOT in
ticker_signals (they live in decision_snapshots only), so they cannot be event-time-ordered from
stored data. Therefore the "would-gate" count here is an UPPER BOUND — real runtime may have had
news/options corroboration that lifts the gate. Raw counts only; if gated n<10, every one is listed.
"""
import asyncio
import sys

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")
from consensus_engine import config as cfg, db
from consensus_engine.cross_reference import _analyse_burst, _E6_SIMILARITY_DEFAULT, _E6_BURST_WINDOW_SEC_DEFAULT, _E6_MIN_ACCOUNTS_DEFAULT


async def main() -> None:
    cfg.load_config()
    await db.init_db()
    conn = await db.get_db()

    sim = float(cfg.get("features.manufactured_agreement_gate.similarity_threshold", _E6_SIMILARITY_DEFAULT))
    win = int(cfg.get("features.manufactured_agreement_gate.burst_window_sec", _E6_BURST_WINDOW_SEC_DEFAULT))
    minacc = int(cfg.get("features.manufactured_agreement_gate.min_accounts", _E6_MIN_ACCOUNTS_DEFAULT))
    print(f"=== E6 backtest (similarity>={sim}, window={win}s, min_accounts={minacc}) ===\n")

    # All twitter signals, grouped by ticker.
    cur = await conn.execute(
        "SELECT ticker, source_detail, raw_text, detected_at FROM ticker_signals "
        "WHERE source_type='twitter' AND raw_text IS NOT NULL ORDER BY ticker, detected_at"
    )
    rows = [dict(r) for r in await cur.fetchall()]
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    tickers_scanned = len(by_ticker)
    bursts = 0
    burst_events = []  # (ticker, burst_time, accounts)
    for tk, sigs in by_ticker.items():
        sigs.sort(key=lambda r: float(r["detected_at"]))
        n = len(sigs)
        # Slide a window: for each anchor i, take rows within `win` seconds and run the real detector.
        i = 0
        last_burst_end = -1.0
        while i < n:
            t0 = float(sigs[i]["detected_at"])
            window_rows = [s for s in sigs[i:] if float(s["detected_at"]) - t0 <= win]
            detected, accounts = _analyse_burst(window_rows, similarity_threshold=sim, burst_window_sec=win, min_accounts=minacc)
            if detected and t0 > last_burst_end:  # avoid double-counting overlapping windows
                bursts += 1
                burst_events.append((tk, t0, accounts))
                last_burst_end = t0 + win
            i += 1

    print(f"twitter signals: {len(rows)} across {tickers_scanned} tickers")
    print(f"bursts detected (real _analyse_burst, default thresholds): {bursts}\n")

    if bursts == 0:
        print("VERDICT: E6 detects ZERO bursts in all stored twitter history at default thresholds.")
        print("  -> Flipping E6 ON is a near-no-op on stored data (no manufactured-agreement clusters seen).")
        print("  -> Shadow mode will confirm this live; gate cannot suppress legit consensus it never fires on.")
        return

    # Event-time SEC corroboration per burst.
    gated_upper = corr_at_gate = corr_late = 0
    gated_samples = []
    for tk, t0, accounts in burst_events:
        cur = await conn.execute(
            "SELECT MIN(detected_at) FROM ticker_signals WHERE ticker=? AND source_type='sec_filing'",
            (tk,),
        )
        first_sec = (await cur.fetchone())[0]
        if first_sec is not None and float(first_sec) <= t0:
            corr_at_gate += 1
        elif first_sec is not None:
            corr_late += 1
            gated_upper += 1
            gated_samples.append((tk, round(t0, 0), len(accounts), "sec-late"))
        else:
            gated_upper += 1
            gated_samples.append((tk, round(t0, 0), len(accounts), "no-sec(news/options unknown)"))

    ratio = gated_upper / bursts if bursts else 0
    print("Event-time SEC corroboration:")
    print(f"  burst with sec at/before gate (gate LIFTED): {corr_at_gate}")
    print(f"  burst with sec only AFTER gate (late):       {corr_late}")
    print(f"  burst with NO sec ever:                      {gated_upper - corr_late}")
    print(f"  -> would-gate UPPER BOUND (no sec at gate):  {gated_upper}/{bursts} = {ratio:.0%}")
    print(f"     (UPPER BOUND: news/options corroboration not event-time-reconstructable; real gating <= this)")
    if gated_upper < 10:
        print("  gated samples (n<10, all listed):")
        for s in gated_samples:
            print("    ", s)
    print()
    print(f"PASS criterion (Codex): would-gate <= 20%. Observed upper bound = {ratio:.0%}.")


if __name__ == "__main__":
    asyncio.run(main())
