#!/usr/bin/env python3
"""PR7 Layer B — live `!all` quality-bar probe.

Triggers `!all <ticker>` against the running consensus_engine for each of
NVDA / AMD / TSLA via the allow-listed test webhook, then greps the log
file for the structured `quality_bar:` line emitted at the end of
aggregator._compute_all (PR7) and reports PASS/FAIL per ticker against
the 9 quality-bar thresholds.

Run from the workspace root:

    python3 -m scripts.run_quality_bar_live

Exit code 0 iff all 3 tickers report PASS. Use the printed FAIL reasons
to drive the next iteration's fix list before invoking Layer C (manual
blind-compare with Gemini).
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import aiohttp


WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
LOG_FILE = WORKSPACE / "consensus_engine.log"
WEBHOOK_ENV = "ALL_QUALITY_BAR_WEBHOOK_URL"
TICKERS = ("NVDA", "AMD", "TSLA")

# Thresholds locked by quality-bar.md and plan §6.
THRESHOLDS = {
    "sources_surfaced": 3,
    "numbered_facts":   3,
    "catalyst_bullets": 2,
    "risk_bullets":     1,
    "stage_synth_ms_max": 50_000,
    "narrative_chars":  300,
}

# 12 fields in the order they appear in aggregator's quality_bar log line.
_FIELD_RE = re.compile(
    r"quality_bar: ticker=(?P<ticker>\S+) "
    r"sources_surfaced=(?P<sources_surfaced>\d+) "
    r"sources_failed=(?P<sources_failed>\d+) "
    r"anchors_total=(?P<anchors_total>\d+) "
    r"sl=(?P<sl>\S+) tp1=(?P<tp1>\S+) "
    r"narrative_chars=(?P<narrative_chars>\d+) "
    r"narrative_status=(?P<narrative_status>\S+) "
    r"stage_synth_ms=(?P<stage_synth_ms>\d+) "
    r"numbered_facts=(?P<numbered_facts>\d+) "
    r"catalyst_bullets=(?P<catalyst_bullets>\d+) "
    r"risk_bullets=(?P<risk_bullets>\d+)"
)


async def post_command(webhook: str, ticker: str) -> None:
    payload = {"content": f"!all {ticker}"}
    async with aiohttp.ClientSession() as sess:
        async with sess.post(webhook, json=payload, timeout=30) as r:
            r.raise_for_status()


def grep_quality_bar(ticker: str, since_offset: int) -> dict | None:
    """Find the most recent quality_bar line for `ticker` past `since_offset`."""
    if not LOG_FILE.exists():
        return None
    with LOG_FILE.open("rb") as f:
        f.seek(since_offset)
        tail = f.read().decode("utf-8", errors="replace")
    last: dict | None = None
    for line in tail.splitlines():
        m = _FIELD_RE.search(line)
        if m and m.group("ticker") == ticker:
            last = m.groupdict()
    return last


def evaluate(fields: dict) -> tuple[str, list[str]]:
    fails: list[str] = []
    if int(fields["sources_surfaced"]) < THRESHOLDS["sources_surfaced"]:
        fails.append(f"sources<{THRESHOLDS['sources_surfaced']}")
    if int(fields["numbered_facts"]) < THRESHOLDS["numbered_facts"]:
        fails.append(f"facts<{THRESHOLDS['numbered_facts']}")
    if int(fields["catalyst_bullets"]) < THRESHOLDS["catalyst_bullets"]:
        fails.append(f"catalysts<{THRESHOLDS['catalyst_bullets']}")
    if int(fields["risk_bullets"]) < THRESHOLDS["risk_bullets"]:
        fails.append(f"risks<{THRESHOLDS['risk_bullets']}")
    if int(fields["stage_synth_ms"]) > THRESHOLDS["stage_synth_ms_max"]:
        fails.append(f"synth>{THRESHOLDS['stage_synth_ms_max']}ms")
    if int(fields["narrative_chars"]) < THRESHOLDS["narrative_chars"]:
        fails.append(f"narrative<{THRESHOLDS['narrative_chars']}c")
    if fields["narrative_status"] != "ok":
        fails.append(f"narrative_status={fields['narrative_status']}")
    verdict = "PASS" if not fails else f"FAIL {','.join(fails)}"
    return verdict, fails


async def main() -> int:
    webhook = os.environ.get(WEBHOOK_ENV)
    if not webhook:
        print(f"error: set {WEBHOOK_ENV} before running", file=sys.stderr)
        return 2
    if not LOG_FILE.exists():
        print(f"error: log file missing at {LOG_FILE}", file=sys.stderr)
        return 2

    log_offset = LOG_FILE.stat().st_size
    print(f"baseline log offset: {log_offset}")

    results: dict[str, str] = {}
    overall_ok = True
    for ticker in TICKERS:
        print(f"\n--- !all {ticker} ---")
        await post_command(webhook, ticker)
        # Allow up to 90s for the run to complete and the log line to land.
        deadline = time.time() + 90
        fields = None
        while time.time() < deadline:
            fields = grep_quality_bar(ticker, log_offset)
            if fields:
                break
            await asyncio.sleep(2)
        if not fields:
            results[ticker] = "FAIL no_log_line"
            overall_ok = False
            print(f"{ticker}: FAIL — no quality_bar line within 90s")
            continue
        verdict, _ = evaluate(fields)
        results[ticker] = verdict
        if verdict != "PASS":
            overall_ok = False
        print(f"{ticker}: {verdict}")
        print(f"  fields: {fields}")

    print("\n=== Summary ===")
    for t, v in results.items():
        print(f"  {t}: {v}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
