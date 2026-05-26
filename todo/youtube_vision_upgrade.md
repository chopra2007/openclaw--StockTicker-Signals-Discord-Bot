# YouTube Vision Upgrade — Status

**Status:** OPEN — prompt fixes shipped 2026-05-25; production wire-up still pending.
**Created:** 2026-05-25

**Goal:** give the LLM more useful data from each YouTube video so it can understand the analyst's actual evidence (chart levels, scanner numbers, gamma exposures) — not just what was said out loud.

**Test video used throughout:** `https://youtu.be/F74qsOrb6t4` — "This is BIG" by Cheddar Flow, ~10 minutes long.

---

## What worked

### 1. The vision model can read what's on the screen
- Sending the YouTube link directly to Gemini works even though our VPS IP is blocked by YouTube. Google's servers fetch the video on their end (Google → YouTube, same company, no block).
- The VPS only sends a 40-byte URL string. No video data crosses our server.

### 2. Splitting into two API calls produces clean, complete results
Instead of one big call doing everything (which hit Gemini's 65,536-token output cap and got cut off mid-sentence), we now do:
- **Trip A** — "list things visible on screen that aren't spoken" (capped at 50 entries by a hard schema)
- **Trip B** — "transcribe spoken sentences with timestamps" (no cap, free-form)

Both trips finish cleanly. Total time ~35 seconds per video.

### 3. Vision adds real data the audio doesn't have
Live test on the Cheddar Flow video returned:
- **11 horizontal gamma price lines** on the chart that the speaker only called "these lines" — exact values: 745.64, 740.13, 736.78, 730.31, 724.48, 718.65, 712.80, 707.00, 701.18, 710.89, 695.04
- **Aggregate gamma panel**: net 13.3B, calls 30.5B, puts -17.3B
- **Daily expected move bounds**: max 750.3 / min 736.76
- **Full option-flow scanner rows** with strike, premium, delta, gamma, theta, vega, IV, OI for individual contracts (e.g. strike 800 / spot 737.71 / $52.9M premium)
- **Daily change box**: $6.28 (0.71%)

44 distinct visual-only data points on a single 10-minute video.

### 4. Two prompt bugs found and fixed
- **MSFT / "April 29" / $400.15 phantoms** — the old prompt used real-looking placeholder values in its example JSON. When the model had little to extract, it just echoed the example back as if it were real video data. Fixed by switching to obvious `<placeholder>` syntax that the model won't echo.
- **Hallucinated timestamps past 10 minutes** — the old prompt said *"Target 30–80 spans for a 40-minute video"*. The model used "40-minute" as an anchor and emitted timestamps up to 22:47 on a 10:15 video. Fixed by removing the anchor and telling the model to scale to the actual duration.

---

## What didn't work (and why)

### 1. Single-call architecture with everything in one JSON
- All three sections (visual_evidence + segments + spans) in one call always hits the 65,536 output-token cap. Whichever section is listed first eats the budget, the rest get truncated.
- Why we couldn't just raise the cap: 65k is the hard model limit. The 1M context Gemini advertises is for INPUT only (the video coming in), not OUTPUT (notes going out).

### 2. Soft "cap at 50" instructions in the prompt
- Telling Gemini *"return at most 50 entries"* in plain English: the model ignored it, emitted 1,300+ entries.
- The fix that worked: use Gemini's `response_schema` feature, which enforces JSON Schema constraints (like `maxItems: 50`) at the API level. The model literally cannot exceed the cap.

### 3. Complex response schemas
- First schema attempt (all 3 sections + enums + property ordering) was rejected by Google with `"The specified schema produces a constraint that has too many states for serving."`
- Fix: keep the schema minimal — only the array we want capped, no enums, no property ordering, no nested nested objects.

### 4. Per-value uniqueness via schema
- JSON Schema's `uniqueItems` checks whole-object equality, not per-property uniqueness. The model still emits the same chart label at different timestamps (e.g. "739.88" 6 times within the 50-entry budget).
- Workaround: dedup in our code after the response comes back. 44 unique values out of 50 raw entries = 88% efficient — acceptable.

### 5. Gemini's audio transcriber bleeding context across sentences
- One span returned "400 IPO" — the speaker actually said "400 [level/line/area]". The previous sentence mentioned "SpaceX IPO" and Gemini's speech-to-text echoed "IPO" into the next sentence by mistake.
- Not fixable from our side without swapping to a different transcriber (e.g. Whisper).

### 6. The "segments" array
- Came back empty on this video. The model couldn't find chapter-style sections because YouTube chapter markers weren't set.
- Not a real failure — there are no segments to find. Leave as-is.

---

## Next steps

### Priority 1 — Ship the prompt fixes to production
The fixes I made are in `consensus_engine/analysis/gemini_video_parser.py`:
- `_EVIDENCE_PROMPT` (lines 70–95) — placeholder syntax, visual_evidence section, scaled-to-actual-duration anchor, dedup + cap hints

**Status:** ✅ DONE — committed in `e7ae531` and pushed to origin/master 2026-05-25.
**Action:** none for Priority 1; remaining work is Priority 2 (production wire-up).

### Priority 2 — Wire `response_schema` into production
The probe used `response_schema` to hard-cap the vision call. Production code (`_build_generation_config` in same file) does NOT pass `response_schema` — it only sets `media_resolution`.

Without this, production calls will rely on the soft prompt instructions, which the model ignores → we'll still hit truncation in real runs.

**Action:** add ~10 lines to `_build_generation_config` that accept an optional `response_schema` and a `response_mime_type="application/json"`. Then update `extract_evidence_with_gemini` to use the two-trip pattern (vision call with schema cap, spans call without).

### Priority 3 — Decide on the two-call cost tradeoff
- Two API calls per video = ~2× latency (~35s vs ~17s) and ~2× input-token cost (each call re-sends the full video, ~182k tokens).
- On free-tier Gemini quota, this halves how many videos we can process per day.
- Options:
  - (a) Accept 2× cost for the quality gain — recommended if vision-only data materially improves signals
  - (b) Stay with single call but reduce span count drastically (e.g. 10 spans max) so visual_evidence fits in the same budget — fewer spoken-quote details
  - (c) Hybrid: single call for normal videos, two calls only for videos with heavy chart content

**Action:** measure the LLM downstream — does the extra visual data move signal accuracy? If yes, option (a). If no, drop the second call.

### Priority 4 — Post-process dedup and validation
Even with the schema cap, we get ~6 duplicate entries per 50. Add a dedup step in `extract_evidence_with_gemini` that:
- Collapses repeats by `value` (keep first occurrence)
- Drops any entries whose `ts_sec` falls outside the actual video duration
- Persists only unique, in-range entries to the DB

### Priority 5 — DB cleanup of old phantom data
Past videos processed by the old prompt likely have phantom `MSFT` / "April 29" / $400.15 spans persisted in `youtube_evidence_spans`. Suggested cleanup query (review before running):

```sql
DELETE FROM youtube_evidence_spans
WHERE quote LIKE '%Number One Draft Pick: MSFT%'
   OR quote LIKE '%Bullish bias into April 29th%'
   OR (ts_sec IN (2024, 2172) AND tickers @> ARRAY['MSFT']);
```

**Action:** run this once with `SELECT` first to see the row count, then delete.

### Priority 6 — Audio-transcription edge cases (low priority)
The "400 IPO" mishearing won't be common, but if it shows up as a signal-quality issue, consider:
- Adding a post-LLM sanity filter: if `numbers` contains a price and `quote` ends with "IPO" but no IPO is in any other span → flag for review
- Or swap the transcriber from Gemini's built-in speech-to-text to OpenAI Whisper (more accurate but adds another API)

---

## Open questions worth flagging to the user

1. The vision model reported `duration_sec: 906` for a video the user said is 10:15 (615s). Could the user's stated length be wrong, or is the model misreading the timestamp readout? Worth confirming actual length.
2. The Cheddar Flow video used a flow scanner UI we'd never seen before — vision extracted full table rows. Should we treat scanner UI screenshots as a special signal category in the alerts (e.g. "$52.9M call premium at strike $800" alone could trigger an unusual-flow alert)?
