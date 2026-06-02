"""Live before/after gate for #6 latency-speedup (in-process, no Discord posts).

Runs the REAL aggregator.handle_all path (real DB + sources + LLM chain) with
Discord sends mocked, timing each !all and capturing the narrative, under:
  1. serial      (today's behavior — baseline)
  2. head_start  (window=15 — groq wins when healthy; expect parity)
  3. head_start  (window=1  — forces a groq "stall" so the fan-out race runs
                  live; proves the tail path still yields a valid narrative)
Prints a comparison table: elapsed + narrative status + length + section check.
"""
from __future__ import annotations
import asyncio
import time
from unittest.mock import patch

TICKERS = ["NVDA", "AMD", "SOFI"]


def _desc(emb) -> str:
    if emb is None:
        return ""
    if hasattr(emb, "to_dict"):
        emb = emb.to_dict()
    return (emb or {}).get("description", "") or ""


async def _bypass_cache(ticker, compute_fn):
    """Force a real compute — skip the 15-min !all DB cache (single-flight)."""
    return await compute_fn()


async def _run_one(ticker: str) -> tuple[float, str]:
    from consensus_engine.alerts.all_command import aggregator
    from consensus_engine.alerts.all_command import narrator
    narrator._synthesis_cache.clear()
    captured: list = []

    async def _send_reply(*a, **k):
        return "x"

    async def _send_embed(channel_id, msg_id, embed):
        captured.append(embed)
        return "y"

    with patch.object(aggregator.cache, "all_with_single_flight", _bypass_cache), \
         patch.object(aggregator, "send_command_reply", _send_reply), \
         patch.object(aggregator, "send_command_embed_reply", _send_embed):
        t0 = time.monotonic()
        await aggregator.handle_all(ticker, "chan_test", "msg_test")
        elapsed = time.monotonic() - t0
    return elapsed, _desc(captured[-1] if captured else None)


def _section_ok(desc: str) -> bool:
    from consensus_engine.alerts.all_command import quality_bar as qb
    return qb.has_required_sections(desc)


def _status(desc: str) -> str:
    if not desc:
        return "EMPTY"
    if "Narrative unavailable" in desc:
        return "fallback_data_only"
    return "ok"


async def _measure(label: str, strategy: str, window: int, tickers: list[str]) -> list[dict]:
    from consensus_engine import config as cfg
    _orig = cfg.get

    def _patched(k, default=None):
        if k == "llm.all_command_strategy":
            return strategy
        if k == "llm.all_command_head_start_timeout":
            return window
        return _orig(k, default)

    cfg.get = _patched
    rows = []
    try:
        for t in tickers:
            elapsed, desc = await _run_one(t)
            rows.append({
                "label": label, "ticker": t, "elapsed": round(elapsed, 1),
                "status": _status(desc), "len": len(desc),
                "sections_ok": _section_ok(desc),
            })
            print(f"  [{label:18}] {t:5} {elapsed:6.1f}s  {_status(desc):18} "
                  f"len={len(desc):5} sections_ok={_section_ok(desc)}")
    finally:
        cfg.get = _orig
    return rows


async def main():
    from consensus_engine import config as cfg
    cfg.load_config()
    from consensus_engine import db
    await db.init_db()

    print("=" * 78)
    all_rows = []
    all_rows += await _measure("serial(baseline)", "serial", 15, TICKERS)
    print("-" * 78)
    all_rows += await _measure("head_start(w=15)", "head_start", 15, TICKERS)
    print("-" * 78)
    all_rows += await _measure("head_start(w=1,stall)", "head_start", 1, ["NVDA"])
    print("=" * 78)
    print("\nSUMMARY")
    for r in all_rows:
        print(r)


if __name__ == "__main__":
    asyncio.run(main())
