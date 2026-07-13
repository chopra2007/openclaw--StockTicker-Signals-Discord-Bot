# Bot chat memory — keep context small but recall summaries from a month ago

**Status:** DONE 2026-06-15 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-06-13

## The goal (what the user actually wants)

The user wants a better memory setup for the Discord bot's per-channel chat
("the cue"). Specifically:

1. The live chat context must NOT grow so big it bogs things down or starves the
   reply (slow responses, lost answer room).
2. BUT the information should be preserved in an easy-to-access way so the bot
   can recall something — even just a summary — from a month ago in that chat.
3. A cleanup cron IS wanted, **but only if the main stuff is summarized and still
   accessible later (even 30 days later)** before raw archives are deleted. Disk
   is not the constraint (user has ~40 GB free; ~100 MB/month is fine). The
   point of cleanup is tidiness + recall, not saving space.

Three open design questions the user asked (DO NOT answer inline — this todo is
the place to work them out properly later):

- Is there a better way to keep chat context from getting too big to bog things
  down, while still preserving info the bot can easily recall (even a summary
  from a month ago)?
- How does Claude remember things? Is that approach better than OpenClaw's?
- If building a memory setup from scratch, how would you do it?

## What the bot does today (verified this session, 2026-06-12/13)

- @-mention / `!ask` → `consensus_engine/main.py:594 _handle_mention()` →
  spawns `openclaw agent --local --json --agent main --session-id
  channel-<channel_id> ...` (main.py:630-638). One reused session per Discord
  channel, so the conversation accumulates across messages/days.
- Conversation history lives in OpenClaw, NOT in consensus_engine, at:
  `/home/openclaw/.openclaw/agents/main/sessions/`
  - `channel-<id>.jsonl` = the transcript the model re-reads (today's bot
    channel was ~499 KB before reset).
  - `channel-<id>.trajectory.jsonl` = full tool-call trace, NOT fed back to the
    model (today's was ~10 MB for the same channel).
  - `channel-<id>.trajectory-path.json` = pointer to the active runtime file.
- The configured Discord channel is `1468890179698692147` (openclaw.json:139).

### How OpenClaw bounds the model context today
- `openclaw.json` `agents.defaults.compaction`: `{ mode: "safeguard",
  reserveTokens: 16384 }` (openclaw.json:51-54).
- "safeguard" = when the conversation nears the model's context-window limit,
  OpenClaw auto-summarizes older messages (LLM call via the current model) and
  continues, always reserving 16,384 tokens of headroom for the reply.
  Built-in safeguard re-distills prior summaries with new messages (doesn't keep
  the old summary verbatim). Source: OpenClaw docs
  `docs/concepts/context-engine.md`, `docs/agent-runtime-architecture.md`
  (§"Compaction safeguard summarization"); dist files `compact-*.js`,
  `cli-compaction-*.js`, `selection-*.js`. Compaction reasons enum: guard,
  summary, timeout, unknown.
- Result: the "cue eats all tokens, no room to answer" worst case is largely
  prevented. Live price lookups (tool calls) are NOT blocked by a big cue.
- CAVEAT (the real weakness vs. the user's goal): safeguard summarization is
  LOSSY. A diagnostic question about an OLD message (e.g. "why did you say NVDA
  $850 three days ago?") may have lost the exact detail if that turn was already
  summarized. Each compaction also costs an extra LLM call (latency).

### How/when the cue resets today
- On **gateway restart**, OpenClaw archives every channel session (renames the
  live files to `*.deleted.<timestamp>.jsonl`) and starts fresh/empty.
  VERIFIED: gateway restarted 2026-06-12 19:59:39 PDT; all session files renamed
  to `.deleted.1781319602` at 20:00:02 (23 s later). Bot channel is currently
  empty/reset.
- This happens often — distinct reset events found: a near-daily run from
  ~2026-05-05 to 2026-05-15 (millisecond-suffixed `.deleted.<ms>` files), plus
  2026-06-08 01:14 and 2026-06-12 20:00 (second-suffixed). So in practice the
  cue rarely survives more than ~a day before a restart wipes it. (NOTE: there
  was also a burst of ~7 gateway restarts between 19:42–19:59 on 2026-06-12 —
  cause not chased; possibly flapping. Worth a glance if revisiting.)
- Archives are NEVER auto-purged. Sessions dir is currently ~108 MB / 354 files,
  with `.deleted` archives back to early May still present. systemd-tmpfiles
  does not touch this dir.

### Why "it keeps getting bigger" is true at two levels
1. Between restarts, the live transcript + trajectory grow unbounded because
   `truncateAfterCompaction` and `maxActiveTranscriptBytes` are BOTH unset in
   our config. So even after summarizing, the on-disk file does not shrink (the
   10 MB trajectory is the real hog), raising reopen cost/latency.
2. The `.deleted` archives pile up forever (nothing deletes them).

## Possible next steps (priority-ordered)

1. **Decide the memory architecture** (the real ask). Options to evaluate:
   - (a) Stay on OpenClaw safeguard compaction + turn on file rotation
     (`truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"` in
     openclaw.json compaction block) so the live file shrinks after summarizing.
     Lowest effort; still lossy for old detail.
   - (b) Add a durable, queryable long-term memory layer so the bot can recall a
     month-old summary on demand (e.g. periodic per-channel rollup summaries
     written to a store the bot can search — DB table or the existing
     `session-memory` hook / `memoryFlush`, or a vector/keyword index). This is
     what actually satisfies "recall a summary from a month ago."
   - Research how Claude/Claude Code does memory (this repo already uses a
     file-per-fact memory + MEMORY.md index pattern under
     `/root/.claude/projects/.../memory/`) and compare to OpenClaw's
     summarize-in-place model. Note `session-memory` hook is enabled
     (openclaw.json:116) and `memoryFlush` exists in OpenClaw compaction config —
     investigate what they already persist.
2. **Cleanup cron** — only AFTER (1) guarantees the "main stuff" is summarized &
   recallable. Then delete `*.deleted.*` session files older than 30 days
   (user explicitly OK'd 30-day retention). Keep summaries longer / permanently.
3. **Turn on file rotation** (step 1a settings) regardless, to stop the live
   trajectory ballooning to 10 MB+.

## Files / config involved
- `consensus_engine/main.py:594` `_handle_mention` (spawns openclaw agent w/
  `--session-id channel-<id>`).
- `/home/openclaw/.openclaw/openclaw.json` — `agents.defaults.compaction`
  (line 51), `hooks.internal.entries.session-memory` (line 116).
- `/home/openclaw/.openclaw/agents/main/sessions/` — the session JSONL store.
- OpenClaw docs (installed): `/usr/lib/node_modules/openclaw/docs/concepts/
  context-engine.md`, `docs/agent-runtime-architecture.md`,
  `docs/reference/api-usage-costs.md`, `docs/reference/transcript-hygiene.md`.

## Open questions
- What context-window size do the bot's actual chain models have? reserveTokens
  16384 only makes sense relative to that — verify per model in
  openclaw.json agents.defaults.model chain.
- Does `session-memory` hook + `memoryFlush` already persist anything useful we
  can build on, or start fresh?
- Best store for month-old recall: a SQLite table of per-channel rolling
  summaries (simple, fits this codebase's db.py pattern) vs. a vector index
  (semantic recall, more moving parts)?
- Should recall be automatic (always injected) or on-demand (a tool the agent
  calls when it needs old context)? On-demand keeps the live cue small.

### Session notes — 2026-06-13 (discover run todo-sweep)
- **Recommended architecture (b):** a per-channel rolling-summary SQLite table in consensus.db + an on-demand recall path + a 30-day cleanup cron gated on a covering summary existing first. **Recall PROVEN on real data:** a real 510KB #chat archive → 4.4KB rollup (115x), correctly answered a 2-week-old question (skeptic confirmed with 4 more Qs + a hallucination trap).
- **Bucket-4 sub-finding:** OpenClaw's session-memory hook only fires on /new+/reset, never on the bot's restart-resets — so it saves nothing today; the memory search index is frozen (May 20) + points at a stale folder.
- **Gemini review revisions:** summarizer = **nightly cron scan** (NOT a gateway-reconnect hook — that would be an API-cost runaway); cleanup gate by session-label not timestamp ranges; recall via **_handle_mention prepend** first (all-Python) before the OpenClaw tool path (Node build). Also turn on file rotation + repoint memorySearch.extraPaths. Model windows confirmed (primary gpt-oss-120b 131k). Full plan: .claude/discover/todo-sweep-2026-06-13/research/chat-memory.md + final-plan.md §3/§4/§5.
