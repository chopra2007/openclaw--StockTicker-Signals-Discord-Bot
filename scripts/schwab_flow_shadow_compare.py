#!/usr/bin/env python3
"""Flow-loop shadow compare: Schwab vs yfinance (TODO #57, BLOCK-1 gate).

The autonomous unusual-flow ALERT loop (main.py `_run_options_flow_scan`) posts
messages on its own, and its thresholds (`options_flow.min_vol_oi/min_volume/
min_premium_usd`) were tuned on the free ~15-min-delayed yfinance chain. Before we
let the loop run on Schwab's real-time chain (`features.schwab_options.flow_loop_
enabled`), CLAUDE.md requires a live check that Schwab doesn't systematically
change which contracts qualify.

This script runs one flow scan BOTH ways at the CURRENT live thresholds on the
same watchlist, during market hours, and reports:
- qualifying FlowHit counts (Schwab vs yfinance),
- the overlap and each side's exclusives,
- so a human can decide whether to re-tune before flipping the loop ON.

Run during RTH (post-close data is stale and the staleness gate drops everything).
Read-only: it does NOT alert, write, or flip anything. Posts a summary to
notifications.log + #chat when --notify is passed.
"""
import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")

from consensus_engine import config as cfg  # noqa: E402
from consensus_engine import db  # noqa: E402
from consensus_engine.scanners.options import scan_options_flow  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [flow-shadow] %(message)s")
log = logging.getLogger("flow_shadow")

NOTIF_LOG = "/root/task_system/notifications.log"


def _key(h) -> str:
    return f"{h.ticker} {h.expiry} {h.strike:g}{h.side[0]}"


async def _scan(use_schwab: bool) -> list:
    active = await db.get_active_tickers(min_signals=1)
    core = cfg.get("options_flow.fixed_core", []) or []
    tickers = list(dict.fromkeys([*active, *core]))
    if not tickers:
        tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META"]
    return await scan_options_flow(
        tickers, executor=None,
        min_vol_oi=float(cfg.get("options_flow.min_vol_oi", 5.0)),
        min_volume=int(cfg.get("options_flow.min_volume", 500)),
        min_premium=float(cfg.get("options_flow.min_premium_usd", 250000)),
        max_staleness_min=int(cfg.get("options_flow.max_staleness_min", 60)),
        nearest_expirations=int(cfg.get("options_flow.nearest_expirations", 2)),
        use_schwab=use_schwab,
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="post a summary to notifications.log + #chat")
    args = ap.parse_args()

    schwab_hits = await _scan(use_schwab=True)
    yahoo_hits = await _scan(use_schwab=False)

    s_keys = {_key(h) for h in schwab_hits}
    y_keys = {_key(h) for h in yahoo_hits}
    both = s_keys & y_keys
    only_s = s_keys - y_keys
    only_y = y_keys - s_keys

    lines = [
        "Schwab vs yfinance flow-loop shadow compare (current live thresholds):",
        f"  Schwab qualifying hits : {len(schwab_hits)} ({len({h.ticker for h in schwab_hits})} tickers)",
        f"  yfinance qualifying hits: {len(yahoo_hits)} ({len({h.ticker for h in yahoo_hits})} tickers)",
        f"  overlap: {len(both)} | Schwab-only: {len(only_s)} | yfinance-only: {len(only_y)}",
    ]
    if only_s:
        lines.append("  Schwab-only (would fire NEW alerts): " + ", ".join(sorted(only_s)[:12]))
    if only_y:
        lines.append("  yfinance-only (Schwab would MISS): " + ", ".join(sorted(only_y)[:12]))
    verdict = ("LIKELY SAFE to flip flow_loop_enabled — hit sets close"
               if len(only_s) <= 2 and len(only_y) <= 2
               else "RE-TUNE thresholds first — hit sets diverge materially")
    lines.append(f"  VERDICT: {verdict}")
    report = "\n".join(lines)
    print(report)

    if args.notify:
        try:
            with open(NOTIF_LOG, "a") as f:
                f.write("\n[schwab-flow-shadow] " + report.replace("\n", " | ") + "\n")
        except Exception as e:  # noqa: BLE001
            log.debug("notif log write failed: %s", e)
        hook = os.environ.get("CLAUDECODE_WEBHOOK")
        if hook:
            try:
                import requests
                requests.post(hook, json={"content": "```\n" + report + "\n```"}, timeout=10)
            except Exception as e:  # noqa: BLE001
                log.debug("webhook post failed: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
