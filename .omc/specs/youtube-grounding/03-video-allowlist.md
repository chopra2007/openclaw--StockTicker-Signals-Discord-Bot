# Spec 03 — Video-Level Allowlist (Layer 3, defense in depth)

**Goal:** Reject any signal/level/setup/option whose ticker is not grounded in *any* evidence text for the video — title, description, all span quotes, or all level/setup contexts. Catches the case where a ticker slipped past the per-span grounding (e.g., model claims it in `tickers[]` but our regex missed an alias we don't have configured).

**Sizing:** SMALL (~120 LOC).

---

## How it differs from Layer 2

- Layer 2 (Spec 02) rejects per-span: "is the ticker label supported by THIS span's quote?"
- Layer 3 rejects per-video: "is the ticker mentioned ANYWHERE in this video's evidence pool?"

Layer 3 catches: a ticker that sneaks into one span's `tickers[]` (because the model wrote a quote that happened to contain a confusable substring), but which is mentioned nowhere else in title, description, or any other span quote. A real ticker discussed seriously in a video appears multiple times across multiple spans. A hallucinated one usually appears in exactly one span.

---

## (a) Allowlist builder

Add to `consensus_engine/analysis/ticker_grounding.py`:

```python
def build_video_allowlist(
    video_title: str,
    span_quotes: list[str],
    extra_texts: list[str] | None = None,
    candidate_tickers: list[str] | None = None,
) -> set[str]:
    """Build the set of tickers acceptably grounded in this video's evidence.

    A ticker is in the allowlist if it is grounded (literal or alias match) in
    any of: title, any span quote, any extra text.

    `candidate_tickers`: if provided, restrict the check to this set. Otherwise
    we'd have to enumerate all known tickers — too expensive. In practice the
    caller passes the union of all tickers the LLM claimed.

    Note on description: `youtube_videos` schema has no `description` column
    (db.py:160-170). Adding one would be a migration, which this PR explicitly
    forbids (README "No DB migrations"). Title + spans is sufficient grounding
    pool for this fix; a future cheap PR can add description fetch and
    upgrade the allowlist.
    """
    if not candidate_tickers:
        return set()
    pool = [video_title or ""]
    pool.extend(q for q in span_quotes if q)
    if extra_texts:
        pool.extend(t for t in extra_texts if t)

    out: set[str] = set()
    for ticker in candidate_tickers:
        if assert_ticker_grounded_in_any(ticker, pool):
            out.add(ticker.upper())
    return out
```

**LOC delta:** +25 lines.

---

## (b) Wire into Path A (`_process_video_two_stage`)

**File:** `consensus_engine/scanners/youtube.py`
**Current function:** lines 199–392

Currently passes `video_id, channel_id, display_name, published_at`. Add a step after `classify_evidence` that builds the allowlist from spans + title + description, then drops candidates whose ticker isn't in it.

```diff
 async def _process_video_two_stage(
     video_id: str,
     channel_id: str,
     display_name: str,
     published_at: str,
 ) -> bool:
     ...
     bundle, telemetry = await extract_evidence_with_gemini(
         video_id, display_name, published_at,
     )
     if bundle is None:
         return False

     result = classify_evidence(bundle)
     catalysts = await resolve_and_verify_catalysts(
         result.catalyst_candidates, bundle.publish_ts,
     )

+    # ── Video-level allowlist (Layer 3) ─────────────────────────────────
+    from consensus_engine.analysis.ticker_grounding import build_video_allowlist
+    video_meta_row = await db.get_youtube_video(video_id)
+    title = video_meta_row.get("title", "") if video_meta_row else ""
+    span_quotes = [sp.quote for sp in bundle.spans]
+    candidate_set = (
+        {s.ticker for s in result.signals}
+        | {l.ticker for l in result.levels}
+        | {s.ticker for s in result.setups}
+        | {c.ticker for c in catalysts}
+    )
+    allowlist = build_video_allowlist(
+        video_title=title,
+        span_quotes=span_quotes,
+        candidate_tickers=list(candidate_set),
+    )
+    _suppress_off_allowlist(result.signals, allowlist, "off_allowlist")
+    _suppress_off_allowlist(result.levels, allowlist, "off_allowlist")
+    _suppress_off_allowlist(result.setups, allowlist, "off_allowlist")
+    _suppress_off_allowlist(catalysts, allowlist, "off_allowlist")

     min_conf = float(cfg.get("youtube.classifier.min_confidence", 0.5))
     ...
```

Add a small helper near the top of the file:

```python
def _suppress_off_allowlist(items, allowlist: set[str], reason: str) -> int:
    """Mark items whose .ticker is not in `allowlist` as suppressed. Returns count.

    Idempotent: never re-suppresses or overwrites an already-suppressed item's
    `suppression_reason` (preserves earlier reasons like "price_sanity" or
    "near_price_dedup" so the audit trail attributes the FIRST cause).
    """
    n = 0
    for it in items:
        ticker = getattr(it, "ticker", "")
        if not ticker:
            continue
        if getattr(it, "suppressed", False):
            continue  # preserve earlier suppression_reason
        if ticker.upper() not in allowlist:
            it.suppressed = True
            it.suppression_reason = reason
            n += 1
    return n
```

**LOC delta:** +35 lines.

---

## (c) Wire into Path B/C (legacy persist block in `process_video`)

**File:** `consensus_engine/scanners/youtube.py`
**Current location:** lines 601–714 (the shared persistence block after `parsed = await parse_video_with_gemini(...)` or transcript fallback)

**Critic-flagged correction.** The `db.insert_youtube_signal/level/setup/option` helpers already accept `suppressed: int = 0` and `suppression_reason: str | None = None` kwargs (`db.py:1422-1423, 1457-1458, 1634-1635, 1677-1678`). The earlier draft of this spec said Path B/C had to drop rows because suppression columns weren't plumbed through — that was wrong. We can and must suppress, preserving Principle 4 (audit-trail preservation).

Wire the allowlist gate as a per-row tag attached to the `parsed` data, then thread it into each `insert_youtube_*` call:

```diff
         # ── Persist results (shared path for both Gemini and transcript) ──────
         if parsed is None:
             return

+        # ── Video-level allowlist (Layer 3) — applies to both Path B and C ───
+        from consensus_engine.analysis.ticker_grounding import build_video_allowlist
+        candidate_set = (
+            {t.get("symbol", "").upper() for t in parsed.tickers if t.get("symbol")}
+            | {lv.ticker.upper() for lv in parsed.price_levels if lv.ticker}
+            | {s.ticker.upper() for s in parsed.setups if s.ticker}
+            | {o.ticker.upper() for o in parsed.options if o.ticker}
+        )
+        # Path B/C has no spans table — gather evidence from each item's context.
+        evidence_texts = (
+            [t.get("context", "") for t in parsed.tickers]
+            + [lv.condition for lv in parsed.price_levels]
+            + [s.context for s in parsed.setups]
+            + [o.context for o in parsed.options]
+        )
+        title = video_meta.get("title", "")
+        allowlist = build_video_allowlist(
+            video_title=title,
+            span_quotes=evidence_texts,
+            candidate_tickers=list(candidate_set),
+        )
+        log.info(
+            "video_allowlist (Path B/C): video=%s candidates=%s allowlist=%s",
+            video_meta["video_id"], sorted(candidate_set), sorted(allowlist),
+        )
+
+        def _suppress_meta(ticker: str) -> tuple[int, str | None]:
+            """Return (suppressed, reason) for an off-allowlist row; (0, None) otherwise."""
+            if ticker and ticker.upper() not in allowlist:
+                return 1, "off_allowlist"
+            return 0, None

         # Insert signals for each ticker
         for ticker_data in parsed.tickers:
             ticker = ticker_data.get("symbol")
             if ticker:
                 ...
+                supp, reason = _suppress_meta(ticker)
                 await db.insert_youtube_signal(
                     ...
-                    parser_version="v2",
+                    parser_version=parsed.parser_version,
+                    suppressed=supp,
+                    suppression_reason=reason,
                 )
```

Apply identical `_suppress_meta(...)` invocation to the per-level (`insert_youtube_level`), per-option (`insert_youtube_option`), and per-setup (`insert_youtube_setup`) calls in the same block (`youtube.py:637-714`). Each call gains 2 kwargs (`suppressed`, `suppression_reason`) and 1 lookup line.

**Audit consequence:** Path B/C off-allowlist rows are now persisted with `suppressed=1, suppression_reason="off_allowlist"`, identical to Path A's handling. Forensic queries can find every hallucination across all three pipelines via:

```sql
SELECT video_id, ticker, parser_version, suppression_reason
FROM youtube_levels
WHERE suppression_reason = 'off_allowlist'
ORDER BY video_id;
```

**LOC delta:** +45 lines (was +35; +10 for suppression plumbing across 4 insert calls).

---

## (c.1) Parser-version disambiguation (audit-trail preservation)

**Architect-flagged dependency.** Today `consensus_engine/scanners/youtube.py:631, 648, 680, 702` hard-code `parser_version="v2"` for every legacy persistence write — collapsing Path B (legacy single-call Gemini) and Path C (transcript fallback) into the same `parser_version` string that the v2 evidence-first path also uses for its run-row. The hallucinated NVDA rows in `vkqchQQnm88` are tagged `"v2"` but actually came from Path B; without disambiguation, future audits cannot identify which writer produced which row.

`gemini_video_parser.parse_video_with_gemini` already sets the correct distinct identifier at run-row creation (`parser_version = f"gemini/{model}"`, line 576), but the per-row inserts in `scanners/youtube.py` overwrite it.

**Fix:** thread the path-specific parser_version through from `parsed`. Add a `parser_version: str = "v2"` field to `ParsedVideo` (`models.py`) so each parser sets its own:
- `parse_video_with_gemini` → `parser_version=f"gemini/{model}"`
- `parse_video_transcript` → `parser_version="v2-transcript"`

```diff
 # consensus_engine/models.py — add a single field to ParsedVideo
 @dataclass
 class ParsedVideo:
     ...
     run_id: int
     options: list[VideoOptionIdea] = field(default_factory=list)
     setups: list[VideoTradeSetup] = field(default_factory=list)
+    parser_version: str = "v2"  # set by producer; never overwritten by persister

 # gemini_video_parser.py:576 — already creates the run with this label
 parser_version = f"gemini/{model}"
 # ... later in _build_parsed_video, propagate it
+    parsed.parser_version = parser_version

 # video_parser.py:867 — set the transcript-path label
+    parsed.parser_version = "v2-transcript"

 # scanners/youtube.py:631, 648, 680, 702 — read from parsed
-    parser_version="v2",
+    parser_version=parsed.parser_version,
```

**Why this is in scope:** without it, drop-vs-suppress in Path B/C creates a forensic black hole — exactly the principle-4 violation the Architect flagged. With it, future incidents can be replayed and attributed.

**LOC delta:** +8 lines (1 dataclass field, 2 producer assignments, 4 persistence reads, 1 import line in video_parser.py).

---

## (c.2) Defaulting `youtube.legacy_fallback: false`

**Architect-flagged scope addition.** With Layer 2 grounding now applied to Path C (transcript fallback) and Layer 3 allowlist applied to its persistence block, transcript-only fallback is grounding-safe. Path B (legacy single-call Gemini) is the proven hallucination writer and has weaker grounding (no per-span quote — only `context` strings the model itself produced) compared to Path A's verbatim quotes or Path C's literal transcript. Keeping `legacy_fallback: true` for a 2-week soak buys chart-extraction coverage at the cost of carrying the only known hallucination class.

**Decision:** flip the default to `false` in this PR. Path A failures fall straight to Path C (transcript). Operators can set it back to `true` per-deploy if they observe a coverage drop, but the default ships safe.

```diff
 # config/consensus.yaml line ~309
-  legacy_fallback: true                # keep old path as rollback when evidence extractor fails
+  legacy_fallback: false               # disabled; Path B is the hallucination writer (vkqchQQnm88 incident).
+                                       # Set true only after manual review of coverage data; see specs/youtube-grounding/.
```

**LOC delta:** +1 line, -1 line (net zero).

**Risk and mitigation:** transcript fetches via Playwright fail at ~5–10% rate per `youtube.py:7-10` rationale comment. With `legacy_fallback=false`, those videos return zero artifacts instead of Path B's possibly-hallucinated artifacts. Net-precision wins over net-recall for this PR's goals. Re-enable per-channel via a future `youtube.channels.<id>.legacy_fallback` override if a high-trust channel demonstrates >10% transcript failure.

---

## (d) Skip Path A `extra_texts` for now

For Path A we have all spans already; `extra_texts` parameter is forward-compatible for future use (e.g., chapter markers). Default `None` keeps the API simple.

---

## (e) DB helper: `db.get_youtube_video`

Path A's `_process_video_two_stage` does not currently fetch the title — it has only `video_id, channel_id, display_name, published_at`. Need a single-row fetch.

**File:** `consensus_engine/db.py`

```python
async def get_youtube_video(video_id: str) -> dict | None:
    """Return the youtube_videos row for video_id, or None."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT video_id, channel_id, title, published_at FROM youtube_videos WHERE video_id = ?",
        (video_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None
```

**LOC delta:** +9 lines (in db.py).

---

## (f) Description-fetch — explicitly out of scope

`youtube_videos` schema (`db.py:160-170`) has no `description` column. Adding it would be a migration, and the README "No DB migrations" rule forbids that. Description fetch + storage is a separate cheap follow-up PR (read from RSS `<media:description>` or oEmbed, plumb through `db.upsert_youtube_video`). Not blocking this fix — title + span quotes are sufficient grounding pool for the hallucination class observed in `vkqchQQnm88` (title is "AMC GAMESTOP KOSS" — that alone correctly excludes NVDA without needing description).

---

## Verification

```bash
python3 -m pytest tests/analysis/test_video_allowlist.py -v
python3 -m pytest tests/scanners/test_youtube_two_stage.py::test_off_allowlist_suppressed -v
python3 -m pytest tests/scanners/test_youtube_legacy.py::test_off_allowlist_dropped -v
```

Test cases:
- Title="AMC GAMESTOP KOSS", spans = AMC/GME quotes, candidate = {NVDA, AMC, GME} → allowlist = {AMC, GME}, NVDA dropped.
- Title="NVDA earnings preview", spans empty, candidate = {NVDA} → allowlist = {NVDA}.
- Title="" (rare), spans cover NVDA → allowlist = {NVDA} (spans alone sufficient).
- Title="$NVDA review", spans don't mention NVDA at all (model invented spans) → allowlist = {NVDA} (title sufficient — but Layer 2 would have dropped the ungrounded spans first, so this is largely defensive).

---

## Out of scope

- Description fetching (separate small PR; not blocking).
- Per-channel allowlist overrides ("trusted finance channel always allows [SPY, QQQ]") — overengineering for this fix.
- Sector / ETF grouping ("if XLK mentioned, allow tech tickers") — would re-introduce the inference problem we are solving.
