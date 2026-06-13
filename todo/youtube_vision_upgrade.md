# YouTube Vision Upgrade — Status

**Status:** ACTIVE — CRITICAL (reopened 2026-06-09). The chart-number-reading work (Tasks B/C, B1/B3) shipped and is the DONE sub-part. The now-active critical goal: **every YouTube video must be transcribed in full, start to finish.** It is not — see the "⚠ REOPENED 2026-06-09" section directly below. (Older lower-priority pending items from 2026-05-28 — narrator per-ticker wiring, the OUTPUT-token two-trip fix — are in the "Session notes — 2026-05-28" block at the bottom.)
**Created:** 2026-05-25

**Goal:** give the LLM more useful data from each YouTube video so it can understand the analyst's actual evidence (chart levels, scanner numbers, gamma exposures) — not just what was said out loud.

**Test video used throughout:** `https://youtu.be/F74qsOrb6t4` — "This is BIG" by Cheddar Flow, ~10 minutes long.

---

## ⚠ REOPENED 2026-06-09 — CRITICAL: full-video transcription (HIGH PRIORITY)

### The goal (user, 2026-06-09)
**Every YouTube video must be transcribed from start to finish.** Reading only the first few minutes is a critical failure. This is the top-priority YouTube goal now. (This session was documentation only — NOT a fix. The fix is a future session.)

### The issue — Gemini silently reads only the FIRST few minutes of long videos
The primary (and currently only reliable) path sends the YouTube URL to Gemini, which fetches the video on Google's servers (sidesteps our blocked IP — see "What worked"). But for long videos Gemini ingests only a small, **variable** slice of the start and reports `finish_reason=STOP` — i.e. it believes that slice is the whole video.

**Hard evidence (live probes 2026-06-09, video `e_iCwe2yX14`, true length 6314s / 105.2 min):**
- Default media-resolution probe → Gemini reported `observed_duration_sec=1121` (18.7 min); last line "See you guys."
- Low media-resolution probe → `observed_duration_sec=619` (10.3 min).
- Both `finish_reason=STOP`. So it is **input truncation**, not the output-token cut documented in the 2026-05-28 notes (all 45 recent runs logged `finish=STOP`, zero `MAX_TOKENS`).
- The amount seen **varies between identical calls** (18.7 vs 10.3 min) and is NOT explained by resolution — a resolution hypothesis was tested and refuted (low-res saw *less*, not more). Root mechanism of the youtube_uri truncation is still unknown → needs investigation.

**Scope of impact (last 128 videos, durations fetched via Invidious mirror):**
- 97 of 128 are ≤ ~19 min → safe (Gemini reads them whole).
- 10 of 128 are longer → at risk; the worst (105 min) was confirmed cut to ~18 min.
- Historically only 2 of the last 291 analysed runs produced literally no output; the rest produced *something* — but "produced spans" ≠ "read the whole video." Long livestreams are the loss.
- Separate data-quality bug spotted: Gemini sometimes invents timestamps *past the video's end* (a 55-min video had a quote stamped at 70 min). Worth fixing alongside.

### Why the caption fallbacks can't save us — they're effectively DEAD from this VPS
User suspicion confirmed. The chain is Gemini-video → captions → whisper. Both fallbacks depend on reaching YouTube from our IP, which YouTube has **blacklisted**. Live-tested 2026-06-09 on a real video (`JQCS4fv-NBI`), all four caption sources failed:
- `youtube_transcript_api` (free, direct) → **IpBlocked**.
- Supadata (paid, fetches via its own residential infra — IP-independent) → empty/limited. This is the ONLY caption source that *can* work here, but the free plan is ~100 credits/month and runs out (logs show "rate/plan-limited"). The recent ~46 "ytdlp-captions/v1" wins were actually this `fetch_captions` path (the label is legacy/misleading) succeeding intermittently via Supadata.
- Invidious public mirrors → empty.
- `yt-dlp` (also the whisper path's audio download) → **429 + "Sign in to confirm you're not a bot."**

So: **Gemini server-side fetch is the only path that reliably works from this server — and it's the one that truncates.** Captions/whisper would give whole-video coverage but are blocked by the IP blacklist.

### Gemini quota — what we know (the "how many minutes/videos per day" question)
- **2 keys** (`GEMINI_API_KEY`, `GEMINI_API_KEY2`), free tier, reset at **Pacific midnight** (`_next_quota_reset_ts`). On a daily 429 the key is benched to next reset and the other key is tried.
- **Per-video cost:** at `fps: 0.5` ≈ 144k input tokens for a standard video (1 fps ≈ 225k). `media_resolution: "auto"` (66–258 tokens/frame) scales this.
- **Config self-cap:** `budgets.gemini_input_tokens: 2,000,000` tokens/day.
- **Empirical daily reality** (`api_usage_daily`, recent): 1–25 video calls/day. The heaviest day (Jun 8) did 25 calls / 1.33M input tokens and **exhausted both keys** (84 "no_available_key" events). Most days 4–15 calls, no exhaustion. (Call count is inflated by retries — failed videos retry up to 5×.)
- **Documented free-tier limits are murky:** sources put gemini-2.5-flash at anywhere from 250 to 1,500 requests/day + ~1M tokens/minute, and Google **cut free quotas 50–80% in Dec 2025**. Quota is **per-project, not per-key** — so confirm whether our 2 keys are separate Google projects (independent quota) or share one. The config comment "~$0.30/day on Flash" hints these may be billable — **confirm free vs paid.**
- The config already states the practical ceiling: **"~3–4 FULL videos/key/day"** before 429 (so ~6–8 long videos/day across 2 keys; many more if short).

### Candidate fixes (for the future session — NOT done)
1. **Chunk long videos through Gemini** using `VideoMetadata` start/end offsets: split a 105-min video into ~N windows, analyse each, merge spans. Full coverage WITH chart-vision, but ~N× the quota/calls per long video. **First verify offset-chunking actually defeats the truncation** (unknown).
2. **Buy Supadata credits** → full-length captions for every video (IP-independent, whole video, cheap), text-only (loses chart-number vision). Could run captions for full coverage + Gemini for the visual layer.
3. **Gemini Files API (upload) instead of youtube_uri** — may process full length, but needs the video file downloaded first (yt-dlp is IP-blocked → needs a proxy).
4. **Fix the VPS IP blacklist** (residential/rotating proxy, or move YouTube fetches off this host) → revives youtube_transcript_api + yt-dlp + whisper, all of which read the whole video.

### Chain simplified this session (2026-06-09) — dead methods removed for good
The transcription chain is now just **F2 Gemini → F1 Supadata captions**. Removed (with permanent code notes + a memory entry, never to be re-added — all dead on our blacklisted IP): youtube_transcript_api, yt-dlp, the F3 yt-dlp+Whisper stage, and Invidious-captions. Supadata is the limited-credit final backup. Invidious is kept ONLY for the video-duration lookup (metadata still works). So any future fix builds on Gemini (chunking) and/or Supadata (buy credits) — there is no third local path unless the IP block is solved. Tests updated; 244 in the YouTube/transcript/chain slice pass.

### Already built this session (detection only — the alarm, not the fix)
- New columns `youtube_videos.duration_sec` (true length, fetched via `fetch_youtube_duration` → Invidious) and `observed_duration_sec` (what Gemini saw). After each read the bot stores both and logs a `PARTIAL READ` warning when Gemini saw < `youtube.gemini.partial_read_coverage_floor` (0.8) of the true length. Tested (544 tests pass); **goes live on next engine restart** (migration adds the columns then). It flags the problem; it does not yet read the rest of the video.
- Also fixed: the analysis-run bookkeeping row now closes to `status='complete'` instead of being stuck at `running`.

### Open questions to answer first in the fix session
- Does Gemini offset-chunking actually return the later parts of a long video? (probe before building)
- Exact daily capacity in *whole videos* and *total minutes* per key — measure under controlled conditions.
- Are the 2 keys independent-quota (separate projects) or shared? Free or paid?
- Cheapest path to 100% coverage: all-captions (Supadata $) vs Gemini-chunking (quota) vs fixing the IP block.

### Sources (quota web data, 2026-06-09)
- [Gemini API rate limits — Google AI for Developers](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API Free Tier 2026 guide — aifreeapi](https://www.aifreeapi.com/en/posts/gemini-api-free-tier-rate-limits)
- [Why more keys don't add quota — LaoZhang](https://blog.laozhang.ai/en/posts/gemini-api-free-tier)

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

---

### Session notes — 2026-05-28 (PARTIAL — discover run todo-autobatch)

**KEY DISCOVERY that reframes this TODO:** the visual chart data Gemini extracts was being **thrown away entirely**. `_build_evidence_bundle` never read `visual_evidence`; `EvidenceBundle`/`EvidenceSpan` had no field for it; there was NO DB table. So the "P2 add ~10 lines of response_schema" framing missed that nothing consumed the visual data at all. Capturing it is the real prerequisite and the real user value.

**SHIPPED this session (code in working tree, 77 tests pass, new table live):**
- `EvidenceBundle.visual_evidence: list[dict]` (models.py) — back-compat default `[]`.
- `_build_evidence_bundle` now reads `visual_evidence` and runs `_clean_visual_evidence`: dedup by `value` (keep first), drop `ts_sec` outside `[0, duration_sec]` (no-op when duration unknown), drop negatives (catches the year-as-timestamp `2024` bug), cap 50. **This is the going-forward phantom defense.**
- New additive table `youtube_visual_evidence` + `insert_youtube_visual_evidence()` (db.py); persisted in the orchestrator after spans.

**DEFERRED (not done — needs care, not in this session):**
1. **Narrator wiring (the part that makes the LLM actually SEE the numbers).** Stopped here deliberately: `visual_evidence` rows have NO ticker, and the `!all` consumer path is per-ticker (`get_youtube_evidence_for_ticker`). Feeding them to the alert AI needs a video→ticker attribution step (join via `youtube_evidence_spans`/`youtube_signals`, then decide which of a video's ~50 visual items belong to which ticker). Rushing a heuristic would attach the wrong chart numbers to the wrong ticker and HURT signal quality. **So the user-observable goal ("bot uses chart numbers in alerts") is NOT yet met — only "data is captured + stored."**
2. **response_schema + two-trip (truncation fix).** Coupled to an unmeasured ~2× token-cost decision (Priority 3) and untestable while Gemini video was 503-ing. The schema cap was proven to work in isolation (asked for 80, got 50). Build behind a config flag + measure before enabling.
3. **P5 phantom DB cleanup — DONE 2026-05-28 (user approved).** The TODO's suggested clauses were TOO BROAD (would delete real natural speech like "Microsoft is number one on my draft board" across 46 videos). Narrowed to literal planted artifacts only and ran:
   ```sql
   DELETE FROM youtube_evidence_spans
   WHERE quote LIKE '%400.15%' OR quote LIKE '%Number One Draft Pick: MSFT%';
   ```
   Result: **176 rows deleted** (13340→13164), 0 phantom rows remaining, 14 ambiguous natural-speech rows KEPT. Backup at `consensus.db.bak.pre-phantom-cleanup-2026-05-28` (untracked; safe to remove once soaked).
4. TODO's P1 commit hash is wrong: real prompt-fix commit is `6d20b67`, not `e7ae531`.

**Open question for user (#17 q1 answered):** vision model reported duration_sec=906 vs stated 10:15 — the dedup filter now drops out-of-range ts regardless, so this is defended going forward.

---

## NEXT SESSION — remaining #17 work (handoff, 2026-05-28)

Three things remain. **Don't start until a fresh session.** Self-contained brief below.

### Verified fact (so nobody re-litigates the architecture)
Gemini watches the ACTUAL video, not captions: call site `gemini_video_parser.py` ~line 695-704 sends `types.Part.from_uri(file_uri=youtube_url, mime_type="video/*")` with a `media_resolution` setting (frame detail). The single combined prompt `_EVIDENCE_PROMPT` (~line 28) asks for BOTH `visual_evidence` (on-screen numbers/labels not spoken) AND `spans` (spoken quotes) in ONE watch. There is a separate captions-only fallback (`parse_video_transcript`) that only fires if the video path fails. **Implication for the two-call idea:** both visual + spoken come from one watch, so splitting into two calls = Gemini watches the full ~182k-token video TWICE = ~2× cost + latency. The schema-cap mechanism is already proven (asked for 80 items, got exactly 50 via `response_schema` + `response_mime_type="application/json"` on SDK google-genai 1.73.1).

### TASK A (DECIDED — BUILD IT) — two-call upgrade for high-quality transcription
User decision 2026-05-28: **implement the two-call split. Quality matters; the cheaper "trim spoken quotes" middle option is REJECTED** — without high-quality transcription the info isn't useful, so accept the ~2× cost.
- Trip A: vision-only prompt → `generate_content` WITH the visual schema cap (max 50) + `response_mime_type="application/json"` → parse `visual_evidence`.
- Trip B: spoken-only prompt → `generate_content` WITHOUT schema (free-form) → parse `spans` + `segments` + `duration_sec`.
- Merge into one `EvidenceBundle`. Sum token accounting across both trips (currently records one response). Partial-result policy if one trip fails.
- Build `_build_generation_config(media_resolution_cfg, response_schema=None, response_mime_type=None)` + the minimal `_VISUAL_EVIDENCE_SCHEMA` (only the visual_evidence array; NO enums/nesting/ordering — complex schemas get rejected "too many states for serving").
- Persist visual_evidence is ALREADY wired (this session): `_clean_visual_evidence` + `youtube_visual_evidence` table + insert at ~line 552.

### TASK B (investigate FIRST — likely blocks Task A's live test) — why do Gemini video calls time out / 503?
User is confident it is **NOT Google's servers down** (checked Google's status page — green, repeatedly) every time a "Gemini down" claim was made. **Assume the cause is on OUR side and diagnose it.** Prime suspects, in order:
1. **Free-tier quota** — per-minute (RPM) and per-day (RPD) limits. Video calls are ~182k input tokens EACH; we fire many in a window (probe ran 6 back-to-back; the live engine youtube poll loop; the daily eval cron — see TODO #3). A `503 "experiencing high demand"` can be a disguised throttle, and TODO #3 already logged explicit `429 RESOURCE_EXHAUSTED` on Apr 23.
2. **Shared project quota across keys** — `GEMINI_API_KEY` + `GEMINI_API_KEY2` may belong to the same Google project → "rotating keys" buys nothing. Verify they're separate projects.
3. **Our timeout** — `youtube.gemini.timeout_sec=240`; a slow-but-not-dead ingest could be hitting our limit, not Google's.
4. **Payload/config** — media_resolution tier, request size.
**STEP 0 (gating) — CLASSIFY WHICH CAP IS BEING HIT BEFORE picking any fix (user 2026-05-28). The fix depends entirely on which one, and they can co-occur.** Tell them apart by the failure SIGNATURE:
- **Output-token cap (~65k):** call SUCCEEDS (HTTP 200) but the returned JSON is TRUNCATED / `finish_reason == MAX_TOKENS`. Content comes back, just cut off mid-structure. → FIX = two-call split (Task A). **Do NOT reduce fps for this — fps cuts INPUT, not output; it changes nothing here.** (User explicit: if it's ONLY the output cap, lowering fps makes no sense.)
- **Daily-TOKEN budget / rate quota (RPM/RPD):** call FAILS with `429 RESOURCE_EXHAUSTED` (or a `503` masking it); NO content returned; quota/limit details in the error body. → FIX = fewer + more-spaced requests; `fps`↓0.5 helps ONLY the daily-TOKEN variant (not the request-count variant).
- **Latency / timeout:** call hangs and our 240s client timeout aborts it (`DEADLINE_EXCEEDED` / client-side timeout), distinct from a quota rejection. → FIX = larger timeout / lighter payload / retry-with-backoff.
**How to run STEP 0:** capture the EXACT failure for a real failing call — HTTP code, `finish_reason`, whether ANY content came back, and the full error body; count our Gemini video calls in the failing window vs the documented free-tier RPM/RPD for `gemini-2.5-flash-lite` video; confirm the two API keys aren't one shared project quota; and run a SINGLE isolated call (no concurrent engine/cron load) to see if it succeeds. Only after the cap is classified, pick the matching lever (output→two-call, daily-token→fps↓, request-rate→throttle, timeout→backoff). Lesson recorded in memory `comm-check-fail-2026-05-28-section-3` + `feedback_diagnose_before_blaming_providers`.
**Cross-link:** this is the SAME root issue as **TODO #3 (gemini-video-eval-assertions)** — that cron fails 2/7 daily for the same Gemini-video-call reason. Consider tackling A+B+#3 together.

**Ruled out — video time-chunking (don't chase it).** The SDK supports clipping (`types.VideoMetadata` has `start_offset`/`end_offset`/`fps`), but splitting a 10-min video into 5-min halves does NOT help and likely hurts: (a) we're nowhere near the single-request INPUT limit — a full video is ~182k tokens of the 1,048,576 window (~17%); (b) clipped segments are billed per-segment, so two halves ≈ same TOTAL tokens as one call (no daily-token savings); (c) it DOUBLES the request count → worse for the per-minute/day REQUEST quota, which is the leading suspect. Right lever for a rate/quota limit = FEWER, more-spaced requests (throttle, daily cap, backoff, verify the two keys aren't one shared project quota). Chunking would only be needed for videos > ~50 min (none of ours).

**`fps` lever — current value + recommendation.** We currently set `fps` NOWHERE (only `media_resolution: "auto"`), so Gemini uses its default **1 fps**. If the cap turns out to be a **daily-TOKEN** limit, drop to **~0.5 fps** (one frame every 2s): it ~halves input tokens per video with NO extra requests. Safe for this content — user note 2026-05-28: stock-video charts typically sit on screen **5–30s**, so at 0.5 fps a 5s chart still yields ~2–3 sampled frames and a 30s chart ~15; we'd only miss something flashed <2s, which is rare here. **Map the lever to the right cap:** `fps`↓ → fixes INPUT/daily-TOKEN cap (NOT the output cap); two-call split (Task A) → fixes the OUTPUT-token cap / truncation; fewer-spaced requests → fixes the REQUEST-rate (RPM/RPD) cap. Don't aim `fps` at a request-count or output problem — it won't help those.

### TASK C (needs a USER decision, then build) — show the chart numbers to the alert AI
The captured visual_evidence has NO ticker; the `!all` path is per-ticker. Attribution bridge VERIFIED to exist: `youtube_signals` table carries `video_id` + `ticker` + `conviction` + `mention_count` (+ `video_timestamp_sec`, `evidence_span_ids`). So: `youtube_visual_evidence.video_id` → `youtube_signals` (filter by ticker) → that video's visual numbers. `get_youtube_evidence_for_ticker()` (db.py:1912) currently reads `youtube_setups` + `youtube_levels` by ticker — wire visual_evidence into that read model + the narrator's `yt_evidence` block.
**USER DECISION NEEDED — attribution risk posture** (a video often covers several stocks; wrong attachment hurts alert quality):
- **Conservative** — attach a video's numbers to a ticker only if that video clearly centered on it (high conviction + top mention_count). Fewest wrong attachments.
- **Middle** — attach a video's numbers to its single top ticker.
- **Aggressive** — match each number to a ticker by proximity to that ticker's price (e.g. a 745.64 gamma line near SPY's price → SPY).
Recommended: build Conservative default, run `!all` on real tickers with recent video coverage, show before/after; user reviews output + picks final posture.

### Misc relevant info for #17
- P1 prompt-fix real commit is `6d20b67` (TODO body's `e7ae531` is wrong/stale).
- This session's capture/dedup/cleanup shipped in commit `52397e8`; P5 cleanup record in `9e0fbff`/`3048dbf`.
- Sequence recommendation: **B (diagnose Gemini failures) → A (two-call, now testable) → C (attribution + before/after).** A's live test on harness video `4mSyMr8PGLI` needs B resolved (or Gemini quota available) first.

---

### Session notes — 2026-05-29 (discover run todo-2-3-17)

**TASK B — DONE + SHIPPED + LIVE.** Ran isolated live Gemini video calls. The limit is identified:
- `gemini-2.5-flash-lite` (the prod video model) AND `gemini-2.5-flash` return **persistent 503 "high demand"** for video on our tier. `gemini-2.0-flash` is 429-quota'd. **`gemini-flash-latest` works reliably** (`finish_reason=STOP`, complete JSON).
- Free tier caps **~3-4 full videos/key/day** (429). `fps=0.5` cuts input **224,800→143,686 tokens** (~36%), no quality loss (42 spans + 25 visual on the eval video).
- **`finish_reason=STOP` always → NOT the output-token cap.** So **TASK A (two-call split) is SHELVED** — it was premised on an output cap that doesn't exist; it would only double the 503/429-prone calls. (Decision: do not build.)
- **Fix shipped (commits c6736c4 + reorder):** config `youtube.gemini.model` → `gemini-flash-latest`, add `fps: 0.5`, add `model_fallbacks`; parser attaches `VideoMetadata(fps)`, 503→model-fallback retry, captures `finish_reason`; **chain reordered so Gemini video is PRIMARY, captions the FALLBACK** (user chose "Free + 0.5fps + captions fallback"). Verified end-to-end via the production `_extract_evidence_single_pass` path. Engine restarted 2026-05-29 02:12 — live.

**TASK C — REMAINING (the last piece; also unblocks #3's A1/A2/A3).** Captured `visual_evidence` chart numbers are still NOT consumed into per-ticker alerts. Demoable now: video `2UUTK-lntus` has 47 visual rows in `youtube_visual_evidence`. Build per the codex-reviewed plan (`.claude/discover/todo-2-3-17/final-plan.md` §3d):
- Phase 1 (Conservative read-layer): new `get_youtube_visual_evidence_for_ticker(ticker, days)` join `youtube_visual_evidence.video_id → youtube_signals` top ticker; merge into `data['yt_visual_evidence']` in the aggregator ONLY (NOT the shared `get_youtube_evidence_for_ticker` at db.py:1912 — `cross_reference.py:233` hard-checks `=="setup"` and would drop new types); teach `_build_yt_evidence_snippets` (aggregator.py:595) to render visual rows or they're silently dropped before the LLM.
- Phase 2: kind-gated 10% price band (only `kind=='price'`) + exactly-one-in-band proximity fallback, in the aggregator (only layer with a live price).
- Phase 3 (optional): Gemini per-number nullable same-frame `ticker` tagging.
- DoD: a real `!all` on a video-covered ticker shows the chart number text in the synthesis prompt + alert.

#### Task C UPDATE — Phase 1 + Phase 2 SHIPPED 2026-05-29
- **Phase 1 (commit c608bfa):** `get_youtube_visual_evidence_for_ticker` (Conservative — a video's chart rows attach to the video's TOP-mentioned ticker only); aggregator parallel-fetch into `data['yt_visual_evidence']`; `_build_yt_visual_snippets` renders `chart shows <value>` → flows through the existing narrator path. Verified **live** via a real `!all USCI` in #chat (bot processed it; chart numbers reached the alert AI).
- **Phase 2 (commit fabe237):** `_visual_band_filter` — a `kind=='price'` row is kept only within `youtube.visual.proximity_band_pct` (0.10 = ±10%) of the ticker's live price; drops axis gridlines AND cross-ticker numbers; non-price rows pass through; no-live-price → keep all. Real-data: 44 gridline rows (0-73) → 0 kept for USCI (~$98). 5 unit tests.
- **Phase 3 (NOT built, optional):** Gemini per-number nullable same-frame `ticker` tagging. Only worth it if a real before/after shows Conservative+band leaving too many useful numbers unattached (e.g. multi-ticker videos where the band can't disambiguate two similar-priced stocks).
- **IMPORTANT scope note:** Task C feeds the `!all` NARRATOR (the AI thesis), NOT the `youtube_levels`/`setups`/`catalysts` classifier tables. So it does **NOT** fix TODO #3's A1-A3 (which read those tables). Those are a separate path — see #3 correction note.

---

## Update 2026-05-30 (run `all-levers-2026-05-29`) — B2 done, B3 built-flag-off

- **B2 (before/after chart-numbers demo):** done without spending Gemini quota — fresh chart-heavy videos already in the DB (e.g. `e2l8OJ-H1HM` DELL, `S3nZ5K1MMOQ` SPY) carry BOTH signal + visual rows, so `!all <ticker>` surfaces the Gemini-read numbers (WITH); old visual-only videos like `2UUTK-lntus` (47 rows, 0 signal) never surface (WITHOUT). Finding: multi-stock videos dump ALL on-screen numbers onto the top ticker — DELL absorbed other stocks' levels ($6.20/$10.91/$18.45), then the ±10% price-band filter dropped them → 0 usable levels. This is exactly the B3 trigger.
- **B3 (per-number ticker tagging):** BUILT, flag-gated OFF (`youtube.visual.per_number_ticker_tagging: false`, commit `7d77245`). Adds a nullable `ticker` column to `youtube_visual_evidence`; Gemini prompt addendum + parser capture only when on (null allowed → never guesses); two-tier attribution in `get_youtube_visual_evidence_for_ticker` (tagged → own ticker; untagged → pre-B3 top-ticker). Flag-off verified identical to before. To test: flip true + restart (costs Gemini re-processing). 4 new tests; independent verifier approved.

### Session notes — 2026-06-10 (chunked long-video reads SHIPPED + LIVE-VERIFIED)
- **Worked on:** the CRITICAL full-transcription goal. The decisive probe PASSED: Gemini
  `VideoMetadata` start/end offsets defeat the silent truncation (the 105-min evidence video
  `e_iCwe2yX14` returned genuine 60-65-min content from a 3600-3900s window). Built chunked
  reads: videos > 20 min split into 15-min windows (30s overlap, cap 6 windows = 90 min max),
  per-window Gemini calls, merged in real-video timestamp order. Critical live-found bug fixed:
  Gemini returns CLIP-relative timestamps — merge adds win_start to every span (without it all
  window-2 spans landed on window-1 times). Past-end timestamps clamped (also fixes the
  invented-70-min-stamp-on-a-55-min-video bug). ON by default (`youtube.gemini.chunked_long_videos:
  true`); short videos unaffected (1 call). Quota/budget abort keeps completed windows; the
  partial-read alarm verifies coverage. Live verify: 2-window run covered 2,620s vs the old
  1,121s ceiling, 28 spans across both windows. 245 YouTube-slice tests pass.
- **Decisions:** keys confirmed SEPARATE Google projects (independent quota — rotation gives real
  headroom; each free key caps at 250k input tokens/min). 6 Gemini calls spent on probe+verify.
- **Next:** the one open decision — videos LONGER than 90 min (cap 6 windows) still lose the tail
  (alarm fires). Options: raise chunk_max_windows (more quota per video), buy Supadata credits
  (full captions, no vision), or accept the 90-min ceiling. Also watch tonight's pipeline run:
  long videos should now log full(er) coverage instead of PARTIAL READ.

### Session notes — 2026-06-13 (discover run todo-sweep) — #17 verified WORKING live
- The CRITICAL full-transcription goal is **met**: chunked long-video reads (commit 9c8f889) verified working in production WITHOUT spending Gemini quota. Evidence: journalctl window logs show 3 recent long videos read across full-duration windows (e.g. 8Gk6rKuYCHA 1898s→3 windows; NPBxs8WS6Ek 1305s→2 windows), **zero PARTIAL READ warnings since 2026-06-10**, and span timestamps reach each video's tail (17 spans in the 1800-2100s bucket of the 31-min video). Bucket 4 (built/on/works).
- **Caveat for future health checks:** the DB `observed_duration_sec/duration_sec` ratio is **circular for chunked videos** (both set to the Invidious length) → always 1.0, proves nothing. Use absence-of-PARTIAL-READ + max-span-timestamp instead. (Future nicety: make observed_duration_sec record the max real-video span ts.)
- **Only gap:** videos >90 min (the 6-window cap). Zero exist in the DB. **Recommendation: accept the 90-min ceiling**; the alarm fires if one appears; raising the cap risks blowing a day's Gemini quota on one livestream. Revisit only if the alarm fires (cheapest fix then = route only the >90min tail to Supadata captions). Full notes: .claude/discover/todo-sweep-2026-06-13/research/youtube.md.
