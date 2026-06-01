# Pass 4b — Adversarial Plan Review (codex was DOWN → Gemini + independent verifier)

## Tooling note
The user asked to send the plan to **Codex**. Codex is **unavailable on this account**: every invocation (incl. no model flag) errors `gpt-5.4 not supported with a ChatGPT account` — the codex companion is pinned to a model the ChatGPT plan doesn't include. Per the kickoff ladder (diagnose → fix → alternative → surface), the independent adversarial review was routed through the available alternatives instead:
- **Gemini 2.5-flash** (true cross-model, non-Claude) — reviewed the plan text.
- **A fresh opus agent** — verified every plan claim against the ACTUAL code (file:line).
Both reached **VERDICT: REVISE** and converged on the same BLOCKER.

## BLOCKER (both reviewers) — confluence data source is half-empty
Plan §4 assumed twitter/options/SEC write `signal_events` with a usable `direction`. Verified reality:
- **Twitter** → `signal_events` with direction ✓ (db.py:826)
- **YouTube** → `signal_events` + `youtube_signals` with direction ✓ (video_parser.py:1007)
- **ANALYST_CLUSTER** → `signal_events` but `direction=NULL` (herding.py:204) — normalizer must skip NULL
- **Options** ✗ → writes `options_flow` table, direction = `FlowHit.side` CALL/PUT (db.py:416,1926) — NOT in signal_events
- **SEC** ✗ → writes `ticker_signals` with a `Sentiment` enum (main.py:274-288) — NOT a `direction` in signal_events

→ A confluence engine reading only `signal_events` would silently miss options + SEC (2 of 4 spec-required sources).
**Fix (when confluence is built):** read THREE tables — `signal_events` (twitter/youtube), `options_flow` (side→direction), `ticker_signals WHERE source_type='sec_filing'` (sentiment→direction) — and normalize each to a `Stance`. Run a `scripts/verify_confluence_sources.py` data-quality check BEFORE writing any confluence code.

## Convergent recommendation — ship a THINNER v1
Both reviewers: building 8 modules + confluence + 2 schedulers + beneficiary + backfill before one email is verified end-to-end is too much for a non-coder solo project on a free Gemini key, and the BLOCKER lives in the confluence module. **Defer confluence, digests/recap, beneficiary, backfill to a verified phase-2.** This matches the kickoff's own order (reader → state → … ) and "one verified phase beats three half-built."

## Other must-fixes / fixes (verifier + Gemini)
- **Paths:** `consensus_engine/data/sector_map.yaml` (+ peer_groups.yaml), NOT `data/*.yaml`. (verifier MAJOR-1)
- **Subject gate drops Wraps:** default `subject_substrings` don't match "Market Wrap". Sender allowlist already pins to Wolf → **skip the subject substring test for the trusted Wolf sender** (simplest fix). (verifier MAJOR-2)
- **C-2 fix precision:** pass the real `stop_event` (available at the call site, main.py:552) instead of `combined_stop` at main.py:676. Trivial. (verifier claim-1)
- **Digest synthesis output-injection** (Gemini MAJOR): if/when digests are built (phase-3), synthesize ONLY from validated/enum-clamped fields, never verbatim source text; add a synthesis-injection test.
- **Chart prioritization (simplify):** v1 = first 5 distinct non-tracking image URLs by order of appearance (deterministic), not text-linking heuristics. (Gemini MINOR)
- **Chart↔text integration (simplify):** LLM extracts from HTML text; append `ChartRead` results as structured fields linked by identifier — avoid multimodal prompting in v1. (Gemini MINOR)
- **Sprawl-cap behavior:** when a scope cap is hit, invalidate the oldest least-recently-updated active thesis of that scope (+log). (Gemini MINOR)
- **Critical ping batching:** post the alert message to #news IMMEDIATELY; only the @-ping is suppressed/retried on rate-limit (don't delay the content). (Gemini MINOR)

## UPDATE — real Codex review obtained (gpt-5.5, 2026-05-31)
After the user fixed the CLI model to gpt-5.5, Codex ran successfully (251k tokens, xhigh). **Caveat:** its sandbox (root) was denied entry to `/home/openclaw/.openclaw` (owned `nobody:nogroup`, `bwrap: Can't chdir ... Permission denied`), so it could NOT read the plan files — it reviewed the **live source + spec + the public GitHub repo** and honestly marked plan-text claims "UNVERIFIABLE". Verdict: **REVISE**. Raw at `codex-review-raw.txt`.

### Codex BLOCKER that the local critic + Gemini BOTH missed (I verified it against real code):
- **Separate top-level supervisor required.** My earlier C-2 fix (pass raw `stop_event` to `gmail_watcher_loop` at main.py:676) would DEADLOCK: `run_live` gathers all tasks with `await asyncio.gather(*tasks)` (main.py:680). On weekend pause every other task exits but the stop_event-bound Wolf loop keeps running → gather never returns → the weekend command-listener branch (main.py:560-601, your `!`commands + @mentions) never starts all weekend. **Verified** by reading main.py:552-691 + entrypoint main.py:1383 `asyncio.run(run_live(stop))`. **Fix:** run the Wolf news watcher + digest scheduler as a SEPARATE top-level coroutine beside run_live (e.g. `asyncio.gather(run_live(stop), wolf_news_supervisor(stop))`), both on the shutdown `stop` event; the supervisor is independent of the weekend pause. NOT inside run_live's gather.

### Other NEW Codex findings folded in:
- **Durable outbox for ALERTS too (not just digests):** post only from a `pending` row (model on Alfred `briefing_runs` pending→posted, alfred.py:219-255). Prevents double-post/loss on crash. → new `wolf_news_alerts(dedupe_key,status,discord_message_id,payload_json,created_at,posted_at)` table.
- **Wolf-specific processing/dedupe table:** current dedupe hashes TEXT body only + marks seen only after ticker inserts (gmail_watcher.py:277-356) → image-only Wolf emails can be lost or replayed. → store message_id + normalized HTML hash + ordered image-URL hash + parse status + error; mark Gmail processed only AFTER durable state written.
- **Defer level-break alerts out of phase-1:** no price-watcher exists for Wolf levels (existing level alerts only query youtube_levels, main.py:702/731-738). Phase-1 alerts fire ONLY on new/changed thesis from a new email; level-break monitoring → phase-2 with a dedicated price source.
- **Verify token scope before enabling:** do a test label-modify (gmail.modify) on startup; multi-header `Authentication-Results` evaluation; persist skipped-due-budget/cap telemetry.

### Codex findings ALREADY in my plan (independent confirmation):
image helper must be image-specific (not a video-parser mutation); hard backpressure + per-email image cap; new tables go in SCHEMA (not _run_column_migrations) + bump _schema_versions; scope needs scope_type+scope_key not just sector ETF.

## DECISION (delegated to me by the user)
**MODIFY the plan (round 1: Gemini+verifier)** → thinner v1 + must-fixes. Then **round 2 (real Codex on gpt-5.5)** → fold the supervisor-deadlock BLOCKER + outbox-for-alerts + Wolf-processing table + defer level-breaks. See "PLAN REVISION v2" in final-plan.md. Proceed to build **phase-1** (reader → vision → extraction → thesis → new/changed-thesis #news alert via a separate supervisor + durable outbox), stopping at the HARD GATE (sign-off before creating #news content / first live post / enabling in prod). Level-breaks, confluence, digests, beneficiary, backfill = phase-2+, after phase-1 is live-verified.

Codex was the most valuable reviewer: it found the one blocker that would have shipped a real regression (weekend command-listener deadlock). Worth re-running Codex (now working on gpt-5.5) at the end of phase-1 to review the actual diff — but next time fix the sandbox path first (chmod/bind so root can read the workspace) so it can verify the plan/diff directly instead of via GitHub.
