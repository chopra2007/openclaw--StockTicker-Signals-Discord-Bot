# Wolf chart-vision — LIVE on paid gemini-2.5-flash-lite

**Status:** DONE 2026-06-09
**Created:** 2026-06-09

The Wolf chart-reader (item A of the deep-dive-2026-06-08 run) is **LIVE**. After the free
OpenRouter vision models proved unreliable (they share OpenRouter's throttled free upstream —
NOT 4 providers failing, see diagnosis below), the user chose the paid path: read ALL Wolf
charts (per-email cap removed) with `google/gemini-2.5-flash-lite` only, no free models.
Proven live 10/10 charts, zero failures; ~0.03c/chart, ~1.8c/day. `wolf.vision.enabled: true`.

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

## Why the flag is OFF — ROOT CAUSE (corrected 2026-06-09, user challenged "4 providers can't all fail at once")
NOT four independent providers failing. The `:free` OpenRouter variants all draw from
**OpenRouter's shared free upstream credentials**, which are throttled (everyone using `:free`
competes for the same pool). The 429 raw message proves it verbatim:
> "google/gemma-4-31b-it:free is temporarily **rate-limited upstream**. ... or **add your own
>  key** to accumulate your rate limits" — provider Google AI Studio.
The 502s are the same shared-backend overload. Diagnostics that settle it:
- Account is NOT out of money: `/api/v1/key` shows limit $5/day, only $0.06 spent. Not a credit cap.
- The PAID route works instantly: `google/gemma-4-31b-it` (no :free) returned 200 (our request,
  image, auth all fine — only the FREE serving layer is throttled).
- **`google/gemini-2.5-flash-lite` (PAID) READ the chart cleanly: /NQ, 2 levels.** ~a fraction of
  a cent per chart.

## How to turn it on (two viable paths)
1. **Paid shelf (recommended, reliable):** set `wolf.vision.paid_fallback_model:
   "google/gemini-2.5-flash-lite"` and wire it as the final pool entry in
   `wolf_vision._call_vision_image` (after the free pool exhausts on QUOTA_BLOCKED). Cost at ≤5
   charts/email × few emails/day is well under the user-locked ≤10¢/day. PROVEN to read a real chart.
2. **BYOK (free, more setup):** add our own Google AI Studio key to OpenRouter integrations so
   `:free` gemma/gemini route through OUR rate limits instead of the shared throttled pool. We
   already hold GEMINI_API_KEY / GEMINI_API_KEY2 — but those are also used by YouTube video
   transcription (item G), so vision would compete for the same Gemini free quota. Paid flash-lite
   avoids that contention.
3. Then flip `config/consensus.yaml` `wolf.vision.enabled: true`, restart `consensus-engine`.
   The item-F gate requires `.claude/go-live-evidence/wolf_vision_enabled.md` + the smoke test
   (which now WILL pass via the paid reader).

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
