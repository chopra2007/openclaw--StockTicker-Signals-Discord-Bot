# To Do List

Items here are suggestions/ideas to tackle in a future session.
Each entry has enough context to generate a prompt/plan from scratch.
Delete an entry when it's completed.

---

<!-- Add items below -->

## 1. Calibration "commit F" — relabel the lying "Calibrated conf" field

**Layperson:** The bot shows a raw 0–100 score but labels it "Calibrated conf"
even though no calibration model is trained. Two test cases at
`tests/test_calibration_shadow.py` are intentionally RED with a note saying
"RED until Commit F relabels the lying 'Calibrated conf' field."

**Where it is:** Find the Discord field renderer that produces the string
`"P(up 1h): X% | P(down): Y% Calibrated conf: Z%"`. When `shadow_mode=True`
and no calibration model is loaded, the field text needs to be
`"score/100 (uncalibrated)"` (or similar — the test asserts that exact
substring is present). The two RED tests:
  - `tests/test_calibration_shadow.py::test_calibrate_returns_identity_at_score_30_when_no_model`
  - `tests/test_calibration_shadow.py::test_calibrated_section_returns_uncalibrated_label_when_shadow_mode_and_no_model`

**Acceptance:** both tests turn green; full suite still passes.

**Effort:** 30 min. Pure label change + test pass.

---

## 2. Layer C blind-compare with Gemini (operator-driven)

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

## 3. yt-grounding Path B hard-delete (date-gated 2026-05-28)

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

## 4. Speed-accuracy optimization plan — partially unimplemented

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

- **Phase 1.1 migration** — `utils/http.py` singleton exists but ~35 files still
  use bare `aiohttp.ClientSession()` directly, including `news.py`, `discord.py`,
  `social.py`, `technical.py`, `sec_edgar.py`, `video_parser.py`, etc. The plan's
  acceptance criteria ("zero `aiohttp.ClientSession()` calls outside utils/http.py")
  is not met.

- **Phase 1.2** — `ThreadPoolExecutor` still `max_workers=4` at `main.py:1116`.
  One-liner change to 8.

- **Phase 2.1 (biggest win)** — Parallel news cascade with tiered-timeout. Currently
  sequential `for tier_name in tiers:` loop in `news.py`. Plan calls for running all
  4 tiers concurrently with a 3-second Finnhub priority window. Estimated latency
  improvement: 10–30s → 3–8s. **Note:** parallelizing Brave Search means Brave fires
  on every alert instead of only on Finnhub misses — review Brave budget before
  implementing (see item below).

- **Phase 2.2** — Technical filter short-circuit (`short_circuit` parameter in
  `technical.py`) — not implemented.

- **Phase 2.3** — Batch price followups with concurrent yfinance — not implemented.

- **Phase 3.2 (one-liner bug)** — Rate limiter slot-drift fix. `rate_limiter.py:56`
  uses `time.time() + wait_time` instead of the captured `now + wait_time`, causing
  slot drift under concurrency. One-line fix.

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
