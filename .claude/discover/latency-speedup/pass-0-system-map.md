# Pass 0 — System Map (latency-speedup)

> Scope: the `!all` synthesis latency path only. Built from the pre-run code-grounded verification (2 Explore agents, all quotes from current master 3134b89). Task B (#19 YT-score) verified done & skipped — see state.json.

## The latency mechanism (verified)

**Single shared LLM caller:** `consensus_engine/llm_client.py:61 call_with_fallback(role, messages, chain, timeout, ...)`.

The hot loop (`llm_client.py:85`):
```python
for idx, model in enumerate(chain):
    ...
    async with session.post(endpoint, ..., timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        if resp.status == 200 and content: return content
        # else: log + continue to next model
    except (TimeoutError, ClientError): continue   # moves to next model
```
→ **Serial walk.** Model N is fully awaited (up to `timeout`) before model N+1 is tried. Fallover triggers on: timeout, HTTP 408/429/5xx, connection error, or empty content.

**Chain** (`config/consensus.yaml:251` `all_command_chain`):
1. `groq/llama-3.3-70b-versatile`
2. `openai/gpt-oss-120b:free`
3. `openai/gpt-oss-20b:free`

**Synthesis timeout** (`narrator.py:923`): `max(15, min(90, deadline_seconds))` → **up to 90s per model** → worst case 3×90 = **270s for one synthesis call**.

**Synthesis fires up to 3× per `!all`** (`narrator.py:1011-1095`): primary call → if required sections missing, hardened re-prompt → contradiction retry. Each re-walks the full 3-model chain at a reduced deadline.

**Sanitize phase** (`narrator.py:174-196, 280`): 9 concurrent `_batch_summarize` calls (`_BATCH_TIMEOUT = 5`, line 106), each ALSO walking the 3-model chain serially on failure → steady ~17-25s tax.

**Measured worst cases** (from May-31 profiling, `scratch-pass0-latency-cost.md`): MSFT 240.1s, TSLA 234.3s, both `fallback_data_only` (chain exhausted = every model timed out).

## Data flow (text)
```
!all <ticker>
  → aggregator.handle_all  (gathers ~27 sources in parallel)
  → narrator.synthesize_narrative
       ├─ sanitize: 9× _batch_summarize  (call_with_fallback role=text, 5s, chain serial-on-fail)
       └─ _invoke_synthesis  (call_with_fallback role=primary, up to 90s/model, chain serial)
              └─ up to 3 passes (primary + missing-sections + contradiction)
  → embed.build_embed → Discord post   (currently: BLOCKS on narrative before posting)
```

## Fix surface
- `llm_client.py call_with_fallback` — the serial loop. Fix (a)/(b) live here.
- `aggregator.handle_all` + `embed.py` + Discord post path — fix (c) 2-stage embed lives here.
- `narrator._invoke_synthesis` retry logic — interacts with whichever fix.

## Strengths
- Per-model errors are well-isolated (any failure → `continue`), so refactoring to concurrent is low structural risk.
- Per-provider `rate_limiter.acquire` already exists → can gate a concurrent fan-out.
- Deterministic fields (Direction/Confidence/Trade Plan/levels) are computed WITHOUT the LLM → makes fix (c) feasible.

## Gaps (the actual problem)
- No concurrency across chain models — pure serial walk.
- No fast-failover / per-model timeout differentiation (single `timeout` applied to all).
- Discord post blocks on the full narrative — no progressive render.

## Tripwire (shared file) — REAL caller list
`call_with_fallback` callers (must re-test if chain logic changes):
1. `narrator.py` — `!all` (9 batch + vault excerpt + synthesis ×≤3)
2. `briefing/alfred.py:92` — morning briefing
3. `research/sources.py:30` — research gap-fill
4. `analysis/wolf_email_parser.py:261` — Wolf email thesis
5. `analysis/captions_llm_parser.py:192` — YouTube caption→ticker
6. `analysis/video_parser.py:475` — YouTube transcript
7. `analysis/llm_scorer.py:123` — TweetShift mention scoring

**NOT a caller:** `@mention`/`!ask` (kickoff was wrong — that path uses `openclaw agent --local`, verified via grep on `commands.py`).
