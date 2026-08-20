# 9 of 14 YouTube channel feeds fail on every check

**Status:** OPEN
**Created:** 2026-08-19

**CURRENT STATUS (2026-08-19):** Noticed, not investigated. The #errors channel posted
"🔴 YouTube feed access — 9 of 14 channel feeds still failed after 3 tries" at 20:01 PDT
on 2026-08-19, and an earlier one that recovered by itself at 00:06 the same day. Nobody
has looked into why. Surfaced while building #88's guardrails; out of scope for that
session, so it is parked here rather than dropped.

## What is happening

The bot checks 14 YouTube channels for new videos every 10 minutes. On the 2026-08-19
evening check, 9 of the 14 failed three times in a row and the bot posted an outage alert
saying it may miss new videos until the next check. One earlier instance the same day
cleared on its own after 4.3 hours, which suggests something intermittent rather than a
permanent block — but "it fixed itself" is not a diagnosis.

## What we already know that may explain it

- This server's IP address is blacklisted by YouTube. Only two ways of reading videos
  still work from here: Gemini and Supadata. (Memory: `youtube_ip_blacklist_dead_methods`.)
- The failure counts the **feed** — the list of new videos per channel — not the
  transcript step, so it may be a different path from the blacklist problem above.

## Next steps, in order

1. Read the alert's own code to find which call is failing and what error it returns —
   do not guess from the message text.
2. Check whether the same 9 channels fail every time or the set moves around. A fixed set
   points at those channels; a moving set points at rate limiting.
3. If it is rate limiting, space the checks out or stagger the channels.

## Files involved

- `consensus_engine/scanners/` — the YouTube feed scanner and its retry/alert path
- `/root/.openclaw/sources.json` — the list of 14 channels
- `consensus_engine/alerts/ops_alert.py` — what posted the alert to #errors

## Open questions

- Is the 14-channel feed check hitting YouTube directly, or through one of the two
  methods that still work from this IP?
- Does a missed feed check actually lose a video, or does the next successful check pick
  it up? The alert says "may miss new videos", which is not the same as proven loss.
