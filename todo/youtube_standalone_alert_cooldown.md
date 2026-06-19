# Stop the same stock double-alerting from different YouTube videos

**Status:** RESOLVED — won't build (2026-06-18)
**Created:** 2026-06-18

> **Resolution (2026-06-18):** User confirmed the same-ticker-across-different-videos double-post is acceptable ("yes that's fine") — it reads as two YouTubers independently confirming a ticker, not spam. No cooldown to be built. Reopen only if the user later reports it as noisy.

## Goal
Optional polish on the YouTube standalone (🎬 "a YouTuber likes $STOCK") alert. Right now, if two *different* videos picked up in the same 10-minute poll both make a medium-or-stronger call on the same ticker, each fires its own alert for that ticker. Add a per-ticker cooldown so the same ticker can't post twice in a short window.

## Why this is only "optional / watch first"
- It is NOT a new bug — it existed before, when the gate was HIGH-conviction-only. Widening the gate to `medium` (commit 2b45be6, 2026-06-18) just makes a same-ticker double-post a bit more likely.
- It is bounded: the same *video* can never re-fire (guarded by `has_video_been_processed`). A repeat only happens when a genuinely new video also mentions the ticker — which is arguably *more* signal (two independent YouTubers), not spam.
- The user explicitly accepted the new volume band (~6/week → ~19/week). Don't suppress alerts unless live use shows it's actually noisy.

## Trigger to actually build it
Watch the live #alerts channel for the first week or two after 2026-06-18. If the same ticker visibly double/triple-posts within a single poll cycle and it feels spammy, build the cooldown.

## What worked / current state
- Standalone gate: `consensus_engine/scanners/youtube.py` `_send_two_stage_alerts` (~line 607). Dedup today is only the in-call `sent: set[str]` — scoped to ONE video's alert batch, so it can't dedup across videos.
- The 🎯 level alerts already have the pattern to copy: `db.was_level_recently_alerted()` + `db.record_level_alert()` in `consensus_engine/db.py`, with a cooldown check.

## Possible next steps (priority-ordered)
1. Mirror the level-alert cooldown: add `youtube_standalone_alerts` table (ticker + alerted_at) with `was_standalone_recently_alerted(ticker, cooldown)` + `record_standalone_alert(ticker)`; gate the 🎬 send on it. Make cooldown configurable (`youtube.alerts.standalone_cooldown_hours`, default ~6–24h).
2. Add a test mirroring the level-alert cooldown tests.

## Files involved
- `consensus_engine/scanners/youtube.py` (gate + send)
- `consensus_engine/db.py` (new cooldown helpers + table)
- `config/consensus.yaml` (`youtube.alerts.standalone_cooldown_hours`)

## Open questions
- Is a same-ticker repeat from a *different* channel actually undesirable, or is it useful confirmation? If useful, scope the cooldown per (channel, ticker) instead of per ticker.
