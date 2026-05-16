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


## 5. `sync_gateway_models.py` strips file ownership when run as root

**Layperson:** A helper script that syncs the LLM model chain to the
gateway config breaks the gateway if you run it with sudo. The file ends
up owned by root instead of openclaw, and the gateway (which runs as
openclaw) can't read it and crashes with a misleading "missing
gateway.mode" error.

**Reproduced 2026-05-15** during the TODO #5 fix (5-model chain rollout).
Ran `python3 scripts/sync_gateway_models.py` — script implicitly required
elevated perms — `/home/openclaw/.openclaw/openclaw.json` flipped from
`openclaw:openclaw` to `root:root`. Gateway exit code 78/CONFIG. Manual
`chown openclaw:openclaw` + restart restored service.

**Where:** `scripts/sync_gateway_models.py` — `_write_gateway_chain`
shells out to `openclaw config patch`, which inherits the caller's UID
and apparently rewrites the file fresh rather than in-place.

**Workaround in use:** run as `sudo -u openclaw python3 scripts/sync_gateway_models.py`
instead of bare sudo. Verified ownership-preserving in the same session.

**Fix options:**
- (a) `os.chown(GATEWAY_JSON, openclaw_uid, openclaw_gid)` after `_write_gateway_chain` if the file is now root-owned.
- (b) Refuse to run if `os.geteuid() == 0` and `os.environ.get('SUDO_USER') != 'openclaw'`; print the `sudo -u openclaw` invocation.
- (c) Update the script's docstring (currently says `sudo python3 ...`) to say `sudo -u openclaw python3 ...`.

**Acceptance:** Running the script the way the docstring instructs leaves
`/home/openclaw/.openclaw/openclaw.json` owned by `openclaw:openclaw`; gateway
restarts cleanly with no manual chown step.

**Bonus also worth fixing in the same PR:** the gateway's "missing
gateway.mode" error is misleading when the real cause is EACCES — the
read-failed banner appears first, then the schema check runs against an
empty config. Either propagate the read error to the exit message, or
skip the schema check when the file is unreadable.

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

## 7. Optimize `!all` output quality + feature surface (open-ended initiative)

**Layperson:** The user wants to improve what `!all <TICKER>` produces.
This is intentionally broad — the framing matters because most of the
visible output isn't decided by the LLM. Before any session picks
this up, read the architecture map below so you don't waste effort
"fixing" things in the wrong place.

### Architecture — who actually decides what

`consensus_engine/alerts/all_command/` is the package. Order of
operations on a single `!all` invocation:

1. **`aggregator.py`** (802 lines) — the conductor.
   - Validates ticker format via `is_valid_ticker` only — **no
     market-cap gate** (main alerting engine has one; `!all` skips).
   - Fans out data fetches: Finnhub `/quote` (current price),
     yfinance OHLCV (technicals), Finnhub news, Brave + SearXNG
     (broader web), Reddit/social, YouTube indexed analyst calls,
     SEC EDGAR filings, TweetShift Twitter signals, internal #chat
     + #brief Discord history, prior vault excerpts.
   - Calls technical-indicator computation (RSI, EMAs, ATR, volume).
   - Calls `structured_fields.compute_*` and `levels.select_trade_plan`.
   - Packs everything into a `StructuredFields` dataclass at line 595.
   - Hands the clipboard to `narrator.synthesize_narrative`.

2. **`structured_fields.py`** (321 lines, 9 compute_ functions):
   - `compute_direction`, `compute_confidence_label`
   - `compute_buy_zone` (line 141), `compute_breakout_timeframe`
   - `compute_magnitude`, `compute_magnitude_band`
   - `compute_swing_horizon` (line 209), `compute_next_catalyst_days`
   - All pure arithmetic on the data the aggregator already fetched.

3. **`levels.py`** (469 lines) — TP1/TP2/TP3 + stop-loss anchor logic:
   - `extract_anchors_from_youtube_levels` (line 165),
     `extract_swing_levels` (214, from candles),
     `extract_anchors_from_search_snippets` (258, from news).
   - `cluster_anchors` (310), `rank_anchors` (375) — confluence +
     freshness + source-tier scoring.
   - `select_trade_plan` (430) — picks the final SL + 3 TPs.

4. **`narrator.py`** — synthesis prompt builder + LLM call:
   - System instruction (line 238): "COMPUTED SIGNAL is authoritative
     — never contradict its direction, confidence label, or price
     levels. Do NOT invent prices or levels."
   - `_build_synthesis_prompt` (~line 320) packs the COMPUTED SIGNAL +
     18 evidence blocks (news, sec, twitter, social, yt_signals,
     yt_options, yt_evidence, technical, earnings_recap, chart_pattern,
     etc.) with per-section caps to stay under 15k input tokens.
   - LLM call at `_invoke_synthesis` (~line 423):
     `call_with_fallback(role="primary", max_tokens=8000, temperature=0.35)`.
   - The 5-model chain (re-selected 2026-05-16, see `.omc/research/llm-chain-2026-05-16/`) runs here.

5. **`output_filter.py`** — contradict-detection retry:
   - `detect_contradiction(narrative, structured)` (line 61) scans the
     LLM output for new/contradicting price levels.
   - `sanitize_or_retry` (line 86) — on contradiction, re-prompts the
     LLM with a hardened instruction. Returns `("", "fallback_data_only")`
     if retry also fails; engine then renders the deterministic embed.

6. **`embed.py`** — Discord embed renderer (color + footer + fields).
7. **`vault_writer.py`** — writes `<vault>/tickers/<TICKER>-all.md`.
8. **`cache.py`** — single-flight + 15-min TTL on `xref_cache` table
   keyed by `all_v<8-char-version-hash>:TICKER`.

### Output-quality levers (by where the work lives)

The 2026-05-16 isolation test showed all 5 chain models produce the
same trade plan numbers — the only visible LLM-side variation is prose,
catalyst selection, formatting, source-attribution style. So:

**LLM-side changes don't move the trade plan.** To improve the
actionable numbers, work in `structured_fields.py` + `levels.py`.

**Engine-side (deterministic) levers:**
- `levels.select_trade_plan` — current weighting blends YouTube
  analyst calls + swing levels from candles + news mentions. Tune
  `_freshness_bonus`, `_distance_penalty`, `_confluence_bonus` for
  better target placement. Currently TP2/TP3 get "padded" when fewer
  than 3 anchors land — gpt-oss-120b annotates this self-aware-ly;
  others stay silent. Could add anchor-count to COMPUTED SIGNAL so
  every narrative can comment on it.
- `structured_fields.compute_buy_zone` — uses current price ± a band.
  Could incorporate VWAP, EMA20 support, or recent swing-low proximity.
- `structured_fields.compute_swing_horizon` — derived from
  `|TP1−spot|/(0.7×ATR)` capped at next catalyst. Could weight by
  recent realized volatility instead of headline ATR.
- `structured_fields.compute_next_catalyst_days` — currently
  earnings-only. Could include options expiry, ex-div, FDA dates,
  pre-announced events from `news_catalyst`.
- Add a `compute_pattern_strength` for chart patterns beyond the
  current `chart_pattern` block — engine already detects double-
  bottom etc., could score breakout-readiness.

**LLM-side (prose) levers** (everything below leaves the trade plan
unchanged):
- `narrator._build_synthesis_prompt` — the CONSTRAINTS block tells
  the model exactly what sections to write. Tightening the wording
  (e.g. "every catalyst must cite an evidence row by index", "rationale
  column must be ≤ 25 words") removes the per-model wording drift the
  2026-05-16 test surfaced.
- `narrator._build_synthesis_prompt` — evidence blocks are sent via
  `json.dumps(... default=str)`. The EARNINGS RECAP block already gets
  pre-formatted via `_format_earnings_recap` (added 2026-05-16, commit
  732a475). Other blocks (news, sec, twitter, social, yt_*) still pass
  raw — could apply the same pre-formatting pattern for date strings,
  large dollar amounts, etc. to remove formatting variance between
  chain models.
- `narrator._build_constraints_block` — currently asks for "AT LEAST 2
  catalysts". Could raise to AT LEAST 3 when ≥3 distinct source-types
  surfaced, fall back to 2 only when evidence is thin.
- `quality_bar.py` — already enforces minimum standards. Worth reviewing
  what it catches vs. what it lets through.

**Feature gaps** (things `!all` doesn't currently do):
- No market-cap floor — `!all FAKEX` succeeds-empty instead of replying
  "ticker not found on exchange." Fix: call `validate_ticker_market_cap`
  in `aggregator.handle_all` before the data fetch.
- No "data sparseness" warning — when ≤2 sources surface, the embed
  still renders confidently. Could add a "low-confidence: only N sources"
  banner.
- No options-flow integration in the trade plan — engine fetches
  options data (used in scoring) but the TPs don't incorporate
  max-pain or large-strike concentration.
- No competitor-context — for big tickers like AMZN, the narrative
  doesn't relate to AAPL/MSFT/GOOGL moves. Could pull a "sector
  context" mini-block.
- No earnings-week-aware horizon — if earnings is in 3 days, current
  horizon often spans the print; could clip horizon to T-1.
- Cache is binary (hit/miss). On miss the user waits 60-180s with no
  intermediate progress. Could push a 2-stage embed: structured fields
  in 5s, narrative when ready.
- Chart-pattern detection runs but only feeds the LLM. Could add
  pattern_strength to the visible embed.

### Existing prior art

- **memory: `project_all_command_v2_planning.md`** — there's already
  a v2-quality-rebuild planning effort in
  `.claude/discover/all-command-rebuild/v2-quality-rebuild/`. Start
  by reading that before scoping new work — may already capture some
  of the items above.
- **TODO #1** — Layer C blind-compare with Gemini is the human eval
  loop for any quality changes; should be re-run after any
  user-visible improvement.
- **TODO #3** — Speed-accuracy optimization (8 of 13 items unimplemented)
  overlaps with output latency improvements above.
- Float-precision fix (commit 732a475, 2026-05-16) was an early win
  in this initiative — see `_format_earnings_recap` in `narrator.py`
  for the pattern applied.

### How to scope a session

This TODO is intentionally broad — don't try to do it all in one
session. Recommended first move: read the v2-quality-rebuild artifacts,
then pick ONE lever from the lists above + write a focused spec for
just that change (e.g. "tighten Trade Plan rationale to ≤25 words and
re-test all 5 chain models for compliance"). Use the test methodology
from `.omc/research/llm-chain-2026-05-16/probe_llm_chain.py` as the
quality-regression harness.

**Acceptance for this TODO is "shipped at least one user-visible
quality improvement with before/after evidence."** Not "completed all
items above" — those are a menu, not a checklist.

---
