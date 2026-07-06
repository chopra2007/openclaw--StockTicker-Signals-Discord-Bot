#!/usr/bin/env python3
"""Offline eval harness for the #64 trap-proof Wolf reader.

Runs the text-extraction path (`wolf_email_parser._produce_theses`, no charts/network beyond
the LLM) over the 5 snapshotted eval emails, twice — the CURRENT shipped extractor (verifier
flag OFF) and the new extractor->verifier pipeline (flag ON) — and scores the HARD GATE:

  1. zero IGV false bulls across every email        (the trap invariant)
  2. IGV bear recovered on the incident + 06-05a     (recall)
  3. no net increase in invented theses vs baseline  (false-positive discipline)

Usage:
  python3 scripts/eval_wolf_extractor.py            # both versions, full gate
  python3 scripts/eval_wolf_extractor.py --only new # just the new pipeline

Makes real LLM calls (extractor x N + one cross-family judge call per email per version).
Wolf cadence is ~1 email/day so this is affordable; expect a couple of minutes.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from consensus_engine import config as cfg  # noqa: E402
from consensus_engine.analysis import wolf_email_parser as wep  # noqa: E402
from consensus_engine.analysis.wolf_scope import resolve_scope  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "wolf_eval"
GOLD = json.loads((FIXTURES / "gold.json").read_text())["emails"]
IGV_KEY = resolve_scope("IGV")[1]

_real_get = cfg.get


def _patched_get(overrides):
    def g(key, default=None):
        if key in overrides:
            return overrides[key]
        return _real_get(key, default)
    return g


def _load_body(path: Path) -> tuple[str, str]:
    """Return (message_id, body_text). Strips the leading '# ...' header comment lines."""
    lines = path.read_text().splitlines()
    mid = ""
    for ln in lines[:5]:
        m = re.match(r"#\s*message_id:\s*(\S+)", ln)
        if m:
            mid = m.group(1)
    body = "\n".join(ln for ln in lines if not ln.startswith("# "))
    return mid, body


async def _run_version(label: str, verifier_on: bool, reliable_extractor: bool = False) -> dict:
    overrides = {"wolf.verifier.enabled": verifier_on}
    if reliable_extractor:
        # The whole OpenRouter :free pool is shared + throttled (all :free models 429/empty
        # together), so no free model gives a clean eval. Lead with PAID deepseek-v4-flash
        # (reliable, and a DIFFERENT family from the Gemini verifier so errors stay
        # uncorrelated) to isolate PIPELINE LOGIC from free-tier availability.
        overrides["wolf.extraction_models"] = [
            "deepseek/deepseek-v4-flash", "openai/gpt-oss-120b", "openrouter/free"]
    cfg.get = _patched_get(overrides)
    try:
        results = {}
        for path in sorted(FIXTURES.glob("*.txt")):
            mid, body = _load_body(path)
            if mid not in GOLD:
                continue
            theses = await wep._produce_theses(body)
            # _produce_theses returns (theses, raw0)
            theses = theses[0] if isinstance(theses, tuple) else theses
            results[mid] = theses
        return results
    finally:
        cfg.get = _real_get


def _igv_theses(theses):
    return [t for t in theses if t["scope_key"] == IGV_KEY]


def _score(results: dict, version: str):
    print(f"\n{'='*70}\n{version}\n{'='*70}")
    igv_false_bulls = 0
    igv_bear_recovered = {}
    total = 0
    trap_hits_total = 0
    for mid, g in GOLD.items():
        theses = results.get(mid, [])
        total += len(theses)
        igv = _igv_theses(theses)
        igv_dirs = [(t["direction"], t.get("phase", "?")) for t in igv]
        false_bull = sum(1 for t in igv if t["direction"] == "bull")
        igv_false_bulls += false_bull
        igv_bear_recovered[mid] = any(t["direction"] == "bear" for t in igv)
        trap_keys = {resolve_scope(tk)[1] for tk in g.get("trap_tickers", [])}
        trap_hits = [t["scope_key"] for t in theses if t["scope_key"] in trap_keys]
        trap_hits_total += len(trap_hits)
        produced = ", ".join(f"{t['scope_key']}/{t['direction']}/{t.get('phase','?')}" for t in theses) or "(none)"
        flag = " ❌FALSE-BULL" if false_bull else ""
        print(f"\n[{g['label']}]")
        print(f"  IGV: {igv_dirs or '(absent)'}{flag}")
        if trap_hits:
            print(f"  ⚠ trap-ticker theses: {trap_hits}")
        print(f"  all theses ({len(theses)}): {produced}")
    print(f"\n  --- {version} totals ---")
    print(f"  IGV false bulls (must be 0): {igv_false_bulls}")
    print(f"  IGV bear recovered: incident={igv_bear_recovered.get('19e7291f1b217a3c')} "
          f"06-05a={igv_bear_recovered.get('19e96023b60514d2')} "
          f"06-12={igv_bear_recovered.get('19eb9ee20e403188')}")
    print(f"  total theses: {total} | trap-ticker theses: {trap_hits_total}")
    return {"igv_false_bulls": igv_false_bulls, "recovered": igv_bear_recovered,
            "total": total, "trap_hits": trap_hits_total}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["baseline", "new"], default=None)
    ap.add_argument("--reliable-extractor", action="store_true",
                    help="lead the extractor with the paid gpt-oss-120b (same family) to dodge free-tier 429s")
    args = ap.parse_args()
    rel = args.reliable_extractor

    base = new = None
    if args.only in (None, "baseline"):
        base = _score(await _run_version("baseline", False, rel), "BASELINE (current shipped extractor)")
    if args.only in (None, "new"):
        new = _score(await _run_version("new", True, rel), "NEW (extractor->verifier pipeline)")

    if base and new:
        print(f"\n{'='*70}\nGATE\n{'='*70}")
        c1 = new["igv_false_bulls"] == 0
        c2 = (new["recovered"].get("19e7291f1b217a3c") and new["recovered"].get("19e96023b60514d2"))
        c3 = new["trap_hits"] <= base["trap_hits"]
        print(f"  [{'PASS' if c1 else 'FAIL'}] zero IGV false bulls (new={new['igv_false_bulls']})")
        print(f"  [{'PASS' if c2 else 'FAIL'}] IGV bear recovered on incident + 06-05a")
        print(f"  [{'PASS' if c3 else 'FAIL'}] no net increase in trap-ticker theses "
              f"(new={new['trap_hits']} vs baseline={base['trap_hits']})")
        print(f"\n  baseline: IGV false bulls={base['igv_false_bulls']}, "
              f"recovered incident={base['recovered'].get('19e7291f1b217a3c')} "
              f"06-05a={base['recovered'].get('19e96023b60514d2')}, trap={base['trap_hits']}")
        print(f"\n  GATE: {'✅ PASS' if (c1 and c2 and c3) else '❌ FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
