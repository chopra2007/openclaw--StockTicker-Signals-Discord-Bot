# Chat-memory cluster — TODO #39 deep design

**Cluster:** chat-memory (Discord bot per-channel chat memory)
**Bucket:** **1 = not built** (a durable, recallable long-term memory layer for the
bot's chat does not exist) — with a strong **bucket-4 (off / mis-wired)** sub-finding:
the memory plumbing OpenClaw ships is enabled in config but is **not actually firing
on the bot's real reset path**, and its search index is **frozen / pointed at the
wrong folder**. Details below.
**Date:** 2026-06-13
**Mode:** research + design + proving on real data. No code/config/service changes made.

---

## 0. TL;DR for the user (plain words)

- **Today the bot forgets almost everything.** Each Discord channel keeps one running
  chat ("the cue"). When the bot software restarts, that cue is renamed to a dead
  archive file and the channel starts empty. That restart has happened many times —
  **229 dead-archive files** are sitting in the folder right now. So the cue rarely
  lives more than about a day.
- **OpenClaw already has a "save before forgetting" feature, but it isn't catching the
  bot's resets.** The feature (`session-memory` hook) only fires when someone types the
  commands `/new` or `/reset`. The bot doesn't reset that way — it resets when the
  software restarts. Proof: only **3** command-style archives exist vs **229**
  restart-style ones, and the last memory file that feature produced is dated
  **May 20** — 24 days ago. So in practice it saves nothing for the chat.
- **OpenClaw also has a search-the-old-notes feature, but it's pointed at a frozen,
  wrong copy.** Its search index file (`main.sqlite`) was last updated **May 20** and the
  extra folder it's told to search is a stale May-5 snapshot, not the live one. So even
  the notes it does have aren't being kept findable.
- **I proved the fix works on your real data.** I took the biggest real bot-channel
  archive (510 KB, the #chat channel from May 19 to June 2), squeezed it down to a 4.4 KB
  summary (**115x smaller**), then asked the bot — using only that tiny summary, not the
  big file — *"why was the bot giving false NVDA signals back on May 20?"* It answered
  **correctly**, naming the exact cause and the exact file. That is recall of a month-old
  detail from a small summary. (Full transcript + summary + answer shown in §6.)
- **My recommendation:** Architecture **(b)** — a small summary table inside the bot's
  own database, plus a recall tool the bot calls only when it needs old context, plus a
  30-day cleanup of raw archives that runs only after the summary is safely stored.
  This is the only option that actually delivers "recall a month-old summary while
  keeping the live chat small." It is moderate effort and uses patterns already in this
  codebase.

---

## 1. Current mechanism — verified findings (with doc quotes)

### 1.1 How the bot's chat memory works today
- Each `@mention` / `!ask` runs `consensus_engine/main.py:_handle_mention()`
  (verified lines 594-645), which spawns:
  `openclaw agent --local --json --agent main --session-id channel-<channel_id>
   --message <wrapped> --timeout 240`.
  So **one reused OpenClaw session per Discord channel** — the conversation accumulates
  across messages and days under session id `channel-<id>`.
- The conversation lives entirely in OpenClaw (not in `consensus_engine`), under
  `/home/openclaw/.openclaw/agents/main/sessions/`:
  - `channel-<id>.jsonl` — the transcript the model re-reads each turn.
  - `channel-<id>.trajectory.jsonl` — full tool-call trace (NOT fed back to the model).
  - `sessions.json` — small key→metadata store (token counters, model, compaction count).

### 1.2 How OpenClaw bounds context today — "safeguard" compaction
Config (verified `openclaw.json:51-54`):
```json
"compaction": { "mode": "safeguard", "reserveTokens": 16384 }
```
What "safeguard" does, from the installed docs:

> "When a conversation approaches that limit, OpenClaw **compacts** older messages into
> a summary so the chat can continue. … The full conversation history stays on disk.
> Compaction only changes what the model sees on the next turn."
> — `docs/concepts/compaction.md`

> "Built-in safeguard summarization **re-distills prior summaries with new messages
> instead of preserving the full previous summary verbatim**."
> — `docs/reference/session-management-compaction.md`

Trigger (verified, same doc, "When auto-compaction happens"):
> "Threshold maintenance: after a successful turn, when `contextTokens > contextWindow
> - reserveTokens`."
plus overflow-recovery on a provider "context length exceeded" error.

**reserveTokens is silently bumped.** The doc states a floor:
> "If `compaction.reserveTokens < reserveTokensFloor`, OpenClaw bumps it. Default floor
> is `20000` tokens." — `docs/reference/session-management-compaction.md`

So our configured `16384` is **raised to 20000** at runtime. Relative to the model
windows in §2, 20k of headroom is small (≈15% of the 131k primary window) — fine for
the reply, but it means compaction kicks in fairly late and each one is an extra LLM
call (latency + cost). Confirmed live: the largest archived bot transcript already
contains **6 compaction summaries** (see §6), so this path is active, not theoretical.

### 1.3 The real weakness vs the user's goal: safeguard is LOSSY and the cue gets wiped
- Safeguard summaries compress detail. The first compaction summary in the real
  bot transcript (quoted in §6.2) kept stock symbols and a root-cause line but
  flattened an entire investigation into a few bullets. A diagnostic question about an
  *old* turn can lose the exact detail once that turn is summarized.
- Worse, the whole cue is **wiped on gateway (bot software) restart**: OpenClaw renames
  every channel session to `channel-<id>.deleted.<timestamp>.jsonl` and starts empty.
  Verified counts in the live sessions dir:
  - **229** `*.deleted.*` files (gateway-restart archives)
  - **3** `*.reset.*` files (the `/new`-or-`/reset` command path)
  So the bot's resets are ~99% restart-driven, not command-driven. This matters a lot
  for §1.4.

### 1.4 The persistence OpenClaw "has" is NOT firing for the bot (key finding)
`openclaw.json:116` enables the `session-memory` hook. Its own doc
(`dist/bundled/session-memory/HOOK.md`) states exactly when it runs:

> events: ["command:new", "command:reset"] … "Save session context to memory **when
> /new or /reset command is issued**." … "Creates a new file at
> `<workspace>/memory/YYYY-MM-DD-HHMM.md`."

It writes a `# Session …` header + a `## Conversation Summary` of the **last 15
user/assistant messages** (raw extracted text; verified in `handler.js`).

**The gap:** the bot resets via *gateway restart* (the `.deleted.*` path), which does
**not** raise `command:new`/`command:reset`. So this hook almost never fires for the
Discord channels. Proof: the most recent file it could have produced is
`memory/2026-05-20-0340.md` — **24 days old** — while the bot's channels were wiped at
least twice in June (2026-06-08, 2026-06-12). The "enabled" persistence is effectively
inert for this use case.

### 1.5 `memoryFlush` exists but does not save chat to a queryable store either
`docs/concepts/compaction.md` + `session-management-compaction.md`:
> "Before compaction, OpenClaw can run a **silent memory flush** turn to store durable
> notes to disk." Default `enabled: true`, `softThresholdTokens: 4000`.

It runs a hidden `NO_REPLY` agent turn that *asks the model to write notes to
`memory/*.md`*. Two limits for our goal: (1) it only fires right before a compaction,
not on the restart-wipe; (2) it writes free-form workspace notes, not a per-channel,
queryable record — and it depends on the model choosing to write something useful.
`sessions.json` tracks `memoryFlushAt` / `memoryFlushCompactionCount`, but the live
store currently holds only the dreaming-cron entry (channels were just wiped), so I
could not observe a recent flush for a channel.

### 1.6 The memory **search** layer is real but stale + mis-pointed (bucket-4 finding)
OpenClaw's `memory-core` plugin is **enabled** (`openclaw.json:331-338`) with
`dreaming.enabled: true`, and `memorySearch.provider: "github-copilot"`. The builtin
engine indexes `MEMORY.md` + `memory/*.md` into a per-agent SQLite file and offers
`memory_search` / `memory_get` tools (`docs/concepts/memory-builtin.md`).

Two concrete defects found on disk:
1. **Index is frozen.** `/root/.openclaw/memory/main.sqlite` (27 MB) was last written
   **2026-05-20 20:24** — 24 days stale. New chat content is not being indexed.
2. **extraPaths points at the wrong / stale folder.** Config sets
   `memorySearch.extraPaths: ["/root/.claude/projects/-root--openclaw-workspace/memory"]`.
   That folder exists but is a **root-owned May-5 snapshot** (last file dated May 5).
   The *live* Claude memory dir is `-home-openclaw--openclaw-workspace/memory` (files
   dated Jun 11). So the search is told to read a frozen copy.

Net: even OpenClaw's own recall path can't reliably answer "what did we discuss a month
ago" today, because nothing keeps the index fresh for chat and the extra path is wrong.

### 1.7 Why "it keeps getting bigger" is true at two levels (confirmed)
1. **Live file never shrinks after summarizing.** `truncateAfterCompaction` and
   `maxActiveTranscriptBytes` are **both unset** in our compaction block (verified — only
   `mode` and `reserveTokens` are present). The doc is explicit:
   > "The byte guard requires `truncateAfterCompaction: true`. Without transcript
   > rotation, the active file would not shrink and the guard remains inactive."
   > — `docs/concepts/compaction.md`
   So even after a summary, the on-disk transcript (and the ~10 MB trajectory sidecar)
   keeps growing within a session, raising reopen cost/latency.
2. **Archives pile up forever.** 108 MB / ~354 files in the sessions dir, with
   `.deleted` archives back to early May. `systemd-tmpfiles` does not touch this dir.
   (Note: OpenClaw *does* have a built-in `session.maintenance` cleanup with
   `pruneAfter: 30d` and `resetArchiveRetention`, per `session-management-compaction.md`
   — but it is not configured here, so nothing prunes.)

---

## 2. Model chain context-window sizes (so reserveTokens makes sense)

Chain from `openclaw.json:36-43` (`agents.defaults.model`). Windows confirmed via
OpenRouter model pages (the chain is OpenRouter-routed, so the size comes from
OpenRouter, not the local catalog):

| Role | Model | Context window | Max output |
|---|---|---|---|
| primary | `openrouter/openai/gpt-oss-120b` | **131,072** | ~131k (policy-capped lower) |
| fallback 1 | `openrouter/openai/gpt-4.1-nano` | **1,047,576** | 32,768 |
| fallback 2 | `openrouter/qwen/qwen3-235b-a22b-2507` | **262,144** | 16,384 |
| fallback 3 | `openrouter/openai/gpt-oss-120b:free` | **131,072** | ~131k |

Reading of this:
- The **binding constraint is the primary's 131k window** (and the `:free` twin). The
  20k effective reserve = ~15% headroom on 131k. Reasonable, but it means a channel
  cue can grow to ~110k tokens (~400 KB of text) before safeguard fires — which is why
  the live transcript reached ~500 KB before the last wipe.
- `sessions.json` showed `contextTokens: 200000` for the dreaming-cron session — that is
  OpenClaw's tracked counter / an override label, **not** the real gpt-oss window; don't
  treat the store counter as the hard cap (the deep-dive doc warns about exactly this:
  "`contextTokens` … is a runtime estimate/reporting value; don't treat it as a strict
  guarantee").
- Implication for design: with a 131k primary, we do **not** need a huge live cue. A
  small rolling cue (recent turns) + an on-demand recall tool is plenty, and keeps every
  reply fast.

---

## 3. How Claude / Claude Code does memory — and how it compares

This very session runs inside Claude Code, whose memory for this project lives at
`/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/`. Verified real
structure:
- **`MEMORY.md`** = a curated **index**: short one-line entries, each linking to a
  detail file. Example entries: `[comm-check fail 2026-06-09 §3](...)`,
  `[Wolf phase-4 LIVE (2026-06-02)](project_wolf_phase4_shipped.md)`.
- **One file per fact / incident** beside it, e.g.
  `comm-check-fail-2026-06-09-section-3.md`, `project_wolf_phase4_shipped.md`. Each is a
  small, self-contained note (1-7 KB).
- Recall = read the index, then open only the specific file you need. New facts append a
  new small file + one index line; they don't bloat a single growing blob.

OpenClaw's model (default `memory-core`) is conceptually the same file pattern
(`MEMORY.md` + `memory/YYYY-MM-DD.md`) **plus** a machine layer Claude Code doesn't have:
a SQLite hybrid (keyword + vector) search index over those files, and "dreaming" (a
scored promotion of recurring short-term notes into `MEMORY.md`).

**Comparison for our goal:**

| Property | Claude Code (file-per-fact + index) | OpenClaw safeguard compaction | OpenClaw memory-core (files + search) |
|---|---|---|---|
| Old detail survives? | Yes — detail files are never rewritten | **No** — re-distilled, lossy | Yes if it was written to a `memory/*.md` note |
| Recall a month-old item? | Yes — open the file | Only if it landed in the live summary | Yes — `memory_search` (when index is fresh) |
| Keeps live context small? | Yes — index is tiny, details loaded on demand | Partly — but cue grows to ~110k first | Yes — notes aren't injected every turn |
| Auto-captures chat? | No (human/agent writes notes) | Yes (but lossy + wiped on restart) | Only via the flush/hook, which aren't firing here |
| Fit for "recall summary from a month ago" | **Strong** | Weak | Strong **if** capture + index are actually running |

**Takeaway:** Claude Code's win is the *append-only, never-rewritten, indexed* pattern.
OpenClaw can do this (memory-core is the same idea) but for *chat* it currently neither
captures (hook mis-fires) nor keeps the index fresh. The recommended design below
borrows Claude Code's "small recallable summary per unit, never overwritten, query on
demand" pattern and implements it where it will reliably fire: inside the bot's own
pipeline, in the bot's own SQLite DB.

---

## 4. The three architectures (tradeoffs)

Goals restated: **(1)** keep the live cue small so replies stay fast; **(2)** preserve
info so the bot can recall even a month-old summary; **(3)** a cleanup cron, allowed
ONLY after the main content is summarized and still recallable.

### (a) Stay on safeguard + turn on file rotation
Set in `openclaw.json` compaction block:
`truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"`, and configure
`session.maintenance` (`pruneAfter: 30d`) so archives self-prune.
- **Goal 1 (small cue):** ✅ live file rotates to a compacted successor; trajectory
  stops ballooning. Reopen cost drops.
- **Goal 2 (month-old recall):** ❌ still lossy. Rotation throws away the raw tail you
  rotated past; you keep only the re-distilled summary, and only until the next restart
  wipe. No queryable month-old store.
- **Goal 3 (safe cleanup):** ⚠️ `session.maintenance` prunes by age, but it prunes the
  *only* copy — there's no separate durable summary it verifies first. So it satisfies
  "tidiness" but not "summarized-and-recallable-before-delete."
- **Effort:** Lowest (3 config keys). **Cost:** ~free. **Failure modes:** none new; just
  doesn't meet goal 2/3. **Verdict:** necessary hygiene, **not sufficient** alone.

### (b) Durable per-channel rolling-summary table + on-demand recall tool  ← RECOMMENDED
A new SQLite table in the bot's own `consensus.db` holds dated rollup summaries per
channel. A summarizer writes a rollup when a channel session ends/rotates (or on a
schedule). The agent gets a `recall_chat_memory` tool it calls only when it needs old
context. A cleanup cron deletes raw `.deleted.*` archives older than 30 days **only after
verifying** a covering summary row exists.
- **Goal 1 (small cue):** ✅ the live cue stays whatever safeguard keeps; old context is
  NOT injected every turn — it's pulled on demand. Combine with (a)'s rotation for the
  live-file size win.
- **Goal 2 (month-old recall):** ✅ **proven on real data in §6.** A 4.4 KB rollup of a
  510 KB transcript answered a month-old NVDA question with the exact file+function. The
  summary row is never rewritten, so detail survives.
- **Goal 3 (safe cleanup):** ✅ cleanup is gated on "summary row exists and covers this
  archive's date range" — exactly the user's condition.
- **Effort:** Moderate. New table (fits `db.py` pattern), one summarizer function, one
  recall tool registered for the agent, one cron. **Cost:** ~1 cheap LLM call per channel
  per rollup (gpt-oss-120b ≈ fractions of a cent; the rollup input is the *raw* archive,
  ~500 KB ≈ 130k tokens ≈ ~$0.01-0.02 each, infrequent). **Failure modes:** summarizer
  must run before cleanup (gate handles it); recall tool quality depends on rollup
  quality (extractive+LLM rollup in §6 was high-fidelity). **Verdict:** the only option
  that meets all three goals; best fit for this codebase.

### (c) Vector / semantic index (LanceDB or memory-core, fixed)
Either fix memory-core (refresh index, correct extraPaths, make capture fire) or install
`memory-lancedb`, and index every channel turn for semantic recall.
- **Goal 1:** ✅ on-demand recall, small cue.
- **Goal 2:** ✅ semantic recall ("what did we say about that earnings bug") even with
  different wording — strongest *fuzzy* recall.
- **Goal 3:** ⚠️ cleanup of raw archives is safe once indexed, but "is it indexed yet"
  is harder to verify atomically than a single summary row.
- **Effort:** Highest. Embedding provider must stay healthy (the current github-copilot
  provider's index is already stale — evidence the moving parts are fragile here). More
  to monitor, more to break, IP/quota exposure on embeddings.
- **Cost:** embedding calls per turn + storage. **Failure modes:** stale index (already
  happening), provider/auth drift, sqlite-vec load issues. **Verdict:** powerful but
  over-engineered for a handful of low-traffic channels; defer. Option (b)'s table can
  add an FTS5 keyword index trivially later if fuzzy recall is wanted, without embeddings.

---

## 5. Recommended design (concrete)

**Choose (b)**, layered on top of (a)'s cheap hygiene. Reasoning: it is the only design
that delivers month-old recall while keeping replies fast, it reuses this codebase's
existing SQLite + async-DB + cron patterns, it has the fewest fragile moving parts
(no embedding provider to keep healthy), and the recall quality is already **proven on
real data** (§6). Turn on (a)'s rotation too, because that fixes the unbounded live-file
growth regardless.

### 5.1 Schema — new table in `consensus_engine/db.py` `SCHEMA` block
Matches the existing style (REAL epoch timestamps, `IF NOT EXISTS`, AUTOINCREMENT id,
a `CREATE INDEX`). Mirrors `briefing_runs` / `youtube_analysis_runs`:

```sql
CREATE TABLE IF NOT EXISTS chat_memory_rollups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL,          -- Discord channel id (matches session-id channel-<id>)
    archive_path    TEXT NOT NULL,          -- [codex] full path of the EXACT raw archive this covers
    source_sha256   TEXT NOT NULL,          -- [codex] hash of the raw archive bytes (cleanup identity)
    session_label   TEXT,                   -- the openclaw session id (channel-<id>) for reference
    status          TEXT NOT NULL DEFAULT 'pending',  -- [codex] pending|complete|failed — cleanup gate
    span_start_utc  REAL NOT NULL,          -- first message timestamp in the rolled-up range
    span_end_utc    REAL NOT NULL,          -- last message timestamp
    turn_count      INTEGER NOT NULL DEFAULT 0,
    source_bytes    INTEGER NOT NULL DEFAULT 0,  -- size of raw archive summarized (audit/cleanup gate)
    rollup          TEXT NOT NULL,          -- the compact summary text (the recallable artifact)
    model           TEXT,                   -- which model wrote the rollup
    started_at      REAL,                   -- [codex] when summarization began
    completed_at    REAL,                   -- [codex] when it finished (status='complete')
    created_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cmr_archive ON chat_memory_rollups(source_sha256);  -- [codex] one row per exact archive; re-runs are idempotent
CREATE INDEX IF NOT EXISTS idx_cmr_channel ON chat_memory_rollups(channel_id, span_end_utc);
-- Optional later, for keyword recall without embeddings:
-- CREATE VIRTUAL TABLE chat_memory_fts USING fts5(rollup, content='chat_memory_rollups', content_rowid='id');
```

> **[codex revision 2026-06-13 — BLOCKER fix: cleanup/summarization race]** The original schema
> identified a covered archive only by date-range overlap (`span_end_utc`) + `source_bytes > 0`.
> Codex correctly flagged that this can delete the WRONG file: a date-range match could point at a
> different overlapping archive, or at an incomplete/failed summary, and a burst of restart-wipes
> makes overlaps common. The fix above is **identity, not overlap**: every rollup row pins the exact
> `archive_path` + `source_sha256` of the bytes it summarized, plus a `status`. **The cleanup cron
> (§5.4) must be rewritten to: (1) compute the candidate archive's sha256, (2) delete it ONLY if a
> row exists with that exact `source_sha256` AND `status='complete'` AND `source_bytes` == the
> archive's real size. Never delete on a date-range/`bytes>0` match.** The `UNIQUE(source_sha256)`
> makes re-running after a failed delete safe (the summary row is already there → skip).

> **[codex revision 2026-06-13 — privacy/secret retention]** These raw `.deleted.*` JSONL archives
> are full agent trajectories (confirmed in `bounded.md` #38: they hold model IDs + `data` payloads
> = real conversation + tool outputs). They can contain file paths, email bodies (Wolf Gmail), API
> tokens, and other secrets. The design deletes raw archives after 30 days but keeps the **rollups
> permanently** — so any secret that lands in a rollup becomes a permanent artifact that survives the
> raw-archive deletion. **Before the summarizer writes a rollup it MUST run redaction** (drop tool-result
> payloads; mask anything matching key/token/email patterns — reuse or extend the repo's existing
> secret-scrub if one exists). Define a retention + delete/rebuild policy for rollups too (e.g. a way
> to purge a channel's rollups on request), not just for the raw archives. This is a build-blocking
> requirement for #39 AND a precondition on #38's transcript-archive copy step.
Disk cost is trivial (user has ~40 GB free; rollups are KBs). Retention of summaries =
**permanent** (or far longer than 30 days); only the *raw archives* get the 30-day cron.

### 5.2 Where the summarizer runs
A small async function `summarize_channel_archive(path) -> rollup_row`, living next to the
other pipeline code (e.g. `consensus_engine/memory/chat_rollup.py`). It:
1. Parses the JSONL archive (the §6 parser is the working reference: extract
   user+assistant text turns, strip the `[Context: …]` preamble from user turns, also
   read existing `compaction` summaries already in the file so nothing is lost).
2. Builds a **cheap extractive rollup first** (date-bucketed Q/A pairs, capped per line) —
   this alone gave 115x compression and answered the recall question in §6.
3. Optionally passes that through one gpt-oss-120b call to tighten it into a
   "Decisions / Open questions / Identifiers (tickers, files, IDs) / Pending asks"
   shape (the same headings safeguard already uses, see §6.2) — keeps identifiers, which
   is what diagnostic recall needs.
4. Writes one `chat_memory_rollups` row via the existing `AsyncConnection.execute`.

**Trigger options (pick one, recommend the first):**
- **On rotation/reset (event-driven):** when the bot detects a channel was archived
  (a `channel-<id>.deleted.*` appeared) — e.g. a lightweight check at gateway-reconnect
  in `_handle_mention`'s startup path, or a cron that scans for un-summarized
  `.deleted.*` files. Most faithful to "summarize before you lose it." Robust to the
  restart-wipe that the OpenClaw hook misses.
  > **[codex revision — backlog/catch-up throttle]** The earlier "one channel per nightly run"
  > throttle (final-plan §3 #39) cannot drain the existing backlog (229 `.deleted` archives, plus
  > a noted burst of 7 restarts in minutes) — at one/night that's months, during which cleanup
  > stays blocked. **Throttle by a budget (e.g. ≤ N archives or ≤ M total bytes or a wall-clock/
  > token cap per run), process oldest-un-summarized first, and add a one-time catch-up pass** that
  > works through the backlog in budgeted batches. Log a backlog count each run so the drain is
  > observable. The `UNIQUE(source_sha256)` makes every batch idempotent, so a crashed run just
  > resumes.
- **Pre-compaction (richer, optional):** also summarize when safeguard is about to
  compact, so within-session detail is captured before re-distillation. OpenClaw exposes
  `before_compaction` / `session_before_compact` hooks (`docs/concepts/compaction.md`
  "Related"), but the simpler event-driven scan above already covers the dominant
  restart-wipe path and needs no OpenClaw-side wiring.

### 5.3 The recall trigger — on-demand tool, NOT auto-inject (recommended)
Add a tool the agent can call: `recall_chat_memory(channel_id, query)` →
SELECT recent rollups for that channel (optionally FTS5-matched on `query`), return the
matching rollup text. The agent calls it only when a user asks about old context. This
keeps the live cue small (goal 1) and matches the proven §6 flow (rollup-in, answer-out).

Two ways to expose it:
- **Cleanest:** register it as an OpenClaw tool/skill the `main` agent can call (the bot
  already runs `openclaw agent`). The agent decides when to recall.
- **Simplest, no OpenClaw wiring:** detect "old context" intent in `_handle_mention`
  before spawning, query `chat_memory_rollups`, and prepend the matched rollup to
  `wrapped_message` for that one turn only (not persisted into the cue). This avoids
  touching OpenClaw's tool registry.

Recommend the **OpenClaw tool** form if tool registration is straightforward; otherwise
the prepend-on-intent form is a safe, self-contained fallback.

(Auto-injecting recall every turn is NOT recommended — it re-bloats the cue, the exact
problem we're solving, and burns tokens on turns that don't need history.)

### 5.4 Cleanup cron (goal 3) — gated, 30-day retention
A daily cron (use this repo's `/root/task_system/scripts/create_task.sh` + a systemd
timer, per CLAUDE.md "Deferred Task System") that:
1. Lists `*.deleted.*.jsonl` archives older than **30 days**.
2. **[codex revision — identity gate, not date-overlap]** For each candidate, compute its
   `sha256`, then delete it **ONLY IF** a `chat_memory_rollups` row exists with that exact
   `source_sha256` **AND** `status='complete'` **AND** `source_bytes` == the archive's real byte
   size. If no such row exists, **summarize it first** (write a `pending`→`complete` row), then
   re-check. Never delete on a date-range or `bytes>0` match — that can delete the wrong/un-summarized
   file (Codex BLOCKER).
3. Only then deletes the raw archive + its `.trajectory.*` sidecar.
4. Logs what it deleted; never touches `chat_memory_rollups`. Summaries are kept
   permanently (subject to the redaction/retention policy added under §5.1).
This is exactly the user's rule: "cleanup only if the main stuff is summarized and still
accessible later (even 30 days later) before raw archives are deleted."

### 5.5 Also do the cheap hygiene from (a)
In `openclaw.json` compaction block add `truncateAfterCompaction: true` and
`maxActiveTranscriptBytes: "5mb"` so the live transcript + trajectory stop ballooning
within a session. This is independent of the table work and helps reply latency now.
(NOTE: this is a production config edit — out of scope for this research session; flag
for the build session. Also note `reserveTokens` is already floored to 20000.)

### 5.6 Fix the stale memory-core wiring (small, separate)
Independently worth fixing (bucket-4): point `memorySearch.extraPaths` at the *live*
`-home-openclaw--openclaw-workspace/memory` dir (not the May-5 root copy), and confirm
the index refreshes (`openclaw memory index --force`). This makes OpenClaw's own
`memory_search` useful again as a secondary recall path. (Config/CLI change — build
session, not now.)

---

## 6. REAL-DATA BACKTEST — recall PROVEN (not hand-waved)

**Goal:** prove on real data that a small summary lets the bot recall an OLD detail that
naive truncation would drop. Done end-to-end against a real archived transcript.

### 6.1 The source (real archive)
File: `/home/openclaw/.openclaw/agents/main/sessions/channel-1468890179698692147.deleted.1781319602.jsonl`
- This is the real **#chat bot channel** transcript, archived at the 2026-06-12 20:00 wipe.
- **510,254 bytes.** 184 JSONL lines: 1 session header, 155 messages (18 user, 84
  assistant, 53 toolResult), **6 safeguard compaction summaries**, 20 custom entries.
- Spans **2026-05-19 → 2026-06-02**.

### 6.2 What safeguard already keeps (the lossy baseline) — real excerpt
First `compaction` entry in that file (verbatim, trimmed):
```
## Decisions
- [Answer to math question]: Directly answered "12 times 9" as 108
## Constraints/Rules
- Answer directly and concisely … Never invent file contents …
## Exact identifiers
- Stock symbols mentioned: HD, VIAV, GOOG, IREN, AMC
- API sources: finnhub.io, SEC Filings (8-K, Form 4)
…
**Turn Context (split turn):**
## Decisions
- [Decision]: Need to investigate why the system is giving false signals about NVDA earnings
## Pending user asks
- "No shit Sherlock. I want you to find out why it's giving false signals and let me know."
```
So safeguard keeps identifiers and headlines but compresses the *investigation* — a
later "what exactly was the NVDA bug" question could miss the root cause. That's the gap
the rollup closes.

### 6.3 The rollup I built (the recall artifact)
Cheap extractive rollup (Python, no LLM needed for this step) → date-bucketed Q/A pairs,
capped per line. Result: **4,416 bytes** from 510,254 bytes = **115.5x compression**.
Saved at `/tmp/chatmem/extractive_rollup.txt`. It captured, among others, the real
May-20 exchange:
```
[2026-05-20T21:23:23.058Z]
  Q: No shit Sherlock. I want you to find out why it's giving false signals…
  A: Root Cause Found: The fetch_recent_earnings_for_ticker function in
     consensus_engine/scanners/earnings_calendar.py doesn't filter for past earnings
     dates. Finnhub's /stock/earnings endpoint returns ALL quarters…
```

### 6.4 The recall test (proves goal 2)
I fed **only the 4.4 KB rollup** (NOT the 510 KB transcript) to gpt-oss-120b via
OpenRouter, with a prompt: "answer using ONLY the rollup," and asked an OLD question
about a topic at the very start of the conversation:

> **Q:** "Back around May 20, I asked you to find out why the bot was giving false NVDA
> signals. What was the actual root cause you found, and which file/function was
> responsible?"

> **A (model, from the rollup only):** "The false NVDA signals were caused by the
> **`fetch_recent_earnings_for_ticker`** function not filtering out future earnings
> dates. It was pulling the upcoming Q1 2026 earnings (period "2026-06-30") as if they
> were already reported. The problematic code lives in
> **`consensus_engine/scanners/earnings_calendar.py`**, in the
> `fetch_recent_earnings_for_ticker` function."

**This is correct and specific** — exact function, exact file, exact mechanism — recalled
from a 4.4 KB summary, for a topic two weeks (and many turns) back in the transcript.
Artifacts: `/tmp/chatmem/extractive_rollup.txt`, `/tmp/chatmem/recall_answer.txt`.

**Conclusion:** a summary+recall layer (architecture b) demonstrably satisfies "recall a
summary from a month ago" on this project's real chat data, at ~115x size reduction, with
zero loss of the load-bearing identifiers.

> **[codex revision — n=1 proves feasibility, not reliability]** This is ONE 510 KB transcript and
> ONE primary Q&A (plus 4 follow-ups summarized but not shown). That is enough to justify *choosing*
> architecture (b), but NOT enough to declare the recall *quality* proven. **Before #39 goes live,
> build a small eval set**: ~10-20 questions across several channels and dates, each with an expected
> answer, plus **hallucination traps** (questions whose answer is NOT in the rollup → the bot must
> say "I don't have that") and **negative queries**. Gate go-live on that eval, not on the single
> backtest. Also note: the §5.3 **prepend-on-intent** fallback depends on a brittle intent detector
> (it can miss "what did we decide about that thing last month?" or over-inject into unrelated turns).
> Prefer the real on-demand recall tool, or expose an explicit `recall …`/`!recall` command the user
> can invoke, with conservative intent rules + tests — don't ship intent-sniffing alone.

---

## 7. User decisions (each with my recommendation)

1. **Which architecture?**
   → **Recommend (b)** — durable per-channel rolling-summary table + on-demand recall
   tool, plus (a)'s cheap file-rotation hygiene. Only option meeting all 3 goals; proven
   on real data; fits the codebase. Defer (c) vector index unless fuzzy semantic recall
   becomes a real need (and even then, add FTS5 to the (b) table first — no embeddings).

2. **Auto-inject recall vs on-demand recall tool?**
   → **Recommend on-demand** (the agent calls `recall_chat_memory` only when a question
   needs old context). Keeps the live cue small — the whole point. Auto-inject would
   re-create the bloat we're removing.

3. **SQLite summary table vs vector store?**
   → **Recommend the SQLite summary table** in the existing `consensus.db`. Fewest moving
   parts, no embedding provider to keep healthy (the current one is already stale),
   matches `db.py`. Add FTS5 keyword search later if needed.

4. **Cleanup retention?**
   → **Recommend 30-day retention for raw `.deleted.*` archives**, deletion gated on a
   covering summary row existing first; **keep summaries permanently** (or 1 year). Matches
   the user's stated rule exactly. Disk is not the constraint.

5. **(Bonus) Fix the mis-wired bits now or later?**
   → Two quick, separate fixes for the build session: (i) repoint
   `memorySearch.extraPaths` to the live memory dir + refresh the index; (ii) add
   `truncateAfterCompaction: true` + `maxActiveTranscriptBytes: "5mb"` so the live file
   stops ballooning. Both are production-config edits, so not done in this research
   session.

---

## 8. Blockers / open items for the build session

- **Production-config edits are out of scope here** (this was a read-only research
  session). The (a) hygiene keys, the extraPaths fix, and any OpenClaw tool registration
  must be done in a build session with the usual gate.
- **Recall-tool wiring choice** needs a quick spike: confirm whether registering a custom
  OpenClaw tool/skill for the `main` agent is straightforward; if not, fall back to the
  self-contained "prepend matched rollup in `_handle_mention` on old-context intent."
- **Summarizer trigger choice** (event-driven scan for un-summarized `.deleted.*` vs a
  `before_compaction` hook) — recommend starting with the scan; it covers the dominant
  restart-wipe path with no OpenClaw-side dependency.
- **Why so many restarts?** The TODO noted a burst of ~7 gateway restarts on 2026-06-12
  19:42-19:59. Not chased here. If restarts are abnormally frequent, the cue is being
  wiped more than expected — worth a glance, but the (b) design is robust to it either way
  (each wipe just triggers a rollup).

---

## Appendix — files / evidence

- TODO: `todo/bot_chat_memory_redesign.md`
- Spawn path: `consensus_engine/main.py:594-645` (`_handle_mention`, `--session-id channel-<id>`)
- DB pattern: `consensus_engine/db.py` (`AsyncConnection`, `SCHEMA` `CREATE TABLE IF NOT EXISTS` block)
- OpenClaw config: `/home/openclaw/.openclaw/openclaw.json` (compaction :51-54; session-memory hook :116;
  memory-core+dreaming :331-338; memorySearch.extraPaths :55-60; model chain :36-43)
- Sessions store: `/home/openclaw/.openclaw/agents/main/sessions/` (108 MB; 229 `.deleted` vs 3 `.reset`)
- Memory index: `/root/.openclaw/memory/main.sqlite` (27 MB, last written 2026-05-20 — stale)
- Hook doc: `/usr/lib/node_modules/openclaw/dist/bundled/session-memory/HOOK.md`
- Backtest artifacts: `/tmp/chatmem/extractive_rollup.txt`, `/tmp/chatmem/recall_answer.txt`
- Docs read: `docs/concepts/compaction.md`, `docs/reference/session-management-compaction.md`,
  `docs/concepts/context-engine.md`, `docs/concepts/memory.md`, `docs/concepts/memory-builtin.md`,
  `docs/concepts/active-memory.md`, `docs/concepts/dreaming.md`, `docs/reference/transcript-hygiene.md`,
  `docs/reference/api-usage-costs.md`
- Model windows: OpenRouter model pages — gpt-oss-120b (131,072), gpt-4.1-nano (1,047,576),
  qwen3-235b-a22b-2507 (262,144)
