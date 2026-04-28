# YouTube Grounding — Hallucination Killer

**Date:** 2026-04-27
**Branch target:** new feature branch off `master`
**Trigger incident:** Video `vkqchQQnm88` ("AMC GAMESTOP KOSS — IT HAS BEGUN!!!") produced a fabricated NVDA setup ($845-855 entry, $820 stop, $920 target, confidence 0.8). Zero NVDA mentions in actual content. Persisted at `parser_version="v2"` in `youtube_levels`/`youtube_setups`, no spans written.

**Sizing verdict:** MEDIUM (~500 LOC code + ~250 LOC tests). Single PR. No DB migrations. Two existing parsers + one new persistence-time guard.

---

## Problem (root-cause summary)

Three pipelines feed `youtube_levels` / `youtube_setups` / `youtube_signals`:

| Path | Code | `parser_version` | LLM | Hallucination handling today |
|---|---|---|---|---|
| **A. v2 evidence-first (two-stage)** | `_process_video_two_stage` (`scanners/youtube.py:199`) → `extract_evidence_with_gemini` → `classify_evidence` | `gemini-evidence/<model>-v1` | Gemini multimodal (video) → Python classifier | Trusts `EvidenceSpan.tickers` returned by Gemini; `_clean_tickers` only filters TA abbreviations |
| **B. Legacy single-call Gemini** | `parse_video_with_gemini` (`analysis/gemini_video_parser.py:503`) | `v2` | Gemini multimodal (video) — single JSON blob | **No grounding at all.** Source of the NVDA incident. |
| **C. Transcript fallback** | `parse_video_transcript` (`analysis/video_parser.py:867`) | `v2` | OpenRouter LLM on transcript text | `_has_financial_context` filter exists but only in `_fallback_parse`, not the LLM JSON path |

DB confirmation for `vkqchQQnm88`:

```
SELECT ticker, level_type, price, parser_version
FROM youtube_levels WHERE video_id='vkqchQQnm88';
NVDA|entry_low|845.0|v2
NVDA|entry_high|855.0|v2
NVDA|stop|820.0|v2
NVDA|target|920.0|v2
GME|entry_low|25.38|v2
GME|resistance|26.0|v2
AMC|target|2.0|v2

SELECT COUNT(*) FROM youtube_evidence_spans WHERE video_id='vkqchQQnm88';
0
```

Zero spans + `parser_version="v2"` ⇒ **Path B was the writer**. v2 evidence path either errored or returned `bundle=None` (likely flash-lite parse failure or quota), and `legacy_fallback=true` allowed Path B to run unguarded.

The fix must cover **all three paths**, not just the v2 path Codex's plan focused on.

---

## RALPLAN-DR Summary

### Principles
1. **Defense in depth** — multiple cheap deterministic checks beat one expensive LLM check. Each layer rejects independently.
2. **Trust evidence, verify labels** — Gemini's `quote` strings are factual (verbatim transcript-like). The `tickers[]` field is a label and must be cross-checked against the quote.
3. **Surgical changes** — patch the existing parsers; do not redesign the pipeline.
4. **Audit-trail preservation** — suppress, don't delete. Every contaminated row stays in DB with `suppressed=1` + `suppression_reason` so future investigators can replay.
5. **One bug, one PR** — no opportunistic refactors. Adjacent improvements (e.g., consolidating the three parser paths) wait for a separate spec.

### Decision Drivers (top 3)
1. **Zero tolerance for fabricated tickers in alerts** — financial integrity. A single hallucinated NVDA alert undermines trust in every other alert.
2. **Coverage of all three pipelines** — v2 + legacy + transcript. Codex's plan only addressed v2; the actual incident came from Path B.
3. **Single-PR scope** — ~750 LOC inclusive of tests. No DB migrations. No new dependencies. Reviewable in one sitting.

### Viable Options

**Option A (chosen): Layered grounding everywhere + default-disable Path B.**
- Description: implement Layers 1–5 across Paths A, B, and C; default `youtube.legacy_fallback: false` so Path B does not run unless an operator explicitly re-enables it after observing coverage data.
- Pros: cheap deterministic checks first; each layer testable in isolation; covers Path A (v2 evidence-first) and Path C (transcript) — both validated paths; Path B kept hardened-but-off so a future operator can enable it without re-implementing grounding; preserves Gemini multimodal chart-extraction capability via Path A.
- Cons: 5–6 files touched; alias map needs ongoing curation; small recall risk during the soak window when Path A fails and Path C has no transcript available.

**Option A0 (rejected): Layered grounding everywhere + Path B remains default-on.**
- Pros: maximum recall during soak — Path B catches videos where Path A fails AND captions are blocked.
- Cons: Path B is the proven hallucination writer (the `vkqchQQnm88` incident). Even with grounding, Path B has weaker evidence than Paths A/C (no verbatim spans — only the model's own `context` strings, which can be hallucinated alongside the ticker). Carrying it default-on means the only known hallucination class remains armed.

**Option B (rejected, but partially adopted): Delete legacy single-call Gemini path entirely.**
- Pros: simpler — one fewer pipeline to harden permanently.
- Cons: removes the option value of Path B for any future scenario. Permanent deletion is an irreversible decision better made after observing real coverage data with Path B disabled.
- **Partial adoption:** Option A flips `legacy_fallback: false` by default. Functionally Path B is dormant in this PR; hard-deletion is a 30-day follow-up. This is "Option A+B-phased."

**Option C (rejected): Switch to text-transcript-only across all paths (no Gemini video).**
- Pros: trivially groundable — transcript IS the source.
- Cons: loses chart-level extraction Gemini provides via Path A; YouTube finance channels frequently disable auto-captions for cloud IPs (Playwright scraping documented in `youtube.py:7-10`); coverage drop unacceptable; throws away the multimodal capability we paid Gemini to deploy.

**Why A wins (honest framing):** A keeps Path A's chart-extraction capability validated by grounding, keeps Path C's transcript fallback validated by grounding, and disables Path B by default until coverage data justifies enabling it. The hallucination root cause is *unverified LLM output*, not *use of multimodal models*; A defends against the cause without amputating the capability. Option B is partially adopted (default-off) but not fully (no deletion) so we retain the option to re-enable per-channel if a high-trust source produces consistent transcript failures.

### Pre-mortem (deliberate mode auto-triggered: financial integrity / production incident)

1. **Alias map incomplete → grounding rejects legitimate tickers.** E.g. video says "Berkshire" but alias map only knows BRK.B not BRK.A; or new IPO ticker not in map. Mitigation: `$TICKER` literal regex check is primary; alias is supplemental. Allowlist Layer 3 falls through to title — a ticker in the title or another span's quote keeps it alive even if its primary span loses alias match. Test fixture covers 20+ common name→ticker pairs.

2. **Price sanity rejects legitimate post-split levels.** E.g. NVDA pre-10:1-split level of $850 quoted in a 2024 video re-aired today. Mitigation: ratio bucket includes split factors {2,3,4,5,10,20} bidirectionally with ±25% tolerance. Sanity check applies to *alerts* only — persistence keeps the row with `suppressed=1`, so we can audit and adjust thresholds.

3. **Backfill suppresses a span we missed.** E.g. NVDA legitimately mentioned but quote happens to lack the literal symbol (speaker says "the chip giant" with NVDA inferred from context). Mitigation: backfill marks `suppressed=1` not delete; reason `hallucination_backfill` is greppable; manual audit flips individual rows back. Backfill is reversible.

### Expanded test plan (deliberate mode)

| Layer | Unit | Integration | E2E | Observability |
|---|---|---|---|---|
| Layer 1 (prompt) | n/a (string change) | Snapshot test of prompt content | Replay one real video against new prompt; assert ticker count drops sanely | Log full Gemini prompt in DEBUG |
| Layer 2 (quote ground) | `_ticker_grounded_in_quote` table tests (20+ cases) | `_build_evidence_bundle` filters NVDA from AMC-quote span | Replay `vkqchQQnm88` → 0 NVDA artifacts | Log dropped (ticker, span_id) pairs at INFO |
| Layer 3 (allowlist) | `_video_ticker_allowlist` builder tests | `_process_video_two_stage` rejects non-allowlist signal | Replay `vkqchQQnm88` end-to-end → 0 NVDA in DB | `youtube_signals.suppression_reason` rollup metric |
| Layer 4 (price sanity) | ratio-bucket + tolerance tests | `_send_two_stage_alerts` skips $850 NVDA when live=$145 | Mock Discord post — no message sent for hallucinated NVDA | Log all sanity-rejected alerts at WARNING |
| Layer 5 (backfill) | dry-run mode test | Sqlite fixture with 3 hallucinated rows → all 3 suppressed | Run against `consensus.db`, manual sanity check | Print summary `N rows suppressed` |

---

## Layer index

| # | Spec | Layer | Files touched | LOC |
|---|---|---|---|---|
| 01 | [Prompt hardening](01-prompt-hardening.md) | 1 | `gemini_video_parser.py` | +20 |
| 02 | [Quote grounding](02-quote-grounding.md) | 2 | `gemini_video_parser.py`, new `analysis/ticker_grounding.py` | +180 |
| 03 | [Video-level allowlist](03-video-allowlist.md) | 3 | `scanners/youtube.py`, `models.py`, `gemini_video_parser.py`, `video_parser.py`, `config/consensus.yaml` | +145 |
| 04 | [Price sanity at alert time](04-price-sanity.md) | 4 | `scanners/youtube.py`, new `analysis/price_sanity.py` | +95 |
| 05 | [Backfill suppression](05-backfill-suppression.md) | 5 | new `scripts/backfill_youtube_grounding.py` | +140 |
| 06 | [Regression tests](06-regression-tests.md) | all | `tests/analysis/`, `tests/scanners/`, `tests/scripts/` | +375 |

**Total LOC:** ~580 implementation + ~375 tests = ~955. Single PR; reviewable in one session; no DB migrations.

---

## ADR

**Decision:** Implement five-layer defense (prompt + quote-grounding + allowlist + price-sanity + backfill) covering all three YouTube parser paths.

**Drivers:**
1. Eliminate hallucinated tickers from alerts (financial integrity).
2. Cover all three pipelines, not just v2 (the actual incident was Path B).
3. Preserve Gemini multimodal capability (chart-level extraction is a differentiator).
4. Single PR, no migrations.

**Alternatives considered:** Delete legacy path (Option B); transcript-only (Option C). Both rejected: they delete the bug class by deleting the capability, which throws away chart-level extraction and increases coverage gaps when transcripts are blocked.

**Why chosen:** Layered defense lets every check fail-open into the next; no single point of failure. Every layer is independently testable. The deepest check (Layer 2 quote grounding) is essentially free at runtime — one regex search per ticker per span — and would have prevented the NVDA incident on its own.

**Consequences:**
- ~820 LOC PR. Reviewable; not a redesign.
- New small module `analysis/ticker_grounding.py` becomes the source of truth for "is this ticker actually in this evidence?". Reused by all three parser paths.
- Alias map is config-as-data: `config/ticker_aliases.json` maintained by hand; PR adds the top-100 alias map, future tickers added on demand.
- Backfill script is one-shot; lives in `scripts/` and is `.gitignore`d from auto-run. Operator runs it manually after PR ships.
- Discord alert volume may drop short-term as hallucinations are filtered. **Monitor:** `metric: youtube.alerts_sent_per_day` for two weeks post-deploy.

**In-scope expansions added after Architect review:**
- **Path B parser_version disambiguation** (Spec 03 §c.1): preserve `parser_version="gemini/<model>"` for Path B writes instead of collapsing to `"v2"`. Restores forensic attribution of hallucinations to their source pipeline. Adds 1 dataclass field + 7 plumbing lines.
- **Default `youtube.legacy_fallback: false`** (Spec 03 §c.2): flip Path B off by default in this PR. Path A failures fall straight to grounded Path C (transcript). Path B is the proven hallucination writer; carrying it for a 2-week soak buys chart-extraction recall at the cost of the only known hallucination class. Operators can re-enable per-deploy after observing real coverage data.

**Follow-ups (not in this PR):**
- Consolidate Path B and Path C into a single "post-LLM grounding pass" function (refactor; needs separate spec).
- Add `youtube.gemini.model` upgrade path: route HIGH-trust channels to `gemini-2.5-flash` or `gemini-2.5-pro` for higher-quality extraction (lower hallucination rate).
- Hard-delete Path B entirely after 30 days of `legacy_fallback=false` operation with no coverage regressions.

---

## Verification (top-level)

After all specs implemented:

```bash
# 1. Unit tests pass
python3 -m pytest tests/analysis/test_ticker_grounding.py -v
python3 -m pytest tests/analysis/test_price_sanity.py -v

# 2. Full suite green
python3 -m pytest tests/ -q --tb=short

# 3. Replay the incident video against the classifier — must produce zero NVDA artifacts
#    (uses existing scripts/replay_classifier.py with the v2 evidence bundle path)
python3 scripts/replay_classifier.py --video vkqchQQnm88 --assert-no-ticker NVDA
#    If replay_classifier.py does not yet support --assert-no-ticker, the
#    minimum viable verification is reading its output and grepping for NVDA.

# 4. Backfill the existing DB (one-shot, after PR ships)
python3 scripts/backfill_youtube_grounding.py --dry-run  # preview
python3 scripts/backfill_youtube_grounding.py            # apply

# 5. Confirm hallucinated rows now suppressed
sqlite3 consensus.db "SELECT video_id, ticker, suppression_reason FROM youtube_levels WHERE video_id='vkqchQQnm88' AND ticker='NVDA';"
# Expected: 4 rows, all suppression_reason='hallucination_backfill'
```

**Acceptance:** zero NVDA artifacts emerge from `vkqchQQnm88` on a fresh replay; all four NVDA rows in the existing DB are marked `suppressed=1`; full test suite green.

---

## Out of scope (do not touch)

- The `EvidenceBundle` / `EvidenceSpan` dataclasses (`models.py`) — schema is fine; we filter into them, not rewrite them.
- The `_classify_direction` / `_classify_level_type` / `_cluster_setups` rules in `video_classifier.py` — the bug is upstream of classification.
- The Gemini key rotation logic — orthogonal.
- The Discord alert formatting code — Layer 4 only adds a check before sending.
- The `youtube_videos.title` schema or scraping — title is already stored, we just consume it.
- Channel trust scores — orthogonal.
