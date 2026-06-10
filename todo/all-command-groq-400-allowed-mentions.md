# !all Groq synthesis 400 — "property 'allowed_mentions' is unsupported"

**Status:** OPEN
**Created:** 2026-06-09

## The symptom
The `!all` synthesis call to Groq's primary model intermittently returns HTTP 400. Seen in the LLM health-check format in the journal 2026-06-09 ~17:30:

```
❌ `ALL` `primary` `groq/llama-3.3-70b-versatile` — HTTP 400 (0.0s) —
   {"error":{"message":"property 'allowed_mentions' is unsupported ...
```

Groq's chat-completions API is rejecting a JSON property named `allowed_mentions` in the request body. The call returns at ~0.0s (instant reject), so the bot falls back to the other `all_command_chain` models — `!all` still produces output, but the Groq primary is wasted on these calls.

## What I found (2026-06-09, did NOT fix)
- `allowed_mentions` is a **Discord** payload field, not an LLM-API field. In our code it appears ONLY in Discord send paths:
  - `consensus_engine/alerts/discord.py:37` — `payload.setdefault("allowed_mentions", {"parse": []})`
  - `consensus_engine/alerts/wolf_news.py:664/666`
- It does **NOT** appear anywhere in `consensus_engine/llm_client.py` (the Groq/OpenRouter request builder). So how `allowed_mentions` ends up in the Groq chat-completion body is a genuine mystery — that's the core thing to find.

## Leads / open questions for the fix session
1. **Trace how `allowed_mentions` enters the Groq request body.** Candidates:
   - Does `call_with_fallback` / the Groq request builder in `llm_client.py` (around line 99-125, where the body dict is assembled) splat through extra `**kwargs` that could carry a stray `allowed_mentions`?
   - Is the **LLM health-check** (`health.py`, the `❌ ALL primary ...` format) building its probe payload from a Discord-flavored template that leaks `allowed_mentions`?
   - Did a recent Groq API tightening start rejecting a property we always sent harmlessly before?
2. Get the FULL error body (the journal line was truncated) — `journalctl -u consensus-engine.service -o cat | grep allowed_mentions`. Confirm whether it's the health-check probe or the real synthesis call (or both).
3. Once located: strip `allowed_mentions` from the LLM request body (it should never be there) — likely a one-line fix at the body-assembly site or in the health-check probe.

## Files involved
- `consensus_engine/llm_client.py` (Groq/OpenRouter request body — line ~99-125)
- `consensus_engine/health.py` (the `ALL`/`primary` health-check that logged the ❌ line)
- `consensus_engine/alerts/all_command/narrator.py` (the synthesis call site — `synthesize`, ~line 1148)

## Related (same session, already DONE — context)
- The **413 "Request too large" (TPM)** on the same Groq `!all` call was fixed this session: output reservation cut 8000→4000 via `llm.all_command_synthesis_max_tokens`, and the head-start guard now counts `prompt + reserved output` against Groq's 12k TPM cap (`narrator.py` ~1135/1152). That's a DIFFERENT error (413 size vs 400 bad-property) — this TODO is only the 400.
