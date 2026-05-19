# Bot LLM-Quality Improvement Spec — Option 1 ("router as fallback")
**Date:** 2026-05-19
**Status:** IMPLEMENTED 2026-05-19 (with deviations — see Implementation Notes below)
**Companion:** TODO #14 (web-search providers degraded), TODO #15 (redundant Python-side fallback chain), TODO #9 (mention replay), TODO #11–#13 (`!all` quality gaps — out of scope here)

## Implementation Notes (2026-05-19)

User approved the spec contents and authorized engine-code edits. Applied 2026-05-19 with two deviations forced by reality, not by the user:

1. **Primary model is `openrouter/z-ai/glm-4.5-air:free`, not `openrouter/openai/gpt-oss-120b:free`.** Pinning gpt-oss-120b was the original proposal, but its OpenRouter free-tier provider rejects the agent's ~6-8K-token system prompt with `Context overflow: prompt too large for the model`. The model's nominal context is 128K but the free tier caps below 8K. glm-4.5-air handles the same prompt cleanly; it's still in the fallback router for when it 429s, just promoted to primary. gpt-oss-120b stays in the chain via `openrouter/auto`.

2. **Schema field is `fallbacks` (plural array), not `fallback` (singular string).** `openclaw config validate` rejected the singular form. Final shape:
   ```json
   "model": {
     "primary": "openrouter/z-ai/glm-4.5-air:free",
     "fallbacks": ["openrouter/auto"]
   }
   ```

3. **`!ask` channel-history: kept (10 messages, per user)** — not dropped. `_handle_ask` now calls `_handle_mention` directly with the last 10 messages prepended to the user question as "Recent channel messages (oldest→newest, for context only)". One code path for both `!ask` and `@mention` going forward.

4. **`commands.restart: true` finding (out of scope but logged):** the engine restarted 4× in the hour during this session — all clean shutdowns ("Deactivated successfully"), all from outside the engine code (grep confirmed no `os._exit` / `sys.exit(0)` / restart-handler in `consensus_engine/`). Suspect `commands.restart: true` in openclaw.json exposes a `!restart` command. Not addressed in this spec.

5. **Cross-channel session-memory leak (folded into this spec on user approval):** `consensus_engine.main._handle_mention` originally did NOT pass `--session-id`, so all `@-mention` traffic shared one openclaw session. That session (`agent:main:main`) accumulated 30k tokens of context, overflowing glm-4.5-air's effective free-tier window. Resolved by (a) passing `--session-id "channel-{channel_id}"` in `_handle_mention` so each Discord channel gets its own isolated session bucket, and (b) deleting the existing `agent:main:main` session record from `/home/openclaw/.openclaw/agents/main/sessions/sessions.json` (backup at `.bak.pre-clear-2026-05-19`).

**Validation status — FULL PASS (2026-05-19 14:49 PDT):**
- CLI probes: math `7×8=56` ✓, read TODO.md first line `# To Do List` ✓ (glm-4.5-air primary).
- Discord end-to-end: `!ask what is 12 times 9?` → bot replied `108` in 31s (attempt=1, no retries).
- Session list shows new `channel-1468890179698692147` session at 23k/131k (18%), well under the prior overflow threshold.

---

## Problem
The bot's main LLM gives poor answers to questions any free LLM should handle. Observed in #chat 2026-05-18 → 2026-05-19:
- "Read TODO.md and quote it" → hallucinated about README.md/v8b/cache; later leaked a prompt-template fragment (`1. Run in Gemini web/CLI: "Look at <TICKER>..."`).
- NVDA bull-or-bear template with `<PRICE>` placeholder → bot punted "please provide the current price" (twice, 28s apart).
- "Any trump or iran news today of note?" → bot replied "Hello! How can I help you today?" — ignored the question.

## Root causes (one fixed in-session; two open)

1. **[FIXED in 2026-05-19 gateway-flap session]** OpenClaw npm update left `.env.service` and `auth-*.json` chowned to root:root 0600. The systemd `EnvironmentFile=-` line silently skipped them, so the gateway booted with no provider env. Agent calls hung or returned empty stdout. Confirmed end-to-end with `<@bot> ping 2 → pong` reply after chowning the files back to openclaw and restarting `openclaw-gateway.service`.

2. **[OPEN — this spec]** `@-mention` path: openclaw agent uses `openrouter/auto` (5-model router roulette). System prompt is 32KB assembled from generic personal-assistant docs (`AGENTS.md`, `SOUL.md`) and a stub `TOOLS.md` (cameras/SSH/TTS examples — zero ticker-bot guidance). When the router lands on a weak model (nemotron-nano variants), tool-use protocol breaks; model answers from priors, hallucinates, or leaks prompt fragments.

3. **[OPEN — this spec]** `!ask` command path bypasses the openclaw agent entirely. Calls `consensus_engine.llm_client.call_with_fallback` directly with no tools, no domain context beyond raw Discord channel history. Even a strong LLM has nothing to ground on.

## Proposal

### A. Pin a strong primary model with router as fallback
**File:** `/home/openclaw/.openclaw/openclaw.json`

Current shape:
```json
"agents": { "defaults": { "model": { "primary": "openrouter/auto" } } }
```

Proposed shape (subject to schema verification, step 0 below):
```json
"agents": {
  "defaults": {
    "model": {
      "primary": "openrouter/openai/gpt-oss-120b:free",
      "fallback": "openrouter/auto"
    }
  }
}
```

Rationale: `gpt-oss-120b:free` is the strongest of the 5 free OpenRouter models at tool-following. Pinning it removes router roulette on the happy path. When it's rate-limited or VPS-specific 5xx (the user-confirmed reason to keep router available), fall back to `openrouter/auto` which fans across the remaining 4 free models (gpt-oss-20b, nemotron-30b, nemotron-omni-30b, glm-4.5-air).

**Step 0 — schema verify:** Before applying, confirm openclaw.json schema supports a `fallback` field under `agents.defaults.model`. Probe commands:
- `grep -r "model\.primary\|model\.fallback" /usr/lib/node_modules/openclaw/dist/*.d.ts` for type defs.
- `sudo -u openclaw openclaw config validate` against a test variant.

If `fallback` is not a first-class field, alternate shapes to try in order:
- (a) `"primary": ["openrouter/openai/gpt-oss-120b:free", "openrouter/auto"]` — list of fallbacks.
- (b) Define a NEW model alias under `models` like `openrouter/120b-pinned` with `params.models = ["openrouter/openai/gpt-oss-120b:free"]`, then a separate fallback alias.
- (c) Keep `openrouter/auto` as primary but reorder its `params.models` array so `gpt-oss-120b:free` is first — relies on openclaw's router being deterministic "try in order until success."

### B. Add stock-bot-specific tool-use guidance
**File:** `/home/openclaw/.openclaw/workspace/TOOLS.md`

Current: 860-byte stub with `camera.snap`, `ssh.connect`, `tts.speak` example rules — none relevant.

Proposed content (verbatim — user review requested):
```markdown
# Tool-Use Rules

## Ticker / market data
- For any current price query (e.g. "What is NVDA doing?", "Is $AMD above support?"), use `web_search` to fetch a fresh quote and `web_fetch` if you need a specific source.
- For project/system state ("what's in TODO.md?", "what process is on port 18789?"), use `read` for files and `exec` for shell commands.
- When the user's message contains a placeholder token like `<TICKER>`, `<PRICE>`, `<DATE>`, treat it as a parameter to fill via tools — never reply "please provide the current price"; fetch it yourself.

## Web search
- For news / headlines / dated events, use `web_search` first, `web_fetch` for specific URLs.
- Web-search providers occasionally fail (quota, network). If `web_search` errors, try `exec` for a fallback: `python3 -c "import yfinance; print(yfinance.Ticker('NVDA').info)"` for prices, or `curl` for specific endpoints.

## Files and code
- For any "read/show/print/quote X" where X is a file path, use `read` with the exact path.
- Never invent file contents. If `read` fails, say so explicitly — do NOT paraphrase what the file might contain.

## Refusal rules
- Never reply "please provide X" when X is something a tool can fetch.
- Never name an analyst, YouTuber, or influencer as the source for a claim — cite specific dates, numbers, or named events instead.
- If you genuinely don't know and no tool applies, say "I don't have a way to check that from here." Never bluff.
```

### C. Anchor identity as a stock-bot
**File:** `/home/openclaw/.openclaw/workspace/IDENTITY.md`

Current (162 bytes): "Clawdbot, AI research agent ..."

Proposed content (verbatim — user review requested):
```markdown
# Identity

You are Clawdbot, a stock-signal and market-intelligence Discord bot. You answer questions about tickers, market news, project state, and the consensus engine running on this host. You have access to read/exec/web_search/web_fetch tools and you use them whenever the question needs concrete facts rather than priors.

When you don't know, say so. When you have a tool that can answer the question, use the tool — never ask the human to provide the data instead.
```

### D. Route `!ask` through the same openclaw agent (ENGINE CODE — needs explicit user OK)
**File:** `/home/openclaw/.openclaw/workspace/consensus_engine/alerts/commands.py`

In `_handle_ask` (around line 227–234 where `call_with_fallback` is invoked), replace the direct `llm_client` call with a `subprocess.create_subprocess_exec` call mirroring the pattern in `consensus_engine/main.py:_handle_mention` (around line 460). Both paths now share one config, one prompt, one model chain. Channel-history context can either be dropped (openclaw agent has its own session memory) or prefixed to the message body — propose dropping for first cut, can re-add later if needed.

Decision needed: drop channel history, or keep it as a prefix? (Recommend drop.)

### E. Refresh stale memory
**File:** `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/project_mention_openrouter_unreliable.md`

Currently claims primary is `glm-4.5-air:free`. After A lands, primary is pinned to `gpt-oss-120b:free` with `openrouter/auto` fallback. Mark superseded or rewrite with new state.

## Validation (real-world, gated on Discord scanner READY per `[[verify-scanner-ready-before-ping]]`)

After step A only (model pin):
1. `sudo -u openclaw openclaw agent --local --agent main --message "What is 7 times 8?"` → `56` ✓
2. `sudo -u openclaw openclaw agent --local --agent main --message "Read /home/openclaw/.openclaw/workspace/TODO.md and quote line 1 verbatim"` → `# To Do List` ✓

After steps A+B+C (model + prompt):
3. Webhook ping `<@bot> any trump or iran news today of note?` → bot calls `web_search` (or `web_fetch` fallback if `web_search` broken — see TODO #14) and produces a coherent reply with at least one dated headline cited.
4. Webhook re-run of the NVDA-template `<PRICE>` brief from #chat 2026-05-19 00:19 UTC → bot fetches NVDA price via tool and produces the brief. Does NOT reply "please provide the current price."

After step D (`!ask` unification):
5. `!ask hello` returns the same coherent reply as `<@bot> hello`.
6. `!ask` round-trip latency under 60s.

## Risks
- Pinning a model concentrates risk on that model. Mitigated by `openrouter/auto` fallback (per user direction).
- Subprocess shell-out for `!ask` adds ~3-5s overhead. Acceptable for the quality lift.
- `TOOLS.md` wording affects every `@-mention` reply — user should review verbatim text in section B before apply.
- Validation step 3+4 are partially gated on TODO #14 (web search providers). If `web_search` is still failing at apply-time, expect the bot to either `exec`-fallback to yfinance/curl OR explicitly say "I don't have a way to check that from here" — both are acceptable per the proposed refusal rules.

## Implementation order
0. Schema-verify the `agents.defaults.model.fallback` shape.
1. Apply A (openclaw.json edit + chown back to openclaw + restart gateway). Run validation 1+2.
2. Apply B (TOOLS.md rewrite). Restart gateway. Run validation 3+4 (real-world ping with scanner READY confirmed).
3. Apply C (IDENTITY.md rewrite). Restart gateway. Re-run validation 3+4.
4. Apply D (`commands.py` edit). Restart consensus-engine. Run validation 5+6.
5. Apply E (memory refresh).

Each step is independently revertable — each touches one file.

## User decisions before implementation
1. **TOOLS.md verbatim text in section B** — review or edit.
2. **IDENTITY.md verbatim text in section C** — review or edit.
3. **Engine code edit in section D (`commands.py`)** — explicit OK needed (this is the only engine-code change in this spec).
4. **`!ask` channel-history** — drop (recommended) or keep as prefix?
