# Adversarial Review

## Overall Risk Posture

Risk is **high**. The codebase contains several plan-critical paths that are either silently disabled, semantically inconsistent with the plans, or implemented in a way that will fail on common real inputs. The biggest issue is not just missing features; it is **false confidence**: roadmap items are marked shipped or framed as imminent while key runtime dependencies are absent, important semantics are mismatched, and tests do not exercise the real failure paths.

I also ran a targeted test slice:

- `pytest -q tests/test_cross_reference.py tests/test_youtube_scanner.py tests/test_commands.py tests/test_engine.py tests/test_db_youtube.py`
- Result: `69 passed`, but with `2 RuntimeWarning` warnings from mocked async HTTP usage in `tests/test_engine.py`

That passing slice does **not** clear the roadmap. It mainly shows the tests are not covering the most dangerous production paths.

## Ranked Findings

### 1. Reliability engine is called in production code but the modules do not exist

**Why it matters**

This makes the “reliability-first” and decision-snapshot path effectively non-existent at runtime. Worse, it fails silently because `cross_reference()` swallows the import/runtime error. Anything depending on contradiction index, abstain paths, or reliable decision snapshots is not real today.

**Evidence**

- `consensus_engine/cross_reference.py:325-370` imports `consensus_engine.analysis.reliability_engine` and `consensus_engine.analysis.snapshot_builder`, then suppresses all exceptions.
- Repo search shows references to those modules, but no such files exist.
- `plans/ROADMAP.md:81-90` describes the reliability engine as Week 4 work, but the current code already tries to invoke it.

**Concrete fix / mitigation**

- Stop silently pretending this path exists. Either:
- Implement `reliability_engine.py` and `snapshot_builder.py` immediately, with tests.
- Or remove the runtime call and gate the feature behind an explicit config flag with clear logging at `WARNING` level.
- Add a startup integrity check that fails fast if roadmap-critical modules are configured as enabled but missing.

### 2. `video_parser.py` is internally inconsistent and will break on the prompt’s own expected macro output

**Why it matters**

A normal LLM response matching the prompt can crash parse-to-model conversion. This is a direct production failure in the main YouTube analysis path.

**Evidence**

- Prompt expects macro direction values `bullish|bearish|neutral` in `consensus_engine/analysis/video_parser.py:53-59`.
- `Direction` enum only allows `long|short|neutral` in `consensus_engine/models.py:180-183`.
- Parsed macro direction is passed directly into `Direction(...)` in `consensus_engine/analysis/video_parser.py:538-544`.
- Chunk merge also votes on `long|short|neutral` in `consensus_engine/analysis/video_parser.py:421-443`, while the prompt asks for `bullish|bearish|neutral`.

**Concrete fix / mitigation**

- Normalize macro direction explicitly before model construction:
- Map `bullish -> long`, `bearish -> short`, `neutral -> neutral`, or introduce a separate macro enum.
- Add unit tests for:
- prompt-compliant LLM JSON
- mixed chunk outputs
- invalid macro values

### 3. The roadmap and answered open questions are not reconciled with the actual codebase

**Why it matters**

Execution will drift because the “source of truth” documents disagree with each other and with the code. This is how teams build the wrong thing confidently.

**Evidence**

- `plans/OPEN_QUESTIONS.md:27` says the precision engine should **replace** `cross_reference.py`.
- `plans/ROADMAP.md:115-123` still says the precision engine is an “independent track” and asks the same open question again.
- `consensus_engine/main.py:541-545` runs `cross_reference()` and `analyze_signal()` in parallel; precision is supplemental, not the decision-maker.
- `plans/OPEN_QUESTIONS.md:41` says all approved YouTube channels start at **100% trust** via manual curation.
- `plans/ROADMAP.md:31` still references a default `0.5` credibility gate.

**Concrete fix / mitigation**

- Update `plans/ROADMAP.md` immediately to match `OPEN_QUESTIONS.md`.
- Add a short “Current truth” section stating which engine actually decides alerts today.
- Remove answered questions from the roadmap once they are resolved.

### 4. Precision engine is not the decision-maker despite the resolved plan saying it should replace cross-reference

**Why it matters**

This is the most important plan/code mismatch. If AK expects precision-first routing, the current system will still publish follow-ups based on the old cross-reference path and only attach precision as side information.

**Evidence**

- `plans/OPEN_QUESTIONS.md:22-28` resolves this: precision engine replaces `cross_reference.py`.
- `consensus_engine/main.py:541-545` launches both engines in parallel.
- `consensus_engine/main.py:564-574` updates follow-up and alert breakdown from `xref`, not from precision classification.
- `consensus_engine/alerts/discord.py` formatting references `STRONG_ALERT/WATCHLIST/IGNORE`, but the main decision flow still centers on cross-reference results.

**Concrete fix / mitigation**

- Choose one decision-maker.
- If precision is the replacement, route alert suppression, follow-up generation, and persistence through precision outputs first.
- Keep cross-reference only as an explanation/enrichment layer if still useful.

### 5. Budget management is not concurrency-safe and can overspend under load

**Why it matters**

This is an efficiency and cost-control failure. Concurrent alerts can race through `can_consume()` and `consume()` and exceed daily API budgets.

**Evidence**

- `consensus_engine/engine.py:72-98` and `100-116` do read-then-update budget checks with no transaction or lock.
- `consensus_engine/main.py:541-544` spawns `analyze_signal()` concurrently per alert.
- The code also does `can_consume()` followed by `consume()` as separate operations for Exa/SerpApi/Firecrawl in `consensus_engine/engine.py:303-330`.

**Concrete fix / mitigation**

- Make budget consumption atomic with one SQL `UPDATE ... WHERE current + amount <= limit`.
- Or guard budget operations with an async process-local lock plus transactional SQL.
- Emit explicit “budget denied” metrics so budget exhaustion is observable.

### 6. The YouTube command surface in the plans does not exist, and one existing command is semantically misleading

**Why it matters**

The roadmap presents a near-term operational interface that is not actually implemented. This will block validation, operator workflows, and user trust.

**Evidence**

- `plans/ROADMAP.md:36-46` expects `!yt`, `!yt-mentions`, `!macro`, and macro persistence.
- `consensus_engine/alerts/commands.py:82-197` only routes `!transcript`, `!market-view`, and `!levels` from the YouTube/reliability side.
- There is no `!yt`, `!yt-mentions`, `!macro`, or `!channel-score` route.
- `plans/ROADMAP.md:62-65` describes `!market-view` as a composite market direction score.
- Actual `!market-view` is ticker-specific and just reads the latest decision snapshot, then derives `P(up 1h)` from calibration in `consensus_engine/alerts/commands.py:797-842`.

**Concrete fix / mitigation**

- Rename the current command if needed, e.g. `!snapshot-view`.
- Do not describe `!market-view` as shipped until it is actually market-wide.
- Implement only one on-demand YouTube command first: `!yt <URL>`, then add the rest after the persistence model exists.

### 7. Channel credibility and curation cannot work correctly because the pipeline stores channel IDs where plans expect human channel identity

**Why it matters**

Manual curation, trust gating, and user-facing display are all weakened if the system treats `UC...` IDs as channel names. It also makes the answered cold-start policy hard to operationalize.

**Evidence**

- `consensus_engine/scanners/youtube.py:244-249` passes `channel_name=channel_id` into `parse_video_transcript()`.
- `consensus_engine/scanners/youtube.py:265-289` persists `channel_name=channel_id` into `youtube_signals` and `youtube_levels`.
- `plans/OPEN_QUESTIONS.md:41` says only pre-approved YouTube channels are added and all start at 100% trust.
- `plans/ROADMAP.md:67-70` expects a future `youtube_channels` credibility tracker, but there is no such table today.

**Concrete fix / mitigation**

- Add a canonical channel registry keyed by `channel_id` with display name, approval status, trust seed, and metadata.
- Do not use raw channel IDs as “channel_name”.
- Implement the planned metadata fetch path before building any credibility gate.

### 8. Test coverage is giving false assurance on the YouTube path

**Why it matters**

The tests pass, but they are not proving the production path is sound. This is dangerous because roadmap confidence is being inferred from green tests.

**Evidence**

- `tests/test_youtube_scanner.py:115-131` patches `consensus_engine.scanners.youtube.fetch_transcript`.
- Real code does not call that symbol; it imports and calls `fetch_transcript_cascade` inside `process_video()` at `consensus_engine/scanners/youtube.py:195-199`.
- There are no tests for `consensus_engine/analysis/video_parser.py` at all.
- The targeted test run passed despite this mismatch.

**Concrete fix / mitigation**

- Rewrite scanner tests to patch `consensus_engine.utils.transcript_fetch.fetch_transcript_cascade`.
- Add direct tests for:
- prompt-compliant LLM JSON
- macro direction normalization
- chunk merge behavior
- empty/invalid model output
- transcript length gate

### 9. Known hygiene gaps remain unresolved and are still reachable in runtime paths

**Why it matters**

These are not cosmetic. They increase noise, leak operational clarity, and will make debugging harder once traffic increases.

**Evidence**

- `plans/ROADMAP.md:48-50` explicitly lists unresolved hygiene items.
- `consensus_engine/utils/http.py:1-45` provides `close_session()`, but repo search shows no call site.
- `consensus_engine/analysis/video_parser.py:122-160` does not inspect `finish_reason` from OpenRouter at all.
- Targeted test run produced async warning noise in `tests/test_engine.py`, which is another sign of loose HTTP/test hygiene.

**Concrete fix / mitigation**

- Call `close_session()` during daemon shutdown.
- Handle truncated LLM responses explicitly and retry or fail closed.
- Treat warnings as review items, not background noise.

## Plan / Code Mismatches

- `OPEN_QUESTIONS.md` says precision replaces cross-reference; code still runs both and treats precision as advisory.
- `ROADMAP.md` still contains answered questions and stale defaults.
- `ROADMAP.md` says `!market-view` is Week 3 market-direction work; code already has a different ticker-snapshot command with that name.
- `ROADMAP.md` says reliability engine is future work; code already tries to call it, but the modules are missing.
- `ROADMAP.md` says macro persistence is pending; code stores macro JSON inside `youtube_signals`, but there is still no `youtube_macro` table or digest path.

## OPEN_QUESTIONS.md Status

There are **no formally unanswered items** in `plans/OPEN_QUESTIONS.md`; all six questions have answers.

What remains unresolved is the **integration of those answers**:

- Precision replacement is not reflected in runtime behavior.
- Manual 100%-trust channel policy is not reflected in schema/config.
- `!yt` metadata choice (`oEmbed`) is not implemented.
- Macro auto-post + on-demand command are not implemented.
- Level proximity cadence is answered but there is no level proximity alerter yet.

## Bottom Line

The roadmap is currently over-optimistic relative to the code. The most urgent correction is to stop treating the reliability/precision architecture as partially real when it is either missing, silently skipped, or not actually driving decisions. After that, the YouTube parser contract and the command/persistence surface need to be made internally consistent before more roadmap layers are added.
