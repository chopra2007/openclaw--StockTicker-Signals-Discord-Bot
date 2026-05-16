"""Live-test each of the 5 recommended LLMs end-to-end via !all on Discord.

For each (model, ticker) pair:
  1. Rewrite consensus.yaml with model as the SOLE chain entry (no fallback)
  2. sync_gateway_models.py (preserves openclaw ownership)
  3. systemctl restart consensus-engine.service
  4. POST `!all $TICKER` to Discord webhook (bot receives it)
  5. Poll xref_cache until row appears (real !all completion)
  6. Extract narrative + status + capture journalctl latency
After all 5: restore the final 5-model chain from RESULTS.md.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

REPO = Path("/home/openclaw/.openclaw/workspace")
CONSENSUS_YAML = REPO / "config/consensus.yaml"
DB = REPO / "consensus.db"
OUTPUT_DIR = REPO / ".omc/research/llm-chain-2026-05-16"
WEBHOOK = "WEBHOOK_REDACTED"
BOT_MENTION = "<@1468886193054814352>"

# Same ticker for every test so the COMPUTED SIGNAL + evidence corpus is
# (nearly) identical across runs — only the LLM changes. Cache is deleted
# between runs so each post triggers a fresh full !all pass. Minor evidence
# drift from live news/tweet fetches minutes apart is unavoidable.
SHARED_TICKER = "AMZN"
TESTS = [
    ("openai/gpt-oss-120b:free",                            SHARED_TICKER),
    ("openai/gpt-oss-20b:free",                             SHARED_TICKER),
    ("nvidia/nemotron-3-nano-30b-a3b:free",                 SHARED_TICKER),
    ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  SHARED_TICKER),
    ("z-ai/glm-4.5-air:free",                               SHARED_TICKER),
]

# The final 5-model chain to restore at the end (from RESULTS.md)
FINAL_CHAIN = [
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "z-ai/glm-4.5-air:free",
]


def write_yaml_chain(primary: str, fallbacks: list[str]) -> None:
    """Patch llm.model, fallback_models, text_model, text_fallback_models."""
    text = CONSENSUS_YAML.read_text()
    cfg = yaml.safe_load(text)
    cfg["llm"]["model"] = primary
    cfg["llm"]["fallback_models"] = list(fallbacks)
    cfg["llm"]["text_model"] = primary
    cfg["llm"]["text_fallback_models"] = list(fallbacks)
    # Naive rewrite — easier to use yaml.dump than surgically edit, since this
    # file is overwritten back-and-forth by this script alone.
    CONSENSUS_YAML.write_text(yaml.safe_dump(cfg, sort_keys=False, width=120))


def sync_gateway() -> None:
    r = subprocess.run(
        ["sudo", "-u", "openclaw", "python3", "scripts/sync_gateway_models.py"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  sync FAILED: {r.stderr[:200]}")


def restart_engine() -> None:
    r = subprocess.run(
        ["sudo", "systemctl", "restart", "consensus-engine.service"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"restart failed: {r.stderr[:200]}")
    # Wait for engine boot (it logs "engine ready" or similar)
    time.sleep(8)


def cache_prefix() -> str:
    """Re-derive the all_v<hash> cache prefix from package version."""
    import hashlib
    v_line = (REPO / "consensus_engine/__init__.py").read_text()
    v = v_line.split("=")[1].strip().strip('"')
    return "all_v" + hashlib.sha1(v.encode()).hexdigest()[:8]


def clear_ticker_cache(ticker: str) -> None:
    prefix = cache_prefix()
    key = f"{prefix}:{ticker}"
    c = sqlite3.connect(str(DB))
    c.execute("DELETE FROM xref_cache WHERE ticker = ?", (key,))
    c.commit()
    c.close()


def post_all_command(ticker: str) -> None:
    payload = {"content": f"{BOT_MENTION} !all {ticker}", "username": "ClaudeCode"}
    r = requests.post(WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()


def fetch_narrative(ticker: str, deadline_s: float) -> dict | None:
    """Poll xref_cache up to deadline; return parsed row or None."""
    prefix = cache_prefix()
    key = f"{prefix}:{ticker}"
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT cached_at, result_json FROM xref_cache WHERE ticker = ? ORDER BY cached_at DESC LIMIT 1",
            (key,),
        ).fetchone()
        c.close()
        if row:
            return {"cached_at": row[0], "result": json.loads(row[1])}
        time.sleep(5)
    return None


def fetch_log_status(ticker: str, since_ts: float) -> dict:
    """Extract narrative_status + elapsed from journalctl."""
    since_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since_ts - 5))
    r = subprocess.run(
        ["sudo", "journalctl", "-u", "consensus-engine.service",
         "--since", since_str, "--no-pager", "-o", "cat"],
        capture_output=True, text=True,
    )
    out = r.stdout
    # Look for lines like: "aggregator: $TICKER narrative_status=... elapsed=Xs"
    matches = [ln for ln in out.split("\n") if f"${ticker}" in ln and "narrative_status" in ln]
    return {
        "matches": matches[-3:],  # last 3 in case of retries
        "fallback_hits": [ln for ln in out.split("\n") if "LLM fallback hit" in ln][-3:],
        "errors": [ln for ln in out.split("\n") if ticker in ln and ("ERROR" in ln or "exhausted" in ln)][-3:],
    }


def run_test(model: str, ticker: str) -> dict:
    print(f"\n{'='*80}\n  TEST: {model:55} → !all {ticker}\n{'='*80}")
    print("  → write yaml, sync, restart engine")
    write_yaml_chain(model, [])
    sync_gateway()
    restart_engine()
    clear_ticker_cache(ticker)
    print(f"  → POST !all {ticker} to Discord")
    t0 = time.time()
    post_all_command(ticker)
    print("  → polling xref_cache (max 240s)…")
    res = fetch_narrative(ticker, deadline_s=240)
    elapsed = time.time() - t0
    log_info = fetch_log_status(ticker, t0)
    out = {
        "model": model, "ticker": ticker, "elapsed_s": round(elapsed, 1),
        "got_result": bool(res),
        "result": res,
        "logs": log_info,
    }
    if res:
        embed = res.get("result", {}).get("embed", {})
        desc = embed.get("description", "")
        out["narrative_chars"] = len(desc)
        out["narrative"] = desc
        out["status_from_logs"] = log_info["matches"][-1] if log_info["matches"] else "(no log match)"
        print(f"  ✓ result in {elapsed:.1f}s | narrative_chars={len(desc)} | log: {out['status_from_logs'][:120]}")
    else:
        print(f"  ✗ no result in {elapsed:.1f}s — likely timeout or skip")
    return out


def main():
    results = []
    for model, ticker in TESTS:
        try:
            results.append(run_test(model, ticker))
        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            results.append({"model": model, "ticker": ticker, "error": str(exc)})
        # Don't pummel Discord
        time.sleep(10)

    # Restore final chain
    print(f"\n{'='*80}\n  RESTORING FINAL 5-MODEL CHAIN\n{'='*80}")
    write_yaml_chain(FINAL_CHAIN[0], FINAL_CHAIN[1:])
    sync_gateway()
    restart_engine()

    out_path = OUTPUT_DIR / f"live_test-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n  Results: {out_path}")

    # Summary
    print(f"\n{'model':56} {'ticker':6} {'elapsed':>9} {'chars':>6} {'status'}")
    for r in results:
        if "error" in r:
            print(f"  {r['model']:54} {r['ticker']:6} ERROR: {r['error'][:60]}")
            continue
        status = r.get("status_from_logs", "?")[:60]
        chars = r.get("narrative_chars", 0)
        print(f"  {r['model']:54} {r['ticker']:6} {r['elapsed_s']:>7.1f}s {chars:>6} {status}")


if __name__ == "__main__":
    main()
