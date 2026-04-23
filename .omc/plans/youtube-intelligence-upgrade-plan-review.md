# YouTube Intelligence Upgrade Plan — Adversarial Review

**Reviewed:** `.omc/plans/youtube-intelligence-upgrade-plan.md`
**Verdict:** needs-attention — do not implement as written
**Date:** 2026-04-22

> The plan is architecturally sloppy around idempotency, inference cost, and evidence tracking. If implemented as written it will create duplicate state, unstable parses, and unverifiable bad data.

---

## Findings

### [HIGH] Persistence is not idempotent — retries/backfills will duplicate rows

**Where:** Plan Phase 2 & 3, new table insert instructions

The plan adds `youtube_options` and `youtube_setups` tables and directs `process_video()` to persist them after existing inserts. It never defines uniqueness keys, upserts, or transaction boundaries. The current code already uses plain inserts guarded only by a non-atomic `has_video_been_processed()` check. Extending that same pattern to new tables means:

- A retry after a partial failure inserts duplicate options/setups while other tables are only partially populated.
- A future backfill run re-inserts all derived objects for already-processed videos.
- No way to cleanly re-parse a video with an improved prompt without removing all related rows manually first.

**Real-world impact:** Confidence scores inflate silently. Alerts fire on phantom data. Debugging requires manually diffing table contents against transcript files.

**Fix:** Define canonical uniqueness for every derived object before writing any code. Options: a deterministic hash of `(video_id, ticker, normalized_strike, expiry)` for options, and `(video_id, ticker, entry_hash)` for setups. Require transactional persistence or idempotent upserts across all YouTube-derived tables. Add a `parser_version` column and a reparse strategy that atomically replaces prior derived rows for that video/version pair.

---

### [HIGH] Per-chunk multi-pass parsing explodes request volume without budget or degradation design

**Where:** Plan Phase 1, decomposed passes per chunk

Phase 1 runs decomposed passes per chunk. Later phases add options and setups passes. On a long transcript already split into, say, 6 chunks, applying mentions + direction + macro + options + setups means up to **30 LLM calls per video**. The plan assigns the costliest cheap model (minimax) to the broadest passes, making the blow-up worse on the passes that matter most.

**Real-world impact:**
- Slower per-video processing — live scans miss channels publishing close together.
- Provider throttling on free-tier models — partial parse results become the norm, not the exception.
- No fallback defined: if the options pass fails mid-transcript, the plan has nothing to say about what gets persisted.

**Fix:** Redesign around a bounded pipeline:
1. One global mentions pass per full transcript (not per chunk) to extract all candidate tickers and price spans.
2. Chunk-level passes only when the full transcript exceeds context — and only for the narrowest task (mentions).
3. Snippet-scoped enrichment passes (options, setups) run only over the short spans that mention specific candidates — not over the full transcript or all chunks.
4. Explicit per-video call budgets: define a hard cap (e.g. 8 LLM calls max), a priority order for passes, and a degraded mode that stops after core extraction when the budget is exhausted or a provider is slow.

---

### [HIGH] No evidence provenance — will mis-assign trades in multi-ticker transcripts

**Where:** Plan Phase 2 & 3, `VideoOptionIdea` and `VideoTradeSetup` schemas

The proposed data models add `VideoOptionIdea` and `VideoTradeSetup` but never require storing the source snippet, chunk index, transcript timestamp, or any other provenance that ties a derived record back to a specific statement.

Many transcripts discuss 4–8 tickers across 30+ minutes of content. Without provenance, the setup-linking pass can combine a TSLA option mention in the first 5 minutes with an NVDA entry/stop pair from the last 10 minutes and still produce a syntactically valid `VideoTradeSetup` record that looks authoritative.

**Real-world impact:** Wrong ticker-setup pairings get persisted and surfaced in alerts. No way to audit or replay without the original snippet.

**Fix:** Make provenance a first-class schema requirement:
- Every extracted ticker, level, option, and setup carries `source_snippet` (the raw transcript span that produced it), `chunk_id`, and optionally `transcript_offset_chars`.
- Linking passes (setup, options) are restricted to records that share the same provenance window — they cannot combine evidence from different chunks/spans.
- Expose `source_snippet` in `!yt` and `!levels` command output so outputs are auditable.

---

### [MEDIUM] Double-counting: raw levels + setups coexist without a canonical read model

**Where:** Plan Phase 3 persistence + Phase 4 downstream formatting

Phase 3 persists setups in `youtube_setups` in addition to existing `youtube_levels` rows. Phase 4 says alerts and cross-reference should consume the richer structures. But the plan never defines whether setups **replace** their constituent raw levels or **coexist** with them.

Current system: `_handle_levels()` and cross-reference independently read `youtube_levels`. Adding setups/options on top without canonicalization means:
- One NVDA trade idea (entry 850, stop 820, target 920) appears as 3 raw levels **and** 1 setup — same video contributes 4× evidence.
- Confidence scores inflate.
- `!yt` and `!levels` command output will be inconsistent depending on which table each read path hits first.

**Fix:** Define a canonical downstream contract **before implementation**:
- Option A: Setups supersede linked raw levels. Once a level is absorbed into a setup, it is hidden from raw level queries.
- Option B: Raw levels remain but are tagged with `setup_id` to allow deduplication at query time.

Either way: update scoring and all read paths to dedupe by `(video_id, ticker, evidence_group)` rather than independently aggregating raw levels, setups, and options.

---

## Recommended Architecture Changes

These should be incorporated when writing the revised plan.

### 1. Canonical analysis anchor table

Add a `youtube_analysis_runs` table with columns `(video_id, parser_version, status, started_at, completed_at, call_budget_used)`. All child tables (`youtube_signals`, `youtube_levels`, `youtube_options`, `youtube_setups`) carry a `run_id` FK to this record. A reparse under a new parser version creates a new `youtube_analysis_runs` row and replaces all child rows atomically — old derived data is either soft-deleted or version-tagged.

### 2. Two-stage parser instead of N passes × M chunks

**Stage 1 — Transcript-wide candidate extraction (1–2 LLM calls max):**
- Extract all ticker mentions, price spans, and raw option keywords.
- Run on the full transcript if it fits; chunked only when necessary.
- Output: a flat list of candidates with source snippets attached.

**Stage 2 — Snippet-scoped enrichment (1 call per candidate type, not per chunk):**
- Direction/conviction: classify all extracted tickers in one batched call.
- Options: run `_OPTIONS_PROMPT` only over the extracted option-keyword snippets.
- Setups: run `_SETUPS_PROMPT` only over price-span snippets grouped by ticker.
- Each enrichment pass has a hard token and call budget; if exceeded, the pass is skipped and the run is marked `partial`.

### 3. Provenance on every derived row

Minimum required fields on every child table row:
- `source_snippet TEXT` — the raw transcript span that produced this record
- `chunk_id INTEGER` — which chunk this came from (0 = full transcript)
- `parser_version TEXT` — the prompt/schema version string

### 4. Single deduped read model for downstream consumers

Add a `youtube_evidence_for_ticker(ticker, days)` query or view that:
1. Returns setups (with linked options if present) where they exist.
2. Falls back to raw levels only where no setup covers the same evidence group.
3. Never double-counts a price level that has already been absorbed into a setup.

Cross-reference, `!yt`, `!levels`, and any future alert formatting all consume this one view.

---

## Summary

| Issue | Severity | Blocks implementation? |
|-------|----------|------------------------|
| Non-idempotent persistence | HIGH | Yes — fix schema design first |
| Per-chunk × per-pass call explosion | HIGH | Yes — redesign pipeline stages first |
| Missing evidence provenance | HIGH | Yes — add to schema before any new tables |
| Double-counting without canonical read model | MEDIUM | Yes — define contract before Phase 4 |
