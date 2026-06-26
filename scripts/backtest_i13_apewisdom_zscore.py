#!/usr/bin/env python3
"""Read-only I13 backtest — blast radius of flipping features.apewisdom_zscore ON.

Structural fact (cross_reference.py:213-223): with the flag OFF, social_apewisdom = 10 for
ANY ApeWisdom-listed ticker (flat presence boost). With the flag ON it becomes the z-score
gate, returning 10 ONLY when (1) >=14 distinct baseline days, (2) today's mentions >2 sigma
above the per-ticker baseline mean, (3) a hard corroborator agrees (sec/catalyst/tech>=2),
(4) data is fresh. So ON can only LOWER or keep the term vs OFF — I13 can NEVER raise a score,
create an alert, or promote a tier. The only risk is DEMOTION of a currently-firing alert that
loses its flat +10 and crosses below the high-confidence cutoff.

This script reports, from STORED data only (no live-classifier join onto old rows):
  PART A — Today-snapshot selectivity: of the baseline-ready tickers, how many would actually
           earn +10 under I13 RIGHT NOW (z-pass AND corroborator) — i.e. how selective the gate is.
  PART B — Demotion bound on stored STRONG_ALERTs: how many carry the flat +10, how many sit in
           the threshold-vulnerable band [high, high+9] where losing 10 crosses below the cutoff,
           and of those how many had a hard corroborator in their own sources_json.

Honest framing (per Codex review): PART B is specific to the stored population and is an UPPER
BOUND — instant-trigger/bypass STRONG_ALERTs in the band would not actually demote, and any with a
real surge+corroborator at scoring time would keep the +10. We do NOT claim a universal zero.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")
from consensus_engine import config as cfg, db


async def main() -> None:
    cfg.load_config()
    await db.init_db()
    conn = await db.get_db()

    high = int(cfg.get("precision_engine.thresholds.high_confidence", 80))
    min_days = int(cfg.get("features.apewisdom_zscore.min_baseline_days", 14))
    z_thr = float(cfg.get("features.apewisdom_zscore.z_threshold", 2.0))
    print(f"=== I13 backtest (high_cutoff={high}, min_baseline_days={min_days}, z_threshold={z_thr}) ===\n")

    # ---------------------------------------------------------------- PART A
    # Today-snapshot selectivity: how many currently-listed tickers would earn +10 under I13 now.
    cur = await conn.execute(
        "SELECT DISTINCT ticker FROM apewisdom_mentions "
        "WHERE captured_at > (SELECT MAX(captured_at) FROM apewisdom_mentions) - 86400"
    )
    listed = [r["ticker"] for r in await cur.fetchall()]

    baseline_ready = z_pass = 0
    z_pass_tickers = []
    for tk in listed:
        baseline = await db.get_apewisdom_baseline(tk)
        latest = await db.get_latest_apewisdom_mentions(tk)
        if not baseline or not latest:
            continue
        if int(baseline.get("sample_days", 0)) < min_days:
            continue
        baseline_ready += 1
        std = float(baseline.get("std", 0.0))
        if std <= 0:
            continue
        z = (int(latest["mentions"]) - float(baseline.get("mean", 0.0))) / std
        if z > z_thr:
            z_pass += 1
            z_pass_tickers.append((tk, round(z, 2), int(latest["mentions"])))

    print("PART A — today-snapshot selectivity")
    print(f"  ApeWisdom-listed (last 24h):        {len(listed)}")
    print(f"  baseline-ready (>= {min_days} days):       {baseline_ready}")
    print(f"  z-surge now (> {z_thr} sigma):            {z_pass}")
    print(f"  -> would earn +10 only WITH a live corroborator at scoring time (subset of z-pass).")
    if z_pass_tickers:
        print("  z-surge tickers:", ", ".join(f"{t}(z={z},m={m})" for t, z, m in sorted(z_pass_tickers, key=lambda x: -x[1])[:15]))
    print()

    # ---------------------------------------------------------------- PART B
    # Demotion bound on stored STRONG_ALERTs carrying the flat +10.
    cur = await conn.execute(
        "SELECT ticker, sources_json, recorded_at FROM decision_snapshots "
        "WHERE decision='STRONG_ALERT'"
    )
    rows = [dict(r) for r in await cur.fetchall()]

    carriers = band = band_with_corr = band_no_corr = 0
    below_cut_already = 0  # total < high -> fired via instant-trigger/bypass, not threshold
    band_no_corr_samples = []
    for r in rows:
        try:
            s = json.loads(r["sources_json"] or "{}")
        except Exception:
            continue
        aw = int(s.get("social_apewisdom", 0) or 0)
        if aw < 10:
            continue
        carriers += 1
        total = int(s.get("total", 0) or 0)
        if total < high:
            below_cut_already += 1  # not threshold-classified; +10 removal can't un-fire it
            continue
        if high <= total <= high + 9:  # losing 10 crosses below the cutoff
            band += 1
            has_corr = int(s.get("sec_filing", 0) or 0) > 0 or int(s.get("news_catalyst", 0) or 0) > 0 or int(s.get("options_flow", 0) or 0) > 0
            if has_corr:
                band_with_corr += 1
            else:
                band_no_corr += 1
                band_no_corr_samples.append((r["ticker"], total))

    print("PART B — demotion bound on stored STRONG_ALERTs")
    print(f"  STRONG_ALERTs total:                         {len(rows)}")
    print(f"  ...carrying the flat +10:                    {carriers}")
    print(f"  ...total < {high} (instant-trigger/bypass; +10 can't un-fire): {below_cut_already}")
    print(f"  ...in threshold band [{high},{high+9}] (could cross cutoff):   {band}")
    print(f"        of band: had a hard corroborator (likely keep +10):  {band_with_corr}")
    print(f"        of band: NO corroborator in sources_json (would lose +10 -> demote): {band_no_corr}")
    if band_no_corr_samples:
        print("        demotion-candidate samples (ticker,total):", band_no_corr_samples)
    print()
    print("VERDICT INPUTS:")
    print(f"  - I13 can never create/promote an alert (structural).")
    print(f"  - Worst-case user-facing STRONG demotions from stored data: {band_no_corr} "
          f"(raw count; demoting a meme-noise-inflated STRONG is the intended precision gain).")
    print(f"  - Going-forward, I13 fires +10 for at most {z_pass} of {baseline_ready} baseline-ready tickers today (pre-corroborator).")


if __name__ == "__main__":
    asyncio.run(main())
