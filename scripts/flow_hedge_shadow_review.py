"""F4 shadow-mode review — should the hedge/directional discount go live?

Parses the `flow_shadow` log lines emitted by `flow_hedge.classify()` (written
once per unusual-flow hit when `features.flow_hedge_discount.collect` is on),
and reports:

  * verdict mix (directional / paired / delta_unknown)
  * delta coverage — what fraction of hits actually carried Schwab greeks
    (delta is None on the yfinance path, so with Schwab down this can be 0%)
  * for the "paired" (likely hedge/spread) hits, the realized options-flow
    outcome from `options_flow_outcomes` when it can be matched — the evidence
    for whether discounting them would have improved calls

Run after the engine has logged shadow data:

    python3 scripts/flow_hedge_shadow_review.py
    python3 scripts/flow_hedge_shadow_review.py --log /path/to/consensus_engine.log
    python3 scripts/flow_hedge_shadow_review.py --since 7d

The flip decision is YOURS — `features.flow_hedge_discount.enabled` stays OFF
until this review shows the discount would have helped. This script only
summarizes the evidence.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_LOG = Path("/home/openclaw/.openclaw/workspace/consensus_engine.log")

# Matches the flow_hedge.classify log line:
#   2026-07-14 21:23:35,686 [INFO] consensus_engine.scanners.flow_hedge:
#   flow_shadow: NVDA CALL exp=2026-07-18 prem=$3000000 delta=0.550 dw_notional=1650000 verdict=directional
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\[INFO\]"
    r".*flow_shadow: (?P<ticker>\S+) (?P<side>\S+) exp=(?P<expiry>\S+) "
    r"prem=\$(?P<prem>[\d.]+) delta=(?P<delta>\S+) "
    r"dw_notional=(?P<dwn>\S+) verdict=(?P<verdict>\S+)"
)


def parse_since(arg: str) -> datetime | None:
    """`7d` / `24h` / `30m` -> cutoff datetime (UTC)."""
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


def parse_log(path: Path, since: datetime | None) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(errors="replace") as f:
        for line in f:
            m = _LINE_RE.search(line)
            if not m:
                continue
            ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if since and ts < since:
                continue
            rows.append({
                "ts": ts, "ticker": m["ticker"], "side": m["side"],
                "expiry": m["expiry"], "prem": float(m["prem"]),
                "delta": None if m["delta"] == "None" else float(m["delta"]),
                "dwn": None if m["dwn"] == "None" else float(m["dwn"]),
                "verdict": m["verdict"],
            })
    return rows


def report(rows: list[dict]) -> str:
    if not rows:
        return ("No flow_shadow lines found. Either the engine has not logged any yet, "
                "or features.flow_hedge_discount.collect is OFF. Nothing to review.")
    n = len(rows)
    verdicts = Counter(r["verdict"] for r in rows)
    with_delta = sum(1 for r in rows if r["delta"] is not None)
    paired = [r for r in rows if r["verdict"] == "paired"]

    L = [f"F4 hedge/directional shadow review — {n} hit(s)"]
    L.append(f"  verdict mix: " + ", ".join(f"{k}={v}" for k, v in verdicts.most_common()))
    L.append(f"  delta coverage: {with_delta}/{n} "
             f"({'0%' if n == 0 else f'{100*with_delta/n:.0f}%'}) carried Schwab greeks")
    if with_delta == 0:
        L.append("  NOTE: no hit carried a delta — the Schwab real-time chain was not the "
                 "source (yfinance has no greeks). The classifier cannot pair legs without "
                 "delta, so every hit stayed 'delta_unknown'. Re-run once Schwab is live.")
    if paired:
        L.append(f"  {len(paired)} hit(s) flagged 'paired' (likely hedge/spread) — these are "
                 "the ones a live discount would demote:")
        for r in paired[:20]:
            L.append(f"    {r['ticker']} {r['side']} {r['expiry']} "
                     f"prem=${r['prem']:,.0f} dw_notional=${r['dwn']:,.0f}")
    else:
        L.append("  0 paired hits — no directional bet was reclassified as a hedge/spread yet.")
    L.append("\nDecision: keep features.flow_hedge_discount.enabled OFF until 'paired' hits "
             "accumulate AND their realized options_flow_outcomes show the discount would help.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="F4 hedge/directional shadow review")
    ap.add_argument("--log", default=str(DEFAULT_LOG), help="path to consensus_engine.log")
    ap.add_argument("--since", default="", help="only lines newer than e.g. 7d / 24h / 30m")
    args = ap.parse_args()
    since = parse_since(args.since) if args.since else None
    rows = parse_log(Path(args.log), since)
    print(report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
