"""W3 shadow-mode review — tells you whether to flip score_v2 live.

Parses `score_shadow` log lines emitted by `rank_anchors` (W3), groups them
by `!all` invocation (ticker + nearest timestamp window), and reports:

  * How many tickers the v2 ranking would have changed
  * Which prices would have shifted at SL / TP1 / TP2 / TP3
  * Average delta by source tier (yt_curated, swing, yt, web)
  * A flip/wait recommendation

Run after the engine has logged ~7 days of shadow data:

    python3 -m scripts.score_shadow_review
    python3 -m scripts.score_shadow_review --log /path/to/consensus_engine.log
    python3 -m scripts.score_shadow_review --since 7d
    python3 -m scripts.score_shadow_review --ticker NVDA  # focused report

The flip decision is YOURS — this script summarises evidence, you make
the call to set `all_command.score_v2_shadow_mode: false` in config.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_LOG = Path("/home/openclaw/.openclaw/workspace/consensus_engine.log")

# Matches the W3+ log line shape:
#   2026-05-11 21:23:35,686 [INFO] consensus_engine.alerts.all_command.levels:
#   score_shadow ticker=NVDA current_price=219.44 anchor_price=110.00
#   source_type=yt score_v1=14.00 score_v2=7.78 delta=-6.22 distance_pct=0.4980
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\[INFO\]"
    r".*score_shadow ticker=(?P<ticker>\S+) "
    r"current_price=(?P<current_price>[\d.]+) "
    r"anchor_price=(?P<anchor_price>[\d.]+) "
    r"source_type=(?P<source_type>\S+) "
    r"score_v1=(?P<v1>-?\d+\.\d+) "
    r"score_v2=(?P<v2>-?\d+\.\d+) "
    r"delta=(?P<delta>-?\d+\.\d+) "
    r"distance_pct=(?P<distance_pct>\S+)"
)


def parse_since(arg: str) -> datetime | None:
    """`7d` / `24h` / `30m` / ISO date → cutoff datetime."""
    if not arg:
        return None
    now = datetime.now(timezone.utc)
    if arg.endswith("d"):
        return now - timedelta(days=int(arg[:-1]))
    if arg.endswith("h"):
        return now - timedelta(hours=int(arg[:-1]))
    if arg.endswith("m"):
        return now - timedelta(minutes=int(arg[:-1]))
    return datetime.fromisoformat(arg).replace(tzinfo=timezone.utc)


def parse_log(log_path: Path, since: datetime | None, ticker_filter: str | None):
    """Yield parsed event dicts from the engine log."""
    if not log_path.exists():
        print(f"error: log not found at {log_path}", file=sys.stderr)
        sys.exit(2)
    with log_path.open("r", errors="replace") as f:
        for line in f:
            m = _LINE_RE.search(line)
            if not m:
                continue
            ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if since and ts < since:
                continue
            if ticker_filter and m["ticker"].upper() != ticker_filter.upper():
                continue
            yield {
                "ts": ts,
                "ticker": m["ticker"],
                "current_price": float(m["current_price"]),
                "anchor_price": float(m["anchor_price"]),
                "source_type": m["source_type"],
                "v1": float(m["v1"]),
                "v2": float(m["v2"]),
                "delta": float(m["delta"]),
                "distance_pct": m["distance_pct"],
            }


def group_invocations(events):
    """Group events into `!all` invocations.

    A single rank_anchors call emits N consecutive score_shadow lines for the
    same ticker within ~1s. We group by (ticker, timestamp bucket: rounded to
    nearest 2 seconds) to coalesce one invocation per group.
    """
    groups: dict[tuple, list] = defaultdict(list)
    for e in events:
        bucket = e["ts"].replace(microsecond=0)
        # round to even second so calls split across 2-second window stay grouped
        bucket = bucket.replace(second=(bucket.second // 2) * 2)
        groups[(e["ticker"], bucket)].append(e)
    return groups


def winner_for_side(anchors, side: str, score_key: str):
    """Pick the top-scoring anchor on the given side (supports below / resistances above)."""
    if not anchors:
        return None
    pool = []
    for a in anchors:
        cp = a["current_price"]
        if side == "support" and a["anchor_price"] < cp:
            pool.append(a)
        elif side == "resistance" and a["anchor_price"] > cp:
            pool.append(a)
    if not pool:
        return None
    return max(pool, key=lambda a: a[score_key])


def compare_top_n(anchors, side: str, n: int = 3):
    """Return ((v1_prices...), (v2_prices...)) for the top-N ranked anchors on `side`."""
    pool = []
    for a in anchors:
        cp = a["current_price"]
        if side == "support" and a["anchor_price"] < cp:
            pool.append(a)
        elif side == "resistance" and a["anchor_price"] > cp:
            pool.append(a)
    v1_ranked = sorted(pool, key=lambda a: a["v1"], reverse=True)[:n]
    v2_ranked = sorted(pool, key=lambda a: a["v2"], reverse=True)[:n]
    return (
        tuple(a["anchor_price"] for a in v1_ranked),
        tuple(a["anchor_price"] for a in v2_ranked),
    )


def report(groups):
    if not groups:
        print("No score_shadow events parsed. Run !all on some tickers and re-check.")
        return 1

    total = 0
    sl_changed = 0
    tp1_changed = 0
    any_change = 0
    by_tier: dict[str, list] = defaultdict(list)
    changed_tickers: list[tuple[str, str, list, list]] = []

    for (ticker, _bucket), evs in groups.items():
        total += 1
        v1_sl, v2_sl = compare_top_n(evs, "support", n=1)
        v1_tp, v2_tp = compare_top_n(evs, "resistance", n=3)
        sl_diff = v1_sl != v2_sl
        tp_diff = v1_tp != v2_tp
        if sl_diff:
            sl_changed += 1
        if tp_diff:
            tp1_changed += 1
        if sl_diff or tp_diff:
            any_change += 1
            changed_tickers.append((ticker, "SL+TP" if sl_diff and tp_diff else
                                    "SL" if sl_diff else "TP",
                                    list(v1_sl) + list(v1_tp),
                                    list(v2_sl) + list(v2_tp)))
        for e in evs:
            by_tier[e["source_type"]].append(e["delta"])

    print("=== Shadow Review Report ===")
    print(f"Tickers analyzed   : {total}")
    print(f"Would change SL    : {sl_changed} ({sl_changed/total*100:.0f}%)")
    print(f"Would change TPs   : {tp1_changed} ({tp1_changed/total*100:.0f}%)")
    print(f"Any change in plan : {any_change} ({any_change/total*100:.0f}%)")
    print()
    print("Average score delta by source tier (v2 - v1):")
    for tier, deltas in sorted(by_tier.items()):
        avg = sum(deltas) / len(deltas)
        print(f"  {tier:12s}  n={len(deltas):4d}  avg_delta={avg:+8.2f}")
    print()

    if changed_tickers:
        print("Sample of tickers where v2 ranking would change (first 10):")
        for ticker, kind, v1, v2 in changed_tickers[:10]:
            v1_s = ", ".join(f"${p:.2f}" for p in v1) or "—"
            v2_s = ", ".join(f"${p:.2f}" for p in v2) or "—"
            print(f"  {ticker:8s} {kind:6s}  v1=[{v1_s}]  v2=[{v2_s}]")
        print()

    change_rate = any_change / total * 100
    print("--- Recommendation ---")
    if change_rate <= 15:
        print(f"  change rate {change_rate:.0f}% is low — v2 mostly agrees with v1.")
        print("  SAFE TO FLIP: set all_command.score_v2_shadow_mode: false")
    elif change_rate <= 50:
        print(f"  change rate {change_rate:.0f}% is moderate — v2 reorders a meaningful")
        print("  share of plans. Spot-check the sample above against your judgment.")
        print("  Likely safe to flip once you've sanity-checked 3-5 of the changed tickers.")
    else:
        print(f"  change rate {change_rate:.0f}% is HIGH — v2 disagrees with v1 on more")
        print("  than half the tickers. Either the distance penalty α=4 is too aggressive,")
        print("  or the trust scores need calibration. Inspect the per-tier deltas first.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--since", default="7d",
                   help="Time window: 7d / 24h / 30m / ISO date (default: 7d)")
    p.add_argument("--ticker", default=None,
                   help="Filter to a single ticker")
    args = p.parse_args()

    cutoff = parse_since(args.since)
    events = list(parse_log(args.log, cutoff, args.ticker))
    if not events:
        print(f"No score_shadow events found in {args.log} since {cutoff}.")
        print("Either the engine hasn't logged any yet, or the log path / window is wrong.")
        return 1
    groups = group_invocations(events)
    return report(groups)


if __name__ == "__main__":
    sys.exit(main())
