# To Do List

Items here are suggestions/ideas to tackle in a future session.
Each entry has enough context to generate a prompt/plan from scratch.
Delete an entry when it's completed.

---

<!-- Add items below -->

## 1. Layer C blind-compare with Gemini (operator-driven)

**Layperson:** This session shipped a major quality bump for `!all <TICKER>`.
The final acceptance check is humans-only: ask Google's Gemini the same
question, put the two answers side-by-side, and vote which is better.

**For each ticker NVDA / AMD / TSLA:**
1. Run in Gemini web/CLI: *"Look at <TICKER> stock and come up with a
   bullish or bearish thesis, along with a trade plan composed of: 1.
   buying level 2. stop-loss level 3. take profit level."*
2. Pull the bot's cached narrative:
   ```bash
   python3 -c "import sqlite3, json, hashlib; v=open('consensus_engine/__init__.py').read().split('=')[1].strip().strip(chr(34)); prefix='all_v'+hashlib.sha1(v.encode()).hexdigest()[:8]; c=sqlite3.connect('/home/openclaw/.openclaw/workspace/consensus.db'); row=c.execute('SELECT result_json FROM xref_cache WHERE ticker LIKE ? ORDER BY cached_at DESC LIMIT 1', (f'{prefix}:NVDA',)).fetchone(); print(json.loads(row[0])['embed']['description'])"
   ```
3. Render side-by-side and vote prefer-gemini / prefer-all / tie.
4. v2 ships only when all 3 votes are prefer-all or tie.

**Where to find more:** `.claude/discover/all-command-rebuild/v2-quality-rebuild/RESUME-after-compact.md` (full instructions in the "Layer C blind-compare instructions" section).

---

## 2. yt-grounding Path B hard-delete (date-gated 2026-05-28)

**Layperson:** The old YouTube-parsing code is dormant but still on disk as a
safety net. After 30 days with no problems reported, rip it out.

**Earliest date:** 2026-05-28 (PR #12 merged 2026-04-28 — gated on 30-day soak).

**What to delete:**
- `parse_video_with_gemini` function in `consensus_engine/analysis/gemini_video_parser.py`
- `_GEMINI_PROMPT` constant
- Path B fallback branch in `consensus_engine/scanners/youtube.py:528-539`
  (line numbers may have drifted)
- The `_build_parsed_video` function (Path B-specific)
- `youtube.gemini_enabled` and `youtube.legacy_fallback` config keys (and their consumers)
- Path B grounding hooks in `_build_parsed_video` (Layer 2 Path B integration)

**Acceptance:** PR shipping the deletions is merged; full test suite still
passes; no Path B import errors at engine startup.

**Memory pointer:** also delete
`/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/project_yt_grounding_followups.md`
once this lands.

---

## 3. Speed-accuracy optimization plan — partially unimplemented

**Layperson:** The speed-accuracy optimization plan (`plans/speed-accuracy-optimization.md`,
dated 2026-03-30) was marked complete in a prior session but was not. A prior Claude
session created the infrastructure in one commit (87f4478, 2026-03-31) and stopped,
without verifying the acceptance criteria.

**What was actually done (5 of 13 items):**
- Phase 0: latency instrumentation in cross_reference.py ✅
- Phase 1.3: alert cooldown wired into process_tweet ✅
- Phase 1.4: composite DB index on alert_history(ticker, alerted_at) ✅
- Phase 1.5: news cascade early exit on first hit ✅
- Phase 3.1: persistent L1+L2 xref cache (SQLite-backed) ✅

**What is NOT done:**

- ~~**Phase 1.1 migration**~~ — **DONE** in commit `0a0309e` (25 sites across 24 files
  + 8 test fixes; grep verifies zero bare `aiohttp.ClientSession()` calls outside
  `utils/http.py`).

- ~~**Phase 1.2** — `ThreadPoolExecutor` max_workers~~ — **DONE** in commit `2cc59ee`
  (bumped to 8 at `main.py:1136`).

- **Phase 2.1 (biggest win)** — Parallel news cascade with tiered-timeout. Currently
  sequential `for tier_name in tiers:` loop in `news.py`. Plan calls for running all
  4 tiers concurrently with a 3-second Finnhub priority window. Estimated latency
  improvement: 10–30s → 3–8s. **Note:** parallelizing Brave Search means Brave fires
  on every alert instead of only on Finnhub misses — review Brave budget before
  implementing (see item below).

- **Phase 2.2** — Technical filter short-circuit (`short_circuit` parameter in
  `technical.py`) — not implemented.

- **Phase 2.3** — Batch price followups with concurrent yfinance — not implemented.

- ~~**Phase 3.2 (one-liner bug)** — Rate limiter slot-drift fix~~ — **DONE** in
  commit `2cc59ee` (`rate_limiter.py:58` now uses `now + wait_time`).

- **Phase 3.3** — Shared `get_active_watchlist()` across scanners — not implemented.

- **Phase 4** (nice-to-haves) — Discord retry on 429, social signal dedup,
  configurable cascade strategy, Exa.ai tier — none implemented. Note: Exa.ai
  is no longer used.

**Also discovered — dead config and missing enforcement:**

- `news_cascade.brave_daily_budget: 50` in `config/consensus.yaml` is **dead config**.
  No Python file reads this key. The news cascade path (`scanners/news.py`) has no
  daily cap on Brave at all — only the per-call rate limiter (0.5s between calls).

- The only enforced daily Brave cap is `precision_engine.budget.brave_queries: 200`
  inside `engine.py`'s BudgetManager, which only covers the precision engine code path.

- Actual observed Brave usage: 85–121 queries/day on active trading days (May 6–8).
  Brave free tier allows 2,000/month. Currently well within limit.

**Effort:** Phase 2.1 is the high-value item and requires the most care (Brave budget
implications + HTTP connection cleanup after task cancellation). Phase 1.1 migration
and Phase 3.2 are mechanical/low-risk. Full plan detail at `plans/speed-accuracy-optimization.md`.

---

## 4. Gemini video-eval reference assertions — 2/7 chronic failure

**Layperson:** The daily cron `scripts/run_reference_assertions_cron.sh` is a
regression test that asks Gemini to extract evidence-spans from a fixed
YouTube video (`4mSyMr8PGLI`) and checks ~7 assertions. It's been stuck at
**2/7 passing every day since 2026-04-23** because Gemini's video-ingest
times out (was 120s timeout, bumped to 240s on 2026-05-12). Even with the
bump, the chance of all-7-pass is low without a deeper fix.

**Observed pattern** (from `.omc/logs/v2_assertions_*.log`):
- Steady: both `GEMINI_API_KEY` + `GEMINI_API_KEY2` time out → 2/7 pass
- Best case (Apr 29, May 2): only one key times out → 4/7 pass
- Apr 23 saw explicit 429 RESOURCE_EXHAUSTED

**Root cause** (likely): Gemini free-tier video-ingest latency for a long
trading-recap video; the call is `Part.from_uri(file_uri=YT_URL, mime_type="video/*")`
which re-ingests on Google's backend every time (no Files API caching).

**Fix options (ranked)**:
1. **Files API + caching** (best): upload the reference video once via
   `client.files.upload(...)` and reference the cached `file_uri` for every
   subsequent call. Eliminates re-ingest cost entirely. Cleanest fix.
2. **Paid Gemini API key**: drops the variance entirely; priority queue
   processes consistently in <60s. ~$0.30/day at current budgets.
3. **Already-done**: timeout bump 120→240s (config/consensus.yaml:305). May
   convert some 2/7 days to 4/7 or 7/7, but doesn't help if Gemini is taking
   >240s.
4. **Pin a shorter reference video**: replace `4mSyMr8PGLI` with a 5-10 min
   video that's known to ingest in <120s. Loses regression coverage for long-
   form quote extraction.

**Where to dig**:
- Call site: `consensus_engine/analysis/gemini_video_parser.py:812` (`_extract_evidence_single_pass`)
- Script: `scripts/run_reference_assertions.py` (VIDEO_ID = "4mSyMr8PGLI")
- Daily logs: `.omc/logs/v2_assertions_YYYYMMDD.log`
- Config: `config/consensus.yaml` lines 300-322 (the whole `youtube.gemini:` block)

**Out-of-scope-for-now caveats**:
- Wrapper script exits 0 (cron is happy) but inner-python exits 1 — DoD §7c
  ambiguity. Not a crash; a "signal in the log" per the script's own docstring.
- This pre-dates the 2026-05-12 batch and the prior 2026-05-11 batch — not
  a regression from any recent work.

---


## 5. `inclusionai/ring-2.6-1t:free` model is dead — replace project-wide

**Layperson:** This session discovered that one of the LLMs the bot uses
has been switched to paid-only by OpenRouter. The bot tries it first for
most LLM calls, fails with a 404, then falls back. Need to either
upgrade to the paid endpoint or pick a different free primary.

**Where it's used (grep for `ring-2.6-1t`):**
- `config/consensus.yaml:199` — `llm.model: "inclusionai/ring-2.6-1t:free"` (PRIMARY for general/synthesis)
- `config/consensus.yaml:203` — `llm.text_model: "inclusionai/ring-2.6-1t:free"` (PRIMARY for text tasks)
- `consensus_engine/analysis/video_parser.py:105,107,109` — `_STAGE1_MODEL`, `_STAGE2_MACRO_MODEL`, `_STAGE2_SETUPS_MODEL` hardcoded to `openrouter/minimax/minimax-m2.5:free` already — separate; the **config** primary is what's dead.

**Evidence (probe `/home/openclaw/.openclaw/workspace/.claude/discover/yt-chain-fixes/probe_gemini_flash_captions_output.txt`):**
```
"error": {
  "message": "ring-2.6-1t has transitioned to a paid model...",
  "code": 404
}
```

**Options:**
- (a) Switch primary to `openai/gpt-oss-120b:free` (currently fallback #1; probe-validated for caption extraction).
- (b) Switch primary to `z-ai/glm-4.5-air:free` (currently fallback #2; slower on big payloads but reliable for small).
- (c) Pay for `inclusionai/ring-2.6-1t` (no `:free` suffix). Check OpenRouter pricing first.

**Acceptance:** `python3 -m consensus_engine --status` and any narrator/synthesis call land successfully without falling through to the secondary model. Cron health probe (the existing daily LLM chain check at `consensus_engine.health`) confirms primary green for 7 consecutive days.

---

## 6. Redesign the CLAUDE.md DoD checklist to be scope-aware

**Layperson:** The "Critical paths for this project" list in CLAUDE.md
(lines 17-23) was built up incident-by-incident — every time a prior
session declared something "done" while something else was broken, that
broken thing got added to the list. The result is a "check everything
every time" checklist that's mostly unrelated to whatever I'm currently
working on, and it creates a perverse incentive: when one of those
checks fails for reasons unrelated to my changes, the DoD rules forbid
me to call it "pre-existing", so I'd be forced to fix unrelated bugs
before claiming my own work is done.

**The problem (concrete):** Today's session shipped yt-chain-fixes
work — three new features touching ONLY YouTube ingest code
(local_video_ingest.py, captions_llm_parser.py, gemini_video_parser.py
for logging, plus tests). The current DoD requires me to verify:
  - `!ask` / `!trend` / `!all <ticker>` Discord commands — these route
    through Discord/gateway code that I never touched
  - `@-mention <BOT>` — separate agent path, untouched
  - Cron scripts run as openclaw — separate codebase, untouched
  - `/root/.openclaw` symlink — pure VPS-consolidation residue,
    untouched
None of those share a code surface with the yt-chain work, yet the
checklist would have me probe them anyway. If any happens to be
flaky for unrelated reasons, I'd be on the hook.

**Current items + where each came from (from session memory):**
  - Services active under systemd ← VPS consolidation (May 11)
  - `!ask`/`!trend`/`!all` reply in Discord ← `!trend` momentum fix +
    `!all` v2 + `!ask` time-context fix
  - `@-mention <BOT>` replies ← agentic mention feature batch
  - Cron scripts run as openclaw ← VPS consolidation
  - Boot drift check ← gateway/consensus chain alignment work
  - `/root/.openclaw` symlink resolves ← VPS consolidation

**Proposed redesign — scope-aware tagging:**

Restructure the DoD checklist as a tag→checks map. Each check carries
one or more surface tags. Each feature batch (or even individual
commit) declares which surfaces it touches, and only the matching
tag-bucket of checks runs.

```
# Critical-path checks (scope-aware)

[always]                      # invariants — every batch runs these
  - consensus-engine.service active
  - openclaw-gateway.service active
  - No `❌ GATEWAY drift` Discord alert since restart

[gateway]                     # run if the batch touched gateway / consensus chain config
  - Engine boot logs "boot drift check: gateway chain matches consensus.yaml"

[discord-commands]            # run if the batch touched gateway/commands/alerts paths
  - `!ask`, `!trend`, `!all <ticker>` return coherent replies

[agent-mention]               # run if the batch touched openclaw-agent / mention paths
  - `@-mention <BOT>` returns a coherent reply

[infra]                       # run if the batch touched systemd / paths / VPS layout
  - Cron scripts (check_searxng_health.sh, run_reference_assertions_cron.sh) exit 0
  - /root/.openclaw resolves to /home/openclaw/.openclaw

[ingest]                      # run if the batch touched scanner / video / SEC ingest
  - (no current checks; potential future addition)
```

A feature batch declares its surfaces in the kickoff prompt / discover
state.json, OR an LLM auto-detects surfaces from the diff (e.g. via
file-path matching: `consensus_engine/scanners/youtube*` → ingest;
`consensus_engine/alerts/commands.py` → discord-commands;
`openclaw-gateway/` → gateway/agent-mention; etc.).

**Where this lives:**
- Current list: `/home/openclaw/.openclaw/workspace/CLAUDE.md` lines 17-23
- Related memory entries: `feedback_no_premature_closure.md`,
  `feedback_verify_before_claiming_done.md`,
  `feedback_real_world_testing.md` — each documents the incident that
  added one of the current items
- Past sessions where the issue surfaced: yt-chain-fixes (2026-05-15, this session) — multiple times I had to debate whether to probe Discord commands that had no relationship to my YouTube work

**Acceptance:**
1. CLAUDE.md "Critical paths" section restructured into tag-keyed buckets
   like the example above
2. A clear rule for how a batch declares its surfaces — either explicit
   (e.g. `surfaces: [ingest, infra]` in the EXECUTE.md or commit prefix),
   or implicit (path-pattern auto-detect)
3. The DoD prose ("pre-existing / out-of-scope NOT valid exemptions")
   updated so it applies WITHIN the relevant tag-bucket — i.e. a
   gateway-tagged check failing during an ingest-batch is genuinely
   pre-existing and out of scope, and saying so is fine.
4. A migration check: run the redesigned DoD against this session's
   yt-chain-fixes diff — assert it only requires `[always]` and
   possibly `[ingest]` checks, NOT `[discord-commands]` or
   `[agent-mention]`.

**Out of scope:**
- Tagging every existing memory entry / past commit. Just the
  forward-looking DoD.
- Re-running historical DoD checks against past sessions.

---
