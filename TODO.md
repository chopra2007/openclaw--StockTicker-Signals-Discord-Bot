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

### Execution discipline (non-negotiable for this initiative)

**1. The goal is what matters.** This is an open-ended quality
initiative — there is no "completion ceremony" to chase. The worst
possible outcome is shipping code that fails live testing and then
falling back to *"we can just ditch the code."* That outcome burns
time, tokens, and the user's trust. Before writing any code, name
the user-observable outcome that must hold true after the session
ends ("the embed now shows a max-pain level for every ticker", not
"max-pain integration is in"). If you can't name it crisply, do not
start coding — scope down or pick a different lever.

**2. Pre-flight any feature that needs scraping or external-site
access.** If the proposed feature pulls data from Unusual Whales,
TipRanks, OptionStrat, Finviz, Seeking Alpha, or any other
third-party site, **do a live access test first** — fetch the page
or hit the endpoint manually with Firecrawl / WebFetch / curl and
confirm you can actually extract the field you need from this VPS.
If bot detection blocks you, a proxy returns empty, the data is
paywalled, the markup is too dynamic to parse reliably, or the rate
limits make production use untenable — **stop there and reconsider
the lever before writing any code.** The failure mode this prevents:
building a full end-to-end integration only to discover at live-test
time that the source is inaccessible with no workaround. Capture the
access-test result (worked / blocked / partial) in the external
feature audit alongside the feature row, so the same pre-flight
isn't redone next session.

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

### External research — feature gaps from the web

The "Feature gaps" list above is everything *I* (the codebase author)
already noticed. The high-leverage gaps are the ones nobody's looked
for yet. Before scoping any internal lever, spend material time
auditing what other stock/trading-analysis tools surface that `!all`
doesn't. Sources to mine:

- **Direct competitors** (free + paid tiers): TipRanks, Seeking Alpha,
  Benzinga, Finviz, Stocktwits, TradingView analysis pages, Simply
  Wall St, Koyfin, Stock Analysis dot com, Yahoo Finance, Robinhood
  research pages. What sections does each ticker page have? Which
  are free-tier table stakes vs. paywalled premium?
- **Discord / Telegram trading bots** — Unusual Whales, FlowAlerts,
  AlertaPro, options-flow bots. What does their `/ticker` or `/all`
  equivalent produce? What flow / sentiment / dark-pool data do they
  surface that `!all` doesn't?
- **Sell-side research formats** — bank initiation reports,
  one-pagers, "morning notes". What sections are table stakes
  (catalysts, risks, peer comp, valuation tables, scenario fans)?
- **Retail trader subreddits** (r/wallstreetbets, r/options, r/stocks,
  r/investing, r/SecurityAnalysis) — top-upvoted DD post structure
  conventions. What sections do high-quality DDs always include?
- **Hedge fund letters / public memos** — public quarterly letters.
  What frames do they use for thesis articulation, position sizing,
  catalyst timelines?
- **Twitter/X fintwit accounts** — what data points do top-engagement
  ticker tweets reference (options flow, OI changes, gamma levels,
  short interest deltas, insider clusters)?

**The audit format — a markdown spreadsheet, not prose.** Produce a
table with one row per missing feature and these columns: **Feature**
| **Where I saw it** | **Build cost** (trivial / medium / big) |
**How common** (count across competitor sources) | **Pre-flight
access** (worked / blocked / partial / N/A — fill this in by actually
hitting the source from this VPS per discipline rule 2 above).

Concrete examples of what good rows look like:

| Feature | Where I saw it | Build cost | How common | Pre-flight access |
|---|---|---|---|---|
| "Max pain" options level | Unusual Whales, OptionStrat | Medium — needs options chain data | 4/5 options tools | Blocked (UW Cloudflare) / partial (OptionStrat parseable) |
| "3 insiders bought in last 30d" badge | TipRanks, OpenInsider | Trivial — Form 4 data already fetched | Almost universal | N/A (use existing SEC pipeline) |
| Short-interest delta ("SI up 8% WoW") | Finviz, Stocktwits, Fintel | Medium — needs a SI data provider | Most retail tools | Worked (Finviz HTML stable) |
| Peer-comparison mini-table (P/E, growth vs. AAPL/MSFT) | Seeking Alpha, Koyfin | Big — needs peer ticker logic | Sell-side standard | Blocked (SA paywall) / Worked (Koyfin free tier) |
| "Earnings move history" ("avg ±6% on prints") | Benzinga, Estimize | Trivial — calc from existing OHLCV | ~half of tools | N/A (compute locally) |

The audit's job is to make trade-offs visible at a glance. Sort by
**best ratio of "shows up everywhere" to "cheap to build" AND
pre-flight = worked / N/A** — those rows are the high-leverage gaps
with no surprises waiting. Ship them first. Rows where pre-flight is
"blocked" are *not* candidates until a workaround is documented in
the same audit.

Land the audit at
`.claude/discover/all-command-rebuild/external-feature-audit-<YYYY-MM-DD>.md`
before scoping any concrete code change. Use Firecrawl / WebSearch /
WebFetch heavily — this is a "go deep" research pass, not a
10-minute skim. The audit becomes the shared menu future sessions
draw from.

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

## 8. Discover skill modifications (3 changes)

**Layperson:** Three quality-of-life upgrades to the `discover` skill
(installed at `/root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/SKILL.md`,
source-of-truth at `/root/work/claude-discover-publish/repo/skills/discover/SKILL.md`).
Today discover only composes `superpowers:brainstorming`; the rest is OMC
agents. Verification is enforced by `ralph` + the `verifier` agent looping
on Pass 4's checklist, not by the dedicated superpowers gate skill.

### 8a. Invoke `superpowers:verification-before-completion` in Pass 5

**Why:** Pass 5 already has a checklist + verifier agent, but the
superpowers skill enforces "no completion claim without fresh evidence
in the same message" — a stronger gate than "verifier eventually says
ok." Layering it on top of the existing loop catches premature
"implementation complete" claims from the executor/ralph loop itself.

**Where:** Pass 5 section in `SKILL.md` (currently lines 260–299).
Insert an explicit `Skill` invocation step *before* the commit step
(currently step 4). Also add the skill to the composition table
(currently line 312, "Pass 5" row).

**Acceptance:** Pass 5 documentation now lists
`superpowers:verification-before-completion` in the pass-5 composition
row; the execution flow tells the orchestrator to invoke the skill
before any "ready to commit" claim; a dry-run of Pass 5 against a
trivial fixture shows the skill being invoked.

### 8b. Add a non-tmux parallel-agent option

**Why:** Today discover *requires* tmux (`SKILL.md:26` lists it as a
hard prerequisite) and forces a 3-pane or 6-pane layout
(`SKILL.md:65–107`). On systems without tmux — or when the user just
wants the skill to dispatch parallel agents via Claude Code's native
`Agent` / `Task` tools — the skill bails. Add a third layout option
(call it `--layout native` or `--parallel native`) that uses the
native parallel-agent dispatch from
`superpowers:dispatching-parallel-agents` instead of tmux panes.

**Where:**
- `discover.sh` (bundled with skill) — add a code path that skips the
  `tmux new-session` setup when the native layout is selected.
- `SKILL.md:24` and `SKILL.md:65–107` (layout selection question + the
  tmux multi-agent layout section) — document the new option and stop
  treating tmux as a hard prerequisite.
- `references/tmux-layout.md` — add a "Native (no tmux) layout" sibling
  doc or extend the existing one.
- Pass 0 / Pass 1 dispatch steps that currently say "dispatch into
  pane X" — branch on layout so they instead spawn parallel `Agent`
  tool calls in a single message when native layout is active.

**Acceptance:** Running `/discover` on a system without tmux installed
no longer fails the prerequisite check; the layout question now
offers 3-pane / 6-pane / native; selecting native completes Pass 0 +
Pass 1 by dispatching parallel `Agent` calls instead of tmux panes;
final-plan.md is produced identically (same schema) regardless of
which layout was picked.

### 8c. Kickoff prompt must be one short sentence

**Why:** Today the Pass 4 → Pass 5 handoff generates an `EXECUTE.md`
file and asks the user to **paste its contents** into a fresh session
to start Pass 5. That's exactly the workflow the personal-preference
rule in `/root/.claude/CLAUDE.md` forbids:
> "When generating a kickoff prompt for the user to paste into a
> fresh session, keep it to a single short trigger line; all detailed
> instructions go in a file the new session reads, never inline in
> the prompt."

The kickoff prompt should be one sentence like
`discover: resume EXECUTE.md` (or `discover: resume <run-dir>`) and
nothing else. Pass 5 re-activates from that trigger, then reads
`EXECUTE.md` / `state.json` / `final-plan.md` from disk itself.

**Where:**
- Pass 4 / end-of-pass-4 step that emits the kickoff prompt (search
  `SKILL.md` for "EXECUTE.md" and "kickoff" / "paste").
- Pass 5 entry point (`SKILL.md:260–262`) — already says it "reads
  `state.json` and `final-plan.md`", so the on-disk read path
  already exists; the change is purely on the prompt-generation side.
- Update the discover hard-trigger list in the skill description
  (line 3) if `discover: resume ...` needs to be recognized as a
  trigger variant.

**Acceptance:** Pass 4 output instructs the user to paste exactly one
short line (`discover: resume <abs-path-to-EXECUTE.md>` or similar);
the literal contents of `EXECUTE.md` no longer appear in the kickoff
prompt; pasting that single sentence into a fresh Claude Code session
correctly re-enters Pass 5 and reads the on-disk state.

### 8d. Update plugin README to make tmux optional

**Why:** Once 8b ships a native parallel-agent layout, the
public-facing plugin README at
https://github.com/chopra2007/claude-discover (local clone at
`/root/work/claude-discover-publish/repo/README.md`) is out of date.
Today it positions tmux as a hard dependency:
- Line 3 tagline: "Composes existing OMC and superpowers skills via
  tmux multi-agent orchestration — does not reinvent them."
- Line 90 Prerequisites: `**tmux** — required for parallel multi-agent panes`

After 8b ships, tmux becomes one of two parallelization options and
should be moved from "Prerequisites" to "Optional" (or annotated as
"required only for tmux layouts; native layout uses Claude Code's
built-in parallel `Agent` dispatch").

**Where:**
- `/root/work/claude-discover-publish/repo/README.md` line 3 (tagline)
- `/root/work/claude-discover-publish/repo/README.md` line 87–91
  (Prerequisites section)
- `/root/work/claude-discover-publish/extracted/discover-plugin/README.md`
  (mirror copy, same edits)
- Push the updated README to the GitHub repo
  (`chopra2007/claude-discover`) alongside the 8b release so the docs
  match the code.

**Acceptance:** Plugin README no longer lists tmux as a hard
prerequisite; it documents both layout options (tmux vs native);
GitHub `README.md` on the default branch matches; release notes for
the version that ships 8b call out the new layout option.

### Notes for whoever picks this up

- The cache copy at
  `/root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/SKILL.md`
  will be overwritten on next plugin update — edit the source at
  `/root/work/claude-discover-publish/repo/skills/discover/SKILL.md`
  (and `extracted/discover-plugin/skills/discover/` if that's the
  publish staging path) and bump the version.
- 8d (README update) is gated on 8b shipping — don't announce tmux as
  optional until the native layout actually works.
- The three sub-items are independent — each can ship as its own
  patch. 8c is the smallest / highest-leverage (matches an explicit
  personal preference).
- Verify with a real `/discover` invocation on a small toy feature
  before declaring done — not just by reading the diff.

---

## 9. Replay mentions/commands missed during gateway reconnects

**Layperson:** When the engine restarts (or its Discord WebSocket
drops and reconnects with a fresh `IDENTIFY`), any `!` commands or
`@<bot>` mentions that arrived in the disconnect window are silently
lost — Discord gateway is push-only and does not replay missed
events for a new session. The user sees their message in the
channel, but the bot never reacts.

**Concrete repro:** `sudo systemctl restart consensus-engine.service`
and within ~22s post a mention via the ClaudeCode webhook. The
message lands in #chat, the gateway becomes READY a few seconds
later, but no `Mention →` log line appears for it. Hit during the
2026-05-18 steering-template fix verification — first retest mention
was eaten by the reconnect gap, had to be resent.

**Why it matters:** Any time the engine restarts (deploys, code
pushes, OOM, weekend pause flips), in-flight user requests vanish
without acknowledgement. Hard for the user to tell apart from "the
bot is broken." Also masks real regressions during deploy-verify
loops.

**Proposed approach:**
1. On every Gateway READY (especially fresh `IDENTIFY` after an
   invalid session — see `discord_tweetshift.py` around the existing
   `Reconnecting to Discord Gateway in 120s` log), fetch the last N
   messages from #chat + #commands + #briefing via REST and replay
   any `!`-commands or `@<bot_id>`-mentions whose `id` is newer than
   the highest already-processed message id for that channel.
2. Persist `last_processed_message_id` per channel in the DB
   (`engine_state` table or similar) so the lookback window is
   bounded and crash-safe across restarts.
3. Dedupe by message id so the same mention isn't double-fired if
   the gateway eventually delivers it via push too.
4. Cap the replay window (e.g. 10 minutes / 50 messages per channel)
   so the bot doesn't try to replay a multi-hour outage as a torrent
   of belated replies.

**Acceptance:**
- Restart the engine mid-conversation; the user can send a `!ask` or
  `@<bot>` during the ~20s reconnect; the bot replies within ~30s of
  gateway-ready instead of going silent.
- Restarting after an hour-long outage doesn't flood the channel —
  only messages inside the configured replay window get processed.

**Discovered:** 2026-05-18 during the steering-template fix
verification; see commit 6bc150e on master.

---

## 10. `levels.select_trade_plan` silently returns no SL/TP for some tickers

**Layperson:** When the anchor pipeline can't find usable supports/
resistances, `!all <TICKER>` renders SL / TP1 / TP2 / TP3 as literal
"—" in the Discord embed but the rest of the trade plan still ships as
if it were complete. The user gets a "Bullish" call with no exit price
and no targets — actively misleading.

**Concrete repro (2026-05-18 blind compare):**
- AMD: bot returned BULLISH at $420.99 with SL $130 (from a stale
  double-bottom anchor at $203.79 — implies a -69% drawdown
  invalidation, which is not a swing-trade stop), TP1/TP2/TP3 all "—".
- TSLA: bot returned BULLISH at $409.99 with SL "—", TP1/TP2/TP3 "—".
  Body text literally said "No specific stop-loss or target levels are
  supplied, so the trade should be approached with caution."

**Root cause hypothesis:** `levels.cluster_anchors` + `rank_anchors`
filter out everything when anchor density is low or the only
candidates land too far from spot (the `_distance_penalty` weight
prunes them). `select_trade_plan` at `levels.py:430` then returns
partial structure rather than failing loudly.

**Proposed fix levers:**
1. **Completeness gate in `aggregator.py`** — if `select_trade_plan`
   returns ≤2 of {SL, TP1, TP2, TP3}, escalate to a swing-band fallback
   computed from ATR(14): SL = spot − 2×ATR (for long) / spot + 2×ATR
   (for short), TPs at spot ± 1×, ± 2×, ± 3× ATR. Flag the embed with
   a "fallback levels (low anchor confluence)" footer.
2. **Anchor-floor in `levels.select_trade_plan`** — if fewer than N
   ranked anchors land within ±15% of spot, widen the distance window
   before pruning. Today's `_distance_penalty` is opaque — make it
   tunable.
3. **Refuse-to-render** — if no usable SL is found, `aggregator.handle_all`
   posts a structured "insufficient anchor data for $TICKER — no trade
   plan generated" reply instead of an embed with "—" placeholders.

**Acceptance:**
- `!all AMD` and `!all TSLA` produce a complete trade plan (SL + at
  least TP1 + TP2 non-"—") OR explicitly decline to render.
- New unit test: structured fixture with zero clusterable anchors →
  assert chosen fallback path (per whichever lever above is picked).
- New live test (must run in real environment, not just unit):
  `!all` on a low-liquidity ticker known to fail anchor density → no
  "—" placeholders in the rendered embed.

**Discovered:** 2026-05-18 Layer C blind compare (TODO #1) — bot lost
0/3 against Gemini, primary cause for AMD + TSLA losses.

---

## 11. Narrator leans on "YouTube analysts are calling long" — appeal-to-influencer prose

**Layperson:** When evidence is thin, the narrator's prose falls
back to citing analyst names as proof. The Bear Case still has
`[evidence:N]` markers (M2 acceptance criterion is met structurally)
but the *content* those markers point to is shallow ("noted by several
YouTube channels", "Multiple high-conviction YouTube analysts (Wicked
Stocks, Lottery Stocks, CheddarFlow, The Real Shadow Trader) are
calling long, citing recent earnings beats and market sentiment").

This is structurally a quality_bar pass but substantively a regression
vs Gemini, which never falls back to influencer names — it builds
causal theses ("Blackwell volume shipments + hyperscaler commitments
not captured in conservative Q1 metrics → revenue beat to $83B vs
$79.2B consensus") even when its inputs are weaker than the bot's.

**Concrete repro (2026-05-18 NVDA capture):**
> "Multiple high‑conviction YouTube analysts (Wicked Stocks, Lottery
> Stocks, CheddarFlow, The Real Shadow Trader) are calling long, citing
> recent earnings beats and market sentiment."

This bullet is in the Catalysts section. It would not survive a
substance review — "analysts are calling long" is provenance, not
catalyst.

**Proposed fix levers:**
1. **`quality_bar.py` content gate** — add a heuristic that counts
   "appeal-to-influencer" patterns in the narrative ("analysts are
   calling", named influencer handles, "high‑conviction X are bullish")
   and triggers a one-shot reprompt with a hardened CONSTRAINTS clause:
   *"Do not cite analyst names or YouTube channel handles as evidence.
   Every catalyst bullet must reference a specific number, date, or
   named event — not a person's opinion."*
2. **`narrator._build_constraints_block`** — add the no-influencer
   clause directly to the prompt rather than relying on retry. Spec
   exact failure modes ("rejected if any catalyst bullet contains
   the substring 'analysts' or 'channels' without a paired numeric
   or date reference").
3. **`narrator._build_synthesis_prompt` — evidence-block reshaping**
   — currently `yt_signals` and `yt_evidence` blocks get serialized
   with the analyst name as a top-level field. Demote analyst names
   to a `provenance` sub-field so the LLM has less surface to reach
   for when phrasing.

**Acceptance:**
- New unit test in `tests/all_command/test_narrator_pack.py`:
  narrative containing "Multiple high-conviction YouTube analysts (X,
  Y, Z) are calling long" → `quality_bar` rejects, retry is forced.
- After fix: rerun the 3-ticker capture from TODO #1 and verify the
  rendered Catalysts section contains zero analyst-name bullets.

**Discovered:** 2026-05-18 Layer C blind compare (TODO #1) — bot's
NVDA Catalysts bullet 3 was the clearest "loses on substance" signal.

---

## 12. Horizon-anchor mismatch: NVDA SL $178 (20-day support) framed as 2-day catalyst trade

**Layperson:** NVDA returned a bullish call with SL at $178 (a 20-day
support level, implying a -21% drawdown invalidation) but the narrative
framed it as a swing trade against the May 20 earnings print 2 sessions
away. Those two framings can't both be right. A position-trade stop
$178 doesn't pair with a 1–3 session earnings-catalyst horizon.

**What's actually happening:** `levels.select_trade_plan` chose $178
because that's where the cleanest support anchor confluence sat.
`structured_fields.compute_swing_horizon` derived "1-1 days" from
|TP1−spot|/(0.7×ATR) capped at the next catalyst (earnings T-2). The
narrator was handed two horizon signals — short-term-tactical via the
horizon field, position-defensive via the SL — and never reconciled
them. It wrote a swing thesis and accepted the position-trade SL
without flagging.

**Concrete repro (2026-05-18 NVDA capture, nvda-bot.txt:32):**
```
| Horizon | 1–1 days | Derived from |TP1‑spot|/0.7×ATR, capped at the next catalyst. |
| Next Catalyst | 2 days | Earnings on 2026‑05‑20 is the binary catalyst that bounds the horizon. |
```
combined with `| Stop‑Loss | $178.00 | Protects against a significant
downside move beyond the 20‑day support level. |` and a TL;DR saying
"earnings on 2026‑05‑20 is the key catalyst." — the SL is *not*
calibrated to a 2-session earnings window; it's calibrated to a 20-day
horizon.

**Proposed fix levers:**
1. **`levels.select_trade_plan` should pick horizon-aware anchors.**
   When `compute_swing_horizon` returns ≤3 days, weight anchors within
   ±1.5×ATR over anchors that imply >5% drawdown. Today's
   `_distance_penalty` is symmetric across all horizons.
2. **Add a horizon-anchor sanity check in `aggregator.py`** — if SL
   implies more than (horizon_days × ATR%) drawdown, log a
   `horizon_mismatch` warning to the quality_bar telemetry line so
   the regression is observable in live runs.
3. **`narrator._build_constraints_block`** — add a clause requiring
   the narrative to explicitly reconcile horizon vs SL if the ratio
   exceeds some threshold ("If SL implies a drawdown larger than
   1×horizon×ATR, narrative must justify why the position is sized
   for a longer-horizon stop").

**Acceptance:**
- New unit test in `tests/all_command/test_levels.py`: short-horizon
  fixture (catalyst in 2 days, ATR 8) → assert SL chosen within
  ±2×ATR of spot, not at a 20-day support 21% away.
- New quality_bar field: `horizon_anchor_ratio = SL_drawdown_pct /
  (horizon_days × atr_pct)`. Log to quality_bar line. Acceptance:
  ratio > 3.0 triggers a `horizon_mismatch=true` flag in the log.
- After fix: rerun NVDA capture from TODO #1; SL field rationale
  must mention either "calibrated to the X-day earnings window" or
  the embed must show a position-trade horizon (≥2 weeks), not
  "1–1 days".

**Discovered:** 2026-05-18 Layer C blind compare (TODO #1) — NVDA
loss was driven primarily by an unrealistic SL relative to the framed
horizon (Gemini chose SL $209 for the same 2-day-catalyst trade).

---

## 13. `!all` has no forward-dated catalyst ingest beyond earnings

**Layperson:** The Catalysts section of every `!all` embed lists at
most the next earnings date and a backward-looking earnings recap
("Revenue $68.13B, +73.2% YoY from the latest quarter"). Gemini's
side-by-side outputs for the same 3 tickers consistently produced
2 dated *forward* catalysts with mechanism ("May 28: first 1-gigawatt
allocation phase of MI450 commitments by Meta"; "June 09: HBM4 memory
allocation verification with Samsung"). The bot has no pipeline that
ingests forward-dated events beyond `earnings_calendar`.

**What's missing:**
- Analyst day / investor day announcements
- Product launch dates / keynote dates
- FDA PDUFA dates (for biotech tickers)
- Options-expiry dates with unusual flow concentration
- Ex-div dates
- Pre-announced supply chain / partnership milestones (e.g. the Meta
  6GW phase-1 close that Gemini referenced for AMD)
- SEC filing windows (10-K / 10-Q due dates)
- Index inclusion / reconstitution dates

**Current state in code:** `structured_fields.compute_next_catalyst_days`
(at `structured_fields.py:~280`) only reads `earnings_calendar`. The
aggregator fetches `news_catalyst` but it's a backward-looking field
(mentions the last big news item, not future scheduled events).

**Proposed fix levers:**
1. **New scanner: `consensus_engine/scanners/forward_calendar.py`** —
   pulls upcoming dated events from public sources (the same sources
   Gemini likely synthesizes from): SEC EDGAR upcoming-filing dates,
   press-release wires, analyst-day announcements indexed from
   investor-relations pages. Per TODO #7's external-research
   discipline rule, *pre-flight access from this VPS first* before
   building anything — confirm each source is reachable + parseable
   from production.
2. **Extend `compute_next_catalyst_days`** to merge multiple calendar
   feeds and return the closest event with a `kind` label
   ("earnings" / "product_launch" / "analyst_day" / "fda_pdufa" /
   etc.) so the narrator can name the catalyst type.
3. **CONSTRAINTS update** — require AT LEAST 2 dated forward
   catalysts in the Catalysts section, fall back to 1 only when
   genuinely thin. Currently no minimum on forward dates.

**Acceptance:**
- New scanner ships with pre-flight access notes (worked / blocked /
  partial) per TODO #7 rule 2.
- `!all AMD` rerun produces ≥2 dated forward catalysts in the
  Catalysts section, with specific dates and named mechanisms.
- Blind-compare gate (TODO #1) advances from 0/3 prefer-bot to
  ≥1/3 prefer-bot or tie on the same 3 tickers (NVDA / AMD / TSLA).

**Discovered:** 2026-05-18 Layer C blind compare (TODO #1) — primary
substance lever for closing the bot-vs-Gemini gap. Belongs under the
TODO #7 umbrella but tracked here as its own top-level row because the
implementation surface is a brand-new scanner, not a tweak to existing
narrator/levels code.
