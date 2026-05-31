# Autonomous kickoff — TODO #20 (Wolf newsletter → trade-finding macro brain)

You are building TODO #20. The research/requirements phase is **DONE** — do NOT re-interview the user. Read the spec, build it, live-test it. Stop only for the gates at the bottom.

## Source of truth — read first, assume nothing
- `todo/wolf-macro-brain.md` — the full spec + all requirements (interview rounds 1–6). Non-negotiable.
- Memory: `project_gmail_wolf_connected.md` (connection state) + `project_wolf_macro_brain_direction.md` (requirements).
- `CLAUDE.md` — Definition of Done, Regression Gate, Alert Philosophy, Real-World Testing ladder, shared-file tripwire.
- The current (inadequate) reader: `consensus_engine/scanners/gmail_watcher.py`. Understand WHY it can't handle these emails (HTML-only, remote chart images) before rewriting.

## Operating principles (user directive — non-negotiable)
1. **Verify, don't assume.** No assumptions — confirm with **live, real-world tests** that things work in real scenarios (real Wolf emails, real chart images, real test-channel posts). When something looks blocked, **assume you CAN do it** and work from there: diagnose → fix → alternative path (CLAUDE.md real-world-testing ladder) before ever concluding it's impossible.
2. **Found a better way → take it.** If a cleaner/better approach emerges mid-build, use it. The mechanics in the spec are a floor, not a ceiling.
3. **Thought of a new improvement → build it.** New ideas that make the feature better are in-scope; add them.

(Autonomy on *how* to build — but the stop gates at the bottom still hold: sign-off before any LIVE post or enabling in prod, and surface genuine ambiguity.)

## The connection is already done — don't redo OAuth
Gmail is connected: `teche2014@gmail.com`, token at `/root/.openclaw/gmail/token.json` (auto-refresh, scope `gmail.modify`). `config/consensus.yaml gmail_watcher` is wired but `enabled: false`. To pull sample emails/charts for dev, reuse the token (see `/root/.openclaw/gmail/oauth_connect.py` and the read snippets referenced in the detail file).

## Step 0 — baseline before any code (Regression Gate)
1. `consensus-engine.service` + `openclaw-gateway.service` both `active`.
2. `/root/.openclaw` resolves to `/home/openclaw/.openclaw`.
3. `make test-baseline` (or read `.test-baseline`). No commit may turn a green test red.

## Plan before code
This is a large, multi-phase feature. Write a short implementation plan (phases × user-observable outcome × verification) and save it to `.omc/plans/` before writing code. Build in the spec's "next steps" order: **reader → state → confluence → alerts/digests → backfill → (later) !all integration.** One *verified* phase beats three half-built ones.

## Build discipline (every phase)
- Name the user-observable outcome FIRST ("a #news post summarizes the nightly Wrap with levels + who agrees", not "extraction works").
- **Real-world test against REAL Wolf emails** from the inbox and show the actual output (text read + chart read). "Unit tests pass" / "service started" does NOT discharge verification (Evidence Standard).
- Vision: read the remote chart images with a vision model (Gemini flash — see `reference_gemini_video_models`; mind the free-tier per-key/day limits, batch/cap). Skip the SendGrid tracking pixel.
- Keep the regex symbol scan; add the LLM structured extraction on top.
- **Shared-file tripwire:** `config/consensus.yaml`, `gmail_watcher.py`, `main.py`, `llm_client.py`, `db.py` — touch any, test every feature that uses it.
- After every restart: both services `active`, no `GATEWAY drift`, no LLM-health failure, symlink intact.

## Hard requirements not to lose (from the spec — see detail file for full detail)
- Output = directional lean + key level, watchlists, sector-rotation calls (NOT entry/stop/target).
- Stateful thesis tracking through stages (forming → divergences → imminent/acting); active until price invalidates.
- Confluence vs 14 YouTube channels + options flow + Twitter + SEC; tiers Wolf=surface, +1=high, +2=critical; tag + dedicated alert; ~2–3wk agreement window; surface disagreement; equal weighting for now; match at market/sector/stock/asset-class level.
- Proactive #news alerts at every stage + level breaks; @-ping critical ANYTIME (incl. overnight).
- Beneficiary inference for BIG catalysts only; catalysts only from what Wolf says.
- Backfill ALL available Gmail history to seed state.
- Digests (Pacific): event-triggered midday + nightly (Wrap window 7pm–2am PT) + Sunday 10am + Sunday add-on; quiet day = no digest; weekly recap tracks outcomes.
- Keep general (no user positions). New #news lane first; `!all` integration later.

## Git
- Commit locally after each functional change (imperative messages). Do NOT push mid-session. Push + full gate at session close ("bye").

## Update the TODO as you go
- Append dated progress notes to `todo/wolf-macro-brain.md` (commit hash + the live-verified outcome per phase). Keep #20 OPEN until the core #news lane is live-verified.

## Stop ONLY for these gates
1. **Before anything posts to a LIVE Discord channel the user sees, or before flipping `enabled: true` in production.** This bot fires real trade alerts — show a dry-run / sample output and get sign-off first. (Creating the #news channel + first live post = a gate.)
2. An external source/key genuinely blocked from this VPS after the diagnose → fix → alternative-path ladder (e.g. Gemini vision quota) — report what you tried + a recommendation.
3. A genuine ambiguity not resolvable from the spec, the code, or sensible defaults — surface the options, don't pick silently.

Anything else — keep going.
