# 9 of 14 YouTube channel feeds fail on every check

**Status:** DONE 2026-08-22
**Created:** 2026-08-19

**CURRENT STATUS (2026-08-22):** Done — the fix is proven live. Root cause is a
**nightly per-IP limit on YouTube's side**, not broken channels and not our blacklist
problem. Three fixes are in (retry the 404, stop hammering a block, poll less often),
and the block window of 2026-08-20 exercised all of them on real traffic: the breaker
tripped at 20:10 PDT ("7 of 14 feeds refused"), escalated its pause 30 → 60 → 120 min
across three streaks, held through the night, expired ~01:44 PDT, and the scanner was
back to processing new videos normally by 05:33 PDT (23 spans / 10 signals on one
video at 06:41). The fix is complete and proven.

## What is actually happening — evidence, not theory

Across the whole journal (2026-07-29 → 2026-08-20), **every single one of the 3,100 feed
404s landed between 19:00 and 23:59 PDT.** Exactly one fell outside that window. Zero in
the other nineteen hours of the day:

```
19:00 →   98      20:00 →  431      21:00 →  709
22:00 →  866      23:00 →  995      00:00 →    1
```

The block **starts at a drifting time** (19:47, 20:00, 20:32, 23:31 on four sample days)
but **always ends exactly at midnight Pacific**. A drifting start with a fixed midnight
end is a counter that fills up during the day and resets on Google's Pacific day boundary
— not a scheduled job, and not channels breaking.

Confirmed directly, outside the window: all 14 channel IDs returned HTTP 200 on 10
consecutive tries each (140/140), on both our own user-agent and a browser one. During a
probe inside the window the *same* channel returned 404, then 200, then 404 seconds apart.

**So a 404 here does not mean "channel deleted". It means "not right now".**

## The three things that made it worse than it had to be

1. **The retry gave up instantly on a 404.** `_fetch_channel_videos_rss_result` had
   `retryable = resp.status == 429 or resp.status >= 500`, so 404 was treated as fatal.
   The logs show `failed after 1 attempt(s)` for most channels while the alert claimed
   "still failed after 3 tries" — the alert text was wrong.
2. **We kept polling straight through the block.** ~22 cycles × 14 feeds over a 4-hour
   block ≈ 460 wasted requests, all of them spending against the very budget that was
   already exhausted.
3. **We polled faster than the feed can change.** YouTube's own response header says
   `cache-control: public, max-age=900`, and we polled every 600s — asking for identical
   cached bytes 1.5× per refresh, ~670 needless requests a day.

Also checked and ruled out: the feed offers **no ETag and no Last-Modified**, so
conditional requests (`If-None-Match` / `If-Modified-Since`) are impossible — both return
a full 200. The 5-second pacing added on 2026-08-09 was not the fix: failures dropped for
one day, then returned to ~250/day.

## What was changed (2026-08-20)

- `consensus_engine/scanners/youtube.py`
  - 404 is now retryable alongside 429/5xx, so a transient refusal recovers on retry.
  - **Circuit breaker:** when half the feeds in one cycle are refused, the rest of the
    cycle is abandoned and feed polling pauses — 30 min, doubling per consecutive blocked
    cycle, capped at 2 h — and **resets to zero on any clean cycle**.
  - The stored-video backlog now still drains while feeds are blocked (it reads through
    Gemini/Supadata, not youtube.com, so it costs nothing against the budget). Previously
    an empty feed harvest returned early and stalled that too.
  - The #errors alert now reports the true number attempted and says, in plain words, that
    it clears itself at midnight PDT.
- `config/consensus.yaml` — `poll_interval_seconds` 600 → 900 (matches YouTube's own
  15-minute cache), plus `rss_block_ratio`, `rss_block_backoff_seconds`,
  `rss_block_backoff_max_seconds`.
- `tests/scanners/test_youtube_rss_block.py` — 5 new tests. `tests/test_youtube_scanner.py`
  — one assertion updated for the new alert wording.

Net effect on daily requests: ~2,100 → ~1,350 in normal running, and a 4-hour block now
costs ~4 probe cycles instead of ~22.

## Answers to the original open questions

- **Direct or via the two working methods?** Direct. The feed check is a plain HTTPS GET
  to `youtube.com/feeds/videos.xml`. It is a *different* path from the transcript
  blacklist, and it is not permanently blocked — only nightly.
- **Does a missed check lose a video?** **No — it delays it.** The feed returns the latest
  3 per channel and `has_video_been_processed` de-duplicates, so once the block clears at
  midnight the next cycle picks up anything posted during it. Real loss needs a channel to
  post 4+ videos inside one block window.

## What was still owed — now settled (2026-08-22)

One live confirmation that the breaker actually trips, pauses, and then recovers on real
traffic. **Confirmed** from the engine journal for the night of 2026-08-20 → 08-21:

```
20:10:03  7 of 14 feeds refused — abandoning cycle, pausing RSS for 30 min (streak 1)
20:41:20  7 of 11 feeds refused — abandoning cycle, pausing RSS for 60 min (streak 2)
21:43:05  7 of 12 feeds refused — abandoning cycle, pausing RSS for 120 min (streak 3)
01:29:40  RSS backoff active for another 896s — skipping feed poll   (last pause)
05:33:14  youtube: 1 new videos to process                            (recovered)
```

Also verified earlier: the normal (unblocked) path on the live engine, and all five
behaviours under test.

Note: no deferred systemd task for this check exists on the box today — the proof above
was read directly from the journal instead. If one was created on 08-20 it did not
survive, which matches the known stale-deferred-task trap.

## Files involved

- `consensus_engine/scanners/youtube.py` — feed scanner, retry, breaker, alert
- `config/consensus.yaml` — `youtube:` section
- `consensus_engine/alerts/ops_alert.py` — posts to #errors
