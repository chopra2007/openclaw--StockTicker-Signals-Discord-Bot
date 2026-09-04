# Finish the feature-idea sweep, reusing the already-saved codebase map

**Status:** OPEN — 13 of 14 switch decisions are resolved; only the NFCI score decision remains.
**Created:** 2026-07-06

**CURRENT STATUS (2026-09-04):** 13 of 14 decisions are resolved and live. The short-interest score
bump is intentionally off for good; a display-only squeeze tag is on instead. NFCI appears in plain
language, while its score multiplier remains off. The live database has four distinct weekly NFCI
readings, from 2026-08-07 through 2026-08-28, against the required 12. It has 1,132 general
measurement candidates, but zero can count toward the required 100 near-cutoff candidates because
the records still do not store each candidate's effective cutoff, complete inputs and weights, and
point-in-time NFCI value and date. Keep collecting; do not weaken or decide the score gate early.

**PREVIOUS STATUS (2026-08-16):** **User: "flip all switches live except for 11 and 14."** Flipped 12 of the
14 pending switches ON in `config/consensus.yaml`: `sources_denominator`, `trading_halts`, `skew_index`,
`pead`, `market_breadth`, `sweep`, `vvix_residual`, `dealer_gamma`, `iv_skew`, `oi_pinning`, `iv_rv_tag`,
`vol_squeeze`. Held back `cross_asset.nfci_leg_enabled` and `short_interest.enabled` per the explicit
exception — both are score-touching, not display-only. Full regression suite against the flipped config:
**3318 passed, 10 skipped, 0 failed.** Deployed to the live checkout (file-copy, since this session can't
`git pull` the shared checkout directly) and restarted `consensus-engine.service`. **Verified live on the
real bot, not just tests:** `!all NVDA` renders Vol Read, Squeeze, Dealer Gamma, IV Skew, OI Pinning,
SKEW, and the "Sources: N of M attempted" footer; `!market` renders Market breadth and the VVIX
fear-of-fear gauge; `!sweep` returned a real ranked list across 10 tickers (this also confirms the
`!scan`/`!sweep` crash fix from the same session holds under load — see below). **Two caveats flagged
for the record, not silently rolled in:** `pead.enabled`'s own config comment says it feeds "a small
capped confluence leg", not pure display like the other 11 — flipped anyway per the broad instruction.
`trading_halts.enabled` is a genuinely new live alert type (fires to the alerts channel on a real
Nasdaq/NYSE halt), not just a card addition. PR: `worktree-federated-humming-pnueli` → master (#33).

**Separate same-session finding, not part of this item but affecting it:** discovered and fixed a
LIVE PRODUCTION BUG — `!scan` and `!sweep` were both crashing on every call (`trade direction must be
'long' or 'short'`), broken since 2026-08-11 by an unrelated measurement-ledger change that never
accounted for the NEUTRAL-direction fake tweet `!scan`/`!sweep` both use by design. Confirmed crashing
live in the engine log before the fix, confirmed working after. Root cause + fix:
`consensus_engine/cross_reference.py`'s `build_score_cache_key` call now normalizes any non-long/short
direction to "long" for the cache-key only — the real `direction` passed to scoring is untouched. Merged
via PR #32 and deployed live the same way (file-copy + restart) before any switch was flipped, since
`!sweep` couldn't have been verified while it was broken.

**PREVIOUS STATUS (2026-07-14):** **3 more switches added to this list, from the #76 feature-menu build
(run `menu-top10`).** They are display-only, cannot touch an alert or a score, and each was proved on
real data before commit — so they are the *safest* flips on the whole list:

| Switch | What flipping it does, in one line | Risk |
|---|---|---|
| `features.sources_denominator.enabled` | The `!all` footer stops saying `Sources: 21` and starts saying **`Sources: 21 of 27 attempted`** — you can finally tell "4 of 5 sources agreed" from "4 of 27". | None. Display text only. OFF is byte-identical to today. |
| `features.vvix_residual.enabled` | Adds one line to `!market`: the **VVIX "fear-of-fear"** read — is the market nervous about its own nervousness, beyond what the VIX already explains. (`collect: true` is ALREADY ON and quietly filling `vol_of_vol_daily`, so the history is there the day you flip this.) | None to alerts. A test forbids the scorer from ever reading it, so it cannot become the VIX predictor rejected in #47. |
| `features.sweep.enabled` | Turns on the **`!sweep`** command (alias `!universe`): scores your whole watchlist on demand and posts one ranked list. Does not change any existing command. | Low. It is read-only and never alerts. Note it spends the same API budget the live alerts use (it runs the real `!scan` path per ticker), hence the 15-ticker / 3-at-a-time caps. |

**Flipping any of these needs an engine restart to take effect** (`systemctl restart consensus-engine.service`) — the engine reads config at startup.

**CURRENT STATUS (2026-07-08):** **All 6 stages BUILT + VERIFIED + COMMITTED** (Stages 2–6 ran autonomously this session). 16 features shipped, every one behind a config flag **DEFAULT OFF** (shadow) — **no live alert, score, or !all/!market/!sec output changed** (proven byte-identical on both live-scoring surfaces: E2 `cross_asset.get_multiplier` and `cross_reference.score_ticker`). Stage commits (local, unpushed until this close): S2 `e74eb19` (NFCI + FRED macro legs), S3 `f057e23` (dealer-GEX/gamma-flip/IV-skew/OI-pinning + ^SKEW), S4 `1023bdf` (IV-vs-RV + squeeze), S5 `d240257` (short-interest/PEAD/breadth), S6 `931e272` (Form 144/10b5-1/House congress). Each stage: live-probe on real data + full regression (final **2785 passed, 0 regressions**) + ownership fix + per-stage commit; implementer (executor agents) separate from verifier (me). **Go-live NOT done — that's a separate, explicit, per-feature user decision gated on shadow evidence.** Owed follow-ups (in `.claude/discover/next-features-jul2026/outcome.json`): r13-Senate congress (efdsearch gated), r20 true advancers/decliners upgrade (shipped RSP/SPY proxy), and wiring the Stage-6 insider context lines onto the live !sec/!all surfaces (a go-live step after shadow data accrues). 3 ideas killed (max-pain-label/dark-pool/0DTE-directional); 8 kept ideas not built this run (VVIX/VIX, 0-100 score, crowding guard, market put/call, CFTC, GDELT, analyst-PT-disagreement, !scan) remain future candidates.

**CURRENT STATUS (2026-07-07) — sweep DONE, awaiting the user's build pick.** The prerequisite was
built this session: discover **1.2.1** adds the missing `from_pass=1` resume path (reuse the saved
Pass-0 map, then run Research+Filter fresh) — committed locally at `e010f53` on
`/root/work/claude-discover-publish/repo`, push/tag/cache-refresh **pending user OK**. The Deep
`from_pass:1→2` sweep then ran clean on the reused map (run `wf_637ddefe-a4a`, 39 agents, 0 errors,
~2.05M tokens, ~54 min) and produced the deliverable: **40 viable, code-grounded ideas** + ~106
screened-out (with reasons) + a full VVIX/VIX feasibility study. Artifacts in the run dir:
`pass-2-filtered.md` (top-7 build-ready shortlist), `feature-ideas-list.txt` + `discovery-sweep-work.md`
(full 40-idea menu), `VVIX-RESEARCH-FINDINGS.md`, `drops-log.md`. User-chosen continuation settings
(saved in `state.json`): model_tier=**max**, after_plan=**build**, pause after the shortlist. Next:
user reviews the menu and says which idea(s) to carry into kill-test → plan → build (or stop with the
menu as the deliverable). Menu presented at the checkpoint 2026-07-07.

## Goal

Complete the discover feature-idea-sweep run named `next-features-jul2026` — generating a broad,
creative menu of 10-30 candidate feature ideas for the bot — but reuse the system map (the
codebase overview) that's already saved to disk instead of re-scanning the codebase from scratch.

## Prerequisite — check before starting

This requires the discover plugin (repo: `chopra2007/claude-discover`, installed at the plugins
marketplace/cache locations) to support a `from_pass=1` resume path — one that reparses the saved
`pass-0-system-map.md` from disk (same mechanism the script already uses for `from_pass=3/4`) and
then runs Pass 1 (research) and Pass 2 (filter) fresh from there, skipping Pass 0 entirely.

As of this writing, that resume path does **not** exist in the script yet — it's planned to be
added in a separate session before this item is picked up. **Verify it exists first** (grep the
script for `from_pass === 1`) before launching this. If it's still missing, that addition needs to
happen before this item can run.

## Map file to reuse (already verified accurate — do not regenerate)

`/home/openclaw/.openclaw/workspace/.claude/discover/next-features-jul2026/pass-0-system-map.md`

## Run directory

`/home/openclaw/.openclaw/workspace/.claude/discover/next-features-jul2026`

## Launch settings

- dial: `deep`
- run_style: `checkpoints`
- from_pass: `1`, to_pass: `2`
- greenfield: `false`
- capabilities: `{omc: true, superpowers: true, codex: "healthy", gemini: "healthy"}`
- budget_override: `null`
- free_data_only: `true`

## Exact feature_ask to pass verbatim

Broad feature-discovery sweep across the whole trading-signal Discord bot (consensus_engine).
Looking at the TODO list and the last 24h of commits (mostly #57 Schwab options shadow-compare,
#63 decision-first alerts, #64 Wolf newsletter verifier rebuild, #65/#66 dedup+idempotency+DB
pruning), generate a wide, creative menu of things that could be worked on next - big or small:
refactors/improvements to features that already work, sub-features that extend a shipped feature,
and brand-new feature ideas. Think outside the box. Do NOT converge to just 1-2 ideas - the
deliverable IS the breadth of the list; the user explicitly wants 10-30 candidate ideas surfaced,
not narrowed early.

Specifically encouraged: composite/confluence ideas that combine multiple existing signals into
one higher-conviction read - e.g. Expected Move (the !em command, expected_move.py) + max-pain
(options.py) + supply/demand zones + smart chart levels + options-flow imbalances, combined into
'high-probability zones of interest' for long/short setups. This pattern - combine several
individually-noisy signals into one clearer picture - is exactly the kind of idea being sought,
not just single-signal tweaks.

User-supplied lead to research explicitly: VVIX relative strength vs VIX (volatility-of-volatility
vs volatility - e.g. CBOE ^VVIX/^VIX ratio or its trend) as a candidate input into that same
combined-zones/confluence approach, alongside EM, max-pain, and more. IMPORTANT CONTEXT: a pure
VIX-level-based market top/bottom PREDICTOR was already researched this repo and found NO-GO on
free daily data (see TODO #47 / vol-indicator-accuracy-research - proven no statistical edge
across 5+ rigorous phases). VVIX/VIX relative strength is a DIFFERENT angle (a volatility
term-structure / 'fear-of-fear' regime signal, not a standalone top/bottom caller) proposed as one
descriptive input alongside EM/max-pain/etc., not a revival of the already-rejected predictor -
research whether it is genuinely additive (free data availability via yfinance ^VVIX, and whether
it's actually independent of signals already feeding the score) rather than auto-rejecting it as
'already tried' or auto-accepting it without checking for overlap.

Free/public data sources only. Read the actual current code for all named features before
proposing changes to them (expected_move.py, options.py max-pain + unusual-flow, the smart-levels
engine, wolf_beneficiaries.py, insider_display.py, etc.) - this repo has ~500 Python files and a
long feature history (66 TODO items), so redundancy-checking against what's already shipped
matters more here than usual.

## Next steps, priority-ordered

1. Confirm the discover plugin has a working `from_pass=1` resume path (see Prerequisite above).
2. Launch the burst with the settings above.
3. Once Pass 1-2 complete: present the full ranked idea list to the user for checkpoint review —
   that list is the deliverable.
4. Ask the user whether to stop there or continue to Pass 3 (kill-test) + Pass 4 (plan) for the
   top picks.

## Files / code involved

- `chopra2007/claude-discover` — `workflows/discover-pipeline.js` (the resume-path prerequisite)
- `.claude/discover/next-features-jul2026/` — run directory, existing map file, state.json

## Open questions

- None — this item is fully specified and ready to execute once the prerequisite is confirmed.

---

## Session notes — 2026-07-07 (pipeline complete through Stage 1; Stages 2-6 queued autonomous)

Resumed the run and took it all the way through the plan + first build stage.

- **Passes 1-4 done.** Pass 1-2 (fresh, uncontaminated) yielded 113 candidates → 7 kept + 76 below-cut + 6 already-built. User wanted them ALL considered, so I triaged the full 113 to **34 with merit** (`merit-triage.md`), and user picked the **strong 27** for a custom batched kill-test (`killtest-27.workflow.js`, 4 waves × 2 skeptics + advocate/judge + Codex audit): **24 survived, 3 killed** (max-pain-label [was in the original top-7 — Pass-2 misread the code], dark-pool [2-5wk stale], 0DTE-directional [needs aggressor data free feeds lack]). Report: `pass-3-killtest-report.md`.
- **Plan:** user chose the **16 strongest** survivors → clustered by integration point, planned against real code by 5 parallel planners + a sequencer → `final-plan.md` (6-stage build order, shared-file tripwires, byte-identical rules). Planners caught the GEX "reuse the chain" premise was false and corrected the design.
- **Stage 1 SHIPPED + committed** (`f2b0b7d`, local): r14 trading-halt tripwire (full) + r8 ^SKEW module (module only), both flags OFF. Independent verification caught a real redirect bug (http→https feed URL the hardened fetch refused) that green unit tests missed — fixed, re-proven live (60 halts). Full suite 2655 pass, 0 regressions. Ownership trap handled (root→openclaw chown). Log: `pass-5-stage1.md`.
- **Stages 2-6 (14 features) queued to run AUTONOMOUSLY** next session: same one-line trigger `discover: build next-features-jul2026`. Mode + rules + confirmed data recipes in `todo/kickoffs/discover-next-features-resume.md`. Everything ships OFF; go-live is a separate later decision.
- **Both deferrals solved this session** (user pushed to go to primary sources): House congress via `disclosures-clerk.house.gov` (PTR PDFs machine-readable via pdfplumber), market breadth via RSP/SPY equal-weight proxy. Only **Senate congress** remains deferred (efdsearch.senate.gov gated).

### Session notes — 2026-07-14 (3 switches added from the #76 build)
- **Why here:** the user asked that every built-but-off switch live in ONE place they can approve from.
  This item already held the July sweep's 16; the `menu-top10` run's 3 were added to the same
  `**Switches:**` line rather than starting a second list. **Any future session that builds a flag-OFF
  feature registers its switch HERE, whatever item it was built under.**
- **Added:** `features.sources_denominator.enabled` · `features.vvix_residual.enabled` ·
  `features.sweep.enabled` (plus `features.vvix_residual.collect`, already ON and collecting).
- **Count is now 14 pending** (was 11 live-resolved; the header had said a stale "8").
  `python3 scripts/todo_switch_state.py` is the source of truth, not the prose.
- **Nothing was flipped this session.** All 3 are display-only and were proved on real data, so they are
  the lowest-risk flips on the list — but the flip is the user's call, and it needs an engine restart.

### Session notes — 2026-08-17
- **Worked on:** Replaced the short-interest score proposal with a live squeeze tag, added the live NFCI note, measured the stored decision history, and verified both displays in Discord.
- **Decisions:** The short-interest score bump stays off for good. The NFCI score multiplier stays off because the stored records cannot reproduce a valid before-and-after decision.
- **Next:** Record complete per-candidate score inputs, weights, cutoff, timestamp, and NFCI value/date; then collect at least 12 weekly readings and 100 near-cutoff candidates before deciding the NFCI score multiplier.

### Session notes — 2026-09-04

- **Worked on:** Refreshed the NFCI gate from the live database only. No feature, score, alert, or switch changed.
- **Proof:** Four of 12 required weekly readings exist. The candidate table has 1,132 rows, but its record shape has no effective cutoff or point-in-time NFCI fields, so zero rows meet the complete near-cutoff proof requirement.
- **Next:** Add the already-recorded missing candidate fields through its own future build, then wait for 12 readings and 100 complete near-cutoff candidates. Do not weaken the gate.
