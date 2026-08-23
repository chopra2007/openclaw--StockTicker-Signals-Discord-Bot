#!/usr/bin/env python3
"""Lane A -- one-shot analysis of the eval-period frozen-rule outcomes.
Read-only against the JSON files eval-run already wrote. No re-pulls, no
re-freezing of thresholds. Prints the numbers the builder verdict quotes."""
import json
import statistics
from pathlib import Path

OUT = Path(".omc/research/event-reaction-short-duration")
cat = json.loads((OUT / "lane_a_catalyst_outcomes.json").read_text())
ctrl = json.loads((OUT / "lane_a_control_outcomes.json").read_text())


def signed(r):
    v = r.get("mkt_adj_ret_60m_pct")
    if v is None:
        return None
    return v if r["trade_direction"] == "up" else -v


def signed30(r):
    v = r.get("mkt_adj_ret_30m_pct")
    if v is None:
        return None
    return v if r["trade_direction"] == "up" else -v


def wilson_ci(wins, n, z=1.96):
    if n == 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return round(max(0.0, (center - margin) / denom) * 100, 1), round(min(1.0, (center + margin) / denom) * 100, 1)


def z_two_prop(w1, n1, w2, n2):
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = w1 / n1, w2 / n2
    p_pool = (w1 + w2) / (n1 + n2)
    se = (p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) ** 0.5
    if se == 0:
        return None
    return round((p1 - p2) / se, 3)


def summarize(rows, label):
    n = len(rows)
    have60 = [r for r in rows if signed(r) is not None]
    wins60 = [r for r in have60 if signed(r) > 0]
    have30 = [r for r in rows if signed30(r) is not None]
    wins30 = [r for r in have30 if signed30(r) > 0]
    pnl = [r["pnl_per_100_risk_dollars"] for r in rows if r.get("pnl_per_100_risk_dollars") is not None]
    mkt60 = sorted(signed(r) for r in have60)
    print(f"\n--- {label} (n={n}) ---")
    print(f"  60min directional success (mkt-adj, sign-matched to trade_direction): "
          f"{len(wins60)}/{len(have60)} = {len(wins60)/len(have60)*100:.1f}% "
          f"Wilson95%CI={wilson_ci(len(wins60), len(have60))}")
    print(f"  30min directional success: {len(wins30)}/{len(have30)} = "
          f"{len(wins30)/len(have30)*100:.1f}%" if have30 else "  30min: n=0")
    print(f"  mkt-adj 60min return (signed, %): mean={statistics.mean(mkt60):.2f} "
          f"median={statistics.median(mkt60):.2f} stdev={statistics.pstdev(mkt60):.2f} "
          f"min={mkt60[0]:.2f} max={mkt60[-1]:.2f}")
    print(f"  pnl per $100 risk: n={len(pnl)} mean=${statistics.mean(pnl):.2f} "
          f"median=${statistics.median(pnl):.2f} sum=${sum(pnl):.2f}")
    from collections import Counter
    print(f"  target/stop outcome: {dict(Counter(r['target_stop_outcome'] for r in rows if r.get('target_stop_outcome')))}")
    tickers = Counter(r["ticker"] for r in rows)
    print(f"  distinct tickers: {len(tickers)}, top5 by count: {tickers.most_common(5)}")
    return {"n": n, "wins60": len(wins60), "have60": len(have60), "mkt60": mkt60, "pnl": pnl, "rows": rows}


for period in ("dev", "eval"):
    cat_p = [r for r in cat if r["period"] == period]
    ctrl_p = [r for r in ctrl if r["period"] == period]
    print(f"\n===================== {period.upper()} PERIOD =====================")
    print("BALANCE CHECK (before outcomes):")
    print(f"  N catalyst={len(cat_p)} N control={len(ctrl_p)}")
    if cat_p and ctrl_p:
        rv_c = sorted(r["rvol_30m"] for r in cat_p)
        rv_k = sorted(r["rvol_30m"] for r in ctrl_p)
        mv_c = sorted(abs(r["initial_reaction_pct"]) for r in cat_p)
        mv_k = sorted(abs(r["initial_reaction_pct"]) for r in ctrl_p)
        print(f"  rvol_30m median: catalyst={statistics.median(rv_c):.1f} control={statistics.median(rv_k):.1f}")
        print(f"  |initial_reaction_pct| median: catalyst={statistics.median(mv_c):.1f} control={statistics.median(mv_k):.1f}")
        cat_tickers = {r["ticker"] for r in cat_p}
        ctrl_tickers = {r["ticker"] for r in ctrl_p}
        overlap = cat_tickers & ctrl_tickers
        print(f"  distinct tickers: catalyst={len(cat_tickers)} control={len(ctrl_tickers)} overlap={len(overlap)}")
        print(f"  date range: catalyst {min(r['entry_day'] for r in cat_p)}..{max(r['entry_day'] for r in cat_p)}  "
              f"control {min(r['entry_day'] for r in ctrl_p)}..{max(r['entry_day'] for r in ctrl_p)}")

    cs = summarize(cat_p, f"{period} catalyst (frozen qualifying rule)")
    ks = summarize(ctrl_p, f"{period} control (same-ticker, no earnings, matched rvol/move)")

    if cat_p and ctrl_p:
        z = z_two_prop(cs["wins60"], cs["have60"], ks["wins60"], ks["have60"])
        print(f"\n  z-test (60min directional success, catalyst vs control): z={z}")
        # drop largest-|effect| event and recompute
        if cs["rows"]:
            biggest = max(cs["rows"], key=lambda r: abs(signed(r)) if signed(r) is not None else 0)
            print(f"  largest-|effect| catalyst event: {biggest['ticker']} {biggest['entry_day']} "
                  f"signed_mkt_adj_60m={signed(biggest)}")
            rest = [r for r in cs["rows"] if r is not biggest]
            rest60 = [signed(r) for r in rest if signed(r) is not None]
            if rest60:
                print(f"  mean mkt-adj 60min WITHOUT that event: {statistics.mean(rest60):.2f} "
                      f"(vs {statistics.mean(cs['mkt60']):.2f} with it)")
