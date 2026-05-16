"""Probe a single model. Usage: python3 probe_single.py <model_id>"""
import asyncio, os, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
from probe_llm_chain import (
    call_model, score_quality, SYNTHESIS_MESSAGES,
)
import aiohttp

MODEL = sys.argv[1] if len(sys.argv) > 1 else "nvidia/nemotron-3-super-120b-a12b:free"

async def main():
    async with aiohttp.ClientSession() as session:
        # PHASE 1: liveness
        print(f"\n=== {MODEL} ===\n")
        print("PHASE 1: liveness (50t, 15s)")
        r1 = await call_model(session, MODEL,
            [{"role":"user","content":"Reply with exactly: PONG"}],
            max_tokens=50, timeout=15)
        print(f"  ok={r1['ok']} status={r1['status']} elapsed={r1['elapsed']:.1f}s")
        if r1.get("content"): print(f"  content: {r1['content'][:80]!r}")
        if r1.get("reasoning"): print(f"  reasoning: {r1['reasoning'][:80]!r}")
        if r1.get("error"): print(f"  err: {r1['error'][:120]}")
        if not r1["ok"]:
            print("\nLIVENESS FAILED — stopping.")
            return

        # PHASE 2: synthesis
        print("\nPHASE 2: synthesis (8000t, 50s)")
        r2 = await call_model(session, MODEL, SYNTHESIS_MESSAGES, max_tokens=8000, timeout=50)
        print(f"  ok={r2['ok']} status={r2['status']} elapsed={r2['elapsed']:.1f}s "
              f"content_chars={len(r2.get('content',''))} reasoning_chars={len(r2.get('reasoning',''))}")
        if r2["ok"]:
            q = score_quality(r2["content"])
            print(f"  quality: {q['score']}/{q['max']} | failed: {[k for k,v in q['checks'].items() if not v]}")
            print(f"\n  --- FULL CONTENT ({len(r2['content'])} chars) ---")
            print(r2["content"])
            if r2.get("reasoning"):
                print(f"\n  --- REASONING (truncated to 800) ---")
                print(r2["reasoning"][:800])
        else:
            print(f"  err: {r2['error'][:200]}")
        if not r2["ok"]:
            print("\nSYNTHESIS FAILED — skipping parallel.")
            return

        # PHASE 3: 3x parallel
        await asyncio.sleep(2)
        print("\nPHASE 3: 3x parallel synthesis")
        t0 = time.time()
        tasks = [call_model(session, MODEL, SYNTHESIS_MESSAGES, max_tokens=8000, timeout=50) for _ in range(3)]
        rs = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - t0
        ok = sum(1 for r in rs if isinstance(r, dict) and r.get("ok"))
        print(f"  batch={elapsed:.1f}s | ok={ok}/3")
        for i, r in enumerate(rs):
            if isinstance(r, dict):
                qs = score_quality(r.get('content','')) if r.get('ok') else {'score': 0}
                print(f"  [{i}] ok={r['ok']} elapsed={r['elapsed']:.1f}s "
                      f"chars={len(r.get('content',''))} qual={qs.get('score',0)}/12 "
                      f"err={r.get('error','')[:80]}")
            else:
                print(f"  [{i}] exception: {r}")

if __name__ == "__main__":
    asyncio.run(main())
