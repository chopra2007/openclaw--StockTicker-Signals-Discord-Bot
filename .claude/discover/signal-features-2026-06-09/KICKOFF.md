# Discover run kickoff — signal-features-2026-06-09

This file is read by a fresh Claude Code session that was started with the trigger:
`discover: run the stock-bot feature research — read .claude/discover/signal-features-2026-06-09/KICKOFF.md`

## What this run is
Feature research + build for the signal-first stock alert engine at
`/home/openclaw/.openclaw/workspace`. Goal: precision over recall (2 great alerts > 15
mediocre), free/near-free data, catch setups before mainstream news / r/wallstreetbets.

## The spec that drives Passes 1–2
`/home/openclaw/.openclaw/workspace/feature-research-prompt.md` is the driver. Its audit
targets, research angles, "care about / reject" lists, and output contract define scope.
- **Pass 0 (existing-system map):** read the files that spec's STEP 0 names
  (`consensus_engine/scanners/`, `consensus_engine/analysis/`, `cross_reference.py`,
  `alerts/discord.py`, the scoring block + the verified knobs in `config/consensus.yaml`).
- **Pass 1–2 (research):** use the spec's STEP 2 research angles.

## CRITICAL — research engine (USER OVERRIDE of discover's defaults)
The `discover` skill's built-in Pass 1 recipe uses `external-context` + `sciomc`. The user
has explicitly overridden that: **for the external-research pass, REPLACE
`external-context`/`sciomc` with the `deep-research` skill** (fan-out → fetch →
adversarially verify each claim → cite). Use `deep-research` as the engine; do NOT fall
back to the lighter built-in sweep, and do NOT run both. This override is the whole reason
the user chose this approach — it enforces the spec's "no inventing, every claim gets a
real URL" rule. If `deep-research` is somehow unavailable, STOP and tell the user rather
than silently substituting external-context.

Per skill rules, explicit user instructions outrank skill defaults — so honor this.

## Live research tools (verified 2026-06-09 — RE-PROBE before relying, caps reset monthly)
- ✅ **Tavily** — primary for landscape sweeps.
- ✅ **Brave key #1** — breadth + fresh news. (Key #2 is capped — do NOT use.)
- ✅ **Firecrawl** (~1,300 credits) — deep-read the best 10–20 sources (GitHub/Substack/docs).
- ⚠️ **SerpAPI** — only ~160 Google searches left this month. **Main thread only, sparingly.**
  Keep parallel research agents OFF SerpAPI so they don't exhaust it.
- ❌ **Exa AI** — OUT OF CREDITS, do not call. ❌ **Brave key #2** — capped, do not call.

## Recommended setup answers (the skill WILL ask these — confirm or adjust)
- **Run name:** `signal-features-2026-06-09`
- **Mode (Passes 1–4):** autonomous — research + plan without pausing each pass.
- **Execution handoff:** `review-then-build` — pause after the plan (Pass 4) so the user
  approves before any code is written, then build in this same session.
- **Layout:** native (tmux is installed if you prefer panes; native is simpler).
- **Agent count:** 4 (research-heavy, but keep token + search budget in check).

## Notes for Pass 5 (build)
- Git remote exists (`chopra2007/openclaw--StockTicker-Signals-Discord-Bot`) — push allowed.
- This repo's `isolation="worktree"` is BROKEN (the `/root/.openclaw` symlink) — dispatch
  agents sequentially or without worktree isolation, never with it.
- Respect the regression gate: establish a baseline, no passing test may start failing.
- New user-facing features should land flag-OFF unless the user signs off live.
