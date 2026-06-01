# Pass 3 — Adversarial Stress Test + Live Feasibility (wolf-news-brain)

## Step 0 — LIVE vision feasibility probe (the load-bearing gate) — **PASSED**

Ran `_vision_probe.py` against REAL Wolf charts at `/tmp/wolf_charts/` using native `google.genai` + `from_bytes`:
- **e01_2.jpg** → `gemini-flash-latest` succeeded: `{instrument: QQQ, direction: bearish, levels:[{price:737.57,conf:0.95},{price:735.5,role:support,conf:0.8}], patterns:[bearish divergence], indicators:[{name:"3C orange",reading:"divergence"}]}`.
- **e01_1.jpg** → `gemini-flash-latest` returned **503 (high demand)**; **fallback `gemini-2.5-flash` succeeded**: `{instrument: QQQ, 3C orange: "strong/so-so/divergence", caption: rally off March low with 3C divergence}`.

**Verdict:** Gemini reliably extracts instrument + direction + price levels + the proprietary 3C divergence labels from the real hand-annotated charts. The feature's core premise (charts carry the signal; vision can read them) is **validated on real data**. The 503 confirms the **multi-model fallback (flash-latest → 2.5-flash → flash-lite) is mandatory**, not optional. Caveats to carry into the build: digit-accuracy guard (validate levels vs recent price ±~30%), confidence-gate (<0.7 → null), one chart per call.

## Step 1 — Local adversarial review

### Critic (opus) — 3 CRITICAL, 5 Major, 4 Minor. Adopted revisions:

**CRITICAL (block the naive build):**
- **C-1 Separate lane.** The old watcher's only output seam `db.insert_signal → ticker_signals` is counted by `get_active_tickers` (any source, 2h TTL) which drives the live #chat alert loop AND `!all` discovery. Reusing it = Wolf's *commentary* fires real per-ticker alerts + pollutes consensus scoring + double-alerts. **→ Wolf writes ONLY to new tables; the #news lane reads from those. Nothing Wolf touches `ticker_signals` in phase 1.** (If phase-2 !all needs it: a new `WOLF_MACRO` source_type explicitly excluded from `get_active_tickers`/`get_social_signals`, with a test.)
- **C-2 Weekend pause.** `_is_weekend_pause` (main.py:95-104) pauses the whole scanner stack Fri 3pm ET → Sun 2pm ET via `combined_stop`. But the spec needs overnight Wrap alerts (~3am ET, incl. Sat/Sun) and the Sunday 10am PT (=1pm ET, inside pause) recap. **→ The Wolf watcher + digest scheduler run on `stop_event` (shutdown only), NOT `combined_stop`.** Add a test that the Wolf loop is alive on a simulated Saturday.
- **C-3 contradiction_index is LIVE, not dormant.** It IS populated on `CrossReferenceResult` and consumed in main.py:1070/1133 for the production STRONG→WATCHLIST gate (Pass-0 map was wrong — the grep was 0 only because the value is assembled off-file). **→ Confluence computes its OWN agreement value into NEW tables; never reads/overwrites the existing `contradiction_index`.**

**Major (explicit decisions adopted):**
- **M-1** Pure-monotonic stages contradict "active until invalidated *or Wolf drops it*" and Wolf de-escalating. **→ Allow downgrade; model "Wolf drops it" as an explicit invalidate-and-close with audit, not a frozen max-stage.**
- **M-2** Invalidation can never fire if no level was extracted (the known vision weak point) → a never-dying thesis manufacturing confluence. **→ Level-less theses are capped to *surface* tier (no @-ping, no confluence vote) and get a short auto-expiry; the recap flag is a report, not a control.**
- **M-3** Crowding ≠ independence: 14 YouTubers echo each other; worse, a source *quoting Wolf* would count as independent agreement ("bot agreeing with itself"). **→ Wolf-echo filter (drop stances referencing Wolf/the newsletter) + cap YouTube to one video-cluster vote (reuse A3 cluster model).**
- **M-4** Equal-weighting a 1-line tweet vs a 40-min analysis + a 21-day window hides fast regime change. **→ Recency decay across the window + require ≥1 non-Wolf *level-bearing* stance before promoting to high/critical; critical @-ping requires a non-Wolf corroborator. Equal-weighting kept as a stated, conscious risk.**
- **M-5** Scope cross-counting is named but undefined. **→ Write the explicit scope-match matrix (identifier→scope rollup; market-vs-stock/sector/asset cross rules; worked examples) BEFORE coding confluence.**

**Minor (pre-build chores):** `.test-baseline` is EMPTY → run `make test-baseline` + commit first. `subject_substrings` gate + DKIM/SPF/DMARC-all-pass may DROP Wolf Wraps (SendGrid-relayed) → verify against a real email; detect "the Wrap" by chart-count/size, not a subject keyword.

### Security-reviewer (sonnet) — 1 Critical, 2 High, 3 Med, 1 Low. Adopted mitigations:
- **CRITICAL (prompt injection):** email/chart text is attacker-influenceable; extracted JSON drives alerts + the @-ping. **→ Treat extraction as DATA: clamp enums (direction/stage), ticker regex `^[A-Z\^]{1,10}$`, level range + confidence≥0.7, anti-injection clause in the prompt, and NEVER build a Discord mention/content string from raw email text — only from validated enum/allowlisted fields.**
- **HIGH (SSRF):** image fetch must be network-guarded: **https-only, host allowlist (newsletter CDN), `allow_redirects=False`, 10MB cap, reject private/loopback/link-local IPs.**
- **HIGH (@-ping DoS):** **separate critical-ping rate limit ≤3/hr, batch overflow into the next digest** (independent of the 20/hr email cap).
- **MED/LOW:** tighten DKIM/SPF/DMARC to word-boundary regex; `chmod 600 credentials.json` (currently 0644); keep new tables on the hardcoded migration lists + parameterized SQL; new env vars in BOTH `.env` and `.env.service`, then `chown openclaw:openclaw` + `chmod 600`.

## Step 2 — Cross-model synthesis
**Adaptation (noted):** the discover skill's Pass-3 `ccg` step is **consolidated into the user-mandated codex adversarial review of the Pass-4 PLAN** at the Pass 4→5 gate. Reason: the user explicitly asked to "send the plan to codex for an adversarial review" before execution; running ccg on the feature set here AND codex on the plan there is redundant cross-model spend. The codex review will cover the keep/drop/hidden-risk questions on the concrete plan (a stronger artifact than the feature list). The local critic+security already provided deep adversarial coverage this pass. Degradation vs the full skill: one fewer Gemini opinion on the feature set — acceptable given Gemini already served as the live vision model and the codex pass remains.

## Realistic edge (what this actually improves, concretely)
- The bot **never forgets a Wolf thesis** and resurfaces it at the right stage/level-break — a memory + timing edge, not a prediction edge (Wolf hedges; we don't out-predict him).
- **Confluence** turns "Wolf says top" into "Wolf + 2 independent, level-bearing, non-echo sources say top" → a genuinely louder, better-timed signal; and surfaces *disagreement* as its own risk flag.
- **Chart levels become machine-usable** (validated live) → level-break alerts the user would otherwise eyeball across 40 charts.

## Explicit limitations (what it does NOT solve)
- Not a predictor; equal-weighting means a thin source can still tip a tier (mitigated by the level-bearing + non-echo requirement, not eliminated).
- Backfill seeds thesis *state*, not historical *confluence* (no contemporaneous source pool 21 days back).
- Vision can still misread a level (guarded by confidence + price-range validation, not perfect).
- Free Gemini tier under burst → some charts may be skipped (graceful degrade to text-only caption).

## Net: design is sound, NOT build-ready as originally written.
The 3 Criticals + security Critical are now folded into the plan requirements. Proceed to Pass 4 (build plan) → codex adversarial review → revise → build.
