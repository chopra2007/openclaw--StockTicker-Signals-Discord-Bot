# Session findings & fix plan — 2026-06-08 (part 2)

**Status:** DONE 2026-06-09 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-06-08

This file captures everything found in the 2026-06-08 follow-up research session (6 user
questions → deep multi-agent investigation, each finding adversarially re-checked, key facts
re-verified by hand). It is the input for the planning phase. **No code was written this
session** beyond a read-only vision-model benchmark the user explicitly requested.

## Two rules that govern this whole file

1. **Not done until the end goal is met in a LIVE test.** For every item below, "done" means the
   real user-visible behaviour was observed working end-to-end — not "code looks right," not
   "tests pass," not "service started." Each item has an explicit **Live test** line. (This is a
   direct response to the chart-vision miss last session, where vision was called "done" while it
   had never once read a real chart. See item F.)

2. **Two kinds of suggestion, and the Type-2 ones are NOT binding.**
   - **Type-1 (direction):** which way to take a feature/decision. The user decides.
   - **Type-2 (possible code approach):** a plausible way to build it, based on this session's
     research. **During planning, actively look for a better way first.** Only if no better
     approach is found do we fall back to the Type-2 suggestion here. Do not treat any Type-2
     note as a locked-in design — the door stays open for discovery during planning.

Overlaps with existing TODOs (do not duplicate): **#26** (Wolf hedged/stale calls), **#27**
(sanitize A/B then off), **#28** (smart-levels shadow soak). Items C and B below are adjacent to
those but distinct.

---

## A. Chart vision — make the bot actually read Wolf email charts

**End goal:** when a Wolf newsletter email arrives with chart screenshots, the bot reads each
chart and pulls the real price levels off it (support/resistance/target) into a clean structured
form it can post — e.g. "SMH chart: resistance 615, support 585." Right now it reads ZERO charts
and every Wolf thesis is text-only.

**What we found (verified):**
- Since the switch to the free OpenRouter vision chain, **not one chart has been read**. Vision
  only ever fired on June 8 and failed every time — both free models return "too many requests"
  (429), "bad gateway" (502), or empty. Budget is not the blocker now; the free models are.
- The pipeline itself is fine: `consensus_engine/analysis/wolf_vision.py` fetches the chart,
  sends it base64 to OpenRouter with a good extraction prompt, and `_validate()` already drops any
  level more than ±30% from a passed-in recent price (a real anti-garbage guard). The weak link is
  purely **which models** are in the chain.
- There are 7 free vision models and 163 vision-capable models total. Cheap paid vision models
  cost ~1¢/day at our volume — far under budget.

**USER DIRECTION (2026-06-08, locked):**
- **Do NOT lock in `nemotron-nano-12b-v2-vl:free` on the strength of 1 image this session.** That
  was a 4-call screen, not proof. It's a *candidate*, not the decision.
- **Stress-test EVERY free vision model against ONE FULL Wolf email** — i.e. ALL the chart images
  in a single email, fired as the real burst — to see whether it gets rate-limited after the first
  few images. The pass condition is: reads the whole email's charts without hitting 429/502. (A
  model that handles 1 image but dies on image #4 is a fail.)
- **Goal: find ~5 GOOD free vision models.** If we have 5 that survive a full email, we can spread
  the charts across them (rotate) so no single free model ever takes the whole burst — and then we
  **never spend a penny on paid models.** That's the preferred outcome.
- **Paid models: test only 1–2 images each, and spend NO MORE THAN 5¢ on any single model during
  the whole testing phase.** Paid is only the fallback if we can't assemble enough working free
  models.
- **Speed is NOT a factor.** Up to ~15 min to read all of one email's charts is fine. Goal = "as
  fast as possible WITHOUT tripping the rate limit," not "fast."
- **Hard cost ceiling: 10¢/DAY total** — and that day covers ALL ~3 Wolf emails/day combined, **not
  10¢ per email.** So every chart across all 3 emails in a day must total under 10¢ (free = $0,
  which is why a free-only pool is the goal).

**Type-1 (direction):** assemble a pool of free vision models that each survive a full-email burst;
rotate/distribute charts across the pool (and/or pace the reads) so none gets rate-limited; $0 cost.
Only fall back to a cheap-paid slot if fewer than ~5 free models pass — and keep the **whole day**
(all 3 emails) under 10¢.

**Type-2 (possible approach — check for better during planning):** (a) round-robin charts across
the working free models so each handles only a share of the burst; (b) AND/OR read sequentially
with a delay between each, backing off + retrying the SAME chart on a 429/502 (never drop it);
keep `_validate`'s ±30% price guard. The throttle could be fixed or adaptive (speed up while calls
succeed, slow on the first 429). *Open research for planning — DO NOT test this session: which free
models survive a full email? Is the free-tier limit per-minute / per-day / per-IP (decides whether
rotation across models even helps, since a per-IP limit would hit all of them)? How many charts
does a typical Wolf email actually contain (sets the burst size)? Should reads queue ACROSS emails
so two arriving together don't combine into one big burst? Only if <5 free models pass: is one
cheap-paid last-resort slot worth it, and which (kept under the 10¢/day-for-3-emails ceiling)?*

**Live test (when built — NOT this session):** feed a full email's worth of charts (≥5 at once)
through the paced free chain on the live engine and confirm **all** read correctly with **no
rate-limit failures** — that's the exact condition that breaks today. Then wait for a real incoming
Wolf email and confirm its #news post shows chart-derived levels (not text-only), with
`wolf_vision_calls` logging real successes over 1–2 days. **Done only when a full real email's
charts are all read without a single 429/502.**

---

## B. Fake/mock data sitting in the live database

**End goal:** the production database contains only real extracted data — no test/seed rows — and
nothing can silently write test data into it again.

**What we found (verified by hand):** the wrong "NVDA support $850" was **not** a transcription
error and **not** the AI inventing a number. It came from **5 fabricated "video" records**
(June 1–5, all StockedUp). The video IDs are real but the saved transcripts are mock fixtures —
clean one-fact-per-line text at perfectly round 60-second marks ("Nvidia is holding this critical
level at 850." / "AMD also saw a nice push up to 180."), one even citing "April 29" inside a June
video. None ran through the AI reader (zero input recorded; a real video logs ~420,000 units). They
appear once a day, June 1–5, at nearly the same time — a scheduled or repeated test that wrote to
the **live** DB by mistake. These 5 injected 17 levels; **6 are still active and brief-eligible**:
NVDA support 850 (×3), MSFT 415, SPY 500, TSLA 175.

**Type-1 (direction):** (1) remove the fake rows, (2) **find and stop the source** before deleting,
so we kill the cause not just the symptom. The daily June 1–5 cadence is the lead.

**Type-2 (possible approach — check for better during planning):** trace what wrote runs with
`chain_winner='gemini/v2'` AND `input_tokens IS NULL` (only 5 of 79 — the signature of these rows);
likely a demo/seed script or a test that pointed at `consensus.db` instead of a temp DB. Then
delete the 5 runs + their spans + their 17 levels. *Better-way to probe: is there a guard that
should refuse writes when running in a test/demo mode? Add one so prod DB can never take seeded
rows again. Decide in planning.*

**Live test:** after cleanup, query the DB to confirm the 5 runs / 17 levels are gone; read the
next #brief and confirm NVDA 850 (and the other 5) no longer appear; watch for several days and
confirm no new `input_tokens IS NULL` mock runs appear (source is truly stopped). **Done only when
the brief is clean AND no new fake rows have appeared for several days.**

---

## C. One shared "is this level sane right now?" check at display time

**End goal:** no price level that's wildly off the instrument's real current price ever reaches a
user — in the #brief, in `!all`, or in a #news confluence post. (Covers the $850 NVDA brief, the
URA 4,500, and the SMH 12,616 index-vs-ETF mixups.)

**What we found (verified):** the existing checks run in the wrong place. `!all` already builds its
levels FROM the live price and down-weights far-away ones (`all_command/levels.py`) — which is why
the bad numbers never showed in `!all`. But the **brief** (`alfred.py`), the **Wolf confluence**
render (`wolf_news.py`), and the **level-merge** (`wolf_theses.py`) import none of that and print
stored text levels blind. The one hard accept/reject check (`analysis/price_sanity.py`) runs only
when a YouTube level is first saved, and it has a **split-multiple loophole** (forgives 2×/3×/4×…)
— which is exactly how 850 = 4.07× of $208 slipped through.

**Type-1 (direction):** make ONE shared "is this level plausible for this ticker at today's price?"
check and apply it at the **last step before display** (and at save/merge as a second line),
anchored on the live price, with a **hard cutoff** (drop/hide anything more than ~3–4× above or
below the current price). Close the split-multiple loophole for display.

**Type-2 (possible approach — check for better during planning):** lift `!all`'s price-anchored
logic into a shared helper and call it from `alfred.py`, `wolf_news._levels_field`, and
`wolf_theses._merge_levels`; remove the split-factor tolerance from the display path. *Better-way
to probe: is a fixed ±X% band right, or should it scale with the instrument (a 5-min ETF vs a
weekly index)? Should it DROP or just FLAG-and-dim? Decide in planning.* Note: this also backstops
item B (any fake level that's off-price gets caught at display even if a row is missed).

**Live test:** run `!all` on NVDA/SMH/URA and trigger a #brief and a Wolf confluence post; confirm
no level more than the chosen band off the live price appears anywhere. Take a known-bad stored
level (e.g. a leftover index value on an ETF) and confirm it is now hidden in all three surfaces.
**Done only when a deliberately-off level is provably suppressed in brief + !all + confluence.**

---

## D. Discord gateway outage — permanent fix + self-heal + notify

**End goal:** if the bot's live Discord connection ever goes down, it comes back **by itself**
within a few minutes — and if it genuinely can't, it **messages the user**. The user never has to
notice or fix it manually again.

**What we found (verified end-to-end):** a 3am scheduled update (`/root/scripts/update_plugins.sh`,
run as the admin/root account) rewrote the bot's settings file as root-only, so the bot (a
different account) couldn't read it and quit with error 78. A restart rule
(`RestartPreventExitStatus=78`) then told the system to stop retrying. The "alert the user" helper
(`/usr/local/bin/openclaw-notify`) is itself broken — it reads the system log first, isn't
allowed to, and dies before sending. The engine's health check never checks if the gateway is
alive. Result: silently dead 6 hours. Assets that already exist and work: a Discord **webhook**
that posts without the gateway, and `ci-monitor` (a root task that runs every 5 min — the exact
template a self-healer should copy). **Verified caveat:** do NOT blanket-reset ownership of the
whole `~/.openclaw` folder — ~9,600 admin-owned files live there harmlessly, including the live
database; target the settings file only.

**Type-1 (direction):** three layers, all of them — (1) **Prevent:** put the settings file's
readability back after the 3am update and self-correct it on each gateway start. (2) **Auto-fix:**
a root task every ~2 min checks the bot's port (18789); if dead → fix ownership, restart, recheck.
(3) **Notify:** if auto-fix fails 3× in a row, post to the webhook; and fix the broken notify
helper. Also relax the "stop retrying" rule.

**Type-2 (possible approach — check for better during planning):** copy the `ci-monitor`
service+timer pattern for the watchdog; add an `ExecStartPre=+chown/chmod` of just `openclaw.json`
(+ `sources.json`) to the gateway unit; add the chown-back line to `update_plugins.sh`; fix
`openclaw-notify` by either adding the bot user to the `systemd-journal` group or making its log
read non-fatal. *Better-way to probe: confirm which Discord channel the webhook posts to (it's the
"ClaudeCode" webhook) and point it at a channel the user watches; decide watchdog cadence
(2 vs 3 min) and retry budget in planning.*

**Live test:** safely simulate the failure (make the settings file root-only, or stop the gateway)
and observe: the watchdog detects within ~2–3 min, runs the fix, the gateway returns, AND the
bot answers a real `!help` / mention afterward. Then force 3 consecutive failures and confirm a
real alert message lands in the user's channel. **Done only when a simulated outage self-recovers
AND an unrecoverable one produces a real alert — both observed live.**

---

## E. TweetShift source links in #news confluence posts

**End goal:** when a #news confluence post cites a Twitter source, "Twitter: URA" is a **clickable
link** to the exact TweetShift message in the #twitter channel — the same link the bot already
shows under "Source" in #chat tweet alerts — so the user can read that source's actual sentiment.

**What we found (verified):** the bot already builds this exact link in #chat
(`discord_tweetshift.py:350` → `discord.py:311`, format
`https://discord.com/channels/{server}/{channel}/{message}`), and YouTube confluence sources in
#news are already clickable the same way. The link is **thrown away** when a tweet is saved
(`main.py:1126`) — only ticker, analyst handle, and text are kept; there's no column for the
message link, so confluence never sees it. So the renderer is proven; only the data plumbing is
missing. **Open decision:** a confluence post sums up many tweets over 21 days (NVDA had 133 in the
window) — so "the source tweet" isn't one thing; we must pick which to link.

**Type-1 (direction):** add the link, mirroring the YouTube pattern; first decide which message a
multi-tweet confluence should point to (newest? up to 3 samples, like YouTube already shows?).

**Type-2 (possible approach — check for better during planning):** add a message-link column to
`signal_events`, populate it from `discord_source_link` at `insert_signal`, SELECT it in
`get_confluence_stances` for twitter, carry it on `SourceVote` like `sample_video_ids`, render it
in `wolf_news._label` like the YouTube branch. ~5 small edits + one DB column. *Better-way to
probe: do the same for the Options source? Is storing one representative link per ticker enough, or
up to 3? Decide in planning.*

**Live test:** trigger a Twitter-source confluence post in #news, click the link, and confirm it
opens the correct TweetShift message in #twitter (cross-check against the same tweet's #chat
"Source" link). **Done only when a real #news Twitter link opens the right message.**

---

## F. Structural prevention of false "done" claims (process fix)

**End goal:** a feature physically cannot be marked "live/done" unless there's real evidence it
meets its goal — enforced by the machine, not by me remembering a rule. (Root cause of the vision
miss: last session I checked "are the models reachable" instead of "did a real chart produce
levels," and called it done.)

**What we found:** the rule already exists in CLAUDE.md and memory and was followed in spirit but
bypassed under a cheap proxy check. More words in those files won't fix it — it has to be
mechanical.

**Type-1 (direction):** add enforcement, not directives. Best combo: (a) a **real-output smoke
test per feature** wired into the close gate (for vision: feed one real chart, assert ≥1 level
out — it would have failed last session and blocked the "done" claim), and (b) a **flag-flip-needs-
proof hook** (a commit that flips a `*.enabled` flag OFF→ON must reference a real-output artifact,
or the push is blocked).

**Type-2 (possible approach — check for better during planning):** extend `scripts/pre-push` and
the session-close gate to check (a) and (b); store go-live evidence as a small file per feature.
*Better-way to probe: is a smoke test per feature too heavy to maintain? Could a single "show the
artifact" checklist enforced at close be enough? Decide in planning.*

**Live test:** deliberately try to flip a feature flag ON with no evidence and confirm the push is
blocked; make the vision smoke test run when vision returns zero levels and confirm it fails the
gate. **Done only when a no-evidence go-live is actually blocked.**

---

## G. YouTube video transcription — bursts blow the free Gemini quota (NEW, found 2026-06-08)

**End goal:** when a batch of new YouTube videos comes in, they all get transcribed instead of a
wave of "All ingest methods failed" alerts — the bot paces them to stay inside the free Gemini
quota and retries the leftovers sensibly. (This is the **YouTube video → transcript** pipeline via
Gemini, a DIFFERENT pipeline from the Wolf chart-image reader in item A — but the SAME class of
bug: a burst overwhelms a free quota.)

**What we found (verified from the live log, 2026-06-08):** the user spotted 11 back-to-back
"All ingest methods failed — Gemini timeout + Groq Whisper terminal failure" alerts in #chat
(17:32–17:34 UTC). In total **42 such failure alerts fired that day**, in bursts (10:14–10:16,
10:21–10:22, 10:32–10:34, then a slow retry trickle every ~10 min). Root cause chain:
- Video transcription sends the **whole video** to Gemini (~144k input tokens at fps=0.5).
- Gemini **free tier allows 250,000 input tokens per minute per key**; with 2 keys that's only
  ~3 videos/minute. The exact error: `429 RESOURCE_EXHAUSTED … free_tier_input_token_count,
  limit: 250000 … Please retry in ~54s`.
- The poll/retry batch fired **far more than 3 videos/minute** at once → both keys hit the 429 and
  went into ~40–54s cooldown → every remaining video in the burst found `no_available_key tried=0`
  and fell straight through to the fallbacks.
- **The fallback chain is also down:** Supadata "rate/plan-limited", yt-dlp gets YouTube's own 429
  / "Sign in to confirm you're not a bot" (the known Hetzner VPS IP-block), Groq Whisper terminal.
  So nothing catches the video → "All ingest methods failed."
- The retry feature then **re-sent the batch as another burst** (the 10:32–10:34 wave = the alerts
  the user saw) and it failed again the same way; a few succeeded later (e.g. y7CO1rM4z2g at 10:44)
  once a per-minute window reopened.

So the user's hypothesis is **right in spirit** — it IS a burst overwhelming a limit — but the
precise limit is the **Gemini free-tier token-per-minute quota**, not request-rate, and the safety
nets are all rate-limited/IP-blocked too.

**USER DIRECTION (2026-06-08, locked):**
- **Speed is NOT a priority for video transcription — AT ALL.** The only priority is that the video
  actually gets transcribed properly. Waiting is fine.
- **Pace at ~1 video/MINUTE, not ~3** — the ~3/min figure is where it *starts* failing, so go to
  ~1/min for a safety margin (≈3×). Better to be slow than to fail.
- **Videos must NOT fail and get nothing.** A video that can't be done right now must be retried
  later until it succeeds — never permanently abandoned. (Check the current retry cap:
  `youtube.max_retries=5` may give up too early under this "never lose a video" rule; revisit so a
  video keeps getting retried, just paced.)
- **Durable, resumable, multi-DAY queue.** When the daily Gemini quota is hit, the videos not yet
  transcribed must **carry over to the next day and resume** — then the next day, and the next —
  until ALL of them are done. The backlog persists across days; the daily quota reset just lets it
  pick up where it left off.
- **A video is "done" ONLY when FULLY transcribed.** A half-transcribed video is useless — never
  mark a video complete unless its whole transcript was captured. *(Note: today each video is read
  in ONE Gemini call — whole video at once — so it's already all-or-nothing: it either fully
  completes and is saved, or fails and saves nothing. So "resume where it left off" applies at the
  QUEUE level [which videos still need doing], not inside a single video. Preserve this all-or-
  nothing-per-video rule so a partial read can never be saved as if complete. Within-video chunked
  resume is NOT needed unless a single video ever can't fit one call.)*
- **Don't let videos pile up.** The point of the carry-over is to CLEAR the backlog, not to grow an
  endless list. So daily transcription throughput must keep up with how many new videos arrive each
  day. If inflow chronically exceeds the free-tier daily capacity, the pile grows forever no matter
  how good the carry-over is → that's a capacity problem (more Gemini keys / a small paid tier),
  see the open question below.

**Type-1 (direction):** pace the video queue to ~1 video/minute so it stays comfortably under the
free Gemini budget; on a 429, wait the suggested "retry in N s"; and keep retrying a failed video
on later cycles until it transcribes (don't drop it at 5 tries if it still hasn't succeeded). Speed
doesn't matter — completeness does. Same burst-class problem as item A — consider ONE shared "pace
the burst" mechanism serving both the chart-vision and video-transcription pipelines.

**Type-2 (possible approach — check for better during planning):** add a durable throttle/queue in
the youtube scanner that submits at most ~1 video/minute to Gemini, sleeps the suggested retry-in
seconds on a 429, and — crucially — **persists the not-yet-done list across days**: when the daily
quota is exhausted, the remaining videos stay queued (status stays "needs transcription," NOT a
terminal failure) and the next day's run picks them up first. A video flips to "done" only on a
full successful pass. *Open research for planning — DO NOT test this session: what's the real daily
video volume / burst size? Is there a DAILY Gemini cap (vs just per-minute), and does our daily
inflow fit under it at 1/min — i.e. does the backlog actually shrink, or would it grow forever
(→ need more keys / a small paid tier)? How should "carry over, never give up" coexist with the
current `max_retries=5` (which would abandon a video) — likely: distinguish "quota-blocked, retry
forever" from "genuinely un-transcribable, e.g. no captions, give up after N")? Given the fallbacks
are unreliable (yt-dlp IP-blocked, Supadata limited, Groq terminal), is more Gemini capacity the
real fix? Should video reads and Wolf-chart reads share one global pacer?*

**Live test (when built — NOT this session):** two checks. (1) Single-day: a real batch drains
slowly (~1/min) with NO cluster of "All ingest methods failed" alerts. (2) Multi-day carry-over:
when the daily quota is hit with videos still pending, confirm those videos are NOT marked
terminally failed — they carry to the next day and eventually ALL get fully transcribed over
successive days (check the DB: the pending list shrinks to zero across days, and no video sits
`failed` with spans=0 long-term). Speed doesn't count; completeness does. **Done only when a
backlog that spans a quota reset is fully cleared over multiple days with every video transcribed
and none lost.**

---

## Suggested priority order

1. **D — gateway** (live, can silently drop the whole bot), **B — fake data** (live, wrong numbers
   in the brief right now), and **G — YouTube burst quota** (live, whole batches of videos failing
   and getting lost today). All three are active production damage.
2. **C — shared level sanity** (backstops B and fixes the brief/URA/SMH class of bug).
3. **A — chart vision** (restores a whole data source; benchmark below makes this ready). A and G
   are the same burst-class problem — likely built together / share one pacer.
4. **E — TweetShift links** (quality-of-life, low risk).
5. **F — false-done prevention** (process; do alongside the first build so it guards the rest).

---

## Vision benchmark (live test of candidate models)

OpenRouter has 163 vision-capable models right now; the bot's chart-reader currently uses only 2
free ones, and both are failing (rate-limits and server errors), so it reads nothing. Below are
live results from running the **real** chart-reading prompt against **real Wolf charts** (CAT daily
and URA 5-min), measuring success rate, speed, cost per chart, and accuracy vs the known chart.

Budget: **hard ceiling 10¢/DAY across all ~3 Wolf emails combined** (user, 2026-06-08) — not per
email. The direction is a **free-only pool** (~5 free models that survive a full email, rotated so
none gets rate-limited → $0). Paid is only a fallback if <5 free models pass. Speed is NOT a factor
(≤15 min/email is fine). **This benchmark is a CANDIDATE SCREEN, not the final test** — the real
test (item A) stress-tests every free model against one full email; the table below just narrows
the field and provides a paid fallback shelf.

**Test setup (this screen — too light to decide on):** each model got the real chart-reading
prompt + 2 real Wolf charts (CAT daily, URA 5-min), 2 rounds each = only 4 calls/model. That is
enough to see *if a model can read a chart at all*, but NOT enough to judge burst reliability — a
model can pass 4 calls and still rate-limit on image #4 of a real email. So treat "Works 100%" here
as "can read a chart," not "is reliable." Cost is from the API's actual token usage.

### Models that worked (ranked: reliability → accuracy → speed)

| # | Model | Free? | Works | Speed | ¢/day @20 | What it pulled from the CAT chart |
|---|-------|-------|-------|-------|-----------|-----------------------------------|
| 1 | **google/gemini-2.5-flash-lite** | paid | 100% | 2.6s | 0.62¢ | **Richest read** — 900 target, 889 price cluster, 750/690 moving-avg supports, 590 base |
| 2 | **meta-llama/llama-4-scout** | paid | 100% | 2.1s | 0.44¢ | 889.49 resistance, 850.80 support (day's low), named the 50-MA — fast + clean |
| 3 | **qwen/qwen3-vl-8b-instruct** | paid | 100% | 2.2s | 0.33¢ | 889.49 / 889.10 — correct but minimal (current price only) |
| 4 | **mistralai/mistral-small-3.2-24b** | paid | 100% | 3.5s | 0.27¢ | 889.49, 850, 790 — solid support reads |
| 5 | **openai/gpt-4.1-nano** | paid | 100% | 2.4s | 0.50¢ | correct instrument/levels, fast |
| 6 | google/gemma-3-27b-it | paid | 100% | 7.2s | 0.14¢ | rich read (894/854 day H/L, 750/690/630 MAs) but the **slowest** of the good ones |
| 7 | qwen/qwen3-vl-32b-instruct | paid | 100% | 5.3s | 0.46¢ | correct, richer than the 8b |
| 8 | meta-llama/llama-4-maverick | paid | 100% | 6.6s | 0.70¢ | correct |
| 9 | qwen/qwen2.5-vl-72b-instruct | paid | 100% | 7.1s | 0.84¢ | correct |
| 10 | qwen/qwen3-vl-235b-a22b-instruct | paid | 100% | 8.5s | 0.75¢ | correct (flagship VLM) |
| 11 | **nvidia/nemotron-nano-12b-v2-vl** | **free** | 100% | 11.9s | **0¢** | 889.49 / 850 — correct but **slow + rate-limits under burst** |
| 12 | minimax/minimax-01 | paid | 100% | 9.1s | 3.14¢ | correct but slower/pricier |
| 13 | google/gemma-4-31b-it | paid | 100% | 11.5s | 0.26¢ | correct but slow |
| — | amazon/nova-lite-v1 | paid | 75% | 4.1s | 0.44¢ | correct when it answered (one miss) |
| — | qwen/qwen3-vl-30b-a3b-instruct | paid | 75% | 4.8s | 0.61¢ | correct when it answered |
| — | openai/gpt-4o-mini | paid | 100% | 4.0s | ~6–8¢ | correct but by far the **priciest** (near the 10¢/day ceiling) — pointless vs a free model |

### Models that failed every call (don't use)

- **Free that errored in THIS light screen:** google/gemma-4-31b-it:free (25%),
  gemma-4-26b-a4b:free, moonshotai/kimi-k2.6:free, nex-n2-pro:free,
  nemotron-3-nano-omni-30b:free, openrouter/free — all returned provider/rate-limit errors.
  **IMPORTANT: do NOT permanently write these off.** These were 4 light calls; the errors look
  like transient rate-limits/provider hiccups. Per user direction, every free model gets a proper
  **full-email stress test** before being kept or dropped (see item A) — some of these may pass
  when paced, and we need ~5 working free models.
- **Paid that errored in this harness:** openai/gpt-5-nano, bytedance-seed/seed-1.6-flash (likely
  need different params; low priority since the goal is a free-only pool).

### Recommendation (per user direction 2026-06-08 — NOT locked to one model)

- **`nemotron-nano-12b-v2-vl:free` is a CANDIDATE, not the decision.** It passed a 4-call screen at
  100% — that is not proof it survives a full email's burst. It must pass the full-email stress
  test like every other free model.
- **The real test (when built, not this session): run EVERY free vision model against ONE full Wolf
  email** (all its chart images, fired as the real burst) and keep the ones that read the whole
  email without a 429/502. **Goal = ~5 working free models**, then rotate charts across them so no
  single model takes the whole burst → $0 spend, no rate limits.
- **Paid is only a fallback if fewer than ~5 free models pass.** When testing paid models, use just
  1–2 images each and **spend ≤5¢ per model** during the whole test phase. Any paid slot kept in
  production must keep the **whole day (all ~3 emails) under 10¢** — not 10¢/email.
- **Fallback shelf if paid is ever needed** (all read correctly in the screen; speed irrelevant):
  `gemini-2.5-flash-lite`, `llama-4-scout`, `qwen3-vl-8b`, `mistral-small-3.2`, `gemma-3-27b-it`.
- **Avoid:** gpt-4o-mini (priciest, ~6–8¢/day, no better than a free model).

**Live test for the chain (when built — NOT this session):** see item A — feed a full email's
worth of charts (≥5 at once) through the paced free chain and confirm all read with **zero**
429/502, then confirm a real incoming Wolf email's #news post carries chart-derived levels.

