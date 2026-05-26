# Replay mentions/commands missed during gateway reconnects

**Status:** DONE 2026-05-22.

**Layperson:** When the engine restarts (or its Discord WebSocket drops and reconnects with a fresh `IDENTIFY`), any `!` commands or `@<bot>` mentions that arrived in the disconnect window are silently lost — Discord gateway is push-only and does not replay missed events for a new session. The user sees their message in the channel, but the bot never reacts.

**Concrete repro:** `sudo systemctl restart consensus-engine.service` and within ~22s post a mention via the ClaudeCode webhook. The message lands in #chat, the gateway becomes READY a few seconds later, but no `Mention →` log line appears for it. Hit during the 2026-05-18 steering-template fix verification — first retest mention was eaten by the reconnect gap, had to be resent.

**Why it matters:** Any time the engine restarts (deploys, code pushes, OOM, weekend pause flips), in-flight user requests vanish without acknowledgement. Hard for the user to tell apart from "the bot is broken." Also masks real regressions during deploy-verify loops.

## Proposed approach

1. On every Gateway READY (especially fresh `IDENTIFY` after an invalid session — see `discord_tweetshift.py` around the existing `Reconnecting to Discord Gateway in 120s` log), fetch the last N messages from #chat + #commands + #briefing via REST and replay any `!`-commands or `@<bot_id>`-mentions whose `id` is newer than the highest already-processed message id for that channel.
2. Persist `last_processed_message_id` per channel in the DB (`engine_state` table or similar) so the lookback window is bounded and crash-safe across restarts.
3. Dedupe by message id so the same mention isn't double-fired if the gateway eventually delivers it via push too.
4. Cap the replay window (e.g. 10 minutes / 50 messages per channel) so the bot doesn't try to replay a multi-hour outage as a torrent of belated replies.

## Acceptance

- Restart the engine mid-conversation; the user can send a `!ask` or `@<bot>` during the ~20s reconnect; the bot replies within ~30s of gateway-ready instead of going silent.
- Restarting after an hour-long outage doesn't flood the channel — only messages inside the configured replay window get processed.

**Discovered:** 2026-05-18 during the steering-template fix verification; see commit 6bc150e on master.
