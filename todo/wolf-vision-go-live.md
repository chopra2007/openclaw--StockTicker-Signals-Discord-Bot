# Wolf chart-vision — built, awaiting go-live

**Status:** OPEN
**Created:** 2026-06-09

The Wolf chart-reader (item A of the deep-dive-2026-06-08 run) is **built and the mechanism is
proven live**, but its master flag `wolf.vision.enabled` is **OFF** because the free vision
models can't yet read a full 5-chart email cleanly. This is a built-but-off feature.

## What works (proven live this session)
- New paced, rotating, status-aware chain: `vision_completion` (returns HTTP status), retry
  classification via `burst_retry`, rotate-on-429 / backoff-on-5xx / give-up-on-4xx, per-chart
  wall-clock budget + attempt ceiling, never-drop-on-transient.
- Against a REAL Wolf email chart (`/NQ` 5-min), `nvidia/nemotron-nano-12b-v2-vl:free` READ it
  (instrument + 1 level). `wolf_vision_calls_log` captured the 200-ok read plus the 502/429
  rotations — failure visibility now exists (was success-only counter before).
- The dead ±30% guard is armed (resolves instrument → live quote → validates).
- Chart loop is gated on `wolf.vision.enabled`, paced (`wolf.vision.pace_seconds`), and
  serialized by a process lock. Committed in a9d21d2.

## What didn't work (why the flag is OFF)
- The live test bar is "a PAST Wolf email's ≥5 charts ALL read with ZERO 429/502." Right now
  ALL 5 free vision models OpenRouter serves (nemotron-nano-12b-v2-vl, gemma-4-31b-it,
  gemma-4-26b-a4b-it, kimi-k2.6, nex-n2-pro) are returning 429 (rate limit) or 502 (provider
  down). A 5-chart burst only got ~1/2 reads. (My own rapid probing inflated the 429s, but the
  502s are provider-side and real.)

## How to turn it on
1. Confirm the free pool is healthy: run a ≥5-chart past Wolf email through `wolf_vision.read_chart`
   (see the live-test script pattern in the execution log) and confirm ALL read with zero 429/502.
   Production pacing (≤5 charts/email, 8s apart, few emails/day) is far gentler than a probe loop,
   so it may pass even when a rapid probe doesn't.
2. If the free pool still can't sustain a clean burst: set `wolf.vision.paid_fallback_model` to a
   cheap paid OpenRouter vision model (user-locked ≤10¢/day) and wire it as the last pool entry.
3. Flip `config/consensus.yaml` `wolf.vision.enabled: true`, restart `consensus-engine`.
   The item-F gate requires a go-live evidence file for this flag (the ≥1-level smoke read).

## Files
- `models/openrouter_client.py` (vision_completion)
- `consensus_engine/analysis/wolf_vision.py` (chain, guard, logging)
- `consensus_engine/analysis/wolf_email_parser.py` (gate, pacing, lock)
- `consensus_engine/db.py` (wolf_vision_calls_log + log_wolf_vision_call)
- `config/consensus.yaml` `wolf.vision.*`

## Open question
- Are the 429s mostly our per-minute exhaustion (recoverable by pacing) or a hard daily cap on
  the free vision tier? Watch `wolf_vision_calls_log.retry_class` over a day with the flag ON in
  a shadow/manual run before trusting it for production.
